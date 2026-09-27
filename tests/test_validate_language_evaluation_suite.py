import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).parents[1]
MODULE_PATH = PROJECT_ROOT / "tools" / "validate_language_evaluation_suite.py"
SPEC = importlib.util.spec_from_file_location("validate_language_evaluation_suite", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SUITE_PATH = PROJECT_ROOT / "configs" / "evaluation" / "core-30m-e1.candidate.json"


def synthetic_suite(model_name: str, per_cell: int) -> dict:
    prompts = [
        {
            "id": f"{language}-{category}-{index:02d}",
            "language": language,
            "category": category,
            "prompt": f"Synthetic {language} {category} prompt number {index}.",
        }
        for language in MODULE.LANGUAGES
        for category in MODULE.CATEGORIES
        for index in range(1, per_cell + 1)
    ]
    return {
        "schema_version": MODULE.SUITE_SCHEMA,
        "status": MODULE.STATUS,
        "model_name": model_name,
        "evaluation_mode": "owner_blind_review",
        "languages": list(MODULE.LANGUAGES),
        "categories": list(MODULE.CATEGORIES),
        "prompts": prompts,
    }


class LanguageEvaluationSuiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = json.loads(SUITE_PATH.read_text(encoding="utf-8"))

    def test_candidate_suite_is_complete_and_balanced(self) -> None:
        MODULE.validate(self.document)
        MODULE.validate(self.document, model_name="CORE-30M", prompt_count=50)
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

    def test_core_700m_suite_with_another_balanced_size_is_accepted(self) -> None:
        document = synthetic_suite("CORE-700M", per_cell=8)
        MODULE.validate(document)
        MODULE.validate(document, model_name="CORE-700M", prompt_count=80)

    def test_unsupported_model_is_refused(self) -> None:
        for name in ("CORE-80M", "Qwen2.5-1.5B", "", None):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "target"):
                MODULE.validate(synthetic_suite(name, per_cell=2))

    def test_expected_model_or_count_mismatch_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected model"):
            MODULE.validate(self.document, model_name="CORE-700M")
        with self.assertRaisesRegex(ValueError, "expected count"):
            MODULE.validate(self.document, prompt_count=60)

    def test_unbalanced_or_unbounded_size_is_refused(self) -> None:
        document = synthetic_suite("CORE-700M", per_cell=3)
        document["prompts"] = document["prompts"][:-1]
        with self.assertRaisesRegex(ValueError, "multiple"):
            MODULE.validate(document)
        with self.assertRaisesRegex(ValueError, "multiple|bounded"):
            MODULE.validate(synthetic_suite("CORE-700M", per_cell=0))
        with self.assertRaisesRegex(ValueError, "bounded"):
            MODULE.validate(synthetic_suite("CORE-700M", per_cell=100))
        document = synthetic_suite("CORE-700M", per_cell=2)
        moved = next(item for item in document["prompts"] if item["id"] == "fr-general-02")
        moved.update({"id": "fr-systems-03", "category": "systems"})
        with self.assertRaisesRegex(ValueError, "id"):
            MODULE.validate(document)

    def test_prompt_index_beyond_the_cell_size_is_refused(self) -> None:
        document = synthetic_suite("CORE-700M", per_cell=2)
        document["prompts"][1]["id"] = "fr-general-03"
        with self.assertRaisesRegex(ValueError, "id"):
            MODULE.validate(document)

    def test_command_line_reports_and_pins_the_target(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, MODULE.main([str(SUITE_PATH), "--model", "CORE-30M", "--prompt-count", "50"]))
        self.assertIn("valid", output.getvalue())
        with contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(1, MODULE.main([str(SUITE_PATH), "--model", "CORE-700M"]))
        self.assertIn("invalid language evaluation suite", error.getvalue())
        with tempfile.TemporaryDirectory() as directory:
            broken = Path(directory) / "suite.json"
            broken.write_bytes(b"{not json")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(1, MODULE.main([str(broken)]))


if __name__ == "__main__":
    unittest.main()
