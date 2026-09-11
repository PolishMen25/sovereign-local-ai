"""End-to-end HTTP behaviour of the loopback gateway (services/web/app.py).

The gateway runs on 127.0.0.1 with in-memory fakes for authentication,
memory, knowledge and engines, so the suite needs neither argon2 nor a model.
It pins status codes, JSON error codes, cookies, security headers and the
server-sent-event sequences, so the handler can be restructured safely.
"""

from __future__ import annotations

import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from typing import Any

from services.web import app as gateway

SETUP_TOKEN = "s" * 40
SESSION = "session-token-0001"
CSRF = "csrf-token-0001"


class FakeAuthentication:
    def __init__(self) -> None:
        self.owner = False
        self.logged_out: list[str] = []

    def setup_required(self) -> bool:
        return not self.owner

    def initialize_owner(self, username: str, password: str) -> None:
        if self.owner:
            raise RuntimeError("owner already exists")
        if len(password) < 12:
            raise ValueError("password too short")
        self.owner = True

    def authenticate(self, username: str, password: str) -> dict[str, str]:
        if not (self.owner and username == "owner" and password == "correct-horse-battery"):
            raise PermissionError("authentication failed")
        return {"session_token": SESSION, "csrf_token": CSRF, "expires_at": "2026-09-12T00:00:00Z"}

    def validate_session(self, token: str, *, csrf_token: str | None, require_csrf: bool) -> str:
        if token != SESSION or token in self.logged_out or (require_csrf and csrf_token != CSRF):
            raise PermissionError("invalid session")
        return "owner"

    def session_details(self, token: str) -> dict[str, str]:
        if token != SESSION:
            raise PermissionError("invalid session")
        return {"username": "owner", "expires_at": "2026-09-12T00:00:00Z"}

    def logout(self, token: str) -> None:
        self.logged_out.append(token)


class FakeMemory:
    def __init__(self) -> None:
        self.conversations: dict[str, list[dict[str, str]]] = {}

    def create_conversation(self, *, title: str) -> str:
        conversation_id = f"conversation_{len(self.conversations) + 1:03d}"
        self.conversations[conversation_id] = []
        return conversation_id

    def append_message(self, conversation_id: str, *, role: str, content: str) -> dict[str, str]:
        if conversation_id not in self.conversations:
            raise KeyError(conversation_id)
        self.conversations[conversation_id].append({"role": role, "content": content})
        return {"role": role}

    def export_conversation(self, conversation_id: str) -> dict[str, Any]:
        if conversation_id not in self.conversations:
            raise KeyError(conversation_id)
        return {"conversation_id": conversation_id, "messages": list(self.conversations[conversation_id])}

    def list_conversations(self) -> list[dict[str, str]]:
        return [{"conversation_id": key, "title": key, "updated_at": "2026-09-11"} for key in self.conversations]

    def delete_conversation(self, conversation_id: str) -> dict[str, str]:
        if self.conversations.pop(conversation_id, None) is None:
            raise KeyError(conversation_id)
        return {"status": "deleted", "conversation_id": conversation_id}


class FakeKnowledge:
    def status(self) -> dict[str, Any]:
        return {"documents": 1, "mode": "lexical"}

    def search(self, query: str, *, query_embedding: Any, limit: int) -> dict[str, Any]:
        if "BADQUERY" in query:
            raise ValueError("query refused")
        if "RAG" not in query:
            return {"hits": []}
        return {"hits": [{"document_id": "project:status.md", "title": "Statut", "provenance_id": "project-sha256:abc", "summary": "Résumé local."}]}


class FakeBootstrap:
    engine = "BOOTSTRAP"

    def __init__(self) -> None:
        self.last_messages: list[dict[str, str]] = []

    def status(self) -> dict[str, Any]:
        return {"available": True, "state": "ready"}

    def generate(self, messages: list[dict[str, str]]) -> str:
        self.last_messages = messages
        if "PANNE" in messages[-1]["content"]:
            raise RuntimeError("down")
        return "bootstrap:" + messages[-1]["content"]

    def stream(self, messages: list[dict[str, str]]):
        self.last_messages = messages
        yield "bonjour "
        if "PANNE" in messages[-1]["content"]:
            raise RuntimeError("stream interrupted")
        yield "local"


class FakeCore:
    def status(self) -> dict[str, Any]:
        return {"available": False, "state": "checkpoint_refused"}

    def generate(self, prompt: str) -> str:
        raise RuntimeError("CORE checkpoint refused")


class FakeQwen:
    def __init__(self) -> None:
        self.last_messages: list[dict[str, str]] = []

    def status(self) -> dict[str, Any]:
        return {"available": True, "state": "ready"}

    def generate(self, messages: list[dict[str, str]]) -> str:
        self.last_messages = messages
        return "qwen:" + messages[-1]["content"]


