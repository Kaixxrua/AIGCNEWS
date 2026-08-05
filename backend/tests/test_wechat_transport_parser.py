from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from backend.app.services.wechat.parser import (
    QR_STATUS_CONFIRMED,
    QR_STATUS_EXPIRED_2,
    QR_STATUS_EXPIRED_3,
    QR_STATUS_NO_BOUND_EMAIL,
    QR_STATUS_SCANNED,
    QR_STATUS_WAITING,
    build_stable_article_key,
    decode_publish_page,
    extract_token_from_redirect_url,
    map_scan_status,
    normalize_article_metadata,
    parse_appmsg_publish_response,
    parse_biz_login_response,
    parse_search_biz_response,
)
from backend.app.services.wechat.transport import (
    WeChatMpTransport,
    _extract_simple_cookies,
    _merge_cookie_dict,
)


def test_extract_token_from_redirect_url() -> None:
    assert (
        extract_token_from_redirect_url(
            "/cgi-bin/home?t=home/index&lang=zh_CN&token=1234567890"
        )
        == "1234567890"
    )
    assert extract_token_from_redirect_url("") is None
    assert extract_token_from_redirect_url("/cgi-bin/home") is None


def test_extract_simple_cookies_parses_first_segment() -> None:
    cookies = _extract_simple_cookies(
        [
            "uuid=abc; Path=/; Expires=Wed, 21 Oct 2026 07:28:00 GMT",
            "wxa_sid=def; Path=/",
        ]
    )
    assert cookies == {"uuid": "abc", "wxa_sid": "def"}


def test_merge_cookie_dict_drops_expired() -> None:
    base = {"uuid": "abc", "wxa_sid": "def"}
    merged = _merge_cookie_dict(base, {"uuid": "EXPIRED", "token": "123"})
    assert merged == {"wxa_sid": "def", "token": "123"}


def test_map_scan_status_waiting() -> None:
    status, meta = map_scan_status({"base_resp": {"ret": 0}, "status": QR_STATUS_WAITING})
    assert status == "waiting_scan"
    assert meta["upstream_status"] == QR_STATUS_WAITING


def test_map_scan_status_confirmed() -> None:
    status, meta = map_scan_status(
        {"base_resp": {"ret": 0}, "status": QR_STATUS_CONFIRMED}
    )
    assert status == "confirmed"


def test_map_scan_status_expired() -> None:
    for code in (QR_STATUS_EXPIRED_2, QR_STATUS_EXPIRED_3):
        status, _ = map_scan_status({"base_resp": {"ret": 0}, "status": code})
        assert status == "qr_expired"


def test_map_scan_status_scanned_with_account() -> None:
    status, meta = map_scan_status(
        {"base_resp": {"ret": 0}, "status": QR_STATUS_SCANNED, "acct_size": 1}
    )
    assert status == "scanned_waiting_confirmation"
    assert meta["acct_size"] == 1


def test_map_scan_status_scanned_without_account_fails() -> None:
    status, meta = map_scan_status(
        {"base_resp": {"ret": 0}, "status": QR_STATUS_SCANNED, "acct_size": 0}
    )
    assert status == "failed"
    assert meta["reason"] == "没有可登录账号"


def test_map_scan_status_no_bound_email() -> None:
    status, meta = map_scan_status(
        {"base_resp": {"ret": 0}, "status": QR_STATUS_NO_BOUND_EMAIL}
    )
    assert status == "failed"
    assert meta["reason"] == "该账号尚未绑定邮箱"


def test_parse_biz_login_response_extracts_token() -> None:
    token, info = parse_biz_login_response(
        {
            "base_resp": {"ret": 0, "err_msg": ""},
            "redirect_url": "/cgi-bin/home?token=9876543210",
        }
    )
    assert token == "9876543210"
    assert "redirect_url" in info


def test_parse_biz_login_response_raises_when_no_token() -> None:
    from backend.app.services.wechat.errors import WeChatLoginFailed

    with pytest.raises(WeChatLoginFailed):
        parse_biz_login_response(
            {"base_resp": {"ret": 0, "err_msg": ""}, "redirect_url": "/cgi-bin/home"}
        )


