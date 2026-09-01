from pathlib import Path
import unittest

from tools.verify_cpu_model_candidate import load_candidate


class CpuModelCandidateTests(unittest.TestCase):
    ROOT = Path(__file__).parents[1]

    def test_core_80m_candidate_is_structurally_valid(self) -> None:
        document, config = load_candidate(self.ROOT / "configs" / "models" / "core-80m.candidate.json")
        self.assertEqual(document["name"], "CORE-80M")
        self.assertEqual(config.vocabulary_size, 32000)

    def test_core_mini_uses_the_same_architecture_contract(self) -> None:
        document, config = load_candidate(self.ROOT / "configs" / "models" / "core-mini.candidate.json")
        self.assertEqual(document["name"], "CORE-MINI-1M")
        self.assertEqual(config.hidden_size, 128)


if __name__ == "__main__":
    unittest.main()
