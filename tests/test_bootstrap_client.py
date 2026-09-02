import io
import json
import unittest

from services.web.bootstrap_client import BootstrapClient, validate_endpoint


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class Opener:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.requests = []

    def open(self, outgoing, timeout):
        self.requests.append((outgoing, timeout))
        return Response(self.payload)


class BootstrapClientTests(unittest.TestCase):
    def test_only_loopback_endpoint_is_accepted(self) -> None:
        self.assertEqual("http://127.0.0.1:8080", validate_endpoint("http://127.0.0.1:8080"))
        for endpoint in ["https://example.test", "http://192.0.2.1:8080", "http://user:pass@127.0.0.1:8080"]:
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                validate_endpoint(endpoint)

    def test_real_answer_shape_is_returned(self) -> None:
        opener = Opener(json.dumps({"choices": [{"message": {"content": "Bonjour"}}]}).encode())
        client = BootstrapClient(opener=opener)
        answer = client.generate([{"role": "user", "content": "Bonjour"}])
        self.assertEqual("Bonjour", answer)
        sent = json.loads(opener.requests[0][0].data)
        self.assertEqual("BOOTSTRAP", sent["model"])
        self.assertFalse(sent["stream"])

    def test_invalid_response_and_tool_roles_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            BootstrapClient(opener=Opener(b"{}")).generate([{"role": "tool", "content": "x"}])
        with self.assertRaises(RuntimeError):
            BootstrapClient(opener=Opener(b"{}")) .generate([{"role": "user", "content": "x"}])


if __name__ == "__main__":
    unittest.main()
