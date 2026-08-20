#!/usr/bin/env python3
"""Compare the live Python and Go MCP endpoints with the frozen corpus.

This is deliberately dependency-free so it can run on a host or CI runner before
pytest and the application test dependencies are installed.  It compares the
same request against both endpoints; it does not compare either endpoint to the
recorded response.  The default ``static`` selection avoids treating the
fixture-backed corpus as a live database contract.  Use ``--replay all`` only
when both servers point at equivalent data.

The command exits 0 when every selected request receives an identical response,
1 when both endpoints are reachable but at least one response differs, and 2
when a request cannot be completed against one or both endpoints.
"""

from __future__ import annotations

import argparse
import base64
import dataclasses
import difflib
import http.client
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CORPUS_DIR = SCRIPT_DIR / "corpus"
DEFAULT_MANIFEST = SCRIPT_DIR / "corpus_manifest.json"

# These headers are emitted by the two different HTTP servers or by an
# intermediary and are not part of the MCP contract.  Content-Length is not
# ignored: the corpus explicitly defines it as a body-derived contract.
DEFAULT_IGNORED_HEADERS = frozenset(
    {"connection", "date", "keep-alive", "server", "transfer-encoding"}
)
HTTP_TOKEN_PATTERN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


@dataclasses.dataclass(frozen=True)
class CorpusCase:
    name: str
    source: str
    replay: str
    app: str
    method: str
    path: str
    headers: Mapping[str, str]
    body: bytes


@dataclasses.dataclass(frozen=True)
class Exchange:
    status: int | None
    headers: Mapping[str, str]
    body: bytes
    error: str | None = None


@dataclasses.dataclass(frozen=True)
class Difference:
    case: str
    python: Exchange
    go: Exchange
    reason: str


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Diff identical parity-corpus requests against Python and Go MCP servers."
    )
    parser.add_argument(
        "--python-mcp",
        default="http://127.0.0.1:8001",
        help="Python MCP base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--go",
        dest="go_mcp",
        default="http://127.0.0.1:8002",
        help="Go MCP base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=DEFAULT_CORPUS_DIR,
        help="Directory containing the *.jsonl corpus files",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Corpus manifest containing response normalizations",
    )
    parser.add_argument(
        "--replay",
        choices=("static", "stubbed", "all"),
        default="static",
        help="Corpus class to run (default: %(default)s)",
    )
    parser.add_argument(
        "--case",
        dest="cases",
        action="append",
        metavar="NAME",
        help="Run only this case; may be supplied more than once",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Per-request timeout in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=0,
        help="Send each request this many times before comparing it",
    )
    parser.add_argument(
        "--ignore-header",
        action="append",
        default=[],
        metavar="NAME",
        help="Additional response header to ignore (repeatable)",
    )
    parser.add_argument(
        "--include-volatile-headers",
        action="store_true",
        help="Compare transport headers normally ignored by default",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first mismatch or request error",
    )
    parser.add_argument(
        "--json-report",
        type=Path,
        help="Also write a machine-readable report to this path",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List selected cases without sending requests",
    )
    return parser


def _decode_body(record: Mapping[str, Any]) -> bytes:
    if "body" in record and "body_b64" in record:
        raise ValueError("request must not contain both body and body_b64")
    if "body_b64" in record:
        body_b64 = record["body_b64"]
        if not isinstance(body_b64, str):
            raise ValueError("request body_b64 must be a string")
        return base64.b64decode(body_b64, validate=True)
    body = record.get("body", "")
    if not isinstance(body, str):
        raise ValueError("request body must be a string or body_b64")
    return body.encode("utf-8")


def _validate_path(raw_path: Any) -> str:
    if not isinstance(raw_path, str) or not raw_path.startswith("/"):
        raise ValueError("request path must be an absolute path string")
    parsed = urllib.parse.urlsplit(raw_path)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or raw_path.startswith("//")
        or any(segment in {".", ".."} for segment in parsed.path.split("/"))
    ):
        raise ValueError("request path must be an origin-relative path without query, fragment, or traversal")
    return parsed.path


