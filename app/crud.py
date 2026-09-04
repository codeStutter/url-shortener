from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models import ShortUrl
from app.shortener import encode_base62


def _resolve_expiry(expiry_days: int | None) -> datetime | None:
    days = expiry_days if expiry_days is not None else settings.default_expiry_days
    if not days:
        return None
    return datetime.now(timezone.utc) + timedelta(days=days)


def create_short_url(db: Session, original_url: str, expiry_days: int | None) -> ShortUrl:
    short_url = ShortUrl(
        code="",  # placeholder until we know the autoincrement id
        original_url=original_url,
        expires_at=_resolve_expiry(expiry_days),
    )
    db.add(short_url)
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


def is_expired(short_url: ShortUrl) -> bool:
    if short_url.expires_at is None:
        return False
    expires_at = short_url.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at < datetime.now(timezone.utc)
