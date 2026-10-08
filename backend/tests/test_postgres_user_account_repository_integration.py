from __future__ import annotations

import pytest

from backend.app.repositories.postgres_user_account_repository import (
    PostgresUserAccountRepository,
)
from backend.tests.postgres_test_safety import postgres_test_sandbox


@pytest.fixture
def database():
    with postgres_test_sandbox() as sandbox:
        yield sandbox.database


def test_postgres_user_repository_round_trip_and_statistics(database) -> None:
    repository = PostgresUserAccountRepository(database)

    user_id = repository.create_user_with_email(
        "Reader@Example.COM",
        "hash-v1",
        username="reader",
    )

    assert user_id == 1
    row = repository.get_user_by_email("READER@example.com")
    assert row is not None
    assert row["id"] == 1
    assert row["email"] == "reader@example.com"
    assert row["hashed_password"] == "hash-v1"
    assert repository.get_user_count() == 1
    assert repository.get_today_registered_user_count() == 1
    assert (
        repository.update_user_password(
            user_id=user_id,
            email="READER@example.com",
            hashed_password="hash-v2",
        )
        == 1
    )
    assert repository.get_user_by_email("reader@example.com")["hashed_password"] == "hash-v2"


def test_postgres_user_repository_preserves_phone_path_and_unique_email(database) -> None:
    repository = PostgresUserAccountRepository(database)

    phone_id = repository.create_user("13800000000", "phone-user", "hash")
    assert repository.get_user_by_phone("13800000000")["id"] == phone_id

    repository.create_user_with_email("unique@example.com", "hash")
    with pytest.raises(Exception) as context:
        repository.create_user_with_email("unique@example.com", "other-hash")
    assert getattr(context.value, "sqlstate", None) == "23505"
    assert repository.get_user_count() == 2


def test_postgres_get_user_by_id_projects_disabled_flag(database) -> None:
    """auth.get_current_user 依赖 record['disabled'] 判定停用账号（迁移 0029 补列）。"""
    repository = PostgresUserAccountRepository(database)
    user_id = repository.create_user_with_email("flag@example.com", "hash")

    row = repository.get_user_by_id(user_id)
    assert row is not None
    assert row["disabled"] is False

    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE users SET disabled = TRUE WHERE id = %s", (user_id,))

    assert repository.get_user_by_id(user_id)["disabled"] is True


def test_username_cooldown_http_contract_and_expiry(database, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.app.api import routes_auth
    from backend.app.api.dependencies import get_oauth_identity_repository, get_user_account_repository
    from backend.app.core.auth import create_access_token
    from backend.app.core.config import settings
    from backend.app.repositories.postgres_oauth_identity_repository import PostgresOAuthIdentityRepository

    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "username-isolated-test-secret-never-production")
    repo = PostgresUserAccountRepository(database)
    owner = repo.create_user_with_email("rename@example.com", "hash", username="Before")
    other = repo.create_user_with_email("rename-other@example.com", "hash", username="Other")
    token = create_access_token({"user_id": owner, "pwd_ver": repo.get_user_by_id(owner)["pwd_ver"]})
    app = FastAPI()
    app.state.application_repositories = SimpleNamespace(users=repo)
    app.include_router(routes_auth.router, prefix="/api")
    app.dependency_overrides[get_user_account_repository] = lambda: repo
    app.dependency_overrides[get_oauth_identity_repository] = lambda: PostgresOAuthIdentityRepository(database)
    with TestClient(app) as client:
        assert client.patch("/api/auth/me/profile", json={"username": "No auth"}).status_code == 401
        client.headers["Authorization"] = f"Bearer {token}"
        assert client.get("/api/auth/me").json()["username_change_available_at"] is None
        # Saving the current name or invalid input must not consume a rename.
        assert client.patch("/api/auth/me/profile", json={"username": " Before "}).status_code == 200
        assert repo.get_user_by_id(owner)["username_change_available_at"] is None
        assert client.patch("/api/auth/me/profile", json={"username": " "}).status_code == 422
        assert client.patch("/api/auth/me/profile", json={"username": "After", "user_id": other}).status_code == 422
        before = datetime.now(timezone.utc)
        changed = client.patch("/api/auth/me/profile", json={"username": " After "})
        assert changed.status_code == 200, changed.text
        assert changed.json()["username"] == "After"
        deadline = datetime.fromisoformat(changed.json()["username_change_available_at"])
        assert before + timedelta(hours=72) <= deadline <= datetime.now(timezone.utc) + timedelta(hours=72)
        assert client.get("/api/auth/me").json()["username_change_available_at"] == deadline.isoformat()
        same = client.patch("/api/auth/me/profile", json={"username": "After"})
        assert same.status_code == 200
        assert same.json()["username_change_available_at"] == deadline.isoformat()
        for _ in range(2):
            blocked = client.patch("/api/auth/me/profile", json={"username": "Too soon"})
            assert blocked.status_code == 429
            assert "3 天" in blocked.json()["detail"]
            assert 0 < int(blocked.headers["retry-after"]) <= 72 * 60 * 60
            assert blocked.headers["cache-control"] == "no-store"
        assert repo.get_user_by_id(owner)["username"] == "After"
        assert repo.get_user_by_id(owner)["username_change_available_at"] == deadline
        assert repo.get_user_by_id(other)["username_change_available_at"] is None
        assert repo.update_user_username(user_id=other, username="Independent") == 1
        with database.transaction() as connection:
            connection.execute("UPDATE users SET username_change_available_at = statement_timestamp() + INTERVAL '1 minute' WHERE id = %s", (owner,))
        assert client.patch("/api/auth/me/profile", json={"username": "Still early"}).status_code == 429
        with database.transaction() as connection:
            connection.execute("UPDATE users SET username_change_available_at = statement_timestamp() WHERE id = %s", (owner,))
        allowed = client.patch("/api/auth/me/profile", json={"username": "Allowed"})
        assert allowed.status_code == 200
        assert allowed.json()["username"] == "Allowed"
        with database.transaction() as connection:
            connection.execute("UPDATE users SET disabled = TRUE WHERE id = %s", (owner,))
        assert client.patch("/api/auth/me/profile", json={"username": "Disabled"}).status_code == 401
        assert repo.update_user_username(user_id=owner, username="Disabled") == 0


