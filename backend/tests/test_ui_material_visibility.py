import json
from uuid import uuid4

import pytest

from backend.app.services.ui_library import settings
from backend.tests.test_ui_library import client


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps({'version': 1, 'items': [{'id': 'live'}, {'id': 'old'}]}))
    path.with_name('icons.json').write_text(json.dumps({'version': 1, 'sets': [
        {'provider_id': 'demo', 'icons': [{'id': 'demo:live'}, {'id': 'demo:old'}]},
    ]}))
    monkeypatch.setattr(settings, 'ui_library_catalog_path', str(path))
    return path


@pytest.mark.parametrize('user', [None, {'sub': '1', 'role': 'user'}, {'sub': '1', 'role': 'admin'}])
def test_default_catalogs_and_rankings_hide_deprecated_materials(catalog, user):
    c, repo = client(user)
    repo.deprecated_ids.return_value = {'old', 'demo:old'}
    repo.engagement.return_value = [{'template_id': 'live'}, {'template_id': 'old'}]
    response = c.get('/api/ui-library/catalog')
    assert response.json()['items'] == [{'id': 'live'}]
    assert response.json()['icon_count'] == 1
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['vary'] == 'Authorization'
    assert c.get('/api/ui-library/icons').json()['sets'][0]['icons'] == [{'id': 'demo:live'}]
    assert c.get('/api/ui-library/engagement').json()['items'] == [{'template_id': 'live'}]


@pytest.mark.parametrize('user,status', [(None, 401), ({'sub': '1', 'role': 'user'}, 403)])
def test_only_admin_can_change_visibility_or_request_deprecated_rows(catalog, user, status):
    c, repo = client(user)
    for deprecated in (True, False):
        assert c.put('/api/ops/ui-library/old/visibility', json={'deprecated': deprecated}).status_code == status
    for endpoint in ('catalog', 'icons'):
        assert c.get(f'/api/ui-library/{endpoint}?include_deprecated=true').status_code == 403
    repo.set_deprecated.assert_not_called()


def test_admin_can_deprecate_and_restore_without_mutating_published_catalog(catalog):
    c, repo = client({'sub': '7', 'role': 'admin'})
    deprecated = set()
    repo.deprecated_ids.side_effect = lambda: set(deprecated)
    repo.set_deprecated.side_effect = lambda material, hidden, actor: deprecated.add(material) if hidden else deprecated.discard(material)
    for material in ('old', 'demo:old'):
        response = c.put(f'/api/ops/ui-library/{material}/visibility', json={'deprecated': True})
        assert response.json() == {'id': material, 'deprecated': True}
        repo.set_deprecated.assert_called_with(material, True, 7)
    response = c.get('/api/ui-library/catalog?include_deprecated=true')
    assert response.json()['items'] == [{'id': 'live', 'deprecated': False}, {'id': 'old', 'deprecated': True}]
    assert c.get('/api/ui-library/icons?include_deprecated=true').json()['sets'][0]['icons'][1]['deprecated'] is True
    # Same cached source data, but the next public response cannot inherit admin rows.
    assert c.get('/api/ui-library/catalog').json()['items'] == [{'id': 'live'}]
    assert len(json.loads(catalog.read_text())['items']) == 2
    # A newly published version with the same IDs cannot undo moderation.
    catalog.write_text(json.dumps({'version': 1, 'items': [{'id': 'old', 'revision': 'new'}, {'id': 'live'}]}))
    assert c.get('/api/ui-library/catalog').json()['items'] == [{'id': 'live'}]
    assert c.put('/api/ops/ui-library/old/visibility', json={'deprecated': False}).status_code == 200
    assert c.get('/api/ui-library/catalog').json()['items'][0]['id'] == 'old'
    assert c.put('/api/ops/ui-library/missing/visibility', json={'deprecated': True}).status_code == 404


@pytest.mark.parametrize('material', ['old', 'demo:old'])
def test_deprecated_content_cannot_be_liked_or_copied_by_user(catalog, material):
    c, repo = client({'sub': '1', 'role': 'user'})
    repo.deprecated_ids.return_value = {material}
    assert c.put(f'/api/ui-library/{material}/like', json={'liked': True}).status_code == 404
    for kind in ('source', 'prompt'):
        assert c.post(f'/api/ui-library/{material}/copy', json={'kind': kind, 'request_id': str(uuid4())}).status_code == 404
    repo.set_like.assert_not_called()
    repo.consume_copy.assert_not_called()
    repo.deprecated_ids.return_value = set()
    assert c.put(f'/api/ui-library/{material}/like', json={'liked': True}).status_code == 200


def test_database_failure_never_falls_back_to_unfiltered_catalog(catalog):
    c, repo = client()
    repo.deprecated_ids.side_effect = RuntimeError('database unavailable')
    with pytest.raises(RuntimeError, match='database unavailable'):
        c.get('/api/ui-library/catalog')
