from __future__ import annotations

import json
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "project_search_quality_zh_cases.json"


def test_chinese_quality_fixture_keeps_judgments_separate_from_outputs() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert len(payload["cases"]) >= 8
    assert {case["intent"] for case in payload["cases"]} >= {
        "broad_chinese",
        "mixed_chinese_technical",
        "exact_lookup",
        "filtered_chinese",
        "unknown_name",
    }
    for case in payload["cases"]:
        assert "systems" not in case
        assert set(case["must_find"]).issubset(case["judgments"])
        assert all(0 <= relevance <= 3 for relevance in case["judgments"].values())
