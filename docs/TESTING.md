# Testing Approach, Limitations, and Trade-offs

> Evolves alongside the system. Current as of Scenario 1 (greenfield core).

## Approach

Three layers, all runnable locally and in CI, all in Python:

1. **Unit** (`tests/unit/`) — pure logic and the persistence layer in isolation, against an
   in-memory SQLite DB. No HTTP, no subprocess. Fast (well under a second for the whole
   suite) and the first thing to run while iterating.
2. **API / integration** (`tests/api/`) — Playwright's `APIRequestContext` (its `pytest`
   fixtures come from `pytest-playwright`) driven against a **real `uvicorn` process**
   spawned as a subprocess for the test session (`tests/conftest.py::live_server`), on a
   random free port, against a temp SQLite file — never the developer's own `data/` DB.
   Deliberately *not* FastAPI's in-process `TestClient`: the goal is to exercise the same
   network path (real HTTP, real redirects, real headers) a genuine client would see. This
   is also what caught a real SQLite timezone bug during Scenario 1 — an in-process mock of
   the DB would not have.
3. **End-to-end / browser** (`tests/e2e/`) — Playwright driving a real headless Chromium
   against the same live server, exercising the actual HTML/JS UI a user would click
   through, including an error-path test.

All three layers share the `live_server` fixture, so "start the app, wait for
`/api/health`, tear it down" is written once.

## Running the suite

```bash
pytest tests/unit tests/api          # fast layers, no browser needed
playwright install chromium           # one-time browser binary install
pytest tests/e2e --browser chromium   # browser layer
```

## CI

`.github/workflows/ci.yml` runs unit+API tests on every push/PR (fast, no browser install),
and a separate job installs Chromium and runs the E2E suite — so a slow browser install
never blocks fast feedback on the majority of the test suite.

## Limitations (explicit, not hidden)

- **Single-instance SQLite.** No tested story for concurrent writers at scale, replication,
  or backup/restore. Fine for a prototype; the SQLAlchemy layer is the deliberate seam for
  swapping to Postgres later without touching route/business logic.
- **No auth/authz.** Every API is open. Explicit scope cut for a prototype, not an
  oversight — flagged here rather than silently shipped.
- **No load/performance testing.** Correctness and behavior are covered; throughput and
  latency under load are not measured or claimed.
- **Tests assume a free local port and the ability to spawn a subprocess.** This is normal
  for a dev machine or CI runner but wouldn't work as-is in a fully sandboxed/offline
  container without adjustment.
- **E2E coverage is intentionally narrow** — one happy path and one error path through the
  UI, not exhaustive UI coverage. The API layer carries the bulk of behavioral coverage
  because it's faster and less brittle than browser automation; E2E exists to prove the UI
  and API are actually wired together correctly, not to re-test business logic already
  covered at the API layer.

## Trade-offs

- **SQLite over Postgres, in-memory rate limiting over Redis** (rate limiting is added in
  Scenario 2): both chosen so anyone can clone the repo and run everything with zero
  external services. Documented explicitly as the first two things to swap for a real
  production deployment, precisely because they're the "prototype-friendly, not
  production-scale" calls in this design.
- **Real subprocess server over in-process `TestClient`**: slower per-session startup, but
  higher-fidelity tests (see above) — judged worth it given the assessment explicitly asks
  for Playwright tests, which are most valuable when exercising a real running server.
