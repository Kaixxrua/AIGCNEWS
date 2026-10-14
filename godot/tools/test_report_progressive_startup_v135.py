"""Bounded synthetic facts and pinned saved evidence; no browser/build/service/new benchmark runs."""
import copy
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

from report_progressive_startup_v135 import analyze_sample, json_value, summarize, EvidenceError


TOOL = Path(__file__).with_name("report_progressive_startup_v135.py")
URL = "http://127.0.0.1:4231/v135/index.html?quality=lite"
V140_RECORD = Path(__file__).resolve().parents[2] / "artifacts/startup-v135/v140-cold-diagnostic-02.json"
V140_SHA256 = "c67405496b1b98086dcc823d0cf99f2b667e3aed0084fd5b91c39dc21acf0037"


def fixture(run=1, core=9500, *, complete=False, bootstrap=False):
    """Invented numbers ONLY for contract tests; never presented as measurements."""
    loader = f"synthetic-navigation-{run}"
    stamp = 1000 + run * 100
    events = [{"method": "Network.requestWillBeSent", "params": {
        "requestId": f"doc-{run}", "loaderId": loader, "type": "Document",
        "timestamp": stamp, "wallTime": 1_800_000_000 + run * 100, "request": {"url": URL}}}]
    rows = []
    assets = (
            ("index.wasm", 6_000_000, 24_000_000, 4000),
            ("index-lite.pck", 10_000_000, 11_000_000, 7000))
    if bootstrap:
        assets += (("bootstrap.pck", 4096, 12288, 800),)  # Synthetic compressed/raw sizes.
    for index, (file, body, decoded, end) in enumerate(assets):
        url = URL.split("index.html")[0] + file
        request_id = f"{run}.{index}"
        rows.append({"file": file, "encodedBodyBytes": body, "decodedBodyBytes": decoded,
                     "transferBytes": body + 300, "startMs": 150 + index,
                     "responseStartMs": 240 + index, "responseEndMs": end})
        events.extend([
            {"method": "Network.requestWillBeSent", "params": {
                "requestId": request_id, "loaderId": loader, "type": "Fetch",
                "timestamp": stamp + .15 + index / 1000, "request": {"url": url}}},
            {"method": "Network.responseReceived", "params": {
                "requestId": request_id, "loaderId": loader, "timestamp": stamp + .24 + index / 1000,
                "response": {"url": url, "status": 200, "fromDiskCache": False,
                             "fromServiceWorker": False, "fromPrefetchCache": False,
                             "headers": {"content-length": str(body)}}}},
            {"method": "Network.loadingFinished", "params": {
                "requestId": request_id, "timestamp": stamp + end / 1000,
                "encodedDataLength": body + 240}},
        ])
    dataset = {"navigationReadyMs": str(core), "coreReadyMs": str(core), "loadHiddenMs": "0",
               "loadMs": str(core - 100), "loadStartedPageMs": "100", "weatherClock": "0.000",
               "nightBlend": "0.000", "motion": "false", "transitioning": "false", "textureQuality": "lite",
               "detailStatus": "complete" if complete else "loading", "detailChunksTotal": "6",
               "detailChunksApplied": "6" if complete else "0", "detailsStartedPageMs": str(core + 16),
               "startupAuditEnabled": "false", "startupAuditMs": "0", "resourceTiming": rows}
    if complete:
        dataset["detailsCompletePageMs"] = "24000"
    if bootstrap:
        dataset["engineBootstrap"] = "bootstrap.pck"
    return {"conditions": {"downloadMbps": 20, "uploadMbps": 5, "latencyMs": 80,
                           "httpCacheBypass": True, "gpuShaderCache": "not cleared"},
            "data": {"canvas": [2560, 1440], "dpr": 1, "visibility": "visible",
                     "url": URL, "isCoreReady": True, "data": dataset},
            "events": {"hasMore": False, "truncated": False, "events": events}}


def event(record, method, index=0):
    return [entry["params"] for entry in record["events"]["events"] if entry["method"] == method][index]


def add_event(record, method, params):
    record["events"]["events"].append({"method": method, "params": params})


