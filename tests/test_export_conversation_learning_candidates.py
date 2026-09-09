import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import unittest

from services.memory.store import MemoryStore
from tests._temp_support import sovereign_temporary_directory
from tools.export_conversation_learning_candidates import export_learning_candidates


class ConversationLearningCandidateExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = sovereign_temporary_directory()
        self.root = Path(self.temporary.__enter__())
        self.database = self.root / "memory.sqlite3"
        self.store = MemoryStore(self.database)
        self.store.initialize()

    def tearDown(self) -> None:
        self.temporary.__exit__(None, None, None)

    def test_exports_only_complete_redacted_pairs_with_verified_digest(self) -> None:
        first = self.store.create_conversation(conversation_id="conversation_001")
        self.store.append_message(first, role="system", content="private system prompt")
        self.store.append_message(first, role="user", content="password=VerySecretValue123!")
        self.store.append_message(first, role="assistant", content="La valeur a été masquée.")
        self.store.append_message(first, role="assistant", content="orphan answer")
        self.store.append_message(first, role="user", content="unanswered question")

        manifest = export_learning_candidates(database=self.database, output_dir=self.root / "candidate")
        data = (self.root / "candidate" / "learning-candidates.jsonl").read_bytes()
        record = json.loads(data)

        self.assertEqual(manifest["approval_status"], "pending_owner_approval")
        self.assertFalse(manifest["automatic_promotion"])
        self.assertEqual(manifest["record_count"], 1)
        self.assertEqual(manifest["excluded_messages"], {"orphan_assistant": 1, "superseded_user": 0, "unanswered_user": 1})
        self.assertNotIn("VerySecretValue123", record["text"])
        self.assertIn("[SENSITIVE DATA REMOVED]", record["text"])
        self.assertNotIn(first, record["conversation_sha256"])
        self.assertEqual(hashlib.sha256(data).hexdigest(), manifest["data_sha256"])

    def test_export_is_deterministic_for_the_same_queue_snapshot(self) -> None:
        conversation = self.store.create_conversation(conversation_id="conversation_002")
        self.store.append_message(conversation, role="user", content="Bonjour")
        self.store.append_message(conversation, role="assistant", content="Salut")

        first = export_learning_candidates(database=self.database, output_dir=self.root / "first")
        second = export_learning_candidates(database=self.database, output_dir=self.root / "second")
        self.assertEqual(first, second)
        self.assertEqual(
            (self.root / "first" / "learning-candidates.jsonl").read_bytes(),
            (self.root / "second" / "learning-candidates.jsonl").read_bytes(),
        )

    def test_explicit_backfill_exports_older_sanitized_messages(self) -> None:
        conversation = self.store.create_conversation(conversation_id="conversation_005")
        self.store.append_message(conversation, role="user", content="question")
        self.store.append_message(conversation, role="assistant", content="answer")
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("DELETE FROM learning_queue")

        manifest = export_learning_candidates(
            database=self.database,
            output_dir=self.root / "backfilled",
            backfill_existing=True,
        )
        self.assertEqual(manifest["backfilled_message_count"], 2)
        self.assertEqual(manifest["record_count"], 1)

    def test_refuses_existing_destination_and_empty_queue(self) -> None:
        (self.root / "existing").mkdir()
        with self.assertRaises(FileExistsError):
            export_learning_candidates(database=self.database, output_dir=self.root / "existing")
        with self.assertRaisesRegex(ValueError, "no complete"):
            export_learning_candidates(database=self.database, output_dir=self.root / "empty")

    def test_refuses_content_changed_without_matching_digest(self) -> None:
        conversation = self.store.create_conversation(conversation_id="conversation_003")
        message = self.store.append_message(conversation, role="user", content="question")
        self.store.append_message(conversation, role="assistant", content="answer")
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("UPDATE messages SET content='tampered' WHERE message_id=?", (message["message_id"],))
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            export_learning_candidates(database=self.database, output_dir=self.root / "tampered")

    def test_refuses_queue_digest_changed_without_matching_message(self) -> None:
        conversation = self.store.create_conversation(conversation_id="conversation_004")
        message = self.store.append_message(conversation, role="user", content="question")
        self.store.append_message(conversation, role="assistant", content="answer")
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute(
                "UPDATE learning_queue SET content_sha256=? WHERE message_id=?",
                ("0" * 64, message["message_id"]),
            )
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            export_learning_candidates(database=self.database, output_dir=self.root / "queue-tampered")

    def test_backfill_refuses_historical_unsanitized_content(self) -> None:
        conversation = self.store.create_conversation(conversation_id="conversation_006")
        message = self.store.append_message(conversation, role="user", content="safe question")
        self.store.append_message(conversation, role="assistant", content="answer")
        raw_secret = "password=UnsafeHistoricalValue123!"
        raw_digest = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("DELETE FROM learning_queue")
            connection.execute(
                "UPDATE messages SET content=?,content_sha256=? WHERE message_id=?",
                (raw_secret, raw_digest, message["message_id"]),
            )
        with self.assertRaisesRegex(ValueError, "not fully sanitized"):
            export_learning_candidates(
                database=self.database,
                output_dir=self.root / "unsafe-backfill",
                backfill_existing=True,
            )
        self.assertEqual(self.store.learning_queue_summary(), {"messages": 0, "conversations": 0})


if __name__ == "__main__":
    unittest.main()
