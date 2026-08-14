from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.app.services.ingestion.website_content_moderation import (
    _SYSTEM_PROMPT,
    ModerationUnavailableError,
    WebsiteContentModerator,
)


def _llm_returning(text: str) -> MagicMock:
    llm = MagicMock()
    llm.invoke.return_value.content = text
    return llm


class WebsiteContentModeratorTests(unittest.TestCase):
    def test_moderate_returns_adult_verdict(self) -> None:
        moderator = WebsiteContentModerator(
            llm=_llm_returning('{"is_adult":true,"reason":"成人视频平台"}')
        )

        verdict = moderator.moderate(
            domain="adult.example", title="t", description="d"
        )

        self.assertTrue(verdict.is_adult)
        self.assertEqual(verdict.reason, "成人视频平台")

    def test_moderate_returns_clean_verdict(self) -> None:
        moderator = WebsiteContentModerator(
            llm=_llm_returning('{"is_adult":false,"reason":"正规 AI 工具"}')
        )

        verdict = moderator.moderate(
            domain="example.com",
            title="Example",
            description="AI 工具",
            tags=["AI"],
        )

        self.assertFalse(verdict.is_adult)

    def test_moderate_fail_closed_raises_on_llm_error(self) -> None:
        llm = MagicMock()
        llm.invoke.side_effect = RuntimeError("connection refused")
        moderator = WebsiteContentModerator(llm=llm, fail_closed=True)

        with self.assertRaises(ModerationUnavailableError):
            moderator.moderate(domain="example.com", title="t", description="d")

        llm.invoke.assert_called_once()

    def test_moderate_fail_open_allows_on_llm_error(self) -> None:
        llm = MagicMock()
        llm.invoke.side_effect = RuntimeError("connection refused")
        moderator = WebsiteContentModerator(llm=llm, fail_closed=False)

        verdict = moderator.moderate(domain="example.com", title="t", description="d")

        self.assertFalse(verdict.is_adult)

    def test_moderate_retries_once_on_retryable_error(self) -> None:
        llm = MagicMock()
        ok = MagicMock()
        ok.content = '{"is_adult":false,"reason":"正常"}'
        llm.invoke.side_effect = [RuntimeError("429 rate_limit exceeded"), ok]
        moderator = WebsiteContentModerator(llm=llm, fail_closed=True)

        with patch(
            "backend.app.services.ingestion.website_content_moderation.time.sleep"
        ) as sleep:
            verdict = moderator.moderate(domain="example.com", title="t", description="d")

        self.assertFalse(verdict.is_adult)
        self.assertEqual(llm.invoke.call_count, 2)
        sleep.assert_called_once()

    def test_moderate_unparseable_json_treated_as_unavailable(self) -> None:
        moderator = WebsiteContentModerator(
            llm=_llm_returning("not json at all"),
            fail_closed=True,
        )

        with self.assertRaises(ModerationUnavailableError):
            moderator.moderate(domain="example.com", title="t", description="d")

    def test_system_prompt_declares_untrusted_payload(self) -> None:
        self.assertIn("不可信", _SYSTEM_PROMPT)
        self.assertIn("只返回 JSON", _SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
