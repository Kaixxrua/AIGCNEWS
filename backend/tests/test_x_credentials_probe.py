from __future__ import annotations

from unittest.mock import MagicMock

from backend.app.services.ingestion.sources.x_transport import (
    XAuthAbort,
    XAuthNotConfigured,
    XRateLimitAbort,
    XTransportUnavailable,
)
from backend.app.services.x_credentials.probe import (
    probe_all_x_credentials,
    probe_x_credential,
)


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


def test_single_probe_returns_only_stable_sanitized_markers() -> None:
    credential = {"id": 1, "auth_token": "raw-auth-secret", "ct0": "raw-ct0-secret"}
    assert probe_x_credential(credential, "") == {
        "status": "failed",
        "message": "x_probe_no_watch_handle",
    }

    for error, marker in (
        (XAuthNotConfigured("raw-auth-secret"), "x_auth_not_configured"),
        (XAuthAbort("raw-auth-secret"), "x_auth_expired"),
        (XRateLimitAbort("raw-ct0-secret"), "x_rate_limited"),
        (XTransportUnavailable("proxy down"), "x_transport_unavailable"),
        (RuntimeError("raw-auth-secret raw-ct0-secret"), "x_probe_error"),
    ):
        outcome = probe_x_credential(
            credential,
            "openai",
            transport=FakeTransport(error=error),
        )
        assert outcome == {"status": "failed", "message": marker}
        assert "raw-auth-secret" not in str(outcome)
        assert "raw-ct0-secret" not in str(outcome)


def test_single_probe_reports_success_and_missing_handle() -> None:
    credential = {"id": 1, "auth_token": "auth", "ct0": "ct0"}
    success_transport = FakeTransport(result={"openai": ["a", "b"]})
    assert probe_x_credential(
        credential,
        "openai",
        transport=success_transport,
    ) == {"status": "succeeded", "message": "成功拉取 2 条近期推文"}
    assert success_transport.calls == [(["openai"], 2)]

    assert probe_x_credential(
        credential,
        "openai",
        transport=FakeTransport(result={}),
    ) == {"status": "failed", "message": "x_probe_handle_missing"}


def test_pool_probe_is_serial_and_persists_each_result() -> None:
    credentials = [
        {"id": 1, "auth_token": "auth-1", "ct0": "ct0-1"},
        {"id": 2, "auth_token": "auth-2", "ct0": "ct0-2"},
    ]
    update_result = MagicMock()
    transport = FakeTransport(result={"openai": ["a"]})

    results = probe_all_x_credentials(
        credentials,
        "openai",
        update_result=update_result,
        transport=transport,
    )

    assert results == [
        {"credential_id": 1, "status": "succeeded", "message": "成功拉取 1 条近期推文"},
        {"credential_id": 2, "status": "succeeded", "message": "成功拉取 1 条近期推文"},
    ]
    assert transport.calls == [(["openai"], 2), (["openai"], 2)]
    assert [call.args[0] for call in update_result.call_args_list] == [1, 2]


def test_pool_probe_without_watch_handle_persists_failure_for_every_row() -> None:
    credentials = [{"id": 1}, {"id": 2}]
    update_result = MagicMock()

    results = probe_all_x_credentials(
        credentials,
        "",
        update_result=update_result,
    )

    expected_result = {"status": "failed", "message": "x_probe_no_watch_handle"}
    assert results == [
        {"credential_id": 1, **expected_result},
        {"credential_id": 2, **expected_result},
    ]
    assert update_result.call_args_list == [
        ((1, expected_result),),
        ((2, expected_result),),
    ]


def test_pool_probe_contains_result_persistence_failure() -> None:
    update_result = MagicMock(side_effect=RuntimeError("database unavailable"))

    results = probe_all_x_credentials(
        [{"id": 1}],
        "",
        update_result=update_result,
    )

    assert results == [
        {
            "credential_id": 1,
            "status": "failed",
            "message": "x_probe_no_watch_handle",
        }
    ]
