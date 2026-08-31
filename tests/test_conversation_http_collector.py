import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).parents[1] / "services" / "mcp-collector" / "conversation_http.py"
SPEC = importlib.util.spec_from_file_location("conversation_http", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ConversationHttpCollectorTests(unittest.TestCase):
    def test_bearer_token_must_match(self) -> None:
        token = "a" * 32
        self.assertTrue(MODULE.authorized(f"Bearer {token}", token))
        self.assertFalse(MODULE.authorized("Bearer wrong", token))

    def test_short_server_token_is_rejected(self) -> None:
        self.assertFalse(MODULE.authorized("Bearer short", "short"))

    def test_non_object_json_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.parse_submission(b"[]")

    def test_oversized_body_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.parse_submission(b"x" * (MODULE.MAX_BODY_BYTES + 1))


if __name__ == "__main__":
    unittest.main()
