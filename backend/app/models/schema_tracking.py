"""Personal tracking contracts. Entitlements are never accepted from a client."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TrackingSource = Literal["all", "github", "arxiv", "news", "producthunt", "hackernews", "x", "dailyhot"]


class TrackingRuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Literal["keyword", "project"] = "keyword"
    query: str = Field(min_length=1, max_length=120)
    source: TrackingSource = "all"
    excludes: list[str] = Field(default_factory=list, max_length=10)
    star_threshold: int = Field(default=50, ge=1, le=100000)
    enabled: bool = True

    @field_validator("excludes")
    @classmethod
    def clean_excludes(cls, values: list[str]) -> list[str]:
        result = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if any(len(value) > 40 for value in result):
            raise ValueError("Exclude terms must be at most 40 characters")
        return result

    @model_validator(mode="after")
    def validate_query(self) -> TrackingRuleInput:
        if any(ord(char) < 32 for char in self.query):
            raise ValueError("Control characters are not allowed")
        if len(self.query.split()) > 8:
            raise ValueError("Use at most 8 keywords")
        if self.kind == "project":
            self.query = re.sub(r"^https://github\.com/", "", self.query, flags=re.I).rstrip("/")
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.query):
                raise ValueError("Use a GitHub owner/repository")
            self.source = "github"
        return self


class TrackingRule(TrackingRuleInput):
    id: int
    active: bool
    created_at: datetime


class TrackingSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    delivery_hour: int = Field(default=8, ge=0, le=23)
    channel_id: int | None = Field(default=None, gt=0)


class TrackingSettings(TrackingSettingsInput):
    last_checked_at: datetime | None = None


class TrackingItem(BaseModel):
    key: str
    observed_at: datetime
    title: str
    url: str
    summary: str
    source: str
    matched_rules: list[str] = Field(default_factory=list)


class TrackingSurge(BaseModel):
    query: str
    # 最近 24 小时的命中数
    count: int = Field(ge=0)
    # 前 7 天日均命中数（不计采集中断的日子），保留一位小数
    baseline: float = Field(ge=0)


class TrackingDigest(BaseModel):
    id: int
    issue_date: date
    items: list[TrackingItem]
    truncated: bool
    # vip 关键词热度飙升；免费账号和存量简报为空列表
    surges: list[TrackingSurge] = Field(default_factory=list)
    delivery_status: str
    created_at: datetime


class TrackingOverview(BaseModel):
    limit: int
    rules: list[TrackingRule]
    settings: TrackingSettings
    digests: list[TrackingDigest]


class TrackingExportRule(BaseModel):
    kind: str
    query: str
    source: str
    excludes: list[str]
    star_threshold: int
    enabled: bool
    created_at: datetime


class TrackingExport(BaseModel):
    exported_at: datetime
    # 导出范围起点：此后生成的简报（保留期 90 天）
    since: datetime
    rules: list[TrackingExportRule]
    digests: list[TrackingDigest]


class TrackingSourceCount(BaseModel):
    source: str
    count: int = Field(ge=0)


class TrackingExpansion(BaseModel):
    term: str
    aliases: list[str]
    exclude: bool


class TrackingPreview(BaseModel):
    items: list[TrackingItem]
    truncated: bool
    # Matches in the preview window; items list at most the newest 50 of them.
    total: int = Field(ge=0)
    sources: list[TrackingSourceCount]
    # English equivalents a Chinese keyword or exclusion also matched.
    expansions: list[TrackingExpansion]


class TrackingUnread(BaseModel):
    latest_digest_id: int = Field(ge=0)
    last_read_digest_id: int = Field(ge=0)
    unread: bool


class TrackingReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    digest_id: int = Field(gt=0, le=9007199254740991, strict=True)
