from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import crud
from app.db import Base
from app.exceptions import AliasConflictError


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


def test_custom_alias_used_as_code(db_session) -> None:
    short_url = crud.create_short_url(db_session, "https://example.com/g", expiry_days=None, custom_alias="my-alias")
    assert short_url.code == "my-alias"


def test_duplicate_custom_alias_raises_conflict(db_session) -> None:
    crud.create_short_url(db_session, "https://example.com/h1", expiry_days=None, custom_alias="taken")
    with pytest.raises(AliasConflictError):
        crud.create_short_url(db_session, "https://example.com/h2", expiry_days=None, custom_alias="taken")


def test_soft_delete_deactivates_and_is_idempotent_on_missing(db_session) -> None:
    created = crud.create_short_url(db_session, "https://example.com/i", expiry_days=None)
    assert crud.soft_delete(db_session, created.code) is True
    assert crud.get_by_code(db_session, created.code).is_active is False
    assert crud.soft_delete(db_session, "doesnotexist") is False


def test_record_click_background_uses_its_own_session(tmp_path, monkeypatch) -> None:
    # record_click_background opens app.db.SessionLocal directly (it can't
    # reuse a request-scoped session — see the docstring on that function).
    # Point SessionLocal at a throwaway engine sharing the same Base
    # metadata, to exercise that exact code path in isolation.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import db as db_module

    engine = create_engine(f"sqlite:///{tmp_path / 'bg.db'}", connect_args={"check_same_thread": False})
    db_module.Base.metadata.create_all(engine)
    test_session_local = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", test_session_local)

    session = test_session_local()
    try:
        created = crud.create_short_url(session, "https://example.com/j", expiry_days=None)
        short_url_id, code = created.id, created.code
    finally:
        session.close()

    crud.record_click_background(short_url_id, code, "https://ref.example", "pytest-agent", "abc123")

    session = test_session_local()
    try:
        refreshed = crud.get_by_code(session, code)
        assert refreshed.click_count == 1
        analytics = crud.get_analytics(session, refreshed)
        assert analytics["total_clicks"] == 1
        assert analytics["top_referrers"] == [{"referrer": "https://ref.example", "count": 1}]
    finally:
        session.close()


def test_get_analytics_aggregates_across_referrers_and_days(db_session) -> None:
    created = crud.create_short_url(db_session, "https://example.com/k", expiry_days=None)

    crud.record_click(db_session, created.id, created.code, "https://a.example", "ua", "hash1")
    crud.record_click(db_session, created.id, created.code, "https://a.example", "ua", "hash2")
    crud.record_click(db_session, created.id, created.code, "https://b.example", "ua", "hash3")
    crud.record_click(db_session, created.id, created.code, None, "ua", "hash4")  # direct traffic

    analytics = crud.get_analytics(db_session, created)

    assert analytics["total_clicks"] == 4
    assert analytics["clicks_last_24h"] == 4
    assert len(analytics["clicks_by_day"]) == 7
    assert sum(day["count"] for day in analytics["clicks_by_day"]) == 4
    assert analytics["top_referrers"][0] == {"referrer": "https://a.example", "count": 2}
    assert {"referrer": "direct", "count": 1} in analytics["top_referrers"]


def test_get_analytics_with_no_clicks_is_all_zero(db_session) -> None:
    created = crud.create_short_url(db_session, "https://example.com/l", expiry_days=None)
    analytics = crud.get_analytics(db_session, created)

    assert analytics["total_clicks"] == 0
    assert analytics["clicks_last_24h"] == 0
    assert all(day["count"] == 0 for day in analytics["clicks_by_day"])
    assert analytics["top_referrers"] == []
