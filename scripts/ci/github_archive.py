"""Archive deployed local deliveries on GitHub without running Actions."""
from __future__ import annotations

import json
import os
import re
import stat
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import local_delivery as d


class GitHub:
    def __init__(self, config):
        match = re.fullmatch(r'git@github.com:([\w.-]+/[\w.-]+)\.git', config['github_url'])
        if not match:
            raise ValueError('archive requires a github.com SSH repository URL')
        self.repo = match[1]
        path = Path(config['github_archive_token_file'])
        if path.stat().st_uid != os.getuid() or stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ValueError('GitHub credential file must be private and controller-owned')
        self.token = path.read_text().strip()
        if not self.token:
            raise ValueError('GitHub credential is empty')

    def call(self, method, path, body=None):
        request = urllib.request.Request(
            'https://api.github.com/repos/'+self.repo+'/'+path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer '+self.token,
                     'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json'},
            method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            # Never persist request headers or arbitrary response bodies.
            raise RuntimeError(f'GitHub {method} {path.split("?")[0]} returned HTTP {exc.code}') from None

    def disabled(self):
        if self.call('GET', 'actions/permissions').get('enabled') is not False:
            raise RuntimeError('GitHub Actions must be disabled at repository level before archive writes')


def push(config, api, *refspecs):
    api.disabled()
    d.command(['git', '--git-dir', config['bare'], 'push', '--atomic',
               config['github_url'], *refspecs], timeout=90)


def deployed(config, db):
    release = d.meta(db, 'release')
    sha = release.get('sha')
    if release.get('status') != 'delivered' or not d.SHA.fullmatch(sha or ''):
        return None
    control = Path(config['production'])/'.aigcnews-deploy'
    state = json.loads((control/'state.json').read_text())
    edge = json.loads((control/'edge-state.json').read_text())
    sites = json.loads((control/'edge-config.json').read_text())['sites']
    if (state.get('active_release') != sha or state.get('in_progress') or not sites
            or edge.get('source_sha') != sha
            or not state.get('images', {}).get('frontend')
            or edge.get('frontend_image') != state['images']['frontend']
            or any(edge.get('sites', {}).get(site) != 'published' for site in sites)
            or not d.ancestor(config, sha, d.git(config, 'rev-parse', 'refs/heads/main'))):
        raise RuntimeError('archive requires matching source and all edge deployment receipts')
    return sha


