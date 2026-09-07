from pathlib import Path
from types import SimpleNamespace
import json
import shutil
import unittest
import uuid

from tools.train_core_700m import load_preflight


def bundle() -> SimpleNamespace:
    return SimpleNamespace(
        tokenizer_sha256="a" * 64,
        tokenizer_vocabulary_size=32000,
        corpus_id="corpus-core-test",
        manifest_sha256="b" * 64,
        train_sha256="c" * 64,
    )


class Core700RunnerTests(unittest.TestCase):
    def test_matching_preflight_is_required(self) -> None:
        candidate = bundle()
        receipt = {
            "schema_version": "core-700m-tokenizer-preflight.v1",
            "model_name": "CORE-700M",
            "model_config_sha256": "d" * 64,
            "tokenizer_status": "candidate_core",
            "tokenizer_sha256": candidate.tokenizer_sha256,
            "tokenizer_vocabulary_size": candidate.tokenizer_vocabulary_size,
            "corpus_id": candidate.corpus_id,
            "manifest_sha256": candidate.manifest_sha256,
            "train_split_sha256": candidate.train_sha256,
        }
        directory = Path(__file__).parents[1] / f".core-700-runner-{uuid.uuid4().hex}"
        directory.mkdir()
        try:
            path = directory / "preflight.json"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            self.assertEqual(load_preflight(path, config_sha256="d" * 64, bundle=candidate)["model_name"], "CORE-700M")
            receipt["tokenizer_status"] = "experimental"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_preflight(path, config_sha256="d" * 64, bundle=candidate)
        finally:
            shutil.rmtree(directory)
