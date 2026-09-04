"""Shared fixtures.

API and E2E tests run against a real, locally-spawned uvicorn process (not
FastAPI's in-process TestClient) so that Playwright's browser and HTTP
clients exercise the exact same network path a real client would use. Each
test session gets its own temp SQLite file, so tests never touch the
developer's local ``data/shortener.db``.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_health(base_url: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            response = httpx.get(f"{base_url}/api/health", timeout=1)
            if response.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(0.2)
    raise RuntimeError(f"Server did not become healthy in time: {last_error}")


@pytest.fixture(scope="session")
def live_server(tmp_path_factory) -> str:
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    db_path = tmp_path_factory.mktemp("data") / "test.db"

    env = os.environ.copy()
    env["DATABASE_PATH"] = str(db_path)
    env["BASE_URL"] = base_url
    # Generous limits: reliability tests exercise the limiter explicitly via
    # their own low-limit server instance instead of this shared one.
    env["CREATE_RATE_LIMIT"] = "1000/minute"
    env["REDIRECT_RATE_LIMIT"] = "1000/minute"

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    try:
        _wait_for_health(base_url)
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture()
def api_context(playwright, live_server):
    request_context = playwright.request.new_context(base_url=live_server)
    yield request_context
    request_context.dispose()
