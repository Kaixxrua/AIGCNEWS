"""Literal concept matching for PostgreSQL, mirrored by Go projectsem."""


def concept_search_pattern(term: str) -> str:
    """Bound ASCII concepts so eval cannot match retrieval, nor rag storage.

    Punctuation (including snake_case separators) and Han text delimit English
    tokens. Han concepts keep substring matching. Escape only ARE metacharacters
    so the result is identical to Go regexp.QuoteMeta and remains bound data.
    """
    escaped = "".join("\\" + char if char in r"\.+*?()|[]{}^$" else char for char in term)
    if term.isascii():
        return f"(^|[^a-z0-9]){escaped}($|[^a-z0-9])"
    return escaped
