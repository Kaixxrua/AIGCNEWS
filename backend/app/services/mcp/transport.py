from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping

import httpx

from backend.app.services.outbound_target_policy import PinnedHttpTarget


class StreamableHttpTransport:
    def __init__(
        self,
        *,
        headers: Mapping[str, str],
        client_factory: Callable[..., httpx.Client] = httpx.Client,
    ) -> None:
        self._headers = dict(headers)
        self._client_factory = client_factory

    def open(self) -> httpx.Client:
        return self._client_factory(
            timeout=httpx.Timeout(
                connect=5.0,
                read=10.0,
                write=5.0,
                pool=5.0,
            ),
            follow_redirects=False,
            trust_env=False,
            headers=self._headers,
        )

    @staticmethod
    def stream_post(
        client: httpx.Client,
        target: PinnedHttpTarget,
        payload: Mapping[str, Any],
    ):
        return client.stream(
            "POST",
            target.request_url,
            json=dict(payload),
            headers=target.headers,
            extensions=target.extensions,
        )
