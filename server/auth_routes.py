from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import httpx
from jose import jwt as jose_jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth_utils import (
    ACCESS_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    create_access_token,
    create_refresh_token,
    get_current_user,
)
from config import settings
from database import (
    User,
    UserSession,
    get_db,
    grant_initial_free_credits_if_eligible,
)
from security import validate_callback_uri

router = APIRouter(tags=["Authentication"])

templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)

GOOGLE_JWKS_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/"
    "securetoken@system.gserviceaccount.com"
)
_cached_certs: dict[str, Any] = {}
_certs_expiry: datetime | None = None


def _get_cookie_Config() -> dict[str, Any]:
    samesite = (settings.AUTH_COOKIE_SAMESITE or "lax").strip().lower()
    if samesite not in {"lax", "strict", "none"}:
        samesite = "lax"
    secure = bool(settings.AUTH_COOKIE_SECURE)
    if samesite == "none":
        secure = True
    cfg: dict[str, Any] = {
        "httponly": True,
        "secure": secure,
        "samesite": samesite,
        "path": "/",
    }
    if settings.AUTH_COOKIE_DOMAIN.strip():
        cfg["domain"] = settings.AUTH_COOKIE_DOMAIN.strip()
    return cfg


def _set_auth_cookies(response: JSONResponse, access_token: str, refresh_token: str) -> None:
    cookie_cfg = _get_cookie_Config()
    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=access_token,
        max_age=int(settings.ACCESS_TOKEN_EXPIRE_MINUTES) * 60,
        **cookie_cfg,
    )
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=int(settings.REFRESH_TOKEN_EXPIRE_DAYS) * 24 * 60 * 60,
        **cookie_cfg,
    )


def _clear_auth_cookies(response: JSONResponse) -> None:
    cookie_cfg = _get_cookie_Config()
    response.delete_cookie(key=ACCESS_COOKIE_NAME, **cookie_cfg)
    response.delete_cookie(key=REFRESH_COOKIE_NAME, **cookie_cfg)


async def verify_firebase_id_token(id_token: str) -> dict[str, Any]:
    """Xác thực Firebase ID token với chứng chỉ công khai của Google."""
    global _cached_certs, _certs_expiry
    now = datetime.now(timezone.utc)

    if not _cached_certs or not _certs_expiry or now >= _certs_expiry:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(GOOGLE_JWKS_URL)
            resp.raise_for_status()
            _cached_certs = resp.json()
            cache_control = resp.headers.get("cache-control", "")
            max_age = 3600
            for part in cache_control.split(","):
                part = part.strip()
                if part.startswith("max-age="):
                    try:
                        max_age = int(part.split("=")[1])
                    except ValueError:
                        pass
            from datetime import timedelta
            _certs_expiry = now + timedelta(seconds=max_age)

    try:
        header = jose_jwt.get_unverified_header(id_token)
    except Exception as exc:
        raise ValueError(f"Header token không hợp lệ: {exc}") from exc

    kid = header.get("kid")
    if not kid or kid not in _cached_certs:
        raise ValueError("Key ID không hợp lệ trong Firebase ID token.")

    cert_pem = _cached_certs[kid]
    project_id = settings.FIREBASE_PROJECT_ID
    payload = jose_jwt.decode(
        id_token,
        cert_pem,
        algorithms=["RS256"],
        audience=project_id,
        issuer=f"https://securetoken.google.com/{project_id}",
    )
    if not payload.get("sub"):
        raise ValueError("Token thiếu trường sub (uid).")
    return payload


class FirebaseAuthRequest(BaseModel):
    id_token: str
    request_id: str | None = None
    desktop_callback_uri: str | None = None
    redirect_uri: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


@router.get("/login/", response_class=HTMLResponse)
async def login_page(
    request: Request,
    request_id: str | None = None,
    desktop_callback_uri: str | None = None,
    redirect_uri: str | None = None,
):
    """
    Render trang đăng nhập Firebase.
    Vá lỗ hổng #1: Kiểm tra chặt chẽ `desktop_callback_uri` / `redirect_uri` ngay tại `/login/`
    theo danh sách cho phép bằng `urllib.parse.urlparse`. Nếu truyền URI không hợp lệ, trả HTTP 400 ngay.
    """
    raw_callback = desktop_callback_uri if desktop_callback_uri is not None else redirect_uri
    validated_callback = validate_callback_uri(raw_callback)

    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "request": request,
            "request_id": request_id or "",
            "desktop_callback_uri": validated_callback or "",
            "firebase_api_key": settings.FIREBASE_WEB_API_KEY,
            "firebase_auth_domain": settings.FIREBASE_AUTH_DOMAIN,
            "firebase_project_id": settings.FIREBASE_PROJECT_ID,
            "firebase_storage_bucket": settings.FIREBASE_STORAGE_BUCKET,
            "firebase_messaging_sender_id": settings.FIREBASE_MESSAGING_SENDER_ID,
            "firebase_app_id": settings.FIREBASE_APP_ID,
        },
    )


