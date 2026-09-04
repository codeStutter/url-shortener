from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import crud
from app.db import get_db

router = APIRouter(tags=["redirect"])


@router.get("/{code}")
def redirect_to_original(code: str, db: Session = Depends(get_db)) -> RedirectResponse:
    short_url = crud.get_by_code(db, code)
    if short_url is None:
        raise HTTPException(status_code=404, detail="Short URL not found")
    if crud.is_expired(short_url):
        raise HTTPException(status_code=410, detail="This short URL has expired")

    crud.increment_click_count(db, code)
    return RedirectResponse(url=short_url.original_url, status_code=302)
