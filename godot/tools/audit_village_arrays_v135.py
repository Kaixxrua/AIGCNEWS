"""One authorized sequential pair, 20s each; export real village arrays only."""
import argparse
import math
from pathlib import Path

import audit_static_core_v135 as audit

PROBE = Path(__file__).with_suffix('.gd')
PRIOR = audit.SCOPE / 'actual15-native-03'
CANDIDATE_SHA = '8d7a9e04209cd0154029634d7d8a8c92b90d5ec7f009b821bb1e4b4afe86df95'
MISS = 'MEADOW_STATIC_CACHE_MISS: village-DistantVillage exact-context mismatch'


def stats(left, right):
    audit.require(len(left) == len(right) and len(left) > 0, 'Same nonempty numeric array length')
    deltas = []
    for x, y in zip(left, right):
        x = x if isinstance(x, list) else [x]
        y = y if isinstance(y, list) else [y]
        audit.require(len(x) == len(y) and all(math.isfinite(v) for v in x + y), 'Finite matching components')
        deltas.append([b - a for a, b in zip(x, y)])
    lengths = [math.sqrt(sum(v*v for v in row)) for row in deltas]
    index = max(range(len(lengths)), key=lengths.__getitem__)
    return {'count': len(left), 'differentItems': sum(any(v != 0 for v in row) for row in deltas),
            'maxComponentAbs': max(abs(v) for row in deltas for v in row), 'maxDistance': lengths[index],
            'maxIndex': index, 'maxSource': left[index], 'maxCandidate': right[index],
            'rmsDistance': math.sqrt(sum(v*v for v in lengths)/len(lengths))}


def world(vertices, transform):
    return [[transform['origin'][axis] + sum(transform['columns'][j][axis]*v[j] for j in range(3))
             for axis in range(3)] for v in vertices]


def compare(source, candidate):
    for row in [source, candidate]:
        audit.require(row['status'] == 'OBSERVED' and not row['errors'] and row['readyCount'] == 1, 'Complete error-free observation')
    audit.require(len(source['surfaceArrays']) == len(candidate['surfaceArrays']) == 1, 'One village surface')
    left, right = source['surfaceArrays'][0], candidate['surfaceArrays'][0]
    audit.require(left['primitive'] == right['primitive'] and left['format'] == right['format'], 'Same primitive/format')
    audit.require(len(left['slots']) == len(right['slots']) == 13, 'Every Godot Mesh array slot exported')
    slots = []
    for index, (a, b) in enumerate(zip(left['slots'], right['slots'])):
        audit.require(a['type'] == b['type'], 'Same typed array slot')
        row = {'slot': index, 'type': a['type'], 'exact': a == b}
        if a['values'] is not None:
            row['numeric'] = stats(a['values'], b['values']) if a['values'] else {'count': 0}
        slots.append(row)
    local_vertices = stats(left['slots'][0]['values'], right['slots'][0]['values'])
    world_vertices = stats(world(left['slots'][0]['values'], source['transform']),
                           world(right['slots'][0]['values'], candidate['transform']))
    soil = {}
    for name in source['materials']:
        a, b = source['materials'][name], candidate['materials'][name]
        audit.require(a['shader'] == b['shader'], 'Same actual material shader')
        heights_a, heights_b = a['soil_heights']['values'], b['soil_heights']['values']
        audit.require(len(heights_a) == len(heights_b) == 25, 'All actual 25 soil samples')
        soil[name] = {'heightStatsMeters': stats(heights_a, heights_b),
                      'heights': [{'index': i, 'source': x, 'candidate': y, 'delta': y-x} for i,(x,y) in enumerate(zip(heights_a, heights_b))],
                      'boundsSource': a['soil_bounds']['values'], 'boundsCandidate': b['soil_bounds']['values'],
                      'boundsStats': stats(a['soil_bounds']['values'], b['soil_bounds']['values'])}
    return {'status': 'ACTUAL_ARRAYS_QUANTIFIED_NOT_ACCEPTANCE', 'strictFullSceneStatus': 'FAIL', 'toleranceAdded': False,
            'sourceCore': source['corePack'], 'candidateCore': candidate['corePack'],
            'surfaceSlots': slots, 'vertexLocalMeters': local_vertices, 'vertexWorldDoubleTransformMeters': world_vertices,
            'aabbSource': source['aabb'], 'aabbCandidate': candidate['aabb'], 'soil': soil,
            'limits': ['World positions calculated in double precision from actual exported float32 local arrays/transforms.',
                       'No tolerance/pass threshold; no new grounding query, GPU frame or Web performance claim.']}


