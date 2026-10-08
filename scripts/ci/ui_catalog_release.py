"""Compare admitted UI content with the immutable artifact already in production."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path


def catalog_digest(config):
    path = Path(config['production']) / 'mcp-go/internal/uicatalog/data/catalog.json'
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def published_digest(config, db, state):
    from local_delivery import command, meta

    if state.get('ui_catalog_sha256'):
        return state['ui_catalog_sha256']
    # Older production receipts did not include content identity. Read the
    # immutable deployed image once; never assume the on-disk inputs are live.
    image = state.get('images', {}).get('frontend', '')
    if not re.fullmatch(r'[^@\s]+@sha256:[0-9a-f]{64}', image):
        raise RuntimeError('published UI catalog image is not verifiable')
    cached = meta(db, 'ui_catalog_baseline')
    if cached.get('image') == image:
        return cached['sha256']
    output = command(['docker', 'run', '--rm', '--read-only', '--network', 'none',
                      '--entrypoint', 'sha256sum', image,
                      '/usr/share/nginx/html/ui-library/catalog.json'])
    digest = output.split()[0] if output.split() else ''
    if not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise RuntimeError('published UI catalog digest is unavailable')
    meta(db, 'ui_catalog_baseline', {'image': image, 'sha256': digest})
    return digest
