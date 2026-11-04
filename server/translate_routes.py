from __future__ import annotations

from datetime import timedelta
import hashlib
import io
import json
from typing import Any
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
import httpx
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from config import settings
from database import (
    TranslationCache,
    TranslationIdempotency,
    User,
    check_and_record_rate_limit,
    deduct_credits_atomic,
    get_db,
    refund_credits_atomic,
    utcnow,
)
from ocr_postprocess import merge_adjacent_vertical_dialogue, normalize_text, split_blocks
from reading_order import extract_bbox, sort_blocks_by_reading_order
from translator import LLMTranslationError, translate_blocks_with_llm

router = APIRouter(prefix="/api/v1/page", tags=["Page Translation"])

SUPPORTED_LANG_PAIRS: dict[str, tuple[str, str]] = {
    "zh-vi": ("zh", "vi"),
    "en-vi": ("en", "vi"),
    "ko-vi": ("ko", "vi"),
    "ja-vi": ("ja", "vi"),
}


async def call_ocr_service(
    image_bytes: bytes,
    filename: str,
    content_type: str,
    source_lang: str,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """
    Gọi `ocr_service` (`POST /v1/ocr-page`) với đầy đủ các header xác thực nội bộ
    (`X-Internal-Secret`, `X-Internal-Key`, `Authorization: Bearer ...`) và chuẩn hóa
    dữ liệu trả về (hỗ trợ cả `list[dict]` trực tiếp từ `ocr_service` lẫn `{"blocks": [...]}`).
    """
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=settings.OCR_TIMEOUT_SECONDS)
    url = f"{settings.OCR_SERVICE_URL.rstrip('/')}/v1/ocr-page"
    secret = (settings.OCR_INTERNAL_SECRET or "").strip()
    headers = {
        "X-Internal-Secret": secret,
        "X-Internal-Key": secret,
        "Authorization": f"Bearer {secret}",
    }
    files = {"image": (filename or "page.png", image_bytes, content_type or "image/png")}
    data = {"lang": source_lang}

    try:
        resp = await client.post(url, files=files, data=data, headers=headers)
        if resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"OCR service trả mã lỗi HTTP {resp.status_code}: {resp.text[:200]}",
            )
        payload = resp.json()
        if isinstance(payload, list):
            return {"blocks": payload}
        if isinstance(payload, dict):
            return payload
        return {"blocks": []}
    finally:
        if owns_client:
            await client.aclose()