def test_decode_publish_page_and_nested_publish_info() -> None:
    publish_info_inner = {
        "msgid": 1001,
        "appmsgex": [
            {
                "appmsgid": 1001,
                "itemidx": 1,
                "title": "Hello",
                "digest": "summary",
                "link": "https://mp.weixin.qq.com/s?__biz=xyz",
                "cover": "https://cover.png",
                "create_time": 1700000000,
            },
            {
                "appmsgid": 1001,
                "itemidx": 2,
                "title": "Second",
                "link": "https://mp.weixin.qq.com/s?__biz=xyz2",
                "create_time": 1700000000,
            },
        ],
    }
    page = {
        "publish_count": 1,
        "publish_list": [
            {"publish_type": 1, "publish_info": json.dumps(publish_info_inner)}
        ],
    }

    articles, message_count = parse_appmsg_publish_response(
        {
            "base_resp": {"ret": 0},
            "publish_page": json.dumps(page),
        }
    )

    assert message_count == 1
    assert len(articles) == 2
    assert articles[0]["title"] == "Hello"
    assert articles[0]["itemidx"] == 1


def test_parse_appmsg_publish_empty_list() -> None:
    articles, message_count = parse_appmsg_publish_response(
        {
            "base_resp": {"ret": 0},
            "publish_page": json.dumps({"publish_list": []}),
        }
    )
    assert articles == []
    assert message_count == 0


def test_decode_publish_page_bad_json_raises() -> None:
    from backend.app.services.wechat.errors import WeChatUpstreamError

    with pytest.raises(WeChatUpstreamError):
        decode_publish_page("not json")


def test_parse_search_biz_response() -> None:
    accounts, total = parse_search_biz_response(
        {
            "base_resp": {"ret": 0},
            "total": 42,
            "list": [
                {
                    "fakeid": "fake1",
                    "nickname": "Test",
                    "alias": "test",
                    "round_head_img": "https://avatar.png",
                    "signature": "sig",
                }
            ],
        }
    )
    assert total == 42
    assert len(accounts) == 1
    assert accounts[0]["fakeid"] == "fake1"


def test_build_stable_article_key_prefers_appmsgid_itemidx() -> None:
    assert (
        build_stable_article_key({"appmsgid": 1001, "itemidx": 2, "link": "x"})
        == "1001-2"
    )
    assert build_stable_article_key({"link": "https://example.com"}) == "https://example.com"
    assert build_stable_article_key({"aid": "abc"}) == "abc"


def test_normalize_article_metadata() -> None:
    article = {
        "appmsgid": 1001,
        "itemidx": 1,
        "title": " Title ",
        "digest": "Digest",
        "author": "Author",
        "link": "https://mp.weixin.qq.com/s/x",
        "cover": "https://cover.png",
        "source_url": "https://source",
        "create_time": 1700000000,
    }
    meta = normalize_article_metadata(article)
    assert meta["stable_article_key"] == "1001-1"
    assert meta["title"] == "Title"
    assert meta["published_at"] is not None
    assert meta["raw_metadata"] == article


def test_transport_start_login_builds_fixed_target(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200
        headers = httpx.Headers()
        _content = b'{"base_resp":{"ret":0}}'

        async def aread(self):
            return self._content

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured["client_kwargs"] = kwargs

        async def request(self, **kwargs) -> FakeResponse:
            captured["request_kwargs"] = kwargs
            return FakeResponse()

        async def aclose(self) -> None:
            pass

    async def _run():
        transport = WeChatMpTransport(client_factory=FakeClient)
        return await transport.start_login("sid-123")

    response = asyncio.run(_run())

    assert response.status_code == 200
    request_url = captured["request_kwargs"]["url"]
    assert request_url.startswith("https://")
    assert "mp.weixin.qq.com" not in request_url  # pinned to IP
    assert captured["request_kwargs"]["method"] == "POST"
    assert "action=startlogin" in captured["request_kwargs"]["url"]
    assert captured["request_kwargs"]["data"]["sessionid"] == "sid-123"


def test_transport_cookie_helpers_filter_attributes() -> None:
    raw = "uuid=abc; Path=/; HttpOnly"
    assert _extract_simple_cookies([raw]) == {"uuid": "abc"}