def run(out):
    out = out.resolve()
    audit.require(out.is_relative_to(audit.SCOPE) and not out.exists(), 'Fresh owned output only')
    prior = audit.read_json(PRIOR / 'prepared.json')
    engine = prior['engine']
    audit.require(audit.pin(engine['file']) == engine, 'Same prior actual engine')
    requests = {}
    out.mkdir(parents=True)
    for role, digest in [('source', audit.SOURCE_SHA), ('candidate', CANDIDATE_SHA)]:
        original = audit.read_json(prior['requests'][role]['file'])
        audit.require(audit.pin(original['corePack']['file']) == original['corePack'] and original['corePack']['sha256'] == digest, 'Frozen actual PCK')
        entries = audit.pack_entries(original['corePack']['file'])
        names = ['project.binary', 'scripts/meadow_scene.gdc', 'scenes/main.tscn.remap']
        remap = audit.entry_bytes(original['corePack']['file'], names[-1]).decode()
        target = remap.split('res://',1)[1].split('"',1)[0]
        names.append(target)
        if role == 'candidate':
            names.extend(['progressive/static-core/world.scn', 'progressive/static-core/manifest.json', 'progressive/static-core/restore.gdc'])
        directory = out / role
        directory.mkdir()
        request = {'corePack': original['corePack'], 'probe': audit.pin(PROBE), 'role': role,
                   'mountedPins': {name: entries[name]['sha256'] for name in names}, 'out': (directory/'arrays.json').as_posix()}
        request_file = directory/'request.json'
        audit.write_new(request_file, request)
        requests[role] = request
        command = [engine['file'], '--headless', '--path', directory.as_posix(), '--main-pack', original['corePack']['file'],
                   '--log-file', (directory/'engine.log').as_posix(), '--script', PROBE.as_posix(), '--', request_file.as_posix()]
        print('NATIVE_BEGIN ' + role, flush=True)
        result = audit.invoke_bounded(command, directory, 20)
        print('NATIVE_END ' + role + ' ' + str(result['exitCode']) + ' seconds=' + str(result['processWallSecondsNotWebTiming']), flush=True)
        audit.require(result['status'] == 'EXITED' and result['exitCode'] == 0, 'Native failed; outputs preserved')
        log = (directory/'engine.log').read_text(encoding='utf-8')
        audit.require(not any(t in log for t in ['SCRIPT ERROR:', 'ERROR:']), 'Native errors; outputs preserved')
        if role == 'source':
            audit.require(MISS in log, 'Source must reproduce exact-context MISS, not alternate path')
        observed = audit.read_json(directory/'arrays.json')
        audit.require(observed['requestSha256'] == audit.pin(request_file)['sha256'] and observed['corePack'] == request['corePack'], 'Observation bound to exact request')
        # Reproduce the previously observed buffers, not merely a similar run.
        previous = audit.read_json(PRIOR/role/'native.json')['snapshots'][0]['contract']
        audit.require(observed['surfaceArrays'][0]['arraysSha256'] == previous['resources']['DistantVillage/mesh']['surfaces'][0]['arraysSha256'], 'Actual mesh reproduces prior snapshot')
        for name, material in observed['materials'].items():
            for field in ['soil_heights', 'soil_bounds']:
                audit.require(material[field]['sha256'] == previous['resources'][name+'/material_override']['uniforms'][field]['sha256'], 'Actual soil reproduces prior snapshot')
    source, candidate = [audit.read_json(out/role/'arrays.json') for role in ['source','candidate']]
    result = compare(source, candidate)
    result.update(sourceExactContextMissObserved=True, previousMeshAndAllSoilHashesReproduced=True,
                  sourceReport=audit.pin(out/'source/arrays.json'), candidateReport=audit.pin(out/'candidate/arrays.json'),
                  probe=audit.pin(PROBE), engine=engine)
    audit.write_new(out/'comparison.json', result)
    print('CPU_NATIVE_IDLE; comparison=' + str(out/'comparison.json'), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    run(parser.parse_args().out)