def archive_task(config, db, api, task, release, remote_main):
    key = f"github_archive:{task['id']}"
    receipt = d.meta(db, key)
    if receipt.get('status') == 'merged':
        return
    sha = task['sha']
    head = f"archive/task-{task['id']}-{sha[:12]}"
    base = 'main'
    # Already mirrored history cannot open a PR against main. Preserve its real
    # diff on a dedicated archival base; never rewind main or manufacture commits.
    historical = d.ancestor(config, sha, remote_main)
    if historical:
        base = f"archive/base-{task['id']}-{sha[:12]}"
    if receipt.get('number'):
        pr = api.call('GET', f"pulls/{receipt['number']}")
    else:
        query = urllib.parse.urlencode({'state': 'all', 'head': api.repo.split('/')[0]+':'+head,
                                        'base': base, 'per_page': 100})
        found = api.call('GET', 'pulls?'+query)
        if len(found) > 1:
            raise RuntimeError('ambiguous archive PR identity')
        if found:
            pr = found[0]
        else:
            refs = [sha+':refs/heads/'+head]
            if historical:
                parent = d.git(config, 'rev-parse', sha+'^')
                refs.append(parent+':refs/heads/'+base)
            push(config, api, *refs)
            body = (f"本地部署成功后的变更留档。\n\n任务分支：`{task['branch']}`\n"
                    f"源码 SHA：`{sha}`\n上线版本：`{release}`\n\n"
                    "CI、合并及生产发布均由本地交付控制器完成；仓库级 GitHub Actions 已关闭。\n")
            if historical:
                body += '\n历史代码已存在于 main；此 PR 使用独立留档基线保留原始变更，不修改 main 历史。\n'
            api.disabled()
            pr = api.call('POST', 'pulls', {'title': task['title'][:256], 'head': head,
                                           'base': base, 'body': body})
        receipt = {'number': pr['number'], 'url': pr['html_url'], 'head': head,
                   'base': base, 'sha': sha, 'release_sha': release, 'status': 'created'}
        d.meta(db, key, receipt)
    db.execute('UPDATE tasks SET pr=? WHERE id=?', (pr['number'], task['id']))
    db.commit()
    # A retry must never adopt a PR whose refs/commit were changed externally.
    if (pr['head']['sha'] != sha or pr['head']['ref'] != receipt['head']
            or pr['base']['ref'] != receipt['base']
            or pr['head']['repo']['full_name'] != api.repo
            or pr['base']['repo']['full_name'] != api.repo):
        raise RuntimeError('archive PR identity changed')
    if not pr.get('merged_at'):
        if pr['state'] != 'open':
            raise RuntimeError('archive PR was closed without merging')
        if receipt['base'] == 'main':
            return  # Prepare every PR before advancing main once for the batch.
        if deployed(config, db) != release:
            raise RuntimeError('deployment changed while preparing archive')
        # Fast-forwarding the base with the exact head marks the PR merged on
        # GitHub, without introducing GitHub-generated commits into local main.
        push(config, api, sha+':refs/heads/'+receipt['base'])
        pr = api.call('GET', f"pulls/{pr['number']}")
        if not pr.get('merged_at'):
            return  # GitHub recognizes fast-forward merges asynchronously.
    d.meta(db, key, {**receipt, 'status': 'merged', 'merged_at': pr['merged_at']})


def mirror(config, db):
    release = None
    try:
        release = deployed(config, db)
        if release is None:
            d.meta(db, 'mirror', {'status': 'waiting_for_deployment'})
            return
        api = GitHub(config)
        api.disabled()
        remote = api.call('GET', 'git/ref/heads/main')['object']['sha']
        if not d.ancestor(config, remote, release):
            raise RuntimeError('GitHub main diverged or is ahead of the deployed release; refusing rewrite')
        tasks = [dict(row) for row in db.execute(
            "SELECT * FROM tasks WHERE status IN ('landed','delivered') AND branch != 'main' ORDER BY id")]
        eligible = [task for task in tasks if d.ancestor(config, task['sha'], release)
                    and d.ancestor(config, task['landing_sha'], release)]
        pending = [task for task in eligible
                   if d.meta(db, f"github_archive:{task['id']}").get('status') != 'merged']
        # Prioritize new records; existing main PRs wait for the shared main push.
        work = [task for task in pending
                if not d.meta(db, f"github_archive:{task['id']}")]
        work += [task for task in pending if d.meta(db, f"github_archive:{task['id']}").get('base')
                 not in (None, 'main')]
        for task in work[:5]:
            archive_task(config, db, api, task, release, remote)
        all_created = all(d.meta(db, f"github_archive:{task['id']}") for task in eligible)
        if all_created and remote != release:
            if deployed(config, db) != release:
                raise RuntimeError('deployment changed before mirror push')
            push(config, api, release+':refs/heads/main')
        if all_created:
            for task in pending:
                receipt = d.meta(db, f"github_archive:{task['id']}")
                if receipt.get('base') == 'main' and receipt.get('status') != 'merged':
                    archive_task(config, db, api, task, release, remote)
        remaining = sum(d.meta(db, f"github_archive:{task['id']}").get('status') != 'merged'
                        for task in eligible)
        d.meta(db, 'mirror', {'status': 'archiving' if remaining else 'synced', 'sha': release,
                             'remaining_prs': remaining, 'actions_enabled': False,
                             'last_success': d.now()})
    except Exception as exc:  # noqa: BLE001 - mirror never gates local CI/deployment
        d.meta(db, 'mirror', {'status': 'pending', 'sha': release,
                             'error': str(exc), 'last_attempt': d.now()})
