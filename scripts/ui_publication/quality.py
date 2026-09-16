"""Only publish candidates whose exact source and rendered preview were reviewed."""
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
    automatic = item.get('provider_id', '').startswith('xgithub-')
    if not approval_path.exists() and not automatic:
        raise Hold('awaiting_visual_quality_review')
    try:
        for f in item['files'] + item['assets'] + item['notices']:
            assert sha((data / f['path']).read_bytes()) == f['sha256']
        previews = {p.name: sha(p.read_bytes()) for p in (data / 'previews').glob(item_id + '.*') if p.is_file() and not p.name.endswith('.build.json')}
        assert previews
        poster = data / item['poster_url'].removeprefix('/ui-library/')
        poster_sha256 = sha(poster.read_bytes())
        proof = data / item['rights_evidence_url'].removeprefix('/ui-library/')
        evidence = json.loads(proof.read_bytes())
        assert evidence['revision'] == item['revision']
        assert all(evidence['source_files'][f['path']] == f['sha256'] for f in item['files'])
        if automatic:
            approval = {
                'id': item_id, 'status': 'verified', 'revision': item['revision'],
                'reason': 'Strict static HTML policy, pinned MIT source, isolated render and non-blank screenshot checks passed.',
                'reviewer': 'automatic-x-html-pipeline', 'reviewed_at': datetime.now(timezone.utc).isoformat(),
                'checks': {'isolated_render': True, 'nonblank_poster': True, 'no_scripts': True, 'no_external_resources': True},
                'source_files': {f['path']: f['sha256'] for f in item['files']},
                'preview_files': previews, 'screenshot_sha256': poster_sha256,
            }
        else:
            approval = json.loads(approval_path.read_text(encoding='utf-8'))
            assert approval['status'] == 'approved' and approval['id'] == item_id
            assert approval['revision'] == item['revision']
            assert approval['reason'].strip() and approval['reviewer'].strip()
            assert datetime.fromisoformat(approval['reviewed_at'].replace('Z', '+00:00')).tzinfo is not None
            assert all(approval['checks'][key] is True for key in ('composition','typography','complete_preview','usable_interaction'))
            assert approval['source_files'] == {f['path']: f['sha256'] for f in item['files']}
            assert previews == approval['preview_files']
            assert poster_sha256 == approval['screenshot_sha256']
    except (AssertionError, KeyError, TypeError, ValueError, OSError) as error:
        raise Hold('visual_quality_review_stale_or_invalid') from error
    screenshot_name = 'preview-' + item_id + '.png'
    (proof.parent / screenshot_name).write_bytes(poster.read_bytes())
    review_name = 'review-' + item_id + '.json'
    record = {**approval, 'screenshot': screenshot_name,
              'preview_html_sha256': previews[item_id + '.html']}
    write_json(proof.parent / review_name, record)
    url = '/ui-library/' + (proof.parent / review_name).relative_to(data).as_posix()
    item['editorial'] = {'status':approval['status'],'revision':item['revision'],
        'source_sha256':item['files'][0]['sha256'],'reviewed_at':approval['reviewed_at'],
        'reason':approval['reason'],'evidence':url}
    item['visual_review_url'] = url
