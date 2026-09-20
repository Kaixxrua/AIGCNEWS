from io import BytesIO
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin

from backend.app.api import routes_auth
from backend.app.api.dependencies import get_oauth_identity_repository, get_user_account_repository
from backend.app.core.auth import RequireUser
from backend.app.services.auth.avatar import MAX_AVATAR_BYTES, normalize_avatar


def raster(fmt="PNG"):
    output = BytesIO()
    image = Image.new("RGB", (400, 200), "red")
    meta = PngImagePlugin.PngInfo()
    meta.add_text("secret", "private metadata")
    image.save(output, format=fmt, pnginfo=meta)
    return output.getvalue()


@pytest.fixture
def api():
    app = FastAPI()
    app.include_router(routes_auth.router, prefix="/api")
    repo = MagicMock()
    record = {"id": 7, "username": "reader", "role": "user", "avatar_digest": None}
    repo.get_user_by_id.return_value = record
    saved = {}

    def update(*, user_id, png, digest):
        assert user_id == 7
        record["avatar_digest"] = digest
        saved[digest] = png
        return 1

    repo.update_user_avatar.side_effect = update
    repo.get_user_avatar.side_effect = lambda *, user_id, digest: saved.get(digest) if user_id == 7 else None
    oauth = MagicMock()
    oauth.list_identities_for_user.return_value = []
    app.dependency_overrides[get_user_account_repository] = lambda: repo
    app.dependency_overrides[get_oauth_identity_repository] = lambda: oauth
    app.dependency_overrides[RequireUser] = lambda: {"user_id": 7}
    return TestClient(app), app, repo


def test_upload_persists_account_projection_and_serves_safe_png(api):
    client, _, repo = api
    assert client.get("/api/auth/me").json()["avatar_url"] is None
    response = client.post("/api/auth/me/avatar", files={"file": ("untrusted.svg", raster(), "image/svg+xml")}, data={"user_id": "999"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["username"] == "reader"
    url = response.json()["avatar_url"]
    assert url.startswith("/api/auth/avatars/7/")
    assert client.get("/api/auth/me").json()["avatar_url"] == url
    image_response = client.get(url)
    assert image_response.status_code == 200
    assert image_response.headers["content-type"] == "image/png"
    assert image_response.headers["x-content-type-options"] == "nosniff"
    with Image.open(BytesIO(image_response.content)) as decoded:
        assert decoded.size == (256, 256)
        assert not decoded.info
    assert client.get(url.replace("/7/", "/999/")).status_code == 404
    assert client.get("/api/auth/avatars/7/invalid.png").status_code == 404
    assert repo.update_user_avatar.call_args.kwargs["user_id"] == 7


def test_upload_requires_authentication(api):
    client, app, repo = api
    del app.dependency_overrides[RequireUser]
    response = client.post("/api/auth/me/avatar", files={"file": ("avatar.png", raster(), "image/png")})
    assert response.status_code in {401, 403}
    repo.update_user_avatar.assert_not_called()


@pytest.mark.parametrize("payload,status", [(b"<svg xmlns='http://www.w3.org/2000/svg'/>", 400), (b"bad image", 400), (b"", 400), (b"x" * (MAX_AVATAR_BYTES + 1), 413)])
def test_rejects_invalid_and_oversized_uploads(api, payload, status):
    client, _, repo = api
    response = client.post("/api/auth/me/avatar", files={"file": ("avatar.png", payload, "image/png")})
    assert response.status_code == status
    repo.update_user_avatar.assert_not_called()


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_normalize_supported_formats(fmt):
    with Image.open(BytesIO(normalize_avatar(raster(fmt)))) as result:
        assert result.format == "PNG"
        assert result.size == (256, 256)


def test_rejects_excessive_dimensions_before_decode():
    output = BytesIO()
    Image.new("1", (4100, 4100)).save(output, format="PNG")
    with pytest.raises(ValueError, match="分辨率"):
        normalize_avatar(output.getvalue())


def test_truncated_image_is_rejected():
    with pytest.raises(ValueError):
        normalize_avatar(raster()[:60])


def test_failed_owner_update_does_not_report_success(api):
    client, _, repo = api
    repo.update_user_avatar.side_effect = None
    repo.update_user_avatar.return_value = 0
    assert client.post("/api/auth/me/avatar", files={"file": ("a.png", raster())}).status_code == 401
