from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import random
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import httpx
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from config import settings
from database import (
    Payment,
    User,
    get_db,
    topup_credits_from_payment_atomic,
)

router = APIRouter(prefix="/billing/v1", tags=["Billing"])

templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)


class CreateCheckoutRequest(BaseModel):
    package_code: str


def compute_payos_signature(data: dict[str, Any], checksum_key: str) -> str:
    """
    Tính chữ ký HMAC-SHA256 chuẩn của PayOS:
    Sắp xếp các key của `data` theo thứ tự bảng chữ cái: `key1=val1&key2=val2...`
    """
    sorted_parts: list[str] = []
    for k in sorted(data.keys()):
        v = data[k]
        if v is None or v in ("null", "undefined"):
            val_str = ""
        elif isinstance(v, (dict, list)):
            val_str = json.dumps(v, separators=(",", ":"), ensure_ascii=False)
        else:
            val_str = str(v)
        sorted_parts.append(f"{k}={val_str}")
    payload_str = "&".join(sorted_parts)
    return hmac.new(
        checksum_key.encode("utf-8"),
        payload_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_payos_webhook_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Xác thực chữ ký Webhook PayOS bằng HMAC-SHA256 chuẩn của PayOS (không phụ thuộc cứng vào SDK ngoài,
    nhưng hoàn toàn tương thích định dạng `{code, desc, success, data: {...}, signature: "..."}` của PayOS).
    Ném ValueError nếu chữ ký sai hoặc thiếu dữ liệu.
    """
    if not isinstance(payload, dict):
        raise ValueError("Payload webhook không hợp lệ.")

    data = payload.get("data")
    signature = str(payload.get("signature") or "").strip()
    if not isinstance(data, dict) or not signature:
        raise ValueError("Thiếu trường data hoặc signature trong webhook PayOS.")

    checksum_key = (settings.PAYOS_CHECKSUM_KEY or "").strip()
    if not checksum_key:
        raise ValueError("Server chưa cấu hình PAYOS_CHECKSUM_KEY.")

    expected_sig = compute_payos_signature(data, checksum_key)
    if not hmac.compare_digest(expected_sig.lower(), signature.lower()):
        raise ValueError("Chữ ký webhook PayOS không hợp lệ.")

    return data


def _generate_unique_order_code(db: Session) -> int:
    for _ in range(10):
        base = int(datetime.now(timezone.utc).timestamp() * 1000) % 900_000_000_000
        code = base + random.randint(100, 999)
        exists = db.query(Payment).filter(Payment.order_code == code).first()
        if not exists:
            return code
    raise RuntimeError("Không thể sinh mã đơn hàng duy nhất.")


async def _create_payos_payment_link(
    order_code: int,
    amount_vnd: int,
    description: str,
    return_url: str,
    cancel_url: str,
) -> dict[str, Any]:
    """Gọi API PayOS tạo link thanh toán (hoặc trả link giả lập khi chạy dev chưa cấu hình key)."""
    if not (settings.PAYOS_CLIENT_ID and settings.PAYOS_API_KEY and settings.PAYOS_CHECKSUM_KEY):
        return {
            "checkoutUrl": f"{return_url}?orderCode={order_code}&status=PAID",
            "paymentLinkId": f"dev_link_{order_code}",
        }

    sign_data = {
        "amount": amount_vnd,
        "cancelUrl": cancel_url,
        "description": description[:25],
        "orderCode": order_code,
        "returnUrl": return_url,
    }
    signature = compute_payos_signature(sign_data, settings.PAYOS_CHECKSUM_KEY)
    body = {**sign_data, "signature": signature}
    headers = {
        "x-client-id": settings.PAYOS_CLIENT_ID,
        "x-api-key": settings.PAYOS_API_KEY,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://api-merchant.payos.vn/v2/payment-requests",
            json=body,
            headers=headers,
        )
        resp.raise_for_status()
        resp_json = resp.json()
        data = resp_json.get("data") or {}
        return {
            "checkoutUrl": data.get("checkoutUrl") or "",
            "paymentLinkId": data.get("paymentLinkId") or "",
        }


@router.get("/packages")
async def list_packages():
    """Trả danh sách gói nạp đọc từ cấu hình (`settings.get_topup_packages()`)."""
    packages_map = settings.get_topup_packages()
    packages = []
    for code, item in packages_map.items():
        packages.append(
            {
                "package_code": code,
                "title": item.get("title", code),
                "amount_vnd": int(item["amount_vnd"]),
                "credits": int(item["credits"]),
                "tier": item.get("tier", "Basic"),
            }
        )
    return {"packages": packages}


@router.post("/payos/checkout")
async def create_payos_checkout(
    req: CreateCheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    packages_map = settings.get_topup_packages()
    pkg = packages_map.get(req.package_code)
    if not pkg:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mã gói nạp không hợp lệ.",
        )

    order_code = _generate_unique_order_code(db)
    amount_vnd = int(pkg["amount_vnd"])
    credits = int(pkg["credits"])

    payment = Payment(
        user_id=current_user.id,
        provider="payos",
        package_code=req.package_code,
        order_code=order_code,
        amount_vnd=amount_vnd,
        credits=credits,
        status="pending",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    try:
        link_info = await _create_payos_payment_link(
            order_code=order_code,
            amount_vnd=amount_vnd,
            description=f"CTVN {order_code}"[:25],
            return_url=settings.PAYOS_RETURN_URL,
            cancel_url=settings.PAYOS_CANCEL_URL,
        )
        payment.checkout_url = link_info.get("checkoutUrl") or None
        payment.payment_link_id = link_info.get("paymentLinkId") or None
        payment.raw_response = json.dumps(link_info, ensure_ascii=False)
        db.commit()
    except Exception as exc:
        payment.status = "failed"
        payment.raw_response = str(exc)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Không thể khởi tạo giao dịch PayOS.",
        ) from exc

    return {
        "order_code": payment.order_code,
        "amount_vnd": payment.amount_vnd,
        "credits": payment.credits,
        "checkout_url": payment.checkout_url,
        "status": payment.status,
    }


@router.post("/payos/webhook")
async def payos_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Xử lý Webhook PayOS:
    1. Xác thực chữ ký HMAC-SHA256 (`verify_payos_webhook_payload`).
    2. Đối chiếu `orderCode` và `amount == payment.amount_vnd`.
    3. Cộng credit nguyên tử và idempotent (`topup_credits_from_payment_atomic`) + ghi `CreditLedger`.
       Gọi lặp lại 3 lần cho cùng 1 `order_code` chỉ cộng credit đúng 1 lần.
    """
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="JSON webhook không hợp lệ.",
        ) from exc

    try:
        verified_data = verify_payos_webhook_payload(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    order_code = verified_data.get("orderCode")
    amount = verified_data.get("amount")
    code = str(verified_data.get("code") or payload.get("code") or "")

    if order_code is None:
        return {"ok": True, "ignored": "missing_order_code"}

    payment = db.query(Payment).filter(Payment.order_code == int(order_code)).first()
    if not payment:
        return {"ok": True, "ignored": "order_not_found"}

    if amount is not None and int(amount) != int(payment.amount_vnd):
        payment.status = "failed"
        payment.raw_response = json.dumps(verified_data, ensure_ascii=False)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Số tiền thanh toán không khớp với đơn hàng.",
        )

    is_paid = code == "00" or bool(payload.get("success", True) and code in ("", "00"))
    if is_paid:
        packages_map = settings.get_topup_packages()
        pkg = packages_map.get(payment.package_code) or {}
        new_tier = pkg.get("tier")
        credited, _user = topup_credits_from_payment_atomic(
            db=db,
            payment_id=payment.id,
            new_tier=new_tier,
            raw_response_str=json.dumps(verified_data, ensure_ascii=False),
        )
        return {"ok": True, "credited": credited, "order_code": payment.order_code}

    payment.status = "failed"
    payment.raw_response = json.dumps(verified_data, ensure_ascii=False)
    db.commit()
    return {"ok": True, "credited": False, "order_code": payment.order_code}


