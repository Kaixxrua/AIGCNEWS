import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import refresh


def item(item_id, provider='neobrutalism', files=(('a.tsx', '1'),)):
    return {'id': item_id, 'provider_id': provider,
            'files': [{'name': name, 'path': f'sources/{provider}/{name}', 'sha256': digest} for name, digest in files]}


class SelectionTests(unittest.TestCase):
    def test_only_new_unrejected_ids_are_selected(self):
        held_item = item('neobrutalism-held')
        items = [item('neobrutalism-card'), item('neobrutalism-new'), item('neobrutalism-rejected'),
                 item('neobrutalism-gone'), held_item, item('hyperui-button', 'hyperui'), item('../x')]
        fresh, skipped = refresh.select_new(
            items, catalog_ids={'neobrutalism-card'}, known={'neobrutalism-rejected'},
            blocked={'neobrutalism-gone'},
            held={'neobrutalism-held': {'fingerprint': refresh.fingerprint(held_item), 'reason': 'blank_poster'}})
        self.assertEqual([row['id'] for row in fresh], ['neobrutalism-new'])
        self.assertEqual({row['id']: row['reason'] for row in skipped}, {
            'neobrutalism-rejected': 'rejected_at_reviewed_baseline',
            'neobrutalism-gone': 'withdrawn',
            'neobrutalism-held': 'held_unchanged:blank_poster',
            'hyperui-button': 'withdrawn_provider',
            '../x': 'invalid_id',
        })

    def test_identical_sources_under_another_name_are_skipped(self):
        items = [item('neobrutalism-button'), item('neobrutalism-nbutton'), item('neobrutalism-card', files=(('c.tsx', '3'),))]
        published = item('neobrutalism-old', files=(('c.tsx', '3'),))
        fresh, skipped = refresh.select_new(items, catalog_ids=set(), known=set(), blocked=set(), held={},
                                            seen={refresh.fingerprint(published)})
        self.assertEqual([row['id'] for row in fresh], ['neobrutalism-button'])
        self.assertEqual({row['id'] for row in skipped if row['reason'] == 'duplicate_source'},
                         {'neobrutalism-nbutton', 'neobrutalism-card'})

    def test_changed_sources_retry_a_held_candidate(self):
        old = item('neobrutalism-card')
        new = item('neobrutalism-card', files=(('a.tsx', '2'),))
        fresh, _ = refresh.select_new([new], catalog_ids=set(), known=set(), blocked=set(),
                                      held={'neobrutalism-card': {'fingerprint': refresh.fingerprint(old), 'reason': 'render_failed'}})
        self.assertEqual(fresh, [new])

    def test_manual_removal_of_a_refresher_publication_blocks_it(self):
        state = {'withdrawn': ['hyperui-a'], 'published': {'eldoraui-a': {}, 'eldoraui-b': {}}}
        self.assertEqual(refresh.blocked_ids(state, {'eldoraui-b'}), {'hyperui-a', 'eldoraui-a'})

    def test_round_robin_spreads_the_limit_across_providers(self):
        groups = {'b': [{'id': 'b1'}, {'id': 'b2'}, {'id': 'b3'}], 'a': [{'id': 'a1'}], 'c': []}
        self.assertEqual([row['id'] for row in refresh.round_robin(groups, 3)], ['a1', 'b1', 'b2'])
        self.assertEqual(refresh.round_robin(groups, 0), [])