@router.post("/translate")
async def translate_comic_page(
    request: Request,
    image: UploadFile = File(...),
    lang_pair: str = Form("zh-vi"),
    idempotency_key: str = Form(...),
    reading_direction: str | None = Form(None),
    context_json: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Endpoint dịch trang truyện tranh `POST /api/v1/page/translate`:
    1. Tiếp nhận trường `reading_direction` (rtl hoặc ltr), tự động fallback theo aspect ratio ảnh.
    2. Sắp xếp các khối văn bản theo thứ tự đọc tự nhiên trước khi đưa vào LLM.
    3. Tra cứu và lưu `TranslationCache` theo `(user_id, cache_image_hash, lang_pair)`
       (với `cache_image_hash = f"{image_hash}_{reading_direction}"` để tránh lẫn lộn giữa LTR và RTL).
    """
    normalized_pair = (lang_pair or "").strip().lower()
    if normalized_pair not in SUPPORTED_LANG_PAIRS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cặp ngôn ngữ '{lang_pair}' chưa được hỗ trợ. Hỗ trợ: {', '.join(SUPPORTED_LANG_PAIRS.keys())}.",
        )
    source_lang, _target_lang = SUPPORTED_LANG_PAIRS[normalized_pair]

    idem_key = (idempotency_key or "").strip()
    if not idem_key or len(idem_key) > 128:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="idempotency_key không hợp lệ.",
        )

    # 1. Kiểm tra Rate Limit theo từng user (nếu bật và max_requests > 0)
    if settings.TRANSLATE_RATE_LIMIT_ENABLED and settings.TRANSLATE_RATE_LIMIT_MAX_REQUESTS > 0:
        allowed = check_and_record_rate_limit(
            db=db,
            subject_key=f"user:{current_user.id}",
            endpoint="translate_page",
            max_requests=settings.TRANSLATE_RATE_LIMIT_MAX_REQUESTS,
            window_seconds=settings.TRANSLATE_RATE_LIMIT_WINDOW_SECONDS,
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Bạn gửi yêu cầu dịch quá nhanh. Vui lòng đợi một chút rồi thử lại.",
            )

    # 2. Đọc và xác thực ảnh trong RAM
    raw_bytes = await image.read()
    if not raw_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dữ liệu ảnh trống.",
        )
    if len(raw_bytes) > settings.MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Kích thước ảnh vượt quá giới hạn cho phép.",
        )

    img_width, img_height = 0, 0
    try:
        with Image.open(io.BytesIO(raw_bytes)) as pil_img:
            img_width, img_height = pil_img.size
            pil_img.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File tải lên không phải là ảnh hợp lệ.",
        ) from exc

    image_hash = hashlib.sha256(raw_bytes).hexdigest()

    # Chuẩn hóa reading_direction và fallback nếu không truyền
    dir_val = (reading_direction or "").strip().lower()
    if dir_val in ("rtl", "ltr"):
        effective_direction = dir_val
    else:
        # Nếu aspect ratio (height / width) > 2.0 (trang truyện dài/webtoon cuộn) -> mặc định LTR, ngược lại RTL
        if img_width > 0 and img_height > 0 and (img_height / img_width) > 2.0:
            effective_direction = "ltr"
        else:
            effective_direction = "rtl"

    cache_image_hash = f"{image_hash}_{effective_direction}"

    context_dict: dict[str, Any] = {}
    if context_json and context_json.strip():
        try:
            parsed_ctx = json.loads(context_json)
            if isinstance(parsed_ctx, dict):
                context_dict = parsed_ctx
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="context_json không phải là JSON object hợp lệ.",
            ) from exc

    # 3. Kiểm tra Idempotency Key theo user
    existing_idem = (
        db.query(TranslationIdempotency)
        .filter(
            TranslationIdempotency.user_id == current_user.id,
            TranslationIdempotency.idempotency_key == idem_key,
        )
        .first()
    )
    if existing_idem and existing_idem.status == "completed" and existing_idem.response_json:
        saved_payload = json.loads(existing_idem.response_json)
        db.refresh(current_user)
        saved_payload["idempotent_replay"] = True
        saved_payload["reading_direction"] = effective_direction
        saved_payload["credits"] = {
            "subscription": int(current_user.credits_subscription or 0),
            "one_time": int(current_user.credits_one_time or 0),
            "total": int(current_user.credits_total or 0),
        }
        return saved_payload

    # 4. Kiểm tra Cache theo (user_id, cache_image_hash, lang_pair)
    now = utcnow()
    cache_row = (
        db.query(TranslationCache)
        .filter(
            TranslationCache.user_id == current_user.id,
            TranslationCache.image_hash == cache_image_hash,
            TranslationCache.lang_pair == normalized_pair,
        )
        .first()
    )
    if cache_row is not None:
        exp = cache_row.expires_at
        if exp.tzinfo is None:
            from datetime import timezone
            exp = exp.replace(tzinfo=timezone.utc)
        if exp >= now:
            cache_cost = max(0, int(settings.CACHE_HIT_COST))
            if cache_cost > 0:
                ok_deduct, err_code, _info = deduct_credits_atomic(
                    db=db,
                    user_id=current_user.id,
                    cost=cache_cost,
                    note=f"Cache hit translation ({normalized_pair})",
                    check_daily_free_limit=False,
                )
                if not ok_deduct:
                    raise HTTPException(
                        status_code=status.HTTP_402_PAYMENT_REQUIRED,
                        detail=f"Không đủ credit ({err_code}).",
                    )
            db.refresh(current_user)
            cached_blocks = json.loads(cache_row.blocks_json)
            response_data = {
                "blocks": cached_blocks,
                "lang_pair": normalized_pair,
                "reading_direction": effective_direction,
                "cached": True,
                "idempotent_replay": False,
                "charged_credits": cache_cost,
                "credits": {
                    "subscription": int(current_user.credits_subscription or 0),
                    "one_time": int(current_user.credits_one_time or 0),
                    "total": int(current_user.credits_total or 0),
                },
            }
            if existing_idem is None:
                db.add(
                    TranslationIdempotency(
                        user_id=current_user.id,
                        idempotency_key=idem_key,
                        image_hash=cache_image_hash,
                        lang_pair=normalized_pair,
                        status="completed",
                        charged_credits=cache_cost,
                        response_json=json.dumps(response_data, ensure_ascii=False),
                    )
                )
            else:
                existing_idem.status = "completed"
                existing_idem.charged_credits = cache_cost
                existing_idem.response_json = json.dumps(response_data, ensure_ascii=False)
            db.commit()
            return response_data
        else:
            db.delete(cache_row)
            db.commit()

    # 5. Trừ credit nguyên tử trước khi gọi OCR + LLM
    cost = max(0, int(settings.PAGE_TRANSLATE_COST))
    ok_deduct, err_code, deduct_info = deduct_credits_atomic(
        db=db,
        user_id=current_user.id,
        cost=cost,
        note=f"Page translation ({normalized_pair}) key={idem_key}",
        check_daily_free_limit=True,
    )
    if not ok_deduct:
        if err_code == "DAILY_FREE_LIMIT_REACHED":
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Bạn đã dùng hết số trang miễn phí trong ngày. Vui lòng nạp thêm credit để tiếp tục.",
            )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Số dư credit không đủ để dịch trang này.",
        )

    sub_deducted = deduct_info["sub_deducted"]
    one_time_deducted = deduct_info["one_time_deducted"]

    http_client: httpx.AsyncClient | None = getattr(request.app.state, "http_client", None)
# 6. Gọi OCR Service và LLM; nếu thất bại thì hoàn trả nguyên tử số credit vừa trừ
    try:
        ocr_result = await call_ocr_service(
            image_bytes=raw_bytes,
            filename=image.filename or "page.png",
            content_type=image.content_type or "image/png",
            source_lang=source_lang,
            http_client=http_client,
        )
        ocr_blocks = ocr_result.get("blocks") or []

        if ocr_blocks:
            # 1. Gọi normalize_text
            for block in ocr_blocks:
                normalize_text(block)

            # 2. Gọi split_blocks
            dialogue, edge_strips, ignored = split_blocks(
                ocr_blocks, img_w=img_width, img_h=img_height
            )

            # 3. Gom các cột thoại dọc liền kề trong cùng bong bóng thoại
            dialogue = merge_adjacent_vertical_dialogue(
                dialogue, reading_direction=effective_direction
            )

            # 4. Chỉ sort_blocks_by_reading_order phần dialogue
            sorted_dialogue = sort_blocks_by_reading_order(
                dialogue, reading_direction=effective_direction
            )

            # Giữ nguyên thứ tự từ trên xuống của edge_strips
            sorted_edge_strips = sorted(edge_strips, key=lambda b: extract_bbox(b)[1])

            # 4. Danh sách đưa vào LLM = edge_strips (đặt trước) + dialogue đã sort
            final_blocks = sorted_edge_strips + sorted_dialogue

            # 5. Gán lại id = 0..n-1 theo thứ tự cuối cùng
            for new_id, block in enumerate(final_blocks):
                block["id"] = new_id

            # 6. Dịch bằng LLM (khối ignored không dịch và không trả về client)
            if final_blocks:
                translated_blocks = await translate_blocks_with_llm(
                    blocks=final_blocks,
                    lang_pair=normalized_pair,
                    context=context_dict,
                    reading_direction=effective_direction,
                    http_client=http_client,
                )
            else:
                translated_blocks = []
        else:
            translated_blocks = []

    except httpx.TimeoutException as exc:
        print(f"\n[ERROR TIMEOUT]: {exc}")
        refund_credits_atomic(
            db=db,
            user_id=current_user.id,
            sub_deducted=sub_deducted,
            one_time_deducted=one_time_deducted,
            note=f"Refund due to timeout (key={idem_key})",
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Quá thời gian chờ khi xử lý OCR hoặc dịch thuật. Đã hoàn lại credit.",
        ) from exc
    except (LLMTranslationError, HTTPException, httpx.HTTPError) as exc:
        import traceback
        print(f"\n[ERROR UPSTREAM] Type: {type(exc).__name__} | Detail: {exc}")
        traceback.print_exc()
        refund_credits_atomic(
            db=db,
            user_id=current_user.id,
            sub_deducted=sub_deducted,
            one_time_deducted=one_time_deducted,
            note=f"Refund due to upstream error (key={idem_key})",
        )
        if isinstance(exc, HTTPException):
            raise exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Lỗi dịch vụ xử lý ({exc}). Đã hoàn lại credit.",
        ) from exc
    except Exception as exc:
        import traceback
        print(f"\n[ERROR UNEXPECTED] Type: {type(exc).__name__} | Detail: {exc}")
        traceback.print_exc()
        refund_credits_atomic(
            db=db,
            user_id=current_user.id,
            sub_deducted=sub_deducted,
            one_time_deducted=one_time_deducted,
            note=f"Refund due to unexpected error (key={idem_key})",
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Lỗi hệ thống khi dịch trang. Đã hoàn lại credit.",
        ) from exc

    # 7. Lưu Cache (chỉ văn bản) và Idempotency record
    expires_at = utcnow() + timedelta(seconds=settings.TRANSLATE_CACHE_TTL_SECONDS)
    new_cache = TranslationCache(
        user_id=current_user.id,
        image_hash=cache_image_hash,
        lang_pair=normalized_pair,
        blocks_json=json.dumps(translated_blocks, ensure_ascii=False),
        expires_at=expires_at,
    )
    db.add(new_cache)

    db.refresh(current_user)
    response_payload = {
        "blocks": translated_blocks,
        "lang_pair": normalized_pair,
        "reading_direction": effective_direction,
        "cached": False,
        "idempotent_replay": False,
        "charged_credits": cost,
        "credits": {
            "subscription": int(current_user.credits_subscription or 0),
            "one_time": int(current_user.credits_one_time or 0),
            "total": int(current_user.credits_total or 0),
        },
    }

    if existing_idem is None:
        db.add(
            TranslationIdempotency(
                user_id=current_user.id,
                idempotency_key=idem_key,
                image_hash=cache_image_hash,
                lang_pair=normalized_pair,
                status="completed",
                charged_credits=cost,
                response_json=json.dumps(response_payload, ensure_ascii=False),
            )
        )
    else:
        existing_idem.status = "completed"
        existing_idem.charged_credits = cost
        existing_idem.response_json = json.dumps(response_payload, ensure_ascii=False)

    db.commit()
    return response_payload
