from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.exceptions import AliasConflictError
from app.models import ShortUrl
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


def increment_click_count_background(code: str) -> None:
    """Entry point for FastAPI's BackgroundTasks.

    Opens and closes its own session rather than reusing the request-scoped
    one, because the request's session may already be closed by the time a
    background task actually runs (it executes after the response is sent).
    """
    from app.db import SessionLocal  # local import avoids a module-level cycle

    db = SessionLocal()
    try:
        increment_click_count(db, code)
    finally:
        db.close()


def soft_delete(db: Session, code: str) -> bool:
    short_url = get_by_code(db, code)
    if short_url is None:
        return False
    short_url.is_active = False
    db.commit()
    return True


def is_expired(short_url: ShortUrl) -> bool:
    if short_url.expires_at is None:
        return False
    expires_at = short_url.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at < datetime.now(timezone.utc)
