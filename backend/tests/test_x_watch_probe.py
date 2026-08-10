from __future__ import annotations

import unittest

from backend.app.services.ingestion.sources.x_transport import (
    XAuthAbort,
    XAuthNotConfigured,
    XRateLimitAbort,
    XTransportUnavailable,
)
from backend.app.services.x_watch.probe import probe_x_watch_account


class FakeTransport:
    def __init__(self, *, result=None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.calls: list[tuple[list[str], int]] = []

    async def fetch_watchlist_tweets(self, handles, count_per_user):
        self.calls.append((list(handles), count_per_user))
        if self._error is not None:
            raise self._error
        return self._result


class XWatchProbeTests(unittest.TestCase):
    def test_success_reports_tweet_count(self) -> None:
        transport = FakeTransport(result={"openai": ["t1", "t2"]})

        outcome = probe_x_watch_account("openai", transport)

        self.assertEqual(outcome["status"], "succeeded")
        self.assertIn("2", outcome["message"])
        self.assertEqual(transport.calls, [(["openai"], 2)])

    def test_missing_handle_maps_to_spelling_failure(self) -> None:
        transport = FakeTransport(result={})

        outcome = probe_x_watch_account("no_such_account", transport)

        self.assertEqual(outcome["status"], "failed")
        self.assertIn("handle", outcome["message"])

    def test_auth_not_configured_is_loud_failure(self) -> None:
        transport = FakeTransport(
            error=XAuthNotConfigured("x_auth_not_configured")
        )

        outcome = probe_x_watch_account("openai", transport)

        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["message"], "x_auth_not_configured")

    def test_auth_abort_and_rate_limit_propagate_markers(self) -> None:
        for error, marker in (
            (XAuthAbort("x_auth_expired"), "x_auth_expired"),
            (XRateLimitAbort("x_rate_limited"), "x_rate_limited"),
            (XTransportUnavailable("x_transport_unavailable"), "x_transport_unavailable"),
        ):
            with self.subTest(marker=marker):
                outcome = probe_x_watch_account("openai", FakeTransport(error=error))
                self.assertEqual(outcome["status"], "failed")
                self.assertEqual(outcome["message"], marker)

    def test_unexpected_error_is_contained_with_marker(self) -> None:
        transport = FakeTransport(error=RuntimeError("boom"))

        with self.assertLogs("backend.app.services.x_watch.probe", level="ERROR"):
            outcome = probe_x_watch_account("openai", transport)

        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["message"], "x_probe_error")


if __name__ == "__main__":
    unittest.main()
