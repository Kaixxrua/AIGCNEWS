import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / 'scripts/ci'))
import local_delivery as delivery
from ui_catalog_release import catalog_digest, published_digest


def test_catalog_identity_tracks_content_not_code(tmp_path):
    config = {'production': str(tmp_path)}
    assert catalog_digest(config) is None
    path = tmp_path / 'mcp-go/internal/uicatalog/data/catalog.json'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{"items":[]}')
    before = catalog_digest(config)
    assert before == hashlib.sha256(path.read_bytes()).hexdigest()
    path.write_bytes(b'{"items":[{"id":"new"}]}')
    assert catalog_digest(config) != before


def test_legacy_receipt_is_measured_from_immutable_image_once(tmp_path, monkeypatch):
    config = {'state': str(tmp_path)}
    db = delivery.database(config)
    image = 'example/frontend@sha256:' + 'a' * 64
    calls = []
    monkeypatch.setattr(delivery, 'command', lambda args: calls.append(args) or 'b'*64 + '  catalog.json')
    state = {'images': {'frontend': image}}
    assert published_digest(config, db, state) == 'b'*64
    assert published_digest(config, db, state) == 'b'*64
    assert len(calls) == 1 and image in calls[0]
    assert calls[0][:7] == ['docker', 'run', '--rm', '--read-only', '--network', 'none', '--entrypoint']
    state['images']['frontend'] = 'example/frontend@sha256:' + 'c'*64
    published_digest(config, db, state)
    assert len(calls) == 2
    state['ui_catalog_sha256'] = 'd'*64
    assert published_digest(config, db, state) == 'd'*64
    assert len(calls) == 2
    db.close()


def test_legacy_receipt_cannot_guess_live_catalog(tmp_path, monkeypatch):
    config = {'state': str(tmp_path)}
    db = delivery.database(config)
    with pytest.raises(RuntimeError, match='not verifiable'):
        published_digest(config, db, {'images': {'frontend': 'latest'}})
    monkeypatch.setattr(delivery, 'command', lambda args: 'invalid output')
    with pytest.raises(RuntimeError, match='unavailable'):
        published_digest(config, db, {'images': {'frontend': 'example/frontend@sha256:' + 'a'*64}})
    assert delivery.meta(db, 'ui_catalog_baseline') == {}
    db.close()
