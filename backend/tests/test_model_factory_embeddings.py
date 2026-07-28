from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.app.core import model_factory


def test_runtime_setting_reader_failure_falls_back_silently() -> None:
    with patch.object(
        model_factory,
        "_get_runtime_provider_setting_reader",
        side_effect=RuntimeError("database unavailable"),
    ):
        result = model_factory._get_runtime_provider_setting("openai")

    assert result == {}


def test_runtime_setting_reader_receives_normalized_lookup_argument() -> None:
    reader = MagicMock()
    reader.get_runtime_provider_setting.return_value = {"provider": "openai"}

    with patch.object(
        model_factory,
        "_get_runtime_provider_setting_reader",
        return_value=reader,
    ):
        result = model_factory._get_runtime_provider_setting("openai")

    assert result == {"provider": "openai"}
    reader.get_runtime_provider_setting.assert_called_once_with("openai")


def test_runtime_reader_factory_uses_configured_repository_component() -> None:
    repositories = MagicMock()
    reader = repositories.runtime_provider_settings

    with patch(
        "backend.app.repositories.application_repository_context."
        "get_configured_application_repositories",
        return_value=repositories,
    ) as get_repositories:
        result = model_factory._get_runtime_provider_setting_reader()

    assert result is reader
    get_repositories.assert_called_once_with()


def test_siliconflow_embedding_base_url_reuses_siliconflow_key() -> None:
    fake_settings = SimpleNamespace(
        embedding_provider="openai",
        embedding_api_key="",
        embedding_base_url="https://api.siliconflow.cn/v1",
        embedding_model_name="BAAI/bge-m3",
        siliconflow_api_key="siliconflow-secret",
        openai_api_key="openai-secret",
        openai_base_url="https://api.openai.com/v1",
    )
    embeddings = MagicMock()

    with (
        patch.object(model_factory, "settings", fake_settings),
        patch.object(model_factory, "_get_runtime_provider_setting", return_value={}),
        patch("langchain_openai.OpenAIEmbeddings", return_value=embeddings) as factory,
    ):
        result = model_factory.get_embedding_model()

    assert result is embeddings
    assert factory.call_args.kwargs["api_key"] == "siliconflow-secret"
    assert factory.call_args.kwargs["base_url"] == "https://api.siliconflow.cn/v1"
    assert factory.call_args.kwargs["http_client"].trust_env is False
    assert factory.call_args.kwargs["tiktoken_enabled"] is False
    assert factory.call_args.kwargs["check_embedding_ctx_length"] is False


def test_explicit_embedding_key_takes_priority() -> None:
    fake_settings = SimpleNamespace(
        embedding_provider="openai",
        embedding_api_key="embedding-secret",
        embedding_base_url="https://api.siliconflow.cn/v1",
        embedding_model_name="BAAI/bge-m3",
        siliconflow_api_key="siliconflow-secret",
        openai_api_key="openai-secret",
        openai_base_url="https://api.openai.com/v1",
    )

    with (
        patch.object(model_factory, "settings", fake_settings),
        patch.object(model_factory, "_get_runtime_provider_setting", return_value={}),
        patch("langchain_openai.OpenAIEmbeddings") as factory,
    ):
        model_factory.get_embedding_model()

    assert factory.call_args.kwargs["api_key"] == "embedding-secret"
