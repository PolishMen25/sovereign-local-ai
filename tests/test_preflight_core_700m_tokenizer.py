from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.preflight_core_700m_tokenizer import preflight


ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "configs" / "models" / "core-700m.candidate.json"


def bundle(*, status: str = "candidate_core", vocabulary: int = 32000):
    return SimpleNamespace(
        tokenizer_status=status,
        tokenizer_vocabulary_size=vocabulary,
        tokenizer_sha256="a" * 64,
        corpus_id="corpus-approved-preflight",
        manifest_sha256="b" * 64,
        train_sha256="c" * 64,
    )


class Core700TokenizerPreflightTests(unittest.TestCase):
    def test_candidate_core_32k_is_bound_without_model_allocation(self) -> None:
        with patch(
            "tools.preflight_core_700m_tokenizer.load_authorized_text_bundle", return_value=bundle()
        ):
            result = preflight(
                config_path=CONFIG,
                manifest_path=Path("manifest.json"),
                train_jsonl_path=Path("train.jsonl"),
                tokenizer_path=Path("tokenizer.json"),
            )
        self.assertEqual(result["model_name"], "CORE-700M")
        self.assertEqual(result["model_parameters"], 691_160_320)
        self.assertEqual(result["tokenizer_status"], "candidate_core")

    def test_invalid_manifest_bundle_refuses_preflight(self) -> None:
        with self.assertRaisesRegex(ValueError, "license"), patch(
            "tools.preflight_core_700m_tokenizer.load_authorized_text_bundle",
            side_effect=ValueError("source_package.license is not allowed for training"),
        ) as load_bundle:
            preflight(
                config_path=CONFIG,
                manifest_path=Path("manifest.json"),
                train_jsonl_path=Path("train.jsonl"),
                tokenizer_path=Path("tokenizer.json"),
            )
        load_bundle.assert_called_once()

    def test_experimental_or_wrong_vocabulary_is_refused(self) -> None:
        for candidate in (bundle(status="experimental"), bundle(vocabulary=4096)):
            with self.subTest(candidate=candidate), patch(
                "tools.preflight_core_700m_tokenizer.load_authorized_text_bundle",
                return_value=candidate,
            ):
                with self.assertRaises(ValueError):
                    preflight(
                        config_path=CONFIG,
                        manifest_path=Path("manifest.json"),
                        train_jsonl_path=Path("train.jsonl"),
                        tokenizer_path=Path("tokenizer.json"),
                    )