def test_concurrent_renames_only_change_once(database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    repo = PostgresUserAccountRepository(database)
    owner = repo.create_user_with_email("concurrent-rename@example.com", "hash", username="Before")
    barrier = Barrier(2)

    def rename(name):
        barrier.wait(timeout=5)
        return repo.update_user_username(user_id=owner, username=name)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(rename, ["First", "Second"]))
    assert sorted(results) == [0, 1]
    assert repo.get_user_by_id(owner)["username"] == ["First", "Second"][results.index(1)]
    assert repo.get_user_by_id(owner)["username_change_available_at"] is not None
    assert repo.update_user_username(user_id=99999, username="Missing") == 0


def test_avatar_round_trip_is_owner_scoped_and_replacement_invalidates_old_url(database):
    import hashlib
    from io import BytesIO

    from PIL import Image

    from backend.app.services.auth.avatar import normalize_avatar

    repository = PostgresUserAccountRepository(database)
    owner = repository.create_user_with_email("avatar@example.com", "hash")
    other = repository.create_user_with_email("other@example.com", "hash")
    output = BytesIO()
    Image.new("RGB", (16, 16), "red").save(output, format="PNG")
    png = normalize_avatar(output.getvalue())
    digest = hashlib.sha256(png).hexdigest()
    assert repository.get_user_by_id(owner)["avatar_digest"] is None
    assert repository.update_user_avatar(user_id=owner, png=png, digest=digest) == 1
    assert repository.get_user_avatar(user_id=owner, digest=digest) == png
    assert repository.get_user_by_id(owner)["avatar_digest"] == digest
    assert "avatar_png" not in repository.get_user_by_id(owner)
    assert repository.get_user_avatar(user_id=other, digest=digest) is None
    assert repository.get_user_by_id(other)["avatar_digest"] is None
    replacement = "b" * 64
    assert repository.update_user_avatar(user_id=owner, png=png, digest=replacement) == 1
    assert repository.get_user_avatar(user_id=owner, digest=digest) is None
    with database.transaction() as connection:
        connection.execute("UPDATE users SET disabled = TRUE WHERE id = %s", (owner,))
    assert repository.get_user_avatar(user_id=owner, digest=replacement) is None
    assert repository.update_user_avatar(user_id=owner, png=png, digest=digest) == 0
    assert repository.update_user_avatar(user_id=99999, png=png, digest=digest) == 0


