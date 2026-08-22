from __future__ import annotations

import unittest
from datetime import date

from backend.app.repositories.site_visit_repository import (
    PLATFORM_BUCKETS,
    PlatformVisits,
)
from backend.app.services.dashboard.visit_platforms import (
    build_platform_breakdown_response,
    classify_platform,
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

    def test_other_bucket_for_linux_bot_and_empty(self) -> None:
        self.assertEqual(classify_platform(LINUX_UA), "other")
        self.assertEqual(classify_platform(BOT_UA), "other")
        self.assertEqual(classify_platform("curl/8.5.0"), "other")
        self.assertEqual(classify_platform(""), "other")
        self.assertEqual(classify_platform(None), "other")

    def test_every_bucket_label_is_part_of_the_contract_tuple(self) -> None:
        for ua, expected in (
            (IPHONE_UA, "ios"),
            (ANDROID_UA, "android"),
            (WINDOWS_UA, "windows"),
            (MACOS_UA, "macos"),
            (BOT_UA, "other"),
        ):
            self.assertIn(expected, PLATFORM_BUCKETS)
            self.assertEqual(classify_platform(ua), expected)


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
                {"platform": "other", "visits": 0, "share": 0.0},
            ],
        )

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
