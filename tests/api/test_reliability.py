import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx


def test_custom_alias_happy_path(api_context) -> None:
    alias = f"alias-{uuid.uuid4().hex[:8]}"
    response = api_context.post(
        "/api/urls", data={"original_url": "https://example.com/aliased", "custom_alias": alias}
    )
    assert response.status == 201
    assert response.json()["code"] == alias


def test_duplicate_custom_alias_returns_409(api_context) -> None:
    alias = f"dup-{uuid.uuid4().hex[:8]}"
    first = api_context.post("/api/urls", data={"original_url": "https://example.com/1", "custom_alias": alias})
    assert first.status == 201

    second = api_context.post("/api/urls", data={"original_url": "https://example.com/2", "custom_alias": alias})
    assert second.status == 409


def test_reserved_alias_rejected(api_context) -> None:
    response = api_context.post("/api/urls", data={"original_url": "https://example.com/x", "custom_alias": "api"})
    assert response.status == 400


def test_malformed_alias_rejected_by_validation(api_context) -> None:
    response = api_context.post("/api/urls", data={"original_url": "https://example.com/x", "custom_alias": "a"})
    assert response.status == 422  # below the 3-char minimum


def test_soft_deleted_link_is_gone_from_redirect_and_get(api_context) -> None:
    created = api_context.post("/api/urls", data={"original_url": "https://example.com/deleteme"}).json()
    code = created["code"]

    delete_response = api_context.delete(f"/api/urls/{code}")
    assert delete_response.status == 204

    assert api_context.get(f"/{code}", max_redirects=0).status == 404


def test_deleting_unknown_code_returns_404(api_context) -> None:
    assert api_context.delete("/api/urls/doesnotexist").status == 404


def test_concurrent_requests_for_same_alias_only_one_succeeds(live_server) -> None:
    """Regression test for the check-then-insert race a naive implementation
    would have: fire N simultaneous creates for the same brand-new alias and
    assert exactly one gets 201 and the rest get 409 — never two 201s."""
    alias = f"race-{uuid.uuid4().hex[:8]}"

    def attempt(_: int) -> int:
        with httpx.Client(base_url=live_server, timeout=5) as client:
            response = client.post("/api/urls", json={"original_url": "https://example.com/race", "custom_alias": alias})
            return response.status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        statuses = list(pool.map(attempt, range(10)))

    assert statuses.count(201) == 1
    assert statuses.count(409) == 9


def test_create_rate_limit_returns_429_once_exceeded(rate_limited_api_context) -> None:
    statuses = []
    for i in range(5):
        response = rate_limited_api_context.post(
            "/api/urls", data={"original_url": f"https://example.com/rl-{i}"}
        )
        statuses.append(response.status)

    assert 201 in statuses
    assert 429 in statuses
