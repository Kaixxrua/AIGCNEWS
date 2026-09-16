import json
import tempfile
import unittest
from pathlib import Path

from policy import withdrawn_ids


class WithdrawalPolicyTests(unittest.TestCase):
    def test_default_and_revision_independent_withdrawal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(withdrawn_ids(root), set())
            path = root / 'local/ui-publication/withdrawn.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'version': 1, 'ids': ['hyperui-application-buttons-1']}))
            self.assertIn('hyperui-application-buttons-1', withdrawn_ids(root))
            self.assertNotIn('hyperui-application-buttons-2', withdrawn_ids(root))

    def test_corrupt_policy_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'local/ui-publication/withdrawn.json'
            path.parent.mkdir(parents=True)
            for payload in ({'version': 2, 'ids': []}, {'version': 1, 'ids': ['../catalog']}, {'version': 1, 'ids': [None]}):
                path.write_text(json.dumps(payload))
                with self.assertRaises(ValueError):
                    withdrawn_ids(root)


if __name__ == '__main__':
    unittest.main()
