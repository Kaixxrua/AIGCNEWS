from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "project_catalog_rehearsal_evidence.py"


def _module():
    spec = importlib.util.spec_from_file_location("project_catalog_rehearsal_evidence", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Response:
    status_code = 200
    headers = {"content-type": "application/json; charset=utf-8"}
    text = ""

    def json(self):
        return {"status": "ok"}


class SseResponse(Response):
    headers = {"content-type": "text/event-stream; charset=utf-8"}
    text = 'data: {"type":"progress","data":"secret payload"}\n\ndata: [DONE]\n\n'

    def json(self):
        raise ValueError


class Client:
    def __init__(self) -> None:
        self.calls = []

    def request(self, method, path, json=None):
        self.calls.append((method, path, json))
        return SseResponse() if path == "/api/report/daily/stream" else Response()


def test_fixed_suite_covers_rest_health_and_mcp_without_raw_payloads() -> None:
    module = _module()
    client = Client()

    cases = module._request_cases(client)

    assert {case["case_id"] for case in cases} >= {
        "live",
        "ready",
        "categories",
        "projects-exact",
        "projects-zh",
        "mcp-initialize",
        "mcp-tools-list",
        "mcp-search-exact",
        "mcp-search-zh",
        "sse-report",
    }
    assert all(len(case["response_sha256"]) == 64 for case in cases)
    assert "DeusData/codebase-memory-mcp" not in json.dumps(cases)
    assert "secret payload" not in json.dumps(cases)
    sse_case = next(case for case in cases if case["case_id"] == "sse-report")
    assert sse_case["content_type"] == "text/event-stream"
    assert any(call[0] == "POST" and call[1] == "/api/mcp" for call in client.calls)


def test_shadow_cohort_uses_only_queries_with_exact_legacy_v2_parity() -> None:
    module = _module()
    client = Client()

    cases = module._request_cases(client, shadow_cohort=True)

    case_ids = {case["case_id"] for case in cases}
    assert "mcp-search-exact" in case_ids
    assert "sse-report" in case_ids
    assert "mcp-search-zh" not in case_ids
    assert "projects-zh" not in case_ids
    assert "ready" not in case_ids


def test_digest_is_canonical_and_image_digest_accepts_repository_form() -> None:
    module = _module()
    assert module._digest({"b": 2, "a": 1}) == module._digest({"a": 1, "b": 2})
    assert module._sha256(f"backend@sha256:{'a' * 64}", "image") == "a" * 64
