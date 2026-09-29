from __future__ import annotations

import unittest
from datetime import date

from backend.app.repositories.site_visit_repository import (
    AUTOMATED_PLATFORM,
    PLATFORM_BUCKETS,
    PlatformVisits,
)
from backend.app.services.dashboard.visit_platforms import (
    build_platform_breakdown_response,
    classify_platform,
    is_automated_user_agent,
    window_start_date,
)

IPHONE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
IPAD_UA = "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
ANDROID_UA = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"
WINDOWS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
MACOS_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
IPADOS_DESKTOP_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
LINUX_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
BOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
HEADLESS_CHROME_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/148.0.0.0 Safari/537.36"

# 带移动平台特征的爬虫：平台判定在前会被误算成真人 android / ios 访问
GOOGLEBOT_SMARTPHONE_UA = "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.126 Mobile Safari/537.36 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
APPLEBOT_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1 (Applebot/0.1; +http://www.apple.com/go/applebot)"
BYTESPIDER_UA = "Mozilla/5.0 (Linux; Android 5.0) AppleWebKit/537.36 (KHTML, like Gecko) Mobile Safari/537.36 (compatible; Bytespider; spider-feedback@bytedance.com)"

AUTOMATED_UAS: dict[str, str] = {
    "googlebot": BOT_UA,
    "googlebot-smartphone": GOOGLEBOT_SMARTPHONE_UA,
    "applebot": APPLEBOT_UA,
    "bytespider": BYTESPIDER_UA,
    "baiduspider-render": "Mozilla/5.0 (Linux;u;Android 4.2.2;zh-cn;) AppleWebKit/534.46 (KHTML,like Gecko) Version/5.1 Mobile Safari/10600.6.3 (compatible; Baiduspider-render/2.0; +http://www.baidu.com/search/spider.html)",
    "bingbot": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm) Chrome/116.0.1938.76 Safari/537.36",
    "gptbot": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)",
    "yisouspider": "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/69.0.3497.81 YisouSpider/5.0 Safari/537.36",
    "360spider": "Mozilla/5.0 (compatible; MSIE 9.0; Windows NT 6.1; Trident/5.0); 360Spider",
    "twitterbot": "Twitterbot/1.0",
    "slackbot": "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)",
    "facebook": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
    "headless-chrome": HEADLESS_CHROME_UA,
    "lighthouse": "Mozilla/5.0 (Linux; Android 11; moto g power (2022)) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36 Chrome-Lighthouse",
    "curl": "curl/8.5.0",
    "python-requests": "python-requests/2.32.3",
    "httpx": "python-httpx/0.27.0",
    "undici": "node",
    "go": "Go-http-client/2.0",
}

# 真实浏览器与易误伤的边角：CUBOT 手机型号、国内 App 内置浏览器
HUMAN_UAS: dict[str, str] = {
    "iphone": IPHONE_UA,
    "android": ANDROID_UA,
    "windows": WINDOWS_UA,
    "macos": MACOS_UA,
    "linux": LINUX_UA,
    "cubot-underscore": "Mozilla/5.0 (Linux; Android 9; CUBOT_X19) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "cubot-space": "Mozilla/5.0 (Linux; Android 11; CUBOT X30 Build/RP1A) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "wechat": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.50(0x1800322d) NetType/WIFI Language/zh_CN",
    "douyin": "Mozilla/5.0 (Linux; Android 14; V2309A Build/UP1A) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile Safari/537.36 aweme_310100 JsSdk/1.0 NetType/WIFI BytedanceWebview/d8a21c6",
}


