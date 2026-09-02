import json
import unittest

from services.web.app import authorize, parse_chat, response


class WebAppTests(unittest.TestCase):
    def test_authorization_is_constant_time_and_requires_long_token(self) -> None:
        token = "x" * 32
        self.assertTrue(authorize(f"Bearer {token}", token))
        self.assertFalse(authorize("Bearer wrong", token))
        self.assertFalse(authorize(f"Bearer {'x' * 8}", "x" * 8))

    def test_chat_parser_rejects_wrong_schema(self) -> None:
        with self.assertRaises(ValueError):
            parse_chat(b'{"schema_version":"wrong"}')

    def test_response_matches_local_contract(self) -> None:
        payload = response(
            "req-123456",
            "coordination",
            "error",
            "not ready",
            engine="BOOTSTRAP",
            conversation_id="conversation_001",
        )
        self.assertEqual(payload["schema_version"], "local-assistant-response.v1")
        self.assertEqual(payload["engine"], "BOOTSTRAP")
        self.assertEqual(json.loads(json.dumps(payload))["status"], "error")


if __name__ == "__main__":
    unittest.main()
