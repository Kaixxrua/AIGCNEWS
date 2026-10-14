"""Read-only startup gate contracts, extracted-source logic and bridge JS tests.

No Godot process, compilation, exports, browser, network or artifact writes.
The small Python adapter executes the actual gate/report/first-physics prefix;
it is NOT a GDScript parser or runtime acceptance test. Native compilation and
Web A/B acceptance remain with the isolated compiler and main integrator.

E:/Anaconda3/python.exe -B godot/tools/test_startup_audit.py -v
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import types
import unittest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "godot/scripts/meadow_scene.gd"
ORIGINAL_SHA256 = "3477a2bd4bd67c8de488b977c81ffa76726844e004886b86b77e6f3d2b519d12"
ORIGINAL_PHYSICS = '''func _physics_process(delta: float) -> void:
	if not audit_complete:
		_audit_walk_surface()
		audit_complete = true
	if not scale_guide.visible:
		return
	travel = fmod(travel + delta * 1.5, 2.0 * route_length)
	var distance := travel if travel < route_length else 2.0 * route_length - travel
	var point := _point_on_route(distance)
	walker.position = Vector3(point.x, terrain_height(point.x, point.y) + PLAYER_HEIGHT * 0.5, point.y)

'''


def function(source, name):
    match = re.search(
        rf"^func {re.escape(name)}\([^\n]*\) -> [^\n]+:\n(?P<body>.*?)"
        r"(?=^(?:static )?func |\Z)", source, re.MULTILINE | re.DOTALL)
    if not match:
        raise AssertionError(f"Missing function: {name}")
    return match.group(0), match.group("body")


def extracted_function(body, parameters, namespace):
    """Translate only the bounded snippets under test, not the game/audits."""
    body = re.sub(r"(?m)^(\s*)var (\w+) :=", r"\1\2 =", body)
    body = re.sub(r"\btrue\b", "True", body)
    body = re.sub(r"\bfalse\b", "False", body)
    body = re.sub(r"% \[([^\n]+)\]", r"% (\1)", body)
    for name in ("audit_complete", "_startup_audit_enabled", "_report_startup_audit", "_audit_walk_surface"):
        body = re.sub(rf"(?<![\w.]){re.escape(name)}\b", "self." + name, body)
    exec("def extracted(" + parameters + "):\n" + body.expandtabs(4), namespace)
    return namespace["extracted"]


class Args(list):
    def has(self, value):
        return value in self


class GateHarness:
    def __init__(self, source, *, debug=False, web=False, args=(), query_enabled=False):
        self.audit_complete = False
        self.events = []
        self.logs = []
        self.bridge_calls = []
        self.clock_reads = []
        self.ticks_us = 100_000
        self.on_audit = None

        def bridge_eval(code):
            self.bridge_calls.append(code)
            if "new URLSearchParams" in code:
                return query_enabled
            return None

        def ticks():
            self.clock_reads.append(self.ticks_us)
            return self.ticks_us

        def log(message):
            self.logs.append(message)
            self.events.append(("report", self.audit_complete, message))

        namespace = {
            "__builtins__": {}, "bool": bool, "float": float, "print": log,
            "OS": types.SimpleNamespace(is_debug_build=lambda: debug,
                                        get_cmdline_user_args=lambda: Args(args),
                                        has_feature=lambda feature: web and feature == "web"),
            "Time": types.SimpleNamespace(get_ticks_usec=ticks),
            "JavaScriptBridge": types.SimpleNamespace(eval=bridge_eval),
            "JSON": types.SimpleNamespace(stringify=json.dumps),
        }
        gate = extracted_function(function(source, "_startup_audit_enabled")[1], "self", namespace)
        report = extracted_function(function(source, "_report_startup_audit")[1],
                                    "self, status, duration_ms=-1.0", namespace)
        prefix = function(source, "_physics_process")[1].split("\tif not scale_guide.visible:", 1)[0]
        prefix += '\tself.events.append(("physics", self.audit_complete))\n'
        step = extracted_function(prefix, "self", namespace)
        self._startup_audit_enabled = types.MethodType(gate, self)
        self._report_startup_audit = types.MethodType(report, self)
        self.step = types.MethodType(step, self)

    def _audit_walk_surface(self):
        self.events.append(("audit", self.audit_complete))
        if self.on_audit:
            self.on_audit()
        self.ticks_us += 34_125

    def count(self, event):
        return sum(row[0] == event for row in self.events)


NODE_HARNESS = r'''
const assert = require("node:assert/strict");
const vm = require("node:vm");
const input = JSON.parse(require("node:fs").readFileSync(0, "utf8"));
if (input.mode === "query") {
  const results = input.queries.map(search => vm.runInNewContext(input.code,
    { URLSearchParams, location: { search } }, { timeout: 1000 }));
  process.stdout.write(JSON.stringify(results));
} else {
  const canvas = input.missingCanvas ? null : {
    dataset: { untouched: "preserved", ...(input.initial || {}) },
    width: input.width ?? 1280, height: input.height ?? 800
  };
  const loading = { hidden: false };
  const snapshots = [];
  for (const action of input.actions) {
    const context = { document: { getElementById(id) {
      assert.equal(id, "canvas");
      return canvas;
    } }, performance: { now: () => action.stamp },
      window: { devicePixelRatio: input.dpr ?? 1 }, loading };
    vm.runInNewContext(action.code, context, { timeout: 1000 });
    snapshots.push(canvas ? JSON.parse(JSON.stringify(canvas)) : null);
  }
  assert.equal(loading.hidden, false);
  process.stdout.write(JSON.stringify(snapshots));
}
'''


class StartupAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")

    def node(self, payload):
        executable = shutil.which("node")
        if executable is None and Path("E:/Nodejs/node.exe").is_file():
            executable = "E:/Nodejs/node.exe"
        if executable is None:
            self.skipTest("Node.js required for bridge JavaScript tests; no install attempted")
        result = subprocess.run([executable, "-e", NODE_HARNESS], input=json.dumps(payload),
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_entire_source_outside_bounded_patch_matches_frozen_original(self):
        restored = self.source
        for name in ("_startup_audit_enabled", "_report_startup_audit"):
            restored = restored.replace(function(restored, name)[0], "", 1)
        restored = restored.replace(function(restored, "_physics_process")[0], ORIGINAL_PHYSICS, 1)
        self.assertEqual(hashlib.sha256(restored.encode()).hexdigest(), ORIGINAL_SHA256,
                         "Unexpected change outside the startup gate/telemetry")

    def test_actual_physics_tail_is_exact_and_never_disabled(self):
        tail = "\tif not scale_guide.visible:"
        physics = function(self.source, "_physics_process")[0]
        self.assertEqual(physics[physics.index(tail):], ORIGINAL_PHYSICS[ORIGINAL_PHYSICS.index(tail):])
        prefix = physics[:physics.index(tail)]
        self.assertNotIn("return", prefix)
        for forbidden in ("set_physics_process", "set_process", "process_mode", "queue_free"):
            self.assertNotIn(forbidden, prefix)

    def test_normal_release_skips_once_and_continues_physics(self):
        for web in (False, True):
            with self.subTest(web=web):
                harness = GateHarness(self.source, web=web)
                harness.step()
                harness.step()
                self.assertTrue(harness.audit_complete)
                self.assertEqual(harness.count("audit"), 0)
                self.assertEqual(harness.count("physics"), 2)
                self.assertEqual(harness.logs, ["MEADOW_STARTUP_AUDIT: status=skipped duration_ms=0.000"])
                self.assertEqual(harness.clock_reads, [])

    def test_debug_build_enables_once_on_native_and_web(self):
        for web in (False, True):
            with self.subTest(web=web):
                harness = GateHarness(self.source, debug=True, web=web)
                harness.step()
                harness.step()
                self.assertEqual(harness.count("audit"), 1)
                self.assertEqual(harness.count("physics"), 2)
                self.assertFalse(any("URLSearchParams" in code for code in harness.bridge_calls))

    def test_exact_custom_cli_flag_enables_once_on_native_and_web(self):
        for web in (False, True):
            with self.subTest(web=web):
                harness = GateHarness(self.source, web=web, args=["--startup-audit", "--meadow-quality=lite"])
                harness.step()
                harness.step()
                self.assertEqual(harness.count("audit"), 1)
                self.assertEqual(harness.count("physics"), 2)
                self.assertFalse(any("URLSearchParams" in code for code in harness.bridge_calls))

    def test_cli_lookalikes_and_architecture_flag_do_not_enable(self):
        for flag in ("--startup-audit=0", "--startup-audit=1", "startup-audit", "--architecture-audit"):
            with self.subTest(flag=flag):
                harness = GateHarness(self.source, args=[flag])
                harness.step()
                self.assertEqual(harness.count("audit"), 0)

    def test_query_gate_is_web_only(self):
        for web in (False, True):
            with self.subTest(web=web):
                harness = GateHarness(self.source, web=web, query_enabled=True)
                harness.step()
                self.assertEqual(harness.count("audit"), int(web))
                self.assertEqual(sum("URLSearchParams" in code for code in harness.bridge_calls), int(web))

    def test_actual_query_expression_accepts_only_exact_startup_value(self):
        gate = function(self.source, "_startup_audit_enabled")[1]
        code = re.search(r'JavaScriptBridge\.eval\("([^"\n]+)"\)', gate).group(1)
        queries = ["", "?architecture_audit=1", "?unknown=1", "?startup_audit=0", "?startup_audit=true",
                   "?startup_audit=01", "?startup_audit", "?startup_audit=1", "?startup_audit=%31",
                   "?startup_audit=0&startup_audit=1", "?architecture_audit=1&startup_audit=1"]
        self.assertEqual(self.node({"mode": "query", "code": code, "queries": queries}),
                         [False, False, False, False, False, False, False, True, True, False, True])

    def test_architecture_and_other_explicit_ready_audits_stay_independent(self):
        ready = function(self.source, "_ready")[1]
        self.assertNotIn("_startup_audit_enabled", ready)
        for name in ("architecture", "render", "canopy", "mountain"):
            self.assertIn(f".get('{name}_audit') === '1'", ready)
            self.assertIn(f"{name}_audit.run.call_deferred(self)", ready)

    def test_guard_precedes_reporting_and_audit_even_on_reentry(self):
        harness = GateHarness(self.source, debug=True)
        harness.on_audit = harness.step
        harness.step()
        self.assertEqual(harness.count("audit"), 1)
        self.assertEqual(harness.count("physics"), 2)
        self.assertTrue(all(row[1] for row in harness.events))

    def test_failure_is_not_reported_completed_or_retried(self):
        harness = GateHarness(self.source, debug=True)

        def fail():
            raise RuntimeError("audit fixture failure")

        harness.on_audit = fail
        with self.assertRaisesRegex(RuntimeError, "audit fixture failure"):
            harness.step()
        self.assertTrue(harness.audit_complete)
        harness.step()
        self.assertEqual(harness.count("audit"), 1)
        self.assertEqual(harness.count("physics"), 1)
        self.assertEqual(harness.logs, ["MEADOW_STARTUP_AUDIT: status=running duration_ms=-1.000"])

    def test_duration_brackets_only_the_audit_with_microsecond_precision(self):
        harness = GateHarness(self.source, debug=True)
        harness.step()
        self.assertEqual(harness.clock_reads, [100_000, 134_125])
        self.assertEqual(harness.logs[-1], "MEADOW_STARTUP_AUDIT: status=completed duration_ms=34.125")
        physics = function(self.source, "_physics_process")[1]
        self.assertLess(physics.index('_report_startup_audit("running")'), physics.index("var audit_start_us"))
        self.assertLess(physics.index("var audit_start_us"), physics.index("_audit_walk_surface()"))
        self.assertLess(physics.index("_audit_walk_surface()"), physics.index("var audit_duration_ms"))
        self.assertLess(physics.index("var audit_duration_ms"), physics.index('_report_startup_audit("completed"'))

    def test_native_reporting_does_not_call_javascript(self):
        harness = GateHarness(self.source, debug=True)
        harness.step()
        self.assertEqual(harness.bridge_calls, [])

    def test_dom_records_independent_duration_and_page_clock_without_ui_changes(self):
        harness = GateHarness(self.source, web=True, debug=True)
        harness.step()
        initial = {"sceneBuildMs": "4270", "sceneSignalMs": "16775", "engineStartedMs": "218309",
                   "loadMs": "225613", "startupAuditFinishedAtMs": "old", "startupAuditMs": "old",
                   "startupAuditElapsedMs": "old"}
        before, after = self.node({"mode": "telemetry", "initial": initial, "actions": [
            {"code": harness.bridge_calls[0], "stamp": 17_000.25},
            {"code": harness.bridge_calls[1], "stamp": 17_037.75}]})
        self.assertEqual(before["dataset"]["startupAuditStatus"], "running")
        self.assertEqual(before["dataset"]["startupAuditStartedAtMs"], "17000.25")
        self.assertNotIn("startupAuditMs", before["dataset"])
        self.assertNotIn("startupAuditElapsedMs", before["dataset"])
        self.assertNotIn("startupAuditFinishedAtMs", before["dataset"])
        self.assertEqual(after["dataset"]["startupAuditStatus"], "completed")
        self.assertEqual(after["dataset"]["startupAuditMs"], "34.125")
        self.assertEqual(after["dataset"]["startupAuditElapsedMs"], "34.125")
        self.assertEqual(after["dataset"]["startupAuditFinishedAtMs"], "17037.75")
        for state in (before, after):
            self.assertEqual((state["width"], state["height"]), (1280, 800))
            self.assertEqual(state["dataset"]["startupAuditEnabled"], "true")
            self.assertEqual(state["dataset"]["startupAuditDebugBuild"], "true")
            self.assertEqual(state["dataset"]["untouched"], "preserved")
            for key in ("sceneBuildMs", "sceneSignalMs", "engineStartedMs", "loadMs"):
                self.assertEqual(state["dataset"][key], initial[key])

    def test_dom_skipped_marker_zero_is_not_a_measured_audit(self):
        harness = GateHarness(self.source, web=True)
        harness.step()
        state, = self.node({"mode": "telemetry", "initial": {"startupAuditStartedAtMs": "stale"},
                            "actions": [{"code": harness.bridge_calls[-1], "stamp": 101.125}]})
        self.assertEqual(state["dataset"]["startupAuditStatus"], "skipped")
        self.assertEqual(state["dataset"]["startupAuditMs"], "0")
        self.assertEqual(state["dataset"]["startupAuditElapsedMs"], "0")
        self.assertEqual(state["dataset"]["startupAuditEnabled"], "false")
        self.assertEqual(state["dataset"]["startupAuditDebugBuild"], "false")
        self.assertEqual(state["dataset"]["startupAuditFinishedAtMs"], "101.125")
        self.assertNotIn("startupAuditStartedAtMs", state["dataset"])

    def test_canvas_telemetry_reads_backing_pixels_without_applying_dpr(self):
        harness = GateHarness(self.source, web=True)
        harness.step()
        code = harness.bridge_calls[-1]
        for width, height, dpr in ((3840, 2160, 1.5), (1280, 800, 1.5), (1280, 800, 1.0)):
            with self.subTest(width=width, height=height, dpr=dpr):
                state, = self.node({"mode": "telemetry", "width": width, "height": height, "dpr": dpr,
                                    "actions": [{"code": code, "stamp": 101.125}]})
                self.assertEqual((state["width"], state["height"]), (width, height))
                self.assertEqual(state["dataset"]["startupAuditCanvasWidth"], str(width))
                self.assertEqual(state["dataset"]["startupAuditCanvasHeight"], str(height))
                self.assertEqual(float(state["dataset"]["startupAuditDpr"]), dpr)

    def test_release_opt_in_reports_enabled_but_not_debug(self):
        for options in ({"query_enabled": True}, {"args": ["--startup-audit"]}):
            with self.subTest(options=options):
                harness = GateHarness(self.source, web=True, **options)
                harness.step()
                reports = [code for code in harness.bridge_calls if "new URLSearchParams" not in code]
                states = self.node({"mode": "telemetry", "actions": [
                    {"code": reports[0], "stamp": 100}, {"code": reports[1], "stamp": 140}]})
                for state in states:
                    self.assertEqual(state["dataset"]["startupAuditEnabled"], "true")
                    self.assertEqual(state["dataset"]["startupAuditDebugBuild"], "false")
                    self.assertEqual(state["dataset"]["startupAuditCanvasWidth"], "1280")
                    self.assertEqual(state["dataset"]["startupAuditCanvasHeight"], "800")

    def test_missing_canvas_is_safe_and_report_values_are_json_encoded(self):
        harness = GateHarness(self.source, web=True)
        status = 'fixture "quoted" \\ value'
        harness._report_startup_audit(status, 3.125)
        code = harness.bridge_calls[-1]
        state, = self.node({"mode": "telemetry", "actions": [{"code": code, "stamp": 20}]})
        self.assertEqual(state["dataset"]["startupAuditStatus"], status)
        self.assertEqual(self.node({"mode": "telemetry", "missingCanvas": True,
                                    "actions": [{"code": code, "stamp": 20}]}), [None])


if __name__ == "__main__":
    unittest.main()
