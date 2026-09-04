def test_redirect_returns_302_to_original_url(api_context, live_server) -> None:
    target = f"{live_server}/demo/target"
    created = api_context.post("/api/urls", data={"original_url": target}).json()

    response = api_context.get(f"/{created['code']}", max_redirects=0)

    assert response.status == 302
    assert response.headers["location"] == target


def test_redirect_increments_click_count(api_context, live_server) -> None:
    target = f"{live_server}/demo/target"
    created = api_context.post("/api/urls", data={"original_url": target}).json()

    api_context.get(f"/{created['code']}", max_redirects=0)
    api_context.get(f"/{created['code']}", max_redirects=0)

    metadata = api_context.get(f"/api/urls/{created['code']}").json()
    assert metadata["click_count"] == 2


def test_redirect_unknown_code_returns_404(api_context) -> None:
    response = api_context.get("/doesnotexist", max_redirects=0)
    assert response.status == 404


def test_redirect_actually_reaches_target_page(api_context, live_server) -> None:
    target = f"{live_server}/demo/target"
    created = api_context.post("/api/urls", data={"original_url": target}).json()

    response = api_context.get(f"/{created['code']}")  # follows the redirect
    assert response.status == 200
    assert "You made it" in response.text()
