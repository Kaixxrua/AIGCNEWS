"""Classify retryable model failures without serializing provider responses."""
from __future__ import annotations

from typing import Any

from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError

_NON_RETRY_ERRORS = frozenset({
    "insufficient_quota", "quota_exceeded", "billing_not_active", "billing_hard_limit_reached",
    "rate_limit_error", "rate_limit_exceeded", "authentication_error", "invalid_api_key",
    "permission_error", "permission_denied", "invalid_request_error", "invalid_request",
    "content_filter", "content_policy_violation", "context_length_exceeded",
})


def without_openai_sdk_retries(model: Any) -> Any:
    """Give this poster job its own retry policy without mutating shared models.

    Changing ChatOpenAI.max_retries alone does not change already-created SDK
    clients. Clone both clients with their documented per-client option, then
    rebind completions as well as the root clients (used for alternate paths).
    Other providers retain their existing behavior and are not classified for
    OpenAI server-error retries here.
    """
    from langchain_openai import ChatOpenAI

    if not isinstance(model, ChatOpenAI):
        return model
    sync = model.root_client.with_options(max_retries=0)
    asynchronous = model.root_async_client.with_options(max_retries=0)
    return model.model_copy(update={
        "max_retries": 0, "root_client": sync, "client": sync.chat.completions,
        "root_async_client": asynchronous, "async_client": asynchronous.chat.completions,
    })


def transient_model_failure(exc: Exception) -> str | None:
    if isinstance(exc, (TimeoutError, APITimeoutError)):
        return "model_timeout"
    if isinstance(exc, APIConnectionError):
        return "model_transport_failure"
    fields: set[str] = set()
    if isinstance(exc, APIError) and isinstance(exc.body, dict):
        for level in (exc.body, exc.body.get("error")):
            if isinstance(level, dict):
                fields.update(level[key] for key in ("code", "type") if isinstance(level.get(key), str))
    # Explicit quota/auth/request failures override a generic server_error
    # envelope or an incorrectly reported HTTP 5xx status.
    if fields & _NON_RETRY_ERRORS:
        return None
    if isinstance(exc, APIStatusError):
        # Authentication, quota/rate limits, invalid requests and content
        # rejections need their own handling, not another paid request.
        return "model_server_error" if exc.status_code in {408, 500, 502, 503, 504} else None
    if type(exc) is APIError:
        if fields & {"server_error", "internal_error", "internal_server_error", "overloaded_error", "service_unavailable"}:
            return "model_server_error"
    return None
