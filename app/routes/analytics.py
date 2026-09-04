from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import crud
from app.db import get_db
from app.schemas import AnalyticsResponse

router = APIRouter(prefix="/api/urls", tags=["analytics"])


@router.get("/{code}/analytics", response_model=AnalyticsResponse)
def get_analytics(code: str, db: Session = Depends(get_db)) -> AnalyticsResponse:
    short_url = crud.get_by_code(db, code)
    if short_url is None:
        raise HTTPException(status_code=404, detail="Short URL not found")
    return crud.get_analytics(db, short_url)
