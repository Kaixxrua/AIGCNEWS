"""Interpret a publisher's real MCP probe without weakening production quotas."""
import hashlib
import json


def source_probe(status, payload, item):
    error = payload.get('error', {})
    quota = error.get('data', {})
    if (status == 429 and error.get('code') == -32000
            and quota.get('quota_scope') == 'daily' and quota.get('identity_kind') == 'ip'
            and quota.get('tier') == 'free' and isinstance(quota.get('limit'), int)
            and quota['limit'] > 0 and isinstance(quota.get('retry_after'), int)
            and quota['retry_after'] > 0):
        return {'mcp_original_source': False, 'mcp_guest_daily_quota': quota}
    if status != 200 or error:
        raise RuntimeError('mcp_runtime_probe_failed')
    result = payload['result']
    if result.get('isError'):
        raise RuntimeError('mcp_source_tool_error')
    data = result.get('structuredContent') or json.loads(next(part['text'] for part in result['content'] if part['type'] == 'text'))
    if data['revision'] != item['revision'] or not data['rights_evidence_url'].endswith(item['rights_evidence_url']):
        raise RuntimeError('mcp_source_provenance_mismatch')
    if hashlib.sha256(data['files'][0]['content'].encode()).hexdigest() != item['files'][0]['sha256']:
        raise RuntimeError('mcp_original_source_mismatch')
    return {'mcp_original_source': True}
