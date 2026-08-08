from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from backend.app.core.config import Settings
from backend.app.domain.wechat_secret_box import WeChatSecretBox
from backend.app.repositories.postgres_x_credentials_repository import (
    PostgresXCredentialRepository,
    XCredentialSecretError,
    _parse_sealed_envelope,
    build_x_credential_secret_box,
)
from backend.app.repositories.x_credentials_repository import XCredentialRepository


class FakeDatabase:
    def __init__(self, cursor: MagicMock) -> None:
        self.cursor = cursor
        self.connection = MagicMock()
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        self.connection.cursor.return_value = cursor_context
        self.transaction_count = 0

    @contextmanager
    def transaction(self):
        self.transaction_count += 1
        yield self.connection


def make_box() -> WeChatSecretBox:
    return WeChatSecretBox.generate_for_test()


def repository_with_cursor(bootstrap=None, secret_box: WeChatSecretBox | None = None):
    """默认装配测试加密盒；显式需要"无盒"场景请直接构造仓储。"""
    cursor = MagicMock()
    database = FakeDatabase(cursor)
    repository = PostgresXCredentialRepository(
        database, bootstrap, secret_box if secret_box is not None else make_box()
    )
    return repository, database, cursor


def repository_without_box(bootstrap=None):
    cursor = MagicMock()
    database = FakeDatabase(cursor)
    repository = PostgresXCredentialRepository(database, bootstrap, None)
    return repository, database, cursor


def sealed_str(box: WeChatSecretBox, plaintext: str) -> str:
    return json.dumps(box.seal(plaintext), ensure_ascii=False)


def unseal_arg(box: WeChatSecretBox, stored: str) -> str:
    envelope = _parse_sealed_envelope(stored)
    assert envelope is not None, f"expected sealed envelope, got: {stored!r}"
    return box.unseal(envelope)


def test_postgres_adapter_exposes_credential_contract() -> None:
    repository, _, _ = repository_with_cursor()
    contract: XCredentialRepository = repository

    assert callable(contract.list_x_credentials)
    assert callable(contract.get_x_credential)
    assert callable(contract.list_enabled_x_credentials)
    assert callable(contract.create_x_credential)
    assert callable(contract.update_x_credential)
    assert callable(contract.delete_x_credential)
    assert callable(contract.update_x_credential_test_result)


def test_parse_sealed_envelope_distinguishes_legacy_plaintext() -> None:
    box = make_box()

    assert _parse_sealed_envelope("plain-cookie-token") is None
    assert _parse_sealed_envelope('{"v": "v1"}') is None
    assert _parse_sealed_envelope("") is None
    assert _parse_sealed_envelope(None) is None

    envelope = _parse_sealed_envelope(sealed_str(box, "secret"))
    assert envelope is not None
    assert box.unseal(envelope) == "secret"


def test_seed_bootstraps_only_when_table_and_state_empty() -> None:
    box = make_box()
    repository, database, cursor = repository_with_cursor(
        (" auth-token ", " ct0-token "), box
    )
    cursor.fetchone.side_effect = [None, {"n": 0}]
    cursor.fetchall.return_value = [{"id": 1, "display_name": "env-bootstrap"}]

    result = repository.list_x_credentials()

    (
        advisory_lock,
        bootstrap_select,
        count_query,
        insert,
        state_insert,
        listing,
    ) = cursor.execute.call_args_list
    assert "pg_advisory_xact_lock" in advisory_lock.args[0]
    assert "x_credentials_bootstrap_state" in bootstrap_select.args[0]
    assert "COUNT(*)" in count_query.args[0]
    assert "INSERT INTO x_credentials" in insert.args[0]
    # 种子 cookie 也必须密封落库，不出现明文
    assert insert.args[1][0] == "env-bootstrap"
    assert insert.args[1][1] == "由环境变量初始化；请在 Monitor 的 X 凭证池中管理。"
    assert unseal_arg(box, insert.args[1][2]) == "auth-token"
    assert unseal_arg(box, insert.args[1][3]) == "ct0-token"
    assert "auth-token" not in insert.args[1][2]
    assert "ct0-token" not in insert.args[1][3]
    assert "x_credentials_bootstrap_state" in state_insert.args[0]
    # 读取投影会补齐解密后的 auth_token/ct0 键
    assert result == [
        {"id": 1, "display_name": "env-bootstrap", "auth_token": "", "ct0": ""}
    ]
    assert database.transaction_count == 2