def load_cases(corpus_dir: Path, replay: str, selected: Iterable[str] | None) -> list[CorpusCase]:
    if replay not in {"static", "stubbed", "all"}:
        raise ValueError(f"invalid replay class {replay!r}")
    selected_names = set(selected or ())
    records: list[CorpusCase] = []
    all_names: set[str] = set()
    selected_seen: set[str] = set()
    for path in sorted(corpus_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                    if not isinstance(item, Mapping):
                        raise ValueError("corpus record must be an object")
                    request = item["request"]
                    if not isinstance(request, Mapping):
                        raise ValueError("request must be an object")
                    name = item["name"]
                    method = request["method"]
                    request_headers = request.get("headers", {})
                    if not isinstance(name, str) or not name:
                        raise ValueError("name must be a non-empty string")
                    if name in all_names:
                        raise ValueError(f"duplicate case name {name!r}")
                    all_names.add(name)
                    if not isinstance(method, str) or not HTTP_TOKEN_PATTERN.fullmatch(method):
                        raise ValueError("request method must be an HTTP token")
                    request_path = _validate_path(request["path"])
                    if not isinstance(request_headers, Mapping):
                        raise ValueError("request headers must be an object")
                    if any(
                        not isinstance(key, str)
                        or not HTTP_TOKEN_PATTERN.fullmatch(key)
                        or not isinstance(value, str)
                        for key, value in request_headers.items()
                    ):
                        raise ValueError("request header names must be HTTP tokens and values must be strings")
                    case_replay = item.get("replay", "static")
                    if case_replay not in {"static", "stubbed"}:
                        raise ValueError("replay must be static or stubbed")
                    app = item.get("app", "both")
                    if app not in {"both", "main", "mcp"}:
                        raise ValueError("app must be both, main, or mcp")
                    body = _decode_body(request)
                    if selected_names and name in selected_names:
                        selected_seen.add(name)
                    if replay != "all" and case_replay != replay:
                        continue
                    if selected_names and name not in selected_names:
                        continue
                    records.append(
                        CorpusCase(
                            name=name,
                            source=path.name,
                            replay=case_replay,
                            app=app,
                            method=method.upper(),
                            path=request_path,
                            headers=dict(request_headers),
                            body=body,
                        )
                    )
                except (KeyError, TypeError, ValueError, base64.binascii.Error) as exc:
                    raise ValueError(f"{path}:{line_number}: invalid corpus record: {exc}") from exc
    missing = selected_names - selected_seen
    if missing:
        raise ValueError("unknown case(s): " + ", ".join(sorted(missing)))
    if not records:
        raise ValueError("no corpus cases selected")
    return records


def load_normalizations(manifest_path: Path) -> list[tuple[str, re.Pattern[str], str]]:
    with manifest_path.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, Mapping):
        raise ValueError("manifest must be an object")
    raw_rules = manifest.get("normalizations", [])
    if not isinstance(raw_rules, list):
        raise ValueError("manifest normalizations must be a list")
    rules: list[tuple[str, re.Pattern[str], str]] = []
    normalized_headers: set[str] = set()
    for index, rule in enumerate(raw_rules):
        if not isinstance(rule, Mapping):
            raise ValueError(f"normalization {index} must be an object")
        target = rule.get("target")
        pattern = rule.get("pattern")
        replacement = rule.get("replacement")
        if not all(isinstance(value, str) for value in (target, pattern, replacement)):
            raise ValueError(f"normalization {index} target, pattern, and replacement must be strings")
        prefix = "response.header."
        if not target.startswith(prefix):
            raise ValueError(f"normalization {index} has unsupported target {target!r}")
        name = target.removeprefix(prefix).lower()
        if not name or not HTTP_TOKEN_PATTERN.fullmatch(name):
            raise ValueError(f"normalization {index} has invalid response header target {target!r}")
        if name in normalized_headers:
            raise ValueError(f"normalization {index} duplicates response header {name!r}")
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"normalization {index} has invalid pattern: {exc}") from exc
        normalized_headers.add(name)
        rules.append((name, compiled, replacement))
    return rules


