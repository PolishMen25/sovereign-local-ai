import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from services.common.private_endpoints import PRIVATE_ENDPOINTS_ENV
from services.inference.runtime import LocalInferenceRuntime
from services.web.app import WEB_PROFILES, WebState, authorize, parse_chat, pinned_engine, response
from services.web.core_client import CoreClient
from services.web.qwen_client import QwenClient
from tests._private_endpoint_support import CORE_ENDPOINT, QWEN_ENDPOINT, write_private_endpoints


class BootstrapStatus:
    def __init__(self, available: bool) -> None:
        self.available = available

    def status(self) -> dict[str, bool | str]:
        return {"available": self.available, "state": "ready" if self.available else "unavailable"}


class WebAppTests(unittest.TestCase):
    def test_authorization_is_constant_time_and_requires_long_token(self) -> None:
        token = "x" * 32
        self.assertTrue(authorize(f"Bearer {token}", token))
        self.assertFalse(authorize("Bearer wrong", token))
        self.assertFalse(authorize(f"Bearer {'x' * 8}", "x" * 8))

    def test_chat_parser_rejects_wrong_schema(self) -> None:
        with self.assertRaises(ValueError):
            parse_chat(b'{"schema_version":"wrong"}')

    def test_chat_parser_allows_only_known_engines(self) -> None:
        request = {
            "schema_version": "local-chat-request.v1",
            "request_id": "req-123456",
            "message": "bonjour",
            "engine": "CORE-700M",
        }
        self.assertEqual("CORE-700M", parse_chat(json.dumps(request).encode())["engine"])
        request["engine"] = "remote"
        with self.assertRaises(ValueError):
            parse_chat(json.dumps(request).encode())

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

    def test_response_keeps_bounded_retrieval_citations(self) -> None:
        citations = [{"document_id": "project:status.md", "title": "Statut", "provenance_id": "project-sha256:abc"}]
        payload = response("req-123456", "coordination", "completed", "ok", citations=citations)
        self.assertEqual(citations, payload["citations"])

    def test_web_exposes_only_the_safe_coordination_profile(self) -> None:
        self.assertEqual(["coordination"], [profile["profile_id"] for profile in WEB_PROFILES])
        self.assertIn("désactivés", WEB_PROFILES[0]["description"])

    def test_response_reports_retrieval_mode(self) -> None:
        self.assertEqual("lexical", response("req-123456", "coordination", "completed", "ok")["rag_mode"])

    def test_core_engine_is_advertised_but_not_available_without_runtime(self) -> None:
        state = WebState(None, None, BootstrapStatus(True), LocalInferenceRuntime("CORE-700M", Path("missing.pt")), None, "x" * 32)
        engines = state.engines()
        self.assertTrue(engines[0]["available"])
        self.assertEqual("CORE-700M", engines[1]["engine"])
        self.assertFalse(engines[1]["available"])

    def test_bootstrap_is_not_advertised_when_its_health_check_fails(self) -> None:
        state = WebState(None, None, BootstrapStatus(False), LocalInferenceRuntime("CORE-700M", Path("missing.pt")), None, "x" * 32)
        self.assertFalse(state.engines()[0]["available"])



class PinnedEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.environ = write_private_endpoints(self._directory.name, CORE_ENDPOINT, QWEN_ENDPOINT)

    def isolated(self, **values: str):
        cleared = {key: "" for key in (PRIVATE_ENDPOINTS_ENV, "SOVEREIGN_CORE_ENDPOINT", "SOVEREIGN_QWEN_ENDPOINT")}
        patcher = patch.dict(os.environ, cleared)
        patcher.start()
        self.addCleanup(patcher.stop)
        for key in cleared:
            del os.environ[key]
        os.environ.update(values)

    def test_engines_are_pinned_to_the_private_configuration(self) -> None:
        self.isolated(**self.environ)
        self.assertEqual(pinned_engine(CoreClient, "core_inference", "SOVEREIGN_CORE_ENDPOINT", "x" * 32).endpoint, CORE_ENDPOINT.url)
        self.assertEqual(pinned_engine(QwenClient, "qwen_coder", "SOVEREIGN_QWEN_ENDPOINT", "x" * 32).endpoint, QWEN_ENDPOINT.url)

    def test_a_matching_legacy_override_is_accepted(self) -> None:
        self.isolated(**self.environ, SOVEREIGN_QWEN_ENDPOINT=QWEN_ENDPOINT.url)
        self.assertEqual(pinned_engine(QwenClient, "qwen_coder", "SOVEREIGN_QWEN_ENDPOINT", "x" * 32).endpoint, QWEN_ENDPOINT.url)

    def test_gateway_refuses_to_start_on_mismatch_or_missing_configuration(self) -> None:
        cases = (
            ({**self.environ, "SOVEREIGN_CORE_ENDPOINT": QWEN_ENDPOINT.url}, CoreClient, "core_inference", "SOVEREIGN_CORE_ENDPOINT"),
            ({**self.environ, "SOVEREIGN_QWEN_ENDPOINT": QWEN_ENDPOINT.url + "/"}, QwenClient, "qwen_coder", "SOVEREIGN_QWEN_ENDPOINT"),
            ({}, CoreClient, "core_inference", "SOVEREIGN_CORE_ENDPOINT"),
        )
        for environ, client, name, variable in cases:
            with self.subTest(name=name, variables=sorted(environ)):
                self.isolated(**environ)
                with self.assertRaises(SystemExit) as caught:
                    pinned_engine(client, name, variable, "x" * 32)
                message = str(caught.exception.code)
                self.assertIn("refusing to start", message)
                for marker in (CORE_ENDPOINT.host, QWEN_ENDPOINT.host, self._directory.name):
                    self.assertNotIn(marker, message)


if __name__ == "__main__":
    unittest.main()
