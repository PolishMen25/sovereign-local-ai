import importlib.util
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest import mock
from uuid import uuid4


MODULE_PATH = Path(__file__).parents[1] / "tools" / "codex_conversation_sync.py"
SPEC = importlib.util.spec_from_file_location("codex_conversation_sync", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CodexConversationSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = Path(__file__).parent / f"runtime-codex-sync-{uuid4()}"
        self.temp_root.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_secret_lines_and_mixed_tokens_are_removed(self) -> None:
        source = "mot de passe : VerySecret123@@\ntexte utile\nBearer abcdefghijklmnopqrstuvwxyz"
        sanitized = MODULE.sanitize_text(source)
        self.assertNotIn("VerySecret", sanitized)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", sanitized)
        self.assertIn("texte utile", sanitized)

    def test_collector_endpoint_is_required_and_strictly_validated(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "missing"):
                MODULE.configured_collector_url()

        valid = {
            MODULE.COLLECTOR_URL_ENV: "https://collector.example.test/v1/conversations",
            MODULE.COLLECTOR_ALLOWED_HOST_ENV: "collector.example.test",
        }
        with mock.patch.dict(os.environ, valid, clear=True):
            self.assertEqual(
                valid[MODULE.COLLECTOR_URL_ENV], MODULE.configured_collector_url()
            )

        invalid_urls = (
            "http://collector.example.test/v1/conversations",
            "https://user@collector.example.test/v1/conversations",
            "https://collector.example.test:8443/v1/conversations",
            "https://collector.example.test/v1/conversations?token=no",
            "https://other.example.test/v1/conversations",
            "https://collector.example.test/v1/internal",
        )
        for candidate in invalid_urls:
            with self.subTest(candidate=candidate):
                invalid = dict(valid)
                invalid[MODULE.COLLECTOR_URL_ENV] = candidate
                with mock.patch.dict(os.environ, invalid, clear=True):
                    with self.assertRaises(ValueError):
                        MODULE.configured_collector_url()

    def test_inline_secret_labels_are_removed(self) -> None:
        sanitized = MODULE.sanitize_text("config = {'password': 'VerySecret123@@'}")
        self.assertNotIn("VerySecret", sanitized)

    def test_french_mdp_and_long_alphanumeric_tokens_are_removed(self) -> None:
        source = "mdp : SyntheticAccessCode2026\nSyntheticSessionToken42\ntexte utile"
        sanitized = MODULE.sanitize_text(source)
        self.assertNotIn("SyntheticAccessCode", sanitized)
        self.assertNotIn("SyntheticSessionToken", sanitized)
        self.assertIn("texte utile", sanitized)

    def test_ordinary_lowercase_identifiers_are_preserved(self) -> None:
        source = "documentationlocale2026 et texte utile"
        self.assertEqual(MODULE.sanitize_text(source), source)

    def test_extracts_only_visible_user_and_assistant_messages(self) -> None:
        transcript = self.temp_root / "rollout.jsonl"
        rows = [
            {"type": "session_meta", "payload": {"session_id": "session-1", "timestamp": "2026-08-31T12:00:00Z"}},
            {"type": "response_item", "payload": {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "hidden"}]}},
            {"type": "response_item", "payload": {"type": "reasoning", "summary": ["hidden"]}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "bonjour"}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "salut"}]}},
        ]
        transcript.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
        session_id, captured_at, messages = MODULE.read_transcript(transcript)
        self.assertEqual("session-1", session_id)
        self.assertEqual("2026-08-31T12:00:00Z", captured_at)
        self.assertEqual([{"role": "user", "content": "bonjour"}, {"role": "assistant", "content": "salut"}], messages)

    def test_document_ids_are_deterministic(self) -> None:
        messages = [{"role": "user", "content": "bonjour"}]
        first = MODULE.build_documents("stable-session", "2026-08-31T12:00:00Z", messages)
        second = MODULE.build_documents("stable-session", "2026-08-31T12:00:00Z", messages)
        self.assertEqual(first, second)

    def test_queue_is_idempotent_after_receipt(self) -> None:
        transcript = self.temp_root / "rollout.jsonl"
        transcript.write_text(
            json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "bonjour"}]}}),
            encoding="utf-8",
        )
        previous = os.environ.get("SOVEREIGN_SYNC_HOME")
        os.environ["SOVEREIGN_SYNC_HOME"] = str(self.temp_root / "sync")
        try:
            self.assertEqual(1, MODULE.queue_transcript(transcript, "stable-session"))
            queued = next((self.temp_root / "sync" / "queue").glob("*.json"))
            receipt = self.temp_root / "sync" / "receipts" / queued.name
            receipt.parent.mkdir(parents=True)
            receipt.write_text("{}", encoding="utf-8")
            queued.unlink()
            self.assertEqual(0, MODULE.queue_transcript(transcript, "stable-session"))
        finally:
            if previous is None:
                os.environ.pop("SOVEREIGN_SYNC_HOME", None)
            else:
                os.environ["SOVEREIGN_SYNC_HOME"] = previous


if __name__ == "__main__":
    unittest.main()
