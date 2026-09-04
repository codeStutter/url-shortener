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


class URLResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    short_url: str
    original_url: str
    created_at: datetime
    expires_at: datetime | None
    click_count: int