def test_seed_is_skipped_when_bootstrap_state_exists() -> None:
    repository, database, cursor = repository_with_cursor(("auth", "ct0"))
    cursor.fetchone.return_value = {"singleton_key": 1}
    cursor.fetchall.return_value = [{"id": 1}]

    result = repository.list_x_credentials()

    assert result == [{"id": 1, "auth_token": "", "ct0": ""}]
    assert cursor.execute.call_count == 3  # lock + state select + listing
    assert database.transaction_count == 2


def test_seed_marks_state_without_insert_when_table_not_empty() -> None:
    repository, _, cursor = repository_with_cursor(("auth", "ct0"))
    cursor.fetchone.side_effect = [None, {"n": 3}]
    cursor.fetchall.return_value = [{"id": 1}]

    repository.list_x_credentials()

    executed = [call.args[0] for call in cursor.execute.call_args_list]
    assert not any("INSERT INTO x_credentials\n" in sql for sql in executed)
    assert any("x_credentials_bootstrap_state" in sql and "INSERT" in sql for sql in executed)


def test_seed_is_skipped_without_encryption_key(caplog: pytest.LogCaptureFixture) -> None:
    repository, _, cursor = repository_without_box(("auth-token", "ct0-token"))
    cursor.fetchall.return_value = [{"id": 1}]

    with caplog.at_level(logging.WARNING):
        result = repository.list_x_credentials()

    # 无密钥时不落明文种子：跳过 seed，只做列表查询
    assert cursor.execute.call_count == 1
    assert "加密密钥未配置" in caplog.text
    assert result == [{"id": 1, "auth_token": "", "ct0": ""}]


def test_create_requires_complete_secret_pair() -> None:
    repository, database, _ = repository_with_cursor()

    with pytest.raises(ValueError, match="auth_token 和 ct0 不能为空"):
        repository.create_x_credential({"auth_token": "token", "ct0": "  "})
    assert database.transaction_count == 0


def test_create_persists_sealed_secrets_and_returns_plaintext_row() -> None:
    box = make_box()
    repository, _, cursor = repository_with_cursor(secret_box=box)
    stored_row = {
        "id": 7,
        "display_name": "pool-a",
        "note": "",
        "auth_token": "auth-plain",
        "ct0": "ct0-plain",
        "enabled": True,
        "sort_order": 0,
    }
    cursor.fetchone.side_effect = [{"id": 7}, stored_row]

    result = repository.create_x_credential(
        {
            "display_name": "pool-a",
            "auth_token": " auth-plain ",
            "ct0": " ct0-plain ",
        }
    )

    insert_call = cursor.execute.call_args_list[0]
    assert "INSERT INTO x_credentials" in insert_call.args[0]
    # 密封往返：落库参数是信封，可解密回原文，且不等于明文
    assert unseal_arg(box, insert_call.args[1][2]) == "auth-plain"
    assert unseal_arg(box, insert_call.args[1][3]) == "ct0-plain"
    assert "auth-plain" not in insert_call.args[1][2]
    # 读取投影返回明文
    assert result["auth_token"] == "auth-plain"
    assert result["ct0"] == "ct0-plain"


def test_create_refuses_to_store_plaintext_without_encryption_key() -> None:
    repository, _, cursor = repository_without_box()

    with pytest.raises(XCredentialSecretError):
        repository.create_x_credential({"auth_token": "a", "ct0": "b"})
    assert not any(
        "INSERT INTO x_credentials" in call.args[0]
        for call in cursor.execute.call_args_list
    )


