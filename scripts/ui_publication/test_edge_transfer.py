import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from edge_transfer import reuse_release_files, transfer_args


class TransferTests(unittest.TestCase):
    def controller(self):
        def validate(value):
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,95}', value):
                raise ValueError('Invalid release')
        return SimpleNamespace(validate_release=Mock(side_effect=validate), subprocess=SimpleNamespace(run=Mock()))

    def test_reuse_only_rsync_and_restore_controller_after_failure(self):
        controller = self.controller()
        original = controller.subprocess
        with self.assertRaisesRegex(RuntimeError, 'worker failure'):
            with reuse_release_files(controller, 'prior-release'):
                controller.subprocess.run(['ssh', 'host', 'status'], check=True)
                controller.subprocess.run(['rsync', '-a', 'src/', 'host:incoming/new/'], check=True)
                raise RuntimeError('worker failure')
        self.assertIs(controller.subprocess, original)
        controller.validate_release.assert_called_once_with('prior-release')
        self.assertEqual(original.run.call_args_list[0].args[0], ['ssh', 'host', 'status'])
        self.assertEqual(original.run.call_args_list[1].args[0], ['rsync', '--checksum', '--copy-dest=../../releases/prior-release', '-a', 'src/', 'host:incoming/new/'])

    def test_initial_deploy_has_no_basis_directory(self):
        controller = self.controller()
        original = controller.subprocess
        with reuse_release_files(controller, None):
            self.assertIs(controller.subprocess, original)
        controller.validate_release.assert_not_called()

    def test_reject_unsafe_release_before_starting_transport(self):
        for value in ('../outside', '/etc', 'old;command', 'old/name'):
            controller = self.controller()
            with self.assertRaises(ValueError):
                with reuse_release_files(controller, value):
                    self.fail('Unsafe release was accepted')
            controller.subprocess.run.assert_not_called()

    @unittest.skipUnless(shutil.which('rsync'), 'Requires the deployed rsync runtime')
    def test_real_transfer_reuses_bytes_detects_changes_and_keeps_old_release_independent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old = root / 'releases/prior-release'
            new = root / 'incoming/new-release'
            source = root / 'source'
            for path in (old, new, source):
                path.mkdir(parents=True)
            blob = os.urandom(1024 * 1024)
            (old / 'large.bin').write_bytes(blob)
            (source / 'large.bin').write_bytes(blob)
            os.utime(old / 'large.bin', (1000, 1000))
            os.utime(source / 'large.bin', (2000, 2000))
            (old / 'changed.txt').write_text('old-data')
            (source / 'changed.txt').write_text('new-data')
            for path in (old / 'changed.txt', source / 'changed.txt'):
                os.utime(path, (1000, 1000))
            (old / 'removed.txt').write_text('removed')
            (source / 'added.txt').write_text('added')
            args = transfer_args(['rsync', '-a', '--delete', '--stats', str(source) + '/', str(new) + '/'], 'prior-release')
            result = subprocess.run(args, check=True, capture_output=True, text=True, env={**os.environ, 'LC_ALL': 'C'})
            transferred = re.search(r'Total transferred file size: ([\d,]+) bytes', result.stdout)
            self.assertIsNotNone(transferred, result.stdout)
            self.assertLess(int(transferred[1].replace(',', '')), 100)
            self.assertEqual((new / 'large.bin').read_bytes(), blob)
            self.assertEqual((new / 'changed.txt').read_text(), 'new-data')
            self.assertFalse((new / 'removed.txt').exists())
            self.assertEqual((new / 'added.txt').read_text(), 'added')
            self.assertNotEqual((old / 'large.bin').stat().st_ino, (new / 'large.bin').stat().st_ino)
            (new / 'large.bin').write_bytes(b'replacement')
            self.assertEqual((old / 'large.bin').read_bytes(), blob)
            self.assertEqual((old / 'large.bin').stat().st_mtime, 1000)


if __name__ == '__main__':
    unittest.main()