class SourceLayoutTests(unittest.TestCase):
    def test_nested_checkout_license_is_repository_relative(self):
        source = {'checkout': 'eldoraui/apps/www', 'license_source': '../../LICENSE.md'}
        self.assertEqual(refresh.checkout_parts('import_batch_registry_sources', 'eldoraui', source), ('eldoraui', 'apps/www'))
        self.assertEqual(refresh.license_path('import_batch_registry_sources', 'eldoraui', source), 'LICENSE.md')
        self.assertEqual(refresh.checkout_parts('import_batch4_demo_sources', 'visx', {'license_source': 'LICENSE'}), ('visx', ''))
        with self.assertRaises(refresh.Hold):
            refresh.license_path('import_batch_registry_sources', 'x', {'checkout': 'x', 'license_source': '../LICENSE'})

    def test_registered_sources_are_unique_and_pinned(self):
        for provider_id, (_, source) in refresh.registry().items():
            self.assertRegex(source['revision'], refresh.SHA, provider_id)
            self.assertRegex(source['license_sha256'], '^[0-9a-f]{64}$', provider_id)
            self.assertRegex(source['repository'], refresh.REPOSITORY, provider_id)
            self.assertNotIn(provider_id, refresh.WITHDRAWN_PROVIDERS)

    def test_git_env_drops_hook_repository_overrides(self):
        original = dict(refresh.os.environ)
        try:
            refresh.os.environ.update(GIT_DIR='/elsewhere', GIT_INDEX_FILE='/x', GIT_SSH_COMMAND='ssh -i key')
            env = refresh.git_env()
        finally:
            refresh.os.environ.clear()
            refresh.os.environ.update(original)
        self.assertNotIn('GIT_DIR', env)
        self.assertNotIn('GIT_INDEX_FILE', env)
        self.assertEqual(env['GIT_SSH_COMMAND'], 'ssh -i key')


class EvidenceAndCommitTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.checkout = self.root / 'checkout'
        self.checkout.mkdir()
        (self.checkout / 'LICENSE').write_text('MIT License\n')
        (self.checkout / 'README.md').write_text('# Readme\n')

    def tearDown(self):
        self.directory.cleanup()

    def test_evidence_uses_pinned_bytes_and_only_grows(self):
        target = self.root / 'evidence'
        rev = 'a' * 40
        record = refresh.evidence_record('o/r', rev, 'MIT', 'LICENSE', 'README.md', self.checkout, target, {'s/a': '1'})
        self.assertEqual([r['name'] for r in record['resources']], ['LICENSE', 'README.md'])
        self.assertEqual(record['resources'][0]['sha256'], refresh.sha(b'MIT License\n'))
        self.assertIn(f'/o/r/{rev}/LICENSE', record['resources'][0]['url'])
        self.assertEqual((target / 'README.md').read_text(), '# Readme\n')
        refresh.write_json(target / 'manifest.json', record)
        merged = refresh.evidence_record('o/r', rev, 'MIT', 'LICENSE', 'README.md', self.checkout, target, {'s/b': '2'})
        self.assertEqual(merged['source_files'], {'s/a': '1', 's/b': '2'})
        with self.assertRaises(refresh.Hold):
            refresh.evidence_record('o/r', rev, 'MIT', 'LICENSE', 'README.md', self.checkout, target, {'s/a': '9'})
        with self.assertRaises(refresh.Hold):
            refresh.evidence_record('o/r', rev, 'Apache-2.0', 'LICENSE', 'README.md', self.checkout, target, {})

    def test_evidence_without_readme_waits_for_review(self):
        with self.assertRaises(refresh.Hold):
            refresh.evidence_record('o/r', 'b' * 40, 'MIT', 'LICENSE', None, self.checkout, self.root / 'e2', {})

    def test_copy_new_never_overwrites_content(self):
        source = self.root / 'source'
        source.write_text('one')
        target = self.root / 'out/target'
        self.assertTrue(refresh.copy_new(source, target))
        self.assertFalse(refresh.copy_new(source, target))
        source.write_text('two')
        with self.assertRaises(RuntimeError):
            refresh.copy_new(source, target)
        self.assertEqual(target.read_text(), 'one')

    def test_commit_appends_items_and_refuses_a_moved_catalog(self):
        production, staging = self.root / 'prod', self.root / 'stage'
        previews, production_previews = self.root / 'previews', self.root / 'prod-previews'
        for base in (production, staging):
            refresh.write_json(base / 'catalog.json', {'items': [{'id': 'old'}]})
            refresh.write_json(base / 'upstreams.json', {'old': {'revision': '1'}})
        evidence = 'assets/p/evidence/' + 'c' * 40
        for relative, text in (('sources/p/rcccccccccccc/a.tsx', 'x'), ('licenses/p/LICENSE', 'MIT'),
                               ('posters/p-a-c.webp', 'poster'), ('clips/p-a-c.mp4', 'clip'),
                               (evidence + '/LICENSE', 'MIT'), (evidence + '/license-page.png', 'png')):
            (staging / relative).parent.mkdir(parents=True, exist_ok=True)
            (staging / relative).write_text(text)
        refresh.write_json(staging / evidence / 'manifest.json', {'source_files': {}})
        previews.mkdir()
        for suffix in ('html', 'js', 'css', 'build.json'):
            (previews / f'p-a.{suffix}').write_text(suffix)
        new = {'id': 'p-a', 'files': [{'path': 'sources/p/rcccccccccccc/a.tsx'}],
               'notices': [{'path': 'licenses/p/LICENSE'}], 'assets': [],
               'poster_url': '/ui-library/posters/p-a-c.webp', 'clip_url': '/ui-library/clips/p-a-c.mp4',
               'rights_evidence_url': '/ui-library/' + evidence + '/manifest.json'}
        with self.assertRaises(RuntimeError):
            refresh.commit(production, production_previews, staging, previews, [new], 'stale', {})
        catalog_sha = refresh.sha((production / 'catalog.json').read_bytes())
        refresh.commit(production, production_previews, staging, previews, [new], catalog_sha, {'p': {'revision': 'c' * 40}})
        self.assertEqual([row['id'] for row in json.loads((production / 'catalog.json').read_text())['items']], ['old', 'p-a'])
        self.assertEqual(set(json.loads((production / 'upstreams.json').read_text())), {'old', 'p'})
        self.assertEqual(sorted(path.name for path in production_previews.iterdir()), ['p-a.css', 'p-a.html', 'p-a.js'])
        self.assertTrue((production / evidence / 'license-page.png').is_file())

    def test_gc_scope_keeps_only_chosen_files(self):
        root = self.root / 'data'
        for name in ('keep.tsx', 'drop.tsx', 'dir/drop.tsx'):
            path = root / 'sources/p/r1/' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
        refresh.gc_scope(root, 'p', 'r1/', {'sources/p/r1/keep.tsx'})
        self.assertEqual([p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()], ['sources/p/r1/keep.tsx'])

    def test_break_link_gives_staging_its_own_inode(self):
        original = self.root / 'original'
        original.write_text('data')
        linked = self.root / 'linked'
        linked.hardlink_to(original)
        refresh.break_link(linked)
        linked.write_text('changed')
        self.assertEqual(original.read_text(), 'data')

    def test_withdrawal_policy_fails_closed(self):
        state = self.root / 'state'
        refresh.write_json(state / 'withdrawn.json', {'version': 1, 'ids': ['../catalog']})
        with self.assertRaises(ValueError):
            refresh.load_state(state)


