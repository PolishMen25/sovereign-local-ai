from pathlib import Path
from types import SimpleNamespace
from array import array
import hashlib
import json
import shutil
import unittest
import uuid

from services.inference.tokenizer import ByteBpeTokenizer, experimental_tokenizer_document, train_byte_bpe
from tools.authorized_text_bundle import AuthorizedTextBundle, AuthorizedTextRecord
from tools.pretokenized_authorized_text import (
    load_pretokenized_authorized_text,
    pretokenized_text_token_rows,
)
from tools.train_core_mini import authorized_text_token_rows
from tools.train_core_700m import load_preflight, metric_record


def bundle() -> SimpleNamespace:
    return SimpleNamespace(
        tokenizer_sha256="a" * 64,
        tokenizer_vocabulary_size=32000,
        corpus_id="corpus-core-test",
        manifest_sha256="b" * 64,
        train_sha256="c" * 64,
    )


class Core700RunnerTests(unittest.TestCase):
    def _authorized_bundle(self) -> AuthorizedTextBundle:
        texts = ("A", "Texte autorisé plus long.", "Encore un document technique.")
        result = train_byte_bpe(["bonjour bonjour bonjour", *texts], 264)
        tokenizer = ByteBpeTokenizer.from_document(experimental_tokenizer_document(
            training_corpus_id="corpus-approved-training",
            training_corpus_sha256="b" * 64,
            result=result,
            minimum_frequency=2,
        ))
        return AuthorizedTextBundle(
            corpus_id="corpus-approved-training", manifest_schema_version="0.2.0",
            manifest_sha256="a" * 64, train_sha256="b" * 64,
            train_byte_size=123, train_record_count=len(texts),
            tokenizer_sha256="c" * 64, tokenizer_schema_version="0.2.0",
            tokenizer_status="candidate_core", tokenizer_vocabulary_size=264,
            normalization_policy_id="unicode-nfc-v1",
            records=tuple(AuthorizedTextRecord(record_id=f"record-{index}", text=text) for index, text in enumerate(texts)),
            tokenizer=tokenizer,
        )

    def _write_pretokenized(self, directory: Path, bundle: AuthorizedTextBundle) -> None:
        values = array("H")
        offsets = array("Q", [0])
        for record in bundle.records:
            values.extend(bundle.tokenizer.encode(record.text, bos=True, eos=True))
            offsets.append(len(values))
        tokens = values.tobytes()
        offset_bytes = offsets.tobytes()
        (directory / "tokens.u16.bin").write_bytes(tokens)
        (directory / "offsets.u64.bin").write_bytes(offset_bytes)
        manifest = {
            "artefact": "pretokenized-authorized-train",
            "corpus_manifest_sha256": bundle.manifest_sha256,
            "train_jsonl_sha256": bundle.train_sha256,
            "tokenizer_sha256": bundle.tokenizer_sha256,
            "encode_parameters": {"bos": True, "eos": True},
            "record_count": bundle.train_record_count,
            "token_count": len(values), "dtype": "uint16",
            "tokens_file": "tokens.u16.bin", "offsets_file": "offsets.u64.bin",
            "tokens_sha256": hashlib.sha256(tokens).hexdigest(),
            "offsets_sha256": hashlib.sha256(offset_bytes).hexdigest(),
        }
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_pretokenized_rows_are_strictly_equivalent_to_authorized_rows(self) -> None:
        directory = Path(__file__).parents[1] / f".pretokenized-{uuid.uuid4().hex}"
        directory.mkdir()
        try:
            bundle = self._authorized_bundle()
            self._write_pretokenized(directory, bundle)
            cache = load_pretokenized_authorized_text(directory, bundle=bundle)
            for seed in (1, 7, 20260909):
                for step in range(70):
                    self.assertEqual(
                        pretokenized_text_token_rows(cache, step=step, batch_size=3, sequence_length=8, seed=seed),
                        authorized_text_token_rows(bundle, step=step, batch_size=3, sequence_length=8, seed=seed),
                    )
        finally:
            shutil.rmtree(directory)

    def test_pretokenized_cache_refuses_a_manifest_divergence(self) -> None:
        directory = Path(__file__).parents[1] / f".pretokenized-{uuid.uuid4().hex}"
        directory.mkdir()
        try:
            bundle = self._authorized_bundle()
            self._write_pretokenized(directory, bundle)
            manifest_path = directory / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["tokenizer_sha256"] = "d" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "authorized bundle"):
                load_pretokenized_authorized_text(directory, bundle=bundle)
        finally:
            shutil.rmtree(directory)

    def test_metric_is_content_free_and_measurable(self) -> None:
        metric = metric_record(step=2, loss=1.5, tokens=64, elapsed_seconds=2.0, cpu_seconds=1.0)
        self.assertEqual("core-700m-metric.v1", metric["schema_version"])
        self.assertNotIn("content", metric)
        with self.assertRaises(ValueError):
            metric_record(step=0, loss=1.0, tokens=1, elapsed_seconds=0.0, cpu_seconds=0.0)

        core_30_metric = metric_record(
            model_name="CORE-30M", step=2, loss=1.5, tokens=64,
            elapsed_seconds=2.0, cpu_seconds=1.0,
        )
        self.assertEqual("core-30m-metric.v1", core_30_metric["schema_version"])

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
            self.assertEqual(load_preflight(path, model_name="CORE-700M", config_sha256="d" * 64, bundle=candidate)["model_name"], "CORE-700M")
            receipt["tokenizer_status"] = "experimental"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_preflight(path, model_name="CORE-700M", config_sha256="d" * 64, bundle=candidate)
        finally:
            shutil.rmtree(directory)