def _url(base: str, path: str) -> str:
    """Resolve a corpus path against an origin, /api, or /api/mcp base."""
    parsed = urllib.parse.urlsplit(base)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"invalid endpoint URL: {base!r}")
    request_path = _validate_path(path)
    base_path = parsed.path.rstrip("/")
    if base_path == "/api/mcp":
        # An MCP endpoint is only one member of the corpus's wider HTTP
        # surface. Resolve sibling paths such as /api/live and /docs from the
        # host origin, rather than from the MCP mount.
        resolved_path = request_path
    elif base_path == "/api" and request_path.startswith("/api/"):
        resolved_path = base_path + request_path.removeprefix("/api")
    elif base_path:
        resolved_path = base_path + "/" + request_path.lstrip("/")
    else:
        resolved_path = request_path
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, resolved_path, "", ""))


def _request_headers(case: CorpusCase) -> dict[str, str]:
    # Corpus headers are already lower-case, but accepting arbitrary case makes
    # hand-authored corpus extensions behave like the Python recorder.  The
    # recorder also supplies JSON content-type for POST cases that omit it.
    headers = {str(key): str(value) for key, value in case.headers.items()}
    if case.method == "POST" and "content-type" not in {key.lower() for key in headers}:
        headers["content-type"] = "application/json"
    return headers


def _partial_body(exc: BaseException) -> bytes:
    partial = getattr(exc, "partial", b"")
    return partial if isinstance(partial, bytes) else b""


def _response_exchange(status: int, headers: Any, body: bytes) -> Exchange:
    try:
        response_headers = _headers(headers)
    except (AttributeError, TypeError, ValueError) as exc:
        return Exchange(
            status=status,
            headers={},
            body=body,
            error=f"unable to read headers: {type(exc).__name__}: {exc}",
        )
    return Exchange(status=status, headers=response_headers, body=body)


def _read_error_exchange(status: int, headers: Any, exc: BaseException) -> Exchange:
    response = _response_exchange(status, headers, _partial_body(exc))
    header_error = f"; {response.error}" if response.error else ""
    return dataclasses.replace(
        response,
        error=f"{type(exc).__name__}: {exc}{header_error}",
    )


