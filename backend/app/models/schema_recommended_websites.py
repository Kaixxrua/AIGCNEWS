from __future__ import annotations

from datetime import datetime

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, TypeAdapter, field_validator

_URL_ADAPTER = TypeAdapter(AnyHttpUrl)


class RecommendedWebsiteRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2048)
    description: str = Field(default="", max_length=500)
    category: str = Field(default="", max_length=64)
    sort_order: int = Field(default=0, ge=-10000, le=10000)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if any(character.isspace() or ord(character) < 32 for character in value):
            raise ValueError("Website URL cannot contain whitespace")
        parsed = _URL_ADAPTER.validate_python(value)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Website URL cannot contain credentials")
        normalized = str(parsed)
        if len(normalized) > 2048:
            raise ValueError("Website URL is too long")
        return normalized


class RecommendedWebsiteResponse(RecommendedWebsiteRequest):
    id: int
    created_at: datetime
    updated_at: datetime


class RecommendedWebsitesResponse(BaseModel):
    items: list[RecommendedWebsiteResponse]
