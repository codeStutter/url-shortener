# Testing Approach, Limitations, and Trade-offs

> Evolves alongside the system. Current as of Scenario 3 (ambiguous analytics
> requirements) — the full three-scenario build.

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
`/api/health`, tear it down" is written once. A second fixture, `rate_limited_server`,
spawns an independent server instance with a deliberately tight `CREATE_RATE_LIMIT` so the
rate-limit test can actually trip the limiter without lowering it for every other test
that shares `live_server`.

Reliability-specific tests (`tests/api/test_reliability.py`) include a genuine concurrency
test: `test_concurrent_requests_for_same_alias_only_one_succeeds` fires 10 simultaneous
`POST /api/urls` requests for the same brand-new custom alias from a `ThreadPoolExecutor`
and asserts exactly one succeeds — this is what actually validates the
attempt-insert-and-catch-conflict design decision in `docs/scenarios/02-brownfield-reliability-hardening.md`,
rather than just asserting it in prose.

Analytics tests (`tests/api/test_analytics_api.py`, `tests/unit/test_crud.py`) cover both
directions of the write/read split: unit tests seed `ClickEvent` rows directly and assert
the aggregation logic (referrer ranking, `None` → `"direct"`, zero-filled day buckets),
while the API tests drive a real click through the live server and poll the analytics
endpoint until the backgrounded write lands — proving the two code paths actually agree,
not just that each one is individually correct in isolation.

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
- **No schema migration tool.** `Base.metadata.create_all()` creates missing tables but
  never alters existing ones, so a schema change like Scenario 2's new `is_active` column
  requires a fresh dev DB (gitignored, disposable) rather than an in-place migration.
  Alembic is the documented swap-in for a real deployment.
- **Rate limiting, soft-deleted rows, and click events have no cleanup story.** The
  limiter's counters live only in process memory (see Trade-offs below); soft-deleted
  short URLs and their click history accumulate with no purge/retention job. All fine at
  prototype scale, all named here rather than discovered later.
- **IP hashing is unsalted (`app/privacy.py`).** A real IP is never stored, but the same
  IP always hashes to the same value, so it's a stable fingerprint within this dataset —
  not a strong anonymization guarantee. A production system would rotate a per-day salt or
  drop IP capture entirely.
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

- **SQLite over Postgres, in-memory `slowapi` rate limiting over a Redis-backed limiter**:
  both chosen so anyone can clone the repo and run everything with zero external services.
  Documented explicitly as the first two things to swap for a real production deployment,
  precisely because they're the "prototype-friendly, not production-scale" calls in this
  design.
- **Attempt-and-catch over check-then-insert for alias conflicts**: slightly less obvious
  to read than a `SELECT` guard, but the guard has a real race under concurrency — see
  `docs/scenarios/02-brownfield-reliability-hardening.md`. Correctness was judged to
  outweigh the small readability cost.
- **Real subprocess server over in-process `TestClient`**: slower per-session startup, but
  higher-fidelity tests (see above) — judged worth it given the assessment explicitly asks
  for Playwright tests, which are most valuable when exercising a real running server.
