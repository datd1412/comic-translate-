from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hmac
import io
import logging
import os
import time
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from config import settings
from engine import OCREngine, PaddleOCREngine
from pipeline import run_ocr_page_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ocr_service")

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/bmp",
}
ALLOWED_LANGS = {"zh", "en", "ko", "ja"}

DEFAULT_DEV_SECRETS = {
    "dev-internal-ocr-secret-change-me",
    "dev-internal-secret-change-me",
}


class AppState:
    engine: OCREngine | None = None
    semaphore: asyncio.Semaphore | None = None
    active_workers: int = 0
    peak_concurrent_workers: int = 0


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_TASKS)
    if state.engine is None and os.environ.get("OCR_SKIP_STARTUP_MODEL_LOAD") != "1":
        t0 = time.perf_counter()
        logger.info("Initializing PaddleOCREngine on startup...")
        state.engine = PaddleOCREngine()
        logger.info(
            "PaddleOCREngine ready in %.2f ms",
            (time.perf_counter() - t0) * 1000.0,
        )
    yield


app = FastAPI(
    title="Comic Translate VN - Internal OCR Service",
    version="1.0.0",
    lifespan=lifespan,
)


def set_ocr_engine_for_testing(custom_engine: OCREngine, max_concurrent: int | None = None) -> None:
    """Dùng trong pytest để gắn Mock Engine và cấu hình lại Semaphore mà không cần nạp PaddleOCR."""
    state.engine = custom_engine
    state.semaphore = asyncio.Semaphore(
        max_concurrent if max_concurrent is not None else settings.MAX_CONCURRENT_TASKS
    )
    state.active_workers = 0
    state.peak_concurrent_workers = 0


def _verify_internal_secret(
    x_internal_secret: str | None,
    x_internal_key: str | None = None,
    authorization: str | None = None,
) -> None:
    """
    Xác thực kết nối nội bộ giữa `server` (port 8000) và `ocr_service` (port 8001):
    - Cho phép bypass nếu bật `OCR_BYPASS_AUTH=true` trong `.env` khi chạy local dev.
    - Hỗ trợ đồng thời các header `X-Internal-Secret`, `X-Internal-Key`, hoặc `Authorization: Bearer <secret>`.
    - Ở môi trường `development`, chấp nhận cả 2 giá trị mặc định (`dev-internal-ocr-secret-change-me`
      và `dev-internal-secret-change-me`) để tránh lỗi lệch biến môi trường giữa 2 service.
    """
    if settings.OCR_BYPASS_AUTH or os.environ.get("OCR_BYPASS_AUTH", "").lower() in {"1", "true", "yes"}:
        return

    bearer_token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer_token = authorization[7:].strip()

    candidate = (x_internal_secret or x_internal_key or bearer_token or "").strip()
    if not candidate:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Missing or invalid X-Internal-Secret / X-Internal-Key header.",
        )

    expected = (settings.OCR_INTERNAL_SECRET or "").strip()
    if hmac.compare_digest(candidate, expected):
        return

    env_mode = (settings.ENV or os.environ.get("ENV", "development")).strip().lower()
    if env_mode in {"development", "dev", "local"} and expected in DEFAULT_DEV_SECRETS:
        if any(hmac.compare_digest(candidate, dev_sec) for dev_sec in DEFAULT_DEV_SECRETS):
            return

    raise HTTPException(
        status_code=401,
        detail="Unauthorized: Missing or invalid X-Internal-Secret / X-Internal-Key header.",
    )


