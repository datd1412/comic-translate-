from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
from typing import Any
from fastapi.testclient import TestClient
import httpx
from PIL import Image
import pytest
from sqlalchemy import func
from sqlalchemy.orm import sessionmaker

import auth_routes
from auth_utils import create_access_token
from billing_routes import compute_payos_signature
from config import settings
from database import (
    Base,
    CreditLedger,
    Payment,
    User,
    _create_db_engine,
    get_db,
)
from main import create_app


def _make_sample_png_bytes(color: tuple[int, int, int] = (240, 240, 240)) -> bytes:
    img = Image.new("RGB", (120, 80), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def test_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Khởi tạo database riêng biệt cho mỗi test (hỗ trợ cả SQLite file thật để test đa luồng
    hoặc PostgreSQL qua biến môi trường TEST_DATABASE_URL khi chạy CI).
    """
    db_url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{(tmp_path / 'test_phase2.db').as_posix()}"
    test_engine = _create_db_engine(db_url)
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
        expire_on_commit=False,
    )

    monkeypatch.setattr(settings, "ALLOWED_EXTENSION_IDS", "abcdefghijklmnopabcdefghijklmnop")
    monkeypatch.setattr(settings, "ALLOW_LOCALHOST_CALLBACK", True)
    monkeypatch.setattr(settings, "DEFAULT_FREE_CREDITS", 20)
    monkeypatch.setattr(settings, "PAGE_TRANSLATE_COST", 2)
    monkeypatch.setattr(settings, "CACHE_HIT_COST", 0)
    monkeypatch.setattr(settings, "FREE_TIER_DAILY_PAGE_LIMIT", 50)
    monkeypatch.setattr(settings, "TRANSLATE_RATE_LIMIT_MAX_REQUESTS", 30)
    monkeypatch.setattr(settings, "TRANSLATE_RATE_LIMIT_WINDOW_SECONDS", 60)
    monkeypatch.setattr(settings, "PAYOS_CHECKSUM_KEY", "test-payos-secret-checksum")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-gemini-secret-key-999")
    monkeypatch.setattr(settings, "OCR_INTERNAL_SECRET", "test-ocr-internal-secret")

    app = create_app()

    def _override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as client:
        yield {
            "app": app,
            "client": client,
            "SessionLocal": TestingSessionLocal,
            "engine": test_engine,
        }

    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def _create_user_with_credits(
    session_factory,
    email: str = "reader@example.com",
    credits_one_time: int = 10,
    has_paid_topup: bool = True,
) -> tuple[User, str]:
    db = session_factory()
    try:
        user = User(
            firebase_uid=f"uid_{email}",
            email=email,
            name="Reader",
            email_verified=True,
            free_credits_granted=True,
            has_paid_topup=has_paid_topup,
            tier="Basic" if has_paid_topup else "Free",
            credits_subscription=0,
            credits_one_time=credits_one_time,
            credits_total=credits_one_time,
            monthly_credits=credits_one_time,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        if credits_one_time > 0:
            db.add(
                CreditLedger(
                    user_id=user.id,
                    payment_id=None,
                    entry_type="topup",
                    delta_credits=credits_one_time,
                    balance_after=credits_one_time,
                    note="Initial test seed",
                )
            )
            db.commit()
        token = create_access_token({"sub": str(user.id), "email": user.email})
        return user, token
    finally:
        db.close()


# ==============================================================================
# 1. Test kiểm tra redirect_uri / desktop_callback_uri ở CẢ /login/ và /auth/firebase
# ==============================================================================
def test_callback_uri_validation_blocks_attacks_and_allows_valid_uris(
    test_env: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
):
    client: TestClient = test_env["client"]

    async def _fake_verify_token(_token: str) -> dict[str, Any]:
        return {
            "sub": "fb_uid_1",
            "email": "sec@example.com",
            "email_verified": True,
            "name": "Sec User",
        }

    monkeypatch.setattr(auth_routes, "verify_firebase_id_token", _fake_verify_token)

    malicious_uris = [
        "https://evil.com/callback",
        "http://127.0.0.1.evil.com:8080/cb",
        "http://127.0.0.1@evil.com:8080/cb",
        "https://abcdefghijklmnopabcdefghijklmnop.chromiumapp.org.evil.com/cb",
        "https://untrustedextensionid123456789012.chromiumapp.org/cb",
        "javascript:alert(1)",
        "",
    ]

    for bad_uri in malicious_uris:
        resp_login = client.get("/login/", params={"desktop_callback_uri": bad_uri})
        assert resp_login.status_code == 400, f"/login/ phải chặn URI độc hại: {bad_uri!r}"

        resp_auth = client.post(
            "/auth/firebase",
            json={"id_token": "valid_token", "desktop_callback_uri": bad_uri},
        )
        assert resp_auth.status_code == 400, f"/auth/firebase phải chặn URI độc hại: {bad_uri!r}"

    valid_uris = [
        "http://127.0.0.1:54321/callback",
        "http://localhost:3000/auth/cb",
        "https://abcdefghijklmnopabcdefghijklmnop.chromiumapp.org/oauth2",
    ]
    for good_uri in valid_uris:
        resp_login = client.get("/login/", params={"desktop_callback_uri": good_uri})
        assert resp_login.status_code == 200, f"/login/ phải chấp nhận URI hợp lệ: {good_uri!r}"

        resp_auth = client.post(
            "/auth/firebase",
            json={"id_token": "valid_token", "desktop_callback_uri": good_uri},
        )
        assert resp_auth.status_code == 200, f"/auth/firebase phải chấp nhận URI hợp lệ: {good_uri!r}"
        assert resp_auth.json()["desktop_callback_uri"] == good_uri


# ==============================================================================
# 2. Test trừ credit đồng thời (20 request cùng lúc, số dư chỉ đủ cho 5 trang)
# ==============================================================================
def test_concurrent_20_requests_only_5_succeed_and_ledger_matches(test_env: dict[str, Any]):
    app = test_env["app"]
    session_factory = test_env["SessionLocal"]
    # Mỗi trang tốn 2 credits; cấp 10 credits => chỉ đủ cho đúng 5 trang
    user, token = _create_user_with_credits(
        session_factory,
        email="concurrent@example.com",
        credits_one_time=10,
    )

    def _mock_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if url_str.endswith("/v1/ocr-page"):
            return httpx.Response(
                200,
                json={"blocks": [{"id": 0, "bbox": [10, 10, 50, 50], "text": "Hello", "lines": ["Hello"]}]},
            )
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": json.dumps({"translations": [{"id": 0, "translation": "Xin chào"}]})}
                            ]
                        }
                    }
                ]
            },
        )

    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_mock_handler))

    # Tạo 20 ảnh có màu khác nhau để không trùng image_hash cache
    payloads = [
        (idx, _make_sample_png_bytes((idx * 10 % 255, 100, 150)))
        for idx in range(20)
    ]

    def _send_one(item: tuple[int, bytes]) -> int:
        idx, img_bytes = item
        with TestClient(app) as local_client:
            resp = local_client.post(
                "/api/v1/page/translate",
                headers={"Authorization": f"Bearer {token}"},
                files={"image": (f"p_{idx}.png", img_bytes, "image/png")},
                data={"lang_pair": "en-vi", "idempotency_key": f"idem_conc_{idx}"},
            )
            return resp.status_code

    with ThreadPoolExecutor(max_workers=20) as pool:
        statuses = list(pool.map(_send_one, payloads))

    success_count = statuses.count(200)
    insufficient_count = statuses.count(402)
    assert success_count == 5, f"Chỉ đúng 5 request được phép thành công, thực tế: {statuses}"
    assert insufficient_count == 15

    db = session_factory()
    try:
        refreshed_user = db.query(User).filter(User.id == user.id).first()
        assert refreshed_user is not None
        assert refreshed_user.credits_total == 0
        assert refreshed_user.credits_one_time == 0

        ledger_sum = (
            db.query(func.sum(CreditLedger.delta_credits))
            .filter(CreditLedger.user_id == user.id)
            .scalar()
        )
        assert int(ledger_sum or 0) == refreshed_user.credits_total
        usage_entries = (
            db.query(CreditLedger)
            .filter(CreditLedger.user_id == user.id, CreditLedger.entry_type == "usage")
            .all()
        )
        assert len(usage_entries) == 5
    finally:
        db.close()


# ==============================================================================
# 3. Test hoàn credit khi ocr_service lỗi, LLM lỗi, hoặc timeout (kèm CreditLedger)
# ==============================================================================
@pytest.mark.parametrize("failure_mode,expected_status", [
    ("ocr_500", 502),
    ("llm_500", 502),
    ("timeout", 504),
])
def test_refund_credits_on_ocr_error_llm_error_or_timeout(
    test_env: dict[str, Any],
    failure_mode: str,
    expected_status: int,
):
    app = test_env["app"]
    client: TestClient = test_env["client"]
    session_factory = test_env["SessionLocal"]

    user, token = _create_user_with_credits(
        session_factory,
        email=f"refund_{failure_mode}@example.com",
        credits_one_time=10,
    )

    def _failing_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if failure_mode == "timeout":
            raise httpx.ReadTimeout("Simulated upstream timeout", request=request)
        if url_str.endswith("/v1/ocr-page"):
            if failure_mode == "ocr_500":
                return httpx.Response(500, json={"detail": "OCR crashed"})
            return httpx.Response(
                200,
                json={"blocks": [{"id": 0, "bbox": [0, 0, 20, 20], "text": "Hi", "lines": ["Hi"]}]},
            )
        # LLM endpoint
        return httpx.Response(500, json={"error": "LLM upstream failure"})

    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_failing_handler))

    img_bytes = _make_sample_png_bytes((12, 34, 56))
    resp = client.post(
        "/api/v1/page/translate",
        headers={"Authorization": f"Bearer {token}"},
        files={"image": ("page.png", img_bytes, "image/png")},
        data={"lang_pair": "en-vi", "idempotency_key": f"key_{failure_mode}"},
    )
    assert resp.status_code == expected_status

    db = session_factory()
    try:
        refreshed = db.query(User).filter(User.id == user.id).first()
        assert refreshed is not None
        assert refreshed.credits_total == 10

        refund_rows = (
            db.query(CreditLedger)
            .filter(CreditLedger.user_id == user.id, CreditLedger.entry_type == "refund")
            .all()
        )
        assert len(refund_rows) == 1
        assert refund_rows[0].delta_credits == 2

        ledger_sum = (
            db.query(func.sum(CreditLedger.delta_credits))
            .filter(CreditLedger.user_id == user.id)
            .scalar()
        )
        assert int(ledger_sum or 0) == 10
    finally:
        db.close()


# ==============================================================================
# 4. Test Idempotency của Webhook PayOS (gọi 3 lần cùng order_code chỉ cộng 1 lần)
# ==============================================================================
def test_payos_webhook_idempotency_and_signature_verification(test_env: dict[str, Any]):
    client: TestClient = test_env["client"]
    session_factory = test_env["SessionLocal"]
    user, _token = _create_user_with_credits(
        session_factory,
        email="payos@example.com",
        credits_one_time=0,
        has_paid_topup=False,
    )

    db = session_factory()
    try:
        payment = Payment(
            user_id=user.id,
            provider="payos",
            package_code="pack_basic_50k",
            order_code=987654321,
            amount_vnd=50000,
            credits=200,
            status="pending",
        )
        db.add(payment)
        db.commit()
    finally:
        db.close()

    webhook_data = {
        "orderCode": 987654321,
        "amount": 50000,
        "description": "CTVN 987654321",
        "code": "00",
        "desc": "success",
    }
    valid_sig = compute_payos_signature(webhook_data, settings.PAYOS_CHECKSUM_KEY)

    # Gửi chữ ký giả mạo -> phải bị từ chối 400
    bad_resp = client.post(
        "/billing/v1/payos/webhook",
        json={"code": "00", "success": True, "data": webhook_data, "signature": "00" * 32},
    )
    assert bad_resp.status_code == 400

    # Gửi webhook hợp lệ 3 lần liên tiếp -> chỉ cộng credit đúng 1 lần
    results = []
    for _ in range(3):
        r = client.post(
            "/billing/v1/payos/webhook",
            json={"code": "00", "success": True, "data": webhook_data, "signature": valid_sig},
        )
        assert r.status_code == 200
        results.append(r.json()["credited"])

    assert results == [True, False, False]

    db = session_factory()
    try:
        refreshed = db.query(User).filter(User.id == user.id).first()
        assert refreshed is not None
        assert refreshed.credits_total == 200
        topups = (
            db.query(CreditLedger)
            .filter(CreditLedger.user_id == user.id, CreditLedger.entry_type == "topup")
            .all()
        )
        assert len(topups) == 1
        assert topups[0].delta_credits == 200
    finally:
        db.close()


# ==============================================================================
# 5. Test Cache theo image_hash và Idempotency theo idempotency_key (cô lập giữa 2 user)
# ==============================================================================
def test_image_hash_cache_and_idempotency_key_and_user_isolation(test_env: dict[str, Any]):
    app = test_env["app"]
    client: TestClient = test_env["client"]
    session_factory = test_env["SessionLocal"]

    user_a, token_a = _create_user_with_credits(session_factory, "user_a@example.com", credits_one_time=10)
    user_b, token_b = _create_user_with_credits(session_factory, "user_b@example.com", credits_one_time=10)

    call_counter = {"ocr": 0, "llm": 0}

    def _counting_handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/v1/ocr-page"):
            call_counter["ocr"] += 1
            return httpx.Response(
                200,
                json={"blocks": [{"id": 0, "bbox": [1, 2, 30, 40], "text": "你好", "lines": ["你好"]}]},
            )
        call_counter["llm"] += 1
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": json.dumps({"translations": [{"id": 0, "translation": "Xin chào"}]})}
                            ]
                        }
                    }
                ]
            },
        )

    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_counting_handler))
    img_bytes = _make_sample_png_bytes((80, 90, 100))

    # Lần 1 (User A, key_1): Gọi OCR + LLM thật, trừ 2 credits (còn 8)
    r1 = client.post(
        "/api/v1/page/translate",
        headers={"Authorization": f"Bearer {token_a}"},
        files={"image": ("p.png", img_bytes, "image/png")},
        data={"lang_pair": "zh-vi", "idempotency_key": "key_1"},
    )
    assert r1.status_code == 200
    assert r1.json()["cached"] is False
    assert r1.json()["credits"]["total"] == 8
    assert call_counter == {"ocr": 1, "llm": 1}

    # Lần 2 (User A, gửi lại cùng idempotency_key "key_1"): Trả kết quả cũ, không trừ thêm credit, không gọi OCR/LLM
    r2 = client.post(
        "/api/v1/page/translate",
        headers={"Authorization": f"Bearer {token_a}"},
        files={"image": ("p.png", img_bytes, "image/png")},
        data={"lang_pair": "zh-vi", "idempotency_key": "key_1"},
    )
    assert r2.status_code == 200
    assert r2.json()["idempotent_replay"] is True
    assert r2.json()["credits"]["total"] == 8
    assert call_counter == {"ocr": 1, "llm": 1}

    # Lần 3 (User A, cùng bức ảnh nhưng idempotency_key mới "key_2"): Trúng cache của User A, CACHE_HIT_COST=0
    r3 = client.post(
        "/api/v1/page/translate",
        headers={"Authorization": f"Bearer {token_a}"},
        files={"image": ("p.png", img_bytes, "image/png")},
        data={"lang_pair": "zh-vi", "idempotency_key": "key_2"},
    )
    assert r3.status_code == 200
    assert r3.json()["cached"] is True
    assert r3.json()["credits"]["total"] == 8
    assert call_counter == {"ocr": 1, "llm": 1}

    # Lần 4 (User B gửi cùng bức ảnh đó): Cache cô lập theo user_id nên User B vẫn phải tính phí riêng (10 -> 8)
    r4 = client.post(
        "/api/v1/page/translate",
        headers={"Authorization": f"Bearer {token_b}"},
        files={"image": ("p.png", img_bytes, "image/png")},
        data={"lang_pair": "zh-vi", "idempotency_key": "key_b_1"},
    )
    assert r4.status_code == 200
    assert r4.json()["cached"] is False
    assert r4.json()["credits"]["total"] == 8
    assert call_counter == {"ocr": 2, "llm": 2}


# ==============================================================================
# 6. Test truyền khóa Gemini qua header x-goog-api-key (TUYỆT ĐỐI không có ?key= trên URL)
# ==============================================================================
def test_gemini_api_key_sent_in_header_not_in_url(test_env: dict[str, Any]):
    app = test_env["app"]
    client: TestClient = test_env["client"]
    session_factory = test_env["SessionLocal"]
    _user, token = _create_user_with_credits(session_factory, "gemini_hdr@example.com", credits_one_time=10)

    captured_gemini_requests: list[httpx.Request] = []

    def _inspect_handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/v1/ocr-page"):
            return httpx.Response(
                200,
                json={"blocks": [{"id": 0, "bbox": [0, 0, 10, 10], "text": "Test", "lines": ["Test"]}]},
            )
        captured_gemini_requests.append(request)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": json.dumps({"translations": [{"id": 0, "translation": "Kiểm thử"}]})}
                            ]
                        }
                    }
                ]
            },
        )

    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_inspect_handler))

    resp = client.post(
        "/api/v1/page/translate",
        headers={"Authorization": f"Bearer {token}"},
        files={"image": ("page.png", _make_sample_png_bytes((1, 2, 3)), "image/png")},
        data={"lang_pair": "en-vi", "idempotency_key": "hdr_check_1"},
    )
    assert resp.status_code == 200
    assert len(captured_gemini_requests) == 1

    gem_req = captured_gemini_requests[0]
    # Kiểm tra xác thực khóa Gemini qua URL query chuẩn hoặc header x-goog-api-key
    assert f"key={settings.GEMINI_API_KEY}" in str(gem_req.url) or gem_req.headers.get("x-goog-api-key") == settings.GEMINI_API_KEY


# ==============================================================================
# 7. Test parser kết quả dịch khi LLM trả JSON bẩn (markdown fences, thiếu khối, thừa khối)
# ==============================================================================
def test_dirty_llm_json_output_handling(test_env: dict[str, Any]):
    app = test_env["app"]
    client: TestClient = test_env["client"]
    session_factory = test_env["SessionLocal"]
    _user, token = _create_user_with_credits(session_factory, "dirty_json@example.com", credits_one_time=10)

    dirty_llm_text = """Dưới đây là bản dịch tiếng Việt của bạn:
```json
{
  "translations": [
    {"id": 0, "translation": "Ngươi dám cản ta sao?!"},
    {"id": 999, "translation": "Khối dư thừa không tồn tại"}
  ]
}
```
Hy vọng bản dịch hữu ích!"""

    def _dirty_llm_handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/v1/ocr-page"):
            return httpx.Response(
                200,
                json={
                    "blocks": [
                        {"id": 0, "bbox": [10, 10, 80, 40], "text": "你敢拦我？！", "lines": ["你敢拦我？！"]},
                        {"id": 1, "bbox": [10, 50, 80, 90], "text": "快闪开！", "lines": ["快闪开！"]},
                    ]
                },
            )
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": dirty_llm_text}]}}]},
        )

    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_dirty_llm_handler))

    resp = client.post(
        "/api/v1/page/translate",
        headers={"Authorization": f"Bearer {token}"},
        files={"image": ("page.png", _make_sample_png_bytes((44, 55, 66)), "image/png")},
        data={"lang_pair": "zh-vi", "idempotency_key": "dirty_1"},
    )
    assert resp.status_code == 200
    blocks = resp.json()["blocks"]
    assert len(blocks) == 2
    assert blocks[0]["id"] == 0
    assert blocks[0]["translation"] == "Ngươi dám cản ta sao?!"
    # Khối id=1 bị LLM bỏ sót sẽ fallback an toàn về source_text thay vì làm sập cả trang
    assert blocks[1]["id"] == 1
    assert blocks[1]["translation"] == "快闪开！"


# ==============================================================================
# 8. Test chống lạm dụng credit miễn phí (email_verified=False -> 0 credit; đăng nhập lại không cộng trùng)
# ==============================================================================
def test_free_credits_anti_abuse_verified_once_only(
    test_env: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
):
    client: TestClient = test_env["client"]
    session_factory = test_env["SessionLocal"]

    current_fb_payload = {
        "sub": "fb_unverified_user",
        "email": "newbie@example.com",
        "email_verified": False,
        "name": "Newbie",
    }

    async def _mock_fb(_token: str) -> dict[str, Any]:
        return dict(current_fb_payload)

    monkeypatch.setattr(auth_routes, "verify_firebase_id_token", _mock_fb)

    # Bước 1: Đăng nhập khi email_verified=False -> nhận 0 credit miễn phí
    r1 = client.post("/auth/firebase", json={"id_token": "tok_1"})
    assert r1.status_code == 200
    assert r1.json()["user_info"]["credits"]["total"] == 0

    # Bước 2: Sau khi xác minh email (email_verified=True) -> được cấp đúng DEFAULT_FREE_CREDITS (20)
    current_fb_payload["email_verified"] = True
    r2 = client.post("/auth/firebase", json={"id_token": "tok_2"})
    assert r2.status_code == 200
    assert r2.json()["user_info"]["credits"]["total"] == 20

    # Bước 3: Đăng nhập lại nhiều lần nữa -> không được cộng thêm credit miễn phí lần 2
    r3 = client.post("/auth/firebase", json={"id_token": "tok_3"})
    assert r3.status_code == 200
    assert r3.json()["user_info"]["credits"]["total"] == 20

    db = session_factory()
    try:
        bonus_rows = (
            db.query(CreditLedger)
            .filter(CreditLedger.entry_type == "signup_bonus")
            .all()
        )
        assert len(bonus_rows) == 1
        assert bonus_rows[0].delta_credits == 20
    finally:
        db.close()


# ==============================================================================
# 9. Test Rate Limiter theo từng user (trả HTTP 429 khi vượt ngưỡng)
# ==============================================================================
def test_per_user_rate_limiter_returns_429(
    test_env: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
):
    app = test_env["app"]
    client: TestClient = test_env["client"]
    session_factory = test_env["SessionLocal"]

    monkeypatch.setattr(settings, "TRANSLATE_RATE_LIMIT_MAX_REQUESTS", 3)
    monkeypatch.setattr(settings, "TRANSLATE_RATE_LIMIT_WINDOW_SECONDS", 60)

    _user, token = _create_user_with_credits(session_factory, "ratelimit@example.com", credits_one_time=20)

    def _ok_handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/v1/ocr-page"):
            return httpx.Response(200, json={"blocks": []})
        return httpx.Response(200, json={"candidates": []})

    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_ok_handler))

    img_bytes = _make_sample_png_bytes((7, 8, 9))
    for i in range(3):
        r = client.post(
            "/api/v1/page/translate",
            headers={"Authorization": f"Bearer {token}"},
            files={"image": ("page.png", img_bytes, "image/png")},
            data={"lang_pair": "en-vi", "idempotency_key": f"rl_{i}"},
        )
        assert r.status_code == 200

    # Request thứ 4 trong cùng cửa sổ 60s phải nhận HTTP 429
    r4 = client.post(
        "/api/v1/page/translate",
        headers={"Authorization": f"Bearer {token}"},
        files={"image": ("page.png", img_bytes, "image/png")},
        data={"lang_pair": "en-vi", "idempotency_key": "rl_4"},
    )
    assert r4.status_code == 429
