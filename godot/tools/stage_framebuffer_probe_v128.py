"""One pinned v131 -> NEW v132 framebuffer-query experiment, without a build.

Only four exact generated-JS sites are transformed. All existing helpers, WASM,
three packs and provenance stay byte-identical. The shell adds SRI-bound assets
and a lite-only opt-in adapter; query input never asserts interception coverage.
The standalone state helper remains unchanged. A single isolated prepare() call
refreshes encodings/shared sizes, including that newly referenced helper.
"""
import argparse
import base64
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "artifacts/v131"
DESTINATION = ROOT / "artifacts/v132"
HELPER_NAME = "meadow-framebuffer-state.js"
HELPER = ROOT / "godot/engine-patches" / HELPER_NAME
PREPARER = ROOT / "godot/tools/prepare_web_build.py"
NODE = Path("E:/Nodejs/node.exe")
HELPER_SHA = "661b196fd61031ac977604f9e5fdb5fb4b56dbe4e8c2abab9d5f2fb76ebfe0d8"
PREPARER_SHA = "a072c16bf0fb693771bb81d431072dbcd335dcd2b3bcaa942b1a36595721a9fa"
PINS = {
    "index.html": "21e5042c523721eb7aca194f94a2af4cde98d491cb6070c3c74f8ca391ae278f",
    "index.js": "aa5b17fbdc5f5e72ca7f5bf05c186623d6a86b1ab0aaf87e7dc15ade1d3e1a52",
    "index.wasm": "01e849967a05d6d008b9e2527b047e95f36a3e069d48edab67d497ea14c83945",
    "index.audio.worklet.js": "5b476a9c9ce642c0ee4256436d1bc31d9c38f868aca0f9a8e2a57c18d2dec2a3",
    "index.audio.position.worklet.js": "be33985bc7160d6bf9646f259cd86b259cd67b02ccb297ee5c44f8ac84327bc8",
    "index.pck": "02adc956b196fc701092b5186343da9146a5f30b64f349d5d3dcbe12b8f81a6d",
    "index-balanced.pck": "68198062fb7918abaef956d588ec5e929104dffe348d520602c862749af67a33",
    "index-lite.pck": "dfae7b33bbf28a12a456610abb7dd80da36bd5158b5b5cfc8f1527c5150cadfc",
    "index.png": "3cb4495c0b98dfbe4b663cbf2b6836473572339beb66d902367893162a70be0e",
    "meadow-controls.css": "d1ed449b89ac4978e54376718c12d23256190c60b434254df84578e8832be046",
    "meadow-controls.js": "57ff033e35f4749b5b1c0b077188e56b9a6d61de3755c4e6ecbe95d267191559",
    "meadow-loader.js": "4ce92fdfac9a4af584ec264561d0f0a6b1abdf7d1ed6c17708a3d88ad7613592",
    "meadow-quality.js": "fe1f540bc35a1e7034af48022f0a088f8bc92792e301bda93accece74c4260e6",
    "meadow-startup-trace.js": "4be6169381651d6cfe92bd542c651c1d31e7266db1f8dc9efb838fb83b37f0bd",
    "meadow-webgl-compile.js": "73c86c4f4a8e1a89cf677ebb1b65a844e260df7a94ed145433ce07592d4885d7",
    "engine-build.json": "9cf319c7aa07fe6aa195c7a570acc689a9be11baaa2592363b118d349d7bd4c3",
    "frozen-original.json": "c292bf5d24d87c105d4edcd9a5e55441d7786a92a01d00e3079e51d7963d3981",
    "proof.json": "5de6115c86ede5f11fe3a44411d35cfd91ec2cb7d427e28ee21a2e24f7e2a36f",
    "web-payload.json": "132de31c07baf97c2766c2c64f2c74b64528fb26b228e07219abdfb5674df8ae",
}
PACKS = ("index.pck", "index-balanced.pck", "index-lite.pck")
HOSTS = tuple(name for name in PINS if name.startswith("meadow-"))
PROVENANCE = ("engine-build.json", "frozen-original.json", "proof.json")
STATE = 'globalThis["MeadowFramebufferState"]'
EDITS = (
    ("blit-scissor", "var prevScissorTest=gl.getParameter(3089);",
     f'var meadowState={STATE};var prevScissorTest=meadowState&&typeof meadowState["readScissor"]=="function"?meadowState["readScissor"](context):gl.getParameter(3089);'),
    ("blit-draw-binding", "var prevFbo=gl.getParameter(36006);",
     'var prevFbo=meadowState&&typeof meadowState["readFramebufferBinding"]=="function"?meadowState["readFramebufferBinding"](context):gl.getParameter(36006);'),
    ("register-before-offscreen", "GLctx:ctx};if(ctx.canvas)ctx.canvas.GLctxObject=context;",
     f'GLctx:ctx}};var meadowState={STATE};if(webGLContextAttributes.renderViaOffscreenBackBuffer&&meadowState&&typeof meadowState["register"]=="function")meadowState["register"](context);if(ctx.canvas)ctx.canvas.GLctxObject=context;'),
    ("release-before-delete", "deleteContext:contextHandle=>{if(GL.currentContext===GL.contexts[contextHandle])",
     f'deleteContext:contextHandle=>{{var meadowState={STATE};if(meadowState&&typeof meadowState["release"]=="function")meadowState["release"](GL.contexts[contextHandle]);if(GL.currentContext===GL.contexts[contextHandle])'),
)


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def exact_once(source, old, new):
    require(source.count(old) == 1, f"Missing/duplicate exact transform anchor: {old[:65]}")
    return source.replace(old, new, 1)


