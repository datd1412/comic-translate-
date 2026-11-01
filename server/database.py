from __future__ import annotations

from datetime import datetime, timedelta, timezone
import threading
from typing import Any
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

from config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _create_db_engine(database_url: str):
    is_sqlite = database_url.startswith("sqlite")
    connect_args = {"check_same_thread": False, "timeout": 30.0} if is_sqlite else {}
    eng = create_engine(
        database_url,
        connect_args=connect_args,
        pool_pre_ping=True,
    )
    if is_sqlite:
        @event.listens_for(eng, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA busy_timeout = 30000")
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.close()
    return eng


engine = _create_db_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)

# Khóa đồng bộ bổ trợ khi chạy SQLite đa luồng trong cùng tiến trình kiểm thử
_SQLITE_WRITE_LOCK = threading.RLock()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    firebase_uid = Column(String, unique=True, index=True, nullable=True)
    google_id = Column(String, unique=True, index=True, nullable=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)
    avatar_url = Column(String, nullable=True)

    email_verified = Column(Boolean, default=False, nullable=False)
    free_credits_granted = Column(Boolean, default=False, nullable=False)
    has_paid_topup = Column(Boolean, default=False, nullable=False)

    tier = Column(String, default="Free", nullable=False)
    credits_subscription = Column(Integer, default=0, nullable=False)
    credits_one_time = Column(Integer, default=0, nullable=False)
    credits_total = Column(Integer, default=0, nullable=False)
    monthly_credits = Column(Integer, default=0, nullable=False)

    # Giới hạn trang miễn phí theo ngày cho tài khoản chưa từng nạp tiền (biện pháp chống lạm dụng thứ 2)
    daily_free_pages_used = Column(Integer, default=0, nullable=False)
    daily_free_reset_date = Column(String, default="", nullable=False)

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="user", cascade="all, delete-orphan")
    ledger_entries = relationship("CreditLedger", back_populates="user", cascade="all, delete-orphan")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    refresh_token = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    revoked = Column(Boolean, default=False, nullable=False)

    user = relationship("User", back_populates="sessions")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String, default="payos", nullable=False)
    package_code = Column(String, nullable=False)
    order_code = Column(Integer, unique=True, index=True, nullable=False)
    payment_link_id = Column(String, index=True, nullable=True)
    amount_vnd = Column(Integer, nullable=False)
    credits = Column(Integer, nullable=False)
    status = Column(String, default="pending", index=True, nullable=False)  # pending | paid | cancelled | failed
    checkout_url = Column(Text, nullable=True)
    raw_response = Column(Text, nullable=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="payments")


class CreditLedger(Base):
    __tablename__ = "credit_ledger"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True, index=True)
    entry_type = Column(String, default="topup", index=True, nullable=False)  # signup_bonus | topup | usage | refund
    delta_credits = Column(Integer, nullable=False)
    balance_after = Column(Integer, nullable=False)
    note = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    user = relationship("User", back_populates="ledger_entries")


