import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
import shutil
import unittest
import uuid

from services.inference.tokenizer import (
    experimental_tokenizer_document,
    promote_to_candidate_core,
    train_byte_bpe,
)
from tools.authorized_text_bundle import load_authorized_text_bundle


@contextmanager
def workspace_directory():
    directory = Path(__file__).parents[1] / f".authorized-bundle-{uuid.uuid4().hex}"
    directory.mkdir()
    try:
        yield directory
    finally:
        shutil.rmtree(directory)


def record(record_id: str, text: str) -> bytes:
    return (
        json.dumps(
            {"record_id": record_id, "text": text},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def build_documents(
    train: bytes,
    *,
    train_record_count: int = 1,
) -> tuple[dict, dict, bytes, bytes, bytes]:
    validation = record("validation-1", "Validation seulement.")
    test = record("test-1", "Test seulement.")
    global_materialization = train + validation + test
    result = train_byte_bpe(["bonjour bonjour bonjour"], 264)
    tokenizer = experimental_tokenizer_document(
        training_corpus_id="corpus-approved-bundle",
        training_corpus_sha256=sha256(train),
        result=result,
        minimum_frequency=2,
    )
    manifest = {
        "schema_version": "0.2.0",
        "corpus_id": "corpus-approved-bundle",
        "lifecycle_state": "VALIDATED",
        "classification": "approved_training",
        "materialization": {
            "format": "jsonl-utf8",
            "content_sha256": sha256(global_materialization),
            "byte_size": len(global_materialization),
            "record_count": train_record_count + 2,
        },
        "source_packages": [
            {
                "package_id": "package-train",
                "provenance_id": "provenance-train",
                "content_sha256": sha256(train),
                "license": "MIT",
                "languages": ["fr"],
                "review_state": "approved",
            },
            {
                "package_id": "package-validation",
                "provenance_id": "provenance-validation",
                "content_sha256": sha256(validation),
                "license": "MIT",
                "languages": ["fr"],
                "review_state": "approved",
            },
            {
                "package_id": "package-test",
                "provenance_id": "provenance-test",
                "content_sha256": sha256(test),
                "license": "MIT",
                "languages": ["fr"],
                "review_state": "approved",
            },
        ],
        "splits": {
            "train": {
                "package_ids": ["package-train"],
                "content_sha256": sha256(train),
                "byte_size": len(train),
                "record_count": train_record_count,
            },
            "validation": {
                "package_ids": ["package-validation"],
                "content_sha256": sha256(validation),
                "byte_size": len(validation),
                "record_count": 1,
            },
            "test": {
                "package_ids": ["package-test"],
                "content_sha256": sha256(test),
                "byte_size": len(test),
                "record_count": 1,
            },
        },
        "tokenizer_contract": {
            "input_encoding": "utf-8",
            "normalization_policy_id": "unicode-nfc-v1",
            "candidate_vocabulary_size": tokenizer["vocabulary_size"],
            "review_state": "approved",
        },
        "approvals": {
            "data_governance": "approved",
            "training_authorization": "approved",
        },
    }
    return manifest, tokenizer, validation, test, global_materialization


def write_inputs(
    directory: Path,
    manifest: dict,
    tokenizer: dict,
    train: bytes,
) -> tuple[Path, Path, Path]:
    manifest_path = directory / "manifest.json"
    train_path = directory / "train.jsonl"
    tokenizer_path = directory / "tokenizer.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    train_path.write_bytes(train)
    tokenizer_path.write_text(
        json.dumps(tokenizer, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return manifest_path, train_path, tokenizer_path


class AuthorizedTextBundleTests(unittest.TestCase):
    def test_loads_only_authorized_train_and_binds_content_free_lineage(self) -> None:
        train = record("train-1", "Bonjour depuis Lyon.")
        manifest, tokenizer, _, _, _ = build_documents(train)
        with workspace_directory() as temporary:
            paths = write_inputs(temporary, manifest, tokenizer, train)
            bundle = load_authorized_text_bundle(
                manifest_path=paths[0], train_jsonl_path=paths[1], tokenizer_path=paths[2]
            )

        self.assertEqual([item.record_id for item in bundle.records], ["train-1"])
        self.assertEqual(bundle.train_sha256, sha256(train))
        self.assertEqual(bundle.tokenizer_schema_version, "0.2.0")
        self.assertEqual(bundle.tokenizer_status, "experimental")
        self.assertEqual(bundle.tokenizer_vocabulary_size, tokenizer["vocabulary_size"])
        contract = bundle.lineage_contract()
        self.assertEqual(contract["corpus"]["split"], "train")
        self.assertEqual(contract["tokenizer"]["status"], "experimental")
        self.assertNotIn("records", contract)
        self.assertNotIn("path", json.dumps(contract))
        self.assertNotIn("approval", json.dumps(contract))

    def test_validation_test_and_global_materializations_are_refused(self) -> None:
        train = record("train-1", "Entraînement seulement.")
        manifest, tokenizer, validation, test, global_materialization = build_documents(train)
        for name, wrong_payload in (
            ("validation", validation),
            ("test", test),
            ("global", global_materialization),
        ):
            with self.subTest(name=name), workspace_directory() as temporary:
                paths = write_inputs(temporary, manifest, tokenizer, wrong_payload)
                with self.assertRaisesRegex(ValueError, name):
                    load_authorized_text_bundle(
                        manifest_path=paths[0],
                        train_jsonl_path=paths[1],
                        tokenizer_path=paths[2],
                    )

    def test_unknown_hash_and_declared_size_mismatch_are_refused(self) -> None:
        train = record("train-1", "Texte autorisé.")
        manifest, tokenizer, _, _, _ = build_documents(train)
        with workspace_directory() as temporary:
            paths = write_inputs(
                temporary, manifest, tokenizer, record("other", "Autre texte.")
            )
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                load_authorized_text_bundle(
                    manifest_path=paths[0], train_jsonl_path=paths[1], tokenizer_path=paths[2]
                )

        manifest["splits"]["train"]["byte_size"] += 1
        with workspace_directory() as temporary:
            paths = write_inputs(temporary, manifest, tokenizer, train)
            with self.assertRaisesRegex(ValueError, "byte size"):
                load_authorized_text_bundle(
                    manifest_path=paths[0], train_jsonl_path=paths[1], tokenizer_path=paths[2]
                )

    def test_record_count_duplicate_ids_and_invalid_utf8_are_refused(self) -> None:
        duplicate = record("same", "Premier") + record("same", "Second")
        manifest, tokenizer, _, _, _ = build_documents(
            duplicate, train_record_count=2
        )
        with workspace_directory() as temporary:
            paths = write_inputs(temporary, manifest, tokenizer, duplicate)
            with self.assertRaisesRegex(ValueError, "repeats"):
                load_authorized_text_bundle(
                    manifest_path=paths[0], train_jsonl_path=paths[1], tokenizer_path=paths[2]
                )

        invalid_utf8 = b"\xff\n"
        manifest, tokenizer, _, _, _ = build_documents(invalid_utf8)
        with workspace_directory() as temporary:
            paths = write_inputs(temporary, manifest, tokenizer, invalid_utf8)
            with self.assertRaisesRegex(ValueError, "UTF-8"):
                load_authorized_text_bundle(
                    manifest_path=paths[0], train_jsonl_path=paths[1], tokenizer_path=paths[2]
                )

    def test_record_count_and_line_size_are_enforced(self) -> None:
        train = record("train-1", "Court.")
        manifest, tokenizer, _, _, _ = build_documents(train)
        manifest["splits"]["train"]["record_count"] = 2
        manifest["materialization"]["record_count"] = 4
        with workspace_directory() as temporary:
            paths = write_inputs(temporary, manifest, tokenizer, train)
            with self.assertRaisesRegex(ValueError, "record count"):
                load_authorized_text_bundle(
                    manifest_path=paths[0], train_jsonl_path=paths[1], tokenizer_path=paths[2]
                )

        oversized = record("train-1", "x" * (1024 * 1024))
        manifest, tokenizer, _, _, _ = build_documents(oversized)
        with workspace_directory() as temporary:
            paths = write_inputs(temporary, manifest, tokenizer, oversized)
            with self.assertRaisesRegex(ValueError, "line size"):
                load_authorized_text_bundle(
                    manifest_path=paths[0], train_jsonl_path=paths[1], tokenizer_path=paths[2]
                )

    def test_candidate_core_tokenizer_is_linked_to_train_and_exact_vocab(self) -> None:
        train = record("train-1", "Tokenizer lié.")
        manifest, tokenizer, _, _, _ = build_documents(train)

        candidate = promote_to_candidate_core(tokenizer)
        with workspace_directory() as temporary:
            paths = write_inputs(temporary, manifest, candidate, train)
            bundle = load_authorized_text_bundle(
                manifest_path=paths[0], train_jsonl_path=paths[1], tokenizer_path=paths[2]
            )
        self.assertEqual(bundle.tokenizer_status, "candidate_core")

        wrong_lineage = dict(tokenizer)
        wrong_lineage["training_corpus_sha256"] = "f" * 64
        with workspace_directory() as temporary:
            paths = write_inputs(temporary, manifest, wrong_lineage, train)
            with self.assertRaisesRegex(ValueError, "authorized train"):
                load_authorized_text_bundle(
                    manifest_path=paths[0], train_jsonl_path=paths[1], tokenizer_path=paths[2]
                )

        manifest["tokenizer_contract"]["candidate_vocabulary_size"] += 1
        with workspace_directory() as temporary:
            paths = write_inputs(temporary, manifest, tokenizer, train)
            with self.assertRaisesRegex(ValueError, "vocabulary"):
                load_authorized_text_bundle(
                    manifest_path=paths[0], train_jsonl_path=paths[1], tokenizer_path=paths[2]
                )

    def test_tokenizer_schema_or_status_tampering_is_refused(self) -> None:
        train = record("train-1", "Artefact strict.")
        manifest, tokenizer, _, _, _ = build_documents(train)
        for field, value in (("schema_version", "0.1.0"), ("status", "approved_core_v1")):
            tampered = dict(tokenizer)
            tampered[field] = value
            with self.subTest(field=field), workspace_directory() as temporary:
                paths = write_inputs(temporary, manifest, tampered, train)
                with self.assertRaises(ValueError):
                    load_authorized_text_bundle(
                        manifest_path=paths[0],
                        train_jsonl_path=paths[1],
                        tokenizer_path=paths[2],
                    )


if __name__ == "__main__":
    unittest.main()
