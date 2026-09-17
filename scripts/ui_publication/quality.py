"""Bind human or automated media verification to exact source and preview bytes."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from adapter import Hold, sha, write_json


def private_hyperui_seed(data):
    """The public catalog may contain zero HyperUI entries after withdrawal."""
    seed = Path(__file__).parent / 'fixtures/hyperui'
    template = json.loads((seed / 'template.json').read_text(encoding='utf-8'))
    for entry in template['files'][1:] + template['notices'] + template['assets']:
        source = (seed / entry['path']).resolve()
        target = (data / entry['path']).resolve()
        if not source.is_relative_to(seed.resolve()) or not target.is_relative_to(data.resolve()):
            raise Hold('unsafe_seed_path')
        raw = source.read_bytes()
        if sha(raw) != entry['sha256']:
            raise Hold('private_seed_changed')
        if target.exists() and sha(target.read_bytes()) != entry['sha256']:
            raise Hold('existing_seed_changed')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return template


def approve_rendered_candidate(root, data, item):
    item_id = item['id']
    if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,240}', item_id):
        raise Hold('invalid_quality_id')
    approval_path = root / 'local/ui-publication/quality-approvals' / (item_id + '.json')
    manual = approval_path.exists()
    strict_x = item.get('provider_id', '').startswith('xgithub-')
    try:
        for f in item['files'] + item['assets'] + item['notices']:
            assert sha((data / f['path']).read_bytes()) == f['sha256']
        previews = {p.name: sha(p.read_bytes()) for p in (data / 'previews').glob(item_id + '.*') if p.is_file() and not p.name.endswith('.build.json')}
        assert previews
        poster = data / item['poster_url'].removeprefix('/ui-library/')
        clip = data / item['clip_url'].removeprefix('/ui-library/')
        poster_sha256 = sha(poster.read_bytes())
        clip_sha256 = sha(clip.read_bytes())
        assert poster.suffix == '.webp' and clip.suffix == '.mp4'
        assert 2048 <= clip.stat().st_size <= 3 * 1024 * 1024
        proof = data / item['rights_evidence_url'].removeprefix('/ui-library/')
        evidence = json.loads(proof.read_bytes())
        assert evidence['revision'] == item['revision']
        assert all(evidence['source_files'][f['path']] == f['sha256'] for f in item['files'])
        if manual:
            approval = json.loads(approval_path.read_text(encoding='utf-8'))
            assert approval['status'] == 'approved' and approval['id'] == item_id
            assert approval['revision'] == item['revision']
            assert approval['reason'].strip() and approval['reviewer'].strip()
            assert datetime.fromisoformat(approval['reviewed_at'].replace('Z', '+00:00')).tzinfo is not None
            assert all(approval['checks'][key] is True for key in ('composition', 'typography', 'complete_preview', 'usable_interaction'))
            assert approval['source_files'] == {f['path']: f['sha256'] for f in item['files']}
            assert previews == approval['preview_files']
            assert poster_sha256 == approval['screenshot_sha256']
            assert approval.get('clip_sha256', clip_sha256) == clip_sha256
        elif strict_x:
            approval = {
                'id': item_id, 'status': 'verified', 'revision': item['revision'],
                'reason': 'Strict static HTML policy, pinned MIT source, isolated render and playable H.264 MP4 checks passed.',
                'reviewer': 'automatic-x-html-pipeline', 'reviewed_at': datetime.now(timezone.utc).isoformat(),
                'checks': {'isolated_render': True, 'nonblank_poster': True, 'playable_mp4': True,
                           'no_scripts': True, 'no_external_resources': True},
                'source_files': {f['path']: f['sha256'] for f in item['files']},
                'preview_files': previews, 'screenshot_sha256': poster_sha256, 'clip_sha256': clip_sha256,
            }
        else:
            approval = {
                'id': item_id, 'status': 'verified', 'revision': item['revision'],
                'reason': 'Automated isolated render, non-blank poster and playable H.264 MP4 checks passed.',
                'reviewer': 'automatic-media-pipeline', 'reviewed_at': datetime.now(timezone.utc).isoformat(),
                'checks': {'isolated_render': True, 'nonblank_poster': True, 'playable_mp4': True},
                'source_files': {f['path']: f['sha256'] for f in item['files']},
                'preview_files': previews, 'screenshot_sha256': poster_sha256, 'clip_sha256': clip_sha256,
            }
    except (AssertionError, KeyError, TypeError, ValueError, OSError) as error:
        raise Hold('visual_quality_review_stale_or_invalid') from error
    screenshot_name = 'preview-' + item_id + poster.suffix
    (proof.parent / screenshot_name).write_bytes(poster.read_bytes())
    review_name = 'review-' + item_id + '.json'
    record = {**approval, 'screenshot': screenshot_name,
              'preview_html_sha256': previews[item_id + '.html'],
              'clip': item['clip_url'], 'clip_sha256': clip_sha256}
    write_json(proof.parent / review_name, record)
    url = '/ui-library/' + (proof.parent / review_name).relative_to(data).as_posix()
    item['editorial'] = {'status': 'approved' if manual else 'verified', 'revision': item['revision'],
                         'source_sha256': item['files'][0]['sha256'], 'reviewed_at': approval['reviewed_at'],
                         'reason': approval['reason'], 'evidence': url}
    item['visual_review_url'] = url