def parse_json(blob):
    def pairs(rows):
        result = {}
        for name, value in rows:
            require(name not in result, f"Duplicate JSON field: {name}")
            result[name] = value
        return result
    return json.loads(blob, object_pairs_hook=pairs)


def transform_engine(blob):
    require(digest(blob) == PINS["index.js"], "Unknown generated JS: no transform or coverage assertion")
    source = blob.decode("utf-8")
    require("MeadowFramebufferState" not in source, "Already transformed engine")
    expected_calls = {".bindFramebuffer(": 6, ".deleteFramebuffer(": 1,
                      ".createFramebuffer(": 1, ".enable(": 6, ".disable(": 6}
    for token, count in expected_calls.items():
        require(source.count(token) == count, f"Native mutation call-path drift: {token}")
    for token in ('var buffer=GLctx[createFunction]();',
                  'GL.genObject(n,ids,"createFramebuffer",GL.framebuffers)',
                  'var _glEnable=x0=>GLctx.enable(x0)', 'var _glDisable=x0=>GLctx.disable(x0)',
                  'GLctx.bindFramebuffer(target,framebuffer?GL.framebuffers[framebuffer]:GL.currentContext.defaultFbo)'):
        require(source.count(token) == 1, "Audited dynamic interception path changed")
    result = source
    evidence = []
    for name, old, new in EDITS:
        evidence.append({"name": name, "originalByteOffset": source.index(old),
                         "before": old, "after": new})
        result = exact_once(result, old, new)
    reversed_source = result
    for _, old, new in reversed(EDITS):
        reversed_source = exact_once(reversed_source, new, old)
    require(reversed_source.encode("utf-8") == blob, "Transform changes bytes outside the four sites")
    for token, count in expected_calls.items():
        require(result.count(token) == count, "Native draw/restoration mutations changed")
    return result.encode("utf-8"), evidence


def sri(checksum):
    return "sha256-" + base64.b64encode(bytes.fromhex(checksum)).decode("ascii")


