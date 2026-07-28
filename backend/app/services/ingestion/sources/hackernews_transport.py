from __future__ import annotations

import asyncio
from typing import Any, Callable, Iterable

import httpx

HN_TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
TOP_N = 30
SEMAPHORE_LIMIT = 30


class HackerNewsTransport:
    def __init__(
        self,
        client_factory: Callable[..., Any] | None = None,
        *,
        top_n: int = TOP_N,
        semaphore_limit: int = SEMAPHORE_LIMIT,
    ) -> None:
        self._client_factory = client_factory or httpx.AsyncClient
        self._top_n = top_n
        self._semaphore_limit = semaphore_limit

    async def fetch_top_ids(self) -> list[int]:
        async with self._client_factory(
            timeout=15,
            trust_env=True,
            follow_redirects=True,
        ) as client:
            response = await client.get(HN_TOP_STORIES_URL)
            response.raise_for_status()
            data = response.json()
        if not data or not isinstance(data, list):
            return []
        return data[: self._top_n]

    async def fetch_items(self, item_ids: Iterable[int]) -> list[dict | None]:
        semaphore = asyncio.Semaphore(self._semaphore_limit)
        async with self._client_factory(
            timeout=10,
            trust_env=True,
            follow_redirects=True,
        ) as client:
            return await asyncio.gather(
                *(
                    self._fetch_item(client, semaphore, item_id)
                    for item_id in item_ids
                )
            )

    @staticmethod
    async def _fetch_item(
        client: Any,
        semaphore: asyncio.Semaphore,
        item_id: int,
    ) -> dict | None:
        async with semaphore:
            try:
                response = await client.get(
                    HN_ITEM_URL.format(item_id=item_id),
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, dict) else None
            except Exception:
                return None
