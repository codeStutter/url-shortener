from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class CreateURLRequest(BaseModel):
    original_url: HttpUrl = Field(..., description="The long URL to shorten. Must be http(s).")
    expiry_days: int | None = Field(
        default=None,
        ge=0,
        le=3650,
        description="Days until the link expires. 0 or omitted means it never expires.",
    )
    custom_alias: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_-]{3,30}$",
        description="Optional custom short code. 3-30 chars: letters, digits, - or _.",
    )


class URLResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    short_url: str
    original_url: str
    created_at: datetime
    expires_at: datetime | None
    click_count: int
    active: bool


class DailyClicks(BaseModel):
    date: str  # YYYY-MM-DD
    count: int


class ReferrerCount(BaseModel):
    referrer: str
    count: int


class AnalyticsResponse(BaseModel):
    code: str
    total_clicks: int
    clicks_last_24h: int
    clicks_by_day: list[DailyClicks]
    top_referrers: list[ReferrerCount]
