import importlib.util
import hashlib
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

    def _write_local_endpoint_config(self, content: object) -> Path:
        sync_home = self.temp_root / "sync"
        sync_home.mkdir(exist_ok=True)
        config_path = sync_home / MODULE.LOCAL_COLLECTOR_CONFIG_NAME
        config_path.write_text(json.dumps(content), encoding="utf-8")
        return config_path

    def _prepare_queued_conversation(
        self,
    ) -> tuple[Path, Path, bytes, dict[str, object]]:
        sync_home = self.temp_root / "sync"
        self._write_local_endpoint_config(
            {
                "collector_url": "https://collector.example.test/v1/conversations",
                "allowed_host": "collector.example.test",
            }
        )
        (sync_home / "collector.token").write_text("x" * 32, encoding="utf-8")
        conversation_id = str(uuid4())
        document: dict[str, object] = {
            "schema_version": MODULE.SCHEMA_VERSION,
            "conversation_id": conversation_id,
            "captured_at": "2026-08-31T12:00:00Z",
            "messages": [{"role": "user", "content": "contenu synthétique"}],
        }
        payload = json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        queue_path = sync_home / "queue" / f"{conversation_id}.json"
        queue_path.parent.mkdir()
        queue_path.write_bytes(payload)
        return sync_home, queue_path, payload, document

    def _response(self, body: bytes, content_type: str = "application/json") -> object:
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 202
        response.headers = {"Content-Type": content_type}
        response.read.return_value = body
        return response

    def test_secret_lines_and_mixed_tokens_are_removed(self) -> None:
        source = "mot de passe : VerySecret123@@\ntexte utile\nBearer abcdefghijklmnopqrstuvwxyz"
        sanitized = MODULE.sanitize_text(source)
        self.assertNotIn("VerySecret", sanitized)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", sanitized)
        self.assertIn("texte utile", sanitized)

    def test_collector_endpoint_is_required_and_strictly_validated(self) -> None:
        with mock.patch.object(MODULE, "sync_home", return_value=self.temp_root / "sync"):
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

    def test_local_endpoint_config_is_used_when_environment_is_absent(self) -> None:
        expected_url = "https://collector.example.test/v1/conversations"
        self._write_local_endpoint_config(
            {"collector_url": expected_url, "allowed_host": "collector.example.test"}
        )
        with mock.patch.object(MODULE, "sync_home", return_value=self.temp_root / "sync"):
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(expected_url, MODULE.configured_collector_url())

    def test_environment_has_priority_and_partial_pair_fails_closed(self) -> None:
        self._write_local_endpoint_config({"unexpected": "local file must not be read"})
        valid_environment = {
            MODULE.COLLECTOR_URL_ENV: "https://env.example.test/v1/conversations",
            MODULE.COLLECTOR_ALLOWED_HOST_ENV: "env.example.test",
        }
        with mock.patch.object(MODULE, "sync_home", return_value=self.temp_root / "sync"):
            with mock.patch.dict(os.environ, valid_environment, clear=True):
                self.assertEqual(
                    valid_environment[MODULE.COLLECTOR_URL_ENV],
                    MODULE.configured_collector_url(),
                )

        self._write_local_endpoint_config(
            {
                "collector_url": "https://local.example.test/v1/conversations",
                "allowed_host": "local.example.test",
            }
        )
        partial_environment = {
            MODULE.COLLECTOR_URL_ENV: "https://env.example.test/v1/conversations"
        }
        with mock.patch.object(MODULE, "sync_home", return_value=self.temp_root / "sync"):
            with mock.patch.dict(os.environ, partial_environment, clear=True):
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    MODULE.configured_collector_url()

    def test_local_endpoint_config_rejects_extra_duplicate_and_invalid_fields(self) -> None:
        invalid_documents = (
            {
                "collector_url": "https://collector.example.test/v1/conversations",
                "allowed_host": "collector.example.test",
                "extra": True,
            },
            {
                "collector_url": "http://collector.example.test/v1/conversations",
                "allowed_host": "collector.example.test",
            },
            {"collector_url": 7, "allowed_host": "collector.example.test"},
        )
        with mock.patch.object(MODULE, "sync_home", return_value=self.temp_root / "sync"):
            for document in invalid_documents:
                with self.subTest(document=document):
                    self._write_local_endpoint_config(document)
                    with mock.patch.dict(os.environ, {}, clear=True):
                        with self.assertRaises(ValueError):
                            MODULE.configured_collector_url()

            duplicate = self.temp_root / "sync" / MODULE.LOCAL_COLLECTOR_CONFIG_NAME
            duplicate.write_text(
                '{"collector_url":"https://collector.example.test/v1/conversations",'
                '"collector_url":"https://collector.example.test/v1/conversations",'
                '"allowed_host":"collector.example.test"}',
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(ValueError, "duplicate"):
                    MODULE.configured_collector_url()

    def test_local_endpoint_config_must_be_small_regular_file(self) -> None:
        config_path = self._write_local_endpoint_config({})
        config_path.write_bytes(b"x" * (MODULE.MAX_LOCAL_COLLECTOR_CONFIG_BYTES + 1))
        with mock.patch.object(MODULE, "sync_home", return_value=self.temp_root / "sync"):
            with mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(ValueError, "size limit"):
                    MODULE.configured_collector_url()

        config_path.unlink()
        config_path.mkdir()
        with mock.patch.object(MODULE, "sync_home", return_value=self.temp_root / "sync"):
            with mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(ValueError, "regular file"):
                    MODULE.configured_collector_url()

    def test_flush_fails_closed_before_network_when_configuration_is_invalid(self) -> None:
        self._write_local_endpoint_config({"unexpected": "value"})
        with mock.patch.object(MODULE, "sync_home", return_value=self.temp_root / "sync"):
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(MODULE.request, "build_opener") as build_opener:
                    self.assertEqual(2, MODULE.flush_queue())
        build_opener.assert_not_called()

    def test_inline_secret_labels_are_removed(self) -> None:
        sanitized = MODULE.sanitize_text("config = {'password': 'VerySecret123@@'}")
        self.assertNotIn("VerySecret", sanitized)

    def test_url_queries_are_removed_for_http_and_case_insensitive_https(self) -> None:
        source = (
            "http://example.test/callback?token=lowercasecredential\n"
            "HTTPS://example.test/callback?token=anotherlowercasecredential"
        )
        sanitized = MODULE.sanitize_text(source)
        self.assertEqual(
            "[URL QUERY REMOVED]\n[URL QUERY REMOVED]",
            sanitized,
        )

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

    def test_queue_is_idempotent_only_after_valid_receipt(self) -> None:
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
            payload = queued.read_bytes()
            receipt.write_text(
                json.dumps(
                    {
                        "received_at": "2026-08-31T12:00:00Z",
                        "state": "raw_imported",
                        "conversation_id": queued.stem,
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            queued.unlink()
            self.assertEqual(0, MODULE.queue_transcript(transcript, "stable-session"))
        finally:
            if previous is None:
                os.environ.pop("SOVEREIGN_SYNC_HOME", None)
            else:
                os.environ["SOVEREIGN_SYNC_HOME"] = previous

    def test_corrupt_local_receipt_regenerates_queue(self) -> None:
        transcript = self.temp_root / "rollout-corrupt-receipt.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "bonjour"}],
                    },
                }
            ),
            encoding="utf-8",
        )
        sync_home = self.temp_root / "sync"
        with mock.patch.object(MODULE, "sync_home", return_value=sync_home):
            self.assertEqual(1, MODULE.queue_transcript(transcript, "stable-session"))
            queued = next((sync_home / "queue").glob("*.json"))
            receipt = sync_home / "receipts" / queued.name
            receipt.parent.mkdir(parents=True)
            receipt.write_text("{}", encoding="utf-8")
            queued.unlink()

            self.assertEqual(1, MODULE.queue_transcript(transcript, "stable-session"))

        self.assertTrue((sync_home / "queue" / queued.name).is_file())

    def test_non_object_collector_receipt_keeps_queue_for_retry(self) -> None:
        sync_home, queue_path, _, _ = self._prepare_queued_conversation()
        response = self._response(b"[]")
        opener = mock.MagicMock()
        opener.open.return_value = response

        with mock.patch.object(MODULE, "sync_home", return_value=sync_home):
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(
                    MODULE.request,
                    "build_opener",
                    return_value=opener,
                ):
                    self.assertEqual(1, MODULE.flush_queue())

        self.assertTrue(queue_path.is_file())
        self.assertFalse((sync_home / "receipts" / queue_path.name).exists())

    def test_invalid_remote_receipts_keep_queue_for_retry(self) -> None:
        sync_home, queue_path, payload, document = self._prepare_queued_conversation()
        conversation_id = document["conversation_id"]
        digest = hashlib.sha256(payload).hexdigest()
        invalid_receipts = {
            "empty_object": b"{}",
            "bad_state": json.dumps(
                {
                    "state": "accepted",
                    "conversation_id": conversation_id,
                    "sha256": digest,
                }
            ).encode("utf-8"),
            "bad_id": json.dumps(
                {
                    "state": "raw_imported",
                    "conversation_id": str(uuid4()),
                    "sha256": digest,
                }
            ).encode("utf-8"),
            "bad_hash": json.dumps(
                {
                    "state": "raw_imported",
                    "conversation_id": conversation_id,
                    "sha256": "0" * 64,
                }
            ).encode("utf-8"),
            "duplicate": (
                '{"state":"raw_imported","state":"already_imported",'
                f'"conversation_id":"{conversation_id}","sha256":"{digest}"}}'
            ).encode("utf-8"),
            "non_finite": (
                '{"state":"raw_imported",'
                f'"conversation_id":"{conversation_id}","sha256":NaN}}'
            ).encode("utf-8"),
        }

        with mock.patch.object(MODULE, "sync_home", return_value=sync_home):
            with mock.patch.dict(os.environ, {}, clear=True):
                for label, body in invalid_receipts.items():
                    with self.subTest(label=label):
                        opener = mock.MagicMock()
                        opener.open.return_value = self._response(body)
                        with mock.patch.object(
                            MODULE.request,
                            "build_opener",
                            return_value=opener,
                        ):
                            self.assertEqual(1, MODULE.flush_queue())
                        self.assertTrue(queue_path.is_file())
                        self.assertFalse(
                            (sync_home / "receipts" / queue_path.name).exists()
                        )

    def test_valid_remote_receipt_is_persisted_before_queue_removal(self) -> None:
        sync_home, queue_path, payload, document = self._prepare_queued_conversation()
        remote_receipt = {
            "state": "raw_imported",
            "conversation_id": document["conversation_id"],
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        opener = mock.MagicMock()
        opener.open.return_value = self._response(
            json.dumps(
                remote_receipt,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )

        with mock.patch.object(MODULE, "sync_home", return_value=sync_home):
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(
                    MODULE.request,
                    "build_opener",
                    return_value=opener,
                ):
                    self.assertEqual(0, MODULE.flush_queue())

        self.assertFalse(queue_path.exists())
        local_receipt_path = sync_home / "receipts" / queue_path.name
        local_receipt = json.loads(local_receipt_path.read_bytes())
        self.assertEqual(
            {"received_at", "state", "conversation_id", "sha256"},
            set(local_receipt),
        )
        self.assertTrue(
            MODULE._local_receipt_matches(
                local_receipt_path,
                payload=payload,
                conversation_id=str(document["conversation_id"]),
            )
        )

    def test_queued_payload_is_strict_bounded_and_validated_before_network(self) -> None:
        sync_home, queue_path, _, document = self._prepare_queued_conversation()
        invalid_payloads = {
            "empty_object": b"{}",
            "duplicate": (
                b'{"schema_version":"0.1.0","schema_version":"0.1.0"}'
            ),
            "non_finite": b'{"schema_version":NaN}',
            "invalid_utf8": b"\xff",
            "non_canonical": json.dumps(
                document,
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8"),
            "too_large": b"x" * (MODULE.MAX_COLLECTOR_BODY_BYTES + 1),
        }
        opener = mock.MagicMock()

        with mock.patch.object(MODULE, "sync_home", return_value=sync_home):
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(
                    MODULE.request,
                    "build_opener",
                    return_value=opener,
                ):
                    for label, payload in invalid_payloads.items():
                        with self.subTest(label=label):
                            queue_path.write_bytes(payload)
                            self.assertEqual(1, MODULE.flush_queue())
                            self.assertTrue(queue_path.is_file())

        opener.open.assert_not_called()

    def test_non_json_content_type_keeps_queue_for_retry(self) -> None:
        sync_home, queue_path, payload, document = self._prepare_queued_conversation()
        receipt = {
            "state": "raw_imported",
            "conversation_id": document["conversation_id"],
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        opener = mock.MagicMock()
        opener.open.return_value = self._response(
            json.dumps(receipt).encode("utf-8"),
            content_type="text/plain",
        )

        with mock.patch.object(MODULE, "sync_home", return_value=sync_home):
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(
                    MODULE.request,
                    "build_opener",
                    return_value=opener,
                ):
                    self.assertEqual(1, MODULE.flush_queue())

        self.assertTrue(queue_path.is_file())

    def test_collector_redirect_is_not_followed_and_keeps_queue(self) -> None:
        sync_home, queue_path, _, _ = self._prepare_queued_conversation()

        class RedirectingHttpsHandler(MODULE.request.BaseHandler):
            handler_order = 100

            def __init__(self) -> None:
                self.requests: list[MODULE.request.Request] = []

            def https_open(self, outgoing: MODULE.request.Request) -> object:
                self.requests.append(outgoing)
                response = mock.MagicMock()
                response.code = 302
                response.status = 302
                response.msg = "Found"
                response.info.return_value = {
                    "Location": "https://outside.example.test/collect"
                }
                return response

        transport = RedirectingHttpsHandler()
        opener = MODULE.request.build_opener(
            MODULE.request.ProxyHandler({}),
            MODULE._RejectRedirectHandler(),
            transport,
        )

        def checked_build_opener(*handlers: object) -> object:
            self.assertTrue(
                any(
                    isinstance(handler, MODULE._RejectRedirectHandler)
                    for handler in handlers
                )
            )
            return opener

        with mock.patch.object(MODULE, "sync_home", return_value=sync_home):
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(
                    MODULE.request,
                    "build_opener",
                    side_effect=checked_build_opener,
                ):
                    self.assertEqual(1, MODULE.flush_queue())

        self.assertEqual(1, len(transport.requests))
        self.assertEqual(
            "https://collector.example.test/v1/conversations",
            transport.requests[0].full_url,
        )
        self.assertTrue(queue_path.is_file())
        self.assertFalse((sync_home / "receipts" / queue_path.name).exists())


if __name__ == "__main__":
    unittest.main()