class QuietHandler(gateway.LocalWebHandler):
    def log_message(self, format_string: str, *arguments: object) -> None:
        pass


class GatewayTestCase(unittest.TestCase):
    def start(self, qwen_runtime: Any) -> None:
        self.auth, self.memory = FakeAuthentication(), FakeMemory()
        self.bootstrap = FakeBootstrap()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        self.server.state = gateway.WebState(self.auth, self.memory, self.bootstrap, FakeCore(), FakeKnowledge(), SETUP_TOKEN, qwen_runtime)  # type: ignore[attr-defined]
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method: str, path: str, body: Any = None, *, headers: dict[str, str] | None = None, session: bool = False, csrf: bool = False) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        all_headers = dict(headers or {})
        if body is not None and not isinstance(body, bytes):
            body = json.dumps(body).encode()
            all_headers.setdefault("Content-Type", "application/json")
        if session:
            all_headers["Cookie"] = f"sovereign_session={SESSION}"
        if csrf:
            all_headers["X-CSRF-Token"] = CSRF
        connection.request(method, path, body=body, headers=all_headers)
        reply = connection.getresponse()
        payload = reply.read()
        connection.close()
        return reply.status, {k.lower(): v for k, v in reply.getheaders()}, payload

    def login(self) -> None:
        self.auth.owner = True

    def chat(self, message: str, **fields: Any) -> dict[str, Any]:
        return {"schema_version": "local-chat-request.v1", "request_id": "req-12345678", "message": message, **fields}

    @staticmethod
    def events(payload: bytes) -> list[tuple[str, dict[str, Any]]]:
        result = []
        for block in payload.decode().strip().split("\n\n"):
            event_line, data_line = block.split("\n")
            result.append((event_line[len("event: "):], json.loads(data_line[len("data: "):])))
        return result