class TranslationIdempotency(Base):
    __tablename__ = "translation_idempotency"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_user_idempotency_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    idempotency_key = Column(String, nullable=False, index=True)
    image_hash = Column(String, nullable=False)
    lang_pair = Column(String, nullable=False)
    status = Column(String, default="in_progress", nullable=False)  # in_progress | completed | failed
    charged_credits = Column(Integer, default=0, nullable=False)
    response_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TranslationCache(Base):
    """
    Cache kết quả dịch CHỈ LƯU VĂN BẢN (tuyệt đối không lưu ảnh gốc),
    tách biệt theo từng `user_id` + `image_hash` + `lang_pair` và có hạn sử dụng `expires_at`.
    """
    __tablename__ = "translation_cache"
    __table_args__ = (
        UniqueConstraint("user_id", "image_hash", "lang_pair", name="uq_user_image_lang_cache"),
        Index("ix_translation_cache_lookup", "user_id", "image_hash", "lang_pair"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    image_hash = Column(String, nullable=False, index=True)
    lang_pair = Column(String, nullable=False)
    blocks_json = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class RateLimitLog(Base):
    """
    Bảng lưu vết giới hạn tần suất (Rate Limit) theo từng user trong DB.
    Giúp nhiều worker process chia sẻ chung trạng thái giới hạn mà không bắt buộc cài thêm Redis.
    """
    __tablename__ = "rate_limit_logs"
    __table_args__ = (
        Index("ix_rate_limit_subject_endpoint_time", "subject_key", "endpoint", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    subject_key = Column(String, nullable=False, index=True)
    endpoint = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


def init_db(target_engine=None) -> None:
    bind_engine = target_engine or engine
    Base.metadata.create_all(bind=bind_engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def grant_initial_free_credits_if_eligible(
    db: Session,
    user: User,
    free_credits: int | None = None,
) -> bool:
    """
    Cấp credit miễn phí ban đầu ĐÚNG 1 LẦN cho tài khoản khi và chỉ khi:
    - `user.email_verified == True`
    - `user.free_credits_granted == False`
    Ghi nhận đầy đủ vào `CreditLedger` với `entry_type="signup_bonus"`.
    """
    amount = settings.DEFAULT_FREE_CREDITS if free_credits is None else int(free_credits)
    if not user.email_verified or user.free_credits_granted or amount <= 0:
        return False

    with _SQLITE_WRITE_LOCK:
        stmt = text(
            """
            UPDATE users
            SET credits_one_time = credits_one_time + :amt,
                credits_total = credits_total + :amt,
                monthly_credits = CASE WHEN monthly_credits < :amt THEN :amt ELSE monthly_credits END,
                free_credits_granted = :granted_true
            WHERE id = :uid AND free_credits_granted = :granted_false AND email_verified = :verified_true
            """
        )
        res = db.execute(
            stmt,
            {
                "amt": amount,
                "uid": user.id,
                "granted_true": True,
                "granted_false": False,
                "verified_true": True,
            },
        )
        if res.rowcount != 1:
            db.rollback()
            return False

        db.refresh(user)
        db.add(
            CreditLedger(
                user_id=user.id,
                payment_id=None,
                entry_type="signup_bonus",
                delta_credits=amount,
                balance_after=int(user.credits_total or 0),
                note="Initial verified account free credits",
            )
        )
        db.commit()
        db.refresh(user)
        return True


def deduct_credits_atomic(
    db: Session,
    user_id: int,
    cost: int,
    note: str,
    check_daily_free_limit: bool = True,
) -> tuple[bool, str | None, dict[str, int]]:
    """
    Trừ credit nguyên tử (Atomic SQL UPDATE) và ghi `CreditLedger(entry_type="usage")`.
    Đảm bảo khi N request chạy đồng thời:
    - Không bao giờ để `credits_total` âm.
    - Chỉ đúng số request đủ số dư mới cập nhật thành công (`rowcount == 1`).
    - Luôn ghi `CreditLedger` khớp tuyệt đối với số credit bị trừ.
    Trả về: `( thành_công, mã_lỗi_nếu_có, {"sub_deducted": ..., "one_time_deducted": ..., "balance_after": ...} )`.
    """
    cost_int = max(0, int(cost))
    today_str = utcnow().strftime("%Y-%m-%d")

    with _SQLITE_WRITE_LOCK:
        dialect = db.bind.dialect.name if db.bind is not None else "sqlite"
        if dialect == "sqlite":
            # Khóa ghi tức thời trên SQLite để tuần tự hóa các giao dịch đồng thời
            db.execute(text("BEGIN IMMEDIATE"))
            user_row = db.execute(
                text(
                    "SELECT id, credits_subscription, credits_one_time, credits_total, "
                    "has_paid_topup, daily_free_pages_used, daily_free_reset_date "
                    "FROM users WHERE id = :uid"
                ),
                {"uid": user_id},
            ).fetchone()
        else:
            user_row = db.execute(
                text(
                    "SELECT id, credits_subscription, credits_one_time, credits_total, "
                    "has_paid_topup, daily_free_pages_used, daily_free_reset_date "
                    "FROM users WHERE id = :uid FOR UPDATE"
                ),
                {"uid": user_id},
            ).fetchone()

        if user_row is None:
            db.rollback()
            return False, "USER_NOT_FOUND", {"sub_deducted": 0, "one_time_deducted": 0, "balance_after": 0}

        sub_bal = int(user_row[1] or 0)
        one_bal = int(user_row[2] or 0)
        total_bal = sub_bal + one_bal
        has_paid = bool(user_row[4])
        daily_used = int(user_row[5] or 0)
        daily_date = str(user_row[6] or "")

        if daily_date != today_str:
            daily_used = 0

        # Kiểm tra giới hạn trang miễn phí mỗi ngày cho tài khoản chưa từng nạp tiền
        if (
            check_daily_free_limit
            and not has_paid
            and cost_int > 0
            and daily_used >= settings.FREE_TIER_DAILY_PAGE_LIMIT
        ):
            db.rollback()
            return (
                False,
                "DAILY_FREE_LIMIT_REACHED",
                {"sub_deducted": 0, "one_time_deducted": 0, "balance_after": total_bal},
            )

        if cost_int == 0:
            return (
                True,
                None,
                {"sub_deducted": 0, "one_time_deducted": 0, "balance_after": total_bal},
            )

        if total_bal < cost_int:
            db.rollback()
            return (
                False,
                "INSUFFICIENT_CREDITS",
                {"sub_deducted": 0, "one_time_deducted": 0, "balance_after": total_bal},
            )

        sub_deducted = min(sub_bal, cost_int)
        one_time_deducted = cost_int - sub_deducted
        new_sub = sub_bal - sub_deducted
        new_one = one_bal - one_time_deducted
        new_total = new_sub + new_one
        new_daily_used = daily_used + 1 if not has_paid else daily_used

        upd = db.execute(
            text(
                """
                UPDATE users
                SET credits_subscription = :new_sub,
                    credits_one_time = :new_one,
                    credits_total = :new_total,
                    daily_free_pages_used = :new_daily_used,
                    daily_free_reset_date = :today_str
                WHERE id = :uid
                  AND credits_subscription = :old_sub
                  AND credits_one_time = :old_one
                  AND (credits_subscription + credits_one_time) >= :cost
                """
            ),
            {
                "new_sub": new_sub,
                "new_one": new_one,
                "new_total": new_total,
                "new_daily_used": new_daily_used,
                "today_str": today_str,
                "uid": user_id,
                "old_sub": sub_bal,
                "old_one": one_bal,
                "cost": cost_int,
            },
        )
        if upd.rowcount != 1:
            db.rollback()
            return (
                False,
                "CONCURRENT_MODIFICATION",
                {"sub_deducted": 0, "one_time_deducted": 0, "balance_after": total_bal},
            )

        db.add(
            CreditLedger(
                user_id=user_id,
                payment_id=None,
                entry_type="usage",
                delta_credits=-cost_int,
                balance_after=new_total,
                note=note,
            )
        )
        db.commit()
        return (
            True,
            None,
            {
                "sub_deducted": sub_deducted,
                "one_time_deducted": one_time_deducted,
                "balance_after": new_total,
            },
        )


def refund_credits_atomic(
    db: Session,
    user_id: int,
    sub_deducted: int,
    one_time_deducted: int,
    note: str,
) -> int:
    """
    Hoàn trả nguyên tử số credit đã trừ khi OCR hoặc LLM thất bại/timeout,
    đồng thời ghi `CreditLedger(entry_type="refund")` với `delta_credits = +(sub_deducted + one_time_deducted)`.
    """
    sub_add = max(0, int(sub_deducted))
    one_add = max(0, int(one_time_deducted))
    total_add = sub_add + one_add
    if total_add <= 0:
        user = db.query(User).filter(User.id == user_id).first()
        return int(user.credits_total or 0) if user else 0

    with _SQLITE_WRITE_LOCK:
        dialect = db.bind.dialect.name if db.bind is not None else "sqlite"
        if dialect == "sqlite":
            db.execute(text("BEGIN IMMEDIATE"))
            row = db.execute(
                text(
                    "SELECT credits_subscription, credits_one_time, daily_free_pages_used, has_paid_topup "
                    "FROM users WHERE id = :uid"
                ),
                {"uid": user_id},
            ).fetchone()
        else:
            row = db.execute(
                text(
                    "SELECT credits_subscription, credits_one_time, daily_free_pages_used, has_paid_topup "
                    "FROM users WHERE id = :uid FOR UPDATE"
                ),
                {"uid": user_id},
            ).fetchone()

        if row is None:
            db.rollback()
            return 0

        new_sub = int(row[0] or 0) + sub_add
        new_one = int(row[1] or 0) + one_add
        new_total = new_sub + new_one
        old_daily = int(row[2] or 0)
        has_paid = bool(row[3])
        new_daily = max(0, old_daily - 1) if not has_paid else old_daily

        db.execute(
            text(
                """
                UPDATE users
                SET credits_subscription = :new_sub,
                    credits_one_time = :new_one,
                    credits_total = :new_total,
                    daily_free_pages_used = :new_daily
                WHERE id = :uid
                """
            ),
            {
                "new_sub": new_sub,
                "new_one": new_one,
                "new_total": new_total,
                "new_daily": new_daily,
                "uid": user_id,
            },
        )
        db.add(
            CreditLedger(
                user_id=user_id,
                payment_id=None,
                entry_type="refund",
                delta_credits=total_add,
                balance_after=new_total,
                note=note,
            )
        )
        db.commit()
        return new_total


def topup_credits_from_payment_atomic(
    db: Session,
    payment_id: int,
    new_tier: str | None = None,
    raw_response_str: str | None = None,
) -> tuple[bool, User | None]:
    """
    Cộng credit nguyên tử và idempotent cho một giao dịch PayOS:
    - Nếu `payment.status == "paid"` hoặc đã có bản ghi `CreditLedger` gắn với `payment_id`, không cộng trùng.
    - Cập nhật `payment.status = "paid"`, cộng `credits_one_time` và `credits_total`, đánh dấu `has_paid_topup = True`,
      và ghi `CreditLedger(entry_type="topup")`.
    """
    with _SQLITE_WRITE_LOCK:
        dialect = db.bind.dialect.name if db.bind is not None else "sqlite"
        if dialect == "sqlite":
            db.execute(text("BEGIN IMMEDIATE"))

        payment = db.query(Payment).filter(Payment.id == payment_id).first()
        if not payment:
            db.rollback()
            return False, None

        existing_ledger = (
            db.query(CreditLedger)
            .filter(CreditLedger.payment_id == payment.id, CreditLedger.entry_type == "topup")
            .first()
        )
        if payment.status == "paid" or existing_ledger is not None:
            user = db.query(User).filter(User.id == payment.user_id).first()
            db.commit()
            return False, user

        upd_payment = db.execute(
            text(
                """
                UPDATE payments
                SET status = 'paid',
                    paid_at = :paid_at,
                    raw_response = COALESCE(:raw_resp, raw_response)
                WHERE id = :pid AND status != 'paid'
                """
            ),
            {
                "paid_at": utcnow(),
                "raw_resp": raw_response_str,
                "pid": payment.id,
            },
        )
        if upd_payment.rowcount != 1:
            db.rollback()
            user = db.query(User).filter(User.id == payment.user_id).first()
            return False, user

        added = max(0, int(payment.credits or 0))
        user_row = db.execute(
            text("SELECT credits_subscription, credits_one_time, monthly_credits, tier FROM users WHERE id = :uid"),
            {"uid": payment.user_id},
        ).fetchone()
        if user_row is None:
            db.rollback()
            return False, None

        sub_bal = int(user_row[0] or 0)
        one_bal = int(user_row[1] or 0)
        old_monthly = int(user_row[2] or 0)
        old_tier = str(user_row[3] or "Free")

        new_one = one_bal + added
        new_total = sub_bal + new_one
        new_monthly = max(old_monthly, new_total)
        resolved_tier = new_tier or old_tier

        db.execute(
            text(
                """
                UPDATE users
                SET credits_one_time = :new_one,
                    credits_total = :new_total,
                    monthly_credits = :new_monthly,
                    tier = :tier,
                    has_paid_topup = :has_paid
                WHERE id = :uid
                """
            ),
            {
                "new_one": new_one,
                "new_total": new_total,
                "new_monthly": new_monthly,
                "tier": resolved_tier,
                "has_paid": True,
                "uid": payment.user_id,
            },
        )
        db.add(
            CreditLedger(
                user_id=payment.user_id,
                payment_id=payment.id,
                entry_type="topup",
                delta_credits=added,
                balance_after=new_total,
                note=f"PayOS order {payment.order_code}",
            )
        )
        db.commit()
        user = db.query(User).filter(User.id == payment.user_id).first()
        return True, user


def check_and_record_rate_limit(
    db: Session,
    subject_key: str,
    endpoint: str,
    max_requests: int,
    window_seconds: int,
) -> bool:
    """
    Kiểm tra và ghi nhận rate limit theo từng user trong bảng `rate_limit_logs`.
    Trả về `True` nếu được phép, `False` nếu vượt quá `max_requests` trong `window_seconds`.
    """
    now = utcnow()
    cutoff = now - timedelta(seconds=window_seconds)

    with _SQLITE_WRITE_LOCK:
        db.query(RateLimitLog).filter(
            RateLimitLog.subject_key == subject_key,
            RateLimitLog.endpoint == endpoint,
            RateLimitLog.created_at < cutoff,
        ).delete(synchronize_session=False)

        count = (
            db.query(RateLimitLog)
            .filter(
                RateLimitLog.subject_key == subject_key,
                RateLimitLog.endpoint == endpoint,
                RateLimitLog.created_at >= cutoff,
            )
            .count()
        )
        if count >= max_requests:
            db.commit()
            return False

        db.add(
            RateLimitLog(
                subject_key=subject_key,
                endpoint=endpoint,
                created_at=now,
            )
        )
        db.commit()
        return True
