from contextlib import redirect_stderr
import hashlib
from io import StringIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from services.inference.configuration import (
    MAXIMUM_MODEL_CONFIG_BYTES,
    load_core_candidate_configuration,
    load_core_mini_configuration,
)
from tests._temp_support import sovereign_temporary_directory
from tools.count_core_parameters import CoreConfig, count_parameters
from tools.train_core_mini import DATA_MODE_SYNTHETIC, main as training_main


DEFAULT_CONFIG = (
    Path(__file__).parents[1]
    / "configs"
    / "models"
    / "core-mini.candidate.json"
)
CORE_700_CONFIG = Path(__file__).parents[1] / "configs" / "models" / "core-700m.candidate.json"


class CountingPath:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.open_count = 0

    def open(self, *args, **kwargs):
        self.open_count += 1
        return self.path.open(*args, **kwargs)


class InferenceConfigurationTests(unittest.TestCase):
    def test_semantically_identical_copy_is_accepted_and_hashed_once(self) -> None:
        document = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
        compact = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        self.assertNotEqual(compact, DEFAULT_CONFIG.read_bytes())
        with sovereign_temporary_directory() as temporary_directory:
            copied_config = Path(temporary_directory) / "semantic-copy.json"
            copied_config.write_bytes(compact)
            counting_path = CountingPath(copied_config)
            loaded_document, config, digest = load_core_mini_configuration(
                counting_path
            )
        self.assertEqual(counting_path.open_count, 1)
        self.assertEqual(loaded_document, document)
        self.assertEqual(config, CoreConfig.from_document(document))
        self.assertEqual(digest, hashlib.sha256(compact).hexdigest())

    def test_duplicate_keys_and_oversized_documents_are_refused(self) -> None:
        duplicate = b'{"name":"CORE-MINI-1M",' + DEFAULT_CONFIG.read_bytes()[1:]
        with sovereign_temporary_directory() as temporary_directory:
            directory = Path(temporary_directory)
            duplicate_path = directory / "duplicate.json"
            duplicate_path.write_bytes(duplicate)
            with self.assertRaisesRegex(ValueError, "strict JSON"):
                load_core_mini_configuration(duplicate_path)

            oversized_path = directory / "oversized.json"
            oversized_path.write_bytes(b" " * (MAXIMUM_MODEL_CONFIG_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "bounded"):
                load_core_mini_configuration(oversized_path)

    def test_core_700m_preflight_is_strict_without_allocating_the_model(self) -> None:
        document, config, digest = load_core_candidate_configuration(CORE_700_CONFIG)
        self.assertEqual("CORE-700M", document["name"])
        self.assertEqual(691_160_320, count_parameters(config)["total_trainable"])
        self.assertEqual(digest, hashlib.sha256(CORE_700_CONFIG.read_bytes()).hexdigest())
        with sovereign_temporary_directory() as temporary_directory:
            duplicate_path = Path(temporary_directory) / "duplicate-core.json"
            duplicate_path.write_bytes(b'{"name":"CORE-700M",' + CORE_700_CONFIG.read_bytes()[1:])
            with self.assertRaisesRegex(ValueError, "strict JSON"):
                load_core_candidate_configuration(duplicate_path)

    def test_self_consistent_giant_candidate_is_refused_before_torch_or_model_build(self) -> None:
        document = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
        document["architecture"]["vocabulary_size"] = 8_192
        document["parameter_count"] = count_parameters(
            CoreConfig.from_document(document)
        )
        with sovereign_temporary_directory() as temporary_directory:
            directory = Path(temporary_directory)
            config_path = directory / "giant.json"
            config_path.write_text(
                json.dumps(document, sort_keys=True), encoding="utf-8"
            )
            with patch("tools.train_core_mini.require_cpu_torch") as require_torch, patch(
                "tools.train_core_mini.build_model"
            ) as build_model:
                stderr = StringIO()
                with redirect_stderr(stderr):
                    result = training_main(
                        [
                            "--config",
                            str(config_path),
                            "--output-dir",
                            str(directory / "output"),
                            "--data-mode",
                            DATA_MODE_SYNTHETIC,
                        ]
                    )
        self.assertEqual(result, 1)
        self.assertEqual(stderr.getvalue().strip(), "CORE-MINI training refused")
        self.assertNotIn(str(config_path), stderr.getvalue())
        require_torch.assert_not_called()
        build_model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
