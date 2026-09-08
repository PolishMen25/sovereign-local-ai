import importlib.util
import json
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).parents[1]
MODULE_PATH = PROJECT_ROOT / "tools" / "validate_language_evaluation_suite.py"
SPEC = importlib.util.spec_from_file_location("validate_language_evaluation_suite", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SUITE_PATH = PROJECT_ROOT / "configs" / "evaluation" / "core-30m-e1.candidate.json"


class LanguageEvaluationSuiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = json.loads(SUITE_PATH.read_text(encoding="utf-8"))

    def test_candidate_suite_is_complete_and_balanced(self) -> None:
        MODULE.validate(self.document)
        self.assertEqual(50, len(self.document["prompts"]))
        self.assertEqual("candidate_owner_review_required", self.document["status"])

    def test_duplicate_or_misaligned_prompt_is_refused(self) -> None:
        changed = json.loads(json.dumps(self.document))
        changed["prompts"][1]["id"] = changed["prompts"][0]["id"]
        with self.assertRaisesRegex(ValueError, "id"):
            MODULE.validate(changed)
        changed = json.loads(json.dumps(self.document))
        changed["prompts"][0]["category"] = "networking"
        with self.assertRaisesRegex(ValueError, "match"):
            MODULE.validate(changed)

    def test_unknown_status_or_automatic_mode_is_refused(self) -> None:
        changed = json.loads(json.dumps(self.document))
        changed["status"] = "approved"
        with self.assertRaisesRegex(ValueError, "contract"):
            MODULE.validate(changed)
        changed = json.loads(json.dumps(self.document))
        changed["evaluation_mode"] = "automatic"
        with self.assertRaisesRegex(ValueError, "target"):
            MODULE.validate(changed)


if __name__ == "__main__":
    unittest.main()
