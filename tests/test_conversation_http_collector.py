from contextlib import ExitStack, redirect_stderr
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import sys
import unittest
from unittest import mock
from uuid import uuid4

from tests._temp_support import sovereign_temporary_directory


MODULE_PATH = Path(__file__).parents[1] / "services" / "mcp-collector" / "conversation_http.py"
SPEC = importlib.util.spec_from_file_location("conversation_http", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

TEST_TOKEN = "synthetic-collector-token-" + "x" * 16
REJECTED_BODY = b'{"error":"submission_rejected"}'


class InMemoryConnection:
    """Socket stand-in: the real handler parses raw HTTP bytes, no port is opened."""

    def __init__(self, request: bytes) -> None:
        self._incoming = io.BytesIO(request)
        self.sent = bytearray()

    def makefile(self, mode: str, *_arguments: object, **_keywords: object) -> io.BytesIO:
        if "r" not in mode:
            raise AssertionError("the handler is expected to write through sendall")
        return self._incoming

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)


def conversation(content: str = "Documente la procédure de sauvegarde.") -> dict:
    return {
        "schema_version": "0.1.0", "conversation_id": str(uuid4()), "captured_at": "2026-08-31T12:00:00Z",
        "messages": [{"role": "user", "content": content}],
    }


class CollectorSurfaceTests(unittest.TestCase):
    """Pin the V0 ingress surface: generic refusals, status-only logs, no write on rejection."""

    def setUp(self) -> None:
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.workbench = Path(stack.enter_context(sovereign_temporary_directory()))
        environment = {"SOVEREIGN_COLLECTOR_TOKEN": TEST_TOKEN, "SOVEREIGN_WORKBENCH_ROOT": str(self.workbench)}
        stack.enter_context(mock.patch.dict(os.environ, environment))

    def exchange(
        self, method: str, path: str, body: bytes = b"", *, headers: dict[str, str] | None = None
    ) -> tuple[int, bytes, str]:
        if headers is None:
            headers = {"Authorization": f"Bearer {TEST_TOKEN}", "Content-Type": "application/json"}
        lines = [f"{method} {path} HTTP/1.1", "Host: collector.test", *(f"{name}: {value}" for name, value in headers.items())]
        if body or method in {"POST", "PUT", "PATCH"}:
            lines.append(f"Content-Length: {len(body)}")
        connection = InMemoryConnection(("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body)
        log = io.StringIO()
        with redirect_stderr(log):
            MODULE.CollectorHandler(connection, ("client", 0), None)
        head, _separator, payload = bytes(connection.sent).partition(b"\r\n\r\n")
        status = int(head.split(b"\r\n", 1)[0].split(b" ")[1])
        return status, payload, log.getvalue()

    def assert_nothing_written(self) -> None:
        self.assertEqual(sorted(self.workbench.rglob("*")), [])

    def test_rejected_bodies_get_a_generic_reply_a_status_only_log_and_no_raw_write(self) -> None:
        marker = f"do-not-echo-{uuid4().hex}"
        unknown_field = conversation(); unknown_field["file_path"] = marker
        wrong_version = conversation(marker); wrong_version["schema_version"] = "9.9.9"
        bad_identifier = conversation(marker); bad_identifier["conversation_id"] = marker
        bad_role = conversation(marker); bad_role["messages"][0]["role"] = "operator"
        cases = {
            "invalid_json": ('{"' + marker).encode("utf-8"),
            "non_object": json.dumps([marker]).encode("utf-8"),
            "unknown_field": json.dumps(unknown_field).encode("utf-8"),
            "wrong_schema_version": json.dumps(wrong_version).encode("utf-8"),
            "bad_conversation_id": json.dumps(bad_identifier).encode("utf-8"),
            "bad_role": json.dumps(bad_role).encode("utf-8"),
            "likely_secret": json.dumps(conversation(f"password: {marker}")).encode("utf-8"),
        }
        for name, body in cases.items():
            with self.subTest(case=name):
                status, payload, log = self.exchange("POST", "/v1/conversations", body)
                self.assertEqual(status, 422)
                self.assertEqual(payload, REJECTED_BODY)
                self.assertEqual(log, "collector event status=422\n")
                self.assertNotIn(marker, log)
                self.assert_nothing_written()

    def test_refusals_before_the_body_is_read_write_nothing(self) -> None:
        body = json.dumps(conversation()).encode("utf-8")
        cases = {
            "missing_token": ({"Content-Type": "application/json"}, 401, {"error": "unauthorized"}),
            "wrong_token": ({"Authorization": "Bearer " + "y" * 42, "Content-Type": "application/json"}, 401, {"error": "unauthorized"}),
            "wrong_media_type": ({"Authorization": f"Bearer {TEST_TOKEN}", "Content-Type": "text/plain"}, 415, {"error": "unsupported_media_type"}),
        }
        for name, (headers, expected_status, expected_payload) in cases.items():
            with self.subTest(case=name):
                status, payload, log = self.exchange("POST", "/v1/conversations", body, headers=headers)
                self.assertEqual((status, json.loads(payload)), (expected_status, expected_payload))
                self.assertEqual(log, f"collector event status={expected_status}\n")
                self.assert_nothing_written()

    def test_accepted_receipt_has_exactly_state_conversation_id_and_sha256(self) -> None:
        marker = f"content-{uuid4().hex}"
        document = conversation(marker)
        status, payload, log = self.exchange("POST", "/v1/conversations", json.dumps(document).encode("utf-8"))
        self.assertEqual(status, 202)
        receipt = json.loads(payload)
        self.assertEqual(set(receipt), {"state", "conversation_id", "sha256"})
        self.assertEqual(receipt["state"], "raw_imported")
        self.assertEqual(receipt["conversation_id"], document["conversation_id"])
        self.assertRegex(receipt["sha256"], re.compile(r"^[0-9a-f]{64}$"))
        self.assertNotIn(marker.encode("utf-8"), payload)
        self.assertEqual(log, "collector event status=202\n")

    def test_get_serves_only_healthz(self) -> None:
        status, payload, log = self.exchange("GET", "/healthz", headers={})
        self.assertEqual((status, json.loads(payload)), (200, {"status": "ok", "mode": "write-only"}))
        self.assertEqual(log, "collector event status=200\n")
        for path in ("/", "/healthz/", "/healthz?verbose=1", "/v1/conversations", f"/v1/conversations/{uuid4()}", "/raw/conversations"):
            with self.subTest(path=path):
                status, payload, _log = self.exchange("GET", path, headers={})
                self.assertEqual((status, json.loads(payload)), (404, {"error": "not_found"}))
        self.assert_nothing_written()

    def test_post_accepts_only_the_conversations_route(self) -> None:
        body = json.dumps(conversation()).encode("utf-8")
        for path in ("/", "/healthz", "/v1/conversations/", "/v1/conversations?replay=1", "/v1/research-packages", "/v2/conversations"):
            with self.subTest(path=path):
                status, payload, log = self.exchange("POST", path, body)
                self.assertEqual((status, json.loads(payload)), (404, {"error": "not_found"}))
                self.assertEqual(log, "collector event status=404\n")
        self.assert_nothing_written()

    def test_put_delete_patch_are_not_implemented(self) -> None:
        # Seule la ligne de statut est épinglée : sur ce chemin, send_error
        # journalise aussi un message qui recopie la méthode du client (écart
        # connu, voir test_unsupported_method_log_carries_status_only).
        body = json.dumps(conversation()).encode("utf-8")
        for method in ("PUT", "DELETE", "PATCH"):
            with self.subTest(method=method):
                self.assertFalse(hasattr(MODULE.CollectorHandler, f"do_{method}"))
                status, _payload, log = self.exchange(method, "/v1/conversations", body)
                self.assertEqual(status, 501)
                self.assertIn("collector event status=501\n", log)
        self.assert_nothing_written()

    def test_client_chosen_method_is_not_implemented_and_writes_nothing(self) -> None:
        method = "FOOBAR" + uuid4().hex.upper()
        status, _payload, log = self.exchange(method, "/v1/conversations")
        self.assertEqual(status, 501)
        self.assertIn("collector event status=501\n", log)
        self.assert_nothing_written()

    @unittest.expectedFailure
    def test_unsupported_method_log_carries_status_only(self) -> None:
        """Écart connu du code de production, consigné ici plutôt que masqué.

        BaseHTTPRequestHandler.send_error appelle log_error(format, code, message)
        et log_message journalise arguments[1] : le message « Unsupported method »
        recopie donc dans le journal une méthode choisie par le client. Ce test
        deviendra un succès inattendu quand le collecteur ne journalisera plus que
        des statuts numériques ; cette correction relève du code de production,
        après la PR #17, et non de ce lot de tests.
        """
        method = "FOOBAR" + uuid4().hex.upper()
        _status, _payload, log = self.exchange(method, "/v1/conversations")
        self.assertNotIn(method, log)
        self.assertEqual(log, "collector event status=501\n")


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

    def test_non_loopback_host_refuses_to_start(self) -> None:
        for host in ("0.0.0.0", "::", "::1", "localhost", "192.0.2.10"):
            with self.subTest(host=host):
                with mock.patch.dict(
                    os.environ, {"SOVEREIGN_COLLECTOR_HOST": host}
                ):
                    with self.assertRaisesRegex(SystemExit, "loopback-only"):
                        MODULE.main()


if __name__ == "__main__":
    unittest.main()
