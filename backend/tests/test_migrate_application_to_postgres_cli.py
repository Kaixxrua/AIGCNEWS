from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "migrate_application_to_postgres.py"


def load_script():
    spec = importlib.util.spec_from_file_location("migrate_application_to_postgres", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_application_transfer_cli_requires_target_for_plan() -> None:
    parser = load_script().build_parser()

    args = parser.parse_args(
        [
            "plan",
            "--job-id",
            "application-job",
            "--target-database",
            "aigc_news",
            "--target-schema",
            "public",
        ]
    )

    assert args.command == "plan"
    assert args.job_id == "application-job"
    assert args.target_database == "aigc_news"
    assert args.target_schema == "public"
    assert args.source_timezone == "UTC"


def test_application_transfer_cli_load_is_dry_run_by_default() -> None:
    parser = load_script().build_parser()

    args = parser.parse_args(
        [
            "load",
            "--job-id",
            "application-job",
            "--target-database",
            "aigc_news",
            "--target-schema",
            "public",
        ]
    )

    assert args.apply is False
    assert args.authorize_production is False
