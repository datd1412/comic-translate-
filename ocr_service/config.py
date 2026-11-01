from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class OCRServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENV: str = "development"
    OCR_HOST: str = "127.0.0.1"
    OCR_PORT: int = 8001
    OCR_INTERNAL_SECRET: str = "dev-internal-ocr-secret-change-me"
    OCR_BYPASS_AUTH: bool = False

    # Giới hạn bảo mật & tài nguyên
    MAX_FILE_BYTES: int = 15 * 1024 * 1024          # 15 MB
    MAX_IMAGE_PIXELS: int = 25_000_000             # 25 Megapixels (chống decompression bomb)
    MAX_CONCURRENT_TASKS: int = 2                  # Semaphore giới hạn 1-2 tác vụ đồng thời
    OCR_TIMEOUT_SECONDS: float = 45.0              # Timeout cho mỗi trang OCR
    CPU_THREADS: int = 4

    # Cấu hình model PaddleOCR 3.7.0 Mobile cho CPU
    DET_MODEL_NAME: str = "PP-OCRv5_mobile_det"
    REC_MODEL_NAME: str = "PP-OCRv5_mobile_rec"

    # Cấu hình cắt lát dọc (vertical slicing) cho ảnh dài (> 1500px)
    SLICE_HEIGHT_THRESHOLD_PX: int = 1500
    SLICE_CHUNK_HEIGHT_PX: int = 1400
    SLICE_OVERLAP_PX: int = 150

    # Ngưỡng gắn cờ điểm thấp (KHÔNG xóa dòng theo điểm tin cậy)
    LOW_CONFIDENCE_THRESHOLD: float = 0.60

    # Ngưỡng lọc rác hình học & watermark
    MIN_BOX_WIDTH_PX: int = 8
    MIN_BOX_HEIGHT_PX: int = 8
    MIN_BOX_AREA_PX: int = 100
    WATERMARK_EDGE_MARGIN_PX: int = 50


settings = OCRServiceSettings()
