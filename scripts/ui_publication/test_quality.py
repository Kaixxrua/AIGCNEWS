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
    def test_strict_x_html_can_receive_automated_verified_review(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); data = root / 'data'; source = b'<body>card</body>'
            item = {'id':'x-acme-ui-card','provider_id':'xgithub-9','revision':'a'*40,
                    'files':[{'path':'sources/xgithub-9/card.html','sha256':sha(source)}],
                    'assets':[],'notices':[],'poster_url':'/ui-library/posters/x-acme-ui-card-aaaaaaaaaaaa.webp',
                    'clip_url':'/ui-library/clips/x-acme-ui-card-aaaaaaaaaaaa.mp4',
                    'rights_evidence_url':'/ui-library/assets/xgithub-9/evidence/'+'a'*40+'/manifest.json'}
            values = {'sources/xgithub-9/card.html':source,'previews/x-acme-ui-card.html':b'render',
                      'posters/x-acme-ui-card-aaaaaaaaaaaa.webp':b'picture',
                      'clips/x-acme-ui-card-aaaaaaaaaaaa.mp4':b'0' * 2048}
            for name, raw in values.items():
                path=data/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(raw)
            write_json(data/item['rights_evidence_url'].removeprefix('/ui-library/'), {'revision':item['revision'],'source_files':{item['files'][0]['path']:sha(source)}})
            approve_rendered_candidate(root,data,item)
            self.assertEqual(item['editorial']['status'],'verified')
            record = json.loads((data / item['visual_review_url'].removeprefix('/ui-library/')).read_bytes())
            self.assertEqual(record['reviewer'],'automatic-x-html-pipeline')
            self.assertEqual(record['clip_sha256'],sha(b'0' * 2048))

    def test_empty_public_catalog_can_still_build_private_candidates(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            template = private_hyperui_seed(data)
            self.assertFalse((data / 'catalog.json').exists())
            for f in template['files'][1:] + template['notices'] + template['assets']:
                self.assertEqual(sha((data / f['path']).read_bytes()), f['sha256'])

    def test_rendered_media_is_automatically_verified_and_stale_manual_reviews_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); data = root / 'data'
            item = {'id':'sample','revision':'a'*40,'files':[{'path':'sources/sample.html','sha256':sha(b'original')}],
                    'assets':[],'notices':[],'poster_url':'/ui-library/posters/sample.webp','clip_url':'/ui-library/clips/sample.mp4',
                    'rights_evidence_url':'/ui-library/assets/sample/evidence/manifest.json'}
            values = {'sources/sample.html':b'original','previews/sample.html':b'render','posters/sample.webp':b'picture',
                      'clips/sample.mp4':b'0' * 2048}
            for name, raw in values.items():
                path = data / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
            write_json(data / 'assets/sample/evidence/manifest.json', {'revision':item['revision'],'source_files':{'sources/sample.html':sha(b'original')}})
            approve_rendered_candidate(root, data, item)
            self.assertEqual(item['editorial']['status'],'verified')
            automatic = json.loads((data / item['visual_review_url'].removeprefix('/ui-library/')).read_bytes())
            self.assertEqual(automatic['reviewer'],'automatic-media-pipeline')
            self.assertEqual(automatic['clip_sha256'],sha(b'0' * 2048))
            approval = {'id':'sample','status':'approved','revision':item['revision'],'reason':'Reviewed composition and interaction',
                'reviewer':'test reviewer','reviewed_at':'2026-09-11T07:00:00Z',
                'checks':dict.fromkeys(['composition','typography','complete_preview','usable_interaction'],True),
                'source_files':{'sources/sample.html':sha(b'original')},'preview_files':{'sample.html':sha(b'render')},
                'screenshot_sha256':sha(b'picture'),'clip_sha256':sha(b'0' * 2048)}
            path = root / 'local/ui-publication/quality-approvals/sample.json'
            for change in [{'revision':'b'*40}, {'source_files':{}}, {'preview_files':{}}, {'screenshot_sha256':'0'*64}, {'clip_sha256':'0'*64}, {'checks':{}}]:
                write_json(path, {**approval, **change})
                with self.subTest(change=change), self.assertRaisesRegex(Hold,'stale_or_invalid'):
                    approve_rendered_candidate(root, data, copy.deepcopy(item))
            write_json(path, approval)
            approve_rendered_candidate(root, data, item)
            record = json.loads((data / item['visual_review_url'].removeprefix('/ui-library/')).read_bytes())
            self.assertEqual(record['preview_html_sha256'],sha(b'render'))
            self.assertEqual(record['clip_sha256'],sha(b'0' * 2048))
            self.assertEqual(item['editorial']['revision'],item['revision'])
            (data / 'sources/sample.html').write_bytes(b'changed')
            with self.assertRaisesRegex(Hold,'stale_or_invalid'):
                approve_rendered_candidate(root, data, item)


if __name__ == '__main__':
    unittest.main()