def fetch(base: str, case: CorpusCase, timeout: float) -> Exchange:
    try:
        request = urllib.request.Request(
            _url(base, case.path),
            data=case.body if case.method not in {"GET", "HEAD"} else None,
            headers=_request_headers(case),
            method=case.method,
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            try:
                body = response.read()
            except (OSError, http.client.HTTPException) as exc:
                return _read_error_exchange(response.status, response.headers, exc)
            return _response_exchange(response.status, response.headers, body)
    except urllib.error.HTTPError as exc:
        # HTTPError is also a response.  Reading its body is important for the
        # 400/401/405/429 surface cases and keeps the diff diagnostic useful.
        try:
            body = exc.read()
        except (OSError, http.client.HTTPException) as read_exc:
            return _read_error_exchange(exc.code, exc.headers, read_exc)
        return _response_exchange(exc.code, exc.headers, body)
    except (OSError, urllib.error.URLError, ValueError, http.client.HTTPException) as exc:
        return Exchange(status=None, headers={}, body=b"", error=f"{type(exc).__name__}: {exc}")


def _headers(headers: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in headers.keys():
        if hasattr(headers, "get_all"):
            values = headers.get_all(name) or []
        else:
            values = [headers[name]]
        result[str(name).lower()] = ", ".join(str(value) for value in values)
    return result


def normalize_exchange(
    exchange: Exchange,
    rules: list[tuple[str, re.Pattern[str], str]],
    ignored_headers: set[str],
) -> Exchange:
    normalized_headers = {
        str(name).lower(): str(value)
        for name, value in exchange.headers.items()
        if str(name).lower() not in ignored_headers
    }
    for name, pattern, replacement in rules:
        value = normalized_headers.get(name)
        if value is not None and pattern.fullmatch(value):
            normalized_headers[name] = replacement
    return dataclasses.replace(exchange, headers=dict(sorted(normalized_headers.items())))


def _body_diff(left: bytes, right: bytes) -> str:
    if left == right:
        return ""
    limit = min(len(left), len(right))
    index = next((i for i in range(limit) if left[i] != right[i]), limit)
    left_context = left[max(0, index - 32) : index + 32]
    right_context = right[max(0, index - 32) : index + 32]
    chunks = [
        f"first body byte difference at offset {index} "
        f"(python_len={len(left)}, go_len={len(right)})",
        f"python context: {left_context!r}",
        f"go context:     {right_context!r}",
    ]
    try:
        left_text = left.decode("utf-8").splitlines(keepends=True)
        right_text = right.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        return "\n".join(chunks)
    diff = "".join(difflib.unified_diff(left_text, right_text, "python", "go", n=1))
    if diff:
        chunks.append(diff[:6000])
    return "\n".join(chunks)


def compare(case: CorpusCase, python: Exchange, go: Exchange) -> Difference | None:
    if python.error or go.error:
        return Difference(case.name, python, go, "request error")
    reasons: list[str] = []
    if python.status != go.status:
        reasons.append(f"status python={python.status} go={go.status}")
    if python.headers != go.headers:
        reasons.append(f"headers python={python.headers!r} go={go.headers!r}")
    if python.body != go.body:
        reasons.append(_body_diff(python.body, go.body))
    if not reasons:
        return None
    return Difference(case.name, python, go, "\n".join(reasons))


def _exchange_json(exchange: Exchange) -> dict[str, Any]:
    return {
        "status": exchange.status,
        "headers": dict(exchange.headers),
        "body_utf8": exchange.body.decode("utf-8", errors="replace"),
        "body_length": len(exchange.body),
        **({"error": exchange.error} if exchange.error else {}),
    }


def _print_difference(diff: Difference) -> None:
    print(f"MISMATCH {diff.case}")
    if diff.python.error or diff.go.error:
        print(f"  python: {diff.python.error or 'ok'}")
        print(f"  go:     {diff.go.error or 'ok'}")
        return
    print(f"  python: HTTP {diff.python.status}")
    print(f"  go:     HTTP {diff.go.status}")
    print("  " + diff.reason.replace("\n", "\n  "))


def run(args: argparse.Namespace) -> int:
    if args.timeout <= 0:
        raise ValueError("--timeout must be positive")
    if args.warmup < 0:
        raise ValueError("--warmup must not be negative")
    cases = load_cases(args.corpus_dir, args.replay, args.cases)
    if args.list:
        for case in cases:
            print(f"{case.name}\t{case.replay}\t{case.method} {case.path}")
        return 0

    rules = load_normalizations(args.manifest)
    ignored = set() if args.include_volatile_headers else set(DEFAULT_IGNORED_HEADERS)
    ignored.update(str(name).lower() for name in args.ignore_header)
    differences: list[Difference] = []
    errors = 0
    executed = 0
    matching = 0
    for number, case in enumerate(cases, 1):
        python_exchange: Exchange | None = None
        go_exchange: Exchange | None = None
        for _ in range(args.warmup + 1):
            python_exchange = fetch(args.python_mcp, case, args.timeout)
            go_exchange = fetch(args.go_mcp, case, args.timeout)
            if python_exchange.error or go_exchange.error:
                break
        assert python_exchange is not None and go_exchange is not None
        executed += 1
        python_exchange = normalize_exchange(python_exchange, rules, ignored)
        go_exchange = normalize_exchange(go_exchange, rules, ignored)
        difference = compare(case, python_exchange, go_exchange)
        if difference is None:
            matching += 1
            print(f"OK         {number:03d}/{len(cases):03d} {case.name}")
            continue
        differences.append(difference)
        _print_difference(difference)
        if difference.python.error or difference.go.error:
            errors += 1
        if args.fail_fast:
            break

    skipped = len(cases) - executed
    print(
        f"\nLive diff: {len(cases)} case(s), "
        f"{matching} matching, "
        f"{len(differences)} differing, {errors} request error(s), "
        f"{skipped} skipped."
    )
    if args.json_report:
        report = {
            "python_mcp": args.python_mcp,
            "go_mcp": args.go_mcp,
            "replay": args.replay,
            "cases": len(cases),
            "executed": executed,
            "matching": matching,
            "differing": len(differences),
            "request_errors": errors,
            "skipped": skipped,
            "differences": [
                {
                    "case": difference.case,
                    "reason": difference.reason,
                    "python": _exchange_json(difference.python),
                    "go": _exchange_json(difference.go),
                }
                for difference in differences
            ],
        }
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return 2 if errors else (1 if differences else 0)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    sys.exit(main())
