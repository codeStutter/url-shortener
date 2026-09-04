import time


def _poll_until(fn, predicate, timeout=2.0, interval=0.05):
    deadline = time.time() + timeout
    result = None
    while time.time() < deadline:
        result = fn()
        if predicate(result):
            return result
        time.sleep(interval)
    return result


def test_analytics_unknown_code_returns_404(api_context) -> None:
    response = api_context.get("/api/urls/doesnotexist/analytics")
    assert response.status == 404


def test_analytics_starts_at_zero(api_context) -> None:
    created = api_context.post("/api/urls", data={"original_url": "https://example.com/fresh"}).json()
    response = api_context.get(f"/api/urls/{created['code']}/analytics")
    assert response.status == 200
    body = response.json()
    assert body["total_clicks"] == 0
    assert body["clicks_last_24h"] == 0
    assert len(body["clicks_by_day"]) == 7
    assert body["top_referrers"] == []


def test_analytics_reflects_clicks_and_referrer(api_context, live_server) -> None:
    target = f"{live_server}/demo/target"
    created = api_context.post("/api/urls", data={"original_url": target}).json()
    code = created["code"]

    # Click logging happens in a BackgroundTask after the redirect response,
    # so poll the analytics endpoint briefly instead of asserting instantly.
    api_context.get(f"/{code}", max_redirects=0, headers={"referer": "https://search.example/results"})

    analytics = _poll_until(
        lambda: api_context.get(f"/api/urls/{code}/analytics").json(),
        lambda body: body["total_clicks"] >= 1,
    )

    assert analytics["total_clicks"] == 1
    assert analytics["clicks_last_24h"] == 1
    assert analytics["top_referrers"] == [{"referrer": "https://search.example/results", "count": 1}]


def test_analytics_survives_soft_delete(api_context) -> None:
    created = api_context.post("/api/urls", data={"original_url": "https://example.com/soon-deleted"}).json()
    code = created["code"]

    api_context.get(f"/{code}", max_redirects=0)
    _poll_until(
        lambda: api_context.get(f"/api/urls/{code}/analytics").json(),
        lambda body: body["total_clicks"] >= 1,
    )

    api_context.delete(f"/api/urls/{code}")

    # History is preserved even after the link itself is retired.
    response = api_context.get(f"/api/urls/{code}/analytics")
    assert response.status == 200
    assert response.json()["total_clicks"] == 1
