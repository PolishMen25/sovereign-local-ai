import io
import json
import unittest
from unittest.mock import patch

from services.web.qwen_client import QwenClient


class QwenClientTests(unittest.TestCase):
    def setUp(self):
        self.client = QwenClient("http://192.168.0.144:8790", "x" * 32)

    def test_preserves_history_and_references_in_order(self):
        messages = [
            {"role": "system", "content": "Local coding assistant"},
            {"role": "system", "content": "Reference: project uses Python"},
            {"role": "user", "content": "Name the function alpha"},
            {"role": "assistant", "content": "def alpha(): pass"},
            {"role": "user", "content": "Keep its name"},
        ]
        payload = {"choices": [{"message": {"content": "alpha"}}]}
        with patch("services.web.qwen_client.request.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as call:
            self.assertEqual("alpha", self.client.generate(messages))
        self.assertEqual(messages, json.loads(call.call_args.args[0].data)["messages"])

    def test_rejects_empty_and_malformed_answers(self):
        for payload in [None, {}, {"choices": []}, {"choices": [{"message": {"content": "  "}}]}]:
            with self.subTest(payload=payload), patch("services.web.qwen_client.request.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())):
                with self.assertRaises(RuntimeError):
                    self.client.generate("hello")

    def test_rejects_malformed_health(self):
        with patch("services.web.qwen_client.request.urlopen", return_value=io.BytesIO(b'[]')):
            with self.assertRaises(RuntimeError):
                self.client.status()

    def test_rejects_invalid_history_before_network(self):
        with patch("services.web.qwen_client.request.urlopen") as call:
            for messages in [[], [{"role": "tool", "content": "x"}], [{"role": "user", "content": None}]]:
                with self.assertRaises(RuntimeError):
                    self.client.generate(messages)
            call.assert_not_called()
