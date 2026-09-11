from pathlib import Path
import tempfile
import unittest

from services.arena.store import ArenaStore
from services.web.app import WebState


class WebChatProfilesTests(unittest.TestCase):
    def setUp(self) -> None:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.db = Path(d.name) / "arena.sqlite3"
        store = ArenaStore(self.db)
        store.initialize()
        store.add_profile({"profile_id": "author-x", "display_name": "Lecteur de spec", "role": "author",
                           "engine": "QWEN-CODER", "temperature": 0.2, "system_prompt": "PERSONA-PROMPT"})
        self.store = store

    def state(self) -> WebState:
        return WebState(None, None, None, None, None, "x" * 32, None, ArenaStore(self.db, read_only=True), None)

    def test_unapproved_agent_is_not_a_chat_profile(self) -> None:
        state = self.state()
        ids = {p["profile_id"] for p in state.chat_profiles()}
        self.assertIn("coordination", ids)
        self.assertNotIn("author-x", ids)
        self.assertIsNone(state.arena_chat_profile("author-x"))

    def test_approved_agent_becomes_a_selectable_chat_profile(self) -> None:
        self.assertTrue(self.store.approve_profile_for_chat("author-x"))
        state = self.state()
        by_id = {p["profile_id"]: p for p in state.chat_profiles()}
        self.assertIn("author-x", by_id)
        self.assertIn("arène", by_id["author-x"]["description"].lower())
        persona = state.arena_chat_profile("author-x")
        self.assertEqual(persona, {"system_prompt": "PERSONA-PROMPT", "engine": "QWEN-CODER"})

    def test_unknown_profile_is_none(self) -> None:
        self.store.approve_profile_for_chat("author-x")
        self.assertIsNone(self.state().arena_chat_profile("author-does-not-exist"))


if __name__ == "__main__":
    unittest.main()
