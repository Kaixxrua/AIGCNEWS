"""Independent v128 wire/measurement guards; no browser, service or native run.

Default: bounded synthetic regression tests. --baseline-report: read the actual
saved v127 telemetry and resource inventory. No shipping instrumentation changes.
"""
import copy
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import unittest

from inspect_web_pack import read_pack, summarize


ROOT = Path(__file__).resolve().parents[2]
V127_SHA = "771ef72d7011b8843d826a84d387dd8e31c2518ba105cd4ad2981471901165cf"


def number(value, label, positive=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(label)
    try:
        result = float(value)
    except (ValueError, OverflowError):
        raise ValueError(label) from None
    if not math.isfinite(result) or result < 0 or (positive and result == 0):
        raise ValueError(label)
    return result


def wire_budget(body_bytes, *, mbps=20, target_ms=10000, serial_reserve_ms=0):
    """Necessary optimistic bound only: decimal Mbps, no fictitious overlap win."""
    size = number(body_bytes, "encoded bytes")
    rate = number(mbps, "Mbps", positive=True) * 1_000_000 / 8
    target = number(target_ms, "target", positive=True)
    reserve = number(serial_reserve_ms, "reserve")
    if reserve >= target:
        raise ValueError("No time left for transfer")
    ceiling = math.floor(rate * (target - reserve) / 1000)
    return {"encodedBodyBytes": size, "wireOnlyLowerBoundMs": size / rate * 1000,
            "serialReserveMs": reserve, "optimisticBodyCeilingBytes": ceiling,
            "necessaryWireBoundSatisfied": size <= ceiling,
            "sufficientToClaimTenSeconds": False}


def phases(evidence):
    d = evidence["data"]
    get = lambda key: number(d[key], key)
    # Loader, controls and ResourceTiming have different origins. Only subtract
    # fields belonging to the same clock. The two resulting intervals overlap.
    loader_span = get("engineStartedMs") - get("runtimeStartMs")
    scene_to_ready = get("loadMs") - get("sceneSignalMs")
    if min(loader_span, scene_to_ready) < 0:
        raise ValueError("Inverted milestones")
    return {"controlsStartToPresentationMs": get("loadMs"), "parentReadyBodyMs": get("sceneBuildMs"),
            "loaderStartCallSpanMs": loader_span, "controlsSceneSignalToPresentationMs": scene_to_ready,
            "engineInitElapsedOverlapsPackFetchMs": get("engineInitMs"),
            "attributedCpuMs": None, "intervalsMayNotBeSummed": True,
            "navigationToPresentationMs": None}


def controlled_http_first_load(evidence, expected_encoded, expected_pack_sha):
    """Validate saved controls, not merely an under-10s number or decoded size."""
    net, d = evidence.get("network", {}), evidence["data"]
    if net.get("httpCacheDisabled") is not True or net.get("downloadMbps") != 20 or net.get("uploadMbps") != 5 or net.get("latencyMs") != 80:
        raise ValueError("Require recorded 20/5 Mbps, 80 ms and HTTP cache bypass")
    if not isinstance(net.get("driverCache"), str) or not net["driverCache"].strip():
        raise ValueError("Driver cache state must be separately described")
    if evidence.get("visibility") != "visible" or number(d.get("loadHiddenMs"), "hidden duration") != 0:
        raise ValueError("Foreground-only measurement")
    canvas = evidence.get("canvas")
    if canvas != [2560, 1440] or [number(d.get("startupAuditCanvasWidth"), "width"),
                                 number(d.get("startupAuditCanvasHeight"), "height")] != canvas:
        raise ValueError("Actual QHD backing canvas required")
    dpr = number(evidence.get("dpr"), "DPR", positive=True)
    if abs(dpr - 1) > 1e-6 or abs(dpr - number(d.get("startupAuditDpr"), "bridge DPR", positive=True)) > 1e-6:
        raise ValueError("Matched DPR required; tolerance is only recorded float representation")
    if d.get("textureQuality") != "lite" or d.get("motion") != "false" or d.get("transitioning") != "false" or number(d.get("nightBlend"), "night") != 0 or number(d.get("weatherClock"), "clock") != 0:
        raise ValueError("Matched paused day-zero controls required")
    if d.get("startupAuditStatus") != "skipped" or d.get("startupAuditEnabled") != "false" or number(d.get("startupAuditMs"), "audit duration") != 0:
        raise ValueError("Normal trace-off/audit-off benchmark required")
    if "startupTrace" in d or "startup_trace=1" in evidence.get("url", ""):
        raise ValueError("Diagnostic GL tracing is not a final timing run")
    compile_state = json.loads(d["fastCompile"])
    if compile_state.get("specializationPackSha256") != expected_pack_sha or compile_state.get("nativeFailures") != 0:
        raise ValueError("Selected pack pin or shader failure")
    resources = json.loads(d["resourceTiming"])
    if len(resources) != len(expected_encoded) or {r["file"] for r in resources} != set(expected_encoded):
        raise ValueError("Exactly the selected pack plus engine, no extra quality PCK")
    for row in resources:
        encoded = number(row["encodedBodyBytes"], "encoded size", positive=True)
        if encoded != expected_encoded[row["file"]] or number(row["transferBytes"], "transfer bytes") < encoded:
            raise ValueError("Cached/revalidated/mismatched body is not HTTP first-load evidence")
        start, response, end = (number(row[k], k) for k in ("startMs", "responseStartMs", "responseEndMs"))
        if not start <= response <= end:
            raise ValueError("ResourceTiming ordering")
    return {"controlsValid": True, "driverCache": net["driverCache"], "phases": phases(evidence),
            "bodyBytes": sum(expected_encoded.values()), "fullNavigationTimingProved": False}


def final_navigation_gate(evidence, expected_pack_sha):
    """Proposed normalized evidence envelope from main's DOM/frame records.

This consumes evidence; it does not instrument or replace the application's
ready gate. Strict source/native/visual reviews must attest the supplied facts.
"""
    if evidence.get("packSha256") != expected_pack_sha or evidence.get("clockDomain") != "performance.now/navigation":
        raise ValueError("Pinned pack and common page-clock origin required")
    if evidence.get("mandatoryNodes") != 144 or evidence.get("allSceneObjectsReady") is not True or evidence.get("collisionReady") is not True:
        raise ValueError("No incomplete scene/collision at the measurement endpoint")
    keys = ("navigationStartAtMs", "sceneCompleteAtMs", "framePostDrawAtMs", "rafOneAtMs", "presentedAtMs")
    stamps = [number(evidence.get(k), k) for k in keys]
    if stamps != sorted(stamps) or not stamps[-1] > stamps[-2] > stamps[-3]:
        raise ValueError("Require completed-scene draw followed by two distinct RAF boundaries")
    if evidence.get("loadingHidden") is not True or evidence.get("webErrors") != []:
        raise ValueError("Readiness/error evidence incomplete")
    elapsed = stamps[-1] - stamps[0]
    return {"navigationToPresentationMs": elapsed, "withinTenSeconds": elapsed <= 10000,
            "gpuVisualAcceptance": "separate required main review"}


def baseline_report():
    version = ROOT / "artifacts/v127"
    blob = (version / "index-lite.pck").read_bytes()
    if hashlib.sha256(blob).hexdigest() != V127_SHA:
        raise ValueError("Actual v127 PCK pin")
    pack = read_pack(version / "index-lite.pck")
    manifest = json.loads((version / "web-payload.json").read_text())
    for name, row in manifest.items():
        if name in ("index.pck", "index-balanced.pck"):
            continue
        for coding in ("br", "gzip"):
            suffix = ".br" if coding == "br" else ".gz"
            data = (version / (name + suffix)).read_bytes()
            encoding = row["encodings"][coding]
            if len(data) != encoding["bytes"] or hashlib.sha256(data).hexdigest() != encoding["sha256"]:
                raise ValueError("Actual selected sidecar size/hash mismatch")
    expected = {n: manifest[n]["encodings"]["br"]["bytes"] for n in ("index.wasm", "index-lite.pck")}
    common = [n for n in manifest if not n.endswith(".pck")]
    totals = {coding: sum(manifest[n]["encodings"][coding]["bytes"] for n in common + ["index-lite.pck"])
              for coding in ("br", "gzip")}
    unlisted = {name: (version / name).stat().st_size for name in
                ("index.html", "index.png", "index.audio.worklet.js", "index.audio.position.worklet.js")}
    measurements = {}
    for name in ("v127-cold-20mbps-80ms.json", "v127-http-bypass.json", "v127-warm-20mbps-80ms.json"):
        path = ROOT / "artifacts/startup-v126" / name
        evidence = json.loads(path.read_text())
        row = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "phases": phases(evidence)}
        try:
            row["controlledFirstLoad"] = controlled_http_first_load(evidence, expected, V127_SHA)
        except ValueError as error:
            row["controlledFirstLoad"] = {"controlsValid": False, "reason": str(error)}
        measurements[name] = row
    caches = []
    for row in pack["entries"]:
        if row["path"].endswith(".scn"):
            raw = blob[row["offset"]:row["offset"] + row["bytes"]]
            info = {"path": row["path"], "storedBytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            if raw[:4] == b"RSCC":
                mode, block_size, decoded_bytes = struct.unpack_from("<III", raw, 4)
                info.update(mode=mode, blockBytes=block_size, decodedBytes=decoded_bytes)
            caches.append(info)
    baseline = json.loads((ROOT / "artifacts/startup-v126/independent/runtime/dense-q60-01.json").read_text())
    colliders = [{"path": r["stablePath"], "faceVertices": r["shape"]["faceVertexCount"],
                  "triangles": r["shape"]["faceVertexCount"] // 3,
                  "rawFloat32FaceBytes": r["shape"]["faceVertexCount"] * 12} for r in baseline["inventory"]["colliders"]]
    return {"schemaVersion": 1, "status": "V127_OBSERVED_BUDGET_FAIL_NOT_CANDIDATE_ACCEPTANCE",
            "packSha256": V127_SHA, "packInventory": summarize(pack), "sceneContainers": caches,
            "nativeColliderBaselineNotWebTiming": colliders, "manifestSelectedBodyTotalBytes": totals,
            "unlistedPreparedRawFileBytesNotObservedCriticalRequests": unlisted,
            "manifestTotalsExcludeHtmlIconAudioAndResponseHeaders": True,
            "wireBudget": {c: wire_budget(size) for c, size in totals.items()},
            "provisionalReserveScenarios": [wire_budget(totals["br"], serial_reserve_ms=r) for r in (2000, 3000, 4000)],
            "measurements": measurements, "allActualSelectedEncodingSizesHashesChecked": True,
            "v127NotMeasuredNavigationToPresentation": True, "nativeRuns": 0, "browserActions": 0, "builds": 0,
            "checkerSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


class BudgetTests(unittest.TestCase):
    def test_decimal_mbps_and_wire_floor(self):
        self.assertEqual(wire_budget(39_102_090)["wireOnlyLowerBoundMs"], 15640.836)
        self.assertFalse(wire_budget(39_102_090)["necessaryWireBoundSatisfied"])

    def test_reserved_cpu_budget_is_not_a_measured_win(self):
        row = wire_budget(15_000_000, serial_reserve_ms=4000)
        self.assertEqual(row["optimisticBodyCeilingBytes"], 15_000_000)
        self.assertFalse(row["sufficientToClaimTenSeconds"])

    def test_reject_nonfinite_negative_and_boolean(self):
        for value in (float("nan"), float("inf"), -1, True, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                wire_budget(value)

    def test_no_cross_origin_or_overlapping_phase_sum(self):
        d = dict(engineStartedMs="25548", runtimeStartMs="17742", loadMs="26553", sceneSignalMs="22510",
                 sceneBuildMs="2812", engineInitMs="7820")
        row = phases({"data": d})
        self.assertEqual(row["loaderStartCallSpanMs"], 7806)
        self.assertEqual(row["controlsSceneSignalToPresentationMs"], 4043)
        self.assertIsNone(row["attributedCpuMs"])

    def fixture(self):
        return {"network": {"downloadMbps": 20, "uploadMbps": 5, "latencyMs": 80, "httpCacheDisabled": True,
                            "driverCache": "existing, not cleared"}, "canvas": [2560, 1440], "dpr": 1, "visibility": "visible",
                "data": {"loadHiddenMs": "0", "startupAuditCanvasWidth": "2560", "startupAuditCanvasHeight": "1440",
                         "startupAuditDpr": "1", "textureQuality": "lite", "motion": "false", "transitioning": "false",
                         "nightBlend": "0", "weatherClock": "0", "startupAuditStatus": "skipped", "startupAuditEnabled": "false",
                         "startupAuditMs": "0", "fastCompile": json.dumps({"specializationPackSha256": V127_SHA, "nativeFailures": 0}),
                         "resourceTiming": json.dumps([{"file": "index-lite.pck", "encodedBodyBytes": 1000, "transferBytes": 1300,
                                                       "startMs": 10, "responseStartMs": 20, "responseEndMs": 30}]),
                         "engineStartedMs": "50", "runtimeStartMs": "30", "loadMs": "100", "sceneSignalMs": "70",
                         "sceneBuildMs": "20", "engineInitMs": "25"}}

    def test_valid_controls_do_not_prove_navigation_gpu_or_ten_seconds(self):
        row = controlled_http_first_load(self.fixture(), {"index-lite.pck": 1000}, V127_SHA)
        self.assertTrue(row["controlsValid"])
        self.assertFalse(row["fullNavigationTimingProved"])

    def test_warm_cache_rejected_even_with_nonzero_encoded_size(self):
        e = self.fixture()
        rows = json.loads(e["data"]["resourceTiming"])
        rows[0]["transferBytes"] = 300
        e["data"]["resourceTiming"] = json.dumps(rows)
        with self.assertRaises(ValueError):
            controlled_http_first_load(e, {"index-lite.pck": 1000}, V127_SHA)

    def test_invalid_controls_fail_closed(self):
        mutations = [("network", "httpCacheDisabled", False), ("network", "driverCache", ""),
                     ("network", "downloadMbps", 100), ("data", "loadHiddenMs", "1"),
                     ("data", "startupAuditCanvasWidth", "1280"), ("data", "motion", "true"),
                     ("data", "startupAuditStatus", "completed"), ("data", "startupTrace", "{}")]
        for section, key, value in mutations:
            e = self.fixture()
            e[section][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                controlled_http_first_load(e, {"index-lite.pck": 1000}, V127_SHA)

    def test_wrong_pack_pin_rejected(self):
        with self.assertRaises(ValueError):
            controlled_http_first_load(self.fixture(), {"index-lite.pck": 1000}, "0" * 64)

    def test_extra_quality_download_rejected(self):
        e = self.fixture()
        rows = json.loads(e["data"]["resourceTiming"])
        rows.append({**rows[0], "file": "index.pck"})
        e["data"]["resourceTiming"] = json.dumps(rows)
        with self.assertRaises(ValueError):
            controlled_http_first_load(e, {"index-lite.pck": 1000}, V127_SHA)

    def frame_fixture(self):
        return {"packSha256": V127_SHA, "clockDomain": "performance.now/navigation", "mandatoryNodes": 144,
                "allSceneObjectsReady": True, "collisionReady": True, "navigationStartAtMs": 0, "sceneCompleteAtMs": 8000,
                "framePostDrawAtMs": 8100, "rafOneAtMs": 8200, "presentedAtMs": 8300, "loadingHidden": True, "webErrors": []}

    def test_final_navigation_threshold_includes_complete_frame(self):
        e = self.frame_fixture()
        self.assertTrue(final_navigation_gate(e, V127_SHA)["withinTenSeconds"])
        e["presentedAtMs"] = 10000.1
        self.assertFalse(final_navigation_gate(e, V127_SHA)["withinTenSeconds"])

    def test_early_scene_signal_or_ack_is_not_a_complete_frame(self):
        for key, value in (("allSceneObjectsReady", False), ("collisionReady", False), ("mandatoryNodes", 142),
                           ("presentedAtMs", 7900), ("rafOneAtMs", 8100), ("clockDomain", "tool-wall-clock"),
                           ("webErrors", ["context lost"])):
            e = copy.deepcopy(self.frame_fixture())
            e[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                final_navigation_gate(e, V127_SHA)


if __name__ == "__main__":
    if sys.argv[1:] == ["--baseline-report"]:
        print(json.dumps(baseline_report(), indent=2))
    else:
        unittest.main(verbosity=2)
