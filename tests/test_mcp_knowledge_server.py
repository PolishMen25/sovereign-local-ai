import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).parents[1] / "services" / "knowledge" / "mcp_server.py"
SPEC = importlib.util.spec_from_file_location("mcp_knowledge_server", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class McpKnowledgeServerTests(unittest.TestCase):
    def initialized_server(self) -> bool:
        response, initialized = MODULE.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, False)
        self.assertEqual(response["result"]["protocolVersion"], "2025-06-18")
        response, initialized = MODULE.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}, initialized)
        self.assertIsNone(response)
        return initialized

    def test_tools_are_not_available_before_initialization(self) -> None:
        response, _ = MODULE.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, False)
        self.assertEqual(response["error"]["code"], -32002)

    def test_search_returns_bounded_provenance(self) -> None:
        previous = os.environ.get("SOVEREIGN_KNOWLEDGE_ROOT")
        os.environ["SOVEREIGN_KNOWLEDGE_ROOT"] = str(Path(__file__).parent / "fixtures")
        try:
            initialized = self.initialized_server()
            response, _ = MODULE.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "search_validated", "arguments": {"query": "restauration"}}}, initialized)
        finally:
            if previous is None:
                del os.environ["SOVEREIGN_KNOWLEDGE_ROOT"]
            else:
                os.environ["SOVEREIGN_KNOWLEDGE_ROOT"] = previous
        self.assertEqual(response["result"]["structuredContent"]["hits"][0]["provenance_id"], "pkg-1")

    def test_client_path_is_not_an_argument(self) -> None:
        initialized = self.initialized_server()
        response, _ = MODULE.handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search_validated", "arguments": {"query": "test", "path": "/etc/passwd"}}}, initialized)
        self.assertTrue(response["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
