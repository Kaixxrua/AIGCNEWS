import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from adapter import Hold, sha, write_json
from quality import approve_rendered_candidate, private_hyperui_seed


class QualityTests(unittest.TestCase):
    def test_empty_public_catalog_can_still_build_private_candidates(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            template = private_hyperui_seed(data)
            self.assertFalse((data / 'catalog.json').exists())
            for f in template['files'][1:] + template['notices'] + template['assets']:
                self.assertEqual(sha((data / f['path']).read_bytes()), f['sha256'])

    def test_running_preview_alone_is_not_approval_and_stale_reviews_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); data = root / 'data'
            item = {'id':'sample','revision':'a'*40,'files':[{'path':'sources/sample.html','sha256':sha(b'original')}],
                    'assets':[],'notices':[],'poster_url':'/ui-library/posters/sample.png',
                    'rights_evidence_url':'/ui-library/assets/sample/evidence/manifest.json'}
            values = {'sources/sample.html':b'original','previews/sample.html':b'render','posters/sample.png':b'picture'}
            for name, raw in values.items():
                path = data / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
            write_json(data / 'assets/sample/evidence/manifest.json', {'revision':item['revision'],'source_files':{'sources/sample.html':sha(b'original')}})
            with self.assertRaisesRegex(Hold, 'awaiting_visual_quality_review'):
                approve_rendered_candidate(root, data, item)
            approval = {'id':'sample','status':'approved','revision':item['revision'],'reason':'Reviewed composition and interaction',
                'reviewer':'test reviewer','reviewed_at':'2026-09-11T07:00:00Z',
                'checks':dict.fromkeys(['composition','typography','complete_preview','usable_interaction'],True),
                'source_files':{'sources/sample.html':sha(b'original')},'preview_files':{'sample.html':sha(b'render')},'screenshot_sha256':sha(b'picture')}
            path = root / 'local/ui-publication/quality-approvals/sample.json'
            for change in [{'revision':'b'*40}, {'source_files':{}}, {'preview_files':{}}, {'screenshot_sha256':'0'*64}, {'checks':{}}]:
                write_json(path, {**approval, **change})
                with self.subTest(change=change), self.assertRaisesRegex(Hold,'stale_or_invalid'):
                    approve_rendered_candidate(root, data, copy.deepcopy(item))
            write_json(path, approval)
            approve_rendered_candidate(root, data, item)
            record = json.loads((data / item['visual_review_url'].removeprefix('/ui-library/')).read_bytes())
            self.assertEqual(record['preview_html_sha256'],sha(b'render'))
            self.assertEqual(item['editorial']['revision'],item['revision'])
            (data / 'sources/sample.html').write_bytes(b'changed')
            with self.assertRaisesRegex(Hold,'stale_or_invalid'):
                approve_rendered_candidate(root, data, item)


if __name__ == '__main__':
    unittest.main()
