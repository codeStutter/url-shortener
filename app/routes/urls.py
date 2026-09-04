from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import crud
from app.config import settings
from app.db import get_db
from app.exceptions import AliasConflictError
from app.rate_limit import limiter
from app.schemas import CreateURLRequest, URLResponse
from app.shortener import RESERVED_CODES

router = APIRouter(prefix="/api/urls", tags=["urls"])


def _to_response(short_url) -> URLResponse:
    return URLResponse(
        code=short_url.code,
        short_url=f"{settings.base_url.rstrip('/')}/{short_url.code}",
        original_url=short_url.original_url,
        created_at=short_url.created_at,
        expires_at=short_url.expires_at,
        click_count=short_url.click_count,
        active=short_url.is_active,
    )


@router.post("", response_model=URLResponse, status_code=201)
@limiter.limit(settings.create_rate_limit)
def create_url(request: Request, payload: CreateURLRequest, db: Session = Depends(get_db)) -> URLResponse:
    if payload.custom_alias and payload.custom_alias.lower() in RESERVED_CODES:
        raise HTTPException(status_code=400, detail=f"'{payload.custom_alias}' is a reserved path and can't be used as an alias")

    try:
        short_url = crud.create_short_url(
            db, str(payload.original_url), payload.expiry_days, payload.custom_alias
        )
    except AliasConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _to_response(short_url)


@router.get("/{code}", response_model=URLResponse)
def get_url(code: str, db: Session = Depends(get_db)) -> URLResponse:
    short_url = crud.get_by_code(db, code)
    if short_url is None:
        raise HTTPException(status_code=404, detail="Short URL not found")
    return _to_response(short_url)


@router.delete("/{code}", status_code=204)
def delete_url(code: str, db: Session = Depends(get_db)) -> None:
    # Soft delete: preserves the row (and its click history) rather than
    # hard-deleting, so analytics for a retired link remain queryable.
    deleted = crud.soft_delete(db, code)
    if not deleted:
        raise HTTPException(status_code=404, detail="Short URL not found")
