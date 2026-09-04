from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.db import init_db
from app.rate_limit import limiter
from app.routes import health, redirect, urls

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="URL Shortener", version="0.1.0", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/demo/target", response_class=HTMLResponse)
def demo_target() -> HTMLResponse:
    """A same-app static landing page used as a safe, network-independent
    redirect target for manual demos and end-to-end tests."""
    return HTMLResponse(
        "<html><body><h1 id='demo-target-heading'>You made it!</h1>"
        "<p>This is the destination page the short link redirected to.</p></body></html>"
    )


# Routers: API routes first, then the catch-all "/{code}" redirect last so it
# never shadows a more specific path.
app.include_router(urls.router)
app.include_router(health.router)
app.include_router(redirect.router)
