import json
import re
from pathlib import Path

from backend.app.domain.project_search_patterns import concept_search_pattern

CONCEPT_PATTERN_CASES = json.loads(
    (Path(__file__).resolve().parents[2] / "mcp-go/internal/projectsem/testdata/concept_patterns.json")
    .read_text(encoding="utf-8")
)


def test_concept_patterns_preserve_literal_boundaries() -> None:
    for case in CONCEPT_PATTERN_CASES:
        actual = re.search(concept_search_pattern(case["term"]), case["text"], re.IGNORECASE)
        assert bool(actual) == case["match"], case
