from __future__ import annotations

import re
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

_HREF_SCHEME = re.compile(r"^(https?://|mailto:|tel:)", re.IGNORECASE)
_QR_URL_SCHEME = re.compile(r"^(https?://|/)", re.IGNORECASE)


class SiteContactServiceCardModel(BaseModel):
    """联系合作页服务卡片。icon 为短 key，由前端映射为内联 SVG。"""

    title: str = Field(min_length=1, max_length=50)
    description: str = Field(default="", max_length=500)
    icon: str = Field(default="", max_length=30)


class SiteContactEntryModel(BaseModel):
    """联系合作页联系方式条目。qr_image_url 允许站外 URL 或站内 /... 相对路径。"""

    label: str = Field(min_length=1, max_length=50)
    value: str = Field(default="", max_length=255)
    href: str = Field(default="", max_length=2048)
    qr_image_url: str = Field(default="", max_length=2048)

    @field_validator("href")
    @classmethod
    def _validate_href(cls, value: str) -> str:
        if value and not _HREF_SCHEME.match(value):
            raise ValueError("href 仅支持 http(s)://、mailto:、tel: 协议")
        return value

    @field_validator("qr_image_url")
    @classmethod
    def _validate_qr_image_url(cls, value: str) -> str:
        if value and not _QR_URL_SCHEME.match(value):
            raise ValueError("二维码图片仅支持 http(s):// URL 或站内 /... 相对路径")
        return value


class SiteContactPageRequest(BaseModel):
    """联系合作页保存请求。内容由管理员撰写，按单语言原样展示。"""

    enabled: bool = False
    nav_label: str = Field(default="", max_length=20)
    title: str = Field(default="", max_length=100)
    subtitle: str = Field(default="", max_length=255)
    service_cards: List[SiteContactServiceCardModel] = Field(default_factory=list, max_length=6)
    contact_entries: List[SiteContactEntryModel] = Field(default_factory=list, max_length=8)
    body_markdown: str = Field(default="", max_length=20000)

    @model_validator(mode="after")
    def _require_title_when_enabled(self) -> "SiteContactPageRequest":
        if self.enabled and not self.title.strip():
            raise ValueError("启用页面时标题不能为空")
        return self


class SiteContactPageResponse(BaseModel):
    """联系合作页投影。请求/响应同构（无密钥字段）。"""

    enabled: bool = False
    nav_label: str = ""
    title: str = ""
    subtitle: str = ""
    service_cards: List[SiteContactServiceCardModel] = Field(default_factory=list)
    contact_entries: List[SiteContactEntryModel] = Field(default_factory=list)
    body_markdown: str = ""
    updated_at: Optional[str] = None
