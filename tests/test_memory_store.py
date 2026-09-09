from contextlib import closing
from pathlib import Path
import unittest

from services.memory.store import MemoryStore
from tests._temp_support import sovereign_temporary_directory


class MemoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = sovereign_temporary_directory()
        temporary_path = self.temporary.__enter__()
        self.database = Path(temporary_path) / "memory.sqlite3"
        self.store = MemoryStore(self.database)
        self.store.initialize()

    def tearDown(self) -> None:
        self.temporary.__exit__(None, None, None)

    def test_round_trip_redacts_secret_and_preserves_digest(self) -> None:
        conversation_id = self.store.create_conversation(conversation_id="conversation_001")
        message = self.store.append_message(
            conversation_id,
            role="user",
            content="password=VerySecretValue123!",
        )
        exported = self.store.export_conversation(conversation_id)
        self.assertNotIn("VerySecretValue123", exported["messages"][0]["content"])
        self.assertEqual(message["content_sha256"], exported["messages"][0]["content_sha256"])
        self.assertTrue(message["learning_candidate_queued"])
        self.assertEqual(self.store.learning_queue_summary(), {"messages": 1, "conversations": 1})

    def test_delete_removes_content_and_returns_content_free_receipt(self) -> None:
        conversation_id = self.store.create_conversation(conversation_id="conversation_002")
        self.store.append_message(conversation_id, role="user", content="private content")
        receipt = self.store.delete_conversation(conversation_id)
        self.assertEqual("conversation_deleted", receipt["event_type"])
        self.assertNotIn("content", receipt)
        with self.assertRaises(KeyError):
            self.store.export_conversation(conversation_id)
        self.assertEqual(self.store.learning_queue_summary(), {"messages": 0, "conversations": 0})

    def test_system_and_tool_messages_are_not_learning_candidates(self) -> None:
        conversation_id = self.store.create_conversation(conversation_id="conversation_004")
        self.assertFalse(self.store.append_message(conversation_id, role="system", content="internal prompt")["learning_candidate_queued"])
        self.assertFalse(self.store.append_message(conversation_id, role="tool", content="tool result")["learning_candidate_queued"])
        self.assertEqual(self.store.learning_queue_summary(), {"messages": 0, "conversations": 0})

    def test_backfill_queues_only_integrity_checked_sanitized_roles(self) -> None:
        conversation_id = self.store.create_conversation(conversation_id="conversation_005")
        user = self.store.append_message(conversation_id, role="user", content="safe question")
        self.store.append_message(conversation_id, role="assistant", content="safe answer")
        self.store.append_message(conversation_id, role="system", content="system")
        with closing(self.store._connect()) as connection, connection:
            connection.execute("DELETE FROM learning_queue")
        self.assertEqual(self.store.backfill_learning_queue(), {"queued": 2})
        self.assertEqual(self.store.learning_queue_summary(), {"messages": 2, "conversations": 1})
        self.assertIn(user["content_sha256"], {row["content_sha256"] for row in self.store.learning_candidates()})

    def test_unknown_conversation_and_invalid_inputs_fail_closed(self) -> None:
        with self.assertRaises(KeyError):
            self.store.append_message("conversation_999", role="user", content="hello")
        with self.assertRaises(ValueError):
            self.store.create_conversation(conversation_id="bad/id")
        with self.assertRaises(ValueError):
            self.store.list_conversations(limit=0)


if __name__ == "__main__":
    unittest.main()
