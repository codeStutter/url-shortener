# Scenario 2 — Brownfield: reliability hardening

**Type:** Brownfield (enhancement of an existing, already-shipped system)

## Requirement

> ...and reliability features.

Building on the greenfield core (Scenario 1), harden it: protect against abuse, handle
concurrent writes safely, support link lifecycle management (custom names, retiring a
link), and keep redirect latency low. Unlike Scenario 1, this isn't new-system design —
every change here has to fit into code and a schema that already exist and are already
covered by a passing test suite that must keep passing.

## Decomposition

1. **Custom aliases** — users want memorable short links, not just base62 codes. This is
   new user-facing surface, decomposed into: request-schema validation (allowed
   characters/length), reserved-path protection (an alias can't shadow `/api`, `/docs`,
   etc.), and safe conflict handling.
2. **Concurrency safety for aliases** — the moment two people can request the same alias,
   there's a race to reason about explicitly, not just "add a uniqueness check".
3. **Abuse protection** — nothing currently stops one client from hammering `POST
   /api/urls` or the redirect endpoint. Needed before this could be called "reliable".
4. **Link lifecycle** — a `DELETE` was implied by "reliability" (the ability to retire a
   bad/compromised link) but wasn't specified; decided to preserve history rather than
   hard-delete (see decision below).
5. **Redirect latency** — the existing redirect handler does a synchronous DB write
   (click-count increment) in the hot path before responding.

## Execution

- **Custom alias = the `code` field, directly.** Rather than adding a separate
  `custom_alias` column alongside the generated `code`, a supplied alias *becomes* the
  code (`app/crud.py::create_short_url`). One lookup column, one unique index, no dual
  code paths in the redirect handler.
- **Concurrency decision, made before writing the happy path**: a naive implementation
  would `SELECT` for the alias, and if absent, `INSERT`. That has a TOCTOU race — two
  concurrent requests can both pass the `SELECT` before either commits. Instead, the insert
  is attempted directly and the database's own unique constraint on `code` is the
  authority; a caught `IntegrityError` becomes `AliasConflictError` becomes an HTTP `409`
  (`app/crud.py`, `app/exceptions.py`, `app/routes/urls.py`). This is proven, not just
  argued: `tests/api/test_reliability.py::test_concurrent_requests_for_same_alias_only_one_succeeds`
  fires 10 simultaneous requests for one brand-new alias via a `ThreadPoolExecutor` and
  asserts exactly one `201` and nine `409`s.
- **Rate limiting via `slowapi`** (`app/rate_limit.py`, wired in `app/main.py`), with
  separate, independently configurable limits for creates vs. redirects
  (`CREATE_RATE_LIMIT` / `REDIRECT_RATE_LIMIT` in `.env`) — creating a link is more
  expensive and more abuse-prone than following one, so it gets the tighter default.
- **Soft delete, not hard delete**: `DELETE /api/urls/{code}` sets `is_active = false`
  rather than removing the row (`app/models.py` gains `is_active`; `app/crud.py::soft_delete`).
  A retired link's click history stays queryable — relevant once Scenario 3 adds analytics
  — and the redirect/lookup paths simply treat an inactive row as not-found.
- **Click logging moved off the request path**: `app/routes/redirect.py` now schedules
  `crud.increment_click_count_background` via FastAPI's `BackgroundTasks` instead of
  writing synchronously before responding. That function opens its **own** DB session
  rather than reusing the request's, because a background task runs after the response is
  sent — by which point the request-scoped session from `Depends(get_db)` may already be
  closed.
- **No schema migration tooling added.** `Base.metadata.create_all()` only adds new
  *tables*, not new *columns* on existing tables — so a developer's pre-existing
  `data/shortener.db` from before this change would not automatically gain `is_active`.
  Not a real problem for a prototype (the DB is gitignored and disposable), but it's a real
  limitation of the current setup, called out explicitly here and in `docs/TESTING.md`
  rather than silently left for someone to hit later. Alembic is the documented swap-in for
  a production system.

## Validation

- **Unit** (`tests/unit/test_crud.py`): custom alias becomes the code; duplicate alias
  raises `AliasConflictError`; soft delete deactivates and is idempotent against a missing
  code; the background click-increment path exercised against its own throwaway DB
  (monkeypatching `app.db.SessionLocal`, not reusing the in-memory fixture DB, to actually
  exercise the "opens its own session" code path).
- **API** (`tests/api/test_reliability.py`): custom alias happy path, duplicate alias
  `409`, reserved-path alias `400`, malformed alias `422`, soft-deleted link returns `404`
  from both redirect and metadata lookup, deleting an unknown code is `404` not a silent
  no-op, the concurrency race test described above, and a rate-limit test against a
  **dedicated** low-limit server instance (`rate_limited_server` fixture) so tightening the
  limit for this one test can't make every other test flaky.
- **Regression check on existing behavior**: `test_redirect_increments_click_count` had to
  be updated to poll briefly instead of asserting immediately, since the click count is now
  updated asynchronously after the redirect response — a deliberate, documented behavior
  change to an existing, already-passing test, not a bug.

Result at the end of this scenario: 24 unit tests, 20 API tests, 2 E2E tests, all passing.
