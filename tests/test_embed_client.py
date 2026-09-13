import io
import json
import unittest

from services.web.embed_client import EmbedClient, validate_endpoint, QUERY_INSTRUCTION


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


class FakeOpener:
    def __init__(self, payload):
        self.payload = payload
        self.last_request = None

    def open(self, outgoing, timeout=None):
        self.last_request = outgoing
        return FakeResponse(self.payload)


def embeddings_payload(vector):
    return json.dumps({"data": [{"embedding": vector, "index": 0}]}).encode("utf-8")


class EmbedClientTests(unittest.TestCase):
    def test_endpoint_must_be_loopback(self):
        with self.assertRaises(ValueError):
            validate_endpoint("http://192.168.0.99:8082")
        self.assertEqual(validate_endpoint("http://127.0.0.1:8082/"), "http://127.0.0.1:8082")

    def test_embed_returns_vector(self):
        opener = FakeOpener(embeddings_payload([0.1, 0.2, 0.3]))
        client = EmbedClient("http://127.0.0.1:8082", opener=opener)
        self.assertEqual(client.embed("bonjour"), [0.1, 0.2, 0.3])

    def test_query_gets_instruction_prefix(self):
        opener = FakeOpener(embeddings_payload([1.0, 0.0]))
        client = EmbedClient("http://127.0.0.1:8082", opener=opener)
        client.embed("ma requête", is_query=True)
        sent = json.loads(opener.last_request.data)
        self.assertTrue(sent["input"].startswith(QUERY_INSTRUCTION))
        self.assertIn("ma requête", sent["input"])

    def test_document_has_no_prefix(self):
        opener = FakeOpener(embeddings_payload([1.0, 0.0]))
        client = EmbedClient("http://127.0.0.1:8082", opener=opener)
        client.embed("un passage", is_query=False)
        sent = json.loads(opener.last_request.data)
        self.assertEqual(sent["input"], "un passage")

    def test_rejects_empty_text(self):
        client = EmbedClient("http://127.0.0.1:8082", opener=FakeOpener(embeddings_payload([1.0])))
        with self.assertRaises(ValueError):
            client.embed("   ")

    def test_non_finite_is_rejected(self):
        opener = FakeOpener(json.dumps({"data": [{"embedding": [1.0, float("nan")]}]}).encode("utf-8"))
        client = EmbedClient("http://127.0.0.1:8082", opener=opener)
        with self.assertRaises(RuntimeError):
            client.embed("x")

    def test_zero_norm_is_rejected(self):
        opener = FakeOpener(embeddings_payload([0.0, 0.0]))
        client = EmbedClient("http://127.0.0.1:8082", opener=opener)
        with self.assertRaises(RuntimeError):
            client.embed("x")

    def test_invalid_shape_raises(self):
        opener = FakeOpener(json.dumps({"nope": True}).encode("utf-8"))
        client = EmbedClient("http://127.0.0.1:8082", opener=opener)
        with self.assertRaises(RuntimeError):
            client.embed("x")


if __name__ == "__main__":
    unittest.main()
