import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

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


def test_runtime_reader_factory_uses_configured_reader() -> None:
    reader = MagicMock()

    model_factory.configure_runtime_provider_settings(reader)
    try:
        result = model_factory._get_runtime_provider_setting_reader()
    finally:
        model_factory.configure_runtime_provider_settings(None)

    assert result is reader


def test_runtime_reader_factory_requires_configuration() -> None:
    model_factory.configure_runtime_provider_settings(None)

    with pytest.raises(RuntimeError, match="not configured"):
        model_factory._get_runtime_provider_setting_reader()


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
    assert factory.call_args.kwargs["http_async_client"].trust_env is False
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


def test_explicit_proxy_preserves_non_siliconflow_tokenization() -> None:
    fake_settings = SimpleNamespace(
        embedding_provider="openai", embedding_api_key="embedding-secret",
        embedding_base_url="https://embeddings.example/v1",
        embedding_proxy="socks5://proxy.example:1080",
        embedding_model_name="text-embedding-3-small", siliconflow_api_key="",
        openai_api_key="", openai_base_url="",
    )
    with (
        patch.object(model_factory, "settings", fake_settings),
        patch.object(model_factory, "_get_runtime_provider_setting", return_value={}),
        patch("httpx.Client") as sync_client,
        patch("httpx.AsyncClient") as async_client,
        patch("langchain_openai.OpenAIEmbeddings") as factory,
    ):
        model_factory.create_embedding_model()

    sync_client.assert_called_once_with(trust_env=False, proxy=fake_settings.embedding_proxy)
    async_client.assert_called_once_with(trust_env=False, proxy=fake_settings.embedding_proxy)
    assert factory.call_args.kwargs["tiktoken_enabled"] is True
    assert factory.call_args.kwargs["check_embedding_ctx_length"] is True


def test_sync_and_async_embeddings_use_explicit_proxy_despite_no_proxy(monkeypatch) -> None:
    requests = []

    class ProxyHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, self.headers.get("Authorization"), payload))
            body = json.dumps({
                "object": "list", "model": "BAAI/bge-m3",
                "data": [{"object": "embedding", "index": 0, "embedding": [0.25, 0.75]}],
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    fake_settings = SimpleNamespace(
        embedding_provider="openai", embedding_api_key="embedding-secret",
        embedding_base_url="http://api.siliconflow.cn/v1",
        embedding_proxy=f"http://127.0.0.1:{server.server_port}",
        embedding_model_name="BAAI/bge-m3", siliconflow_api_key="",
        openai_api_key="", openai_base_url="",
    )
    embeddings = None
    try:
        with (
            patch.object(model_factory, "settings", fake_settings),
            patch.object(model_factory, "_get_runtime_provider_setting", return_value={}),
        ):
            embeddings = model_factory.create_embedding_model()
        assert embeddings.embed_query("sync text") == [0.25, 0.75]

        async def embed_async():
            try:
                return await embeddings.aembed_query("async text")
            finally:
                await embeddings.http_async_client.aclose()

        assert asyncio.run(embed_async()) == [0.25, 0.75]
    finally:
        if embeddings is not None:
            embeddings.http_client.close()
            if not embeddings.http_async_client.is_closed:
                asyncio.run(embeddings.http_async_client.aclose())
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert [request[0] for request in requests] == ["http://api.siliconflow.cn/v1/embeddings"] * 2
    assert all(request[1] == "Bearer embedding-secret" for request in requests)
    assert [request[2]["input"] for request in requests] == [["sync text"], ["async text"]]
    assert all(request[2]["model"] == "BAAI/bge-m3" for request in requests)
