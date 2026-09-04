from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import crud
from app.config import settings
from app.db import get_db
from app.privacy import hash_ip
from app.rate_limit import limiter

router = APIRouter(tags=["redirect"])


@router.get("/{code}")
@limiter.limit(settings.redirect_rate_limit)
def redirect_to_original(
    request: Request,
    code: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    short_url = crud.get_by_code(db, code)
    if short_url is None or not short_url.is_active:
        raise HTTPException(status_code=404, detail="Short URL not found")
    if crud.is_expired(short_url):
        raise HTTPException(status_code=410, detail="This short URL has expired")

    # Captured now (while the request is available) but written after the
    # response is sent, so a slow analytics write never adds latency to the
    # redirect itself. The client IP is hashed, never stored raw — see
    # app/privacy.py.
    referrer = request.headers.get("referer")
    user_agent = request.headers.get("user-agent")
    ip_hash = hash_ip(request.client.host) if request.client else None
    background_tasks.add_task(
        crud.record_click_background, short_url.id, code, referrer, user_agent, ip_hash
    )

    return RedirectResponse(url=short_url.original_url, status_code=302)
