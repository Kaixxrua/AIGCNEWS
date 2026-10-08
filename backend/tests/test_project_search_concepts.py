from pathlib import Path

from scripts.sync_project_search_concepts import generated_files


def test_go_concept_artifacts_match_canonical_python_table() -> None:
    root = Path(__file__).resolve().parents[2]
    for relative, expected in generated_files().items():
        assert (root / relative).read_text(encoding="utf-8") == expected, (
            f"{relative} drifted; run python scripts/sync_project_search_concepts.py"
        )
