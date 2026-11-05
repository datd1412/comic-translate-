from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from fastapi.testclient import TestClient
import pytest
from database import Base, _create_db_engine, get_db
from main import create_app
from config import settings
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def test_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_url = f"sqlite:///{(tmp_path / 'test_landing.db').as_posix()}"
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
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")

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
        }

    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def test_landing_page_renders_html_with_comic_translate_vn_brand(test_env: dict[str, Any]):
    client: TestClient = test_env["client"]
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Comic Translate VN" in resp.text
    assert "pack_basic_50k" in resp.text or "50.000 VND" in resp.text


def test_login_page_renders_html(test_env: dict[str, Any]):
    client: TestClient = test_env["client"]
    resp = client.get("/login/")
    assert resp.status_code == 200
    assert "Comic Translate VN" in resp.text


def test_dev_fast_login_creates_session_and_returns_tokens(test_env: dict[str, Any]):
    client: TestClient = test_env["client"]
    resp = client.post(
        "/auth/firebase",
        json={
            "id_token": "dev_token_user_tester@comictranslate.vn",
            "desktop_callback_uri": "https://abcdefghijklmnopabcdefghijklmnop.chromiumapp.org/cb",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["user_info"]["email"] == "tester@comictranslate.vn"
    assert data["desktop_callback_uri"] == "https://abcdefghijklmnopabcdefghijklmnop.chromiumapp.org/cb"


def test_create_payment_intent_endpoint_supports_aliases(test_env: dict[str, Any]):
    client: TestClient = test_env["client"]
    # First login via dev token
    resp_login = client.post(
        "/auth/firebase",
        json={"id_token": "dev_token_user_tester@comictranslate.vn"},
    )
    token = resp_login.json()["access_token"]

    # Call /billing/v1/payment-intents with vnd_100000 alias
    resp_pay = client.post(
        "/billing/v1/payment-intents",
        headers={"Authorization": f"Bearer {token}"},
        json={"package_code": "vnd_100000"},
    )
    assert resp_pay.status_code == 200
    data = resp_pay.json()
    assert "order_code" in data
    assert "checkout_url" in data
    assert data["amount_vnd"] == 100000

