from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from backend.app.api.dependencies import get_x_operation_lock


def test_get_x_operation_lock_returns_app_state_lock() -> None:
    lock = asyncio.Lock()
    request = MagicMock()
    request.app.state.x_operation_lock = lock

    resolved = get_x_operation_lock(request)

    assert resolved is lock


def test_get_x_operation_lock_falls_back_to_fresh_lock() -> None:
    request = MagicMock()
    request.app.state.x_operation_lock = None

    resolved = get_x_operation_lock(request)

    assert isinstance(resolved, asyncio.Lock)
    assert resolved is not request.app.state.x_operation_lock