def test_get_x_credential_decrypts_sealed_row() -> None:
    box = make_box()
    repository, _, cursor = repository_with_cursor(secret_box=box)
    cursor.fetchone.return_value = {
        "id": 3,
        "display_name": "pool-b",
        "auth_token": sealed_str(box, "real-auth"),
        "ct0": sealed_str(box, "real-ct0"),
        "enabled": True,
    }

    result = repository.get_x_credential(3)

    assert result is not None
    assert result["auth_token"] == "real-auth"
    assert result["ct0"] == "real-ct0"


def test_get_x_credential_passes_through_legacy_plaintext_row() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.fetchone.return_value = {
        "id": 4,
        "display_name": "legacy",
        "auth_token": "legacy-auth",
        "ct0": "legacy-ct0",
        "enabled": True,
    }

    result = repository.get_x_credential(4)

    # 明文行兼容读取（懒迁移：下次写入即密封）
    assert result is not None
    assert result["auth_token"] == "legacy-auth"
    assert result["ct0"] == "legacy-ct0"


def test_sealed_row_unreadable_without_key_returns_blank_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    box = make_box()
    repository, _, cursor = repository_without_box()
    ciphertext = sealed_str(box, "real-auth")
    cursor.fetchone.return_value = {
        "id": 5,
        "display_name": "sealed",
        "auth_token": ciphertext,
        "ct0": sealed_str(box, "real-ct0"),
        "enabled": True,
    }

    with caplog.at_level(logging.WARNING):
        result = repository.get_x_credential(5)

    # 绝不把密文当明文下发；表现为未配置并记告警
    assert result is not None
    assert result["auth_token"] == ""
    assert result["ct0"] == ""
    assert ciphertext not in (result["auth_token"], result["ct0"])
    assert "无法解密封存的凭证" in caplog.text


def test_update_retains_existing_secrets_when_blank() -> None:
    box = make_box()
    repository, _, cursor = repository_with_cursor(secret_box=box)
    existing = {
        "id": 42,
        "display_name": "old-name",
        "note": "old-note",
        "auth_token": "old-auth",
        "ct0": "old-ct0",
        "enabled": True,
        "sort_order": 1,
    }
    cursor.fetchone.side_effect = [existing, {**existing, "display_name": "new-name"}]

    result = repository.update_x_credential(42, {"display_name": "new-name"})

    select, update, refetch = cursor.execute.call_args_list
    assert "WHERE id = %s LIMIT 1" in select.args[0]
    assert "UPDATE x_credentials" in update.args[0]
    assert update.args[1][0] == "new-name"
    assert update.args[1][1] == "old-note"
    # 历史明文保留值在写路径上立即密封迁移，update 参数不再出现明文
    assert unseal_arg(box, update.args[1][2]) == "old-auth"
    assert unseal_arg(box, update.args[1][3]) == "old-ct0"
    assert update.args[1][2] != "old-auth"
    assert result is not None
    assert result["display_name"] == "new-name"
    assert refetch.args[1] == (42,)


def test_update_carries_existing_envelope_verbatim() -> None:
    box = make_box()
    repository, _, cursor = repository_with_cursor(secret_box=box)
    sealed_auth = sealed_str(box, "old-auth")
    sealed_ct0 = sealed_str(box, "old-ct0")
    existing = {
        "id": 42,
        "display_name": "old-name",
        "note": "old-note",
        "auth_token": sealed_auth,
        "ct0": sealed_ct0,
        "enabled": True,
        "sort_order": 1,
    }
    cursor.fetchone.side_effect = [existing, existing]

    repository.update_x_credential(42, {"note": "touched"})

    update = cursor.execute.call_args_list[1]
    # 已密封值原样携带，不重复加密封（nonce 不变，幂等可比对）
    assert update.args[1][2] == sealed_auth
    assert update.args[1][3] == sealed_ct0


