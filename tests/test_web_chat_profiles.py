from pathlib import Path
import tempfile
import unittest

from services.arena.store import ArenaStore
from services.web.app import WebState
from services.web.catalog_profiles import load_catalog_profiles, engine_for_family


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


class CatalogProfilesTests(unittest.TestCase):
    CATALOG = [
        {"profile_id": "test_designer", "display_name": "test designer", "family": "development",
         "mission": "Conçoit des tests", "engine": "QWEN-CODER", "system_prompt": "PERSONA-CODE", "tools": False},
        {"profile_id": "threat_modeler", "display_name": "threat modeler", "family": "security",
         "mission": "Modélise les menaces", "engine": "BOOTSTRAP", "system_prompt": "PERSONA-14B", "tools": True},
    ]

    def state(self) -> WebState:
        return WebState(None, None, None, None, None, "x" * 32, catalog=self.CATALOG)

    def test_catalog_profiles_are_selectable(self) -> None:
        by_id = {p["profile_id"]: p for p in self.state().chat_profiles()}
        self.assertIn("coordination", by_id)
        self.assertIn("test_designer", by_id)
        self.assertIn("threat_modeler", by_id)
        self.assertIn("Qwen-Coder 7B", by_id["test_designer"]["description"])

    def test_catalog_profile_resolves_persona(self) -> None:
        state = self.state()
        self.assertEqual(state.catalog_profile("threat_modeler"),
                         {"system_prompt": "PERSONA-14B", "engine": "BOOTSTRAP", "tools": True})
        self.assertEqual(state.catalog_profile("test_designer")["engine"], "QWEN-CODER")
        self.assertIsNone(state.catalog_profile("nope"))


class CatalogLoaderTests(unittest.TestCase):
    REGISTRY = Path("configs/agents/registry.json")

    def test_loads_registry_without_coordination(self) -> None:
        profiles = load_catalog_profiles(self.REGISTRY)
        self.assertGreaterEqual(len(profiles), 50)
        ids = {p["profile_id"] for p in profiles}
        self.assertNotIn("coordination", ids)
        for profile in profiles:
            self.assertIn(profile["engine"], {"BOOTSTRAP", "QWEN-CODER"})
            self.assertIn("Sovereign", profile["system_prompt"])

    def test_family_engine_mapping(self) -> None:
        self.assertEqual(engine_for_family("development"), "QWEN-CODER")
        self.assertEqual(engine_for_family("security"), "BOOTSTRAP")

    def test_missing_registry_is_empty(self) -> None:
        self.assertEqual(load_catalog_profiles(Path("/nonexistent/registry.json")), [])


if __name__ == "__main__":
    unittest.main()
