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
from services.web.action_switch import ActionSwitch

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

    def documents(self) -> list[dict[str, Any]]:
        return [{"provenance_id": "upload:doc", "title": "Doc", "chunks": 1, "characters": 20}]

    def chunks_for_provenance(self, provenance_id: str) -> list[dict[str, Any]]:
        return [] if provenance_id != "upload:doc" else [{"document_id": "upload:doc:000", "title": "Doc", "content": "Contenu local."}]


class FakeBootstrap:
    engine = "BOOTSTRAP"

    def __init__(self) -> None:
        self.last_messages: list[dict[str, str]] = []
        self.offered_tools: list[set[str]] = []

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

    def chat_with_tools(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        self.last_messages = messages
        self.offered_tools.append({spec["function"]["name"] for spec in tools})
        if messages[-1].get("role") == "tool":  # resuming after a tool/action result
            return {"content": "résultat intégré: " + (messages[-1].get("content") or "")[:40], "tool_calls": []}
        last = messages[-1].get("content") or ""
        if "PANNE" in last:
            raise RuntimeError("down")
        if "ECRIS" in last and tools:
            return {"content": None, "tool_calls": [{"id": "w1", "function": {"name": "write_file", "arguments": '{"path": "note.md", "content": "CONTENU_TEST", "purpose": "test"}'}}]}
        if "EXECUTE" in last and tools:
            return {"content": None, "tool_calls": [{"id": "a1", "function": {"name": "run_python", "arguments": '{"code": "print(1)", "purpose": "test"}'}}]}
        if "CHERCHE" in last and tools:
            return {"content": None, "tool_calls": [{"id": "c1", "function": {"name": "search_knowledge", "arguments": '{"query": "RAG local"}'}}]}
        return {"content": "outil:" + last, "tool_calls": []}


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

    def log_security_event(self, event: str, **fields: str) -> None:
        self.server.security_events.append((event, fields))  # type: ignore[attr-defined]


class GatewayTestCase(unittest.TestCase):
    def start(self, qwen_runtime: Any) -> None:
        self.auth, self.memory = FakeAuthentication(), FakeMemory()
        self.bootstrap = FakeBootstrap()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        self.server.state = gateway.WebState(self.auth, self.memory, self.bootstrap, FakeCore(), FakeKnowledge(), SETUP_TOKEN, qwen_runtime, tools_enabled=False)  # type: ignore[attr-defined]
        self.server.security_events = []  # type: ignore[attr-defined]
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

    def enable_actions(self) -> None:
        """D-035: what SOVEREIGN_ACTIONS_ENABLED=1 gives the gateway at startup."""
        self.server.state.action_switch = ActionSwitch(enabled=True)

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
        self.assertEqual(json.loads(self.request("GET", "/v1/session", session=True)[2]), {"username": "owner", "expires_at": "2026-09-12T00:00:00Z", "engine": "BOOTSTRAP", "rag_mode": "lexical", "actions_enabled": False})
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

    def test_bootstrap_tools_stream(self) -> None:
        self.login()
        self.server.state.tools_enabled = True
        # Plain turn: the model answers directly, no tool call.
        status, headers, body = self.request("POST", "/v1/chat", self.chat("Salut"), headers={"Accept": "text/event-stream"}, session=True, csrf=True)
        events = self.events(body)
        self.assertEqual((status, [name for name, _ in events]), (200, ["metadata", "completed"]))
        self.assertEqual(events[0][1]["rag_mode"], "tools")
        self.assertTrue(events[-1][1]["answer"].startswith("outil:"))
        # Tool turn: the model calls search_knowledge, then answers using the result.
        _, _, body = self.request("POST", "/v1/chat", self.chat("CHERCHE le statut"), headers={"Accept": "text/event-stream"}, session=True, csrf=True)
        events = self.events(body)
        self.assertEqual([name for name, _ in events], ["metadata", "tool", "completed"])
        self.assertEqual(events[1][1], {"name": "search_knowledge"})
        self.assertEqual(events[-1][1]["citations"][0]["provenance_id"], "project-sha256:abc")
        # Runtime failure surfaces as an error event.
        _, _, body = self.request("POST", "/v1/chat", self.chat("PANNE"), headers={"Accept": "text/event-stream"}, session=True, csrf=True)
        self.assertEqual([name for name, _ in self.events(body)], ["metadata", "error"])

    def test_catalog_profiles_route(self) -> None:
        self.login()
        self.server.state.tools_enabled = True
        self.server.state.catalog = [
            {"profile_id": "threat_modeler", "display_name": "threat modeler", "family": "security",
             "mission": "Modélise les menaces", "engine": "BOOTSTRAP", "system_prompt": "PERSONA-14B", "tools": True},
            {"profile_id": "test_designer", "display_name": "test designer", "family": "development",
             "mission": "Conçoit des tests", "engine": "QWEN-CODER", "system_prompt": "PERSONA-CODE", "tools": False},
        ]
        # catalog present in the selectable list
        profiles = json.loads(self.request("GET", "/v1/profiles", session=True)[2])["profiles"]
        self.assertIn("threat_modeler", {p["profile_id"] for p in profiles})
        # 14B catalog profile -> tool loop, persona used as the system prompt
        _, _, body = self.request("POST", "/v1/chat", self.chat("CHERCHE", profile_id="threat_modeler"),
                                  headers={"Accept": "text/event-stream"}, session=True, csrf=True)
        events = self.events(body)
        self.assertEqual([n for n, _ in events], ["metadata", "tool", "completed"])
        self.assertTrue(self.bootstrap.last_messages[0]["content"].startswith("PERSONA-14B"))
        # code catalog profile -> Qwen engine, persona kept
        body = json.loads(self.request("POST", "/v1/chat", self.chat("écris un test", profile_id="test_designer"),
                                       session=True, csrf=True)[2])
        self.assertEqual(body["engine"], "QWEN-CODER")
        self.assertEqual(self.qwen.last_messages[0]["content"], "PERSONA-CODE")

    def test_action_confirmation_flow(self) -> None:
        self.login()
        self.server.state.tools_enabled = True
        self.enable_actions()
        import services.web.code_sandbox as cs
        orig = (cs.available, cs.run_python)
        cs.available = lambda: True
        cs.run_python = lambda code: {"ok": True, "timed_out": False, "exit_code": 0, "output": "SANDBOX_OK"}
        self.addCleanup(lambda: (setattr(cs, "available", orig[0]), setattr(cs, "run_python", orig[1])))
        # 1) the model proposes run_python -> confirmation required, nothing executed
        _, _, body = self.request("POST", "/v1/chat", self.chat("EXECUTE ceci"), headers={"Accept": "text/event-stream"}, session=True, csrf=True)
        events = self.events(body)
        self.assertEqual([n for n, _ in events], ["metadata", "confirmation_required"])
        conf = events[-1][1]
        self.assertEqual(conf["tool"], "run_python")
        self.assertIn("print(1)", conf["code"])
        action_id = conf["action_id"]
        # 2) approve -> sandbox runs, loop resumes, final answer references the output
        _, _, body = self.request("POST", "/v1/chat/confirm",
                                  {"conversation_id": "conversation_001", "action_id": action_id, "decision": "approve"},
                                  headers={"Accept": "text/event-stream"}, session=True, csrf=True)
        ev = self.events(body)
        self.assertEqual([n for n, _ in ev], ["metadata", "tool", "completed"])
        self.assertIn("SANDBOX_OK", ev[-1][1]["answer"])
        # 3) the action id is single-use
        status, _, _ = self.request("POST", "/v1/chat/confirm",
                                    {"conversation_id": "conversation_001", "action_id": action_id, "decision": "approve"},
                                    session=True, csrf=True)
        self.assertEqual(status, 404)

    def test_action_reject_does_not_execute(self) -> None:
        self.login()
        self.server.state.tools_enabled = True
        self.enable_actions()
        import services.web.code_sandbox as cs
        orig = (cs.available, cs.run_python)
        calls = {"n": 0}
        def _run(code):
            calls["n"] += 1
            return {"ok": True, "timed_out": False, "exit_code": 0, "output": "X"}
        cs.available = lambda: True
        cs.run_python = _run
        self.addCleanup(lambda: (setattr(cs, "available", orig[0]), setattr(cs, "run_python", orig[1])))
        _, _, body = self.request("POST", "/v1/chat", self.chat("EXECUTE ceci"), headers={"Accept": "text/event-stream"}, session=True, csrf=True)
        action_id = self.events(body)[-1][1]["action_id"]
        _, _, body = self.request("POST", "/v1/chat/confirm",
                                  {"conversation_id": "conversation_001", "action_id": action_id, "decision": "reject"},
                                  headers={"Accept": "text/event-stream"}, session=True, csrf=True)
        self.assertEqual([n for n, _ in self.events(body)], ["metadata", "completed"])
        self.assertEqual(calls["n"], 0)  # sandbox never ran

    def test_write_file_action_flow(self) -> None:
        self.login()
        self.server.state.tools_enabled = True
        self.enable_actions()
        import tempfile
        from pathlib import Path as _Path
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.server.state.workspace_dir = _Path(directory.name)
        import services.web.code_sandbox as cs
        orig = cs.available
        cs.available = lambda: True  # so action tools are offered
        self.addCleanup(lambda: setattr(cs, "available", orig))
        # the model proposes a file write -> confirmation, nothing written yet
        _, _, body = self.request("POST", "/v1/chat", self.chat("ECRIS un fichier"), headers={"Accept": "text/event-stream"}, session=True, csrf=True)
        events = self.events(body)
        self.assertEqual([n for n, _ in events], ["metadata", "confirmation_required"])
        conf = events[-1][1]
        self.assertEqual((conf["tool"], conf["path"]), ("write_file", "note.md"))
        self.assertIn("CONTENU_TEST", conf["content"])
        self.assertFalse((_Path(directory.name) / "note.md").exists())
        # approve -> file written, a "file" event announces it
        _, _, body = self.request("POST", "/v1/chat/confirm",
                                  {"conversation_id": "conversation_001", "action_id": conf["action_id"], "decision": "approve"},
                                  headers={"Accept": "text/event-stream"}, session=True, csrf=True)
        names = [n for n, _ in self.events(body)]
        self.assertEqual(names, ["metadata", "tool", "file", "completed"])
        self.assertEqual((_Path(directory.name) / "note.md").read_text(encoding="utf-8"), "CONTENU_TEST")
        # and it can be downloaded
        status, headers, payload = self.request("GET", "/v1/workspace/note.md", session=True)
        self.assertEqual((status, payload.decode()), (200, "CONTENU_TEST"))
        self.assertIn("attachment", headers["content-disposition"])
        # traversal is refused
        self.assertEqual(self.request("GET", "/v1/workspace/../app.py", session=True)[0], 404)

    def test_health_snapshot(self) -> None:
        self.assertEqual(self.request("GET", "/v1/health")[0], 401)  # authenticated only
        self.login()
        status, _, body = self.request("GET", "/v1/health", session=True)
        payload = json.loads(body)
        self.assertEqual(status, 200)
        engines = {row["engine"]: row for row in payload["engines"]}
        self.assertTrue(engines["CHAT-14B"]["available"])
        self.assertFalse(engines["CORE-700M"]["available"])
        for section in ("knowledge", "arena", "corpus", "workspace", "actions", "resources"):
            self.assertIn(section, payload)
        self.assertEqual(self.request("GET", "/sante")[0], 200)  # the page itself is public, its data is not

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


class ActionSwitchGatewayTests(GatewayTestCase):
    """D-035: with SOVEREIGN_ACTIONS_ENABLED off, no path proposes, confirms or runs an action."""

    READ_ONLY_TOOLS = {"search_knowledge", "list_documents", "read_document", "current_time", "list_workspace"}
    ACTIONS = {"run_python", "write_file"}

    def setUp(self) -> None:
        import tempfile
        from pathlib import Path
        import services.web.code_sandbox as sandbox

        self.start(FakeQwen())
        self.login()
        self.server.state.tools_enabled = True
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.workspace = Path(directory.name)
        self.server.state.workspace_dir = self.workspace
        # A sandbox that "works" and counts every execution: any run is a failure.
        self.executions: list[str] = []
        original = (sandbox.available, sandbox.run_python)
        sandbox.available = lambda: True
        sandbox.run_python = lambda code: self.executions.append(code) or {"ok": True, "timed_out": False, "exit_code": 0, "output": "RAN"}
        self.addCleanup(lambda: (setattr(sandbox, "available", original[0]), setattr(sandbox, "run_python", original[1])))

    def stream(self, message: str) -> list[tuple[str, dict[str, Any]]]:
        status, _, body = self.request("POST", "/v1/chat", self.chat(message), headers={"Accept": "text/event-stream"}, session=True, csrf=True)
        self.assertEqual(status, 200)
        return self.events(body)

    def confirm(self, action_id: str, decision: str = "approve", **options: Any) -> tuple[int, bytes]:
        body = {"conversation_id": "conversation_001", "action_id": action_id, "decision": decision}
        status, _, payload = self.request("POST", "/v1/chat/confirm", body, headers={"Accept": "text/event-stream"}, **{"session": True, "csrf": True, **options})
        return status, payload

    def refusals(self) -> list[dict[str, str]]:
        return [fields for event, fields in self.server.security_events if event == "action_refused"]

    def forged_pending_action(self, action_id: str, tool: str = "run_python") -> None:
        arguments = '{"code": "print(1)"}' if tool == "run_python" else '{"path": "forged.md", "content": "X"}'
        self.server.state.pending_actions[action_id] = {
            "conversation_id": "conversation_001", "profile_id": "coordination", "request_id": "req-12345678",
            "work": [{"role": "user", "content": "EXECUTE"}], "citations": [],
            "call": {"id": "a1", "name": tool, "arguments": arguments}, "created_at": __import__("time").time(),
        }

    def handler(self) -> gateway.LocalWebHandler:
        import io
        handler = QuietHandler.__new__(QuietHandler)
        handler.server = self.server
        handler.wfile = io.BytesIO()
        return handler

    def test_actions_are_disabled_by_default(self) -> None:
        self.assertFalse(self.server.state.actions_enabled)

    def test_disabled_offers_only_read_only_tools_and_prompt_does_not_advertise_actions(self) -> None:
        events = self.stream("Salut")
        self.assertEqual([name for name, _ in events], ["metadata", "completed"])
        self.assertEqual(self.bootstrap.offered_tools[0], self.READ_ONLY_TOOLS)
        system = self.bootstrap.last_messages[0]["content"]
        self.assertEqual(system, gateway.TOOLS_SYSTEM_PROMPT_WITHOUT_ACTIONS)
        self.assertNotIn("run_python", system)
        self.assertNotIn("write_file", system)

    def test_disabled_read_only_tools_are_unaffected(self) -> None:
        events = self.stream("CHERCHE le statut")
        self.assertEqual([name for name, _ in events], ["metadata", "tool", "completed"])
        self.assertEqual(events[1][1], {"name": "search_knowledge"})
        self.assertEqual(events[-1][1]["citations"][0]["provenance_id"], "project-sha256:abc")
        self.assertEqual(self.refusals(), [])

    def test_disabled_model_action_call_is_refused_never_proposed_nor_run(self) -> None:
        for message, tool in (("EXECUTE ceci", "run_python"), ("ECRIS un fichier", "write_file")):
            events = self.stream(message)
            self.assertEqual([name for name, _ in events], ["metadata", "completed"], message)
            self.assertIn("Action refusée", events[-1][1]["answer"])
            self.assertEqual(self.refusals()[-1], {"reason": "actions_disabled", "stage": "model", "tool": tool})
        self.assertEqual(self.server.state.pending_actions, {})
        self.assertEqual(self.executions, [])
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_disabled_confirm_refuses_pending_and_forged_ids(self) -> None:
        self.forged_pending_action("0123456789abcdef")
        self.forged_pending_action("fedcba9876543210", tool="write_file")
        for action_id, decision in (("0123456789abcdef", "approve"), ("fedcba9876543210", "approve"),
                                    ("ffffffffffffffff", "approve"), ("0123456789abcdef", "reject")):
            status, payload = self.confirm(action_id, decision)
            self.assertEqual((status, json.loads(payload)), (403, {"error": "actions_disabled"}), (action_id, decision))
        # malformed ids get the same generic refusal: nothing about the action is processed
        status, _, payload = self.request("POST", "/v1/chat/confirm", {"action_id": "../../x"}, session=True, csrf=True)
        self.assertEqual((status, json.loads(payload)), (403, {"error": "actions_disabled"}))
        self.assertEqual(self.server.state.pending_actions, {})  # a pending action created before is dropped
        self.assertEqual(self.executions, [])
        self.assertEqual(list(self.workspace.iterdir()), [])
        self.assertEqual(self.refusals()[0], {"reason": "actions_disabled", "stage": "confirm", "tool": "other"})
        self.assertEqual(len(self.refusals()), 5)

    def test_disabled_confirm_still_requires_a_session_and_csrf(self) -> None:
        self.assertEqual(self.confirm("0123456789abcdef", session=False)[0], 401)
        self.assertEqual(self.confirm("0123456789abcdef", csrf=False)[0], 401)
        self.assertEqual(self.refusals(), [])

    def test_disabled_executor_and_proposal_paths_refuse_even_if_reached(self) -> None:
        handler = self.handler()
        for call in ({"id": "a1", "name": "run_python", "arguments": '{"code": "print(1)"}'},
                     {"id": "w1", "name": "write_file", "arguments": '{"path": "x.md", "content": "X"}'}):
            self.assertEqual(handler._run_action(call), gateway.agent_tools.ACTION_REFUSED_RESULT)
        self.assertEqual(self.executions, [])
        self.assertEqual(list(self.workspace.iterdir()), [])
        # a forged "confirm" loop result never becomes a pending action
        forged = {"status": "confirm", "call": {"id": "a1", "name": "run_python", "arguments": "{}"}, "work": [], "citations": []}
        handler._finish_tool_result("req-12345678", "coordination", "conversation_001", forged)
        self.assertEqual(self.server.state.pending_actions, {})
        self.assertEqual([name for name, _ in self.events(handler.wfile.getvalue())], ["error"])
        self.assertEqual(self.events(handler.wfile.getvalue())[0][1]["error"], "action_refused")
        self.assertEqual([fields["stage"] for fields in self.refusals()], ["execute", "execute", "propose"])

    def test_session_and_health_expose_a_content_free_actions_flag(self) -> None:
        import services.web.code_sandbox as sandbox
        probes: list[int] = []
        sandbox.available = lambda: probes.append(1) or True  # restored by setUp's cleanup
        session = json.loads(self.request("GET", "/v1/session", session=True)[2])
        self.assertIs(session["actions_enabled"], False)
        actions = json.loads(self.request("GET", "/v1/health", session=True)[2])["actions"]
        self.assertEqual(actions, {"sandbox": False, "tools_enabled": True, "actions_enabled": False})
        self.assertEqual(probes, [])  # disabled: the sandbox self-test is not even run
        self.enable_actions()
        self.assertIs(json.loads(self.request("GET", "/v1/session", session=True)[2])["actions_enabled"], True)
        actions = json.loads(self.request("GET", "/v1/health", session=True)[2])["actions"]
        self.assertEqual(actions, {"sandbox": True, "tools_enabled": True, "actions_enabled": True})
        self.assertEqual(self.request("GET", "/v1/session")[0], 401)  # the flag is behind the session

    def test_the_interface_reads_the_flag_and_never_offers_approval_when_disabled(self) -> None:
        index = self.request("GET", "/")[2].decode()
        script = self.request("GET", "/app.js")[2].decode()
        self.assertIn('id="actions-status"', index)
        self.assertIn("session.actions_enabled === true", script)
        self.assertIn("if (!state.actionsEnabled)", script)

    def test_enabled_path_offers_actions_with_the_unchanged_prompt(self) -> None:
        self.enable_actions()
        events = self.stream("EXECUTE ceci")
        self.assertEqual([name for name, _ in events], ["metadata", "confirmation_required"])
        self.assertEqual(self.bootstrap.offered_tools[0], self.READ_ONLY_TOOLS | self.ACTIONS)
        self.assertEqual(self.bootstrap.last_messages[0]["content"], gateway.TOOLS_SYSTEM_PROMPT)
        self.assertIn("run_python", gateway.TOOLS_SYSTEM_PROMPT)
        status, payload = self.confirm(events[-1][1]["action_id"])
        self.assertEqual(status, 200)
        self.assertEqual([name for name, _ in self.events(payload)], ["metadata", "tool", "completed"])
        self.assertEqual(self.executions, ["print(1)"])
        self.assertEqual(self.refusals(), [])

    def test_enabled_host_failures_never_echo_a_server_path(self) -> None:
        import services.web.code_sandbox as sandbox
        import services.web.workspace as workspace_module

        self.enable_actions()
        handler = self.handler()
        server_path = "/srv/example-gateway/workspace/note.md"  # placeholder, not a real host path

        def failing_write(root: Any, relative: str, content: str) -> dict[str, Any]:
            raise OSError(13, "Permission denied", server_path)

        def failing_run(code: str) -> dict[str, Any]:
            raise FileNotFoundError(2, "No such file or directory", server_path)

        original_write = workspace_module.write_file
        workspace_module.write_file = failing_write
        self.addCleanup(setattr, workspace_module, "write_file", original_write)
        sandbox.run_python = failing_run  # restored by setUp's cleanup
        written = handler._run_action({"id": "w1", "name": "write_file", "arguments": '{"path": "note.md", "content": "X"}'})
        ran = handler._run_action({"id": "a1", "name": "run_python", "arguments": '{"code": "print(1)"}'})
        self.assertEqual(written, gateway.ACTION_WRITE_FAILED_RESULT)
        self.assertEqual(ran, gateway.ACTION_EXECUTION_FAILED_RESULT)
        for result in (written, ran):
            self.assertNotIn(server_path, result)
            self.assertNotIn("example-gateway", result)
        self.assertEqual(handler.wfile.getvalue(), b"")  # no "file" event for a failed write
        failures = [fields for event, fields in self.server.security_events if event == "action_failed"]
        self.assertEqual(failures, [{"stage": "execute", "tool": "write_file", "error": "PermissionError"},
                                    {"stage": "execute", "tool": "run_python", "error": "FileNotFoundError"}])
        for fields in failures:
            self.assertNotIn(server_path, " ".join(fields.values()))

    def test_enabled_workspace_refusals_keep_their_path_free_message(self) -> None:
        self.enable_actions()
        handler = self.handler()
        for relative in ("../evade.md", "a/b/c.md", "/abs.md"):
            arguments = json.dumps({"path": relative, "content": "X"})
            result = handler._run_action({"id": "w1", "name": "write_file", "arguments": arguments})
            self.assertTrue(result.startswith("Écriture impossible : "), relative)
            self.assertNotIn(str(self.workspace), result, relative)
            self.assertNotIn(str(self.workspace.resolve()), result, relative)
        self.assertEqual(list(self.workspace.iterdir()), [])


class ArenaGatewayTests(GatewayTestCase):
    """The gateway reads the arena database read-only and writes approvals to its inbox."""

    def setUp(self) -> None:
        import os
        import tempfile
        from pathlib import Path
        from services.arena.store import ArenaStore

        self.os = os
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        writer = ArenaStore(self.root / "arena.sqlite3")
        writer.initialize()
        writer.add_profile({"profile_id": "author-direct", "display_name": "Direct", "role": "author", "engine": "QWEN-CODER",
                            "system_prompt": "Write the function.", "temperature": 0.2})
        writer.add_event("arena_started", {"engines": ["QWEN-CODER"], "tasks": 50})
        writer.add_event("match_started", {"match_id": 1, "task_id": "python-01-x", "prompt": "<script>alert(1)</script>",
                                           "authors": ["author-direct", "author-direct"], "critic_id": None})
        self.inbox = self.root / "inbox"
        self.inbox.mkdir()
        self.start(FakeQwen())
        self.server.state.arena = ArenaStore(self.root / "arena.sqlite3", read_only=True)
        self.server.state.arena_inbox = self.inbox
        self.login()

    def test_arena_page_and_overview(self) -> None:
        status, headers, _ = self.request("GET", "/arena")
        self.assertEqual((status, headers["content-type"]), (200, "text/html; charset=utf-8"))
        self.assertEqual(self.request("GET", "/arena.js")[0], 200)
        self.assertEqual(self.request("GET", "/v1/arena")[0], 401)
        body = json.loads(self.request("GET", "/v1/arena", session=True)[2])
        self.assertTrue(body["available"])
        self.assertEqual(body["profiles"][0]["profile_id"], "author-direct")
        self.assertEqual(body["last_event_id"], 2)

    def test_events_are_paged_and_returned_as_data(self) -> None:
        events = json.loads(self.request("GET", "/v1/arena/events?after=1", session=True)[2])["events"]
        self.assertEqual([e["kind"] for e in events], ["match_started"])
        self.assertEqual(events[0]["payload"]["prompt"], "<script>alert(1)</script>")
        for bad in ("/v1/arena/events?after=-1", "/v1/arena/events?after=x", "/v1/arena/events?after=9999999999999"):
            self.assertEqual(self.request("GET", bad, session=True)[0], 422, bad)

    def test_approval_requires_csrf_and_a_valid_target(self) -> None:
        packet = {"kind": "packet", "target_id": "arena-20260911t120000z", "target_sha256": "a" * 64}
        self.assertEqual(self.request("POST", "/v1/arena/approve", packet, session=True)[0], 401)
        for bad in ({**packet, "kind": "train_now"}, {**packet, "target_sha256": "short"}, {**packet, "extra": 1},
                    {"kind": "profile_chat", "target_id": "../../etc/passwd"}, {"kind": "profile_chat", "target_id": "author-x", "target_sha256": "a" * 64}):
            self.assertEqual(self.request("POST", "/v1/arena/approve", bad, session=True, csrf=True)[0], 422, bad)
        self.assertEqual(list(self.inbox.iterdir()), [])
        status, _, body = self.request("POST", "/v1/arena/approve", packet, session=True, csrf=True)
        self.assertEqual((status, json.loads(body)["status"]), (202, "approval_recorded"))
        files = list(self.inbox.iterdir())
        self.assertEqual(len(files), 1)
        self.assertEqual(self.os.stat(files[0]).st_mode & 0o777, 0o640)
        recorded = json.loads(files[0].read_text())
        self.assertEqual((recorded["schema_version"], recorded["approved_by"], recorded["target_sha256"]), ("arena-approval.v1", "owner", "a" * 64))
        status, _, _ = self.request("POST", "/v1/arena/approve", {"kind": "profile_chat", "target_id": "author-direct"}, session=True, csrf=True)
        self.assertEqual(status, 202)

    def test_missing_arena_is_reported_not_crashed(self) -> None:
        self.server.state.arena_inbox = self.root / "absent"
        body = {"kind": "profile_chat", "target_id": "author-direct"}
        self.assertEqual(json.loads(self.request("POST", "/v1/arena/approve", body, session=True, csrf=True)[2]), {"error": "arena_unavailable"})
        from pathlib import Path
        from services.arena.store import ArenaStore
        self.server.state.arena = ArenaStore(Path(self.root / "absent.sqlite3"), read_only=True)
        self.assertEqual(json.loads(self.request("GET", "/v1/arena", session=True)[2]), {"available": False})
        self.server.state.arena = None
        self.assertEqual(json.loads(self.request("GET", "/v1/arena/events?after=0", session=True)[2]), {"available": False, "events": []})


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
