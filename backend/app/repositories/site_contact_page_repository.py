from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class SiteContactServiceCard:
    """联系合作页的服务卡片（外包服务、商务合作等）。

    icon 为短 key 字符串（如 code/briefcase/chat），由前端映射为内联 SVG；
    空字符串表示使用前端默认图标。
    """

    title: str
    description: str = ""
    icon: str = ""


@dataclass(frozen=True)
class SiteContactEntry:
    """联系合作页的联系方式条目（QQ 群、邮箱等）。

    qr_image_url 允许站外 https URL 或站内相对路径（/...），空字符串表示无图。
    """

    label: str
    value: str = ""
    href: str = ""
    qr_image_url: str = ""


@dataclass(frozen=True)
class SiteContactPage:
    """单行持久化的站点联系合作页配置。

    空字符串/空列表表示该字段未设置（全列 NOT NULL，无 NULL 分支）；
    内容由管理员撰写，按单语言原样展示，不做 i18n。
    """

    enabled: bool
    nav_label: str
    title: str
    subtitle: str
    service_cards: tuple[SiteContactServiceCard, ...] = field(default_factory=tuple)
    contact_entries: tuple[SiteContactEntry, ...] = field(default_factory=tuple)
    body_markdown: str = ""
    updated_at: datetime | None = None


class SiteContactPageReader(Protocol):
    def get_site_contact_page(self) -> SiteContactPage | None: ...


class SiteContactPageManager(SiteContactPageReader, Protocol):
    def upsert_site_contact_page(
        self,
        *,
        enabled: bool,
        nav_label: str,
        title: str,
        subtitle: str,
        service_cards: tuple[SiteContactServiceCard, ...],
        contact_entries: tuple[SiteContactEntry, ...],
        body_markdown: str,
    ) -> SiteContactPage: ...


class SiteContactPageRepository(SiteContactPageManager, Protocol):
    """Persistence boundary for the singleton site contact page row."""