class ClassifyPlatformTests(unittest.TestCase):
    def test_iphone_and_ipad_are_ios_despite_like_mac_os_x_marker(self) -> None:
        # 顺序回归：iOS UA 带 `like Mac OS X`，若 macos 先判会把 iOS 错划走
        self.assertEqual(classify_platform(IPHONE_UA), "ios")
        self.assertEqual(classify_platform(IPAD_UA), "ios")
        self.assertEqual(classify_platform("Mozilla/5.0 (iPod touch; ...)"), "ios")

    def test_android_bucket(self) -> None:
        # Android UA 同时含 linux 字样，android 必须先于 other 命中
        self.assertEqual(classify_platform(ANDROID_UA), "android")

    def test_windows_bucket(self) -> None:
        self.assertEqual(classify_platform(WINDOWS_UA), "windows")

    def test_macos_bucket_and_ipados_desktop_mode_documented_limit(self) -> None:
        self.assertEqual(classify_platform(MACOS_UA), "macos")
        # iPadOS 桌面模式伪装 Macintosh，纯 UA 无法区分——口径上计入 macos
        self.assertEqual(classify_platform(IPADOS_DESKTOP_UA), "macos")

    def test_linux_bucket_after_android(self) -> None:
        self.assertEqual(classify_platform(LINUX_UA), "linux")
        self.assertEqual(
            classify_platform("Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"),
            "linux",
        )

    def test_automated_user_agents_fall_into_bot_bucket_before_platform_checks(self) -> None:
        for name, ua in AUTOMATED_UAS.items():
            with self.subTest(name=name):
                self.assertTrue(is_automated_user_agent(ua))
                self.assertEqual(classify_platform(ua), AUTOMATED_PLATFORM)

    def test_human_browsers_are_not_flagged_as_automated(self) -> None:
        for name, ua in HUMAN_UAS.items():
            with self.subTest(name=name):
                self.assertFalse(is_automated_user_agent(ua))
                self.assertNotEqual(classify_platform(ua), AUTOMATED_PLATFORM)

    def test_empty_and_unrecognized_user_agents_stay_in_other(self) -> None:
        # 空 UA 无从判断，按真人计入 other；ChromeOS 不并入 linux
        self.assertFalse(is_automated_user_agent(""))
        self.assertFalse(is_automated_user_agent(None))
        self.assertEqual(classify_platform(""), "other")
        self.assertEqual(classify_platform(None), "other")
        self.assertEqual(
            classify_platform("Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
            "other",
        )
        self.assertEqual(classify_platform("testclient"), "other")

    def test_every_bucket_label_is_part_of_the_contract_tuple(self) -> None:
        for ua, expected in (
            (IPHONE_UA, "ios"),
            (ANDROID_UA, "android"),
            (WINDOWS_UA, "windows"),
            (MACOS_UA, "macos"),
            (LINUX_UA, "linux"),
            (None, "other"),
        ):
            self.assertIn(expected, PLATFORM_BUCKETS)
            self.assertEqual(classify_platform(ua), expected)
        # bot 桶刻意不在计数桶元组里：它不计入访问量
        self.assertNotIn(AUTOMATED_PLATFORM, PLATFORM_BUCKETS)


class WindowStartDateTests(unittest.TestCase):
    def test_window_spans_include_today(self) -> None:
        today = date(2026, 8, 22)
        self.assertEqual(window_start_date("today", today), date(2026, 8, 22))
        self.assertEqual(window_start_date("7d", today), date(2026, 8, 16))
        self.assertEqual(window_start_date("30d", today), date(2026, 7, 24))

    def test_all_window_has_no_lower_bound(self) -> None:
        self.assertIsNone(window_start_date("all", date(2026, 8, 22)))


class BuildPlatformBreakdownResponseTests(unittest.TestCase):
    def test_fixed_bucket_order_with_zero_fill_and_shares(self) -> None:
        rows = [
            PlatformVisits(platform="windows", visits=2),
            PlatformVisits(platform="ios", visits=6),
        ]

        response = build_platform_breakdown_response(rows, "7d", date(2026, 8, 22))

        self.assertEqual(response["window"], "7d")
        self.assertEqual(response["start_date"], "2026-08-16")
        self.assertEqual(response["end_date"], "2026-08-22")
        self.assertEqual(response["total_visits"], 8)
        self.assertEqual(
            response["platforms"],
            [
                {"platform": "ios", "visits": 6, "share": 75.0},
                {"platform": "android", "visits": 0, "share": 0.0},
                {"platform": "windows", "visits": 2, "share": 25.0},
                {"platform": "macos", "visits": 0, "share": 0.0},
                {"platform": "linux", "visits": 0, "share": 0.0},
                {"platform": "other", "visits": 0, "share": 0.0},
            ],
        )
        self.assertEqual(response["automated_visits"], 0)

    def test_bot_rows_are_reported_separately_and_excluded_from_totals(self) -> None:
        rows = [
            PlatformVisits(platform="windows", visits=3),
            PlatformVisits(platform="linux", visits=1),
            PlatformVisits(platform=AUTOMATED_PLATFORM, visits=48),
        ]

        response = build_platform_breakdown_response(rows, "today", date(2026, 9, 29))

        self.assertEqual(response["total_visits"], 4)
        self.assertEqual(response["automated_visits"], 48)
        by_platform = {e["platform"]: e for e in response["platforms"]}
        self.assertNotIn(AUTOMATED_PLATFORM, by_platform)
        self.assertEqual(by_platform["other"]["visits"], 0)
        self.assertEqual(by_platform["windows"]["share"], 75.0)
        self.assertEqual(by_platform["linux"]["share"], 25.0)

    def test_zero_total_yields_zero_shares_without_division_error(self) -> None:
        response = build_platform_breakdown_response([], "today", date(2026, 8, 22))

        self.assertEqual(response["total_visits"], 0)
        self.assertEqual(response["start_date"], "2026-08-22")
        for entry in response["platforms"]:
            self.assertEqual(entry["share"], 0.0)

    def test_all_window_has_null_start_date(self) -> None:
        response = build_platform_breakdown_response(
            [PlatformVisits(platform="macos", visits=3)], "all", date(2026, 8, 22)
        )

        self.assertIsNone(response["start_date"])
        self.assertEqual(response["total_visits"], 3)

    def test_unknown_bucket_rows_fold_into_other(self) -> None:
        # 防御历史脏数据：响应桶集合恒为 PLATFORM_BUCKETS
        rows = [
            PlatformVisits(platform="harmonyos", visits=2),
            PlatformVisits(platform="other", visits=1),
        ]

        response = build_platform_breakdown_response(rows, "30d", date(2026, 8, 22))

        other = next(e for e in response["platforms"] if e["platform"] == "other")
        self.assertEqual(other["visits"], 3)
        self.assertEqual(response["total_visits"], 3)
        self.assertEqual(
            [e["platform"] for e in response["platforms"]], list(PLATFORM_BUCKETS)
        )


if __name__ == "__main__":
    unittest.main()
