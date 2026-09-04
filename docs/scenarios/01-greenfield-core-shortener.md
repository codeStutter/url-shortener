# Scenario 1 — Greenfield: core URL shortener

**Type:** Greenfield (new system, well-defined requirement)

## Requirement

> Build a URL shortener service from scratch with core APIs, analytics, and reliability
> features.

This scenario covers the "core APIs" slice only: turn a long URL into a short one, redirect
through it, and let a caller look up what a code points to. Analytics and reliability
hardening are deliberately out of scope here — see Scenarios 2 and 3.

## Decomposition

The requirement was well-defined enough to break down directly into tasks, in dependency
order:

1. **Storage model** — what does a "short URL" record need to exist at all? (`app/models.py`)
2. **Code generation** — how do we turn a stored row into a short, unique code, without a
   collision-retry loop? (`app/shortener.py`)
3. **Create path** — validate an inbound long URL, persist it, return a short link.
   (`app/schemas.py`, `app/crud.py`, `app/routes/urls.py` POST)
4. **Read path** — fetch metadata for a code. (`app/routes/urls.py` GET)
5. **Redirect path** — the actual "shortener" behavior: `GET /{code}` → 302 to the
   original URL, with a naive click counter. (`app/routes/redirect.py`)
6. **Operational baseline** — a health endpoint or the system can't be deployed/monitored
   at all. (`app/routes/health.py`)
7. **A thin UI** — not asked for explicitly, but needed for the assessment's own "runnable
   end-to-end" and Playwright-E2E requirements; a human/browser needs a way to exercise the
   API without curl. (`app/templates/index.html`, `app/main.py`)

## Execution

- **Code generation strategy**: base62-encode the row's auto-increment primary key
  (`app/shortener.py`) instead of generating a random string and retrying on collision.
  The database already guarantees the id is unique, so this makes code generation O(1)
  with zero retry logic — a smaller, more testable surface than random-with-retry.
- **Validation at the boundary**: `CreateURLRequest` uses Pydantic's `HttpUrl` type, so
  `http(s)://` and general URL well-formedness are rejected before they ever reach the
  database layer, with FastAPI producing a structured `422` automatically.
- **Two-phase create**: `crud.create_short_url` inserts with a placeholder code, flushes to
  obtain the autoincrement id, encodes it, then commits — the code and the row are created
  in the same transaction, so there's never a row with a missing/invalid code visible to
  another request.
- **Routing order matters**: `GET /{code}` is a catch-all path, so it's registered in
  `app/main.py` *after* `/api/...` routes — otherwise it would shadow every API route.
- **A same-app demo target** (`GET /demo/target`) was added specifically so later tests
  (and manual demos) can redirect somewhere real without depending on the public internet.

## Validation

- **Unit** (`tests/unit/test_shortener.py`, `tests/unit/test_crud.py`): base62
  encode/decode round-trips, uniqueness across 5000 sequential ids, negative-input
  rejection, create/get/increment/expiry-check behavior against an in-memory SQLite DB.
- **API** (`tests/api/test_urls_api.py`, `test_redirect_api.py`, `test_health_api.py`):
  Playwright's `APIRequestContext` against a real, locally-spawned `uvicorn` process (not
  an in-process test client) — create happy path, rejected malformed/non-http URLs,
  metadata lookup, 404 on unknown codes, redirect returns a real `302` with the correct
  `Location` header, click count increments, and the redirect actually resolves to the
  demo target page.
- **E2E** (`tests/e2e/test_ui_flow.py`): a real Chromium browser (via Playwright) fills in
  the form, submits, follows the resulting short link, and lands on the target page; a
  second test confirms an invalid URL surfaces the inline error instead of silently
  failing.
- **A real bug surfaced during validation**: the first version of
  `test_expiry_days_sets_future_timestamp` compared a timezone-aware `datetime.now(utc)`
  against `short_url.expires_at` fetched back from SQLite — and failed, because SQLite
  does not persist timezone info, so a value written as UTC-aware comes back naive after a
  refresh. `crud.is_expired()` already normalized for this; the test was fixed to do the
  same, and it's called out here because it's exactly the kind of storage-layer gotcha
  that's easy to miss without running the tests against the real database engine (an
  in-memory mock would not have caught it).

Result at the end of this scenario: 20 unit tests, 12 API tests, 2 E2E tests, all passing.
