from __future__ import annotations

import pytest

from backend.app.services.dashboard.visit_platforms import classify_platform


def browser_ua(platform: str = "Windows NT 10.0; Win64; x64", version: int = 149) -> str:
    return (
        f"Mozilla/5.0 ({platform}) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{version}.0.0.0 Safari/537.36"
    )


@pytest.mark.parametrize("platform", ["Windows NT 10.0; Win64; x64", "Macintosh; Intel Mac OS X 10_15_7"])
@pytest.mark.parametrize("version", [148, 149, 150])
@pytest.mark.parametrize("address", [
    "124.243.189.24", "119.28.68.186", "166.108.227.207", "::ffff:190.92.218.252",
    "111.119.245.48", "166.108.201.118", "111.119.203.48", "129.226.11.172",
])
def test_observed_rotating_browser_sources_are_automated(platform, version, address):
    assert classify_platform(browser_ua(platform, version), client_ip=address) == "bot"


@pytest.mark.parametrize("address", [
    "203.0.113.9", "2001:db8::1", "43.127.255.255", "111.119.191.255", "119.27.255.255",
    "124.243.192.0", "172.20.0.1", "not-an-ip", "119.28.68.186, 203.0.113.9", "", None,
])
def test_browser_fingerprint_alone_does_not_exclude_a_visitor(address):
    assert classify_platform(browser_ua(), client_ip=address) == "windows"


@pytest.mark.parametrize("user_agent,expected", [
    (browser_ua(version=156), "windows"),
    (browser_ua() + " Edg/149.0.0.0", "windows"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0", "windows"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148", "ios"),
    (None, "other"),
])
def test_hosting_network_alone_does_not_exclude_a_visitor(user_agent, expected):
    assert classify_platform(user_agent, client_ip="124.243.189.24") == expected


def test_self_identified_automation_remains_excluded_on_other_networks():
    assert classify_platform("HeadlessChrome/156.0.0.0", client_ip="203.0.113.9") == "bot"
