import json
from pathlib import Path
import re
import unittest

from services.arena import runner
from services.arena.runner import load_suite
from tools import build_core_increment_from_arena as bridge
from tools import generate_arena_practice_suite as gen

REPO = Path(__file__).resolve().parents[1]
SUITE_PATH = REPO / "configs" / "arena" / "practice-suite.v1.json"
SEALED_E2_PATH = REPO / "configs" / "evaluation" / "core-python-e2.candidate.json"

# The practice suite feeds CORE corpus increments; the E2 benchmark must stay
# unseen by training.  These 14 E2 tasks share their function name with a
# practice task whose prompt is a paraphrase.  They are listed, not accepted.
# D-040 admits arena data only without overlap with the evaluation sets, so the
# increment builder refuses any solution for these practice tasks.  D-044
# labels this E2 suite contaminated and replaces it, for evaluation, with a
# sealed E2-v2 kept out of the public repository (see
# docs/model/v1-evaluation-grid.md).  Any overlap not listed here fails.
KNOWN_E2_FUNCTION_OVERLAPS = {
    "balanced_brackets": ("python-14-balanced-brackets", "arena-030-balanced-brackets"),
    "binary_search": ("python-30-binary-search", "arena-086-binary-search"),
    "clamp": ("python-02-clamp", "arena-017-clamp"),
    "count_words": ("python-06-count-words", "arena-053-count-words"),
    "expand_port_range": ("python-37-port-range", "arena-116-expand-port-range"),
    "fibonacci": ("python-04-fibonacci", "arena-064-fibonacci"),
    "is_palindrome": ("python-03-palindrome", "arena-003-is-palindrome"),
    "median": ("python-48-median", "arena-019-median"),
    "merge_intervals": ("python-13-merge-intervals", "arena-133-merge-intervals"),
    "parse_query": ("python-18-parse-query", "arena-035-parse-query"),
    "prime_factors": ("python-25-prime-factors", "arena-014-prime-factors"),
    "render_template": ("python-49-template-render", "arena-162-template-render"),
    "rotate_left": ("python-12-rotate-left", "arena-077-rotate-left"),
    "slugify": ("python-17-slugify", "arena-007-slugify"),
}


def normalized_prompt(text: str) -> str:
    """Case, punctuation and spacing do not make two prompts different."""

    return " ".join(re.sub(r"[^0-9a-z_]+", " ", text.casefold()).split())


def sealed_tasks() -> list[dict]:
    return json.loads(SEALED_E2_PATH.read_text(encoding="utf-8"))["tasks"]


class ArenaPracticeSuiteTests(unittest.TestCase):
    def test_every_reference_solution_passes_its_tests(self) -> None:
        self.assertEqual(gen.self_validate(), [])

    def test_shipped_suite_matches_the_generator(self) -> None:
        self.assertEqual(json.loads(SUITE_PATH.read_text(encoding="utf-8")), gen.build_suite())

    def test_arena_can_load_it_and_ids_are_unique(self) -> None:
        tasks = load_suite(SUITE_PATH)
        self.assertGreaterEqual(len(tasks), 50)
        ids = [t["id"] for t in tasks]
        self.assertEqual(len(ids), len(set(ids)))
        for task in tasks:
            self.assertTrue(task["id"].startswith("arena-"))
            self.assertTrue(task["test_source"].strip())

    def test_distinct_from_the_sealed_benchmark(self) -> None:
        bench_ids = {t["id"] for t in sealed_tasks()}
        practice_ids = {t["id"] for t in load_suite(SUITE_PATH)}
        self.assertEqual(bench_ids & practice_ids, set())

    def test_function_name_overlaps_are_only_the_documented_ones(self) -> None:
        # Every (function, E2 task, practice task) triple, so that a second task
        # reusing an overlapping name cannot hide behind the first one.
        found = {
            (sealed["function_name"], sealed["id"], practice["id"])
            for sealed in sealed_tasks()
            for practice in json.loads(SUITE_PATH.read_text(encoding="utf-8"))["tasks"]
            if sealed["function_name"] == practice["function_name"]
        }
        documented = {(name, e2_id, practice_id)
                      for name, (e2_id, practice_id) in KNOWN_E2_FUNCTION_OVERLAPS.items()}
        self.assertEqual(sorted(found - documented), [],
                         "new function shared by the sealed E2 benchmark and the practice suite")
        self.assertEqual(found, documented, "the documented overlap list is stale: update it with the owner's decision")

    def test_the_increment_builder_withholds_exactly_the_documented_overlaps(self) -> None:
        _, _, withheld = bridge.load_task_suite(SUITE_PATH)
        self.assertEqual(withheld, {practice_id: name
                                    for name, (_, practice_id) in KNOWN_E2_FUNCTION_OVERLAPS.items()})

    def test_no_normalized_prompt_overlap(self) -> None:
        sealed = {normalized_prompt(t["prompt"]) for t in sealed_tasks()}
        practice = {normalized_prompt(t["prompt"]) for t in load_suite(SUITE_PATH)}
        self.assertEqual(sealed & practice, set())

    def test_prompt_normalization_ignores_case_punctuation_and_spacing(self) -> None:
        self.assertEqual(normalized_prompt("Write  clamp(x, lo, hi)!"), normalized_prompt("write CLAMP x lo hi"))
        self.assertNotEqual(normalized_prompt("Write clamp(x)."), normalized_prompt("Write median(x)."))

    def test_runner_and_bridge_default_to_the_practice_suite(self) -> None:
        self.assertEqual(runner.suite_path({}), Path("configs/arena/practice-suite.v1.json"))
        self.assertEqual(REPO / runner.suite_path({}), SUITE_PATH)
        self.assertEqual(Path(runner.DEFAULT_SUITE), bridge.DEFAULT_SUITE)
        self.assertEqual(runner.suite_path({"SOVEREIGN_ARENA_SUITE": "explicit.json"}), Path("explicit.json"))


if __name__ == "__main__":
    unittest.main()
