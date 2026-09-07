import copy
import json
from pathlib import Path
import unittest

from tools.validate_training_source_policy import validate


POLICY_PATH = Path(__file__).parents[1] / "configs" / "corpus" / "core-v1-source-policy.candidate.json"


class TrainingSourcePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    def test_candidate_policy_matches_owner_choices(self) -> None:
        validate(self.policy)
        self.assertEqual(["fr", "en"], self.policy["target_languages"])
        self.assertIn("MIT", self.policy["allowed_licenses"])
        self.assertNotIn("GPL-3.0-only", self.policy["allowed_licenses"])

    def test_policy_refuses_approval_or_missing_protection(self) -> None:
        approved = copy.deepcopy(self.policy)
        approved["status"] = "approved"
        with self.assertRaises(ValueError):
            validate(approved)
        unsafe = copy.deepcopy(self.policy)
        unsafe["excluded_content"].remove("private-conversations")
        with self.assertRaises(ValueError):
            validate(unsafe)


if __name__ == "__main__":
    unittest.main()