class GatewayHttpTests(GatewayTestCase):
    def setUp(self) -> None:
        self.qwen = FakeQwen()
        self.start(self.qwen)

    def test_public_routes_and_security_headers(self) -> None:
        status, headers, body = self.request("GET", "/healthz")
        self.assertEqual((status, json.loads(body)), (200, {"status": "ok", "mode": "loopback-gateway", "engine": "BOOTSTRAP"}))
        for name in ("cache-control", "x-content-type-options", "referrer-policy", "content-security-policy"):
            self.assertIn(name, headers)
        self.assertEqual(headers["content-security-policy"], "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.assertEqual(json.loads(self.request("GET", "/v1/setup-status")[2]), {"setup_required": True, "engine": "BOOTSTRAP"})
        status, headers, body = self.request("GET", "/")
        self.assertEqual((status, headers["content-type"]), (200, "text/html; charset=utf-8"))
        self.assertEqual(self.request("GET", "/app.js")[1]["content-type"], "text/javascript; charset=utf-8")

    def test_private_routes_require_a_session(self) -> None:
        for path in ("/v1/session", "/v1/profiles", "/v1/engines", "/v1/conversations", "/v1/unknown"):
            status, _, body = self.request("GET", path)
            self.assertEqual((status, json.loads(body)), (401, {"error": "unauthorized"}), path)

    def test_setup_is_token_gated_and_single_use(self) -> None:
        credentials = {"username": "owner", "password": "correct-horse-battery"}
        self.assertEqual(self.request("POST", "/v1/setup", credentials)[0], 401)
        self.assertEqual(self.request("POST", "/v1/setup", credentials, headers={"X-Setup-Token": "wrong"})[0], 401)
        self.assertEqual(self.request("POST", "/v1/setup", {"username": "owner"}, headers={"X-Setup-Token": SETUP_TOKEN})[:1], (422,))
        status, _, body = self.request("POST", "/v1/setup", credentials, headers={"X-Setup-Token": SETUP_TOKEN})
        self.assertEqual((status, json.loads(body)), (201, {"status": "owner_initialized"}))
        self.assertEqual(json.loads(self.request("POST", "/v1/setup", credentials, headers={"X-Setup-Token": SETUP_TOKEN})[2]), {"error": "setup_refused"})

    def test_login_sets_a_strict_cookie_and_logout_expires_it(self) -> None:
        self.login()
        status, _, body = self.request("POST", "/v1/login", {"username": "owner", "password": "wrong-password"})
        self.assertEqual((status, json.loads(body)), (401, {"error": "authentication_failed"}))
        self.assertEqual(self.request("POST", "/v1/login", b"not json", headers={"Content-Type": "application/json"})[0], 401)
        status, headers, body = self.request("POST", "/v1/login", {"username": "owner", "password": "correct-horse-battery"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"csrf_token": CSRF, "expires_at": "2026-09-12T00:00:00Z", "engine": "BOOTSTRAP"})
        self.assertEqual(headers["set-cookie"], f"sovereign_session={SESSION}; Path=/; Max-Age=43200; Secure; HttpOnly; SameSite=Strict")
        self.assertEqual(self.request("POST", "/v1/logout", {}, session=True)[0], 401)
        status, headers, body = self.request("POST", "/v1/logout", {}, session=True, csrf=True)
        self.assertEqual((status, json.loads(body)), (200, {"status": "logged_out"}))
        self.assertEqual(headers["set-cookie"], "sovereign_session=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict")

    def test_authenticated_read_routes(self) -> None:
        self.login()
        self.assertEqual(json.loads(self.request("GET", "/v1/session", session=True)[2]), {"username": "owner", "expires_at": "2026-09-12T00:00:00Z", "engine": "BOOTSTRAP", "rag_mode": "lexical"})
        self.assertEqual(json.loads(self.request("GET", "/v1/profiles", session=True)[2])["profiles"][0]["profile_id"], "coordination")
        engines = json.loads(self.request("GET", "/v1/engines", session=True)[2])["engines"]
        self.assertEqual([(e["engine"], e["available"]) for e in engines], [("BOOTSTRAP", True), ("CORE-700M", False), ("QWEN-CODER", True)])
        self.assertEqual(json.loads(self.request("GET", "/v1/knowledge-status", session=True)[2]), {"documents": 1, "mode": "lexical"})
        self.assertEqual(self.request("GET", "/v1/conversations/conversation_404/export", session=True)[0], 404)
        self.assertEqual(json.loads(self.request("GET", "/v1/nope", session=True)[2]), {"error": "not_found"})

    def test_chat_validation_errors(self) -> None:
        self.login()
        self.assertEqual(self.request("POST", "/v1/chat", self.chat("x"), session=True)[0], 401)
        self.assertEqual(json.loads(self.request("POST", "/v1/chat", b"{}", headers={"Content-Type": "text/plain"}, session=True, csrf=True)[2]), {"error": "unsupported_media_type"})
        self.assertEqual(json.loads(self.request("POST", "/v1/chat", {"schema_version": "wrong"}, session=True, csrf=True)[2]), {"error": "invalid_request"})
        self.assertEqual(json.loads(self.request("POST", "/v1/chat", self.chat("x", profile_id="security_auditor"), session=True, csrf=True)[2]), {"error": "unknown_profile"})
        self.assertEqual(json.loads(self.request("POST", "/v1/chat", self.chat("x", conversation_id="conversation_404"), session=True, csrf=True)[2]), {"error": "conversation_not_found"})
        self.assertEqual(self.request("POST", "/v1/other", {}, session=True, csrf=True)[0], 404)

    def test_bootstrap_chat_json_with_citations_and_history(self) -> None:
        self.login()
        status, _, body = self.request("POST", "/v1/chat", self.chat("Question RAG"), session=True, csrf=True)
        first = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual((first["engine"], first["status"], first["answer"], first["conversation_id"]), ("BOOTSTRAP", "completed", "bootstrap:Question RAG", "conversation_001"))
        self.assertEqual(first["citations"], [{"document_id": "project:status.md", "title": "Statut", "provenance_id": "project-sha256:abc"}])
        roles = [m["role"] for m in self.bootstrap.last_messages]
        self.assertEqual(roles, ["system", "system", "user"])
        self.assertIn("[Référence 1: Statut | project-sha256:abc]", self.bootstrap.last_messages[1]["content"])
        self.request("POST", "/v1/chat", self.chat("Suite BADQUERY", conversation_id="conversation_001"), session=True, csrf=True)
        self.assertEqual([m["role"] for m in self.bootstrap.last_messages], ["system", "user", "assistant", "user"])
        self.assertEqual(self.memory.conversations["conversation_001"][-1], {"role": "assistant", "content": "bootstrap:Suite BADQUERY"})

    def test_bootstrap_stream_events(self) -> None:
        self.login()
        status, headers, body = self.request("POST", "/v1/chat", self.chat("Salut"), headers={"Accept": "text/event-stream"}, session=True, csrf=True)
        self.assertEqual((status, headers["content-type"], headers["x-accel-buffering"]), (200, "text/event-stream; charset=utf-8", "no"))
        events = self.events(body)
        self.assertEqual([name for name, _ in events], ["metadata", "delta", "delta", "completed"])
        self.assertEqual(events[0][1], {"conversation_id": "conversation_001", "engine": "BOOTSTRAP", "rag_mode": "lexical"})
        self.assertEqual(events[-1][1]["answer"], "bonjour local")
        status, _, body = self.request("POST", "/v1/chat", self.chat("PANNE"), headers={"Accept": "text/event-stream"}, session=True, csrf=True)
        events = self.events(body)
        self.assertEqual([name for name, _ in events], ["metadata", "delta", "error"])
        self.assertEqual((events[-1][1]["error"], events[-1][1]["status"]), ("runtime_unavailable", "error"))

    def test_other_engines_and_failures(self) -> None:
        self.login()
        body = json.loads(self.request("POST", "/v1/chat", self.chat("écris une fonction", engine="QWEN-CODER"), session=True, csrf=True)[2])
        self.assertEqual((body["engine"], body["answer"]), ("QWEN-CODER", "qwen:écris une fonction"))
        self.assertTrue(self.qwen.last_messages[0]["content"].startswith("Tu es Qwen Coder"))
        status, _, raw = self.request("POST", "/v1/chat", self.chat("bonjour", engine="CORE-700M"), session=True, csrf=True)
        self.assertEqual((status, json.loads(raw)["engine"], json.loads(raw)["status"]), (503, "CORE-700M", "error"))
        status, _, raw = self.request("POST", "/v1/chat", self.chat("bonjour", engine="CORE-700M"), headers={"Accept": "text/event-stream"}, session=True, csrf=True)
        self.assertEqual([name for name, _ in self.events(raw)], ["error"])
        status, _, raw = self.request("POST", "/v1/chat", self.chat("PANNE"), session=True, csrf=True)
        self.assertEqual(status, 503)
        status, _, raw = self.request("POST", "/v1/chat", self.chat("code", engine="QWEN-CODER"), headers={"Accept": "text/event-stream"}, session=True, csrf=True)
        self.assertEqual([name for name, _ in self.events(raw)], ["metadata", "completed"])

    def test_conversation_list_export_and_delete(self) -> None:
        self.login()
        self.request("POST", "/v1/chat", self.chat("Salut"), session=True, csrf=True)
        self.assertEqual(json.loads(self.request("GET", "/v1/conversations", session=True)[2])["conversations"][0]["conversation_id"], "conversation_001")
        self.assertEqual(len(json.loads(self.request("GET", "/v1/conversations/conversation_001/export", session=True)[2])["messages"]), 2)
        self.assertEqual(self.request("DELETE", "/v1/conversations/conversation_001", session=True)[0], 401)
        self.assertEqual(json.loads(self.request("DELETE", "/v1/conversations/conversation_001", session=True, csrf=True)[2]), {"status": "deleted", "conversation_id": "conversation_001"})
        self.assertEqual(self.request("DELETE", "/v1/conversations/conversation_001", session=True, csrf=True)[0], 404)
        self.assertEqual(self.request("DELETE", "/v1/elsewhere", session=True, csrf=True)[0], 404)


class UnconfiguredQwenTests(GatewayTestCase):
    """Without SOVEREIGN_QWEN_TOKEN the gateway must answer, not drop the connection."""

    def check(self, qwen_runtime: Any, expected_state: str) -> None:
        self.start(qwen_runtime)
        self.login()
        status, _, body = self.request("GET", "/v1/engines", session=True)
        qwen = json.loads(body)["engines"][2]
        self.assertEqual((status, qwen["engine"], qwen["available"]), (200, "QWEN-CODER", False))
        self.assertIn(expected_state, qwen["description"])
        status, _, body = self.request("POST", "/v1/chat", self.chat("code", engine="QWEN-CODER"), session=True, csrf=True)
        self.assertEqual((status, json.loads(body)["status"], json.loads(body)["engine"]), (503, "error", "QWEN-CODER"))
        status, _, body = self.request("POST", "/v1/chat", self.chat("code", engine="QWEN-CODER"), headers={"Accept": "text/event-stream"}, session=True, csrf=True)
        self.assertEqual([name for name, _ in self.events(body)], ["error"])

    def test_unconfigured_engine_placeholder(self) -> None:
        self.check(gateway.UnconfiguredEngine("QWEN-CODER"), "not_configured")

    def test_missing_qwen_runtime(self) -> None:
        self.check(None, "unavailable")

    def test_local_runtime_placeholder_does_not_crash_the_engine_list(self) -> None:
        from pathlib import Path
        from services.inference.runtime import LocalInferenceRuntime
        self.start(LocalInferenceRuntime("QWEN-CODER", Path("/nonexistent-qwen-checkpoint")))
        self.login()
        status, _, body = self.request("GET", "/v1/engines", session=True)
        self.assertEqual((status, json.loads(body)["engines"][2]["available"]), (200, False))


if __name__ == "__main__":
    unittest.main()
