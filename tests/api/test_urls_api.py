def test_create_url_happy_path(api_context) -> None:
    response = api_context.post("/api/urls", data={"original_url": "https://example.com/some/path"})
    assert response.status == 201
    body = response.json()
    assert body["code"]
    assert body["original_url"] == "https://example.com/some/path"
    assert body["click_count"] == 0
    assert body["short_url"].endswith(body["code"])


def test_create_url_rejects_non_http_scheme(api_context) -> None:
    response = api_context.post("/api/urls", data={"original_url": "ftp://example.com/file"})
    assert response.status == 422


def test_create_url_rejects_malformed_url(api_context) -> None:
    response = api_context.post("/api/urls", data={"original_url": "not-a-url"})
    assert response.status == 422


def test_create_url_rejects_missing_field(api_context) -> None:
    response = api_context.post("/api/urls", data={})
    assert response.status == 422


def test_get_url_metadata_after_create(api_context) -> None:
    created = api_context.post("/api/urls", data={"original_url": "https://example.com/meta"}).json()
    response = api_context.get(f"/api/urls/{created['code']}")
    assert response.status == 200
    assert response.json()["original_url"] == "https://example.com/meta"


def test_get_url_metadata_unknown_code_returns_404(api_context) -> None:
    response = api_context.get("/api/urls/doesnotexist")
    assert response.status == 404


def test_two_creates_of_same_url_get_distinct_codes(api_context) -> None:
    first = api_context.post("/api/urls", data={"original_url": "https://example.com/dup"}).json()
    second = api_context.post("/api/urls", data={"original_url": "https://example.com/dup"}).json()
    assert first["code"] != second["code"]
