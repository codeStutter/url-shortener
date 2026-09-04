# Architecture Overview

> This document evolves with the system. It currently reflects the state after
> Scenario 1 (greenfield core). See `docs/scenarios/` for the change-by-change history.

## Components

```
                 ┌───────────────────────┐
  Browser/API ──▶│   FastAPI app (app/)  │
   client         │  ┌──────────────────┐ │
                  │  │ routes/urls.py   │ │  POST/GET /api/urls...
                  │  │ routes/redirect  │ │  GET /{code} -> 302
                  │  │ routes/health    │ │  GET /api/health
                  │  └────────┬─────────┘ │
                  │           │ crud.py    │  (query/command layer)
                  │           ▼            │
                  │  ┌──────────────────┐ │
                  │  │ SQLAlchemy models │ │  models.py: ShortUrl
                  │  └────────┬─────────┘ │
                  └───────────┼───────────┘
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

## Control flow

**Create:**
`POST /api/urls` → Pydantic validates `original_url` is a well-formed `http(s)` URL →
`crud.create_short_url` inserts a row, flushes to get the autoincrement id, base62-encodes
it into `code`, commits → response includes the full short link
(`{BASE_URL}/{code}`).

**Redirect:**
`GET /{code}` → look up the row → if missing, `404`; if expired, `410` → increment the
click counter → `302` to `original_url`.

## Key decisions

| Decision | Rationale | Trade-off accepted |
|---|---|---|
| Base62(autoincrement id) instead of random+retry codes | O(1), no collision handling needed, trivially unique | Codes are sequential/guessable — acceptable for a prototype with no auth; would move to a random/opaque scheme for a public production system where enumerability matters |
| SQLite via SQLAlchemy (not raw `sqlite3`) | Zero setup for anyone running the prototype; SQLAlchemy means swapping to Postgres later is a connection-string change, not a rewrite | Single-file DB doesn't support concurrent writers well — fine at prototype scale, flagged as a scale limit in `docs/TESTING.md` |
| FastAPI + Pydantic for request validation | Validation, serialization, and OpenAPI docs come for free and are enforced at the boundary, not scattered through handlers | None significant for this use case |
| Soft dependency boundary: routes → crud → models | Keeps HTTP concerns out of the persistence layer, so persistence logic is unit-testable without spinning up the app | One extra layer of indirection for a prototype this small |
| Tests run against a real spawned `uvicorn` process, not FastAPI's in-process `TestClient` | Playwright's browser and HTTP clients exercise the exact network path a real client would use; also what actually caught the SQLite timezone-naive datetime bug during Scenario 1 (see `docs/scenarios/01-greenfield-core-shortener.md`) | Slower test startup (~sub-second per session) than an in-process client |
