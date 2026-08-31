import json
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class AgentRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = json.loads((ROOT / "configs" / "agents" / "registry.json").read_text(encoding="utf-8"))

    def test_registry_contains_sixty_unique_logical_profiles(self) -> None:
        profiles = self.registry["profiles"]
        self.assertEqual(self.registry["schema_version"], "agent-profile-registry.v1")
        self.assertEqual(len(profiles), 60)
        self.assertEqual(len({profile["id"] for profile in profiles}), 60)

    def test_profiles_are_proposal_only_and_have_no_dangerous_capability(self) -> None:
        forbidden = {"shell", "filesystem.read_arbitrary", "filesystem.write_arbitrary", "network.arbitrary", "secrets.read"}
        for profile in self.registry["profiles"]:
            self.assertEqual(profile["status"], "draft")
            self.assertEqual(profile["action_policy"], "proposal_only")
            self.assertFalse(profile["memory_policy"]["writes"])
            self.assertTrue(forbidden.isdisjoint(profile["capabilities"]))
            self.assertTrue(forbidden.isdisjoint(profile["tool_allowlist"]))

    def test_profiles_have_stable_eval_and_output_contracts(self) -> None:
        for profile in self.registry["profiles"]:
            self.assertRegex(profile["version"], r"^\d+\.\d+\.\d+$")
            self.assertRegex(profile["eval_suite"], r"^agent-[a-z0-9_]+\.v1$")
            self.assertEqual(profile["output_schema"], "local-assistant-response.v1")


if __name__ == "__main__":
    unittest.main()
