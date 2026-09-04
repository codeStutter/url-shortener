from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import crud
from app.config import settings
from app.db import get_db
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

    # Logged after the response is sent, so a slow analytics write never adds
    # latency to the redirect itself.
    background_tasks.add_task(crud.increment_click_count_background, code)
    return RedirectResponse(url=short_url.original_url, status_code=302)
