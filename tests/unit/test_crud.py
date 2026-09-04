from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import crud
from app.db import Base


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    from app import models  # noqa: F401  ensure ShortUrl is registered on Base

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_create_short_url_assigns_code(db_session) -> None:
    short_url = crud.create_short_url(db_session, "https://example.com/a", expiry_days=None)
    assert short_url.code
    assert short_url.click_count == 0
    assert short_url.expires_at is None


def test_get_by_code_round_trip(db_session) -> None:
    created = crud.create_short_url(db_session, "https://example.com/b", expiry_days=None)
    fetched = crud.get_by_code(db_session, created.code)
    assert fetched is not None
    assert fetched.original_url == "https://example.com/b"


def test_get_by_code_missing_returns_none(db_session) -> None:
    assert crud.get_by_code(db_session, "doesnotexist") is None


def test_increment_click_count(db_session) -> None:
    created = crud.create_short_url(db_session, "https://example.com/c", expiry_days=None)
    crud.increment_click_count(db_session, created.code)
    crud.increment_click_count(db_session, created.code)
    refreshed = crud.get_by_code(db_session, created.code)
    assert refreshed.click_count == 2


def test_expiry_days_sets_future_timestamp(db_session) -> None:
    short_url = crud.create_short_url(db_session, "https://example.com/d", expiry_days=1)
    assert short_url.expires_at is not None
    # SQLite doesn't persist tzinfo, so a value read back after a refresh is
    # naive even though it was written as UTC-aware. Normalize like
    # crud.is_expired() does before comparing.
    expires_at = short_url.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    assert expires_at > datetime.now(timezone.utc)


def test_is_expired_true_for_past_timestamp(db_session) -> None:
    short_url = crud.create_short_url(db_session, "https://example.com/e", expiry_days=None)
    short_url.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    assert crud.is_expired(short_url) is True


def test_is_expired_false_when_no_expiry(db_session) -> None:
    short_url = crud.create_short_url(db_session, "https://example.com/f", expiry_days=None)
    assert crud.is_expired(short_url) is False
