def test_health_check_ok(api_context) -> None:
    response = api_context.get("/api/health")
    assert response.status == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