def make_bootstrap(asset_pins, *, legacy_labels=False):
    # This fixed policy is emitted ONLY after exact engine/host/helper/pack pins
    # pass. Query input changes requested activation, NEVER the coverage claim.
    policy = {"schemaVersion": 1, "stage": "v132", "experimentOnly": True,
              "engineSourceSha256": PINS["index.js"], "wasmSha256": PINS["index.wasm"],
              "litePackSha256": PINS["index-lite.pck"], "helperSha256": HELPER_SHA,
              # prepare() versions quoted helper filenames anywhere in HTML,
              # including JSON labels. Runtime needs only id/integrity, not a
              # redundant filename susceptible to that mechanical rewrite.
              "assets": asset_pins if legacy_labels else
                  [{"id": pin["id"], "integrity": pin["integrity"]} for pin in asset_pins]}
    return """(() => {
  "use strict";
  const policy = Object.freeze(__POLICY__);
  const api = globalThis.MeadowFramebufferState;
  const loader = window.meadowLoader;
  if (!api || api.schemaVersion !== 1 || typeof loader?.start !== "function") return;
  api.configure({ enabled: false, exclusiveContextMethods: false });
  const values = new URLSearchParams(window.location.search).getAll("framebuffer_state");
  const requested = values.length === 1 && values[0] === "1";
  const originalStart = loader.start;
  loader.start = function (...args) {
    const [config, , canvas] = args;
    const assetsMatch = policy.assets.every(pin => document.getElementById(pin.id)?.integrity === pin.integrity);
    const qualityArgs = (config?.args || []).filter(value => typeof value === "string" && value.startsWith("--meadow-quality="));
    const selectedLite = config?.executable === "index" && config.mainPack === "index-lite.pck"
      && qualityArgs.length === 1 && qualityArgs[0] === "--meadow-quality=lite"
      && config.fileSizes?.["index-lite.pck"] === 25166812
      && config.fileSizes?.["index.wasm"] === 26609281
      && window.MEADOW_RENDER_CONTRACTS?.["index-lite.pck"]?.packSha256 === policy.litePackSha256;
    // SRI enforces the build-pinned scripts. This check can only revoke that
    // fixed audit, not grant coverage from a URL, user JSON or localStorage.
    const fixedAuditApplies = assetsMatch && typeof Engine === "function" && selectedLite;
    api.configure({ enabled: requested && fixedAuditApplies, exclusiveContextMethods: fixedAuditApplies });
    window.MEADOW_FRAMEBUFFER_PROBE = Object.freeze({ stage: policy.stage, requested,
      eligible: !!fixedAuditApplies, enabled: requested && !!fixedAuditApplies,
      engineSourceSha256: policy.engineSourceSha256, wasmSha256: policy.wasmSha256,
      litePackSha256: policy.litePackSha256, helperSha256: policy.helperSha256,
      note: "Activation only; snapshot() must confirm registration/hits. DOM/2RAF is not physical presentation." });
    if (canvas?.dataset) canvas.dataset.framebufferProbe = JSON.stringify(window.MEADOW_FRAMEBUFFER_PROBE);
    return Reflect.apply(originalStart, this, args);
  };
})();""".replace("__POLICY__", json.dumps(policy, separators=(",", ":")))


def transform_shell(blob, engine, *, legacy_labels=False):
    require(digest(blob) == PINS["index.html"], "Unknown host shell: no coverage assertion")
    html = blob.decode("utf-8")
    mounts = list(re.finditer(r"window\.meadowQuality\.mount\((\{[^\n]+\})\);", html))
    require(len(mounts) == 1 and html.count("window.meadowQuality.mount(") == 1, "Ambiguous engine config")
    config = parse_json(mounts[0][1])
    require(config.get("executable") == "index" and not config.get("gdextensionLibs")
            and not config.get("args"), "Unexpected executable/extensions/startup arguments")
    for name, count in config["fileSizes"].items():
        require(name in PINS and count == (SOURCE / name).stat().st_size, f"Stale config size: {name}")
    config["fileSizes"]["index.js"] = len(engine)
    start, end = mounts[0].span(1)
    html = html[:start] + json.dumps(config, ensure_ascii=False) + html[end:]
    html = exact_once(html, '<script src="index.js"></script>',
                      f'<script src="{HELPER_NAME}?v={HELPER_SHA}"></script>\n  <script src="index.js"></script>')
    checksums = {**{name: PINS[name] for name in HOSTS},
                 "index.js": digest(engine), HELPER_NAME: HELPER_SHA}
    asset_pins = []
    for index, (name, checksum) in enumerate(checksums.items()):
        # CSS is pinned/copied too, but only scripts form this call-path guard.
        if not name.endswith(".js"):
            continue
        matches = list(re.finditer(r'<script src="(' + re.escape(name) + r'(?:\?[^"<>]*)?)"></script>', html))
        require(len(matches) == 1, f"Missing/ambiguous script tag: {name}")
        pin = {"id": f"meadow-framebuffer-pin-{index}", "name": name, "integrity": sri(checksum)}
        asset_pins.append(pin)
        old = matches[0][0]
        new = f'<script id="{pin["id"]}" src="{matches[0][1]}" integrity="{pin["integrity"]}"></script>'
        html = exact_once(html, old, new)
    bootstrap = make_bootstrap(asset_pins, legacy_labels=legacy_labels)
    html = exact_once(html, "  <script>\n    /* MEADOW_QUALITY_MANIFEST_BEGIN */",
                      "  <script>\n" + bootstrap + "\n  </script>\n  <script>\n    /* MEADOW_QUALITY_MANIFEST_BEGIN */")
    return html, bootstrap, asset_pins


