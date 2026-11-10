from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_DESCRIPTION_REPOS = 50
# GitHub owner and repository path segments, excluding dot traversal and URLs.
_REPO = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9_.-]{1,100}")


def normalize_description_repo(value: str) -> str:
    if not isinstance(value, str) or not _REPO.fullmatch(value) or value.split("/")[-1] in {".", ".."}:
        raise ValueError("repo 须为有效的 GitHub owner/repo，不接受网址或路径")
    return value.lower()


class ProjectDescriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repo: str = Field(min_length=3, max_length=140, strict=True)
    gameDetails: bool = Field(default=False, strict=True)
    refreshPoster: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def poster_requires_game_details(self):
        if self.refreshPoster and not self.gameDetails:
            raise ValueError("refreshPoster 需要 gameDetails=true")
        return self

    @field_validator("repo")
    @classmethod
    def valid_repo(cls, value: str) -> str:
        return normalize_description_repo(value)


class ProjectDescriptionItem(BaseModel):
    repo: str
    status: Literal["ready", "pending", "missing", "failed"]
    descriptionZh: str = ""
    source: Literal["aigcnews"] = "aigcnews"
    error: str | None = None
    retryAfter: int | None = None
    # Opt-in fields are absent from legacy responses, including cache misses.
    gameNameZh: str | None = None
    gameNameOriginal: str | None = None
    posterUrl: str | None = None
    posterSourceUrl: str | None = None
    posterKind: Literal["", "cover", "screenshot"] | None = None
    detailsVersion: Literal[1] | None = None
    posterStatus: Literal["ready", "missing", "unavailable"] | None = None
    posterRetryAfter: int | None = Field(default=None, ge=0)
    posterSearchVersion: Literal[0, 1] | None = None


class ProjectDescriptionsResponse(BaseModel):
    items: list[ProjectDescriptionItem]
    pollAfter: int = 3
