"""Independent startup timing/ready-gate regressions; no browser or engine.

Run: E:/Anaconda3/python.exe -B godot/tools/test_startup_v118_contract.py -v
Inspect saved snapshots without inventing missing controls:
  ... test_startup_v118_contract.py --saved A.json B.json
The legacy-snapshot CLI exits 1 for INVALID_CAUSAL_AB, not a performance pass.
Inspect the actual v118 DOM dataset (startupTrace may be a JSON string):
  ... test_startup_v118_contract.py --trace artifacts/v118/startup-trace-01.json
Trace CLI exit 0 means internally consistent diagnostic evidence, NOT a
controlled A/B, compiler-only attribution, or first-frame performance pass.
Check the separately pinned, five-entry sunbreak-hoist experiment:
  ... test_startup_v118_contract.py --sunbreak artifacts/startup-v118/godot-analysis/sunbreak-hoist-01
Check the separate three-entry material-loop experiment (no new native run):
  ... test_startup_v118_contract.py --material-loops artifacts/startup-v118/godot-analysis/bounded-material-loops-01
Check the actual combined pack and optionally its separately captured native report:
  ... test_startup_v118_contract.py --combined artifacts/startup-v118/godot-analysis/combined-01 --native-report artifacts/loading-v115/runtime/combined-01-v122-independent.json
Check zero-unused-light eligibility of a byte-identical approved v117 lite pack:
  ... test_startup_v118_contract.py --zero-types-v117 artifacts/v117/index-lite.pck

Node VM executes the actual loader/controls with queued RAF callbacks and
controllable promises. Simulated milliseconds prove ordering, NOT performance.
This adds no shipping instrumentation, modifies no input, and writes no files.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]


def number(value):
    """Missing/invalid telemetry is unknown, never a fabricated zero."""
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def inspect_saved(record):
    fields = ("runtimeStartMs", "engineStartedMs", "sceneSignalMs", "loadMs", "loadHiddenMs",
              "startupAuditMs", "startupAuditStartedAtMs", "startupAuditFinishedAtMs")
    values = {key: number(record.get(key)) for key in fields}
    startup_size = [number(record.get("startupAuditCanvasWidth")), number(record.get("startupAuditCanvasHeight"))]
    readout_size = [number(record.get("width")), number(record.get("height"))]
    known_size = all(v is not None and v > 0 for v in startup_size + readout_size)
    intervals = {}
    # These two pairs each share an actual source-defined origin. Do NOT
    # subtract loader-relative, controls-relative, or page-absolute clocks.
    for name, end, start in (("loaderStartToContinuationMs", "engineStartedMs", "runtimeStartMs"),
                              ("controlsSceneToOverlayMs", "loadMs", "sceneSignalMs")):
        a, b = values[end], values[start]
        intervals[name] = a - b if a is not None and b is not None and a >= b else None
    return {
        "status": "OBSERVATION_ONLY", "markers": values, "withinClockIntervals": intervals,
        "startupBackingSize": startup_size, "readoutBackingSize": readout_size,
        "startupDpr": number(record.get("startupAuditDpr")),
        "backingChangedAfterStartup": startup_size != readout_size if known_size else None,
        "auditStatus": record.get("startupAuditStatus"),
        "auditEnabled": record.get("startupAuditEnabled"),
        "auditDebugBuild": record.get("startupAuditDebugBuild"),
        "limitations": [
            "Legacy snapshots lack a common captured page time origin and milestone provenance.",
            "No visibility/focus/resize history, profiler/cache cohort or tool observation timestamp is established.",
            "loadHiddenMs=0 alone does not prove an unthrottled foreground run.",
            "No callMain exit or independently evidenced presented-frame milestone is available.",
        ],
    }


def inspect_pair(a, b):
    reports = [inspect_saved(a), inspect_saved(b)]
    reasons = ["Legacy terminal snapshots alone do not establish a controlled causal A/B comparison"]
    if reports[0]["startupBackingSize"] != reports[1]["startupBackingSize"]:
        reasons.append("Different startup backing canvas dimensions")
    da, db = (r["startupDpr"] for r in reports)
    if da is None or db is None:
        reasons.append("Startup DPR is missing")
    elif not math.isclose(da, db, rel_tol=0, abs_tol=1e-6):
        reasons.append("Different startup DPR")
    if any(r["backingChangedAfterStartup"] is True for r in reports):
        reasons.append("Backing canvas changed between startup and saved readout")
    if any(r["backingChangedAfterStartup"] is None for r in reports):
        reasons.append("Backing canvas stability is unknown")
    return {"status": "INVALID_CAUSAL_AB", "reasons": reasons, "runs": reports,
            "speedup": None, "note": "Only same-origin spans are reported; no audit-duration subtraction or root attribution."}


def interval_coverage(intervals, start, end):
    """Union clipped intervals; overlapping scopes must never be double-counted."""
    clipped = sorted((max(start, a), min(end, b)) for a, b in intervals
                     if min(end, b) > max(start, a))
    merged = []
    for a, b in clipped:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return math.fsum(b - a for a, b in merged)


def inspect_trace(record, aggregation="unknown"):
    """Read-only validation of main's actual trace schema, not new instrumentation.

    Published trace-01 rounds its accumulator on EVERY call. A worst-case
    0.05 ms/call bound also safely covers unknown versions. Only an explicitly
    source-reviewed final-round-only tracer gets a 0.05 ms aggregate bound.
    The bounded slow list classifies its own calls, never unrecorded calls.
    """
    if aggregation not in ("unknown", "per-call-rounded", "final-round-only"):
        raise ValueError("Unknown aggregation mode")
    errors = []
    failed = {"status": "INVALID_TRACE", "errors": errors, "performanceAccepted": False}
    raw = record.get("startupTrace") if isinstance(record, dict) else None
    try:
        trace = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        errors.append("startupTrace is not valid JSON")
        return failed
    if not isinstance(trace, dict):
        errors.append("Missing startupTrace object/string")
        return failed
    elapsed = number(trace.get("elapsedMs"))
    if trace.get("status") != "completed" or elapsed is None or elapsed <= 0:
        errors.append("Trace is incomplete or its elapsedMs is invalid")
    marks, totals, slow = (trace.get(key) for key in ("marks", "totals", "slow"))
    if not isinstance(marks, list) or not isinstance(totals, dict) or not isinstance(slow, list):
        errors.append("marks/totals/slow have invalid types")
    if errors:
        return failed

    required = ("runtimeStartMs", "sceneReady", "engineStartedMs", "presentation")
    boundaries = {}
    prior = -1.0
    for index, row in enumerate(marks):
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            errors.append(f"Invalid mark {index}")
            continue
        ms = number(row.get("ms"))
        if ms is None or ms < prior or ms > elapsed + 0.1:
            errors.append(f"Invalid/non-monotonic mark timestamp {index}")
            continue
        prior = ms
        if row["name"] in required:
            if row["name"] in boundaries:
                errors.append(f"Duplicate boundary {row['name']}")
            boundaries[row["name"]] = ms
    if any(key not in boundaries for key in required):
        errors.append("Missing required same-origin trace boundaries")
    elif not (boundaries["runtimeStartMs"] <= min(boundaries["sceneReady"], boundaries["engineStartedMs"])
              and max(boundaries["sceneReady"], boundaries["engineStartedMs"]) <= boundaries["presentation"]):
        errors.append("Required boundaries are out of order")

    clean_totals = {}
    for name, row in totals.items():
        if not isinstance(row, dict):
            errors.append(f"Invalid total {name}")
            continue
        calls, ms, maximum = (number(row.get(key)) for key in ("calls", "ms", "maxMs"))
        if calls is None or not calls.is_integer() or ms is None or maximum is None:
            errors.append(f"Invalid numeric total {name}")
            continue
        rounding = 0.05 if aggregation == "final-round-only" else calls * 0.05
        if maximum > ms + rounding + 0.05 or (calls == 0 and (ms or maximum)):
            errors.append(f"Inconsistent maximum/calls in {name}")
        clean_totals[name] = {"calls": int(calls), "ms": ms, "maxMs": maximum,
                              "aggregateRoundingBoundMs": round(rounding, 6)}
    if "getProgramParameter" not in clean_totals:
        errors.append("Missing getProgramParameter total")

    # These bounds come from the inspected published/current tracer, not an
    # inference that PerformanceObserver delivered every pending long task.
    if len(slow) > 200:
        errors.append("Slow list exceeds the source-defined 200-entry bound")
    clean_slow = []
    previous_end = -1.0
    for index, row in enumerate(slow):
        if (not isinstance(row, dict) or not isinstance(row.get("name"), str)
                or row["name"] not in clean_totals):
            errors.append(f"Invalid/unknown slow call {index}")
            continue
        start, ms = number(row.get("startMs")), number(row.get("ms"))
        if start is None or ms is None or ms < 20 or start + ms > elapsed + 0.15:
            errors.append(f"Invalid/out-of-window slow call {index}")
            continue
        # Start and duration round independently to 0.1 ms. A material overlap
        # cannot represent these unnested synchronous WebGL calls faithfully.
        if start < previous_end - 0.15:
            errors.append(f"Overlapping/non-monotonic slow call {index}")
        previous_end = start + ms
        clean_slow.append({**row, "startMs": start, "ms": ms})
    for name, total in clean_totals.items():
        rows = [row for row in clean_slow if row["name"] == name]
        duration = math.fsum(row["ms"] for row in rows)
        tolerance = total["aggregateRoundingBoundMs"] + len(rows) * 0.05 + 0.1
        remaining = total["calls"] - len(rows)
        if remaining < 0 or duration > total["ms"] + tolerance:
            errors.append(f"Slow records exceed aggregate {name}")
        if len(slow) < 200:
            if total["ms"] - duration > remaining * 20 + tolerance:
                errors.append(f"Uncapped slow list omits required slow calls for {name}")
            observed_max = max((row["ms"] for row in rows), default=0)
            if total["maxMs"] > max(20, observed_max) + 0.1:
                errors.append(f"Uncapped slow list omits maximum for {name}")
        if rows and max(row["ms"] for row in rows) > total["maxMs"] + 0.1:
            errors.append(f"Slow duration exceeds recorded maximum for {name}")
    if errors:
        return failed

    queries = [row for row in clean_slow if row["name"] == "getProgramParameter"]
    links = [row for row in queries if row.get("parameter") == 35714]
    intervals = [(row["startMs"], row["startMs"] + row["ms"]) for row in links]
    total = clean_totals["getProgramParameter"]
    phases = {}
    for label, left, right in (("runtimeStartToScene", "runtimeStartMs", "sceneReady"),
                               ("sceneToContinuation", "sceneReady", "engineStartedMs"),
                               ("continuationToOverlayOpportunity", "engineStartedMs", "presentation")):
        a, b = boundaries[left], boundaries[right]
        if b < a:
            # Ready gates may legitimately arrive in either order. Do not
            # fabricate a negative latency if a later implementation does so.
            phases[label] = {"spanMs": None, "observedLinkStatusCoverageMs": None,
                             "callsStartingInPhase": None, "reason": "End boundary precedes start"}
            continue
        covered = interval_coverage(intervals, a, b)
        phases[label] = {"spanMs": round(b - a, 3), "observedLinkStatusCoverageMs": round(covered, 3),
                         "callsStartingInPhase": sum(a <= row["startMs"] < b for row in links)}
    canvas = trace.get("canvas")
    startup = [number(record.get("startupAuditCanvasWidth")), number(record.get("startupAuditCanvasHeight"))]
    return {
        "status": "VALID_DIAGNOSTIC_TRACE", "errors": [], "performanceAccepted": False,
        "traceElapsedMs": elapsed, "aggregationAssumption": aggregation,
        "reportedControlsLoadMs": number(record.get("loadMs")),
        "boundariesTraceRelativeMs": boundaries, "phases": phases,
        "getProgramParameter": {**total, "fractionOfTracedElapsed": total["ms"] / elapsed,
                                "slowRecordedCalls": len(queries),
                                "unclassifiedUnrecordedCalls": total["calls"] - len(queries)},
        "linkStatusSlowCalls": {
            "parameter": 35714, "calls": len(links),
            "sumMs": round(math.fsum(row["ms"] for row in links), 3),
            "sumRoundingBoundMs": round(len(links) * 0.05, 6),
            "unionMs": round(interval_coverage(intervals, 0, elapsed), 3),
            "fractionOfTracedElapsed": interval_coverage(intervals, 0, elapsed) / elapsed,
            "slowQueryParameters": dict(Counter(str(row.get("parameter", "unknown")) for row in queries)),
            "topCalls": sorted(links, key=lambda row: row["ms"], reverse=True)[:10],
        },
        "slowList": {"entries": len(slow), "capReached": len(slow) == 200,
                     "counts": dict(Counter(row["name"] for row in clean_slow))},
        "context": {"renderer": trace.get("renderer"), "finalBackingCanvas": canvas,
                    "startupAuditBackingCanvas": startup, "finalDpr": number(trace.get("dpr")),
                    "startupAuditDpr": number(record.get("startupAuditDpr")),
                    "finalVisibility": trace.get("visibility"), "finalFocused": trace.get("focused"),
                    "fullVisibilityFocusResizeHistoryEstablished": False},
        "limitations": [
            "API scopes measure synchronous elapsed wall time, not compiler CPU time; driver/GPU queue waits and scheduling may contribute.",
            "Program IDs are run-local identities, not shader-source hashes or stable A/B correspondences.",
            "Only slow rows carry query parameters; unrecorded getProgramParameter calls are not assumed LINK_STATUS.",
            "Trace-relative marks share an origin; no ResourceTiming or controls-origin offset is inferred.",
            "presentation means the finish/overlay RAF opportunity, not proof of actual rendered pixels.",
            "Long-task delivery is asynchronous; the trace disconnects its observer at finish and cannot prove complete delivery.",
            "This profiled single run localizes waits but does not establish a controlled unprofiled speedup or performance acceptance.",
        ],
    }


HOIST_SOURCE_SHA = "018ae7b592213c3dedb7f538cde84c08f17935487d9da8349873106abfe5ed79"
HOIST_CANDIDATE_SHA = "4618be05599075c5377045597984b5afb146ea1263012fee1d32d818fe396588"
HOIST_SHARED = "shaders/meadow_sunbreak.gdshaderinc"
HOIST_CONSUMERS = frozenset("shaders/" + name for name in (
    "meadow_cutout_surface.gdshaderinc", "meadow_ground_surface.gdshaderinc",
    "meadow_leaves.gdshader", "meadow_limestone.gdshader"))
HOIST_ALLOWED = HOIST_CONSUMERS | {HOIST_SHARED}
HOIST_ACTIVE_ROOTS = frozenset("shaders/" + name + ".gdshader" for name in (
    "meadow_cutout", "meadow_grove_day", "meadow_ground", "meadow_ground_day",
    "meadow_leaves", "meadow_limestone"))
HOIST_VALUE = b"sunbreak_fragment_transmission"
HOIST_EXPRESSION = b"sunbreak_transmission(sunbreak_position)"
HOIST_ASSIGNMENT = b"    " + HOIST_VALUE + b" = " + HOIST_EXPRESSION + b";"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def shader_code(blob):
    # Preserve quoted res:// paths; a naive // remover would corrupt includes.
    return re.sub(rb'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/',
                  lambda match: match[0] if match[0].startswith(b'"') else b"\n" * match[0].count(b"\n"), blob)


def shader_body(blob, name):
    """Small fail-closed extractor for this pinned shader grammar, not a compiler."""
    code = shader_code(blob)
    matches = list(re.finditer(rb"\b(?:void|float)\s+" + name.encode() + rb"\s*\([^)]*\)\s*\{", code))
    require(len(matches) == 1, f"Expected one {name}() definition")
    start = matches[0].end()
    depth = 1
    for index in range(start, len(code)):
        if code[index] == 123:
            depth += 1
        elif code[index] == 125:
            depth -= 1
            if not depth:
                return code[start:index]
    raise ValueError(f"Unterminated {name}()")


def expanded_shader(blobs, path, defines=None, trail=()):
    """Resolve only observed include/condition forms, with no C-preprocessor eval.

    This verifies ALL packed wrapper consumers under GLES compatibility. It
    deliberately rejects an unfamiliar directive rather than guessing its gate.
    """
    require(path in blobs and path not in trail and len(trail) < 32, "Missing/cyclic shader include")
    defines = set() if defines is None else defines
    active, conditions, result = True, [], []
    for line in shader_code(blobs[path]).splitlines(keepends=True):
        directive = re.match(rb"\s*#(\w+)\s*(.*?)\s*$", line)
        if not directive:
            if active:
                result.append(line)
            continue
        op, argument = directive.groups()
        if op in (b"ifdef", b"ifndef", b"if"):
            if op == b"if":
                require(argument == b"CURRENT_RENDERER == RENDERER_COMPATIBILITY", "Unreviewed shader #if")
                condition = True
            else:
                require(re.fullmatch(rb"\w+", argument), "Unreviewed conditional macro")
                condition = (argument in defines) == (op == b"ifdef")
            conditions.append((active, condition, False))
            active = active and condition
        elif op == b"else":
            require(conditions and not conditions[-1][2], "Unmatched/duplicate #else")
            parent, condition, _ = conditions[-1]
            conditions[-1] = (parent, condition, True)
            active = parent and not condition
        elif op == b"endif":
            require(conditions, "Unmatched #endif")
            active = conditions.pop()[0]
        elif op == b"define":
            require(re.fullmatch(rb"\w+", argument), "Unreviewed value/function macro")
            if active:
                defines.add(argument)
        elif op == b"include":
            match = re.fullmatch(rb'"res://(shaders/[^".]+\.gdshaderinc)"', argument)
            require(match is not None, "Unreviewed include syntax/path")
            if active:
                result.append(expanded_shader(blobs, match[1].decode(), defines, trail + (path,)))
        else:
            raise ValueError(f"Unreviewed shader directive {op!r}")
    require(not conditions, "Unclosed preprocessor condition")
    return b"".join(result)


def verify_sunbreak_sources(before, after):
    require(set(before) == set(after) and len(before) == 184, "PCK resource membership/count changed")
    changed = {path for path in before if before[path] != after[path]}
    require(changed == HOIST_ALLOWED, "Expected exactly the five sunbreak shader edits")
    for path in sorted(changed):
        old, new = before[path], after[path]
        nl = b"\r\n" if b"\r\n" in old else b"\n"
        if path == HOIST_SHARED:
            declaration = b"varying float " + HOIST_VALUE + b";" + nl
            read = b"transmission = " + HOIST_VALUE + b";"
            require(new.count(declaration) == new.count(read) == 1, "Shared declaration/read multiplicity")
            reverted = new.replace(declaration, b"").replace(read, b"transmission = " + HOIST_EXPRESSION + b";")
            require(shader_body(new, "light").replace(HOIST_VALUE, HOIST_EXPRESSION) == shader_body(old, "light"),
                    "Directional-light predicate or downstream light response changed")
            for name in ("sunbreak_hash", "sunbreak_noise", "sunbreak_scope", "sunbreak_transmission", "sunbreak_fresnel"):
                require(shader_body(old, name) == shader_body(new, name), f"Changed cloud/light function {name}")
        else:
            insertion = HOIST_ASSIGNMENT + nl
            require(new.count(insertion) == 1, "Each consumer needs exactly one direct assignment")
            require(b"    sunbreak_specular = SPECULAR;" + nl + insertion in new, "Assignment must follow existing per-fragment specular write")
            reverted = new.replace(insertion, b"")
            require(shader_body(old, "vertex") == shader_body(new, "vertex"), "Vertex behavior changed")
        require(reverted == old, f"Unexplained source/precision/uniform/default/guard edit: {path}")

    pure = b"\n".join(shader_body(after[HOIST_SHARED], name) for name in (
        "sunbreak_hash", "sunbreak_noise", "sunbreak_scope", "sunbreak_transmission"))
    require(not re.search(rb"\b(?:LIGHT\w*|NORMAL\w*|VIEW\w*|dFdx|dFdy|fwidth|texture\w*|discard)\b", pure),
            "Hoisted computation has a light/stage/derivative/texture dependency")
    require(b"sunbreak_position" not in pure, "Pure function must use its world argument, not writable stage state")

    consumers, inactive = [], []
    roots = sorted(path for path in before if path.endswith(".gdshader"))
    require(len(roots) == 20, "Expected all 20 packed shader roots")
    for path in roots:
        old, new = expanded_shader(before, path), expanded_shader(after, path)
        if HOIST_VALUE not in new:
            require(new == old, f"Inactive shader changed after preprocessing: {path}")
            inactive.append(path)
            continue
        vertex, fragment, light = (shader_body(new, stage) for stage in ("vertex", "fragment", "light"))
        require(new.count(b"varying float " + HOIST_VALUE + b";") == 1, f"Varying declaration missing/duplicated: {path}")
        require(fragment.count(HOIST_ASSIGNMENT) == 1, f"Fragment must assign exactly once: {path}")
        require(HOIST_VALUE not in vertex and HOIST_EXPRESSION not in vertex, f"Vertex interpolation approximation: {path}")
        require(HOIST_EXPRESSION not in light and light.count(HOIST_VALUE) == 1, f"Repeated/missing light-stage read: {path}")
        prefix = fragment.split(HOIST_ASSIGNMENT)[0]
        require(prefix.count(b"{") == prefix.count(b"}") and not re.search(rb"\b(?:return|discard)\b", prefix),
                f"Assignment does not dominate every live fragment path: {path}")
        require(vertex == shader_body(old, "vertex"), f"Expanded vertex changed: {path}")
        require(light.replace(HOIST_VALUE, HOIST_EXPRESSION) == shader_body(old, "light"), f"Expanded light predicate/response changed: {path}")
        consumers.append(path)
    require(set(consumers) == HOIST_ACTIVE_ROOTS, "Unexpected active sunbreak consumers")
    return {"changedEntries": sorted(changed), "activeShaderConsumers": consumers,
            "inactiveExpandedShadersExact": inactive, "all20ShaderRootsChecked": True,
            "fourDirectFragmentWriters": sorted(HOIST_CONSUMERS), "perFragmentNotVertexInterpolated": True,
            "lightPredicateAndResponseExactAfterSingleReadReversal": True,
            "mathConclusion": "Same pure f(interpolated world position, clock, night, strength) once per fragment; same per-light predicate selects f or 1. No GPU bit-exactness claim."}


def sunbreak_inputs(directory):
    # Reuse only the read-only PCK parser; never the candidate builder/validator.
    from inspect_web_pack import read_pack
    directory = directory.resolve()
    manifest = json.loads((directory / "shader-replacements.v1.json").read_text(encoding="utf-8-sig"))
    source = Path(manifest["sourcePck"])
    candidate = directory / "index-lite.pck"
    blobs, hashes, inventories = [], [], []
    for path, pin in ((source, HOIST_SOURCE_SHA), (candidate, HOIST_CANDIDATE_SHA)):
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        require(digest == pin, f"Unreviewed input PCK hash: {path}")
        inventory = read_pack(path, verify=True)
        require(inventory["version"] == 4 and inventory["engine"] == [4, 7, 2], "Wrong PCK/engine version")
        blobs.append({row["path"]: payload[row["offset"]:row["offset"] + row["bytes"]] for row in inventory["entries"]})
        hashes.append(digest)
        inventories.append(inventory)
    return directory, manifest, blobs, hashes, inventories


def inspect_sunbreak(directory):
    directory, manifest, (before, after), hashes, inventories = sunbreak_inputs(directory)
    evidence = verify_sunbreak_sources(before, after)
    require(manifest["schema"] == "fast-shader-pack-v1" and manifest["profile"] == "sunbreak-hoist-only", "Wrong experiment manifest")
    require(manifest["sourcePckSha256"] == hashes[0] and manifest["candidatePckSha256"] == hashes[1], "Manifest PCK pin mismatch")
    require(Path(manifest["candidatePck"]).resolve() == directory / "index-lite.pck", "Manifest points to another candidate")
    require(manifest["candidateBytes"] == inventories[1]["bytes"] == 44327596, "Candidate length mismatch")
    proof_path = directory / "proof.json"
    require(Path(manifest["proof"]).resolve() == proof_path and Path(manifest["diff"]).resolve() == directory / "shader.diff", "Unbound proof/diff path")
    rows = manifest["replacements"]
    require(len(rows) == 5 and {row["path"] for row in rows} == HOIST_ALLOWED, "Manifest replacement membership mismatch")
    for row in rows:
        path = row["path"]
        require(Path(row["file"]).resolve() == directory / "replacement" / path and Path(row["proof"]).resolve() == proof_path,
                "Replacement payload/proof points elsewhere")
        require(Path(row["file"]).read_bytes() == after[path] and (directory / "original" / path).read_bytes() == before[path], "Exported proof payload differs from actual PCK")
        for prefix, content in (("before", before[path]), ("after", after[path])):
            require(row[prefix + "Sha256"] == hashlib.sha256(content).hexdigest() and row[prefix + "Bytes"] == len(content), "Per-entry manifest pin/length mismatch")
    proof = json.loads(proof_path.read_text(encoding="utf-8-sig"))
    require(proof["sourcePckSha256"] == hashes[0] and proof["candidatePckSha256"] == hashes[1], "Proof PCK pin mismatch")
    require(proof["entryCount"] == 184 and proof["unchangedEntries"] == 179 and proof["changedEntries"] == evidence["changedEntries"], "Proof entry counts/delta disagree with bytes")
    compilation = proof["shaderLanguageValidation"]
    for label in ("baseline", "candidate"):
        recorded = json.loads((directory / (label + "-shader-compile.json")).read_text(encoding="utf-8-sig"))
        require(recorded == compilation[label] and recorded["ok"] is True and recorded["shaderCount"] == 20,
                "Compiled-interface proof disagrees with recorded result")
        for suffix in ("-engine.log", "-console.log"):
            text = (directory / (label + suffix)).read_text(encoding="utf-8-sig")
            require(not re.search(r"(?:SHADER ERROR|SCRIPT ERROR|\bERROR:)", text), "Shader-language proof log contains an error")
    require(compilation["baseline"]["uniforms"] == compilation["candidate"]["uniforms"], "Compiled uniform interfaces changed")
    entry_proofs = [{"path": path, "bytes": len(before[path]), "sha256": hashlib.sha256(before[path]).hexdigest(),
                     "byteExact": before[path] == after[path]} for path in sorted(before) if path not in HOIST_ALLOWED]
    require(len(entry_proofs) == 179 and all(row["byteExact"] for row in entry_proofs), "Unapproved pack payload change")
    return {"status": "PASS_BOUNDED_STRUCTURE_AND_SOURCE", "performanceAccepted": False, "webVisualAccepted": False,
            "sourcePckSha256": hashes[0], "candidatePckSha256": hashes[1], "sourceBytes": inventories[0]["bytes"],
            "candidateBytes": inventories[1]["bytes"], "entryCount": 184, "unchangedEntryCount": 179,
            "semantics": evidence, "unchangedEntries": entry_proofs, "shaderLanguageInterfacesExact": True,
            "proofSha256": hashlib.sha256(proof_path.read_bytes()).hexdigest(),
            "manifestSha256": hashlib.sha256((directory / "shader-replacements.v1.json").read_bytes()).hexdigest(),
            "limitations": ["This exact candidate only; not a relaxed generic shader replacement policy.",
                            "Language/native checks do not execute ANGLE GLSL or measure Web startup.",
                            "Pure computation is now unconditional per fragment; later frame/night/driver cost needs live measurement."]}


MATERIAL_SHA = "b5eca5aae8e70bb8c9b0b3b14ec7aead1352cb29aadff4b3d66aac960d4a6f2c"
MATERIAL_GROUND = "shaders/meadow_ground_surface.gdshaderinc"
MATERIAL_COUNT_LOOPS = {"shaders/meadow_cutout_surface.gdshaderinc": ("window_count", 12),
                        "shaders/meadow_architecture.gdshaderinc": ("architecture_count", 8)}
MATERIAL_ALLOWED = frozenset(MATERIAL_COUNT_LOOPS) | {MATERIAL_GROUND}
MATERIAL_NAME = b"contact_shadow_iterations"
MATERIAL_DECLARATION = b"uniform int contact_shadow_iterations = 72;"
MATERIAL_BOUND = b"for (int i = 0; i < clamp(contact_shadow_iterations, 0, 72); i++)"
MATERIAL_UNIFORM_ROOTS = frozenset(("res://shaders/meadow_ground.gdshader", "res://shaders/meadow_ground_day.gdshader"))


def undo_material_loops(before, after):
    """Reverse only the three reviewed edits, retaining any hoist additions."""
    require(set(before) == set(after) and len(before) == 184, "Material-loop resource membership/count changed")
    restored = dict(after)
    for path in MATERIAL_ALLOWED:
        old, new = before[path], after[path]
        nl = b"\r\n" if b"\r\n" in old else b"\n"
        if path == MATERIAL_GROUND:
            require(new.count(MATERIAL_DECLARATION + nl) == new.count(MATERIAL_BOUND) == 1,
                    "Require sole integer default72 declaration and exact two-sided clamp")
            require(b"uniform vec4 contact_shadows[72];" + nl + MATERIAL_DECLARATION + nl in new,
                    "Ground declaration/array capacity changed")
            restored[path] = new.replace(MATERIAL_DECLARATION + nl, b"").replace(
                MATERIAL_BOUND, b"for (int i = 0; i < 72; i++)")
        else:
            name, indent = MATERIAL_COUNT_LOOPS[path]
            new_head = f"for (int i = 0; i < min(32, {name}); i++) {{".encode() + nl
            guard = f"if (i >= {name}) {{ break; }}".encode()
            old_head = b"for (int i = 0; i < 32; i++) {" + nl + b" " * indent + guard + nl
            require(new.count(new_head) == 1 and guard not in new, "Count bound or redundant-break removal differs")
            restored[path] = new.replace(new_head, old_head)
    return restored


def verify_material_sources(before, after, combined=False):
    """Source-only composition guard. combined=True does not certify any PCK."""
    allowed = MATERIAL_ALLOWED | HOIST_ALLOWED if combined else MATERIAL_ALLOWED
    changed = {path for path in before if before[path] != after.get(path)}
    require(changed == allowed and set(before) == set(after), "Wrong standalone/combined changed-entry set")
    restored = undo_material_loops(before, after)
    if combined:
        verify_sunbreak_sources(before, restored)
    else:
        require(restored == before, "Loop body/order/default/unlisted shader change")
    changed_roots, exact_roots = [], []
    for path in sorted(p for p in before if p.endswith(".gdshader")):
        old, new = expanded_shader(before, path), expanded_shader(after, path)
        (changed_roots if new != old else exact_roots).append(path)
        count = new.count(MATERIAL_DECLARATION)
        require(count == (1 if "res://" + path in MATERIAL_UNIFORM_ROOTS else 0), "Ground uniform leaks into another wrapper")
        if "res://" + path not in MATERIAL_UNIFORM_ROOTS:
            require(MATERIAL_NAME not in new, "Unexpected new-uniform use")
    return {"mode": "hoist-plus-material-loops-source-only" if combined else "material-loops-only",
            "changedEntries": sorted(changed), "unchangedEntryCount": 184 - len(changed),
            "changedExpandedShaderRoots": changed_roots, "exactExpandedShaderRoots": exact_roots,
            "allExistingUniformDeclarationsAndDefaultsExact": True, "allUniformInterfacesExact": False,
            "newUniform": {"name": MATERIAL_NAME.decode(), "type": "int", "default": 72, "clamp": [0, 72],
                           "shaderRoots": sorted(MATERIAL_UNIFORM_ROOTS)},
            "twoCountLoops": "Both execute indices 0..max(0,min(32,count))-1, in the original order; only the redundant initial count break is removed.",
            "groundDefaultWorkload": "All original 72 iterations. Other uniform values are bounded but NOT fidelity-equivalent to default72.",
            "gpuDefaultReadbackEstablished": False}


def verify_material_interface(before, after):
    require(set(before) == set(after) and len(before) == 20, "Changed compiled shader interface membership")
    additions = {}
    for path, rows in after.items():
        expected = 1 if path in MATERIAL_UNIFORM_ROOTS else 0
        extra = [row for row in rows if row.get("name") == MATERIAL_NAME.decode()]
        require(len(extra) == expected and all(row.get("type") == 2 for row in extra), "Only one new int on each ground wrapper is allowed")
        require(not any(row.get("name") == MATERIAL_NAME.decode() for row in before[path]), "New uniform name already existed")
        retained = [row for row in rows if row.get("name") != MATERIAL_NAME.decode()]
        require(retained == before[path], "Existing compiled uniform interface changed")
        if extra:
            additions[path] = extra
    require(before != after, "Must not call the newly extended interface wholly identical")
    return additions


def material_no_override(before):
    # Read-only, bounds-checked codec; never call resource repackers/builders.
    from repack_web_cache import _unpack
    needles = (MATERIAL_NAME, MATERIAL_NAME.decode().encode("utf-16-le"))
    decoded = []
    for path, blob in sorted(before.items()):
        raw = _unpack(blob) if blob.startswith(b"RSCC") else blob
        require(not any(needle in raw for needle in needles), f"Pre-existing parameter/override in {path}")
        if blob.startswith(b"RSCC"):
            decoded.append({"path": path, "decodedBytes": len(raw), "decodedSha256": hashlib.sha256(raw).hexdigest()})
    require(len(decoded) == 6, "Expected all six decoded RSCC resources, including terrain")
    return decoded


def material_inputs(directory):
    from inspect_web_pack import read_pack
    directory = directory.resolve()
    manifest = json.loads((directory / "shader-replacements.v1.json").read_text(encoding="utf-8-sig"))
    source, candidate = Path(manifest["sourcePck"]), directory / "index-lite.pck"
    blobs = []
    for path, pin in ((source, HOIST_SOURCE_SHA), (candidate, MATERIAL_SHA)):
        payload = path.read_bytes()
        require(hashlib.sha256(payload).hexdigest() == pin, "Unreviewed material-loop input pack")
        inventory = read_pack(path, verify=True)
        require(inventory["version"] == 4 and inventory["engine"] == [4, 7, 2], "Unsupported PCK/engine")
        blobs.append({row["path"]: payload[row["offset"]:row["offset"] + row["bytes"]] for row in inventory["entries"]})
    return directory, manifest, blobs


def inspect_material_loops(directory):
    directory, manifest, (before, after) = material_inputs(directory)
    semantics = verify_material_sources(before, after)
    require(manifest["schema"] == "fast-shader-pack-v1" and manifest["profile"] == "bounded-material-loops-only", "Wrong material-loop manifest profile")
    require(manifest["sourcePckSha256"] == HOIST_SOURCE_SHA and manifest["candidatePckSha256"] == MATERIAL_SHA,
            "Material-loop manifest PCK pins disagree")
    require(Path(manifest["candidatePck"]).resolve() == directory / "index-lite.pck" and manifest["candidateBytes"] == 44327244
            and (directory / "index-lite.pck").stat().st_size == 44327244, "Candidate path/length mismatch")
    proof_path = directory / "proof.json"
    require(Path(manifest["proof"]).resolve() == proof_path, "Proof path mismatch")
    rows = manifest["replacements"]
    require(len(rows) == 3 and {row["path"] for row in rows} == MATERIAL_ALLOWED, "Wrong replacement membership")
    for row in rows:
        path = row["path"]
        require(Path(row["file"]).resolve() == directory / "replacement" / path and Path(row["proof"]).resolve() == proof_path,
                "Replacement/proof path mismatch")
        require(Path(row["file"]).read_bytes() == after[path] and (directory / "original" / path).read_bytes() == before[path], "Proof files differ from actual packed shaders")
        for prefix, blob in (("before", before[path]), ("after", after[path])):
            require(row[prefix + "Sha256"] == hashlib.sha256(blob).hexdigest() and row[prefix + "Bytes"] == len(blob), "Replacement hash/length mismatch")
    proof = json.loads(proof_path.read_text(encoding="utf-8-sig"))
    require(proof["sourcePckSha256"] == HOIST_SOURCE_SHA and proof["candidatePckSha256"] == MATERIAL_SHA,
            "Proof pack pin mismatch")
    require(proof["entryCount"] == 184 and proof["unchangedEntries"] == 181 and proof["changedEntries"] == semantics["changedEntries"], "Proof delta/count mismatch")
    require(proof["uniformsAndDefaultsExact"] is False and proof["existingUniformsAndDefaultsExact"] is True,
            "Proof mislabels the new-uniform interface")
    check = proof["shaderLanguageValidation"]
    for label in ("baseline", "candidate"):
        recorded = json.loads((directory / (label + "-shader-compile.json")).read_text(encoding="utf-8-sig"))
        require(recorded == check[label] and recorded["ok"] is True and recorded["shaderCount"] == 20, "Language-proof mismatch")
        for suffix in ("-engine.log", "-console.log"):
            require(not re.search(r"(?:SHADER ERROR|SCRIPT ERROR|\bERROR:)", (directory / (label + suffix)).read_text(encoding="utf-8-sig")), "Language-proof log contains errors")
    additions = verify_material_interface(check["baseline"]["uniforms"], check["candidate"]["uniforms"])
    require(check["uniformInterfacesExactlyEqual"] is False and check["existingUniformInterfacesExactlyEqual"] is True
            and check["addedUniforms"] == additions, "Incorrect interface-delta attestation")
    decoded = material_no_override(before)
    defaults = proof["newUniformDefaultAndNoOverrideProof"]
    require(defaults["default"] == 72 and defaults["bounds"] == [0, 72] and defaults["decodedRsccEntries"] == decoded,
            "Default/decoded material proof disagrees")
    script_rows = defaults["runtimeSourcesWithoutNewName"]
    expected_scripts = set((ROOT / "godot/scripts").glob("*.gd"))
    require(len(script_rows) == len(expected_scripts) and {Path(row["path"]) for row in script_rows} == expected_scripts,
            "Runtime source coverage mismatch")
    for row in script_rows:
        blob = Path(row["path"]).read_bytes()
        require(hashlib.sha256(blob).hexdigest() == row["sha256"] and MATERIAL_NAME not in blob, "Runtime source/default proof changed")
    entries = [{"path": path, "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(), "byteExact": blob == after[path]}
               for path, blob in sorted(before.items()) if path not in MATERIAL_ALLOWED]
    require(len(entries) == 181 and all(row["byteExact"] for row in entries), "Protected entry changed")
    return {"status": "PASS_BOUNDED_MATERIAL_LOOP_SOURCE", "nativeCandidateAudited": False, "performanceAccepted": False,
            "webVisualAccepted": False, "sourcePckSha256": HOIST_SOURCE_SHA, "candidatePckSha256": MATERIAL_SHA,
            "candidateBytes": 44327244, "entryCount": 184, "unchangedEntries": entries, "semantics": semantics,
            "allUniformInterfacesExact": False, "existingUniformInterfacesExact": True, "allowedAddedUniforms": additions,
            "decodedRsccNoOverride": decoded, "runtimeSourcesWithoutNewName": len(script_rows),
            "proofSha256": hashlib.sha256(proof_path.read_bytes()).hexdigest(),
            "manifestSha256": hashlib.sha256((directory / "shader-replacements.v1.json").read_bytes()).hexdigest(),
            "combinedCandidate": "No combined pack accepted by this standalone report. Source-only guard expects exactly six changes /178 unchanged.",
            "limits": ["Default72 is exact source plus absence-of-override proof, not GPU uniform readback.",
                       "No new native run; hoist-only native PASS must not be relabeled as combined-final acceptance.",
                       "Web/ANGLE loop-guard rewrite and screenshots are main-owned evidence, not reproduced by this source check."]}


COMBINED_SHA = "3255a33ff20e6a778d5191c584aa254b35a999c8e5fd9c853a8a0053582e447c"
COMBINED_ALLOWED = HOIST_ALLOWED | MATERIAL_ALLOWED
RUNTIME_PROBE_SHA = "260f76ab28073f052600549bbc8249007a42b6d674602460f773076eec4337b9"
ORIGINAL_RUNTIME_SHA = "b28ce18a8cc2256a36aa65e79b0c28da7dd4a69e51cc1467fa3b813021990294"


def undo_sunbreak(before, after):
    """Reverse the hoist while retaining loop edits; never overwrite whole files."""
    require(set(before) == set(after), "Hoist reversal membership mismatch")
    restored = dict(after)
    for path in HOIST_ALLOWED:
        old, new = before[path], after[path]
        nl = b"\r\n" if b"\r\n" in old else b"\n"
        if path == HOIST_SHARED:
            declaration = b"varying float " + HOIST_VALUE + b";" + nl
            read = b"transmission = " + HOIST_VALUE + b";"
            require(new.count(declaration) == new.count(read) == 1, "Combined shared hoist multiplicity")
            restored[path] = new.replace(declaration, b"").replace(read, b"transmission = " + HOIST_EXPRESSION + b";")
        else:
            line = HOIST_ASSIGNMENT + nl
            require(new.count(line) == 1, "Combined consumer hoist multiplicity")
            restored[path] = new.replace(line, b"")
    return restored


def combined_inputs(directory):
    from inspect_web_pack import read_pack
    directory = directory.resolve()
    manifest = json.loads((directory / "shader-replacements.v1.json").read_text(encoding="utf-8-sig"))
    blobs = []
    for path, pin in ((Path(manifest["sourcePck"]), HOIST_SOURCE_SHA), (directory / "index-lite.pck", COMBINED_SHA)):
        payload = path.read_bytes()
        require(hashlib.sha256(payload).hexdigest() == pin, "Unreviewed combined input pack")
        inventory = read_pack(path, verify=True)
        require(inventory["version"] == 4 and inventory["engine"] == [4, 7, 2], "Unsupported combined PCK/engine")
        require(len(inventory["entries"]) == 184, "Combined inventory must contain 184 entries")
        blobs.append({row["path"]: payload[row["offset"]:row["offset"] + row["bytes"]] for row in inventory["entries"]})
    return directory, manifest, blobs


def verify_combined_composition(directory, composition, before, after, hoisted, looped):
    semantics = verify_material_sources(before, after, combined=True)
    # Both directions recover separately frozen actual pack resources, not just
    # a builder's generated expectation or its self-attested boolean.
    reversed_loops = undo_material_loops(before, after)
    reversed_hoist = undo_sunbreak(before, after)
    require(reversed_loops == hoisted, "Reversing loops does not recover frozen hoist pack")
    require(reversed_hoist == looped, "Reversing hoist does not recover frozen material-loop pack")
    hoist_semantics = verify_sunbreak_sources(before, reversed_loops)
    verify_material_sources(before, reversed_hoist)
    require(undo_sunbreak(before, reversed_loops) == undo_material_loops(before, reversed_hoist) == before,
            "Both reversal orders must recover all original bytes")
    require(composition["orderedTransforms"] == ["original-v117", "sunbreak-hoist", "bounded-material-loops"], "Wrong composition order")
    for key, expected in (("stageOneChangedEntries", 5), ("stageTwoChangedEntries", 3), ("finalUniqueChangedEntries", 6),
                          ("overlappingEntries", sorted(HOIST_ALLOWED & MATERIAL_ALLOWED))):
        require(composition[key] == expected, "Composition counts/overlap disagree")
    require(composition["secondStageConsumesHoistedSource"] is True and composition["reverseStageProofPassed"] is True,
            "Composition does not attest the reviewed transformations")
    rows = composition["entries"]
    require(len(rows) == 6 and {row["path"] for row in rows} == COMBINED_ALLOWED, "Composition entry membership mismatch")
    for row in rows:
        path = row["path"]
        stage_file = directory / "stage-01-hoist" / path
        require(Path(row["hoistedSourceFile"]).resolve() == stage_file and stage_file.read_bytes() == hoisted[path],
                "Saved intermediate differs from frozen hoist pack")
        for key, blob in (("originalSha256", before[path]), ("afterHoistSha256", hoisted[path]),
                          ("afterMaterialLoopsSha256", after[path])):
            require(row[key] == hashlib.sha256(blob).hexdigest(), "Composition stage hash mismatch")
        require(row["stageOneChanged"] is (before[path] != hoisted[path])
                and row["stageTwoChanged"] is (hoisted[path] != after[path]), "Composition stage-change flags disagree")
    return {"materialSemantics": semantics, "hoistSemantics": hoist_semantics,
            "reverseLoopsRecoversFrozenHoistPackResources": True,
            "reverseHoistRecoversFrozenMaterialLoopPackResources": True,
            "bothReversalOrdersRecoverAll184OriginalResources": True,
            "savedIntermediateMatchesActualFrozenHoistPack": True,
            "frozenHoistPckSha256": HOIST_CANDIDATE_SHA, "frozenMaterialLoopPckSha256": MATERIAL_SHA,
            "stageEntries": rows}


def inspect_combined_native(path):
    """Read a completed run; never spawn Godot or substitute a prior candidate."""
    directory = ROOT / "artifacts/loading-v115/runtime"
    candidate = json.loads(path.read_text(encoding="utf-8-sig"))
    original_path = directory / "original.json"
    original = json.loads(original_path.read_text(encoding="utf-8-sig"))
    previous = json.loads((directory / "final-trial-v117.json").read_text(encoding="utf-8-sig"))
    require(hashlib.sha256(original_path.read_bytes()).hexdigest() == ORIGINAL_RUNTIME_SHA, "Frozen original native report changed")
    require(candidate["status"] == "PASS" and candidate["errors"] == [], "Native probe failed")
    require(candidate["packSha256"] == COMBINED_SHA and previous["packSha256"] == HOIST_SOURCE_SHA, "Wrong native candidate/reference pack")
    probe = ROOT / "godot/tools/audit_lite_runtime.gd"
    require(candidate["probeSha256"] == hashlib.sha256(probe.read_bytes()).hexdigest() == RUNTIME_PROBE_SHA, "Native probe was changed")
    require(candidate["comparison"]["baselineSha256"] == ORIGINAL_RUNTIME_SHA, "Wrong native comparison baseline")
    require(candidate["packBinding"] == {"allLoadedEntryMd5Match": True, "entryCount": 184, "matchedLoadedEntries": 184}
            and candidate["inputPackUnchanged"] is True, "Native mounted pack not fully bound/unchanged")
    checks = candidate["comparison"]["checks"]
    require(len(checks) == 11 and all(value is True for value in checks.values()), "Native baseline comparisons failed/incomplete")
    # Recompute every reported comparison; PASS flags alone are insufficient.
    for key in ("camera", "water", "walkingBoss", "weather", "routes"):
        require(original[key] == candidate[key], f"Native baseline differs: {key}")
    for key in ("structureSha256", "nodeCount", "lightCounts", "colliderSetSha256", "colliderCount"):
        require(original["inventory"][key] == candidate["inventory"][key], f"Native inventory differs: {key}")
    clean = lambda rows: [{key: value for key, value in row.items() if key != "path"} for row in rows]
    require(clean(original["inventory"]["nodes"]) == clean(candidate["inventory"]["nodes"]), "Native objects/transforms/scripts/counts differ")
    require(candidate["renderSettings"] == previous["renderSettings"], "Authorized lite render settings regressed")
    log = path.with_suffix(".engine.log")
    require(not re.search(r"(?:SHADER ERROR|SCRIPT ERROR|\bERROR:|\bWARNING:)", log.read_text(encoding="utf-8-sig")), "Native log contains error/warning")
    return {"status": "PASS", "path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "engineLogSha256": hashlib.sha256(log.read_bytes()).hexdigest(), "packSha256": candidate["packSha256"],
            "probeSha256": RUNTIME_PROBE_SHA, "baselineSha256": ORIGINAL_RUNTIME_SHA,
            "checks": checks, "all11IndependentlyRecomputed": True, "packBinding": candidate["packBinding"],
            "inputPackUnchanged": True, "renderSettings": candidate["renderSettings"],
            "inventory": {key: candidate["inventory"][key] for key in ("nodeCount", "lightCounts", "colliderCount", "colliderSetSha256")},
            "gpuRendered": False, "startupPerformanceMeasured": False}


def inspect_combined(directory, native=None):
    directory, manifest, (before, after) = combined_inputs(directory)
    _, _, (hoist_before, hoisted), _, _ = sunbreak_inputs(directory.parent / "sunbreak-hoist-01")
    _, _, (loop_before, looped) = material_inputs(directory.parent / "bounded-material-loops-01")
    require(before == hoist_before == loop_before, "Standalone source pack resources differ")
    require(manifest["schema"] == "fast-shader-pack-v1" and manifest["profile"] == "combined-only", "Wrong combined manifest profile")
    require(manifest["sourcePckSha256"] == HOIST_SOURCE_SHA and manifest["candidatePckSha256"] == COMBINED_SHA, "Combined manifest pin mismatch")
    require(Path(manifest["candidatePck"]).resolve() == directory / "index-lite.pck"
            and manifest["candidateBytes"] == (directory / "index-lite.pck").stat().st_size == 44327612, "Combined path/length mismatch")
    for key, name in (("proof", "proof.json"), ("diff", "shader.diff"), ("compositionProof", "composition.json")):
        require(Path(manifest[key]).resolve() == directory / name, "Unbound combined proof/diff/composition path")
    rows = manifest["replacements"]
    require(len(rows) == 6 and {row["path"] for row in rows} == COMBINED_ALLOWED, "Combined manifest replacement membership")
    for row in rows:
        path = row["path"]
        require(Path(row["file"]).resolve() == directory / "replacement" / path
                and Path(row["proof"]).resolve() == directory / "proof.json", "Unbound combined replacement")
        require(Path(row["file"]).read_bytes() == after[path] and (directory / "original" / path).read_bytes() == before[path], "Combined evidence differs from PCK bytes")
        for prefix, blob in (("before", before[path]), ("after", after[path])):
            require(row[prefix + "Sha256"] == hashlib.sha256(blob).hexdigest() and row[prefix + "Bytes"] == len(blob), "Combined replacement hash/length mismatch")
    proof = json.loads((directory / "proof.json").read_text(encoding="utf-8-sig"))
    composition = json.loads((directory / "composition.json").read_text(encoding="utf-8-sig"))
    require(proof["composition"] == composition, "Embedded/saved composition disagree")
    stages = verify_combined_composition(directory, composition, before, after, hoisted, looped)
    require(proof["profile"] == "combined-only" and proof["sourcePckSha256"] == HOIST_SOURCE_SHA
            and proof["candidatePckSha256"] == COMBINED_SHA, "Combined proof pin/profile mismatch")
    require(proof["entryCount"] == 184 and proof["unchangedEntries"] == 178
            and proof["changedEntries"] == sorted(COMBINED_ALLOWED), "Combined proof counts/delta mismatch")
    require(proof["uniformsAndDefaultsExact"] is False and proof["existingUniformsAndDefaultsExact"] is True, "Misleading combined uniform attestation")
    check = proof["shaderLanguageValidation"]
    for label in ("baseline", "candidate"):
        recorded = json.loads((directory / (label + "-shader-compile.json")).read_text(encoding="utf-8-sig"))
        require(recorded == check[label] and recorded["ok"] is True and recorded["shaderCount"] == 20, "Combined language proof mismatch")
        expected_pack = Path(manifest["sourcePck"] if label == "baseline" else manifest["candidatePck"])
        require(Path(recorded["pack"]).resolve() == expected_pack.resolve(), "Language proof used another pack")
        for suffix in ("-engine.log", "-console.log"):
            require(not re.search(r"(?:SHADER ERROR|SCRIPT ERROR|\bERROR:|\bWARNING:)", (directory / (label + suffix)).read_text(encoding="utf-8-sig")), "Combined language log error/warning")
    additions = verify_material_interface(check["baseline"]["uniforms"], check["candidate"]["uniforms"])
    require(check["uniformInterfacesExactlyEqual"] is False and check["existingUniformInterfacesExactlyEqual"] is True
            and check["addedUniforms"] == additions, "Combined compiled-interface delta mismatch")
    # Re-run the independent no-override scan against the same source PCK and
    # current pinned runtime sources, then bind the combined proof to that scan.
    material_report = inspect_material_loops(directory.parent / "bounded-material-loops-01")
    defaults = proof["newUniformDefaultAndNoOverrideProof"]
    require(defaults["newUniform"] == MATERIAL_NAME.decode() and defaults["default"] == 72 and defaults["bounds"] == [0, 72]
            and defaults["decodedRsccEntries"] == material_report["decodedRsccNoOverride"], "Combined default/no-override proof mismatch")
    standalone_proof = json.loads((directory.parent / "bounded-material-loops-01/proof.json").read_text(encoding="utf-8-sig"))
    require(defaults["runtimeSourcesWithoutNewName"] == standalone_proof["newUniformDefaultAndNoOverrideProof"]["runtimeSourcesWithoutNewName"], "Combined runtime no-override coverage differs")
    entries = [{"path": path, "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(), "byteExact": blob == after[path]}
               for path, blob in sorted(before.items()) if path not in COMBINED_ALLOWED]
    require(len(entries) == 178 and all(row["byteExact"] for row in entries), "Combined protected entry changed")
    return {"status": "PASS_COMBINED_SOURCE_AND_NATIVE" if native else "PASS_COMBINED_SOURCE",
            "nativeCandidateAudited": native is not None, "performanceAccepted": False, "webVisualAccepted": False,
            "sourcePckSha256": HOIST_SOURCE_SHA, "candidatePckSha256": COMBINED_SHA, "candidateBytes": 44327612,
            "entryCount": 184, "unchangedEntryCount": 178, "changedEntries": rows, "unchangedEntries": entries,
            "composition": stages, "allUniformInterfacesExact": False, "existingUniformInterfacesExact": True,
            "allowedAddedUniforms": additions, "decodedRsccNoOverride": material_report["decodedRsccNoOverride"],
            "runtimeSourcesWithoutNewName": material_report["runtimeSourcesWithoutNewName"],
            "proofFilesSha256": {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in (
                "shader-replacements.v1.json", "proof.json", "composition.json", "shader.diff", "v117-to-hoist.diff", "hoist-to-combined.diff")},
            "native": inspect_combined_native(native) if native else None,
            "limits": ["Exact combined PCK only; no blanket shader-change permission or blind manifest overlay.",
                       "New int default72 is source/no-override proof, not GPU readback. Other values are not fidelity-equivalent.",
                       "Headless scene/animation checks do not execute GPU rendering or establish Web/ANGLE link-time/first-frame improvement.",
                       "Main-owned GL helper, matched day/night pixels, backing canvas/DPR/visibility and cache cohort remain separate acceptance evidence."]}


V117_NATIVE_SHA = "f2a75272dccbbe9b4c78db336d64fdb886bd27209d0d6af7a1fb2c8b13d13939"
ZERO_TYPE_REVIEW_SHA = "d4aef8ada6cd54be0c8bc95861757e2e67e554a95fbce744c2a48dbb1d97c0e3"


def zero_type_snapshot(record, expected_pin):
    require(expected_pin in (HOIST_SOURCE_SHA, COMBINED_SHA) and record["packSha256"] == expected_pin,
            "Unreviewed zero-type pack or wrong native report")
    require(record["status"] == "PASS" and record["errors"] == [] and record["inputPackUnchanged"] is True,
            "Native report did not pass unchanged")
    require(record["probeSha256"] == RUNTIME_PROBE_SHA and record["packBinding"] == {
        "allLoadedEntryMd5Match": True, "entryCount": 184, "matchedLoadedEntries": 184}, "Wrong probe or incomplete mounted-pack binding")
    inventory = record["inventory"]
    require(inventory["nodeCount"] == len(inventory["nodes"]) == 144, "Incomplete scene inventory")
    # Include hidden/zero-energy lights; night-only nodes already exist at ready.
    nodes = [node for node in inventory["nodes"] if "Light" in node["class"]]
    counts = dict(Counter(node["class"] for node in nodes))
    require(counts == inventory["lightCounts"] == {"DirectionalLight3D": 4, "OmniLight3D": 9},
            "Expected four directional/nine omni and no other light classes")
    return {"directional": 4, "omni": 9, "spot": 0, "area": 0}


def inspect_v117_zero_types(pack):
    """Extend only independent eligibility; never edit helper/build allowlists."""
    from inspect_web_pack import read_pack
    pack = pack.resolve()
    payload = pack.read_bytes()
    require(hashlib.sha256(payload).hexdigest() == HOIST_SOURCE_SHA and len(payload) == 44327228,
            "Requires byte-identical approved v117 lite PCK, not combined/future content")
    inventory = read_pack(pack, verify=True)
    actual = {row["path"]: payload[row["offset"]:row["offset"] + row["bytes"]] for row in inventory["entries"]}
    directory = ROOT / "artifacts/startup-v118/godot-analysis/combined-01"
    _, _, (approved, combined) = combined_inputs(directory)
    require(actual == approved and len(actual) == 184, "All 184 entries must equal approved v117 lite")
    semantics = verify_material_sources(approved, combined, combined=True)
    require(semantics["unchangedEntryCount"] == 178, "Do not mislabel combined as 184 unchanged")
    scripts = sorted(path for path in actual if path.endswith(".gdc"))
    scenes = sorted(path for path in actual if path.endswith(".scn"))
    require(len(scripts) == 37 and len(scenes) == 7 and all(actual[path] == combined[path] for path in scripts + scenes),
            "Runtime script/scene identity to reviewed zero-type combined scene changed")
    prior_path = ROOT / "artifacts/startup-v118/independent/zero-unused-light-contract-review.json"
    require(hashlib.sha256(prior_path.read_bytes()).hexdigest() == ZERO_TYPE_REVIEW_SHA, "Pinned source/lifetime zero-type proof changed")
    prior = json.loads(prior_path.read_text(encoding="utf-8-sig"))
    require(prior["packSha256"] == COMBINED_SHA and prior["sceneContractAccepted"] is True
            and prior["spotAreaOrDynamicFactoryMatches"] == [], "Prior scene proof is not the accepted combined contract")
    source_pins = {path: digest for path, digest in prior["sourcePins"].items() if Path(path).suffix == ".gd"}
    expected_sources = set((ROOT / "godot/scripts").glob("*.gd")) | {ROOT / "godot" / Path(path).with_suffix(".gd") for path in scripts}
    require(len(source_pins) == len(expected_sources) == 40 and {Path(path) for path in source_pins} == expected_sources,
            "Zero-type source inspection coverage changed")
    for path, digest in source_pins.items():
        require(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, "A reviewed light-construction/lifetime source changed")
    require({row["path"] for row in prior["packedScenesWithNoSpotAreaTypeName"]} == set(scenes), "Zero-type packed scene coverage changed")
    for row in prior["packedScenesWithNoSpotAreaTypeName"]:
        require(hashlib.sha256(actual[row["path"]]).hexdigest() == row["sha256"], "Previously inspected packed scene changed")
    runtime = ROOT / "artifacts/loading-v115/runtime"
    native_path = runtime / "final-trial-v117.json"
    require(hashlib.sha256(native_path.read_bytes()).hexdigest() == V117_NATIVE_SHA, "Original v117 native report changed")
    native = json.loads(native_path.read_text(encoding="utf-8-sig"))
    counts = zero_type_snapshot(native, HOIST_SOURCE_SHA)
    original_path = runtime / "original.json"
    require(hashlib.sha256(original_path.read_bytes()).hexdigest() == ORIGINAL_RUNTIME_SHA, "Frozen original runtime report changed")
    original = json.loads(original_path.read_text(encoding="utf-8-sig"))
    checks = native["comparison"]["checks"]
    require(native["comparison"]["baselineSha256"] == ORIGINAL_RUNTIME_SHA and len(checks) == 11
            and all(value is True for value in checks.values()), "Incomplete v117 native baseline comparison")
    for key in ("camera", "water", "walkingBoss", "weather", "routes"):
        require(native[key] == original[key], f"v117 original native invariant differs: {key}")
    for key in ("structureSha256", "nodeCount", "lightCounts", "colliderSetSha256", "colliderCount"):
        require(native["inventory"][key] == original["inventory"][key], f"v117 native inventory differs: {key}")
    clean = lambda rows: [{key: value for key, value in row.items() if key != "path"} for row in rows]
    require(clean(native["inventory"]["nodes"]) == clean(original["inventory"]["nodes"]), "v117 objects/transforms/scripts/counts differ")
    combined_native = json.loads((runtime / "combined-01-v122-independent.json").read_text(encoding="utf-8-sig"))
    zero_type_snapshot(combined_native, COMBINED_SHA)
    require(native["weather"] == combined_native["weather"] and native["renderSettings"] == combined_native["renderSettings"],
            "Combined/v117 lighting lifetime or lite settings differ")
    return {"status": "PASS_V117_ZERO_UNUSED_LIGHT_CONTRACT", "pack": str(pack), "packSha256": HOIST_SOURCE_SHA,
            "packBytes": len(payload), "entryCount": 184, "all184EntriesExactAgainstApprovedV117": True,
            "unchangedEntriesAgainstCombined": 178, "shaderDifferencesFromCombined": semantics["changedEntries"],
            "all37CompiledScriptsAnd7ScenesExactAgainstCombined": True,
            "normalSceneLightCounts": counts, "additionalEligibleContract": {"packSha256": HOIST_SOURCE_SHA, "spotLights": 0, "areaLights": 0},
            "nativeReport": str(native_path), "nativeReportSha256": V117_NATIVE_SHA,
            "nativeAll11ComparisonsIndependentlyRecomputed": checks, "nativeWasReusedNotRerun": True,
            "renderSettings": native["renderSettings"], "sourceProofSha256": ZERO_TYPE_REVIEW_SHA,
            "all40InspectedLightSourcePinsStillExact": source_pins, "dayNightNoNewTypesProof": prior["dayNightNoNewTypesProof"],
            "newNativeRuns": 0, "shippingSourceChanges": False, "performanceAccepted": False, "webVisualAccepted": False,
            "limits": ["Counts cover hidden lights in the full reset-day native inventory; lifetime proof is unchanged source plus sampled day/night, not separate full inventories per phase.",
                       "No shader PCK edits are required. This extends independent eligibility only; main/C own the two explicit hash allowlists and selected-pack binding.",
                       "Preserve directional/omni and shadow paths, including the lantern's night shadow toggle.",
                       "Return the actual accepted supplied hash in helper contract/telemetry; do not relabel v117 as the combined hash.",
                       "Unknown future PCKs receive no scene-specialization contract; matched Web timing/QHD acceptance remains separate."]}


NODE_HARNESS = r"""
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const loader = fs.readFileSync(path.join(input.root, 'godot/web/meadow-loader.js'), 'utf8');
const controls = fs.readFileSync(path.join(input.root, 'godot/web/meadow-controls.js'), 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((a, b) => { resolve = a; reject = b; });
  return { promise, resolve, reject };
}
function harness() {
  let clock = 0;
  const init = deferred(), pack = deferred(), start = deferred();
  const elements = new Map(), raf = [], events = [], errors = [];
  const listeners = new Map();
  let engine;
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      id, dataset: {}, attributes: {}, handlers: {}, disabled: true, hidden: false,
      width: 2560, height: 1440, tagName: id === 'canvas' ? 'CANVAS' : 'BUTTON',
      setAttribute(k, v) { this.attributes[k] = v; },
      removeAttribute(k) { delete this.attributes[k]; },
      addEventListener(k, fn) { this.handlers[k] = fn; }
    });
    return elements.get(id);
  }
  const document = {
    body: { dataset: {} }, visibilityState: 'visible', hasFocus: () => true,
    getElementById: element,
    addEventListener(k, fn) { if (!listeners.has(k)) listeners.set(k, new Set()); listeners.get(k).add(fn); },
    removeEventListener(k, fn) { listeners.get(k)?.delete(fn); }
  };
  const window = {
    performance: { now: () => clock, getEntriesByType: () => [] }, devicePixelRatio: 1,
    matchMedia: () => ({ matches: false, addEventListener() {} }),
    location: { reload: () => events.push('reload') },
    requestAnimationFrame(fn) { raf.push(fn); return raf.length; }
  };
  class Engine {
    constructor(options) { engine = this; this.options = options; }
    static getMissingFeatures() { return []; }
    init() { events.push('init'); return init.promise; }
    preloadFile(url) { events.push(['pack', url]); return pack.promise; }
    start() { events.push('start'); return start.promise; }
  }
  vm.runInNewContext(loader + '\n' + controls, {
    window, document, Engine, URL, console: { info() {}, error(e) { errors.push(String(e)); } }
  }, { timeout: 1000 });
  const snapshot = () => ({
    readAtMs: clock, data: { ...element('canvas').dataset }, hidden: element('loading').hidden,
    busy: element('loading').attributes['aria-busy'], rafPending: raf.length,
    errors: [...errors], retryVisible: !element('retry').hidden,
    dimensions: [element('canvas').width, element('canvas').height],
    visibilityListeners: listeners.get('visibilitychange')?.size || 0
  });
  return { ui: window.meadowTimeUI, init, pack, start, events, element, snapshot,
    clock(t) { clock = t; },
    async boot() {
      window.meadowTimeUI.start({ executable: 'index', mainPack: 'index-lite.pck' });
      clock = 10; init.resolve(); await settle();
      clock = 100; pack.resolve(); await settle();
    },
    raf() { const fn = raf.shift(); if (!fn) throw Error('No pending RAF'); fn(clock); },
    visibility(state) { document.visibilityState = state; for (const fn of listeners.get('visibilitychange') || []) fn(); },
    exit() { engine.options.onExit(1); },
    progress() { engine.options.onProgress(100, 100); }
  };
}
(async () => {
  const results = {};
  let h = harness(); await h.boot();
  h.clock(150); h.progress(); h.ui.sceneReady(5);
  results.sceneBeforeEngine = h.snapshot();
  h.clock(250); h.start.resolve(); await settle();
  results.promiseBeforeFrames = h.snapshot();
  h.clock(260); h.raf(); results.oneRaf = h.snapshot();
  h.clock(270); h.raf(); results.twoRaf = h.snapshot();
  h.clock(251000); results.lateRead = h.snapshot();
  results.parallelEvents = h.events;

  h = harness(); await h.boot();
  h.clock(200); h.start.resolve(); await settle(); results.engineBeforeScene = h.snapshot();
  h.clock(210); h.ui.sceneReady(9); results.secondGateArrives = h.snapshot();
  h.clock(220); h.raf(); h.clock(230); h.raf(); results.reverseOrderReady = h.snapshot();

  h = harness(); await h.boot();
  h.clock(200); h.start.resolve(); // settled, but no microtask checkpoint yet
  h.clock(9000); await settle(); results.delayedContinuation = h.snapshot();

  h = harness(); await h.boot(); h.ui.sceneReady(1);
  h.start.reject(Error('fixture startup failure')); await settle(); results.failedStart = h.snapshot();

  h = harness(); await h.boot(); h.ui.sceneReady(1); h.start.resolve(); await settle();
  h.raf(); h.exit(); h.raf(); results.exitBeforeSecondRaf = h.snapshot();

  h = harness(); await h.boot();
  h.clock(120); h.visibility('hidden'); h.clock(420); h.visibility('visible');
  h.clock(450); h.ui.sceneReady(1); h.start.resolve(); await settle();
  h.clock(460); h.raf(); h.clock(470); h.raf(); results.observedHidden = h.snapshot();

  // Exercise ONLY the small shipped public start() method, never WASM/Godot.
  const engineSource = fs.readFileSync(path.join(input.root, 'artifacts/v117/index.js'), 'utf8');
  const begin = engineSource.indexOf('start: function (override) {');
  const end = engineSource.indexOf('\n\t\t\t/**', begin);
  if (begin < 0 || end < begin) throw Error('Cannot locate frozen Engine.start');
  const trace = [];
  const method = vm.runInNewContext('({' + engineSource.slice(begin, end) + '}).start', {
    preloader: { preloadedFiles: [{ path: 'index-lite.pck', buffer: new Uint8Array(1) }] },
    initPromise: null
  }, { timeout: 1000 });
  const subject = {
    init: () => Promise.resolve(),
    config: { update() {}, getGodotConfig: () => ({}), gdextensionLibs: [], args: ['--main-pack', 'index-lite.pck'] },
    rtenv: { initConfig() {}, copyToFS() { trace.push('copyToFS'); }, callMain() { trace.push('callMain-return'); } },
    installServiceWorker() { trace.push('service-worker-call'); return new Promise(() => {}); }
  };
  const finished = method.call(subject).then(() => trace.push('start-resolved'));
  await settle();
  results.engineMethodTrace = trace;
  process.stdout.write(JSON.stringify(results));
})().catch(e => { process.stderr.write(String(e.stack)); process.exitCode = 1; });
"""


class ReadyOrderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node = shutil.which("node") or "E:/Nodejs/node.exe"
        if not Path(node).is_file():
            raise RuntimeError("Node is required; this suite must not silently skip its ordering tests")
        result = subprocess.run([node, "-e", NODE_HARNESS], input=json.dumps({"root": str(ROOT)}),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.results = json.loads(result.stdout)

    def test_download_and_scene_signal_do_not_hide_before_engine_start(self):
        row = self.results["sceneBeforeEngine"]
        self.assertFalse(row["hidden"])
        self.assertEqual(row["rafPending"], 0)
        self.assertEqual(row["data"]["downloadMs"], "150")
        self.assertNotIn("engineStartedMs", row["data"])

    def test_engine_start_alone_does_not_hide_before_scene_signal(self):
        row = self.results["engineBeforeScene"]
        self.assertFalse(row["hidden"])
        self.assertEqual(row["rafPending"], 0)
        self.assertTrue(self.results["reverseOrderReady"]["hidden"])

    def test_two_separate_raf_callbacks_are_required_not_an_immediate_stub(self):
        for key in ("promiseBeforeFrames", "oneRaf"):
            self.assertFalse(self.results[key]["hidden"], key)
            self.assertNotIn("loadMs", self.results[key]["data"], key)
            self.assertEqual(self.results[key]["rafPending"], 1)
        self.assertTrue(self.results["twoRaf"]["hidden"])
        self.assertEqual(self.results["twoRaf"]["data"]["loadMs"], "270")

    def test_late_observer_read_does_not_retimestamp_page_milestones(self):
        a, b = self.results["twoRaf"], self.results["lateRead"]
        self.assertNotEqual(a["readAtMs"], b["readAtMs"])
        self.assertEqual(a["data"], b["data"])
        self.assertEqual(b["data"]["engineStartedMs"], "250")

    def test_settlement_and_continuation_are_distinct_even_without_hidden_tab(self):
        # Resolver called at 200, but its awaiting JS resumes at 9000.
        self.assertEqual(self.results["delayedContinuation"]["data"]["engineStartedMs"], "9000")

    def test_start_failure_does_not_emit_presentation_success(self):
        row = self.results["failedStart"]
        self.assertFalse(row["hidden"])
        self.assertNotIn("loadMs", row["data"])
        self.assertTrue(row["errors"])
        self.assertTrue(row["retryVisible"])

    def test_exit_between_raf_callbacks_keeps_failure_visible(self):
        row = self.results["exitBeforeSecondRaf"]
        self.assertFalse(row["hidden"])
        self.assertNotIn("loadMs", row["data"])
        self.assertTrue(row["errors"])

    def test_visibility_duration_and_listener_cleanup(self):
        row = self.results["observedHidden"]
        self.assertEqual(row["data"]["loadHiddenMs"], "300")
        self.assertEqual(row["visibilityListeners"], 0)

    def test_observation_and_ready_gate_do_not_resize_backing_canvas(self):
        for key, row in self.results.items():
            if isinstance(row, dict) and "dimensions" in row:
                self.assertEqual(row["dimensions"], [2560, 1440], key)

    def test_shipped_engine_start_resolves_after_callmain_not_engine_exit_or_sw(self):
        self.assertEqual(self.results["engineMethodTrace"],
                         ["copyToFS", "callMain-return", "service-worker-call", "start-resolved"])


class SavedTelemetryTests(unittest.TestCase):
    def test_missing_nan_and_negative_are_unknown_not_zero(self):
        for value in (None, "", True, -1, "-1", "nan", "inf", "broken"):
            self.assertIsNone(number(value), repr(value))
        self.assertEqual(number("0"), 0)

    def test_only_same_source_clock_intervals_are_derived(self):
        report = inspect_saved({"runtimeStartMs": "1586", "engineStartedMs": "251107",
                                "sceneSignalMs": "20705", "loadMs": "261896",
                                "startupAuditFinishedAtMs": "22576.8"})
        self.assertEqual(report["withinClockIntervals"],
                         {"loaderStartToContinuationMs": 249521, "controlsSceneToOverlayMs": 241191})

    def test_reversed_or_missing_milestones_are_not_a_negative_speedup(self):
        self.assertIsNone(inspect_saved({"runtimeStartMs": 100, "engineStartedMs": 50})[
            "withinClockIntervals"]["loaderStartToContinuationMs"])

    def test_real_v117_pair_is_rejected_without_speedup_arithmetic(self):
        a, b = [json.loads((ROOT / "artifacts/v117" / name).read_text(encoding="utf-8")) for name in
                ("startup-default-web.json", "startup-audit-enabled-web.json")]
        report = inspect_pair(a, b)
        self.assertEqual(report["status"], "INVALID_CAUSAL_AB")
        self.assertIsNone(report["speedup"])
        self.assertIn("Different startup backing canvas dimensions", report["reasons"])
        self.assertIn("Different startup DPR", report["reasons"])
        self.assertTrue(report["runs"][1]["backingChangedAfterStartup"])

    def test_zero_hidden_and_equal_final_dimensions_do_not_certify_controls(self):
        record = {"width": 2560, "height": 1440, "startupAuditCanvasWidth": 2560,
                  "startupAuditCanvasHeight": 1440, "startupAuditDpr": 1, "loadHiddenMs": 0}
        self.assertEqual(inspect_pair(record, record)["status"], "INVALID_CAUSAL_AB")

    def test_legacy_cli_returns_nonzero_for_uncontrolled_pair(self):
        result = subprocess.run([sys.executable, "-B", str(Path(__file__)), "--saved",
                                 str(ROOT / "artifacts/v117/startup-default-web.json"),
                                 str(ROOT / "artifacts/v117/startup-audit-enabled-web.json")],
                                capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "INVALID_CAUSAL_AB")


class TraceEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = ROOT / "artifacts/v118/startup-trace-01.json"
        cls.record = json.loads(cls.path.read_text(encoding="utf-8-sig"))
        cls.trace = json.loads(cls.record["startupTrace"])

    def changed_trace(self):
        return {**self.record, "startupTrace": copy.deepcopy(self.trace)}

    def test_full_saved_trace_is_pinned_valid_diagnostic_not_performance_pass(self):
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),
                         "dd166d9fe8c762ca559bb8504f7f2281dd3b9fb4970f5008e0d6e2145bde58dc")
        report = inspect_trace(self.record, "per-call-rounded")
        self.assertEqual(report["status"], "VALID_DIAGNOSTIC_TRACE", report)
        self.assertFalse(report["performanceAccepted"])
        self.assertEqual(report["slowList"]["entries"], 179)
        self.assertFalse(report["slowList"]["capReached"])
        self.assertEqual(report["context"]["finalBackingCanvas"], [1280, 800])
        self.assertFalse(report["context"]["fullVisibilityFocusResizeHistoryEstablished"])

    def test_link_status_attribution_is_limited_to_parameter_bearing_slow_rows(self):
        report = inspect_trace(self.record)
        self.assertEqual(report["getProgramParameter"]["calls"], 284)
        self.assertEqual(report["getProgramParameter"]["unclassifiedUnrecordedCalls"], 157)
        links = report["linkStatusSlowCalls"]
        self.assertEqual(links["calls"], 127)
        self.assertEqual(links["slowQueryParameters"], {"35714": 127})
        self.assertEqual(links["sumMs"], 278515.7)
        self.assertEqual(links["unionMs"], 278515.7)
        self.assertEqual(links["topCalls"][0]["ms"], 15718.5)

    def test_old_rounding_bound_cannot_explain_multi_second_waits(self):
        report = inspect_trace(self.record, "per-call-rounded")
        self.assertEqual(report["getProgramParameter"]["aggregateRoundingBoundMs"], 14.2)
        self.assertEqual(report["linkStatusSlowCalls"]["sumRoundingBoundMs"], 6.35)
        self.assertEqual(inspect_trace(self.record, "final-round-only")[
            "getProgramParameter"]["aggregateRoundingBoundMs"], 0.05)

    def test_same_trace_clock_exposes_blocking_after_both_scene_and_engine_markers(self):
        phases = inspect_trace(self.record)["phases"]
        self.assertEqual(phases["sceneToContinuation"], {
            "spanMs": 264370.0, "observedLinkStatusCoverageMs": 259223.4, "callsStartingInPhase": 112})
        self.assertEqual(phases["continuationToOverlayOpportunity"], {
            "spanMs": 11126.1, "observedLinkStatusCoverageMs": 9946.4, "callsStartingInPhase": 9})
        self.assertEqual(phases["runtimeStartToScene"]["observedLinkStatusCoverageMs"], 9345.9)

    def test_missing_query_parameters_are_not_inferred_from_name_or_timing(self):
        record = self.changed_trace()
        for row in record["startupTrace"]["slow"]:
            row.pop("parameter", None)
        report = inspect_trace(record)
        self.assertEqual(report["status"], "VALID_DIAGNOSTIC_TRACE")
        self.assertEqual(report["linkStatusSlowCalls"]["calls"], 0)
        self.assertEqual(report["linkStatusSlowCalls"]["slowQueryParameters"], {"unknown": 127})

    def test_missing_long_task_entries_do_not_erase_direct_gl_timing(self):
        record = self.changed_trace()
        record["startupTrace"]["longTasks"] = []
        report = inspect_trace(record)
        self.assertEqual(report["status"], "VALID_DIAGNOSTIC_TRACE")
        self.assertEqual(report["linkStatusSlowCalls"]["sumMs"], 278515.7)

    def test_union_clips_cross_boundary_scopes_without_additive_double_count(self):
        self.assertEqual(interval_coverage([(1, 5), (3, 8), (11, 14)], 2, 12), 7)
        self.assertEqual(interval_coverage([(1, 5)], 20, 30), 0)

    def test_real_overlaps_fail_instead_of_appearing_as_more_than_wall_time(self):
        record = self.changed_trace()
        record["startupTrace"]["slow"][1]["startMs"] = 2850
        report = inspect_trace(record)
        self.assertEqual(report["status"], "INVALID_TRACE")
        self.assertTrue(any("Overlapping" in error for error in report["errors"]))

    def test_duplicate_missing_invalid_or_out_of_window_boundaries_fail_closed(self):
        for mutation in ("duplicate", "missing", "nan", "outside", "running", "bad_name"):
            with self.subTest(mutation=mutation):
                record = self.changed_trace()
                trace = record["startupTrace"]
                if mutation == "duplicate":
                    trace["marks"].append(trace["marks"][-1].copy())
                elif mutation == "missing":
                    trace["marks"] = [r for r in trace["marks"] if r["name"] != "sceneReady"]
                elif mutation == "nan":
                    trace["totals"]["getProgramParameter"]["ms"] = "nan"
                elif mutation == "outside":
                    trace["slow"][-1]["startMs"] = trace["elapsedMs"]
                elif mutation == "running":
                    trace["status"] = "running"
                else:
                    trace["slow"][0]["name"] = []
                self.assertEqual(inspect_trace(record)["status"], "INVALID_TRACE")

    def test_uncapped_slow_list_cannot_omit_the_recorded_maximum(self):
        record = self.changed_trace()
        record["startupTrace"]["slow"] = [row for row in record["startupTrace"]["slow"]
                                          if row.get("program") != 49]
        self.assertEqual(inspect_trace(record)["status"], "INVALID_TRACE")

    def test_reached_slow_cap_does_not_falsely_claim_complete_call_details(self):
        trace = {"status": "completed", "elapsedMs": 10000,
                 "marks": [{"name": name, "ms": ms} for name, ms in (
                     ("runtimeStartMs", 0), ("sceneReady", 500),
                     ("engineStartedMs", 7000), ("presentation", 9500))],
                 "totals": {"getProgramParameter": {"calls": 201, "ms": 5200, "maxMs": 1000}},
                 "slow": [{"name": "getProgramParameter", "startMs": i * 25, "ms": 21,
                           "parameter": 35714, "program": i + 1} for i in range(200)]}
        report = inspect_trace({"startupTrace": trace})
        self.assertEqual(report["status"], "VALID_DIAGNOSTIC_TRACE", report)
        self.assertTrue(report["slowList"]["capReached"])
        self.assertEqual(report["linkStatusSlowCalls"]["sumMs"], 4200)

    def test_reversed_ready_gate_order_does_not_create_negative_phase_duration(self):
        record = self.changed_trace()
        marks = record["startupTrace"]["marks"]
        for row in marks:
            if row["name"] == "engineStartedMs":
                row["ms"] = 20000
        marks.sort(key=lambda row: row["ms"])
        report = inspect_trace(record)
        self.assertEqual(report["status"], "VALID_DIAGNOSTIC_TRACE", report)
        self.assertIsNone(report["phases"]["sceneToContinuation"]["spanMs"])

    def test_trace_cli_reports_evidence_not_acceptance(self):
        result = subprocess.run([sys.executable, "-B", str(Path(__file__)), "--trace", str(self.path),
                                 "--aggregation", "per-call-rounded"],
                                capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["performanceAccepted"])
        self.assertEqual(report["sourceSha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())


class SunbreakPhysicalContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = ROOT / "artifacts/startup-v118/godot-analysis/sunbreak-hoist-01"
        _, _, (cls.before, cls.after), _, _ = sunbreak_inputs(cls.directory)
        cls.report = inspect_sunbreak(cls.directory)

    def test_actual_pack_not_just_proof_has_exactly_179_unchanged_entries(self):
        self.assertEqual(self.report["status"], "PASS_BOUNDED_STRUCTURE_AND_SOURCE")
        self.assertEqual(self.report["entryCount"], 184)
        self.assertEqual(len(self.report["unchangedEntries"]), 179)
        self.assertTrue(all(row["byteExact"] for row in self.report["unchangedEntries"]))
        self.assertFalse(self.report["performanceAccepted"])
        self.assertFalse(self.report["webVisualAccepted"])

    def test_scenes_settings_geometry_scripts_textures_water_are_byte_exact(self):
        for path in self.before:
            if path not in HOIST_ALLOWED:
                self.assertEqual(self.before[path], self.after[path], path)
        for path in ("project.binary", "scripts/meadow_scene.gdc", "shaders/meadow_water.gdshader"):
            self.assertIn(path, self.before)
            self.assertEqual(self.before[path], self.after[path])

    def test_every_shader_wrapper_is_resolved_and_active_consumers_assign_once(self):
        semantics = self.report["semantics"]
        self.assertEqual(set(semantics["activeShaderConsumers"]), HOIST_ACTIVE_ROOTS)
        self.assertEqual(len(semantics["inactiveExpandedShadersExact"]), 14)
        self.assertEqual(len(semantics["fourDirectFragmentWriters"]), 4)
        for name in ("meadow_architecture", "meadow_architecture_day", "meadow_distant_cutout",
                     "meadow_mountain", "meadow_mountain_day", "meadow_water"):
            self.assertIn("shaders/" + name + ".gdshader", semantics["inactiveExpandedShadersExact"])

    def test_missing_duplicate_or_vertex_interpolated_assignment_rejected(self):
        path = "shaders/meadow_leaves.gdshader"
        for mutation in ("missing", "duplicate", "vertex", "conditional"):
            with self.subTest(mutation=mutation):
                bad = dict(self.after)
                nl = b"\r\n" if b"\r\n" in bad[path] else b"\n"
                line = HOIST_ASSIGNMENT + nl
                if mutation == "missing":
                    bad[path] = bad[path].replace(line, b"")
                elif mutation == "duplicate":
                    bad[path] = bad[path].replace(line, line + line)
                elif mutation == "vertex":
                    bad[path] = bad[path].replace(line, b"").replace(b"void vertex() {" + nl, b"void vertex() {" + nl + line)
                else:
                    bad[path] = bad[path].replace(line, b"    if (middle_scrub) {" + nl + line + b"    }" + nl)
                with self.assertRaises(ValueError):
                    verify_sunbreak_sources(self.before, bad)

    def test_changed_light_predicate_strength_precision_and_cloud_math_rejected(self):
        for old, new in ((b"> 0.999", b"> 0.998"), (b"= 0.72;", b"= 0.70;"),
                         (b"varying float sunbreak_fragment", b"varying lowp float sunbreak_fragment"),
                         (b"warp * 21.0", b"warp * 20.0")):
            with self.subTest(old=old):
                bad = dict(self.after)
                self.assertIn(old, bad[HOIST_SHARED])
                bad[HOIST_SHARED] = bad[HOIST_SHARED].replace(old, new)
                with self.assertRaises(ValueError):
                    verify_sunbreak_sources(self.before, bad)

    def test_vertex_world_input_or_cutout_guard_change_rejected(self):
        for path, old, new in (
                ("shaders/meadow_leaves.gdshader", b"sunbreak_position = world_position;", b"sunbreak_position = vec3(0.0);"),
                ("shaders/meadow_cutout_surface.gdshaderinc", b"#ifdef MEADOW_SUNBREAK", b"#ifdef MEADOW_ARCHITECTURE")):
            bad = dict(self.after)
            self.assertIn(old, bad[path])
            bad[path] = bad[path].replace(old, new)
            with self.assertRaises(ValueError):
                verify_sunbreak_sources(self.before, bad)

    def test_unlisted_water_or_runtime_or_geometry_changes_rejected(self):
        geometry = next(path for path in self.after if path.endswith(".scn"))
        for path in ("shaders/meadow_water.gdshader", "project.binary", "scripts/meadow_scene.gdc", geometry):
            with self.subTest(path=path):
                bad = dict(self.after)
                bad[path] += b"\0"
                with self.assertRaises(ValueError):
                    verify_sunbreak_sources(self.before, bad)

    def test_shader_comment_filter_preserves_quoted_resource_paths(self):
        source = b'#include "res://shaders/a.gdshaderinc" // discard return\n/* comment */\n'
        self.assertIn(b'"res://shaders/a.gdshaderinc"', shader_code(source))
        self.assertNotIn(b"discard", shader_code(source))

    def test_include_cycles_and_unknown_conditional_forms_fail_closed(self):
        for blobs in ({"shaders/a.gdshaderinc": b'#include "res://shaders/a.gdshaderinc"\n'},
                      {"shaders/a.gdshaderinc": b"#if UNKNOWN_DRIVER\n#endif\n"}):
            with self.assertRaises(ValueError):
                expanded_shader(blobs, "shaders/a.gdshaderinc")

    def test_new_native_report_is_pinned_and_reproduces_original_invariants(self):
        directory = ROOT / "artifacts/loading-v115/runtime"
        path = directory / "sunbreak-hoist-01-v119-independent.json"
        candidate = json.loads(path.read_text(encoding="utf-8"))
        original_path = directory / "original.json"
        original = json.loads(original_path.read_text(encoding="utf-8"))
        previous = json.loads((directory / "final-trial-v117.json").read_text(encoding="utf-8"))
        self.assertEqual(candidate["status"], "PASS")
        self.assertEqual(candidate["packSha256"], HOIST_CANDIDATE_SHA)
        self.assertEqual(previous["packSha256"], HOIST_SOURCE_SHA)
        self.assertEqual(candidate["probeSha256"], "260f76ab28073f052600549bbc8249007a42b6d674602460f773076eec4337b9")
        self.assertEqual(candidate["comparison"]["baselineSha256"], hashlib.sha256(original_path.read_bytes()).hexdigest())
        self.assertEqual(candidate["packBinding"], {"allLoadedEntryMd5Match": True, "entryCount": 184, "matchedLoadedEntries": 184})
        self.assertTrue(candidate["inputPackUnchanged"])
        self.assertEqual(candidate["errors"], [])
        self.assertEqual(len(candidate["comparison"]["checks"]), 11)
        self.assertTrue(all(candidate["comparison"]["checks"].values()))
        for key in ("camera", "water", "walkingBoss", "weather", "routes"):
            self.assertEqual(original[key], candidate[key], key)
        for key in ("structureSha256", "nodeCount", "lightCounts", "colliderSetSha256", "colliderCount"):
            self.assertEqual(original["inventory"][key], candidate["inventory"][key], key)
        clean = lambda rows: [{key: value for key, value in row.items() if key != "path"} for row in rows]
        self.assertEqual(clean(original["inventory"]["nodes"]), clean(candidate["inventory"]["nodes"]))
        self.assertEqual(previous["renderSettings"], candidate["renderSettings"])
        log = path.with_suffix(".engine.log").read_text(encoding="utf-8-sig")
        self.assertNotRegex(log, r"(?:SHADER ERROR|SCRIPT ERROR|\bERROR:|\bWARNING:)")


class MaterialLoopContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = ROOT / "artifacts/startup-v118/godot-analysis/bounded-material-loops-01"
        _, _, (cls.before, cls.after) = material_inputs(cls.directory)
        cls.report = inspect_material_loops(cls.directory)
        _, _, (_, cls.hoisted), _, _ = sunbreak_inputs(ROOT / "artifacts/startup-v118/godot-analysis/sunbreak-hoist-01")
        cls.compile = json.loads((cls.directory / "proof.json").read_text())["shaderLanguageValidation"]

    def test_actual_three_entry_candidate_preserves_181_payloads(self):
        self.assertEqual(self.report["status"], "PASS_BOUNDED_MATERIAL_LOOP_SOURCE")
        self.assertEqual(len(self.report["unchangedEntries"]), 181)
        self.assertTrue(all(row["byteExact"] for row in self.report["unchangedEntries"]))
        for path in ("shaders/meadow_sky.gdshader", "shaders/meadow_water.gdshader", HOIST_SHARED,
                     "project.binary", "scripts/meadow_scene.gdc"):
            self.assertEqual(self.before[path], self.after[path], path)
        self.assertFalse(self.report["nativeCandidateAudited"])
        self.assertFalse(self.report["performanceAccepted"])

    def test_count_loops_preserve_index_order_across_signed_integer_boundary_classes(self):
        for count in (-2147483648, -1000, *range(-2, 100), 2147483647):
            old = []
            for index in range(32):
                if index >= count:
                    break
                old.append(index)
            new = list(range(min(32, count)))
            self.assertEqual(old, new, count)
            self.assertTrue(all(0 <= index < 32 for index in new))

    def test_ground_default_is_72_not_equivalence_for_arbitrary_overrides(self):
        self.assertEqual(list(range(72)), list(range(max(0, min(72, 72)))))
        self.assertNotEqual(list(range(72)), list(range(max(0, min(72, 71)))))
        for count in (-2147483648, -1, 0, 1, 71, 72, 73, 2147483647):
            self.assertTrue(all(0 <= index < 72 for index in range(max(0, min(72, count)))))
        self.assertFalse(self.report["semantics"]["gpuDefaultReadbackEstablished"])

    def test_only_one_new_int_on_each_ground_interface_is_permitted(self):
        self.assertFalse(self.report["allUniformInterfacesExact"])
        self.assertTrue(self.report["existingUniformInterfacesExact"])
        self.assertEqual(set(self.report["allowedAddedUniforms"]), MATERIAL_UNIFORM_ROOTS)
        self.assertEqual(len(self.report["semantics"]["changedExpandedShaderRoots"]), 9)
        self.assertEqual(len(self.report["semantics"]["exactExpandedShaderRoots"]), 11)

    def test_changed_defaults_caps_types_comparators_and_loop_arithmetic_rejected(self):
        for old, new in ((b"iterations = 72;", b"iterations = 71;"),
                         (b"iterations = 72;", b"iterations = 73;"),
                         (b"uniform int contact_shadow", b"uniform float contact_shadow"),
                         (b"clamp(contact_shadow_iterations, 0, 72)", b"clamp(contact_shadow_iterations, 0, 73)"),
                         (b"i < clamp", b"i <= clamp"),
                         (b"shadow *= mix(0.72", b"shadow *= mix(0.70")):
            with self.subTest(old=old, new=new):
                bad = dict(self.after)
                self.assertIn(old, bad[MATERIAL_GROUND])
                bad[MATERIAL_GROUND] = bad[MATERIAL_GROUND].replace(old, new)
                with self.assertRaises(ValueError):
                    verify_material_sources(self.before, bad)

    def test_count_cap_wrong_uniform_or_reintroduced_break_rejected(self):
        for path, (name, _) in MATERIAL_COUNT_LOOPS.items():
            for old, new in ((f"min(32, {name})", f"min(31, {name})"),
                             (f"min(32, {name})", f"min(33, {name})"),
                             (f"min(32, {name})", "min(32, wrong_count)"),
                             ("i < min", "i <= min"),
                             (f"i < min(32, {name}); i++) {{", f"i < min(32, {name}); i++) {{ if (i >= {name}) {{ break; }}")):
                with self.subTest(path=path, new=new):
                    bad = dict(self.after)
                    self.assertIn(old.encode(), bad[path])
                    bad[path] = bad[path].replace(old.encode(), new.encode())
                    with self.assertRaises(ValueError):
                        verify_material_sources(self.before, bad)

    def test_extra_wrong_type_duplicate_or_missing_compiled_uniform_is_rejected(self):
        before, original = self.compile["baseline"]["uniforms"], self.compile["candidate"]["uniforms"]
        ground = "res://shaders/meadow_ground.gdshader"
        for mutation in ("float", "duplicate", "missing", "sky", "unrelated"):
            with self.subTest(mutation=mutation):
                bad = copy.deepcopy(original)
                extra = next(row for row in bad[ground] if row["name"] == MATERIAL_NAME.decode())
                if mutation == "float":
                    extra["type"] = 3
                elif mutation == "duplicate":
                    bad[ground].append(extra.copy())
                elif mutation == "missing":
                    bad[ground].remove(extra)
                elif mutation == "sky":
                    bad["res://shaders/meadow_sky.gdshader"].append(extra.copy())
                else:
                    bad[ground].append({**extra, "name": "another_control"})
                with self.assertRaises(ValueError):
                    verify_material_interface(before, bad)

    def test_all_six_compressed_material_resources_are_checked_for_overrides(self):
        self.assertEqual(len(self.report["decodedRsccNoOverride"]), 6)
        self.assertIn("assets/baked/v77/terrain.scn", {row["path"] for row in self.report["decodedRsccNoOverride"]})

    def test_override_hidden_in_raw_or_compressed_utf16_is_rejected(self):
        import struct
        import zstandard
        for encoding in ("utf-8", "utf-16-le"):
            raw = ("shader_parameter/" + MATERIAL_NAME.decode() + " = 1").encode(encoding)
            frame = zstandard.ZstdCompressor().compress(raw)
            compressed = b"RSCC" + struct.pack("<IIII", 2, 4096, len(raw), len(frame)) + frame + b"RSCC"
            for blob in (raw, compressed):
                with self.assertRaisesRegex(ValueError, "Pre-existing parameter/override"):
                    material_no_override({"fixture-material": blob})

    def compose_in_memory(self):
        # Synthetic composition test ONLY: no pack creation or file writes.
        combined = dict(self.hoisted)
        for path in MATERIAL_ALLOWED:
            blob = combined[path]
            nl = b"\r\n" if b"\r\n" in blob else b"\n"
            if path == MATERIAL_GROUND:
                blob = blob.replace(b"uniform vec4 contact_shadows[72];" + nl,
                                    b"uniform vec4 contact_shadows[72];" + nl + MATERIAL_DECLARATION + nl)
                blob = blob.replace(b"for (int i = 0; i < 72; i++)", MATERIAL_BOUND)
            else:
                name, indent = MATERIAL_COUNT_LOOPS[path]
                old = b"for (int i = 0; i < 32; i++) {" + nl + b" " * indent + f"if (i >= {name}) {{ break; }}".encode() + nl
                blob = blob.replace(old, f"for (int i = 0; i < min(32, {name}); i++) {{".encode() + nl)
            combined[path] = blob
        return combined

    def test_composed_source_requires_both_edits_and_exact_six_entry_union(self):
        report = verify_material_sources(self.before, self.compose_in_memory(), combined=True)
        self.assertEqual(len(report["changedEntries"]), 6)
        self.assertEqual(report["unchangedEntryCount"], 178)
        self.assertFalse(report["allUniformInterfacesExact"])

    def test_wholesale_overlays_that_lose_either_edit_are_rejected(self):
        for first, second, paths in ((self.hoisted, self.after, MATERIAL_ALLOWED),
                                     (self.after, self.hoisted, HOIST_ALLOWED)):
            bad = dict(first)
            bad.update({path: second[path] for path in paths})
            with self.assertRaises(ValueError):
                verify_material_sources(self.before, bad, combined=True)

    def test_combined_source_does_not_authorize_extra_sky_water_or_runtime_edits(self):
        for path in ("shaders/meadow_sky.gdshader", "shaders/meadow_water.gdshader", "scripts/meadow_scene.gdc"):
            bad = self.compose_in_memory()
            bad[path] += b"\0"
            with self.assertRaises(ValueError):
                verify_material_sources(self.before, bad, combined=True)


class CombinedPhysicalContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = ROOT / "artifacts/startup-v118/godot-analysis/combined-01"
        _, _, (cls.before, cls.after) = combined_inputs(cls.directory)
        _, _, (_, cls.hoisted), _, _ = sunbreak_inputs(cls.directory.parent / "sunbreak-hoist-01")
        _, _, (_, cls.looped) = material_inputs(cls.directory.parent / "bounded-material-loops-01")
        cls.composition = json.loads((cls.directory / "composition.json").read_text())
        cls.native = ROOT / "artifacts/loading-v115/runtime/combined-01-v122-independent.json"
        cls.report = inspect_combined(cls.directory, cls.native)

    def test_actual_combined_pack_has_exact_six_changes_and_178_preserved_entries(self):
        self.assertEqual(self.report["status"], "PASS_COMBINED_SOURCE_AND_NATIVE")
        self.assertEqual(self.report["candidatePckSha256"], COMBINED_SHA)
        self.assertEqual(self.report["candidateBytes"], 44327612)
        self.assertEqual(len(self.report["unchangedEntries"]), 178)
        self.assertTrue(all(row["byteExact"] for row in self.report["unchangedEntries"]))
        self.assertEqual({path for path in self.before if self.before[path] != self.after[path]}, COMBINED_ALLOWED)
        for path in ("project.binary", "scripts/meadow_scene.gdc", "shaders/meadow_water.gdshader", "shaders/meadow_sky.gdshader"):
            self.assertEqual(self.before[path], self.after[path], path)

    def test_reverse_both_passes_recovers_both_frozen_candidates_and_original(self):
        self.assertEqual(undo_material_loops(self.before, self.after), self.hoisted)
        self.assertEqual(undo_sunbreak(self.before, self.after), self.looped)
        self.assertEqual(undo_sunbreak(self.before, self.hoisted), self.before)
        self.assertEqual(undo_material_loops(self.before, self.looped), self.before)

    def test_actual_combined_fragment_consumers_and_uniform_exception(self):
        self.assertFalse(self.report["allUniformInterfacesExact"])
        self.assertTrue(self.report["existingUniformInterfacesExact"])
        self.assertEqual(set(self.report["allowedAddedUniforms"]), MATERIAL_UNIFORM_ROOTS)
        self.assertIn(MATERIAL_DECLARATION, self.after[MATERIAL_GROUND])
        for path in HOIST_ACTIVE_ROOTS:
            expanded = expanded_shader(self.after, path)
            self.assertEqual(shader_body(expanded, "fragment").count(HOIST_ASSIGNMENT), 1, path)
            self.assertNotIn(HOIST_VALUE, shader_body(expanded, "vertex"), path)
            self.assertEqual(shader_body(expanded, "light").count(HOIST_VALUE), 1, path)

    def test_attested_true_does_not_hide_stage_hash_membership_or_order_errors(self):
        for mutation in ("hash", "missing", "duplicate", "order", "count", "flag", "stagefile"):
            with self.subTest(mutation=mutation):
                bad = copy.deepcopy(self.composition)
                if mutation == "hash":
                    bad["entries"][1]["afterHoistSha256"] = "0" * 64
                elif mutation == "missing":
                    bad["entries"].pop()
                elif mutation == "duplicate":
                    bad["entries"][1] = copy.deepcopy(bad["entries"][0])
                elif mutation == "order":
                    bad["orderedTransforms"][1:] = reversed(bad["orderedTransforms"][1:])
                elif mutation == "count":
                    bad["stageTwoChangedEntries"] = 2
                elif mutation == "flag":
                    bad["entries"][1]["stageTwoChanged"] = False
                else:
                    bad["entries"][1]["hoistedSourceFile"] = str(self.directory / "replacement" / bad["entries"][1]["path"])
                with self.assertRaises(ValueError):
                    verify_combined_composition(self.directory, bad, self.before, self.after, self.hoisted, self.looped)

    def test_neither_blind_overlay_can_be_accepted_with_real_combined_proof(self):
        for first, second, paths in ((self.hoisted, self.looped, MATERIAL_ALLOWED), (self.looped, self.hoisted, HOIST_ALLOWED)):
            bad = dict(first)
            bad.update({path: second[path] for path in paths})
            with self.assertRaises(ValueError):
                verify_combined_composition(self.directory, self.composition, self.before, bad, self.hoisted, self.looped)

    def test_actual_combined_wrong_default_predicate_or_unlisted_edit_is_rejected(self):
        cases = ((MATERIAL_GROUND, b"iterations = 72;", b"iterations = 71;"),
                 (HOIST_SHARED, b"> 0.999", b"> 0.998"),
                 ("shaders/meadow_water.gdshader", b"", b"\0"),
                 ("scripts/meadow_scene.gdc", b"", b"\0"))
        for path, old, new in cases:
            with self.subTest(path=path):
                bad = dict(self.after)
                bad[path] = bad[path].replace(old, new) if old else bad[path] + new
                with self.assertRaises(ValueError):
                    verify_combined_composition(self.directory, self.composition, self.before, bad, self.hoisted, self.looped)

    def test_final_native_is_fresh_pinned_and_all_11_comparisons_recomputed(self):
        native = self.report["native"]
        self.assertEqual(len(native["checks"]), 11)
        self.assertTrue(native["all11IndependentlyRecomputed"])
        self.assertEqual(native["inventory"]["nodeCount"], 144)
        self.assertEqual(native["inventory"]["colliderCount"], 5)
        self.assertEqual(native["packBinding"]["matchedLoadedEntries"], 184)
        self.assertFalse(self.report["performanceAccepted"])
        self.assertFalse(self.report["webVisualAccepted"])

    def test_prior_hoist_native_pass_cannot_be_relabeled_combined(self):
        prior = ROOT / "artifacts/loading-v115/runtime/sunbreak-hoist-01-v119-independent.json"
        with self.assertRaisesRegex(ValueError, "Wrong native candidate/reference pack"):
            inspect_combined_native(prior)

    def test_original_and_balanced_pack_bytes_stay_frozen(self):
        for path, pin in (("artifacts/v114/index.pck", "02adc956b196fc701092b5186343da9146a5f30b64f349d5d3dcbe12b8f81a6d"),
                          ("artifacts/v117/index-balanced.pck", "68198062fb7918abaef956d588ec5e929104dffe348d520602c862749af67a33")):
            self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), pin, path)


class V117ZeroTypeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = inspect_v117_zero_types(ROOT / "artifacts/v117/index-lite.pck")
        cls.native = json.loads((ROOT / "artifacts/loading-v115/runtime/final-trial-v117.json").read_text(encoding="utf-8-sig"))

    def test_approved_v117_is_all184_exact_not_combined_184_exact(self):
        self.assertEqual(self.report["status"], "PASS_V117_ZERO_UNUSED_LIGHT_CONTRACT")
        self.assertTrue(self.report["all184EntriesExactAgainstApprovedV117"])
        self.assertEqual(self.report["unchangedEntriesAgainstCombined"], 178)
        self.assertEqual(set(self.report["shaderDifferencesFromCombined"]), COMBINED_ALLOWED)
        self.assertEqual(self.report["additionalEligibleContract"], {"packSha256": HOIST_SOURCE_SHA, "spotLights": 0, "areaLights": 0})
        self.assertEqual(self.report["newNativeRuns"], 0)
        self.assertFalse(self.report["performanceAccepted"])

    def test_old_native_and_all40_source_pins_extend_day_night_proof(self):
        self.assertEqual(self.report["nativeReportSha256"], V117_NATIVE_SHA)
        self.assertEqual(len(self.report["nativeAll11ComparisonsIndependentlyRecomputed"]), 11)
        self.assertEqual(len(self.report["all40InspectedLightSourcePinsStillExact"]), 40)
        self.assertTrue(self.report["all37CompiledScriptsAnd7ScenesExactAgainstCombined"])
        self.assertEqual(zero_type_snapshot(self.native, HOIST_SOURCE_SHA), {"directional": 4, "omni": 9, "spot": 0, "area": 0})

    def test_hidden_night_light_cannot_be_ignored_or_retyped_spot_area(self):
        for new_type in ("SpotLight3D", "AreaLight3D", "RectLight3D"):
            with self.subTest(new_type=new_type):
                bad = copy.deepcopy(self.native)
                node = next(row for row in bad["inventory"]["nodes"] if row["stablePath"].endswith("MoonStagGroundLight"))
                self.assertFalse(node["visible"])
                node["class"] = new_type
                bad["inventory"]["lightCounts"] = {"DirectionalLight3D": 4, "OmniLight3D": 8, new_type: 1}
                with self.assertRaisesRegex(ValueError, "no other light classes"):
                    zero_type_snapshot(bad, HOIST_SOURCE_SHA)

    def test_unknown_hash_or_combined_native_cannot_be_relabeled_v117(self):
        with self.assertRaisesRegex(ValueError, "Unreviewed zero-type"):
            zero_type_snapshot(self.native, "f" * 64)
        bad = copy.deepcopy(self.native)
        bad["packSha256"] = COMBINED_SHA
        with self.assertRaisesRegex(ValueError, "wrong native report"):
            zero_type_snapshot(bad, HOIST_SOURCE_SHA)
        bad = copy.deepcopy(self.native)
        bad["packBinding"]["matchedLoadedEntries"] = 183
        with self.assertRaisesRegex(ValueError, "incomplete mounted-pack"):
            zero_type_snapshot(bad, HOIST_SOURCE_SHA)

    def test_actual_combined_pack_cannot_claim_no_pck_edits(self):
        with self.assertRaisesRegex(ValueError, "byte-identical approved v117"):
            inspect_v117_zero_types(ROOT / "artifacts/startup-v118/godot-analysis/combined-01/index-lite.pck")


if __name__ == "__main__":
    if "--zero-types-v117" in sys.argv:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--zero-types-v117", type=Path, required=True)
        args = parser.parse_args()
        try:
            report = inspect_v117_zero_types(args.zero_types_v117)
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
            report = {"status": "FAIL_V117_ZERO_TYPE_CONTRACT", "errors": [str(error)], "performanceAccepted": False,
                      "webVisualAccepted": False, "newNativeRuns": 0}
        print(json.dumps(report, indent=2))
        raise SystemExit(0 if report["status"] == "PASS_V117_ZERO_UNUSED_LIGHT_CONTRACT" else 1)
    elif "--combined" in sys.argv:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--combined", type=Path, required=True)
        parser.add_argument("--native-report", type=Path)
        args = parser.parse_args()
        try:
            report = inspect_combined(args.combined, args.native_report)
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
            report = {"status": "FAIL_COMBINED_CONTRACT", "errors": [str(error)], "performanceAccepted": False,
                      "webVisualAccepted": False, "nativeCandidateAudited": False}
        print(json.dumps(report, indent=2))
        raise SystemExit(0 if report["status"] in ("PASS_COMBINED_SOURCE", "PASS_COMBINED_SOURCE_AND_NATIVE") else 1)
    elif "--material-loops" in sys.argv:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--material-loops", type=Path, required=True)
        args = parser.parse_args()
        try:
            report = inspect_material_loops(args.material_loops)
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
            report = {"status": "FAIL_MATERIAL_LOOP_CONTRACT", "errors": [str(error)], "performanceAccepted": False,
                      "webVisualAccepted": False, "nativeCandidateAudited": False}
        print(json.dumps(report, indent=2))
        raise SystemExit(0 if report["status"] == "PASS_BOUNDED_MATERIAL_LOOP_SOURCE" else 1)
    elif "--sunbreak" in sys.argv:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--sunbreak", type=Path, required=True)
        args = parser.parse_args()
        try:
            report = inspect_sunbreak(args.sunbreak)
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
            report = {"status": "FAIL_SUNBREAK_CONTRACT", "errors": [str(error)], "performanceAccepted": False, "webVisualAccepted": False}
        print(json.dumps(report, indent=2))
        raise SystemExit(0 if report["status"] == "PASS_BOUNDED_STRUCTURE_AND_SOURCE" else 1)
    elif "--trace" in sys.argv:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--trace", type=Path, required=True)
        parser.add_argument("--aggregation", choices=("unknown", "per-call-rounded", "final-round-only"),
                            default="unknown")
        args = parser.parse_args()
        try:
            source = args.trace.read_bytes()
            report = inspect_trace(json.loads(source.decode("utf-8-sig")), args.aggregation)
            report.update(source=str(args.trace.resolve()), sourceSha256=hashlib.sha256(source).hexdigest())
        except (OSError, UnicodeError, ValueError) as error:
            report = {"status": "INVALID_TRACE", "errors": [str(error)], "performanceAccepted": False}
        print(json.dumps(report, indent=2))
        raise SystemExit(0 if report["status"] == "VALID_DIAGNOSTIC_TRACE" else 1)
    elif "--saved" in sys.argv:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--saved", nargs=2, type=Path, required=True)
        args = parser.parse_args()
        print(json.dumps(inspect_pair(*(json.loads(p.read_text(encoding="utf-8")) for p in args.saved)), indent=2))
        raise SystemExit(1)
    else:
        unittest.main()
