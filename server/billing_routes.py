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

from auth_utils import create_access_token, create_refresh_token, get_current_user
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


async def _check_payos_order_paid(order_code: int) -> bool:
    """Truy vấn trực tiếp trạng thái đơn hàng từ PayOS API."""
    if not (settings.PAYOS_CLIENT_ID and settings.PAYOS_API_KEY):
        return False
    try:
        headers = {
            "x-client-id": settings.PAYOS_CLIENT_ID,
            "x-api-key": settings.PAYOS_API_KEY,
        }
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                f"https://api-merchant.payos.vn/v2/payment-requests/{order_code}",
                headers=headers,
            )
            if r.status_code == 200:
                payload = r.json()
                data = payload.get("data") or {}
                return data.get("status") == "PAID"
    except Exception as e:
        print(f"[WARN] Không thể kiểm tra PayOS API: {e}")
    return False


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


PACKAGE_ALIASES: dict[str, str] = {
    "vnd_50000": "pack_basic_50k",
    "vnd_100000": "pack_pro_100k",
    "vnd_200000": "pack_ultra_200k",
}


@router.post("/payos/checkout")
@router.post("/payment-intents")
async def create_payos_checkout(
    req: CreateCheckoutRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    package_code = PACKAGE_ALIASES.get(req.package_code, req.package_code)
    packages_map = settings.get_topup_packages()
    pkg = packages_map.get(package_code)
    if not pkg:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Mã gói nạp không hợp lệ: {req.package_code}",
        )

    order_code = _generate_unique_order_code(db)
    amount_vnd = int(pkg["amount_vnd"])
    credits = int(pkg["credits"])

    payment = Payment(
        user_id=current_user.id,
        provider="payos",
        package_code=package_code,
        order_code=order_code,
        amount_vnd=amount_vnd,
        credits=credits,
        status="pending",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    # Dynamic return & cancel URL theo host thực tế của client (127.0.0.1, localhost, hoặc 192.168.x.x)
    host = request.headers.get("host") or "127.0.0.1:8000"
    scheme = request.url.scheme or "http"
    base_url = f"{scheme}://{host}".rstrip("/")
    dynamic_return_url = f"{base_url}/billing/v1/payos/return"
    dynamic_cancel_url = f"{base_url}/billing/v1/payos/cancel"

    try:
        link_info = await _create_payos_payment_link(
            order_code=order_code,
            amount_vnd=amount_vnd,
            description=f"CTVN {order_code}"[:25],
            return_url=dynamic_return_url,
            cancel_url=dynamic_cancel_url,
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


@router.get("/transactions")
async def list_transactions(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payments = (
        db.query(Payment)
        .filter(Payment.user_id == current_user.id)
        .order_by(Payment.created_at.desc())
        .limit(limit)
        .all()
    )
    items = []
    for p in payments:
        items.append({
            "order_code": p.order_code,
            "provider_txn_ref": str(p.order_code),
            "package_code": p.package_code,
            "amount_vnd": p.amount_vnd,
            "credits": p.credits,
            "status": "succeeded" if p.status == "paid" else p.status,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "paid_at": p.paid_at.isoformat() if p.paid_at else None,
        })
    return {"items": items}


@router.get("/payos/return", response_class=HTMLResponse)
async def payos_return(
    request: Request,
    orderCode: int | None = None,
    status: str | None = None,
    code: str | None = None,
    cancel: bool | None = None,
    db: Session = Depends(get_db),
):
    payment_status = "unknown"
    message = "Hệ thống đang đồng bộ trạng thái thanh toán từ PayOS."
    user: User | None = None

    if orderCode is not None:
        payment = db.query(Payment).filter(Payment.order_code == int(orderCode)).first()
        if payment:
            user = db.query(User).filter(User.id == payment.user_id).first()

            # Tín hiệu thanh toán thành công từ PayOS redirect query parameters
            is_paid_signal = (
                (status and status.upper() == "PAID")
                or (code and str(code).strip() in ("00", "0"))
                or (cancel is False)
            )

            # Nếu đơn chưa được cập nhật thành 'paid' trong database:
            if payment.status != "paid":
                # Kiểm tra trực tiếp PayOS API để đảm bảo tính xác thực
                is_confirmed_paid = await _check_payos_order_paid(payment.order_code)
                # Cho phép cộng credit nếu API PayOS xác nhận hoặc có tín hiệu PAID từ redirect
                if is_confirmed_paid or is_paid_signal or getattr(settings, "ENVIRONMENT", "").lower() == "development":
                    packages_map = settings.get_topup_packages()
                    pkg = packages_map.get(payment.package_code) or {}
                    new_tier = pkg.get("tier")
                    credited, credited_user = topup_credits_from_payment_atomic(
                        db=db,
                        payment_id=payment.id,
                        new_tier=new_tier,
                        raw_response_str=json.dumps({"return_query": dict(request.query_params)}, ensure_ascii=False),
                    )
                    if credited_user:
                        user = credited_user

            db.refresh(payment)
            payment_status = payment.status
            if payment.status == "paid":
                message = f"Thanh toán thành công! Đã cộng {payment.credits} credits vào tài khoản của bạn."

    response = templates.TemplateResponse(
        request,
        "payment_success.html",
        {
            "request": request,
            "order_code": orderCode,
            "payment_status": payment_status,
            "provider_status": status or "",
            "message": message,
            "user": user,
        },
    )

    # Đảm bảo nếu user bị mất cookie khi redirect từ PayOS về, tự động cấp lại cookie phiên đăng nhập
    if user:
        from auth_routes import _set_auth_cookies
        access_token = create_access_token(data={"sub": str(user.id), "email": user.email})
        refresh_token, _ = create_refresh_token()
        _set_auth_cookies(response, access_token, refresh_token)

    return response


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
