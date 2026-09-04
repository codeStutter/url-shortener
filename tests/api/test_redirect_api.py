def test_redirect_returns_302_to_original_url(api_context, live_server) -> None:
    target = f"{live_server}/demo/target"
    created = api_context.post("/api/urls", data={"original_url": target}).json()

    response = api_context.get(f"/{created['code']}", max_redirects=0)

    assert response.status == 302
    assert response.headers["location"] == target


def test_redirect_increments_click_count(api_context, live_server) -> None:
    # Click logging runs as a FastAPI BackgroundTask *after* the redirect
    # response is sent (see app/routes/redirect.py), so the counter update
    # isn't guaranteed to be visible the instant the redirect call returns.
    # Poll briefly instead of asserting immediately, to avoid a flaky test.
    import time

    target = f"{live_server}/demo/target"
    created = api_context.post("/api/urls", data={"original_url": target}).json()

    api_context.get(f"/{created['code']}", max_redirects=0)
    api_context.get(f"/{created['code']}", max_redirects=0)

    deadline = time.time() + 2
    click_count = None
    while time.time() < deadline:
        click_count = api_context.get(f"/api/urls/{created['code']}").json()["click_count"]
        if click_count == 2:
            break
        time.sleep(0.05)

    assert click_count == 2


def test_redirect_unknown_code_returns_404(api_context) -> None:
    response = api_context.get("/doesnotexist", max_redirects=0)
    assert response.status == 404


def test_redirect_actually_reaches_target_page(api_context, live_server) -> None:
    target = f"{live_server}/demo/target"
    created = api_context.post("/api/urls", data={"original_url": target}).json()

    response = api_context.get(f"/{created['code']}")  # follows the redirect
    assert response.status == 200
    assert "You made it" in response.text()