def test_initial_avatar_never_overwrites_an_existing_avatar(database):
    """第三方首登导入只填空位：用户已有（自传）头像时写入为 0 行。"""
    repository = PostgresUserAccountRepository(database)
    user_id = repository.create_user_with_email("initial-avatar@example.com", "hash")
    first, second = b"\x89PNG-first", b"\x89PNG-second"

    assert repository.set_initial_user_avatar(user_id=user_id, png=first, digest="a" * 64) == 1
    assert repository.set_initial_user_avatar(user_id=user_id, png=second, digest="b" * 64) == 0
    assert repository.get_user_avatar(user_id=user_id, digest="a" * 64) == first

    uploaded = repository.create_user_with_email("uploaded-avatar@example.com", "hash")
    assert repository.update_user_avatar(user_id=uploaded, png=first, digest="c" * 64) == 1
    assert repository.set_initial_user_avatar(user_id=uploaded, png=second, digest="d" * 64) == 0
    assert repository.get_user_avatar(user_id=uploaded, digest="c" * 64) == first

    disabled = repository.create_user_with_email("disabled-avatar@example.com", "hash")
    with database.transaction() as connection:
        connection.execute("UPDATE users SET disabled = TRUE WHERE id = %s", (disabled,))
    assert repository.set_initial_user_avatar(user_id=disabled, png=first, digest="e" * 64) == 0


def test_avatar_database_bounds_and_pairing_are_enforced(database):
    from psycopg.errors import CheckViolation

    repository = PostgresUserAccountRepository(database)
    owner = repository.create_user_with_email("bounds@example.com", "hash")
    for png, digest in [(b"x" * 300001, "a" * 64), (b"x", "invalid"), (b"x", None), (None, "a" * 64)]:
        with pytest.raises(CheckViolation):
            with database.transaction() as connection:
                connection.execute(
                    "UPDATE users SET avatar_png = %s, avatar_digest = %s WHERE id = %s",
                    (png, digest, owner),
                )
    assert repository.get_user_by_id(owner)["avatar_digest"] is None


def test_avatar_real_http_upload_with_jwt_and_postgres(database, monkeypatch):
    """Exercise the actual ASGI server, JWT ownership and migrated DB over HTTP."""
    import socket
    import threading
    import time
    from io import BytesIO
    from types import SimpleNamespace

    import httpx
    import uvicorn
    from fastapi import FastAPI
    from PIL import Image

    from backend.app.api import routes_auth
    from backend.app.api.dependencies import get_oauth_identity_repository, get_user_account_repository
    from backend.app.core.auth import create_access_token
    from backend.app.core.config import settings
    from backend.app.repositories.postgres_oauth_identity_repository import PostgresOAuthIdentityRepository

    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "avatar-isolated-http-test-secret-never-production")
    repo = PostgresUserAccountRepository(database)
    user_id = repo.create_user_with_email("http-avatar@example.com", "hash", username="Avatar")
    other_id = repo.create_user_with_email("http-other@example.com", "hash")
    token = create_access_token({"user_id": user_id, "pwd_ver": repo.get_user_by_id(user_id)["pwd_ver"]})
    app = FastAPI()
    app.state.application_repositories = SimpleNamespace(users=repo)
    app.include_router(routes_auth.router, prefix="/api")
    app.dependency_overrides[get_user_account_repository] = lambda: repo
    app.dependency_overrides[get_oauth_identity_repository] = lambda: PostgresOAuthIdentityRepository(database)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        with httpx.Client(base_url=f"http://127.0.0.1:{listener.getsockname()[1]}", trust_env=False) as client:
            png = BytesIO()
            Image.new("RGB", (400, 200), "green").save(png, format="PNG")
            upload = {"file": ("avatar.png", png.getvalue(), "image/png")}
            assert client.post("/api/auth/me/avatar", files=upload).status_code == 401
            headers = {"Authorization": f"Bearer {token}"}
            response = client.post("/api/auth/me/avatar", headers=headers, files=upload, data={"user_id": str(other_id)})
            assert response.status_code == 200, response.text
            avatar_url = response.json()["avatar_url"]
            assert response.json()["username"] == "Avatar"
            assert client.get("/api/auth/me", headers=headers).json()["avatar_url"] == avatar_url
            served = client.get(avatar_url)
            assert served.status_code == 200
            assert Image.open(BytesIO(served.content)).size == (256, 256)
            assert repo.get_user_by_id(other_id)["avatar_digest"] is None
            assert client.post("/api/auth/me/avatar", headers=headers, files={"file": ("bad.png", b"<svg/>")}).status_code == 400
            assert client.post("/api/auth/me/avatar", headers=headers, files={"file": ("large.png", b"x" * (2 * 1024 * 1024 + 1))}).status_code == 413
            with database.transaction() as connection:
                connection.execute("UPDATE users SET disabled=TRUE WHERE id=%s", (user_id,))
            assert client.post("/api/auth/me/avatar", headers=headers, files=upload).status_code == 401
            assert client.get(avatar_url).status_code == 404
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        assert not thread.is_alive()