def validate_source(*, finish_prepared=False):
    if finish_prepared:
        require(DESTINATION.is_dir() and not (DESTINATION / "framebuffer-probe.json").exists(),
                "Only the unfinalized, exactly verified v132 preparation can be finalized")
    else:
        require(not DESTINATION.exists() and not DESTINATION.is_symlink(), "v132 must be NEW; existing output is never overwritten")
    require(SOURCE.resolve(strict=True) == SOURCE and DESTINATION.resolve() == DESTINATION,
            "No symlink/junction source or destination redirection")
    for path, expected in ((HELPER, HELPER_SHA), (PREPARER, PREPARER_SHA)):
        require(file_hash(path) == expected, f"Unaudited helper/preparer: {path.name}")
    before = {}
    for name, expected in PINS.items():
        path = SOURCE / name
        require(path.is_file() and not path.is_symlink() and path.resolve() == path, f"Invalid source file: {name}")
        require(file_hash(path) == expected, f"Source pin mismatch: {name}")
        before[name] = expected
    payload = parse_json((SOURCE / "web-payload.json").read_bytes())
    for name, record in payload.items():
        require(name in PINS and record["sha256"] == PINS[name], "Payload pin drift")
        require(record["bytes"] == (SOURCE / name).stat().st_size, f"Payload size drift: {name}")
        for coding, suffix in (("gzip", ".gz"), ("br", ".br")):
            entry = record["encodings"][coding]
            path = SOURCE / (name + suffix)
            require(path.is_file() and not path.is_symlink() and path.resolve() == path, "Encoding path redirection")
            require(path.stat().st_size == entry["bytes"] and file_hash(path) == entry["sha256"], f"Old encoding mismatch: {path.name}")
            before[path.name] = entry["sha256"]
    build = parse_json((SOURCE / "engine-build.json").read_bytes())
    for name, record in build["engine"].items():
        require(record["sha256"] == PINS[name] and record["bytes"] == (SOURCE / name).stat().st_size, "Engine provenance mismatch")
    for name, expected in parse_json((SOURCE / "frozen-original.json").read_bytes()).items():
        require(PINS[name] == expected, "Frozen original provenance mismatch")
    return before, payload


