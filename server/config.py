from __future__ import annotations

import json
import os
from typing import Any
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_TOPUP_PACKAGES: dict[str, dict[str, Any]] = {
    "pack_basic_50k": {
        "amount_vnd": 50000,
        "credits": 200,
        "tier": "Basic",
        "title": "Gói Cơ Bản (200 Credits)",
    },
    "pack_pro_100k": {
        "amount_vnd": 100000,
        "credits": 450,
        "tier": "Pro",
        "title": "Gói Nâng Cao (450 Credits)",
    },
    "pack_ultra_200k": {
        "amount_vnd": 200000,
        "credits": 1000,
        "tier": "Ultra",
        "title": "Gói Siêu Cấp (1000 Credits)",
    },
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(os.path.join(os.path.dirname(__file__), ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "Comic Translate VN Server"
    ENVIRONMENT: str = "development"
    ENV: str = "development"
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    DATABASE_URL: str = "sqlite:///./comic_translate_vn.db"
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:8000"

    # Danh sách Chrome Extension ID được phép nhận callback OAuth/Firebase
    # Ví dụ: "abcdefghijklmnopabcdefghijklmnop,qrstuvwxyzabcdefqrstuvwxyzabcdef"
    ALLOWED_EXTENSION_IDS: str = "abcdefghijklmnopabcdefghijklmnop"
    ALLOW_LOCALHOST_CALLBACK: bool = True

    # Admin access (danh sách email admin phân tách bởi dấu phẩy)
    ADMIN_EMAILS: str = ""

    # Firebase Auth
    FIREBASE_PROJECT_ID: str = ""
    FIREBASE_WEB_API_KEY: str = ""
    FIREBASE_API_KEY: str = ""
    FIREBASE_AUTH_DOMAIN: str = ""
    FIREBASE_STORAGE_BUCKET: str = ""
    FIREBASE_MESSAGING_SENDER_ID: str = ""
    FIREBASE_APP_ID: str = ""

    # OCR Service nội bộ (đồng bộ chính xác giá trị mặc định với ocr_service/config.py)
    OCR_SERVICE_URL: str = "http://127.0.0.1:8001"
    OCR_INTERNAL_SECRET: str = "dev-internal-ocr-secret-change-me"
    OCR_TIMEOUT_SECONDS: float = 90.0

    # Nhà cung cấp LLM dịch thuật ("gemini" hoặc "deepseek")
    LLM_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.1-flash-lite"
    ENABLE_BUBBLE_DETECTOR: bool = True
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"
    LLM_TIMEOUT_SECONDS: float = 45.0
    LLM_TEMPERATURE: float = 0.2

    # Cấu hình Credit & Chống lạm dụng
    DEFAULT_FREE_CREDITS: int = 20
    FREE_TIER_DAILY_PAGE_LIMIT: int = 200
    PAGE_TRANSLATE_COST: int = 2
    CACHE_HIT_COST: int = 0
    TRANSLATE_CACHE_TTL_SECONDS: int = 86400

    # Giới hạn ảnh đầu vào tại Server chính
    MAX_IMAGE_BYTES: int = 10 * 1024 * 1024  # 10 MB

    # Rate limit theo từng user trên endpoint dịch trang:
    # - Phù hợp với hành vi cuộn đọc tự nhiên (60 trang / 60 giây).
    # - Có thể đặt TRANSLATE_RATE_LIMIT_ENABLED=false trong .env khi chạy dev để tắt hẳn limiter.
    TRANSLATE_RATE_LIMIT_ENABLED: bool = True
    TRANSLATE_RATE_LIMIT_MAX_REQUESTS: int = 60
    TRANSLATE_RATE_LIMIT_WINDOW_SECONDS: int = 60

    # PayOS cấu hình & bảng gói nạp (đọc từ biến môi trường JSON hoặc dùng mặc định)
    PAYOS_CLIENT_ID: str = ""
    PAYOS_API_KEY: str = ""
    PAYOS_CHECKSUM_KEY: str = "dev-payos-checksum-key"
    PAYOS_RETURN_URL: str = "http://localhost:8000/billing/v1/payos/return"
    PAYOS_CANCEL_URL: str = "http://localhost:8000/billing/v1/payos/cancel"
    TOPUP_PACKAGES_JSON: str = ""

    # Cookie bảo mật
    AUTH_COOKIE_SECURE: bool = False
    AUTH_COOKIE_SAMESITE: str = "lax"
    AUTH_COOKIE_DOMAIN: str = ""

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        env = os.getenv("ENVIRONMENT", os.getenv("ENV", "development")).lower()
        if env == "production" and (not v or v == "dev-secret-key-change-in-production" or len(v) < 32):
            raise ValueError("SECRET_KEY trên production phải dài tối thiểu 32 ký tự.")
        return v

    @property
    def cors_origins_list(self) -> list[str]:
        return [item.strip() for item in self.CORS_ORIGINS.split(",") if item.strip()]

    @property
    def allowed_extension_ids_set(self) -> set[str]:
        return {
            item.strip().lower()
            for item in self.ALLOWED_EXTENSION_IDS.split(",")
            for item in [item]
            if item.strip()
        }

    def get_topup_packages(self) -> dict[str, dict[str, Any]]:
        raw = (self.TOPUP_PACKAGES_JSON or "").strip()
        if not raw:
            return dict(DEFAULT_TOPUP_PACKAGES)
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed:
                return parsed
        except Exception:
            pass
        return dict(DEFAULT_TOPUP_PACKAGES)


settings = Settings()
