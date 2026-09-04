from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.exceptions import AliasConflictError
from app.models import ClickEvent, ShortUrl
from app.shortener import encode_base62


def _resolve_expiry(expiry_days: int | None) -> datetime | None:
    days = expiry_days if expiry_days is not None else settings.default_expiry_days
    if not days:
        return None
    return datetime.now(timezone.utc) + timedelta(days=days)


def create_short_url(
    db: Session,
    original_url: str,
    expiry_days: int | None,
    custom_alias: str | None = None,
) -> ShortUrl:
    short_url = ShortUrl(
        code=custom_alias or "",  # "" is a placeholder, overwritten below for auto-generated codes
        original_url=original_url,
        expires_at=_resolve_expiry(expiry_days),
    )
    db.add(short_url)

    if custom_alias:
        # Attempt the insert directly and let the DB's unique constraint on
        # `code` be the source of truth, rather than checking for an existing
        # alias with a SELECT first: a check-then-insert has a TOCTOU race
        # window under concurrent requests for the same alias (see
        # docs/scenarios/02-brownfield-reliability-hardening.md and
        # tests/api/test_reliability.py for a concurrency test proving this).
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise AliasConflictError(custom_alias) from None
    else:
        db.flush()  # assigns short_url.id without committing
        short_url.code = encode_base62(short_url.id)
        db.commit()

    db.refresh(short_url)
    return short_url


def get_by_code(db: Session, code: str) -> ShortUrl | None:
    return db.query(ShortUrl).filter(ShortUrl.code == code).first()


def increment_click_count(db: Session, code: str) -> None:
    db.query(ShortUrl).filter(ShortUrl.code == code).update(
        {ShortUrl.click_count: ShortUrl.click_count + 1}
    )
    db.commit()


def record_click(
    db: Session,
    short_url_id: int,
    code: str,
    referrer: str | None,
    user_agent: str | None,
    ip_hash: str | None,
) -> None:
    """Record one click: a detailed event row plus the fast counter update,
    committed together so they can never drift apart."""
    db.add(
        ClickEvent(
            short_url_id=short_url_id,
            referrer=referrer,
            user_agent=user_agent,
            ip_hash=ip_hash,
        )
    )
    increment_click_count(db, code)  # commits the event insert + counter update together


def record_click_background(
    short_url_id: int,
    code: str,
    referrer: str | None,
    user_agent: str | None,
    ip_hash: str | None,
) -> None:
    """Entry point for FastAPI's BackgroundTasks.

    Opens and closes its own session rather than reusing the request-scoped
    one, because the request's session may already be closed by the time a
    background task actually runs (it executes after the response is sent).
    """
    from app.db import SessionLocal  # local import avoids a module-level cycle

    db = SessionLocal()
    try:
        record_click(db, short_url_id, code, referrer, user_agent, ip_hash)
    finally:
        db.close()


def soft_delete(db: Session, code: str) -> bool:
    short_url = get_by_code(db, code)
    if short_url is None:
        return False
    short_url.is_active = False
    db.commit()
    return True


def get_analytics(db: Session, short_url: ShortUrl) -> dict:
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)
    since_7d_start = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)

    clicks_last_24h = (
        db.query(func.count(ClickEvent.id))
        .filter(ClickEvent.short_url_id == short_url.id, ClickEvent.clicked_at >= since_24h)
        .scalar()
        or 0
    )

    daily_rows = (
        db.query(func.date(ClickEvent.clicked_at), func.count(ClickEvent.id))
        .filter(ClickEvent.short_url_id == short_url.id, ClickEvent.clicked_at >= since_7d_start)
        .group_by(func.date(ClickEvent.clicked_at))
        .all()
    )
    counts_by_date = {str(day): count for day, count in daily_rows}
    # Fill in zero-click days too, so a caller can render a continuous 7-day
    # chart without doing that bookkeeping itself.
    last_7_dates = [(now - timedelta(days=offset)).date().isoformat() for offset in range(6, -1, -1)]
    clicks_by_day = [{"date": day, "count": counts_by_date.get(day, 0)} for day in last_7_dates]

    referrer_rows = (
        db.query(ClickEvent.referrer, func.count(ClickEvent.id))
        .filter(ClickEvent.short_url_id == short_url.id)
        .group_by(ClickEvent.referrer)
        .order_by(func.count(ClickEvent.id).desc())
        .limit(5)
        .all()
    )
    top_referrers = [{"referrer": referrer or "direct", "count": count} for referrer, count in referrer_rows]

    return {
        "code": short_url.code,
        "total_clicks": short_url.click_count,
        "clicks_last_24h": clicks_last_24h,
        "clicks_by_day": clicks_by_day,
        "top_referrers": top_referrers,
    }


def is_expired(short_url: ShortUrl) -> bool:
    if short_url.expires_at is None:
        return False
    expires_at = short_url.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at < datetime.now(timezone.utc)