class UpstreamTests(unittest.TestCase):
    def test_unsafe_repository_or_revision_is_refused(self):
        upstreams = refresh.Upstreams(Path('/nonexistent'), Path('/dev/null'))
        with self.assertRaises(refresh.Hold):
            upstreams.head('https://evil/x')
        with self.assertRaises(refresh.Hold):
            upstreams.checkout('owner/repo', 'HEAD')

    def test_checkout_fetches_the_pinned_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            origin = root / 'origin'
            env = refresh.git_env() | {'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't',
                                       'GIT_COMMITTER_EMAIL': 't@t'}
            subprocess.run(['git', 'init', '-q', origin], check=True, env=env)
            (origin / 'LICENSE').write_text('MIT License\n')
            subprocess.run(['git', '-C', origin, 'add', '.'], check=True, env=env)
            subprocess.run(['git', '-C', origin, 'commit', '-qm', 'x'], check=True, env=env)
            revision = subprocess.check_output(['git', '-C', origin, 'rev-parse', 'HEAD'], text=True, env=env).strip()
            upstreams = refresh.Upstreams(root / 'cache', root / 'log')
            original = refresh.run

            def local(args, **kwargs):
                return original([str(origin) if str(a).startswith('https://github.com/') else a for a in args], **kwargs)
            refresh.run = local
            try:
                checkout = upstreams.checkout('owner/repo', revision)
            finally:
                refresh.run = original
            self.assertEqual((checkout / 'LICENSE').read_text(), 'MIT License\n')
            self.assertTrue((checkout / '.refresh-complete').is_file())
            upstreams.prune({})
            self.assertFalse(checkout.exists())


if __name__ == '__main__':
    unittest.main()