def deferred_response_fixture(delay=0.000807):
    """Synthetic response notification delay, with unchanged network/ready clocks."""
    record = fixture(bootstrap=True)
    request = event(record, "Network.requestWillBeSent", 3)
    response = event(record, "Network.responseReceived", 2)
    finish = event(record, "Network.loadingFinished", 2)
    response["timestamp"] = finish["timestamp"] + delay
    response["response"]["timing"] = {"requestTime": request["timestamp"], "receiveHeadersEnd": 80}
    return record


def png_header(width, height):
    ihdr = b"IHDR" + struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + ihdr + struct.pack(">I", zlib.crc32(ihdr))


class ProgressiveEvidenceTests(unittest.TestCase):
    def refused(self, record, expected):
        result = analyze_sample(record)
        self.assertEqual(result["status"], "REFUSED", result)
        self.assertFalse(result["coreFirstLoadPass"])
        self.assertIn(expected, " ".join(result["reasons"]))
        return result

    def test_good_sample_is_core_only_and_keeps_not_cleared_gpu_cache(self):
        record = fixture()
        record["data"]["dpr"] = 1.0000000298023224  # Observed native bridge representation.
        record["data"]["data"]["resourceTiming"] = json.dumps(record["data"]["data"]["resourceTiming"])
        result = analyze_sample(record)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["timings"]["coreReadyMs"], 9500)
        self.assertEqual(result["details"]["status"], "loading")
        self.assertIsNone(result["details"]["completePageMs"])
        self.assertIsNone(result["details"]["within10s"])
        self.assertEqual(result["conditions"]["gpuShaderCache"], "not cleared")
        self.assertEqual(result["capture"]["canvas"], [2560, 1440])
        self.assertEqual(result["capture"]["visibility"], "visible")
        self.assertFalse(result["physicalPresentationVerified"])
        self.assertEqual(result["network"]["corePayloadEncodedBodyBytes"], 16_000_000)

    def test_three_distinct_runs_all_must_pass_inclusive_boundary_not_average(self):
        samples = [analyze_sample(fixture(run, core=core)) for run, core in ((1, 9000), (2, 9500), (3, 10000))]
        report = summarize(samples)
        self.assertTrue(report["bounded3of3"], report)
        self.assertFalse(report["productionSla"])
        self.assertIn("not a production SLA", report["claim"])
        samples[-1] = analyze_sample(fixture(3, core=10001))
        self.assertEqual(samples[-1]["status"], "OVER_BUDGET")
        self.assertFalse(summarize(samples)["bounded3of3"])

    def test_duplicate_missing_extra_or_different_conditions_are_not_three_of_three(self):
        good = [analyze_sample(fixture(n)) for n in (1, 2, 3)]
        for samples in ([], good[:1], good[:2], good + [analyze_sample(fixture(4))],
                        [good[0], copy.deepcopy(good[0]), copy.deepcopy(good[0])]):
            with self.subTest(count=len(samples)):
                self.assertFalse(summarize(samples)["bounded3of3"])
        changed = fixture(3)
        changed["conditions"]["gpuShaderCache"] = "cleared before this navigation"
        self.assertFalse(summarize(good[:2] + [analyze_sample(changed)])["bounded3of3"])
        changed = fixture(3)
        rt = changed["data"]["data"]["resourceTiming"][0]
        rt["encodedBodyBytes"] += 1
        rt["transferBytes"] += 1
        event(changed, "Network.responseReceived")["response"]["headers"]["content-length"] = str(rt["encodedBodyBytes"])
        event(changed, "Network.loadingFinished")["encodedDataLength"] += 1
        self.assertEqual(analyze_sample(changed)["status"], "PASS")
        self.assertFalse(summarize(good[:2] + [analyze_sample(changed)])["bounded3of3"])

    def test_conditions_must_be_explicit_exact_and_gpu_cache_not_inferred(self):
        for key, value in (("downloadMbps", 200), ("uploadMbps", 20), ("latencyMs", 0),
                           ("httpCacheBypass", "true"), ("gpuShaderCache", "")):
            record = fixture()
            record["conditions"][key] = value
            with self.subTest(key=key):
                self.refused(record, key)
        record = fixture()
        del record["conditions"]["gpuShaderCache"]
        self.refused(record, "gpuShaderCache")

    def test_hidden_wrong_canvas_dpr_and_scene_clock_are_refused(self):
        for key, value in (("canvas", [1280, 720]), ("dpr", 2), ("visibility", "hidden")):
            record = fixture()
            record["data"][key] = value
            with self.subTest(key=key):
                self.refused(record, {"canvas": "canvas", "dpr": "DPR", "visibility": "visibility"}[key])
        for key, value in (("loadHiddenMs", ".001"), ("weatherClock", "2.0"), ("nightBlend", "1"),
                           ("motion", "true"), ("transitioning", "true")):
            record = fixture()
            record["data"]["data"][key] = value
            with self.subTest(key=key):
                self.refused(record, "hidden-tab" if key == "loadHiddenMs" else key)

    def test_ready_boolean_never_replaces_mandatory_times_and_conflicts_fail(self):
        for key in ("navigationReadyMs", "coreReadyMs", "loadHiddenMs"):
            record = fixture()
            del record["data"]["data"][key]
            with self.subTest(key=key):
                self.refused(record, key)
        record = fixture()
        del record["data"]["isCoreReady"]
        self.refused(record, "isCoreReady")
        record["data"]["data"]["isCoreReady"] = "true"
        self.assertEqual(analyze_sample(record)["status"], "PASS")
        record["data"]["isCoreReady"] = False
        self.refused(record, "isCoreReady")

    def test_bad_clock_origins_and_nonfinite_values_do_not_get_repaired(self):
        for key, value in (("coreReadyMs", "9000"), ("loadMs", "600"),
                           ("navigationReadyMs", "NaN"), ("coreReadyMs", True)):
            record = fixture()
            record["data"]["data"][key] = value
            with self.subTest(key=key):
                self.refused(record, "clock" if key == "loadMs" else key)
        record = fixture()
        record["data"]["data"]["loadMs"] = "9399"  # Independent integer rounding only.
        self.assertEqual(analyze_sample(record)["status"], "PASS")
        del record["data"]["data"]["loadStartedPageMs"]
        self.refused(record, "loadStartedPageMs")

    def test_incomplete_event_log_and_console_only_capture_refused(self):
        for key in ("hasMore", "truncated"):
            record = fixture()
            record["events"][key] = True
            self.refused(record, "incomplete")
        record = fixture()
        record["events"]["events"] = [{"method": "Runtime.consoleAPICalled", "params": {"type": "log"}}]
        self.refused(record, "navigation Document")
        record = fixture()
        record["events"] = record["events"]["events"]
        self.refused(record, "eventsComplete")
        record["eventsComplete"] = True
        self.assertEqual(analyze_sample(record)["status"], "PASS")

    def test_runtime_exception_and_console_error_anywhere_in_capture_refused(self):
        for method, params, expected in (
                ("Runtime.exceptionThrown", {"exceptionDetails": {"text": "synthetic"}}, "Runtime.exceptionThrown"),
                ("Runtime.consoleAPICalled", {"type": "error"}, "console error"),
                ("Log.entryAdded", {"entry": {"level": "error", "text": "synthetic"}}, "Log error")):
            record = fixture(complete=True)
            add_event(record, method, params)
            self.refused(record, expected)
        record = fixture()
        add_event(record, "Log.entryAdded", {"entry": {"level": "warning", "text": "warning, not an exception"}})
        self.assertEqual(analyze_sample(record)["status"], "PASS")
        self.assertEqual(analyze_sample(record)["runtimeWarningEvents"], 1)

    def test_missing_duplicate_or_mismatched_response_finish_pairs_fail(self):
        for operation in ("missing", "duplicate", "wrong-id", "wrong-url", "wrong-loader"):
            record = fixture()
            response = event(record, "Network.responseReceived")
            if operation == "missing":
                record["events"]["events"] = [e for e in record["events"]["events"] if e["params"] is not response]
            elif operation == "duplicate":
                add_event(record, "Network.responseReceived", copy.deepcopy(response))
            elif operation == "wrong-id":
                event(record, "Network.loadingFinished")["requestId"] = "other"
            elif operation == "wrong-url":
                response["response"]["url"] += "?other-body"
            else:
                response["loaderId"] = "other"
            with self.subTest(operation=operation):
                self.refused(record, "index.wasm")

    def test_duplicate_request_unexpected_quality_pack_and_wrong_origin_fail(self):
        record = fixture()
        add_event(record, "Network.requestWillBeSent", copy.deepcopy(event(record, "Network.requestWillBeSent", 1)))
        self.refused(record, "exactly one request")
        for file in ("index.pck", "index-balanced.pck", "https://other.test/index.wasm"):
            record = fixture()
            request = copy.deepcopy(event(record, "Network.requestWillBeSent", 2))
            request["request"]["url"] = file if file.startswith("https") else URL.split("index.html")[0] + file
            add_event(record, "Network.requestWillBeSent", request)
            self.refused(record, "unexpected")

    def test_real_body_not_headers_or_cached_body_metadata_required(self):
        for field, value in (("transferBytes", 300), ("encodedBodyBytes", 0), ("decodedBodyBytes", 0)):
            record = fixture()
            record["data"]["data"]["resourceTiming"][0][field] = value
            self.refused(record, "index.wasm")
        record = fixture()
        event(record, "Network.loadingFinished")["encodedDataLength"] = 300
        self.refused(record, "300-byte")
        record = fixture()
        del record["data"]["data"]["resourceTiming"]
        self.refused(record, "resourceTiming")
        record = fixture()
        del record["data"]["data"]["resourceTiming"][0]["encodedBodyBytes"]
        self.refused(record, "encodedBodyBytes")

    def test_all_cache_sources_revalidation_and_partial_http_refused(self):
        for flag in ("fromDiskCache", "fromServiceWorker", "fromPrefetchCache"):
            record = fixture()
            event(record, "Network.responseReceived")["response"][flag] = True
            self.refused(record, "cached/service-worker")
        for status in (206, 304, 404):
            record = fixture()
            event(record, "Network.responseReceived")["response"]["status"] = status
            self.refused(record, "HTTP 200")
        for method, params in (
                ("Network.requestServedFromCache", {"requestId": "1.0"}),
                ("Network.loadingFailed", {"requestId": "1.0"}),
                ("Network.responseReceivedExtraInfo", {"requestId": "1.0", "statusCode": 304})):
            record = fixture()
            add_event(record, method, params)
            self.refused(record, "index.wasm")

    def test_resource_end_and_response_bytes_are_checked_without_clock_mixing(self):
        record = fixture()
        record["data"]["data"]["resourceTiming"][0]["responseEndMs"] = 9501
        self.refused(record, "core-ready precedes")
        record = fixture()
        event(record, "Network.responseReceived")["response"]["headers"]["content-length"] = "10"
        self.refused(record, "Content-Length")
        record = fixture()
        event(record, "Network.loadingFinished")["timestamp"] = 1
        self.refused(record, "CDP timestamps")
        record = fixture()
        record["data"]["data"]["resourceTiming"].append(copy.deepcopy(record["data"]["data"]["resourceTiming"][0]))
        self.refused(record, "ResourceTiming counterpart")

    def test_detail_completion_is_separate_and_requires_applied_counts(self):
        record = fixture(complete=True)
        result = analyze_sample(record)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["details"]["completePageMs"], 24000)
        self.assertFalse(result["details"]["within10s"])
        del record["data"]["data"]["detailsCompletePageMs"]
        self.refused(record, "completion timestamp")
        record = fixture(complete=True)
        record["data"]["data"]["detailChunksApplied"] = "5"
        self.refused(record, "all chunks applied")
        record = fixture()
        record["data"]["data"]["detailsCompletePageMs"] = "24000"
        self.refused(record, "pending details contradict")

    def test_detail_requests_allowed_but_failure_never_approves_broken_run(self):
        record = fixture()
        request = copy.deepcopy(event(record, "Network.requestWillBeSent", 2))
        request["requestId"] = "1.detail"
        request["request"]["url"] = URL.split("index.html")[0] + "detail-0-abcdef123456.pck"
        request["timestamp"] += 10
        add_event(record, "Network.requestWillBeSent", request)  # Still in flight after core.
        self.assertEqual(analyze_sample(record)["status"], "PASS")
        record["data"]["data"]["detailStatus"] = "error"
        result = self.refused(record, "detailStatus:error")
        self.assertEqual(result["timings"]["coreReadyMs"], 9500)

    def test_diagnostic_or_runtime_canvas_mismatch_is_not_benchmark(self):
        for key, value in (("startupTrace", "{}"), ("startupAuditEnabled", "true"),
                           ("startupAuditCanvasWidth", "1280"), ("startupAuditDpr", "2")):
            record = fixture()
            record["data"]["data"][key] = value
            self.refused(record, {"startupTrace": "diagnostic", "startupAuditEnabled": "diagnostic",
                                  "startupAuditCanvasWidth": "startupAuditCanvasWidth", "startupAuditDpr": "DPR"}[key])
        record = fixture()
        record["data"]["url"] += "&startup_trace=1"
        self.refused(record, "diagnostic URL")

    def test_root_cache_probe_alone_is_diagnostic_even_with_valid_bootstrap_evidence(self):
        for query in ("root_cache_probe=1", "root_cache_probe=%31",
                      "root_cache_probe=0&root_cache_probe=1"):
            with self.subTest(query=query):
                record = fixture(bootstrap=True)
                record["data"]["url"] += "&" + query
                event(record, "Network.requestWillBeSent")["request"]["url"] = record["data"]["url"]
                self.refused(record, "root_cache_probe: diagnostic URL")

    def test_disabled_or_absent_root_probe_keeps_exact_timing_boundary(self):
        for suffix in ("", "&root_cache_probe=0"):
            for core in (10000, 10001):
                with self.subTest(suffix=suffix, core=core):
                    record = fixture(core=core, bootstrap=True)
                    record["data"]["url"] += suffix
                    event(record, "Network.requestWillBeSent")["request"]["url"] = record["data"]["url"]
                    result = analyze_sample(record)
                    self.assertEqual(result["status"], "PASS" if core == 10000 else "OVER_BUDGET", result)
                    self.assertEqual(result["coreFirstLoadPass"], core == 10000)
                    self.assertEqual(result["timings"]["coreReadyMs"], core)

    def test_optional_png_references_check_file_header_not_claim_visual_acceptance(self):
        with tempfile.TemporaryDirectory(prefix="v135-evidence-test-") as directory:
            root = Path(directory)
            png = root / "synthetic-header.png"
            png.write_bytes(png_header(2560, 1440))
            record = fixture()
            record["screenshots"] = [png.name]
            result = analyze_sample(record, base=root)
            self.assertEqual(result["status"], "PASS", result)
            self.assertEqual(result["screenshots"][0]["dimensions"], [2560, 1440])
            self.assertIn("no pixel/content", result["screenshots"][0]["verification"])
            self.assertFalse(result["physicalPresentationVerified"])
            png.write_bytes(png_header(1280, 720))
            self.assertIn("not QHD", " ".join(analyze_sample(record, base=root)["reasons"]))
            png.write_bytes(png_header(2560, 1440)[:-1] + b"\x00")
            self.assertEqual(analyze_sample(record, base=root)["status"], "REFUSED")

    def test_invalid_json_and_structures_fail_closed_not_default_to_zero(self):
        for text in ('{"a":1,"a":2}', '{"a":NaN}', "{broken"):
            with self.assertRaises(EvidenceError):
                json_value(text)
        for record in (None, {}, {"conditions": []}, {"conditions": fixture()["conditions"], "data": []}):
            result = analyze_sample(record)
            self.assertEqual(result["status"], "REFUSED")
            self.assertIsNone(result["timings"])
        for request in (None, [], "malformed"):
            record = fixture()
            event(record, "Network.requestWillBeSent")["request"] = request
            self.refused(record, "CDP request")

    def test_cli_new_output_input_hashes_and_no_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="v135-evidence-cli-") as directory:
            root = Path(directory)
            inputs = []
            for run in (1, 2, 3):
                path = root / f"synthetic-{run}.json"
                path.write_text(json.dumps(fixture(run)), encoding="utf-8")
                inputs.append(str(path))
            output = root / "new-summary.json"
            command = [sys.executable, "-B", str(TOOL), *inputs, "--output", str(output)]
            first = subprocess.run(command, capture_output=True, text=True, timeout=15)
            self.assertEqual(first.returncode, 0, first.stderr)
            original = output.read_bytes()
            report = json.loads(original)
            self.assertTrue(report["bounded3of3"])
            self.assertEqual(len(report["samples"][0]["inputSha256"]), 64)
            second = subprocess.run(command, capture_output=True, text=True, timeout=15)
            self.assertEqual(second.returncode, 2)
            self.assertEqual(output.read_bytes(), original)

    def test_bootstrap_is_a_third_required_asset_counted_in_separate_real_transfer_totals(self):
        samples = [analyze_sample(fixture(n, bootstrap=True)) for n in (1, 2, 3)]
        self.assertTrue(summarize(samples)["bounded3of3"])
        network = samples[0]["network"]
        self.assertEqual(network["engineBootstrap"], "bootstrap.pck")
        self.assertEqual([row["file"] for row in network["resources"]], ["index.wasm", "index-lite.pck", "bootstrap.pck"])
        self.assertEqual(network["corePayloadEncodedBodyBytes"], 16_004_096)
        self.assertEqual(network["requiredInitialResourceTimingTransferBytes"], 16_004_996)
        self.assertEqual(network["requiredInitialCdpCompletedTransferBytes"], 16_004_816)
        self.assertEqual(samples[0]["timings"]["coreReadyMs"], 9500)
        self.assertIsNone(samples[0]["details"]["completePageMs"])
        self.assertFalse(samples[0]["physicalPresentationVerified"])
        record = fixture(bootstrap=True)
        record["data"]["data"]["engineBootstrapBytes"] = "12288"
        record["data"]["data"]["resourceTiming"] = json.dumps(record["data"]["data"]["resourceTiming"])
        self.assertEqual(analyze_sample(record)["status"], "PASS")

    def test_bootstrap_marker_is_not_a_general_extra_pack_permission(self):
        for value in (None, "", True, "../bootstrap.pck", "index-balanced.pck", "Bootstrap.pck"):
            record = fixture(bootstrap=True)
            record["data"]["data"]["engineBootstrap"] = value
            with self.subTest(value=value):
                self.refused(record, "engineBootstrap")
        record = fixture(bootstrap=True)
        del record["data"]["data"]["engineBootstrap"]
        self.refused(record, "unexpected")
        for file in ("index.pck", "index-balanced.pck", "other.pck", "bootstrap.pck?cached=1", "../bootstrap.pck"):
            record = fixture(bootstrap=True)
            request = event(record, "Network.requestWillBeSent", 3)
            request["request"]["url"] = URL.split("index.html")[0] + file
            self.refused(record, "unexpected")

    def test_bootstrap_requires_one_complete_request_response_finish_and_rt_pair(self):
        for method in ("Network.requestWillBeSent", "Network.responseReceived", "Network.loadingFinished"):
            record = fixture(bootstrap=True)
            events = record["events"]["events"]
            events[:] = [row for row in events if not (row["method"] == method and row["params"].get("requestId") == "1.2")]
            with self.subTest(method=method):
                self.refused(record, "bootstrap.pck")
        record = fixture(bootstrap=True)
        record["data"]["data"]["resourceTiming"].pop()
        self.refused(record, "bootstrap.pck: require exact ResourceTiming")
        record = fixture(bootstrap=True)
        add_event(record, "Network.requestWillBeSent", copy.deepcopy(event(record, "Network.requestWillBeSent", 3)))
        self.refused(record, "bootstrap.pck: require exactly one request")
        record = fixture()
        record["data"]["data"]["engineBootstrap"] = "bootstrap.pck"
        self.refused(record, "bootstrap.pck: require exactly one request")

    def test_bootstrap_cannot_use_cache_headers_only_or_inconsistent_sizes(self):
        for key, value in (("status", 304), ("status", 206), ("fromDiskCache", True), ("fromServiceWorker", True)):
            record = fixture(bootstrap=True)
            event(record, "Network.responseReceived", 2)["response"][key] = value
            self.refused(record, "bootstrap.pck")
        for field, value in (("encodedBodyBytes", 0), ("decodedBodyBytes", 0), ("transferBytes", 300)):
            record = fixture(bootstrap=True)
            record["data"]["data"]["resourceTiming"][2][field] = value
            self.refused(record, "bootstrap.pck")
        record = fixture(bootstrap=True)
        event(record, "Network.loadingFinished", 2)["encodedDataLength"] = 300
        self.refused(record, "bootstrap.pck")
        record = fixture(bootstrap=True)
        event(record, "Network.responseReceived", 2)["response"]["headers"]["content-length"] = "12288"
        self.refused(record, "Content-Length disagrees with encoded body")
        record = fixture(bootstrap=True)
        record["data"]["data"]["engineBootstrapBytes"] = 4096
        self.refused(record, "decoded size differs")

    def test_bootstrap_finished_does_not_replace_real_core_resource_or_ready_gate(self):
        record = fixture(bootstrap=True)
        record["events"]["events"] = [row for row in record["events"]["events"]
                                       if row["params"].get("requestId") != "1.1"]
        self.refused(record, "index-lite.pck: require exactly one request")
        record = fixture(core=900, bootstrap=True)  # Bootstrap ended at 800; actual core PCK ends at 7000.
        self.refused(record, "core-ready precedes required resource end")
        record = fixture(bootstrap=True)
        del record["data"]["data"]["coreReadyMs"]
        record["data"]["data"]["bootstrapStartedMs"] = "800"
        self.refused(record, "coreReadyMs")
        record = fixture(bootstrap=True)
        record["data"]["data"]["resourceTiming"][2]["responseEndMs"] = 9600
        self.refused(record, "bootstrap.pck: core-ready precedes")
        record = fixture(bootstrap=True)
        add_event(record, "Runtime.exceptionThrown", {"exceptionDetails": {"text": "core mount failed"}})
        self.refused(record, "Runtime.exceptionThrown")

    def test_three_run_cohort_cannot_mix_bootstrap_presence_or_payload_sizes(self):
        samples = [analyze_sample(fixture(n, bootstrap=True)) for n in (1, 2, 3)]
        self.assertTrue(summarize(samples)["bounded3of3"])
        self.assertFalse(summarize(samples[:2] + [analyze_sample(fixture(3))])["bounded3of3"])
        changed = fixture(3, bootstrap=True)
        changed["data"]["data"]["resourceTiming"][2]["decodedBodyBytes"] += 1
        result = analyze_sample(changed)
        self.assertEqual(result["status"], "PASS")  # Without a stage size pin this is reported, not authenticated.
        self.assertFalse(summarize(samples[:2] + [result])["bounded3of3"])

    def test_actual_v140_deferred_response_is_over_budget_not_repaired_to_pass(self):
        raw = V140_RECORD.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), V140_SHA256)
        record = json_value(raw.decode("utf-8"))
        boot = [row["params"] for row in record["events"]["events"]
                if row["method"] == "Network.responseReceived" and row["params"].get("requestId") == "32348.748"][0]
        self.assertEqual(boot["timestamp"], 59361.499892)
        self.assertEqual(boot["response"]["timing"]["requestTime"], 59361.384954)
        self.assertEqual(boot["response"]["timing"]["receiveHeadersEnd"], 112.718)
        result = analyze_sample(record, base=V140_RECORD.parent)
        self.assertEqual(result["status"], "OVER_BUDGET", result)
        self.assertFalse(result["coreFirstLoadPass"])
        self.assertEqual(result["timings"]["coreReadyMs"], 12192)
        self.assertEqual(result["timings"]["navigationReadyMs"], 12192)
        self.assertEqual(result["details"]["completePageMs"], 29235)
        self.assertEqual(result["network"]["corePayloadEncodedBodyBytes"], 13_018_518)
        bootstrap = next(row for row in result["network"]["resources"] if row["file"] == "bootstrap.pck")
        self.assertEqual(bootstrap["encodedBodyBytes"], 4070)
        self.assertEqual(bootstrap["cdpCompletedTransferBytes"], 4478)
        self.assertFalse(summarize([result])["bounded3of3"])
        self.assertFalse(result["physicalPresentationVerified"])

    def test_deferred_notification_uses_evidence_not_a_delay_tolerance_or_new_clock(self):
        for delay in (0.000807, 3.0):
            record = deferred_response_fixture(delay)
            before = copy.deepcopy(record)
            result = analyze_sample(record)
            self.assertEqual(result["status"], "PASS", result)
            self.assertEqual(result["timings"]["coreReadyMs"], 9500)
            self.assertEqual(record, before, "never sort/repair the input timestamps")
        for method, index in (("Network.requestWillBeSent", 3), ("Network.loadingFinished", 2)):
            record = deferred_response_fixture()
            boundary = event(record, method, index)["timestamp"]
            event(record, "Network.responseReceived", 2)["response"]["timing"] = {
                "requestTime": boundary, "receiveHeadersEnd": 0}
            self.assertEqual(analyze_sample(record)["status"], "PASS", "inclusive exact boundary")
        ordinary = fixture(bootstrap=True)  # Original ordered path needs no extra timing fields.
        self.assertEqual(analyze_sample(ordinary)["status"], "PASS")

    def test_deferred_response_requires_finite_nonnegative_complete_header_evidence(self):
        for timing in (None, {}, [], {"requestTime": 1100.2}, {"receiveHeadersEnd": 80},
                       {"requestTime": float("inf"), "receiveHeadersEnd": 80},
                       {"requestTime": 1100.2, "receiveHeadersEnd": -1},
                       {"requestTime": 1100.2, "receiveHeadersEnd": float("nan")}):
            record = deferred_response_fixture()
            event(record, "Network.responseReceived", 2)["response"]["timing"] = timing
            with self.subTest(timing=timing):
                self.refused(record, "bootstrap.pck")
        record = deferred_response_fixture()
        del event(record, "Network.responseReceived", 2)["response"]["timing"]
        self.refused(record, "header timing evidence")

    def test_deferred_response_rejects_headers_outside_request_finish_without_epsilon(self):
        for method, index, direction in (("Network.requestWillBeSent", 3, -math.inf),
                                         ("Network.loadingFinished", 2, math.inf)):
            record = deferred_response_fixture()
            boundary = event(record, method, index)["timestamp"]
            # Even one representable step outside the bound fails; no 1ms allowance.
            event(record, "Network.responseReceived", 2)["response"]["timing"] = {
                "requestTime": math.nextafter(boundary, direction), "receiveHeadersEnd": 0}
            self.refused(record, "headers end outside request/finish")

    def test_deferred_response_cannot_bypass_request_loader_or_url_identity(self):
        for method, index, key, value, reason in (
                ("Network.responseReceived", 2, "requestId", "other-run", "exact responseReceived/loadingFinished pair"),
                ("Network.loadingFinished", 2, "requestId", "other-run", "exact responseReceived/loadingFinished pair"),
                ("Network.requestWillBeSent", 3, "loaderId", "other-run", "another navigation"),
                ("Network.responseReceived", 2, "loaderId", "other-run", "response loader mismatch")):
            record = deferred_response_fixture()
            event(record, method, index)[key] = value
            self.refused(record, reason)
        record = deferred_response_fixture()
        event(record, "Network.responseReceived", 2)["response"]["url"] = "http://127.0.0.1:4231/other/bootstrap.pck"
        self.refused(record, "exact URL")

    def test_deferred_response_keeps_body_cache_visibility_runtime_and_core_gates(self):
        record = deferred_response_fixture()
        event(record, "Network.loadingFinished", 2)["encodedDataLength"] = 300
        self.refused(record, "300-byte-only")
        record = deferred_response_fixture()
        event(record, "Network.responseReceived", 2)["response"]["fromDiskCache"] = True
        self.refused(record, "cached/service-worker")
        record = deferred_response_fixture()
        record["data"]["data"]["loadHiddenMs"] = "1"
        self.refused(record, "hidden-tab")
        record = deferred_response_fixture()
        record["data"]["data"]["resourceTiming"][2]["responseEndMs"] = 9501
        self.refused(record, "core-ready precedes")
        record = deferred_response_fixture()
        add_event(record, "Runtime.exceptionThrown", {"exceptionDetails": {"text": "real failure"}})
        self.refused(record, "Runtime.exceptionThrown")


if __name__ == "__main__":
    unittest.main()
