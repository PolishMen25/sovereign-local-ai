import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).parents[1] / "tools" / "count_core_parameters.py"
SPEC = importlib.util.spec_from_file_location("count_core_parameters", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ParameterCountTests(unittest.TestCase):
    def test_candidate_total_is_exact(self) -> None:
        document = MODULE.load_candidate_document()
        config = MODULE.CoreConfig.from_document(document)
        result = MODULE.count_parameters(config)
        self.assertEqual(result["total_trainable"], 81_444_480)
        self.assertEqual(result, document["parameter_count"])

    def test_head_dimensions_must_cover_hidden_size(self) -> None:
        document = MODULE.load_candidate_document()
        config = MODULE.CoreConfig.from_document(document)
        invalid = MODULE.CoreConfig(
            vocabulary_size=config.vocabulary_size,
            hidden_size=641,
            num_hidden_layers=config.num_hidden_layers,
            num_attention_heads=config.num_attention_heads,
            head_dimension=config.head_dimension,
            intermediate_size=config.intermediate_size,
            tie_word_embeddings=config.tie_word_embeddings,
        )
        with self.assertRaises(ValueError):
            MODULE.count_parameters(invalid)


if __name__ == "__main__":
    unittest.main()

