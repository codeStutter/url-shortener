from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import crud
from app.config import settings
from app.db import get_db
from app.schemas import CreateURLRequest, URLResponse

router = APIRouter(prefix="/api/urls", tags=["urls"])


def _to_response(short_url) -> URLResponse:
    return URLResponse(
        code=short_url.code,
        short_url=f"{settings.base_url.rstrip('/')}/{short_url.code}",
        original_url=short_url.original_url,
        created_at=short_url.created_at,
        expires_at=short_url.expires_at,
        click_count=short_url.click_count,
    )


@router.post("", response_model=URLResponse, status_code=201)
def create_url(payload: CreateURLRequest, db: Session = Depends(get_db)) -> URLResponse:
    short_url = crud.create_short_url(db, str(payload.original_url), payload.expiry_days)
    return _to_response(short_url)


@router.get("/{code}", response_model=URLResponse)
def get_url(code: str, db: Session = Depends(get_db)) -> URLResponse:
    short_url = crud.get_by_code(db, code)
    if short_url is None:
        raise HTTPException(status_code=404, detail="Short URL not found")
    return _to_response(short_url)
