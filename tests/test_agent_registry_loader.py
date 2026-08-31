import json
from pathlib import Path
import unittest

from services.orchestrator.registry import RegistryError, get_profile, load_registry


ROOT = Path(__file__).parents[1]


class AgentRegistryLoaderTests(unittest.TestCase):
    def test_loads_project_registry_and_resolves_profile(self) -> None:
        registry = load_registry(ROOT / "configs" / "agents" / "registry.json")
        self.assertEqual(len(registry["profiles"]), 60)
        self.assertEqual(get_profile(registry, "code_reviewer")["family"], "development")

    def test_unknown_profile_fails_closed(self) -> None:
        registry = load_registry(ROOT / "configs" / "agents" / "registry.json")
        with self.assertRaises(RegistryError):
            get_profile(registry, "not_registered")

    def test_dangerous_capability_is_rejected(self) -> None:
        source = json.loads((ROOT / "configs" / "agents" / "registry.json").read_text(encoding="utf-8"))
        source["profiles"][0]["tool_allowlist"] = ["shell"]
        path = ROOT / "tests" / "invalid-agent-registry.json"
        try:
            path.write_text(json.dumps(source), encoding="utf-8")
            with self.assertRaises(RegistryError):
                load_registry(path)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
