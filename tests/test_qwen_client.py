import io
import json
import unittest
from unittest.mock import patch

from services.common.private_endpoints import PrivateEndpoint
from services.web.qwen_client import QwenClient
from tests._private_endpoint_support import CORE_ENDPOINT, QWEN_ENDPOINT, synthetic_private_host


class QwenClientTests(unittest.TestCase):
    def setUp(self):
        self.client = QwenClient(QWEN_ENDPOINT.url, "x" * 32, pinned=QWEN_ENDPOINT)

    def test_endpoint_is_pinned_exactly_to_the_private_configuration(self):
        self.assertEqual(self.client.endpoint, QWEN_ENDPOINT.url)
        other_port = PrivateEndpoint("qwen_coder", QWEN_ENDPOINT.host, 8791)
        for endpoint, pinned in [
            (f"http://{synthetic_private_host(45)}:8790", QWEN_ENDPOINT),
            (QWEN_ENDPOINT.url + "/", QWEN_ENDPOINT),
            ("https://" + QWEN_ENDPOINT.url[len("http://"):], QWEN_ENDPOINT),
            (QWEN_ENDPOINT.url, other_port),
            (CORE_ENDPOINT.url, CORE_ENDPOINT),
            (QWEN_ENDPOINT.url, None),
        ]:
            with self.subTest(endpoint=endpoint, pinned=pinned), self.assertRaises(ValueError) as caught:
                QwenClient(endpoint, "x" * 32, pinned=pinned)
            self.assertNotIn(QWEN_ENDPOINT.host, str(caught.exception))
        with self.assertRaises(ValueError):
            QwenClient(QWEN_ENDPOINT.url, "short", pinned=QWEN_ENDPOINT)

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
