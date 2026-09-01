import json
from pathlib import Path
import unittest


LOCK_PATH = Path(__file__).parents[1] / "configs" / "runtime" / "bootstrap-qwen2.5-1.5b-q4km.lock.json"


class BootstrapModelLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = json.loads(LOCK_PATH.read_text(encoding="utf-8"))

    def test_artifacts_are_pinned_by_lowercase_sha256(self) -> None:
        for component in ("model", "runtime", "local_cpu_dependency"):
            digest = self.document[component]["sha256"]
            self.assertEqual(len(digest), 64)
            self.assertEqual(digest, digest.lower())
            self.assertTrue(all(character in "0123456789abcdef" for character in digest))

    def test_runtime_policy_remains_cli_only_and_offline(self) -> None:
        policy = self.document["execution_policy"]
        self.assertEqual(policy["interface"], "ssh_cli_only")
        self.assertFalse(policy["network_download_at_runtime"])
        self.assertFalse(policy["persistent_service"])
        self.assertFalse(policy["tools_enabled"])
        self.assertFalse(policy["rag_enabled"])
        self.assertFalse(policy["conversation_logging"])

    def test_bootstrap_is_not_declared_as_core(self) -> None:
        self.assertEqual(self.document["status"], "approved_cli_bootstrap")
        self.assertNotIn("CORE", self.document["model"]["name"].upper())


if __name__ == "__main__":
    unittest.main()
