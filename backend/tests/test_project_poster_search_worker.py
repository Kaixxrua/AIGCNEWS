from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import quote

from backend.app.services.project_catalog import game_poster_search as worker


def redirected(url: str) -> str:
    return "https://r.search.yahoo.com/_ylt=test/RV=2/RE=123/RO=10/RU=" + quote(url, safe="") + "/RK=2/RS=test"


def result_html(url: str, *, title: str = "A Game II cover", layout: str = "algo", snippet: str = "Original box art") -> str:
    # Yahoo returns both relsrch/anchor > h3 and algo/h3 > anchor layouts.
    heading = f'<h3 class="title d-ib">{title}</h3>'
    linked = f'<a href="{redirected(url)}">{heading}</a>' if layout == "relsrch" else f'<h3 class="title"><a href="{redirected(url)}">{title}</a></h3>'
    return f'<div class="{layout} other"><div class="compTitle">{linked}</div><div class="compText">{snippet}</div></div>'


class YahooOrganicLayoutTests(unittest.TestCase):
    def test_both_real_organic_layouts_yield_discovered_source_urls(self):
        for layout in ("relsrch", "algo", "algo-sr"):
            with self.subTest(layout=layout):
                self.assertEqual(worker.parse_yahoo_results(result_html("https://games.example/game/123/covers/", layout=layout)), [
                    {"url": "https://games.example/game/123/covers/", "title": "A Game II cover", "snippet": "Original box art"},
                ])

    def test_organic_requirement_ignores_navigation_ads_and_non_results(self):
        html = '<h3 class="title"><a href="https://games.example/navigation">Navigation</a></h3>'
        html += '<div class="knowledge"><h3 class="title"><a href="https://games.example/panel">Panel</a></h3></div>'
        for unsafe in ("javascript:alert(1)", "http://games.example/cover", "https://secret@games.example/cover",
                       "https://games.example:444/cover", "https://search.yahoo.com/search?q=game",
                       "https://www.bing.com/aclick?target=advert", "https://games.example\\internal/cover"):
            html += result_html(unsafe)
        html += result_html("https://games.example/valid-cover")
        self.assertEqual([row["url"] for row in worker.parse_yahoo_results(html)], ["https://games.example/valid-cover"])

    def test_direct_links_duplicates_unicode_and_text_bounds(self):
        html = result_html("https://games.example/game", title="A  Game\nII", snippet=" Cover \n details ")
        html += result_html("https://games.example/game", layout="relsrch")
        html += '<div class="algo"><h3 class="title"><a href="https://games.example/other">' + "游" * 400 + '</a></h3><div class="compText">' + "述" * 700 + "</div></div>"
        rows = worker.parse_yahoo_results(html)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], {"url": "https://games.example/game", "title": "A Game II", "snippet": "Cover details"})
        self.assertEqual(len(rows[1]["title"]), 300)
        self.assertEqual(len(rows[1]["snippet"]), 600)

    def test_result_count_page_size_and_invalid_redirect_are_bounded(self):
        self.assertEqual(len(worker.parse_yahoo_results("".join(result_html(f"https://games.example/{i}") for i in range(20)))), 6)
        self.assertEqual(worker.parse_yahoo_results("游" * (worker.SEARCH_PAGE_BYTES // 3 + 1)), [])
        self.assertEqual(worker._yahoo_result_url("https://r.search.yahoo.com/no-result-target"), "")
        self.assertEqual(worker._yahoo_result_url("https://[invalid-host/"), "")


class PosterSearchWorkerTests(unittest.TestCase):
    def yahoo_module(self, *, status: int = 200, body: str | None = None):
        response = SimpleNamespace(status_code=status, text=body if body is not None else result_html("https://games.example/game/cover"))
        engine = SimpleNamespace(build_payload=Mock(return_value={"p": "A Game II cover"}),
                                 http_client=SimpleNamespace(request=Mock(return_value=response)),
                                 search_url="https://search.yahoo.com/search")
        constructor = Mock(return_value=engine)
        return SimpleNamespace(Yahoo=constructor), constructor, engine

    def test_yahoo_reuses_pinned_transport_and_one_provider_request(self):
        module, constructor, engine = self.yahoo_module()
        with patch.dict("sys.modules", {"ddgs.engines.yahoo": module}):
            result = worker.search_results("A Game II cover", "private-proxy-value", ("yahoo",))
        constructor.assert_called_once_with(proxy="private-proxy-value", timeout=8)
        engine.http_client.request.assert_called_once_with("GET", "https://search.yahoo.com/search", params={"p": "A Game II cover"})
        self.assertEqual(result["engine"], "yahoo")
        self.assertEqual(result["results"][0]["url"], "https://games.example/game/cover")
        self.assertEqual(result["attempts"][0]["httpStatus"], 200)
        self.assertEqual(result["attempts"][0]["parser"], "yahoo_headings")
        self.assertEqual(result["attempts"][0]["status"], "succeeded")
        self.assertNotIn("private-proxy-value", json.dumps(result))

    def test_rate_limit_and_oversized_html_are_safe_unavailable_diagnostics(self):
        for status, body, reason in [(429, "secret-response", "provider_http"),
                                     (200, "x" * (worker.SEARCH_PAGE_BYTES + 1), "provider_response_oversize")]:
            with self.subTest(reason=reason):
                module, _, engine = self.yahoo_module(status=status, body=body)
                with patch.dict("sys.modules", {"ddgs.engines.yahoo": module}):
                    result = worker.search_results("A Game II cover", None, ("yahoo",))
                self.assertTrue(result["unavailable"])
                self.assertEqual(result["attempts"][0]["reason"], reason)
                self.assertEqual(result["attempts"][0]["httpStatus"], status)
                self.assertEqual(result["results"], [])
                self.assertEqual(engine.http_client.request.call_count, 1)
                self.assertNotIn("secret-response", json.dumps(result))

    def test_provider_failure_falls_back_once_without_leaking_exception_message(self):
        module, _, _ = self.yahoo_module()
        with patch.dict("sys.modules", {"ddgs.engines.yahoo": module}), \
                patch.object(worker, "_search_ddgs", side_effect=RuntimeError("socks5://secret:password@proxy")) as other:
            result = worker.search_results("A Game II cover", None, ("google", "yahoo"))
        other.assert_called_once_with("A Game II cover", None, 8, "google")
        self.assertEqual(result["engine"], "yahoo")
        self.assertEqual([row["status"] for row in result["attempts"]], ["unavailable", "succeeded"])
        self.assertEqual(result["attempts"][0]["errorType"], "RuntimeError")
        self.assertNotIn("secret", json.dumps(result))
        self.assertNotIn("password", json.dumps(result))

    def test_genuine_empty_search_is_distinct_from_provider_failure(self):
        module, _, _ = self.yahoo_module(body="<html><title>No results</title></html>")
        with patch.dict("sys.modules", {"ddgs.engines.yahoo": module}):
            result = worker.search_results("A Game II cover", None, ("yahoo",))
        self.assertFalse(result["unavailable"])
        self.assertEqual(result["attempts"][0]["status"], "empty")
        self.assertEqual(result["attempts"][0]["resultCount"], 0)

    def test_whole_worker_budget_prevents_starting_another_request(self):
        with patch.object(worker.time, "monotonic", side_effect=[0, 0, 20, 20]), \
                patch.object(worker, "_search_ddgs", return_value=[]) as first, \
                patch.object(worker, "_search_yahoo") as second:
            result = worker.search_results("A Game II cover", None, ("google", "yahoo"))
        first.assert_called_once()
        second.assert_not_called()
        self.assertEqual(result["attempts"][-1]["reason"], "worker_deadline")
        self.assertTrue(result["unavailable"])

    def test_engine_budget_rejects_untrusted_engines_and_never_repeats_duplicate(self):
        for engines in [("yahoo", "google", "duckduckgo"), ("untrusted",), (), "yahoo"]:
            with self.subTest(engines=engines), self.assertRaises(ValueError):
                worker.bounded_engines(engines)
        with patch.object(worker, "_search_yahoo", return_value=[]) as search:
            worker.search_results("A Game II cover", None, ("yahoo", "yahoo"))
        search.assert_called_once()

    def test_json_output_is_utf8_bounded_without_breaking_json(self):
        rows = [{"url": "https://games.example/" + "游" * 2000, "title": "名" * 300, "snippet": "述" * 600} for _ in range(6)]
        result = worker.encode_result({"engine": "yahoo", "results": rows, "attempts": []})
        self.assertLessEqual(len(result.encode("utf-8")), worker.SEARCH_OUTPUT_BYTES)
        decoded = json.loads(result)
        self.assertGreater(len(decoded["results"]), 0)
        self.assertLess(len(decoded["results"]), 6)


if __name__ == "__main__":
    unittest.main()
