"""One capped incremental Web engine candidate; never edits engine source.

The separately reviewed patch must already be applied with apply_patch. Existing
reflection-depth release, scene packs, host assets and module policy are frozen.
Run prepare before applying the patch, then build, then collect. Fresh output only.
"""
from datetime import datetime, timezone
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'artifacts/startup-v135/engine/deferred-validation-01'
ENGINE = ROOT/'artifacts/startup-v128/engine'
BASE = ENGINE/'reflection-depth-01'
SRC = ROOT/'.tools/godot-web-v126/src'
CPP = 'drivers/gles3/shader_gles3.cpp'
PINS = ROOT/'godot/engine-patches/deferred-web-validation-v135.json'
PATCH = PINS.with_suffix('.patch')
ZIP_SHA = '1344c8aecdc55404e560240a7dd22b3a4734e85a2a04efef7617416acf3b6858'
sys.path.insert(0, str(ENGINE))
from run_build import environment
from collect_trimmed import brotli_bytes, memory


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def info(path):
    path = Path(path).resolve()
    return {'file':str(path), 'bytes':path.stat().st_size, 'sha256':digest(path)}


def write_json(path, value, *, update=False):
    assert path.resolve().is_relative_to(OUT)
    with path.open('w' if update else 'x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def source_proof(patched):
    before = json.loads((BASE/'source-proof.json').read_bytes())['changesFromUpstream']
    expected = dict(before)
    if patched:
        pins = json.loads(PINS.read_bytes())
        assert pins['beforeSha256'] == before[CPP] and digest(PATCH) == pins['patchSha256']
        expected[CPP] = pins['afterSha256']
    upstream = json.loads((ROOT/'artifacts/startup-v126/engine/upstream-files.json').read_bytes())
    actual = {}
    for row in upstream:
        sha = digest(SRC/row['path'])
        if sha != row['sha256']:
            actual[row['path']] = sha
    assert actual == expected, 'Only the reviewed shader validation change may differ'
    extension = json.loads((ENGINE/'source-extension-02.json').read_bytes())
    for row in extension['files']:
        assert digest(SRC/row['path']) == row['afterSha256'], 'Mode5 extension unchanged'
    return {'upstreamFilesChecked':len(upstream), 'changesFromUpstream':actual,
            'onlyNewSourceChange':CPP if patched else None, 'mode5LazyReflectionExact':True,
            'patch':info(PATCH) if patched else None}


def arguments():
    command = json.loads((BASE/'build.log.json').read_bytes())['command']
    assert '-j4' in command and 'linkflags=-Wl,--threads=4 -Wl,--thinlto-jobs=4' in command
    return command


def child_environment():
    env = environment()
    (OUT/'temp').mkdir(exist_ok=True)
    env.update(TEMP=str(OUT/'temp'), TMP=str(OUT/'temp'), EM_PORTS=str(OUT/'ports'),
               BUILD_NAME='v128_text_gui_lazy')
    return env


def frozen_proof():
    groups = json.loads((OUT/'frozen-inputs.json').read_bytes())
    for rows in groups.values():
        for row in rows:
            assert digest(row['file']) == row['sha256'], row['file']
    return {key:len(rows) for key,rows in groups.items()}


def prepare():
    assert not OUT.exists(), 'Fresh single-attempt engine directory only'
    source = source_proof(False)
    archive = BASE/'release/godot.web.template_release.wasm32.nothreads.zip'
    assert digest(archive) == ZIP_SHA
    files = [p for group in ('scripts','shaders','scenes','assets')
             for p in (ROOT/'godot'/group).rglob('*') if p.is_file()]
    files.append(ROOT/'godot/project.godot')
    release = [p for p in (BASE/'release').rglob('*') if p.is_file()]
    staged = [ROOT/'artifacts/v134'/name for name in
              ('index.pck','index-balanced.pck','index-lite.pck','index.js','index.wasm')]
    policies = [ROOT/'godot/engine-patches/text-gui-web-v128.json',
                SRC/'modules/modules_enabled.gen.h', SRC/'core/disabled_classes.gen.h']
    OUT.mkdir(parents=True)
    (OUT/'baseline').mkdir()
    shutil.copyfile(archive, OUT/'baseline'/archive.name)
    write_json(OUT/'frozen-inputs.json', {key:[info(p) for p in rows] for key,rows in
        (('project',files),('oldRelease',release),('staged',staged),('policy',policies))})
    write_json(OUT/'preflight.json', {'sourceProof':source,'command':arguments(),'baselineZip':info(archive)})
    print(json.dumps({'prepared':True,'sourceFiles':source['upstreamFilesChecked']}), flush=True)


def build():
    assert not (OUT/'build.log.json').exists(), 'One build attempt; no hidden retries'
    before = json.loads((OUT/'preflight.json').read_bytes())
    assert arguments() == before['command']
    record = {'schema':'v135-deferred-shader-validation-build-v1', 'command':arguments(),
              'cwd':str(SRC),'sourceProof':source_proof(True),'frozenCounts':frozen_proof(),
              'startedUtc':datetime.now(timezone.utc).isoformat(),'workerCaps':4,
              'identicalModuleAndCompilerFlags':True,'oneIncrementalBuild':True}
    write_json(OUT/'build.log.json', record)
    started = time.monotonic()
    with (OUT/'build.log').open('xb') as log:
        process = subprocess.Popen(record['command'],cwd=SRC,env=child_environment(),stdout=log,
            stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        record['processId'] = process.pid
        write_json(OUT/'build.log.json', record, update=True)
        print(json.dumps({'started':True,'pid':process.pid,'caps':4}),flush=True)
        code = process.wait()
    record.update(exitCode=code,elapsedSeconds=round(time.monotonic()-started,3),
                  finishedUtc=datetime.now(timezone.utc).isoformat())
    write_json(OUT/'build.log.json',record,update=True)
    print(json.dumps({key:record[key] for key in ('exitCode','elapsedSeconds','finishedUtc')}),flush=True)
    raise SystemExit(code)


def collect():
    record = json.loads((OUT/'build.log.json').read_bytes())
    assert record.get('exitCode') == 0 and record['command'] == arguments()
    proof = source_proof(True)
    proof['frozenCounts'] = frozen_proof()
    log = (OUT/'build.log').read_text(encoding='utf-8',errors='replace')
    units = re.findall(r'^Compiling (.+)$',log,re.M)
    assert any(CPP in row.replace('\\','/') for row in units)
    proof.update(compiledUnits=units,allFrozenFilesExact=True)
    write_json(OUT/'source-proof.json',proof)
    archive = SRC/'bin/godot.web.template_release.wasm32.nothreads.zip'
    assert archive.stat().st_mtime >= datetime.fromisoformat(record['startedUtc']).timestamp()
    release = OUT/'release'
    release.mkdir(exist_ok=False)
    target = release/archive.name
    shutil.copyfile(archive,target)
    assert digest(target) == digest(archive) and digest(target) != ZIP_SHA
    rows = []
    with zipfile.ZipFile(target) as zipped:
        assert zipped.testzip() is None
        for member in ('godot.js','godot.wasm','godot.audio.worklet.js','godot.audio.position.worklet.js'):
            data = zipped.read(member)
            name = 'index'+member.removeprefix('godot')
            file = release/name
            file.write_bytes(data)
            gz,br = gzip.compress(data,6,mtime=0),brotli_bytes(data)
            assert gzip.decompress(gz) == data
            (release/(name+'.gz')).write_bytes(gz)
            (release/(name+'.br')).write_bytes(br)
            if 'worklet' in name:
                assert data == (BASE/'release'/name).read_bytes()
            rows.append({'path':name,**info(file),'gzip':info(release/(name+'.gz')),'brotli':info(release/(name+'.br'))})
    for name in ('LICENSE.txt','COPYRIGHT.txt','AUTHORS.md'):
        shutil.copyfile(SRC/name,release/name)
    node = next((SRC.parent/'emsdk/node').glob('*/node.exe'))
    for script,label in ((ROOT/'artifacts/startup-v126/engine/inspect_engine.mjs','module-validation'),
                         (ENGINE/'inspect_instantiation.mjs','instantiation-validation')):
        result = subprocess.run([str(node),'--v8-pool-size=1',str(script),str(BASE/'release/index'),str(release/'index')],
            capture_output=True,text=True,timeout=90,env=child_environment(),creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode == 0,result.stdout+result.stderr
        write_json(OUT/(label+'.json'),json.loads(result.stdout))
    assert memory((BASE/'release/index.wasm').read_bytes()) == memory((release/'index.wasm').read_bytes())
    write_json(OUT/'engine-manifest.json',{'schema':'v135-deferred-shader-validation-release-v1',
        'templateZip':info(target),'engineFiles':rows,'sourceProof':proof,'sameMemoryLimits':True,
        'sameModuleFlags':True,'actualBrowserGlValidation':'pending','tenSecondTarget':'unverified'})
    print(json.dumps({'templateZip':info(target),'engineFiles':rows},indent=2),flush=True)


if __name__ == '__main__':
    import gzip
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('prepare','build','collect'))
    {'prepare':prepare,'build':build,'collect':collect}[parser.parse_args().mode]()
