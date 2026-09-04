# URL Shortener — Prototype

A working URL-shortener service built from scratch. Built as an engineering-process
demonstration — see `docs/` for the architecture, the decomposition/execution/validation
record for three change scenarios (greenfield, brownfield, ambiguous), and the testing
approach. This README, like the rest of `docs/`, evolves with the system — currently
reflects the state after Scenario 2 (core APIs + custom aliases, rate limiting, soft
delete, background click logging).

## Stack

Python 3.11+, FastAPI, SQLAlchemy + SQLite, Jinja2 (minimal UI), pytest + Playwright
(Python) for unit/API/E2E tests. No Node/JS build step.

## Setup

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements-dev.txt   # includes runtime deps
cp .env.example .env                   # optional, defaults work out of the box

uvicorn app.main:app --reload
```

Open http://localhost:8000 for the UI, or http://localhost:8000/docs for the
auto-generated OpenAPI docs.

## Running the tests

```bash
# unit + API tests (no browser needed)
pytest tests/unit tests/api

# one-time browser binary install, then the E2E suite
playwright install chromium
pytest tests/e2e --browser chromium

# everything
pytest
```

See `docs/TESTING.md` for the full testing approach, known limitations, and trade-offs.

## API summary

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/urls` | Create a short URL (optional `custom_alias`, `expiry_days`) |
| `GET` | `/api/urls/{code}` | Metadata for a short URL |
| `DELETE` | `/api/urls/{code}` | Soft-delete a short URL |
| `GET` | `/{code}` | Redirect to the original URL |
| `GET` | `/api/health` | Liveness/readiness check |

`POST /api/urls` and `GET /{code}` are rate-limited (`CREATE_RATE_LIMIT` /
`REDIRECT_RATE_LIMIT` in `.env`); exceeding the limit returns `429`.

Full request/response schemas: http://localhost:8000/docs (once the app is running).

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — components, control flow, key decisions.
- [`docs/scenarios/`](docs/scenarios) — three worked scenarios (greenfield, brownfield,
  ambiguous), each showing decomposition, execution, and validation.
- [`docs/TESTING.md`](docs/TESTING.md) — testing approach, limitations, trade-offs.

## License

MIT — see [`LICENSE`](LICENSE).
