import hashlib
import unittest
from runtime_probe import source_probe


class RuntimeProbeTests(unittest.TestCase):
    def setUp(self):
        self.item = {'revision': 'a' * 40, 'rights_evidence_url': '/ui-library/assets/provider/evidence/manifest.json', 'files': [{'sha256': hashlib.sha256(b'<button>Original</button>').hexdigest()}]}
        self.quota = {'error': {'code': -32000, 'data': {'quota_scope': 'daily', 'identity_kind': 'ip', 'tier': 'free', 'limit': 30, 'retry_after': 40000}}}

    def test_exhausted_guest_quota_is_recorded_as_unverified_source(self):
        result = source_probe(429, self.quota, self.item)
        self.assertIs(result['mcp_original_source'], False)
        self.assertEqual(result['mcp_guest_daily_quota']['retry_after'], 40000)

    def test_other_failures_never_gain_the_quota_exception(self):
        for status, payload in [(500, self.quota), (429, {'error': {'code': -32000, 'data': {}}}), (200, {'result': {'isError': True}})]:
            with self.assertRaises(RuntimeError):
                source_probe(status, payload, self.item)
        self.quota['error']['data']['identity_kind'] = 'user'
        with self.assertRaises(RuntimeError):
            source_probe(429, self.quota, self.item)

    def test_real_source_must_match_immutable_provenance_and_bytes(self):
        data = {'revision': self.item['revision'], 'rights_evidence_url': 'https://catalog.test' + self.item['rights_evidence_url'], 'files': [{'content': '<button>Original</button>'}]}
        payload = {'result': {'isError': False, 'structuredContent': data}}
        self.assertIs(source_probe(200, payload, self.item)['mcp_original_source'], True)
        data['files'][0]['content'] = '<button>Changed</button>'
        with self.assertRaises(RuntimeError):
            source_probe(200, payload, self.item)
