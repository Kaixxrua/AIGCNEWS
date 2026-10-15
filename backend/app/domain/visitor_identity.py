from __future__ import annotations

import re

_VISITOR_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


class InvalidVisitorId(ValueError):
    """Raised when a client-supplied anonymous visitor ID is malformed."""


def validate_visitor_id(visitor_id: str) -> str:
    value = visitor_id.strip()
    if not _VISITOR_ID_PATTERN.fullmatch(value):
        raise InvalidVisitorId("visitor_id must be 16-128 safe identifier characters")
    return value
