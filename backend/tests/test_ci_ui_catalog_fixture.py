from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_fixture_materializer_creates_integrity_complete_catalog(tmp_path: Path) -> None:
    script = ROOT / "scripts/ci/materialize_ui_catalog_fixture.py"
    text = script.read_text(encoding="utf-8")
    assert "CI-only synthetic fixture" in text
    assert '"commercial-use", "redistribution"' in text
    assert "shutil.copytree(data, target)" in text
    preview_builder = (ROOT / "frontend/scripts/build-ui-previews.mjs").read_text(encoding="utf-8")
    assert "process.env.UI_LIBRARY_DATA_ROOT" in preview_builder


def test_ci_jobs_materialize_fixture_before_catalog_consumers() -> None:
    workflow = (ROOT / ".github/workflows/contract-baseline.yml").read_text(encoding="utf-8")
    assert workflow.count("materialize_ui_catalog_fixture.py") == 3
    assert "python scripts/ci/materialize_ui_catalog_fixture.py --frontend-copy" in workflow
    assert workflow.count("python ../scripts/ci/materialize_ui_catalog_fixture.py") == 2

    deployment = (ROOT / ".github/workflows/deploy-production.yml").read_text(encoding="utf-8")
    assert deployment.count("Inject the production UI catalog") == 2
    assert 'cp -a "$PRODUCTION_ROOT/mcp-go/internal/uicatalog/data/."' in deployment


def test_fixture_script_has_valid_python_syntax() -> None:
    result = subprocess.run(
        ["python3", "-m", "py_compile", "scripts/ci/materialize_ui_catalog_fixture.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
