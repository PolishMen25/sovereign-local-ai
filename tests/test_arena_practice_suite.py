import json
from pathlib import Path
import unittest

from services.arena.runner import load_suite
from tools import generate_arena_practice_suite as gen

SUITE_PATH = Path(__file__).resolve().parents[1] / "configs" / "arena" / "practice-suite.v1.json"


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
        benchmark = Path(__file__).resolve().parents[1] / "configs" / "evaluation" / "core-python-e2.candidate.json"
        bench_ids = {t["id"] for t in json.loads(benchmark.read_text(encoding="utf-8"))["tasks"]}
        practice_ids = {t["id"] for t in load_suite(SUITE_PATH)}
        self.assertEqual(bench_ids & practice_ids, set())


if __name__ == "__main__":
    unittest.main()
