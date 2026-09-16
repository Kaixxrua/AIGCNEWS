import hashlib
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from image_artifacts import prepare_image_contexts, safe_name


class ImageArtifactTests(unittest.TestCase):
    def test_small_update_has_small_context_and_explicit_safe_deletions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old = root / 'old'
            dist = root / 'dist'
            old.mkdir(); dist.mkdir()
            (old / 'large.bin').write_bytes(b'a' * 1024 * 1024)
            (old / 'index.html').write_text('old-page')
            removed = "retired 'source'.js"
            (old / removed).write_text('old source')
            with tarfile.open(root / 'before-artifact.tar', 'w') as archive:
                for path in old.iterdir():
                    archive.add(path, arcname='./' + path.name)
            (dist / 'large.bin').write_bytes((old / 'large.bin').read_bytes())
            (dist / 'index.html').write_text('new-page')
            (dist / 'new.js').write_text('new module')
            (root / 'mcp-server').write_bytes(b'program')
            files = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in dist.iterdir()}
            contexts = prepare_image_contexts(root, {'frontend-web':'local:frontend','mcp-api-go':'local:mcp'}, files)
            frontend = contexts['frontend-web']
            with tarfile.open(frontend / 'frontend-delta.tar.gz') as archive:
                self.assertEqual(set(archive.getnames()), {'index.html','new.js'})
            self.assertLess(sum(p.stat().st_size for p in frontend.iterdir()), 4096)
            lines = (frontend / 'Dockerfile').read_text().splitlines()
            self.assertEqual(lines[0], 'FROM local:frontend')
            self.assertEqual(json.loads(lines[1].removeprefix('RUN ')), ['rm','-f','--','/usr/share/nginx/html/' + removed])
            self.assertEqual({p.name for p in contexts['mcp-api-go'].iterdir()}, {'Dockerfile','mcp-server'})
            self.assertEqual((old / 'large.bin').stat().st_size, 1024 * 1024)

    def test_reject_paths_that_could_escape_image_root(self):
        for name in ('../outside', '/absolute', 'C:/outside', 'dir/../../outside', 'a\\b', 'bad\nname', '.'):
            with self.assertRaises(ValueError):
                safe_name(name)


if __name__ == '__main__':
    unittest.main()
