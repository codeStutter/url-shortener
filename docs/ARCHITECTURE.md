# Architecture Overview

> This document evolves with the system. It currently reflects the state after
> Scenario 3 (ambiguous analytics requirements) — the full three-scenario build. See
> `docs/scenarios/` for the change-by-change history.

## Components

```
                 ┌────────────────────────────┐
  Browser/API ──▶│     FastAPI app (app/)     │
   client         │  ┌───────────────────────┐ │
                  │  │ SlowAPI rate limiter   │ │  per-route @limiter.limit(...)
                  │  ├───────────────────────┤ │
                  │  │ routes/urls.py        │ │  POST/GET/DELETE /api/urls...
                  │  │ routes/analytics.py   │ │  GET /api/urls/{code}/analytics
                  │  │ routes/redirect.py    │ │  GET /{code} -> 302 (+ BackgroundTask)
                  │  │ routes/health.py      │ │  GET /api/health
                  │  └───────────┬───────────┘ │
                  │              │ crud.py       │  (query/command layer)
                  │              ▼               │
                  │  ┌───────────────────────┐ │
                  │  │ SQLAlchemy models      │ │  models.py: ShortUrl, ClickEvent
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
- **`app/privacy.py`** — a single-purpose helper (`hash_ip`) so "never persist a raw IP"
  is enforced at one call site, not something every future caller has to remember.

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
missing or soft-deleted (`is_active = false`); `410` if past `expires_at` → capture
`referer`/`user-agent` headers and the hashed client IP from the live request → schedule a
`BackgroundTask` (`crud.record_click_background`, its own DB session, since the request's
session may be closed by the time the task runs) that inserts a `ClickEvent` row and
increments the click counter in one commit → `302` to `original_url`, sent immediately —
the analytics write never adds to redirect latency.

**Analytics:**
`GET /api/urls/{code}/analytics` → `404` if the code doesn't exist (soft-deleted links
still resolve here, since their `ClickEvent` rows aren't removed) → `crud.get_analytics`
computes a 24h rolling count, a zero-filled 7-day daily series, and the top 5 referrers
(`None` grouped as `"direct"`) from the `ClickEvent` table.

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
| Store per-click `ClickEvent` rows, not just aggregate counters | Time-series and referrer breakdowns need event-level data; aggregates can be derived from events but not the reverse | More storage than a counter-only design; no retention/purge policy exists yet (see `docs/scenarios/03-ambiguous-analytics-requirements.md`) |
| Hash the client IP (unsalted SHA-256) before storing, and never expose it via any API | No auth/consent flow exists in this prototype, so the safer default is not persisting PII in recoverable form | Unsalted means the same IP always hashes the same way — a stable fingerprint within this dataset, not strong anonymization; a per-day rotating salt is the documented next step if this became a real product |
| `ShortUrl.click_count` (fast total) kept alongside the `ClickEvent` log, updated in the same commit | Metadata reads stay O(1) instead of a `COUNT(*)` over events every time | Two representations of "how many clicks" that must be kept in sync by discipline (one shared function, `crud.record_click`, is the only writer of both) rather than by a DB constraint |
