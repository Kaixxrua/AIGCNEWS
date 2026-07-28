from __future__ import annotations

import unittest

from backend.app.services.mcp import protocol


class McpProtocolTests(unittest.TestCase):
    def test_fixed_handshake_payloads_preserve_wire_contract(self) -> None:
        self.assertEqual(
            protocol.initialize_payload(),
            {
                "jsonrpc": "2.0",
                "method": "initialize",
                "id": 1,
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "aigc-news-admin", "version": "1.0.0"},
                },
            },
        )
        self.assertEqual(
            protocol.initialized_payload(),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        self.assertEqual(
            protocol.tools_list_payload(),
            {"jsonrpc": "2.0", "method": "tools/list", "id": 2, "params": {}},
        )

    def test_numeric_and_string_response_ids_are_compatible(self) -> None:
        self.assertTrue(protocol.response_id_matches({"id": 2}, 2))
        self.assertTrue(protocol.response_id_matches({"id": "2"}, 2))
        with self.assertRaisesRegex(protocol.McpProtocolError, "id 与请求不匹配"):
            protocol.validate_json_rpc_data({"id": 3, "result": {}}, expected_id=2)

    def test_sse_decoder_skips_notifications_and_matches_requested_response(self) -> None:
        result = protocol.decode_sse_text(
            ': keepalive\n\n'
            'data: {"jsonrpc":"2.0","method":"notifications/progress"}\n\n'
            'data: {"jsonrpc":"2.0","id":"2","result":{"tools":[]}}\n\n',
            expected_id=2,
        )
        self.assertEqual(result["id"], "2")

    def test_tool_projection_caps_before_filtering_and_truncates_descriptions(self) -> None:
        raw_tools = [{"name": "", "description": "ignored"}] + [
            {"name": f"tool-{index}", "description": "x" * 300}
            for index in range(25)
        ]
        tools = protocol.extract_tools({"result": {"tools": raw_tools}})

        self.assertEqual(len(tools), 19)
        self.assertEqual(tools[0]["name"], "tool-0")
        self.assertEqual(len(tools[0]["description"]), 240)
        self.assertTrue(tools[0]["description"].endswith("…"))


if __name__ == "__main__":
    unittest.main()
