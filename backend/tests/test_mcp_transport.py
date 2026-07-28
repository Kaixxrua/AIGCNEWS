from __future__ import annotations

import unittest
from unittest.mock import MagicMock

import httpx

from backend.app.services.mcp.transport import StreamableHttpTransport
from backend.app.services.outbound_target_policy import PinnedHttpTarget


class McpTransportTests(unittest.TestCase):
    def test_client_options_preserve_timeout_proxy_and_redirect_contract(self) -> None:
        client = MagicMock(spec=httpx.Client)
        factory = MagicMock(return_value=client)
        transport = StreamableHttpTransport(
            headers={"MCP-Protocol-Version": "2025-06-18"},
            client_factory=factory,
        )

        result = transport.open()

        self.assertIs(result, client)
        kwargs = factory.call_args.kwargs
        self.assertFalse(kwargs["follow_redirects"])
        self.assertFalse(kwargs["trust_env"])
        self.assertEqual(kwargs["timeout"].connect, 5.0)
        self.assertEqual(kwargs["timeout"].read, 10.0)
        self.assertEqual(kwargs["timeout"].write, 5.0)
        self.assertEqual(kwargs["timeout"].pool, 5.0)
        self.assertEqual(
            kwargs["headers"],
            {"MCP-Protocol-Version": "2025-06-18"},
        )

    def test_post_uses_pinned_url_original_host_and_sni_extensions(self) -> None:
        client = MagicMock(spec=httpx.Client)
        target = PinnedHttpTarget(
            logical_url="https://mcp.example:8443/rpc",
            request_url="https://8.8.8.8:8443/rpc",
            host_header="mcp.example:8443",
            sni_hostname="mcp.example",
            selected_ip="8.8.8.8",
        )
        payload = {"jsonrpc": "2.0", "method": "tools/list", "id": 2}

        StreamableHttpTransport.stream_post(client, target, payload)

        client.stream.assert_called_once_with(
            "POST",
            "https://8.8.8.8:8443/rpc",
            json=payload,
            headers={"Host": "mcp.example:8443"},
            extensions={"sni_hostname": "mcp.example"},
        )


if __name__ == "__main__":
    unittest.main()