def run_bounded_checks(engine, bootstrap, pins):
    # No filesystem fixtures, browser, services, engine execution or full suites.
    subprocess.run([str(NODE), "--check"], input=engine, check=True, capture_output=True, timeout=30)
    for invalid in (b"", (SOURCE / "index.js").read_bytes() + b" ", engine):
        try:
            transform_engine(invalid)
        except ValueError:
            pass
        else:
            raise ValueError("Unknown/repeated engine transform was accepted")
    for invalid in ("absent", "twice twice"):
        try:
            exact_once(invalid, "twice", "once")
        except ValueError:
            pass
        else:
            raise ValueError("Missing/duplicate transform anchor was accepted")
    try:
        transform_shell((SOURCE / "index.html").read_bytes() + b" ", engine)
    except ValueError:
        pass
    else:
        raise ValueError("Unknown shell was allowed to assert coverage")
    script = r'''
const fs=require("node:fs"),vm=require("node:vm"),assert=require("node:assert/strict");
const input=JSON.parse(fs.readFileSync(0,"utf8"));
const tests=[];
const valid={executable:"index",mainPack:"index-lite.pck",args:["--","--meadow-quality=lite"],
  fileSizes:{"index-lite.pck":25166812,"index.wasm":26609281}};
function check(name,query,config,wanted,unknown=false,contract=input.pack){
  const calls=[],canvas={dataset:{}},options={onProgress:1},sentinel={};
  const root={URLSearchParams,location:{search:query},Engine:function(){},
    MeadowFramebufferState:{schemaVersion:1,configure:x=>calls.push(x)},
    MEADOW_RENDER_CONTRACTS:{"index-lite.pck":{packSha256:contract}},
    document:{getElementById:id=>unknown?null:input.pins.find(p=>p.id===id)},
    meadowLoader:{start(...args){assert.equal(this,root.meadowLoader);assert.deepEqual(args,[config,options,canvas]);return sentinel;}}};
  root.window=root;vm.runInNewContext(input.bootstrap,root);
  assert.equal(root.meadowLoader.start(config,options,canvas),sentinel);
  assert.equal(calls[0].enabled,false);assert.equal(calls.at(-1).enabled,wanted);
  assert.equal(JSON.parse(canvas.dataset.framebufferProbe).enabled,wanted);
  assert.equal(root.MEADOW_FRAMEBUFFER_PROBE.note.includes("not physical presentation"),true);
  tests.push({name,passed:true});
}
for(const query of ["","?framebuffer_state=0","?framebuffer_state=true","?framebuffer_state=1&framebuffer_state=1",
 "?exclusiveContextMethods=1","?framebuffer_state=0&exclusiveContextMethods=true"])
 check("OFF "+query,query,valid,false);
check("Explicit lite ON","?framebuffer_state=1",valid,true);
for(const quality of ["original","balanced"])
 check("Frozen "+quality+" OFF","?framebuffer_state=1&exclusiveContextMethods=1",
 {...valid,mainPack:quality==="original"?"index.pck":"index-balanced.pck",args:["--","--meadow-quality="+quality]},false);
check("Unknown integrity OFF","?framebuffer_state=1",valid,false,true);
check("Unknown pack contract OFF","?framebuffer_state=1",valid,false,false,"unknown");
check("Wrong selected bytes OFF","?framebuffer_state=1",{...valid,fileSizes:{...valid.fileSizes,"index-lite.pck":1}},false);
check("Wrong executable OFF","?framebuffer_state=1",{...valid,executable:"other"},false);
check("Conflicting quality OFF","?framebuffer_state=1",{...valid,args:["--meadow-quality=original","--meadow-quality=lite"]},false);
// Prove exact generated-JS absent-helper fallback, and real native restoration.
function blit(source,api){const start=source.indexOf("blitOffscreenFramebuffer:")+"blitOffscreenFramebuffer:".length;
 const end=source.indexOf(",registerContext:",start);assert.ok(start>0&&end>start);
 return vm.runInNewContext("("+source.slice(start,end)+")",{MeadowFramebufferState:api});}
function setup(){const log=[],canvas={width:2560,height:1440},saved={},read={};
 const gl={canvas,draw:saved,read,scissor:true,getParameter(p){log.push(["query",p]);return p===3089?this.scissor:this.draw;},
  disable(p){log.push(["disable",p]);this.scissor=false;},enable(p){log.push(["enable",p]);this.scissor=true;},
  bindFramebuffer(target,value){log.push(["bind",target,value]);if(target===36160||target===36009)this.draw=value;if(target===36160||target===36008)this.read=value;},
  blitFramebuffer(...args){log.push(["blit",...args]);}};
 return {gl,log,context:{GLctx:gl,defaultFbo:{}}};}
for(const mode of ["absent","cached"]){const a=setup(),b=setup();
 // Normalize resource identities across the independent native mocks.
 b.gl.draw=a.gl.draw;b.gl.read=a.gl.read;b.context.defaultFbo=a.context.defaultFbo;
 const api=mode==="cached"?{readScissor:c=>c.GLctx.scissor,readFramebufferBinding:c=>c.GLctx.draw}:undefined;
 blit(input.stock,undefined)(a.context);blit(input.engine,api)(b.context);
 const native=x=>x.filter(row=>row[0]!=="query");
 assert.deepEqual(native(a.log),native(b.log));assert.equal(a.gl.draw,b.gl.draw);assert.equal(a.gl.read,b.gl.read);assert.equal(a.gl.scissor,b.gl.scissor);
 if(mode==="absent")assert.deepEqual(a.log,b.log);else assert.equal(b.log.some(row=>row[0]==="query"),false);
 tests.push({name:"Actual generated blit "+mode,passed:true});}
console.log(JSON.stringify({passed:tests.length,total:tests.length,tests}));
'''
    inputs = {"bootstrap": bootstrap, "pins": pins, "pack": PINS["index-lite.pck"],
              "stock": (SOURCE / "index.js").read_text(encoding="utf-8"), "engine": engine.decode("utf-8")}
    result = subprocess.run([str(NODE), "-e", script], input=json.dumps(inputs), text=True,
                            capture_output=True, timeout=30)
    require(result.returncode == 0, "Bounded JS checks failed:\n" + result.stderr)
    checks = parse_json(result.stdout)
    checks.update({"engineSyntaxCheck": True, "unknownAndDuplicateTransformsRejected": True,
                   "browserActions": 0, "engineBuilds": 0, "physicalPresentationVerified": False})
    return checks


