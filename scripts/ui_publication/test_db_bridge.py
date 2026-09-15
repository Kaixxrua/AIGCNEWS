"""Exercise candidate-state compatibility without writing to a real database."""
import contextlib
import io
import json
import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class BridgeTests(unittest.TestCase):
    def invoke(self, request):
        calls = []
        class Connection:
            def execute(self, sql, params=None):
                calls.append((sql, params)); return self
            def fetchall(self):
                return []
        class Database:
            @contextlib.contextmanager
            def transaction(self):
                yield Connection()
            def close(self):
                pass
        module = types.ModuleType('backend.app.core.postgres_database')
        module.postgres_database = Database()
        with patch.dict(sys.modules, {'backend.app.core.postgres_database':module}), patch('sys.stdin',io.StringIO(json.dumps(request))), contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(str(Path(__file__).parent / 'db_bridge.py'))
        return calls

    def test_pending_and_quality_held_candidates_remain_discoverable(self):
        calls = self.invoke({'action':'snapshot'})
        self.assertIn("review_status IN ('pending','held_quality')",calls[1][0])

    def test_quality_hold_keeps_revision_guard_and_is_never_published(self):
        calls = self.invoke({'action':'record','run_id':'quality-test','success':True,
                             'items':[{'candidate_id':'a','revision':'b','status':'held_quality'}]})
        self.assertEqual(calls[0][1],('held_quality','a','b'))
        self.assertIn('AND revision=%s',calls[0][0])
        with self.assertRaisesRegex(ValueError,'invalid review status'):
            self.invoke({'action':'record','items':[{'status':'unknown'}]})


if __name__ == '__main__':
    unittest.main()