def test_update_rejects_blank_pair_when_existing_secrets_are_missing() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.fetchone.return_value = {
        "id": 42,
        "display_name": "broken",
        "note": "",
        "auth_token": "",
        "ct0": "",
        "enabled": True,
        "sort_order": 0,
    }

    with pytest.raises(ValueError, match="auth_token 和 ct0 不能为空"):
        repository.update_x_credential(42, {"display_name": "broken"})
    assert not any(
        "UPDATE x_credentials" in call.args[0]
        for call in cursor.execute.call_args_list
    )


def test_update_seals_complete_replacement() -> None:
    box = make_box()
    repository, _, cursor = repository_with_cursor(secret_box=box)
    existing = {
        "id": 42,
        "display_name": "old-name",
        "note": "old-note",
        "auth_token": "old-auth",
        "ct0": "old-ct0",
        "enabled": True,
        "sort_order": 1,
    }
    cursor.fetchone.side_effect = [existing, existing]

    repository.update_x_credential(
        42,
        {"auth_token": " new-auth ", "ct0": " new-ct0 "},
    )

    update = cursor.execute.call_args_list[1]
    assert unseal_arg(box, update.args[1][2]) == "new-auth"
    assert unseal_arg(box, update.args[1][3]) == "new-ct0"


def test_update_returns_none_when_missing() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.fetchone.return_value = None

    assert repository.update_x_credential(99, {"display_name": "x"}) is None
    assert cursor.execute.call_count == 1


def test_delete_x_credential_reports_rowcount() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.rowcount = 1

    assert repository.delete_x_credential(7) is True
    assert "DELETE FROM x_credentials" in cursor.execute.call_args_list[0].args[0]


def test_update_x_credential_test_result_persists_projection() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.rowcount = 1
    cursor.fetchone.return_value = {
        "id": 7,
        "last_test_status": "success",
        "last_test_message": "ok",
        "auth_token": "",
        "ct0": "",
    }

    result = repository.update_x_credential_test_result(
        7, {"status": "success", "message": "ok"}
    )

    update = cursor.execute.call_args_list[0]
    assert "last_test_status" in update.args[0]
    assert update.args[1] == ("success", "ok", 7)
    assert result is not None
    assert result["last_test_status"] == "success"


def test_update_x_credential_test_result_returns_none_for_missing_row() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.rowcount = 0

    assert (
        repository.update_x_credential_test_result(7, {"status": "failed"}) is None
    )


def test_build_box_from_configured_settings() -> None:
    """密钥装配契约：合法配置产出按版本密封的加密盒。"""
    key = WeChatSecretBox.generate_key_material()
    config = Settings(
        _env_file=None,
        x_credential_encryption_key=key,
        x_credential_encryption_key_version="v2",
    )

    box = build_x_credential_secret_box(config=config)

    assert box is not None
    assert box.seal("plain")["v"] == "v2"


def test_build_box_returns_none_when_key_missing() -> None:
    config = Settings(_env_file=None, x_credential_encryption_key="")

    assert build_x_credential_secret_box(config=config) is None


def test_build_box_returns_none_and_warns_on_invalid_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = Settings(
        _env_file=None,
        x_credential_encryption_key="not-valid-base64!!!",
    )

    with caplog.at_level(logging.WARNING):
        assert build_x_credential_secret_box(config=config) is None
    assert "X 凭证加密密钥非法" in caplog.text


def test_settings_rejects_placeholder_key() -> None:
    with pytest.raises(ValidationError, match="example placeholder"):
        Settings(_env_file=None, x_credential_encryption_key="CHANGEME123")


def test_settings_rejects_out_of_range_key_version() -> None:
    with pytest.raises(ValidationError, match="key_version"):
        Settings(_env_file=None, x_credential_encryption_key_version="")
    with pytest.raises(ValidationError, match="key_version"):
        Settings(_env_file=None, x_credential_encryption_key_version="a" * 65)
