from __future__ import annotations

import json

import pytest

from scripts.risk_controls import (
    RiskLevel,
    ValidationReceipt,
    build_cas_landing_command,
    classify_paths,
    serialize_validation_receipt,
)

SHA = "a" * 40
NEW_SHA = "b" * 40


def test_classifier_is_sorted_deduplicated_and_green_by_default() -> None:
    result = classify_paths(["backend/z.py", "backend/a.py", "backend/z.py"])
    assert result.level is RiskLevel.GREEN
    assert result.paths == ("backend/a.py", "backend/z.py")
    assert result.reasons == ()


def test_classifier_marks_yellow_and_red_with_stable_reasons() -> None:
    yellow = classify_paths(["backend/app/auth/service.py"])
    assert yellow.level is RiskLevel.YELLOW
    assert yellow.reasons == ("security or permissions",)

    red = classify_paths(["backend/app/postgres_migrations/001.sql", "docker-compose.yml"])
    assert red.level is RiskLevel.RED
    assert red.reasons == ("postgresql",)
    assert red.requires_manual_approval


def test_classifier_rejects_unsafe_paths() -> None:
    for path in ("/etc/passwd", "../secret", "a/../../secret", ""):
        with pytest.raises(ValueError):
            classify_paths([path])


def test_cas_command_is_serialized_and_never_force() -> None:
    command = build_cas_landing_command(SHA, NEW_SHA)
    assert command == f"git update-ref --no-deref refs/heads/main {NEW_SHA} {SHA}"
    assert "--force" not in command
    assert build_cas_landing_command(SHA, NEW_SHA, "release/main") .endswith("refs/heads/release/main " + NEW_SHA + " " + SHA)

    for value in ("bad", "A" * 40, "-x"):
        with pytest.raises(ValueError):
            build_cas_landing_command(value, NEW_SHA)
    with pytest.raises(ValueError):
        build_cas_landing_command(SHA, NEW_SHA, "main;git push")


def test_validation_receipt_is_canonical_and_rejects_force() -> None:
    receipt = ValidationReceipt(
        commit=NEW_SHA,
        risk=classify_paths(["backend/app/auth/service.py"]),
        checks=("pytest backend/tests/test_risk_controls.py", "ruff check scripts/risk_controls.py"),
        passed=True,
        expected_head=SHA,
        landing_command=build_cas_landing_command(SHA, NEW_SHA),
    )
    serialized = serialize_validation_receipt(receipt)
    assert serialized == receipt.serialize()
    assert serialized == json.dumps(json.loads(serialized), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert json.loads(serialized)["risk"]["level"] == "yellow"
    with pytest.raises(ValueError):
        ValidationReceipt(commit=NEW_SHA, risk=classify_paths([]), checks=(), passed=False, landing_command="git push --force")