@router.post("/auth/firebase")
async def firebase_auth_callback(
    body: FirebaseAuthRequest,
    db: Session = Depends(get_db),
):
    """
    Nhận Firebase ID token từ trang đăng nhập hoặc Chrome Extension, xác thực và cấp JWT của hệ thống.
    - Vá lỗ hổng #1: Kiểm tra `desktop_callback_uri` / `redirect_uri` bằng `validate_callback_uri` (trả 400 nếu sai).
    - Chống lạm dụng credit miễn phí: Chỉ cấp `DEFAULT_FREE_CREDITS` đúng 1 lần khi `email_verified == True`.
    """
    raw_callback = (
        body.desktop_callback_uri
        if body.desktop_callback_uri is not None
        else body.redirect_uri
    )
    validated_callback = validate_callback_uri(raw_callback)

    try:
        fb_payload = await verify_firebase_id_token(body.id_token)
    except Exception as exc:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": f"Xác thực Firebase thất bại: {exc}"},
        )

    firebase_uid = str(fb_payload["sub"])
    email = str(fb_payload.get("email") or "").strip().lower()
    email_verified = bool(fb_payload.get("email_verified", False))
    name = fb_payload.get("name") or (email.split("@")[0] if email else "User")
    picture = fb_payload.get("picture") or ""

    if not email:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Tài khoản không có email hợp lệ."},
        )

    user = db.query(User).filter(User.firebase_uid == firebase_uid).first()
    if not user:
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.firebase_uid = firebase_uid
            if email_verified and not user.email_verified:
                user.email_verified = True
            db.commit()
            db.refresh(user)
        else:
            user = User(
                firebase_uid=firebase_uid,
                email=email,
                name=name,
                avatar_url=picture,
                email_verified=email_verified,
                free_credits_granted=False,
                has_paid_topup=False,
                tier="Free",
                credits_subscription=0,
                credits_one_time=0,
                credits_total=0,
                monthly_credits=0,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
    else:
        changed = False
        if name and user.name != name:
            user.name = name
            changed = True
        if picture and user.avatar_url != picture:
            user.avatar_url = picture
            changed = True
        if email_verified and not user.email_verified:
            user.email_verified = True
            changed = True
        if changed:
            db.commit()
            db.refresh(user)

    # Cấp credit miễn phí ĐÚNG 1 LẦN khi và chỉ khi email_verified == True
    grant_initial_free_credits_if_eligible(db, user, settings.DEFAULT_FREE_CREDITS)

    access_token = create_access_token(data={"sub": str(user.id), "email": user.email})
    refresh_token_str, expires_at = create_refresh_token()

    new_session = UserSession(
        user_id=user.id,
        refresh_token=refresh_token_str,
        expires_at=expires_at,
    )
    db.add(new_session)
    db.commit()

    response_payload = {
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "request_id": body.request_id,
        "desktop_callback_uri": validated_callback,
        "user_info": {
            "email": user.email,
            "name": user.name or "",
            "tier": user.tier,
            "email_verified": bool(user.email_verified),
            "credits": {
                "subscription": int(user.credits_subscription or 0),
                "one_time": int(user.credits_one_time or 0),
                "total": int(user.credits_total or 0),
            },
            "monthly_credits": int(user.monthly_credits or 0),
        },
    }
    response = JSONResponse(content=response_payload)
    _set_auth_cookies(response, access_token, refresh_token_str)
    return response


@router.get("/auth/v1/user_info")
async def get_user_info(current_user: User = Depends(get_current_user)):
    total = int(current_user.credits_subscription or 0) + int(current_user.credits_one_time or 0)
    return {
        "email": current_user.email,
        "name": current_user.name or "",
        "tier": current_user.tier,
        "email_verified": bool(current_user.email_verified),
        "credits": {
            "subscription": int(current_user.credits_subscription or 0),
            "one_time": int(current_user.credits_one_time or 0),
            "total": total,
        },
        "monthly_credits": int(current_user.monthly_credits or 0),
        "avatar_url": current_user.avatar_url or "",
    }


@router.post("/auth/v1/refresh")
async def refresh_token_endpoint(
    request: Request,
    req: RefreshRequest | None = None,
    db: Session = Depends(get_db),
):
    refresh_token_value = (
        req.refresh_token.strip()
        if req and req.refresh_token and req.refresh_token.strip()
        else (request.cookies.get(REFRESH_COOKIE_NAME) or "").strip()
    )
    if not refresh_token_value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Thiếu refresh token.",
        )

    session = (
        db.query(UserSession)
        .filter(
            UserSession.refresh_token == refresh_token_value,
            UserSession.revoked == False,  # noqa: E712
        )
        .first()
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token không hợp lệ.",
        )

    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        session.revoked = True
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token đã hết hạn.",
        )

    user = session.user
    new_access_token = create_access_token(data={"sub": str(user.id), "email": user.email})
    response = JSONResponse(
        content={"access_token": new_access_token, "refresh_token": refresh_token_value}
    )
    _set_auth_cookies(response, new_access_token, refresh_token_value)
    return response


@router.post("/auth/v1/logout")
async def logout(
    request: Request,
    req: RefreshRequest | None = None,
    db: Session = Depends(get_db),
):
    refresh_token_value = (
        req.refresh_token.strip()
        if req and req.refresh_token and req.refresh_token.strip()
        else (request.cookies.get(REFRESH_COOKIE_NAME) or "").strip()
    )
    if refresh_token_value:
        session = (
            db.query(UserSession)
            .filter(UserSession.refresh_token == refresh_token_value)
            .first()
        )
        if session:
            session.revoked = True
            db.commit()

    response = JSONResponse(content={"status": "success"})
    _clear_auth_cookies(response)
    return response
