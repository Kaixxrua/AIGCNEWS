"""Deterministic change-risk and safe landing controls.

This module deliberately has no git or filesystem side effects.  Callers can use
it to classify a proposed change, record validation, and then execute the
serialized compare-and-swap command in an explicitly controlled step.
"""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import PurePosixPath


class RiskLevel(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


# Ordered from most specific to least specific.  Matching is intentionally
# lexical and path-normalized, so the same input always gives the same result.
_RED_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("postgresql", re.compile(r"(^|/)(postgres|postgresql|migrations?)(/|_|\\.|$)|postgres_", flags=re.IGNORECASE)),
    ("release/staging", re.compile(r"(^|/)(release|releases|staging|deploy)(/|_|\\.|$)", flags=re.IGNORECASE)),
    ("project instructions", re.compile(r"(^|/)(claude\.md|docs/git-workflow\.md)$", flags=re.IGNORECASE)),
)
_YELLOW_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("security or permissions", re.compile(r"(^|/)(security|auth|permissions?)(/|_|\\.|$)|(^|/)security_", flags=re.IGNORECASE)),
    ("schema or infrastructure", re.compile(r"(^|/)(docker|terraform|k8s|kubernetes|infra)(/|_|\\.|$)", flags=re.IGNORECASE)),
)


def _normalize_path(path: str) -> str:
    value = str(path).replace("\\", "/").strip()
    if not value or value.startswith("/") or "\x00" in value:
        raise ValueError(f"invalid changed path: {path!r}")
    normalized = str(PurePosixPath(value))
    if normalized == "." or normalized.startswith("../") or "/../" in normalized:
        raise ValueError(f"invalid changed path: {path!r}")
    return normalized


@dataclass(frozen=True)
class RiskAssessment:
    level: RiskLevel
    paths: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def requires_manual_approval(self) -> bool:
        return self.level is RiskLevel.RED

    def to_dict(self) -> dict[str, object]:
        return {"level": self.level.value, "paths": list(self.paths), "reasons": list(self.reasons)}


def classify_paths(paths: Iterable[str]) -> RiskAssessment:
    """Classify paths deterministically; duplicate paths are removed and sorted."""
    normalized = tuple(sorted({_normalize_path(path) for path in paths}))
    reasons: set[str] = set()
    level = RiskLevel.GREEN
    for path in normalized:
        for reason, pattern in _RED_RULES:
            if pattern.search(path):
                reasons.add(reason)
                level = RiskLevel.RED
        for reason, pattern in _YELLOW_RULES:
            if pattern.search(path):
                reasons.add(reason)
                if level is RiskLevel.GREEN:
                    level = RiskLevel.YELLOW
    return RiskAssessment(level, normalized, tuple(sorted(reasons)))


_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_REF = re.compile(r"^[A-Za-z0-9._/-]+$")


def _validate_sha(value: str, label: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None:
        raise ValueError(f"{label} must be a 40-character lowercase commit SHA")
    return value


def build_cas_landing_command(expected_head: str, new_head: str, branch: str = "main") -> str:
    """Return a non-force atomic git ref update guarded by ``expected_head``."""
    expected = _validate_sha(expected_head, "expected_head")
    new = _validate_sha(new_head, "new_head")
    if not isinstance(branch, str) or _REF.fullmatch(branch) is None or branch.startswith("-"):
        raise ValueError("branch must be a safe git ref name")
    # Three positional arguments are git update-ref's compare-and-swap form:
    # update only when refs/heads/branch currently equals expected.
    return "git update-ref --no-deref " + " ".join(
        shlex.quote(value) for value in (f"refs/heads/{branch}", new, expected)
    )


@dataclass(frozen=True)
class ValidationReceipt:
    """Stable, serializable evidence that a change was validated."""

    commit: str
    risk: RiskAssessment
    checks: tuple[str, ...]
    passed: bool
    expected_head: str | None = None
    landing_command: str | None = None
    schema: str = "aigcnews.validation-receipt.v1"

    def __post_init__(self) -> None:
        _validate_sha(self.commit, "commit")
        if self.expected_head is not None:
            _validate_sha(self.expected_head, "expected_head")
        if self.landing_command is not None and "--force" in self.landing_command:
            raise ValueError("validation receipt cannot contain a force landing command")

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["risk"] = self.risk.to_dict()
        data["checks"] = list(self.checks)
        return data

    def serialize(self) -> str:
        """Serialize with stable key and array ordering for hashing/auditing."""
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def serialize_validation_receipt(receipt: ValidationReceipt) -> str:
    return receipt.serialize()


__all__ = [
    "RiskAssessment",
    "RiskLevel",
    "ValidationReceipt",
    "build_cas_landing_command",
    "classify_paths",
    "serialize_validation_receipt",
]
