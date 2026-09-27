import io
import json
import unittest
from unittest.mock import patch

from services.common.private_endpoints import PrivateEndpoint
from services.web.core_client import CoreClient
from tests._private_endpoint_support import CORE_ENDPOINT, QWEN_ENDPOINT, synthetic_private_host


class CoreClientPinTests(unittest.TestCase):
    def test_accepts_only_the_pinned_private_endpoint(self) -> None:
        client = CoreClient(CORE_ENDPOINT.url, "x" * 32, pinned=CORE_ENDPOINT)
        self.assertEqual(client.endpoint, CORE_ENDPOINT.url)
        other_port = PrivateEndpoint("core_inference", CORE_ENDPOINT.host, 9001)
        for endpoint, pinned in [
            (f"http://{synthetic_private_host(99)}:9000", CORE_ENDPOINT),
            (CORE_ENDPOINT.url + "/", CORE_ENDPOINT),
            ("http://127.0.0.1:9000", CORE_ENDPOINT),
            (CORE_ENDPOINT.url, other_port),
            (QWEN_ENDPOINT.url, QWEN_ENDPOINT),
            (CORE_ENDPOINT.url, None),
        ]:
            with self.subTest(endpoint=endpoint, pinned=pinned), self.assertRaises(ValueError) as caught:
                CoreClient(endpoint, "x" * 32, pinned=pinned)
            self.assertNotIn(CORE_ENDPOINT.host, str(caught.exception))
        with self.assertRaises(ValueError):
            CoreClient(CORE_ENDPOINT.url, "x" * 31, pinned=CORE_ENDPOINT)

    def test_requests_go_to_the_pinned_endpoint_only(self) -> None:
        client = CoreClient(CORE_ENDPOINT.url, "x" * 32, pinned=CORE_ENDPOINT)
        payload = {"engine": "CORE-700M", "available": True, "state": "ready", "experimental": True}
        with patch("services.web.core_client.request.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as call:
            self.assertEqual(client.status(), payload)
        self.assertEqual(call.call_args.args[0].full_url, CORE_ENDPOINT.url + "/internal/v1/status")


if __name__ == "__main__":
    unittest.main()