def preview_prepared_html(html, sizes, module):
    """The pinned preparer's HTML-only projection; no compression or writes."""
    for name in ("meadow-controls.js", "meadow-controls.css", "meadow-loader.js", "meadow-quality.js",
                 "meadow-startup-trace.js", "meadow-webgl-compile.js"):
        checksum = PINS[name][:16] if name in ("meadow-controls.js", "meadow-controls.css") else PINS[name]
        html = re.sub(r'(["\'])(?:\./)?' + re.escape(name) + r'(?:\?[^"\']*)?(["\'])',
                      lambda match: f'{match[1]}{name}?v={checksum}{match[2]}', html)
    return module.quality_html(html, sizes)


def stage(check_only=False, finish_prepared=False):
    before, previous_payload = validate_source(finish_prepared=finish_prepared)
    engine, edits = transform_engine((SOURCE / "index.js").read_bytes())
    html, bootstrap, asset_pins = transform_shell((SOURCE / "index.html").read_bytes(), engine)
    checks = run_bounded_checks(engine, bootstrap, asset_pins)
    print(json.dumps({"phase": "preflight-passed", "checks": checks["passed"],
                      "transformedJsSha256": digest(engine), "checkOnly": check_only}), flush=True)
    if check_only:
        return checks
    # Recheck every fixed input before any output exists. Do not refresh helpers
    # from the live worktree: the isolated preparer consumes the frozen copies.
    for name, expected in before.items():
        require(file_hash(SOURCE / name) == expected, f"Source changed before staging: {name}")
    require(file_hash(HELPER) == HELPER_SHA and file_hash(PREPARER) == PREPARER_SHA, "Helper/preparer changed")
    copied = {name: checksum for name, checksum in PINS.items() if name not in ("index.js", "index.html", "web-payload.json")}
    spec = importlib.util.spec_from_file_location("_meadow_prepare_framebuffer_v132", PREPARER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.HELPER_SOURCES = {name: DESTINATION / name for name in module.HELPER_SOURCES}
    module.OPTIONAL_PAYLOADS = (*module.OPTIONAL_PAYLOADS, HELPER_NAME)
    if finish_prepared:
        # Recover only our exact interrupted candidate, never restage or
        # overwrite an arbitrary/completed directory. All byte checks below
        # finish before the sole repaired output (HTML) is written.
        sizes = parse_json((DESTINATION / "web-payload.json").read_bytes())
        require(set(sizes) == set(previous_payload) | {HELPER_NAME}, "Unexpected prepared payload set")
    else:
        DESTINATION.mkdir()
        for name in copied:
            shutil.copy2(SOURCE / name, DESTINATION / name)
        shutil.copy2(SOURCE / "web-payload.json", DESTINATION / "source-web-payload.json")
        shutil.copy2(HELPER, DESTINATION / HELPER_NAME)
        (DESTINATION / "index.js").write_bytes(engine)
        (DESTINATION / "index.html").write_text(html, encoding="utf-8", newline="\n")
        print(json.dumps({"phase": "prepare-once", "destination": str(DESTINATION)}), flush=True)
        sizes = module.prepare(DESTINATION, brotli=True)
    for name, expected in before.items():
        require(file_hash(SOURCE / name) == expected, f"Frozen v131 changed: {name}")
    for name, expected in {**copied, HELPER_NAME: HELPER_SHA, "source-web-payload.json": PINS["web-payload.json"]}.items():
        require(file_hash(DESTINATION / name) == expected, f"Staged frozen file changed: {name}")
    require(file_hash(DESTINATION / "index.js") == digest(engine), "Prepared engine changed")
    for name, record in sizes.items():
        require(record["bytes"] == (DESTINATION / name).stat().st_size and record["sha256"] == file_hash(DESTINATION / name), "Prepared raw hash/size mismatch")
        for coding, suffix in (("gzip", ".gz"), ("br", ".br")):
            encoding = record["encodings"][coding]
            require((DESTINATION / (name + suffix)).stat().st_size == encoding["bytes"]
                    and file_hash(DESTINATION / (name + suffix)) == encoding["sha256"], "Prepared sidecar hash/size mismatch")
        if name not in ("index.js", HELPER_NAME):
            require(record == previous_payload[name], f"Unchanged payload encoding/metadata drift: {name}")
    for name in ("index.js", HELPER_NAME):
        raw = (DESTINATION / name).read_bytes()
        require(gzip.decompress((DESTINATION / (name + ".gz")).read_bytes()) == raw, "New gzip does not decode to exact payload")
        require(module.brotli_module().decompress((DESTINATION / (name + ".br")).read_bytes()) == raw,
                "New Brotli does not decode to exact payload")
    final_html = (DESTINATION / "index.html").read_text(encoding="utf-8")
    if finish_prepared:
        legacy_html, _, _ = transform_shell((SOURCE / "index.html").read_bytes(), engine, legacy_labels=True)
        expected = preview_prepared_html(html, sizes, module)
        require(final_html in (preview_prepared_html(legacy_html, sizes, module), expected),
                "Existing HTML is not the exact interrupted candidate; refuse overwrite")
        require(bootstrap in expected and expected == module.quality_html(html, sizes), "Fixed policy still subject to prepare rewriting")
        (DESTINATION / "index.html").write_text(expected, encoding="utf-8", newline="\n")
        final_html = expected
    require(bootstrap in final_html, "Preparation altered the fixed activation policy")
    # All preparation changes must be confined to its existing quality metadata.
    require(final_html == module.quality_html(html, sizes), "Unexpected shell transformation during preparation")
    require(HELPER_NAME in sizes and HELPER_NAME in module.HelperReferences(final_html).assets,
            "New helper missing from shared transfer metadata")
    require(file_hash(PREPARER) == PREPARER_SHA and file_hash(HELPER) == HELPER_SHA, "Original helper/preparer changed")
    total = sum(row["gzipBytes"] for name, row in sizes.items() if not name.endswith(".pck")) + sizes["index-lite.pck"]["gzipBytes"]
    report = {"schemaVersion": 1, "kind": "framebuffer-state-generated-js-experiment", "status": "READY_FOR_PHYSICAL_AB",
              "sourceVersion": str(SOURCE), "destination": str(DESTINATION), "sourceFiles": before,
              "stagerSha256": file_hash(Path(__file__)), "preparerSha256": PREPARER_SHA,
              "engineSourceSha256": PINS["index.js"], "engineTransformedSha256": digest(engine),
              "engineTransformedBytes": len(engine), "wasmSha256": PINS["index.wasm"],
              "helperSha256": HELPER_SHA, "hostSourceHashes": {name: PINS[name] for name in HOSTS},
              "shellSha256": file_hash(DESTINATION / "index.html"), "assetIntegrityPins": asset_pins,
              "sourceAndCopiedFilesExact": True, "threePacksByteIdentical": True, "oldProvenanceByteIdentical": True,
              "priorEngineMetadataDescribesUntransformedBuild": True, "exactReversibleEdits": edits,
              "checks": checks, "prepareCalls": 1, "finalizedExistingPreparedFiles": finish_prepared,
              "htmlLabelRepair": "Removed mechanically versioned, unused runtime filename labels; no second prepare" if finish_prepared else None,
              "newSidecarsDecodedExact": True, "liteGzipTotalBytes": total,
              "activation": {"default": "OFF", "on": "quality=lite&framebuffer_state=1", "off": "quality=lite&framebuffer_state=0",
                             "original": "always OFF", "balanced": "always OFF", "coverageFromQuery": False,
                             "unknownSourcePolicy": "reject before output", "unknownRuntimeIntegrityPolicy": "OFF; SRI rejects mismatched script content"},
              "physicalPresentationVerified": False, "performanceAccepted": False,
              "note": "One v132 JS/PCK pair for OFF/ON. Existing 2RAF/DOM milestones are unchanged and do not prove GPU presentation or 20-second savings."}
    (DESTINATION / "framebuffer-probe.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (DESTINATION / "FRAMEBUFFER-PROBE.md").write_text(
        "# v132 framebuffer-state experiment\n\nReady for main-owned physical A/B, not performance-accepted.\n\n"
        "Use this same stage with `?quality=lite&framebuffer_state=0` (OFF) and `?quality=lite&framebuffer_state=1` (ON). "
        "Default, duplicate/unknown switch values, original, and balanced stay OFF. Query input never supplies a coverage assertion. "
        "Fixed source hashes and runtime script integrity constrain activation; unknown sources are refused.\n\n"
        "Inspect `MEADOW_FRAMEBUFFER_PROBE` / canvas.dataset.framebufferProbe for activation and "
        "`MeadowFramebufferState.snapshot()` for successful registration/hits, not just requested ON. "
        "Startup trace completion replaces getParameter and can revoke the cache; normal A/B should omit startup_trace. "
        "Saved-native/prototype bypasses require prior invalidation and are not automatically detectable.\n\n"
        "All three PCKs, WASM, worklets, old helpers and old provenance are byte-identical to v131. "
        "engine-build.json remains the original untransformed build provenance; framebuffer-probe.json records the exact generated-JS delta. "
        "source-web-payload.json retains the original offline metadata; web-payload.json and all sidecars are current.\n\n"
        "Two RAF/loader DOM timestamps do not prove the GPU has presented a complete frame. Main must verify actual full-frame "
        "presentation, day/night/return-day/animation and subsequent responsiveness at matched QHD, DPR, visibility and network/cache conditions. "
        "The helper adds isContextLost/wrapper costs and does not remove GPU drawing work. Do not credit the entire profiler interval as savings.\n\n"
        f"Lite gzip payload total (excluding HTML/headers): {total:,} bytes. No browser, SDK edits, engine build or native audit was performed.\n",
        encoding="utf-8")
    print(json.dumps({"phase": "complete", "destination": str(DESTINATION), "engineJsSha256": digest(engine),
                      "checks": checks["passed"], "liteGzipTotalBytes": total, "performanceAccepted": False}), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check-only", action="store_true", help="Bounded pinned-input/JS checks only; no output or prepare")
    modes.add_argument("--finish-prepared", action="store_true", help="Finalize ONLY this exact unfinalized v132 candidate; validate/reuse sidecars, no second prepare")
    args = parser.parse_args()
    stage(args.check_only, args.finish_prepared)