@router.get("/payos/orders/{order_code}")
async def get_order_status(
    order_code: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payment = (
        db.query(Payment)
        .filter(Payment.order_code == order_code, Payment.user_id == current_user.id)
        .first()
    )
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy đơn hàng.",
        )
    return {
        "order_code": payment.order_code,
        "package_code": payment.package_code,
        "amount_vnd": payment.amount_vnd,
        "credits": payment.credits,
        "status": payment.status,
        "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
    }


@router.get("/payos/return", response_class=HTMLResponse)
async def payos_return(
    request: Request,
    orderCode: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    payment_status = "unknown"
    message = "Hệ thống đang đồng bộ trạng thái thanh toán từ PayOS."
    if orderCode is not None:
        payment = db.query(Payment).filter(Payment.order_code == int(orderCode)).first()
        if payment:
            payment_status = payment.status
            if payment.status == "paid":
                message = f"Đã cộng {payment.credits} credits vào tài khoản của bạn."
    return templates.TemplateResponse(
        request,
        "payment_success.html",
        {
            "request": request,
            "order_code": orderCode,
            "payment_status": payment_status,
            "provider_status": status or "",
            "message": message,
        },
    )


@router.get("/payos/cancel", response_class=HTMLResponse)
async def payos_cancel(
    request: Request,
    orderCode: int | None = None,
    db: Session = Depends(get_db),
):
    if orderCode is not None:
        payment = db.query(Payment).filter(Payment.order_code == int(orderCode)).first()
        if payment and payment.status == "pending":
            payment.status = "cancelled"
            db.commit()
    return templates.TemplateResponse(
        request,
        "payment_cancel.html",
        {
            "request": request,
            "order_code": orderCode,
            "message": "Giao dịch đã được hủy theo yêu cầu của bạn.",
        },
    )