def _decode_and_validate_image_in_ram(raw_bytes: bytes) -> Image.Image:
    """
    Giải mã ảnh từ BytesIO hoàn toàn trong RAM và kiểm tra giới hạn tổng số pixel
    trước khi nạp toàn bộ bitmap (chống decompression bomb).
    """
    Image.MAX_IMAGE_PIXELS = settings.MAX_IMAGE_PIXELS
    try:
        bio = io.BytesIO(raw_bytes)
        with Image.open(bio) as im:
            width, height = im.size
            total_pixels = width * height
            if width <= 0 or height <= 0 or total_pixels > settings.MAX_IMAGE_PIXELS:
                raise HTTPException(
                    status_code=413,
                    detail=f"Image dimensions ({width}x{height} = {total_pixels} px) exceed limit of {settings.MAX_IMAGE_PIXELS} pixels.",
                )
            return im.convert("RGB").copy()
    except Image.DecompressionBombError as exc:
        raise HTTPException(
            status_code=413,
            detail=f"Decompression bomb detected: {exc}",
        ) from exc
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid or corrupted image file: {exc}",
        ) from exc


@app.get("/health")
async def health_check() -> dict[str, Any]:
    return {
        "status": "ok",
        "engine_ready": state.engine is not None,
        "max_concurrent_tasks": settings.MAX_CONCURRENT_TASKS,
    }


@app.post("/v1/ocr-page")
async def ocr_page_endpoint(
    image: UploadFile = File(...),
    lang: str = Form(...),
    x_internal_secret: str | None = Header(default=None, alias="X-Internal-Secret"),
    x_internal_key: str | None = Header(default=None, alias="X-Internal-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> list[dict[str, Any]]:
    _verify_internal_secret(
        x_internal_secret=x_internal_secret,
        x_internal_key=x_internal_key,
        authorization=authorization,
    )

    lang_norm = lang.strip().lower()
    if lang_norm not in ALLOWED_LANGS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported lang '{lang}'. Allowed values: {sorted(ALLOWED_LANGS)}",
        )

    content_type = (image.content_type or "").lower().split(";")[0].strip()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported content-type '{content_type}'. Allowed: {sorted(ALLOWED_CONTENT_TYPES)}",
        )

    t_req_start = time.perf_counter()
    raw_bytes = await image.read(settings.MAX_FILE_BYTES + 1)
    if len(raw_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty image payload.")
    if len(raw_bytes) > settings.MAX_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File size exceeds limit of {settings.MAX_FILE_BYTES} bytes.",
        )

    t_dec0 = time.perf_counter()
    pil_image = _decode_and_validate_image_in_ram(raw_bytes)
    decode_ms = round((time.perf_counter() - t_dec0) * 1000.0, 2)

    if state.semaphore is None:
        state.semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_TASKS)
    if state.engine is None:
        state.engine = PaddleOCREngine()

    active_engine = state.engine

    async def _execute_under_semaphore() -> tuple[list[dict[str, Any]], dict[str, float | int]]:
        assert state.semaphore is not None
        async with state.semaphore:
            state.active_workers += 1
            if state.active_workers > state.peak_concurrent_workers:
                state.peak_concurrent_workers = state.active_workers
            try:
                return await asyncio.to_thread(
                    run_ocr_page_pipeline,
                    pil_image,
                    lang_norm,
                    active_engine,
                )
            finally:
                state.active_workers -= 1

    try:
        blocks, stage_stats = await asyncio.wait_for(
            _execute_under_semaphore(),
            timeout=settings.OCR_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail=f"OCR processing timed out after {settings.OCR_TIMEOUT_SECONDS}s.",
        ) from exc

    total_ms = round((time.perf_counter() - t_req_start) * 1000.0, 2)
    logger.info(
        "ocr_page lang=%s size=%dx%d slices=%s raw_lines=%s blocks=%s "
        "decode_ms=%.2f ocr_engine_ms=%.2f postprocess_ms=%.2f total_ms=%.2f",
        lang_norm,
        pil_image.width,
        pil_image.height,
        stage_stats["slice_count"],
        stage_stats["raw_line_count"],
        stage_stats["block_count"],
        decode_ms,
        stage_stats["ocr_engine_ms"],
        stage_stats["postprocess_ms"],
        total_ms,
    )
    return blocks


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.OCR_HOST,
        port=settings.OCR_PORT,
        reload=False,
    )
