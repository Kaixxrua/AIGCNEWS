import copy
import importlib.util
import io
import json
import sys
import tempfile
import tarfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
from adapter import Hold, blob_sha, checked_path, make_item, sha, validate_license, validate_source
from release import Release

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'mcp-go/internal/uicatalog/data'
SEED = Path(__file__).parent / 'fixtures/hyperui'


class PolicyTests(unittest.TestCase):
    def test_original_license_and_scoped_notices(self):
        license_raw = (SEED/'licenses/hyperui/LICENSE').read_bytes()
        helper = (SEED/'sources/hyperui/public/component.js').read_bytes()
        payload = {'repo':'markmead/hyperui','source_revision':'a'*40,'license_files':[{'path':'LICENSE','sha':blob_sha(license_raw)},{'path':'.agents/skills/frontend-design/LICENSE.txt','sha':'f433b1a53f5b830a205fd2df78e2b34974656c7b'}]}
        validate_license(payload,license_raw,helper)
        for changed in (license_raw+b' Noncommercial only', license_raw.replace(b'Permission',b'Restriction')):
            with self.assertRaises(Hold):
                validate_license(payload,changed,helper)
        payload['license_files'].append({'path':'public/examples/LICENSE','sha':'b'*40})
        with self.assertRaises(Hold):
            validate_license(payload,license_raw,helper)

    def test_hostile_and_external_markup_is_held(self):
        for content in ('<img src="https://example.org/x.png">','<script>alert(1)</script>','<svg><foreignObject>x</foreignObject></svg>','<a href="jav&#97;script:alert(1)">x</a>','<button onclick="alert(1)">x</button>','<form action="/payment">x</form>','<iframe srcdoc="x"></iframe>','<style>@import "https://x";</style>'):
            raw=('<body>'+content+'</body>').encode()
            with self.subTest(content=content), self.assertRaises(Hold):
                validate_source(raw,blob_sha(raw))

    def test_safe_markup_hash_and_dedupe(self):
        raw=b'<body><button class="p-4">Action</button></body>'
        self.assertEqual(validate_source(raw,blob_sha(raw)),validate_source(raw.replace(b'>Action',b'>Action'),blob_sha(raw)))
        with self.assertRaises(Hold):
            validate_source(raw,'0'*40)
        for path in ('../../LICENSE','public/examples/../x/1.html','public/examples/application/buttons/1-dark.html'):
            with self.assertRaises(Hold):
                checked_path(path)

    def test_original_source_is_preserved_and_first_added_explicit(self):
        template=json.loads((SEED/'template.json').read_text(encoding='utf-8'))
        before=copy.deepcopy(template)
        template['editorial']={'status':'approved'}
        template['kind']='theme'
        template['styles']=['retro']
        payload={'path':'public/examples/application/badges/999.html','source_revision':'a'*40,'source_url':'https://github.com/markmead/hyperui/blob/'+'a'*40+'/public/examples/application/badges/999.html'}
        raw=b'<body><button>Original</button></body>\r\n'
        with tempfile.TemporaryDirectory() as folder:
            item=make_item(Path(folder),template,payload,raw,'2026-09-11T00:00:00Z')
            self.assertEqual((Path(folder)/item['files'][0]['path']).read_bytes(),raw)
            self.assertEqual(item['files'][0]['sha256'],sha(raw))
            self.assertEqual(item['added_at'],'2026-09-11T00:00:00Z')
            self.assertEqual(item['preview_kind'],'html')
            self.assertEqual(item['clip_url'],'')
            self.assertNotIn('editorial',item)
            self.assertEqual(item['kind'],'component')
            self.assertEqual(item['subcategory'],'badges')
            self.assertEqual(item['styles'],[])
            self.assertEqual(template['files'],before['files'])

    def test_concurrent_origin_change_blocks_release_before_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            obj=Release.__new__(Release)
            obj.compose_path=Path(folder)/'compose.yml'
            obj.compose_path.write_bytes(b'changed')
            obj.compose_before=b'original'
            with self.assertRaisesRegex(RuntimeError,'concurrent_origin_change'):
                obj.publish()

    def test_catalog_cache_observes_atomic_replacement(self):
        from types import ModuleType
        config=ModuleType('backend.app.core.config'); config.settings=object()
        tiers=ModuleType('backend.app.services.membership.tiers'); tiers.resolve_effective_tier=lambda _:None
        spec=importlib.util.spec_from_file_location('publication_cache_test',ROOT/'backend/app/services/ui_library.py')
        module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'backend.app.core.config':config,'backend.app.services.membership.tiers':tiers}):
            spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'catalog.json'
            path.write_text('{"items":[{"id":"old"}]}')
            self.assertEqual(module.catalog_ids(str(path)),frozenset({'old'}))
            target=Path(folder)/'next.json'
            target.write_text('{"items":[{"id":"old"},{"id":"new"}]}')
            target.replace(path)
            self.assertEqual(module.catalog_ids(str(path)),frozenset({'old','new'}))

    def test_rollback_restores_catalog_and_keeps_unrelated_compose_edit(self):
        with tempfile.TemporaryDirectory() as folder:
            obj=Release.__new__(Release)
            obj.run=Path(folder); obj.switched=True
            obj.catalog_path=obj.run/'catalog.json'; obj.catalog_before=b'old'
            obj.catalog_path.write_bytes(b'new')
            (obj.run/'dist/ui-library').mkdir(parents=True)
            (obj.run/'dist/ui-library/catalog.json').write_bytes(b'new')
            obj.compose_path=obj.run/'compose.yml'
            obj.compose_path.write_text('image: new-image\nother: user-change\n')
            obj.old_images={'frontend-web':'old-image'}; obj.images={'frontend-web':'new-image'}
            obj.command=lambda args:'new-image'
            calls=[]
            obj.edge=lambda phase:calls.append(phase)
            obj.compose=lambda images:calls.append(images)
            obj.rollback()
            self.assertEqual(obj.catalog_path.read_bytes(),b'old')
            self.assertEqual(obj.compose_path.read_text(),'image: old-image\nother: user-change\n')
            self.assertEqual(calls,['rollback',{'frontend-web':'old-image'}])

    def test_rollback_refuses_a_later_deployment(self):
        obj=Release.__new__(Release); obj.switched=True
        obj.old_images={'frontend-web':'old'}; obj.images={'frontend-web':'ours'}
        obj.command=lambda args:'someone-elses-new-release'
        with self.assertRaisesRegex(RuntimeError,'concurrent_release_blocks_rollback'):
            obj.rollback()

    def test_sync_publishes_new_bytes_and_preserves_unrelated_files(self):
        with tempfile.TemporaryDirectory() as folder:
            obj=Release.__new__(Release); obj.root=Path(folder); obj.run=obj.root/'run'
            (obj.run/'dist/ui-library/sources').mkdir(parents=True)
            values={'ui-library/catalog.json':b'new catalog','ui-library/sources/new.html':b'original source','index.html':b'unchanged app'}
            for name,raw in values.items():
                (obj.run/'dist'/name).write_bytes(raw)
            (obj.run/'artifact-manifest.json').write_text(json.dumps({name:sha(raw) for name,raw in values.items()}))
            with tarfile.open(obj.run/'before-artifact.tar','w') as archive:
                for name,raw in {'./ui-library/catalog.json':b'old catalog','./index.html':b'unchanged app'}.items():
                    info=tarfile.TarInfo(name); info.size=len(raw); archive.addfile(info,io.BytesIO(raw))
            for relative in ('frontend/dist','local/edge/artifact'):
                target=obj.root/relative; target.mkdir(parents=True)
                (target/'index.html').write_bytes(b'user-owned unrelated change')
            obj.sync()
            for relative in ('frontend/dist','local/edge/artifact'):
                target=obj.root/relative
                self.assertEqual((target/'index.html').read_bytes(),b'user-owned unrelated change')
                self.assertEqual((target/'ui-library/catalog.json').read_bytes(),b'new catalog')
                self.assertEqual((target/'ui-library/sources/new.html').read_bytes(),b'original source')
            self.assertEqual((obj.root/'mcp-go/internal/uicatalog/data/sources/new.html').read_bytes(),b'original source')


if __name__=='__main__':
    unittest.main()
