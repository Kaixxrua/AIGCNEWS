"""Read-only v135 evidence summary; no browser, network, native run or timing probe.

CLI: python -B report_progressive_startup_v135.py run1.json run2.json run3.json
     [--output NEW-report.json]  (never overwrites an existing output)

One input per navigation:
  conditions: {downloadMbps:20, uploadMbps:5, latencyMs:80,
               httpCacheBypass:true, gpuShaderCache:"not cleared"}
  data: {canvas:[2560,1440], dpr:1, visibility:"visible", url:HTTP_URL,
         isCoreReady:true, data:CANVAS_DATASET}
  events: {events:[CDP_EVENTS], hasMore:false, truncated:false}
    A flat events list instead requires eventsComplete:true.
  screenshots: [LOCAL_PNG_PATH, ...]  (optional, relative to the input JSON)

Required canvas dataset: navigationReadyMs, coreReadyMs, loadHiddenMs,
weatherClock:0, nightBlend:0, motion:false, transitioning:false,
textureQuality:"lite", detailStatus, resourceTiming. DOM numeric/boolean strings
are accepted. resourceTiming is the host's JSON string or its decoded array.
isCoreReady is an actual collected DOM-ready predicate, not a replacement clock.
It may alternatively be recorded in the dataset; conflicting copies are refused.

Both navigation-relative ready clocks must agree (the current host copies one).
If loadMs/loadStartedPageMs are supplied, both are required and their sum must
agree within 2 ms of independent integer rounding; no timing is subtracted to
manufacture a faster result. detailsCompletePageMs is separate, never inferred.
Detail completion requires matching positive detailChunksTotal/ChunksApplied.

Capture CDP Network AND Runtime/Log before navigation, through the DOM snapshot.
Require one navigation request and one exact request/200-response/finished chain
for each same-directory index.wasm and index-lite.pck, plus their ResourceTiming
body/transfer evidence. HTTP header overhead differs between CDP and Resource
Timing: their totals are NOT equated. Additional detail-N-12hex.pck requests are
allowed, not other quality packs/engines. Scope the supplied log to one run.
Three samples must also agree on URL, reported payload sizes and cache conditions.
If dataset.engineBootstrap is present it must be exactly "bootstrap.pck": a third
same-directory request/200/finished/ResourceTiming pair becomes mandatory, with
the same noncached body/size checks and included in required initial transfer.
Optional dataset.engineBootstrapBytes is the stage's raw file size and must equal
its decodedBodyBytes. Never supply a guessed size. Without it the size evidence
is reported RT/CDP/header consistency, not independent artifact authentication.
Bootstrap completion never replaces either real core-ready clock or core PCK.
Required-initial transfer sums exclude HTML/JS and later/inflight detail traffic;
they are not total page bandwidth. RT and CDP totals remain separate measurements.
CDP response notifications can be timestamped after a recorded network finish.
Only that reversed pair may instead use the same response's timing.requestTime
+ timing.receiveHeadersEnd/1000, bounded inclusively by request and finish.
Missing/invalid header evidence still refuses it. No timestamp is adjusted and
no millisecond tolerance is applied; the ordinary ordered path is unchanged.

PASS is a bounded, recorded DOM core-readiness result, not a physical-present or
production-SLA claim. PNG checks read IHDR dimensions only, not scene content.
HTTP bypass is not a cleared GPU/driver shader cache. Inputs are evidence records,
not cryptographic proof that a harness, GPU presentation or live scene is honest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import sys
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit
import zlib


LIMIT_MS = 10_000
CORE_FILES = ("index.wasm", "index-lite.pck")
BOOTSTRAP_FILE = "bootstrap.pck"
DETAIL_FILE = re.compile(r"detail-\d+-[0-9a-f]{12}\.pck\Z")
LIMITATIONS = [
    "DOM real-ready predicate/timestamps are recorded evidence, not GPU physical-presentation proof; two RAFs alone do not prove presentation.",
    "HTTP-cache bypass does not clear the GPU/driver shader cache; cache state is reported as supplied.",
    "Network identity is exact URL/request pairing and reported body sizes, not an independently hashed downloaded payload.",
    "Recorded shaping conditions are not independently re-applied or verified by this offline reader.",
    "CDP logs are checked as supplied; the collector must enable Network/Runtime/Log for the entire navigation-to-snapshot interval.",
    "Pending details are permitted for core timing, but are not evidence of eventual full-scene completion.",
    "Three bounded samples are not a production SLA or a guarantee for every device/network.",
]


class EvidenceError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise EvidenceError(message)


def number(value, label, *, positive=False):
    require(not isinstance(value, bool) and isinstance(value, (str, int, float)), f"{label}: missing/non-numeric")
    try:
        result = float(value)
    except (ValueError, OverflowError):
        raise EvidenceError(f"{label}: invalid number") from None
    require(math.isfinite(result) and result >= 0 and (not positive or result > 0), f"{label}: invalid range")
    return result


def count(value, label, *, positive=False):
    result = number(value, label, positive=positive)
    require(result.is_integer() and result <= 2**53 - 1, f"{label}: non-safe-integer")
    return int(result)


def mapping(value, label):
    require(isinstance(value, dict), f"{label}: expected object")
    return value


def true(value):
    return value is True or value == "true"


def false(value):
    return value is False or value == "false"


def json_value(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def nonfinite(value):
        raise EvidenceError(f"non-finite JSON constant: {value}")

    try:
        return json.loads(text, object_pairs_hook=unique, parse_constant=nonfinite)
    except (ValueError, UnicodeError) as exc:
        raise EvidenceError(f"invalid JSON: {exc}") from None


def conditions_of(record):
    conditions = mapping(record.get("conditions"), "conditions")
    for key, expected in (("downloadMbps", 20), ("uploadMbps", 5), ("latencyMs", 80)):
        require(type(conditions.get(key)) in (int, float) and conditions[key] == expected, f"conditions.{key}: require {expected}")
    require(conditions.get("httpCacheBypass") is True, "conditions.httpCacheBypass must be true")
    require(isinstance(conditions.get("gpuShaderCache"), str) and conditions["gpuShaderCache"].strip(),
            "conditions.gpuShaderCache: explicit state required; HTTP bypass says nothing about GPU cache")
    return {key: conditions[key] for key in ("downloadMbps", "uploadMbps", "latencyMs", "httpCacheBypass", "gpuShaderCache")}


def dom_of(record):
    dom = mapping(record.get("data"), "data")
    dataset = mapping(dom.get("data"), "data.data")
    require(dom.get("canvas") == [2560, 1440], "actual backing canvas must be 2560x1440")
    require(abs(number(dom.get("dpr"), "DPR", positive=True) - 1) <= 1e-6, "DPR must be 1 (float representation tolerance only)")
    require(dom.get("visibility") == "visible", "snapshot visibility must be visible")
    require(number(dataset.get("loadHiddenMs"), "loadHiddenMs") == 0, "hidden-tab time is not a foreground benchmark")
    for key in ("weatherClock", "nightBlend"):
        require(number(dataset.get(key), key) == 0, f"{key}: require matched day/clock zero")
    for key in ("motion", "transitioning"):
        require(false(dataset.get(key)), f"{key}: require false for matched capture controls")
    require(dataset.get("textureQuality") == "lite", "require the progressive lite tier")
    for key, expected in (("startupAuditCanvasWidth", 2560), ("startupAuditCanvasHeight", 1440), ("startupAuditMs", 0)):
        if key in dataset:
            require(number(dataset[key], key) == expected, f"{key}: mismatched runtime evidence")
    if "startupAuditDpr" in dataset:
        require(abs(number(dataset["startupAuditDpr"], "startupAuditDpr") - number(dom["dpr"], "DPR")) <= 1e-6,
                "runtime DPR differs from backing-canvas capture")
    if "startupAuditEnabled" in dataset:
        require(false(dataset["startupAuditEnabled"]), "startup audit enabled: diagnostic run")
    require("startupTrace" not in dataset, "diagnostic GL trace is not a final benchmark")
    url = dom.get("url")
    require(isinstance(url, str), "snapshot URL required")
    split = urlsplit(url)
    require(split.scheme in ("http", "https") and split.netloc, "require actual HTTP(S) snapshot URL")
    query = parse_qs(split.query, keep_blank_values=True)
    for key in ("startup_trace", "startup_audit", "startup_profile", "root_cache_probe"):
        require(key not in query or query[key] == ["0"], f"{key}: diagnostic URL is not a final benchmark")
    require("quality" not in query or query["quality"] == ["lite"], "URL quality conflicts with lite canvas")
    signals = [obj["isCoreReady"] for obj in (dom, dataset) if "isCoreReady" in obj]
    require(signals and all(true(value) for value in signals), "actual DOM isCoreReady:true required; conflicting signals refused")
    nav = number(dataset.get("navigationReadyMs"), "navigationReadyMs", positive=True)
    core = number(dataset.get("coreReadyMs"), "coreReadyMs", positive=True)
    require(nav == core, "coreReadyMs must equal the host's navigationReadyMs; no faster-clock substitution")
    if "loadMs" in dataset or "loadStartedPageMs" in dataset:
        total = number(dataset.get("loadMs"), "loadMs") + number(dataset.get("loadStartedPageMs"), "loadStartedPageMs")
        require(abs(total - nav) <= 2, "loadMs + loadStartedPageMs disagrees with navigation clock")
    return dom, dataset, urlunsplit((*split[:4], "")), core


def details_of(dataset, core):
    phase = dataset.get("detailStatus")
    require(phase in ("waiting-for-core", "loading", "applying", "retrying", "complete", "error"), "detailStatus missing/unknown")
    start = number(dataset["detailsStartedPageMs"], "detailsStartedPageMs") if "detailsStartedPageMs" in dataset else None
    end = number(dataset["detailsCompletePageMs"], "detailsCompletePageMs") if "detailsCompletePageMs" in dataset else None
    require(start is None or start >= core, "detail start precedes the current host's core-presented gate")
    require(phase != "error", "detailStatus:error; core timing alone cannot approve a broken progressive run")
    if phase == "complete":
        require(end is not None and end >= core and (start is None or end >= start), "complete details require a consistent navigation-relative completion timestamp")
        total = count(dataset.get("detailChunksTotal"), "detailChunksTotal", positive=True)
        require(count(dataset.get("detailChunksApplied"), "detailChunksApplied") == total, "complete details require all chunks applied")
    else:
        require(end is None, "pending details contradict detailsCompletePageMs")
    if "detailChunksApplied" in dataset and "detailChunksTotal" in dataset:
        require(count(dataset["detailChunksApplied"], "detailChunksApplied") <= count(dataset["detailChunksTotal"], "detailChunksTotal", positive=True),
                "applied detail chunks exceed total")
    return {"status": phase, "startedPageMs": start, "completePageMs": end,
            "completionReported": phase == "complete", "within10s": end <= LIMIT_MS if end is not None else None}


def events_of(record):
    envelope = record.get("events")
    if isinstance(envelope, dict):
        require(envelope.get("hasMore") is False and envelope.get("truncated") is False, "CDP log incomplete/truncated or completeness missing")
        events = envelope.get("events")
    else:
        require(record.get("eventsComplete") is True, "flat CDP event list requires eventsComplete:true")
        events = envelope
    require(isinstance(events, list) and events, "CDP event list missing/empty")
    for event in events:
        mapping(event, "CDP event")
        require(isinstance(event.get("method"), str), "CDP method missing")
        params = mapping(event.get("params"), "CDP params")
        method = event["method"]
        require(method != "Runtime.exceptionThrown", "Runtime.exceptionThrown observed")
        require(not (method == "Runtime.consoleAPICalled" and params.get("type") in ("error", "assert")),
                "Runtime console error/assert observed")
        require(not (method == "Log.entryAdded" and mapping(params.get("entry"), "Log entry").get("level") == "error"),
                "browser Log error observed")
    return events


def network_of(events, dataset, url, core):
    def selected(method, request_id=None):
        return [event["params"] for event in events if event["method"] == method
                and (request_id is None or event["params"].get("requestId") == request_id)]

    bootstrap = dataset.get("engineBootstrap")
    require("engineBootstrap" not in dataset or bootstrap == BOOTSTRAP_FILE,
            "engineBootstrap must be exactly bootstrap.pck when present")
    require("engineBootstrapBytes" not in dataset or bootstrap == BOOTSTRAP_FILE,
            "engineBootstrapBytes requires engineBootstrap:bootstrap.pck")
    required_files = CORE_FILES + ((BOOTSTRAP_FILE,) if bootstrap == BOOTSTRAP_FILE else ())
    requests = selected("Network.requestWillBeSent")
    for request in requests:
        mapping(request.get("request"), "CDP request")
    navigation = [p for p in requests if p.get("type") == "Document" and p.get("request", {}).get("url") == url]
    require(len(navigation) == 1, "require exactly one captured navigation Document request matching snapshot URL")
    navigation = navigation[0]
    require(isinstance(navigation.get("loaderId"), str) and navigation["loaderId"] and not navigation.get("redirectResponse"),
            "navigation loader identity missing/redirected")
    wall_time = number(navigation.get("wallTime"), "navigation CDP wallTime", positive=True)
    stamp = number(navigation.get("timestamp"), "navigation CDP timestamp", positive=True)
    raw_timing = dataset.get("resourceTiming")
    rows = json_value(raw_timing) if isinstance(raw_timing, str) else raw_timing
    require(isinstance(rows, list), "host resourceTiming array required (CDP headers alone do not prove body transfer)")
    for row in rows:
        mapping(row, "ResourceTiming row")
        file = row.get("file")
        require(isinstance(file, str) and (file in required_files or DETAIL_FILE.fullmatch(file)),
                "unexpected engine/quality resource in host resourceTiming")
    for request in requests:
        request_url = mapping(request.get("request"), "CDP request").get("url")
        require(isinstance(request_url, str), "CDP request URL missing")
        file = urlsplit(request_url).path.rsplit("/", 1)[-1]
        if file.endswith((".wasm", ".pck")):
            require((file in required_files or DETAIL_FILE.fullmatch(file)) and request_url == urljoin(url, file),
                    "unexpected engine/quality PCK URL; require exact same-stage resources")
            require(request.get("loaderId") == navigation["loaderId"], "resource belongs to another navigation")
    result = []
    for file in required_files:
        exact_url = urljoin(url, file)
        matching = [p for p in requests if p["request"]["url"] == exact_url]
        require(len(matching) == 1, f"{file}: require exactly one request (no duplicates/retries/mixed runs)")
        request = matching[0]
        request_id = request.get("requestId")
        require(isinstance(request_id, str) and request_id, f"{file}: requestId missing")
        require(request.get("loaderId") == navigation["loaderId"] and not request.get("redirectResponse"), f"{file}: navigation mismatch/redirect")
        response_rows = selected("Network.responseReceived", request_id)
        finish_rows = selected("Network.loadingFinished", request_id)
        require(len(response_rows) == len(finish_rows) == 1, f"{file}: require exact responseReceived/loadingFinished pair")
        require(not selected("Network.loadingFailed", request_id) and not selected("Network.requestServedFromCache", request_id),
                f"{file}: failed or cache-served request")
        received, finished = response_rows[0], finish_rows[0]
        response = mapping(received.get("response"), f"{file} response")
        require(response.get("url") == exact_url and response.get("status") == 200, f"{file}: exact URL and full HTTP 200 required")
        require(received.get("loaderId") == navigation["loaderId"], f"{file}: response loader mismatch")
        for key in ("fromDiskCache", "fromServiceWorker", "fromPrefetchCache"):
            require(key not in response or response[key] is False, f"{file}: cached/service-worker response ({key})")
        for extra in selected("Network.responseReceivedExtraInfo", request_id):
            require(extra.get("statusCode") == 200, f"{file}: extra-info status shows revalidation/non-200")
        request_stamp = number(request.get("timestamp"), f"{file} request timestamp")
        response_stamp = number(received.get("timestamp"), f"{file} response timestamp")
        finish_stamp = number(finished.get("timestamp"), f"{file} finish timestamp")
        require(stamp <= request_stamp <= response_stamp and request_stamp <= finish_stamp,
                f"{file}: inverted/mixed CDP timestamps")
        if response_stamp > finish_stamp:
            # Chromium may timestamp responseReceived when notifying Blink,
            # while loadingFinished carries an earlier network completion time.
            # Use actual header timing from this already identity-checked
            # response, never a tolerance, reordered log or repaired ready clock.
            timing = mapping(response.get("timing"), f"{file}: deferred-response header timing evidence")
            headers_end = (number(timing.get("requestTime"), f"{file} timing.requestTime") +
                           number(timing.get("receiveHeadersEnd"), f"{file} timing.receiveHeadersEnd") / 1000)
            require(request_stamp <= headers_end <= finish_stamp,
                    f"{file}: deferred-response headers end outside request/finish timestamps")
        rt = [r for r in rows if r["file"] == file]
        require(len(rt) == 1, f"{file}: require exact ResourceTiming counterpart")
        rt = rt[0]
        body = count(rt.get("encodedBodyBytes"), f"{file} encodedBodyBytes", positive=True)
        decoded = count(rt.get("decodedBodyBytes"), f"{file} decodedBodyBytes", positive=True)
        if file == BOOTSTRAP_FILE and "engineBootstrapBytes" in dataset:
            require(decoded == count(dataset["engineBootstrapBytes"], "engineBootstrapBytes", positive=True),
                    "bootstrap.pck: decoded size differs from stage engineBootstrapBytes")
        transfer = count(rt.get("transferBytes"), f"{file} transferBytes", positive=True)
        cdp_transfer = count(finished.get("encodedDataLength"), f"{file} CDP completed transfer", positive=True)
        require(transfer > 300 and cdp_transfer > 300 and transfer >= body and cdp_transfer >= body,
                f"{file}: missing HTTP body/300-byte-only cache transfer")
        headers = mapping(response.get("headers", {}), f"{file} response headers")
        lengths = [count(v, f"{file} Content-Length") for k, v in headers.items() if k.lower() == "content-length"]
        require(not lengths or all(value == body for value in lengths), f"{file}: response Content-Length disagrees with encoded body")
        start, response_start, end = (number(rt.get(key), f"{file} {key}") for key in ("startMs", "responseStartMs", "responseEndMs"))
        require(start <= response_start <= end <= core, f"{file}: core-ready precedes required resource end or ResourceTiming inverted")
        result.append({"file": file, "url": exact_url, "requestId": request_id, "encodedBodyBytes": body,
                       "decodedBodyBytes": decoded, "resourceTimingTransferBytes": transfer,
                       "cdpCompletedTransferBytes": cdp_transfer, "responseEndPageMs": end})
    return {"navigationIdentity": [navigation["loaderId"], wall_time, stamp], "resources": result,
            "engineBootstrap": bootstrap,
            "corePayloadEncodedBodyBytes": sum(row["encodedBodyBytes"] for row in result),
            "requiredInitialResourceTimingTransferBytes": sum(row["resourceTimingTransferBytes"] for row in result),
            "requiredInitialCdpCompletedTransferBytes": sum(row["cdpCompletedTransferBytes"] for row in result)}


def screenshots_of(record, base):
    references = record.get("screenshots", [])
    require(isinstance(references, list), "screenshots must be a list of local PNG paths")
    results = []
    for reference in references:
        require(isinstance(reference, str) and reference, "screenshot reference must be a local path string")
        path = Path(reference)
        path = path if path.is_absolute() else base / path
        try:
            with path.open("rb") as source:
                header = source.read(33)
                require(len(header) == 33 and header[:16] == b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", f"{reference}: invalid PNG IHDR")
                require(zlib.crc32(header[12:29]) == struct.unpack(">I", header[29:33])[0], f"{reference}: corrupt PNG IHDR")
                size = list(struct.unpack(">II", header[16:24]))
                require(size == [2560, 1440], f"{reference}: actual PNG dimensions are not QHD")
                digest = hashlib.sha256(header)
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
        except OSError as exc:
            raise EvidenceError(f"{reference}: cannot read screenshot ({exc})") from None
        results.append({"path": str(path.resolve()), "dimensions": size, "sha256": digest.hexdigest(),
                        "verification": "IHDR dimensions only; no pixel/content/presented-timestamp analysis"})
    return results


def analyze_sample(record, *, base=Path(".")):
    result = {"status": "REFUSED", "coreFirstLoadPass": False, "isCoreReady": None, "reasons": [],
              "timings": None, "details": None, "network": None, "physicalPresentationVerified": False}
    try:
        mapping(record, "record")
        observed_dom = record.get("data", {})
        if isinstance(observed_dom, dict):
            observed_dataset = observed_dom.get("data", {})
            observed_ready = observed_dom.get("isCoreReady", observed_dataset.get("isCoreReady") if isinstance(observed_dataset, dict) else None)
            result["isCoreReady"] = True if true(observed_ready) else False if false(observed_ready) else None
        result["conditions"] = conditions_of(record)
        dom, dataset, url, core = dom_of(record)
        result.update(isCoreReady=True, url=url)
        result["capture"] = {"canvas": dom["canvas"], "dpr": number(dom["dpr"], "DPR"), "visibility": dom["visibility"],
                             "weatherClock": number(dataset["weatherClock"], "weatherClock"),
                             "nightBlend": number(dataset["nightBlend"], "nightBlend"), "motion": False,
                             "transitioning": False, "textureQuality": dataset["textureQuality"]}
        result["timings"] = {"navigationReadyMs": number(dataset["navigationReadyMs"], "navigationReadyMs"),
                             "coreReadyMs": core, "loadMs": number(dataset["loadMs"], "loadMs") if "loadMs" in dataset else None,
                             "loadHiddenMs": number(dataset["loadHiddenMs"], "loadHiddenMs")}
        result["details"] = details_of(dataset, core)
        events = events_of(record)
        result["runtimeWarningEvents"] = sum(
            event["method"] == "Runtime.consoleAPICalled" and event["params"].get("type") == "warning"
            or event["method"] == "Log.entryAdded" and event["params"]["entry"].get("level") == "warning"
            for event in events)
        result["network"] = network_of(events, dataset, url, core)
        result["screenshots"] = screenshots_of(record, Path(base))
        result["coreFirstLoadPass"] = core <= LIMIT_MS
        result["status"] = "PASS" if core <= LIMIT_MS else "OVER_BUDGET"
        if core > LIMIT_MS:
            result["reasons"].append(f"navigation-relative core ready {core:g} ms exceeds {LIMIT_MS} ms; no subtraction/averaging")
    except (EvidenceError, ValueError, TypeError, KeyError, OverflowError) as exc:
        result["reasons"].append(str(exc))
    return result


def summarize(samples):
    reasons = []
    if len(samples) != 3:
        reasons.append("Require exactly three preselected navigation samples; no cherry-picking a passing subset.")
    if any(sample["status"] != "PASS" for sample in samples):
        reasons.append("Every sample must independently pass the controls and <=10000 ms core-ready bound.")
    identities = [json.dumps(sample["network"]["navigationIdentity"]) for sample in samples if sample.get("network")]
    if len(set(identities)) != len(samples):
        reasons.append("Three distinct complete navigation identities required; duplicated records do not count.")
    cohorts = [json.dumps([sample.get("url"), sample.get("conditions"),
                          [(row["file"], row["encodedBodyBytes"], row["decodedBodyBytes"])
                           for row in sample.get("network", {}).get("resources", [])] if sample.get("network") else None],
                         sort_keys=True) for sample in samples]
    if len(set(cohorts)) != 1:
        reasons.append("All samples must use the same exact URL, reported payload sizes, shaping and recorded GPU-cache conditions.")
    passed = not reasons
    return {"schemaVersion": 1, "verdict": "PASS" if passed else "NOT_PROVEN",
            "bounded3of3": passed, "thresholdMs": LIMIT_MS, "sampleCount": len(samples),
            "corePassCount": sum(sample["coreFirstLoadPass"] for sample in samples),
            "claim": "Bounded 3/3 recorded foreground core-ready samples <=10s; not a production SLA." if passed else None,
            "physicalPresentationVerified": False, "productionSla": False,
            "reasons": reasons, "limitations": LIMITATIONS, "samples": samples}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("records", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, help="Optional NEW JSON report; existing files are never overwritten.")
    args = parser.parse_args(argv)
    samples = []
    for path in args.records:
        try:
            require(path.stat().st_size <= 64 * 1024 * 1024, "input exceeds bounded 64 MiB limit")
            raw = path.read_bytes()
            sample = analyze_sample(json_value(raw.decode("utf-8-sig")), base=path.resolve().parent)
            sample["inputSha256"] = hashlib.sha256(raw).hexdigest()
        except (OSError, UnicodeError, EvidenceError) as exc:
            sample = {"status": "REFUSED", "coreFirstLoadPass": False, "reasons": [str(exc)]}
        sample["input"] = str(path.resolve())
        samples.append(sample)
    report = summarize(samples)
    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        try:
            with args.output.open("x", encoding="utf-8") as output:
                output.write(text)
        except OSError as exc:
            parser.error(f"cannot create NEW output: {exc}")
    else:
        sys.stdout.write(text)
    return 0 if report["bounded3of3"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
