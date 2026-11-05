from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from config import settings
from database import User, get_db, grant_initial_free_credits_if_eligible

security = HTTPBearer(auto_error=False)
ACCESS_COOKIE_NAME = "ct_access_token"
REFRESH_COOKIE_NAME = "ct_refresh_token"


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token() -> tuple[str, datetime]:
    token = secrets.token_urlsafe(64)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    return token, expires_at


def verify_access_token(token: str) -> dict:
    is_dev = getattr(settings, "ENVIRONMENT", "").lower() == "development" or getattr(settings, "ENV", "").lower() == "development"
    if is_dev and (token.startswith("dev_token") or token.startswith("mock_token")):
        email = "student@mma301.fpt.edu.vn"
        if "@" in token:
            parts = token.split("@", 1)
            local_part = parts[0].split("_")[-1]
            email = f"{local_part}@{parts[1]}"
        return {"sub": f"dev_{email}", "email": email, "type": "access"}

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Loại token không hợp lệ.",
            )
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không hợp lệ hoặc đã hết hạn.",
        ) from exc


def extract_access_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> str:
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.strip():
        parts = auth_header.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
        elif len(parts) == 1:
            return parts[0]

    if credentials and credentials.credentials:
        return credentials.credentials

    cookie_token = request.cookies.get(ACCESS_COOKIE_NAME)
    if cookie_token:
        return cookie_token

    print(f"[DEBUG AUTH 401] Missing auth. Headers: {dict(request.headers)}")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Thiếu thông tin xác thực (Bearer token hoặc cookie).",
    )


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    token = extract_access_token(request, credentials)

    is_dev = getattr(settings, "ENVIRONMENT", "").lower() == "development" or getattr(settings, "ENV", "").lower() == "development"
    if is_dev and (token.startswith("dev_token") or token.startswith("mock_token")):
        email = "student@mma301.fpt.edu.vn"
        if "@" in token:
            parts = token.split("@", 1)
            local_part = parts[0].split("_")[-1]
            email = f"{local_part}@{parts[1]}"
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(
                firebase_uid=f"dev_{abs(hash(email)) % 1000000}",
                email=email,
                name=email.split("@")[0].replace(".", " ").title(),
                email_verified=True,
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
        grant_initial_free_credits_if_eligible(db, user, settings.DEFAULT_FREE_CREDITS)
        return user

    payload = verify_access_token(token)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Payload của token không hợp lệ.",
        )

    try:
        uid_int = int(user_id)
        user = db.query(User).filter(User.id == uid_int).first()
    except ValueError:
        user = db.query(User).filter(User.email == str(payload.get("email"))).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Không tìm thấy người dùng.",
        )
    return user
