from __future__ import annotations

import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.tests.parity import live_diff


class _ResponseHandler(BaseHTTPRequestHandler):
    response_status = 200
    response_body = b"ok"
    response_headers = {"Content-Type": "text/plain", "Content-Length": "2"}

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        self.send_response(self.response_status)
        for name, value in self.response_headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(self.response_body)

    def log_message(self, *_args) -> None:
        return


def _server(
    *,
    status: int = 200,
    body: bytes = b"ok",
    headers: dict[str, str] | None = None,
) -> ThreadingHTTPServer:
    handler = type(
        "ResponseHandler",
        (_ResponseHandler,),
        {
            "response_status": status,
            "response_body": body,
            "response_headers": headers
            or {"Content-Type": "text/plain", "Content-Length": str(len(body))},
        },
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _base_args(corpus_dir: Path, manifest: Path, python_mcp: str, go_mcp: str):
    return SimpleNamespace(
        corpus_dir=corpus_dir,
        manifest=manifest,
        replay="static",
        cases=None,
        timeout=2.0,
        warmup=0,
        ignore_header=[],
        include_volatile_headers=False,
        fail_fast=False,
        json_report=None,
        list=False,
        python_mcp=python_mcp,
        go_mcp=go_mcp,
    )


def _write_corpus(tmp_path: Path, *, name: str = "probe") -> tuple[Path, Path]:
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "surface.jsonl").write_text(
        json.dumps(
            {
                "name": name,
                "replay": "static",
                "request": {
                    "method": "GET",
                    "path": "/probe",
                    "headers": {},
                    "body": "",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "normalizations": [
                    {
                        "target": "response.header.mcp-session-id",
                        "pattern": r"^aigc-radar-[0-9a-f]{32}$",
                        "replacement": "<mcp-session-id>",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return corpus_dir, manifest


def test_load_cases_filters_replay_and_rejects_unknown(tmp_path: Path) -> None:
    corpus_dir, manifest = _write_corpus(tmp_path)
    (corpus_dir / "tools.jsonl").write_text(
        json.dumps(
            {
                "name": "stubbed-case",
                "replay": "stubbed",
                "request": {"method": "POST", "path": "/api/mcp", "body_b64": "/w=="},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    cases = live_diff.load_cases(corpus_dir, "static", None)
    assert [case.name for case in cases] == ["probe"]
    assert cases[0].body == b""
    assert live_diff.load_normalizations(manifest)[0][0] == "mcp-session-id"

    with pytest.raises(ValueError, match="unknown case"):
        live_diff.load_cases(corpus_dir, "static", ["missing"])


def test_normalize_exchange_applies_manifest_and_transport_rules() -> None:
    exchange = live_diff.Exchange(
        status=200,
        headers={
            "Date": "now",
            "Mcp-Session-Id": "aigc-radar-0123456789abcdef0123456789abcdef",
            "Content-Length": "2",
        },
        body=b"ok",
    )
    normalized = live_diff.normalize_exchange(
        exchange,
        live_diff.load_normalizations(live_diff.DEFAULT_MANIFEST),
        set(live_diff.DEFAULT_IGNORED_HEADERS),
    )
    assert normalized.headers == {
        "content-length": "2",
        "mcp-session-id": "<mcp-session-id>",
    }


def test_run_returns_zero_for_matching_live_responses(tmp_path: Path) -> None:
    corpus_dir, manifest = _write_corpus(tmp_path)
    python_server = _server()
    go_server = _server()
    try:
        args = _base_args(
            corpus_dir,
            manifest,
            f"http://127.0.0.1:{python_server.server_port}",
            f"http://127.0.0.1:{go_server.server_port}",
        )
        assert live_diff.run(args) == 0
    finally:
        python_server.shutdown()
        go_server.shutdown()


def test_url_resolves_mcp_endpoint_base_for_sibling_paths() -> None:
    assert live_diff._url("http://example.test/api/mcp", "/api/live") == (
        "http://example.test/api/live"
    )
    assert live_diff._url("http://example.test/api/mcp/", "/api/live") == (
        "http://example.test/api/live"
    )
    assert live_diff._url("http://example.test/api/", "/api/mcp") == (
        "http://example.test/api/mcp"
    )
    assert live_diff._url("http://example.test", "/api/mcp") == (
        "http://example.test/api/mcp"
    )


@pytest.mark.parametrize(
    ("base", "path"),
    [
        ("http://example.test?base=1", "/api/mcp"),
        ("http://example.test/api/mcp#fragment", "/api/mcp"),
        ("ftp://example.test", "/api/mcp"),
        ("http://example.test", "//other.test/api/mcp"),
        ("http://example.test", "/api/mcp?case=1"),
        ("http://example.test", "/api/../mcp"),
    ],
)
def test_url_rejects_ambiguous_base_or_corpus_path(base: str, path: str) -> None:
    with pytest.raises(ValueError):
        live_diff._url(base, path)


def test_run_returns_one_for_mismatching_body(tmp_path: Path) -> None:
    corpus_dir, manifest = _write_corpus(tmp_path)
    python_server = _server(body=b"python")
    go_server = _server(body=b"go")
    try:
        args = _base_args(
            corpus_dir,
            manifest,
            f"http://127.0.0.1:{python_server.server_port}",
            f"http://127.0.0.1:{go_server.server_port}",
        )
        assert live_diff.run(args) == 1
    finally:
        python_server.shutdown()
        go_server.shutdown()


def test_request_headers_adds_json_content_type_for_post() -> None:
    case = live_diff.CorpusCase(
        name="post",
        source="test",
        replay="static",
        app="both",
        method="POST",
        path="/api/mcp",
        headers={},
        body=b"{}",
    )
    assert live_diff._request_headers(case) == {"content-type": "application/json"}


def test_fetch_preserves_http_error_response() -> None:
    server = _server(status=400, body=b"bad")
    try:
        case = live_diff.CorpusCase(
            name="bad",
            source="test",
            replay="static",
            app="both",
            method="GET",
            path="/probe",
            headers={},
            body=b"",
        )
        exchange = live_diff.fetch(f"http://127.0.0.1:{server.server_port}", case, 2.0)
        assert exchange.error is None
        assert exchange.status == 400
        assert exchange.body == b"bad"
    finally:
        server.shutdown()


def test_load_cases_rejects_non_object_headers(tmp_path: Path) -> None:
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "bad.jsonl").write_text(
        json.dumps(
            {
                "name": "bad",
                "request": {"method": "GET", "path": "/probe", "headers": None},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="request headers must be an object"):
        live_diff.load_cases(corpus_dir, "static", None)


@pytest.mark.parametrize(
    "record",
    [
        {"name": "bad-path", "request": {"method": "GET", "path": "//elsewhere"}},
        {"name": "bad-query", "request": {"method": "GET", "path": "/probe?x=1"}},
        {"name": "bad-fragment", "request": {"method": "GET", "path": "/probe#part"}},
        {"name": "bad-traversal", "request": {"method": "GET", "path": "/a/../probe"}},
        {"name": "bad-replay", "replay": "live", "request": {"method": "GET", "path": "/probe"}},
        {"name": "bad-app", "app": "other", "request": {"method": "GET", "path": "/probe"}},
        {"name": "two-bodies", "request": {"method": "GET", "path": "/probe", "body": "", "body_b64": ""}},
    ],
)
def test_load_cases_rejects_invalid_metadata_and_request_forms(
    tmp_path: Path, record: dict[str, object]
) -> None:
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "bad.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        live_diff.load_cases(corpus_dir, "static", None)


def test_load_cases_rejects_duplicate_names_across_replay_classes(tmp_path: Path) -> None:
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    for filename, replay in (("a.jsonl", "static"), ("b.jsonl", "stubbed")):
        (corpus_dir / filename).write_text(
            json.dumps(
                {
                    "name": "duplicated",
                    "replay": replay,
                    "request": {"method": "GET", "path": "/probe"},
                }
            )
            + "\n",
            encoding="utf-8",
        )
    with pytest.raises(ValueError, match="duplicate case name"):
        live_diff.load_cases(corpus_dir, "static", None)


def test_load_normalizations_rejects_invalid_pattern(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "normalizations": [
                    {
                        "target": "response.header.x",
                        "pattern": "[",
                        "replacement": "x",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid pattern"):
        live_diff.load_normalizations(manifest)


@pytest.mark.parametrize(
    "normalizations",
    [
        [{"target": "response.body", "pattern": ".*", "replacement": ""}],
        [{"target": "response.header.bad header", "pattern": ".*", "replacement": ""}],
        [
            {"target": "response.header.x", "pattern": ".*", "replacement": ""},
            {"target": "response.header.X", "pattern": ".*", "replacement": ""},
        ],
    ],
)
def test_load_normalizations_rejects_unsupported_or_duplicate_targets(
    tmp_path: Path, normalizations: list[dict[str, str]]
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"normalizations": normalizations}), encoding="utf-8")
    with pytest.raises(ValueError):
        live_diff.load_normalizations(manifest)


def test_read_error_preserves_incomplete_response_body() -> None:
    partial = b"partial"
    error = http.client.IncompleteRead(partial, len(partial) + 1)
    exchange = live_diff._read_error_exchange(200, {"Content-Length": "8"}, error)
    assert exchange.status == 200
    assert exchange.body == partial
    assert exchange.error is not None
    assert "IncompleteRead" in exchange.error
