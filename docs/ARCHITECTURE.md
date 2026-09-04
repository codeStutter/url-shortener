# Architecture Overview

> This document evolves with the system. It currently reflects the state after
> Scenario 2 (brownfield reliability hardening). See `docs/scenarios/` for the
> change-by-change history.

## Components

```
                 ┌────────────────────────────┐
  Browser/API ──▶│     FastAPI app (app/)     │
   client         │  ┌───────────────────────┐ │
                  │  │ SlowAPI rate limiter   │ │  per-route @limiter.limit(...)
                  │  ├───────────────────────┤ │
                  │  │ routes/urls.py        │ │  POST/GET/DELETE /api/urls...
                  │  │ routes/redirect.py    │ │  GET /{code} -> 302 (+ BackgroundTask)
                  │  │ routes/health.py      │ │  GET /api/health
                  │  └───────────┬───────────┘ │
                  │              │ crud.py       │  (query/command layer)
                  │              ▼               │
                  │  ┌───────────────────────┐ │
                  │  │ SQLAlchemy models      │ │  models.py: ShortUrl (+ is_active)
                  │  └───────────┬───────────┘ │
                  └──────────────┼──────────────┘
                                  ▼
                        SQLite file (data/shortener.db)
```

- **`app/main.py`** — FastAPI app assembly: mounts static files, wires Jinja2 templates,
  initializes the DB on startup (`lifespan`), and registers routers. Order matters: the
  catch-all `GET /{code}` redirect router is registered *last* so it can't shadow
  `/api/...` routes.
- **`app/routes/`** — one module per concern (urls, redirect, health) rather than one flat
  file, so each route group can grow (e.g. rate limits, new sub-resources) without the
  others' code shifting.
- **`app/crud.py`** — the only module that talks to the ORM session directly. Routes call
  into it rather than building queries inline, which is what makes `tests/unit/test_crud.py`
  possible without an HTTP layer at all.
- **`app/shortener.py`** — pure functions (`encode_base62`/`decode_base62`), no I/O. Kept
  separate from `crud.py` because it's the one piece of genuinely non-obvious logic in the
  system and deserves isolated unit tests.
- **`app/config.py`** — a single `pydantic-settings` `Settings` object sourced from
  environment variables / `.env`, so the same code runs locally, in CI, and (with different
  env vars) in a real deployment without code changes.
- **`app/rate_limit.py`** — a single shared `slowapi.Limiter` instance, applied per-route
  with `@limiter.limit(...)` so create and redirect traffic can have independent limits.
- **`app/exceptions.py`** — small domain exceptions (currently `AliasConflictError`)
  raised by `crud.py` and translated to HTTP status codes in the route layer, keeping
  `crud.py` free of any FastAPI/HTTP imports.

## Control flow

**Create:**
`POST /api/urls` → rate limit check (`CREATE_RATE_LIMIT`) → Pydantic validates
`original_url` is a well-formed `http(s)` URL and, if present, `custom_alias` matches the
allowed pattern → reserved-path check on the alias → `crud.create_short_url`:
  - no alias: insert with a placeholder code, flush to get the autoincrement id,
    base62-encode it into `code`, commit.
  - alias given: insert with `code = alias` directly; the DB's unique constraint on `code`
    is the single source of truth for "is this alias taken" (see Scenario 2 in
    `docs/scenarios/` for why this beats a check-then-insert).
  - a unique-constraint violation becomes `AliasConflictError` → HTTP `409`.

Response includes the full short link (`{BASE_URL}/{code}`).

**Redirect:**
`GET /{code}` → rate limit check (`REDIRECT_RATE_LIMIT`) → look up the row → `404` if
missing or soft-deleted (`is_active = false`); `410` if past `expires_at` → schedule a
`BackgroundTask` to increment the click counter (using its own DB session, since the
request's session may be closed by the time the task runs) → `302` to `original_url`,
sent immediately — the click write never adds to redirect latency.

**Delete:**
`DELETE /api/urls/{code}` → soft delete (`is_active = false`); the row and its click
history are kept, not removed.

## Key decisions

| Decision | Rationale | Trade-off accepted |
|---|---|---|
| Base62(autoincrement id) instead of random+retry codes | O(1), no collision handling needed, trivially unique | Codes are sequential/guessable — acceptable for a prototype with no auth; would move to a random/opaque scheme for a public production system where enumerability matters |
| SQLite via SQLAlchemy (not raw `sqlite3`) | Zero setup for anyone running the prototype; SQLAlchemy means swapping to Postgres later is a connection-string change, not a rewrite | Single-file DB doesn't support concurrent writers well — fine at prototype scale, flagged as a scale limit in `docs/TESTING.md` |
| FastAPI + Pydantic for request validation | Validation, serialization, and OpenAPI docs come for free and are enforced at the boundary, not scattered through handlers | None significant for this use case |
| Soft dependency boundary: routes → crud → models | Keeps HTTP concerns out of the persistence layer, so persistence logic is unit-testable without spinning up the app | One extra layer of indirection for a prototype this small |
| Tests run against a real spawned `uvicorn` process, not FastAPI's in-process `TestClient` | Playwright's browser and HTTP clients exercise the exact network path a real client would use; also what actually caught the SQLite timezone-naive datetime bug during Scenario 1 (see `docs/scenarios/01-greenfield-core-shortener.md`) | Slower test startup (~sub-second per session) than an in-process client |
| Attempt-insert-and-catch-`IntegrityError` for alias conflicts, instead of check-then-insert | Eliminates a real TOCTOU race under concurrent requests for the same alias; the DB constraint is the single source of truth | Relies on the DB engine enforcing the unique constraint correctly — true for SQLite/Postgres, would need re-verifying on an eventually-consistent store |
| Custom alias reuses the `code` column instead of adding a separate `custom_alias` column | One lookup path, one unique index, no dual-code-path branching in the redirect handler | A generated code and a custom alias are indistinguishable at the storage layer (not currently a problem — nothing needs to tell them apart) |
| Soft delete (`is_active` flag) instead of hard delete | Preserves click history for a retired link, which Scenario 3's analytics depend on | Deleted rows accumulate in the table forever — no purge/archival job exists (documented limitation) |
| Click logging via `BackgroundTasks` with its own DB session | Redirect response is sent before the DB write happens, so click logging can never slow down a redirect | If the process crashes between sending the redirect and the background task running, that one click is lost — acceptable for a best-effort counter, would need a durable queue if click counts had to be exact |
| In-memory `slowapi` rate limiting | No external dependency (Redis) needed to run the prototype | Limits are per-process and reset on restart; not correct across multiple app instances — documented swap-in is a Redis storage backend, which `slowapi` supports via config |
