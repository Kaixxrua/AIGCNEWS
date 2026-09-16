import sys
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).parent))
from release import Release

class ReleaseStorageTests(unittest.TestCase):
    def release(self):
        release=Release.__new__(Release)
        release.root=Path('project')
        release.run=Path('project/release')
        release.command=Mock(return_value='')
        return release

    def test_large_artifact_uses_native_disk_and_releases_only_its_volume(self):
        release=self.release()
        release.edge('publish')
        create,worker,cleanup=release.command.call_args_list
        name=create.args[0][-1]
        self.assertRegex(name,r'^aigcnews-ui-edge-[0-9a-f]{32}$')
        self.assertEqual(create.args[0][:3],['docker','volume','create'])
        self.assertIn(name+':/tmp',worker.args[0])
        self.assertIn('--read-only',worker.args[0])
        self.assertFalse(any(arg.startswith('/tmp:rw') for arg in worker.args[0]))
        self.assertEqual(cleanup.args[0],['docker','volume','rm',name])

    def test_worker_failure_is_preserved_after_cleanup(self):
        release=self.release()
        release.command.side_effect=['',RuntimeError('upload failed'),'']
        with self.assertRaisesRegex(RuntimeError,'upload failed'):
            release.edge('publish')
        self.assertEqual(release.command.call_args_list[-1].args[0][:3],['docker','volume','rm'])

    def test_in_use_volume_cleanup_does_not_hide_original_failure(self):
        release=self.release()
        release.command.side_effect=['',RuntimeError('upload failed'),RuntimeError('volume in use')]
        with self.assertRaisesRegex(RuntimeError,'upload failed'):
            release.edge('publish')

    def test_timeout_stops_exact_worker_before_removing_scratch(self):
        release=self.release()
        release.command.side_effect=['',subprocess.TimeoutExpired(['docker','run'],7200),'','']
        with self.assertRaises(subprocess.TimeoutExpired):
            release.edge('publish')
        create,worker,stop,cleanup=release.command.call_args_list
        name=create.args[0][-1]
        self.assertIn(name+'-worker',worker.args[0])
        self.assertEqual(stop.args[0],['docker','stop','--timeout','10',name+'-worker'])
        self.assertEqual(cleanup.args[0],['docker','volume','rm',name])

if __name__=='__main__':unittest.main()
