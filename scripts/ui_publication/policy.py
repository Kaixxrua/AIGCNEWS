"""Operator withdrawals persist across discovery revisions and scheduled runs."""
import json
import re


def withdrawn_ids(root):
    path = root / 'local/ui-publication/withdrawn.json'
    if not path.exists():
        return set()
    payload = json.loads(path.read_text(encoding='utf-8'))
    if payload.get('version') != 1 or not isinstance(payload.get('ids'), list):
        raise ValueError('invalid_withdrawal_policy')
    if any(not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,240}', value) for value in payload['ids']):
        raise ValueError('invalid_withdrawal_id')
    return set(payload['ids'])
