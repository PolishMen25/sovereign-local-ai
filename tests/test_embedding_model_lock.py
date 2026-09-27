"""Static activation gate for the candidate RAG embedding model lock.

The embedding runtime was wired by commit d7cc78c without a lock, a promotion
record or a register entry (D-028 requires a verified license and digest).
The candidate lock records what is still unknown as ``pending_*`` values.  The
check below refuses activation while any such value remains and proves, with
a synthetic complete lock, that the refusal is not unconditional.

Nothing reads this lock at runtime: this is a repository gate only.
"""

import copy
import json
from pathlib import Path
import re
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = REPOSITORY_ROOT / "configs" / "runtime" / "qwen3-embedding-0.6b-q8_0.lock.candidate.json"
MAXIMUM_LOCK_BYTES = 64 * 1024
PENDING_PREFIX = "pending_"
ACTIVE_STATUS = "promoted_owner_approved"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_REVISION = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9._-]{1,96}/[A-Za-z0-9._-]{1,96}$")
DECISION_ID = re.compile(r"^D-[0-9]{3}$")
PROMOTION_RECORD = re.compile(r"^configs/runtime/[a-z0-9][a-z0-9._-]{0,95}\.promotion\.json$")
IPV4 = re.compile(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])")
INTERNAL_PATH_MARKERS = ("/opt/", "/var/", "/mnt/", "/etc/", "/home/", "/root/", "/volume", "/srv/", ":\\")

TOP_LEVEL = {
    "schema_version", "status", "purpose", "governance", "model", "runtime",
    "activation_gate", "promotion_record", "deployment_state",
}
GOVERNANCE_KEYS = {"decision", "adr", "adr_status", "introduced_by_commit", "owner_ratification"}
MODEL_KEYS = {
    "name", "quantization", "embedding_dimensions", "repository", "revision", "filename",
    "byte_size", "sha256", "license", "license_claimed_by_commit", "license_evidence_url", "source_url",
}
RUNTIME_KEYS = {
    "name", "release_declared_by_unit", "device", "network_download_at_runtime",
    "offline_flag_required", "bind", "pooling", "context_size",
}
GATE_KEYS = {
    "raw_readback_sha256_required", "runtime_readback_sha256_required", "license_readback_required",
    "loopback_and_no_egress_test_required", "promotion_record_required", "owner_ratification_required",
}


def _refuse_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError(f"duplicate key: {key}")
        document[key] = value
    return document


def _refuse_constant(name: str) -> None:
    raise ValueError(f"non-finite JSON constant: {name}")


def load_lock(path: Path) -> dict:
    raw = path.read_bytes()
    if len(raw) > MAXIMUM_LOCK_BYTES:
        raise ValueError("lock exceeds its size limit")
    document = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_refuse_duplicate_keys,
        parse_constant=_refuse_constant,
    )
    if not isinstance(document, dict):
        raise ValueError("lock must be a JSON object")
    return document


def _pending_fields(value: object, location: str) -> list[str]:
    if isinstance(value, dict):
        found: list[str] = []
        for key, nested in value.items():
            found.extend(_pending_fields(nested, f"{location}.{key}" if location else key))
        return found
    if isinstance(value, list):
        found = []
        for index, nested in enumerate(value):
            found.extend(_pending_fields(nested, f"{location}[{index}]"))
        return found
    if isinstance(value, str) and value.startswith(PENDING_PREFIX):
        return [location]
    return []


def _section(document: dict, name: str, keys: set[str], blockers: list[str]) -> dict:
    section = document.get(name)
    if not isinstance(section, dict) or set(section) != keys:
        blockers.append(f"{name} keys must be exactly {sorted(keys)}")
        return {}
    return section


def activation_blockers(document: object, *, repository_root: Path) -> list[str]:
    """Return every reason the lock cannot be activated; an empty list allows it."""

    if not isinstance(document, dict):
        return ["lock must be a JSON object"]
    blockers = [f"{location} is pending" for location in _pending_fields(document, "")]
    if set(document) != TOP_LEVEL:
        blockers.append(f"top-level keys must be exactly {sorted(TOP_LEVEL)}")
    if document.get("schema_version") != "embedding-model-lock.v1":
        blockers.append("unsupported schema_version")
    if document.get("status") != ACTIVE_STATUS:
        blockers.append(f"status is not {ACTIVE_STATUS}")

    governance = _section(document, "governance", GOVERNANCE_KEYS, blockers)
    if governance:
        if governance["decision"] != "D-028":
            blockers.append("governance.decision must be D-028")
        ratification = governance["owner_ratification"]
        if not isinstance(ratification, str) or not DECISION_ID.fullmatch(ratification):
            blockers.append("governance.owner_ratification must cite a register entry")

    model = _section(document, "model", MODEL_KEYS, blockers)
    if model:
        if not isinstance(model["sha256"], str) or not SHA256.fullmatch(model["sha256"]):
            blockers.append("model.sha256 must be a lowercase SHA-256")
        if type(model["byte_size"]) is not int or model["byte_size"] <= 0:
            blockers.append("model.byte_size must be a positive integer")
        if not isinstance(model["revision"], str) or not GIT_REVISION.fullmatch(model["revision"]):
            blockers.append("model.revision must be a full lowercase commit identifier")
        if not isinstance(model["repository"], str) or not REPOSITORY.fullmatch(model["repository"]):
            blockers.append("model.repository must be owner/name")
        filename = model["filename"]
        if not isinstance(filename, str) or not filename.endswith(".gguf") or "/" in filename or "\\" in filename:
            blockers.append("model.filename must be a bare .gguf file name")
        if not isinstance(model["license"], str) or not model["license"].strip():
            blockers.append("model.license must be read back")
        for field in ("license_evidence_url", "source_url"):
            if not isinstance(model[field], str) or not model[field].startswith("https://"):
                blockers.append(f"model.{field} must be an https URL")
        dimensions = model["embedding_dimensions"]
        if type(dimensions) is not int or not 1 <= dimensions <= 1024:
            blockers.append("model.embedding_dimensions must be between 1 and 1024")

    runtime = _section(document, "runtime", RUNTIME_KEYS, blockers)
    if runtime:
        if runtime["device"] != "cpu":
            blockers.append("runtime.device must be cpu")
        if runtime["network_download_at_runtime"] is not False:
            blockers.append("runtime must never download at runtime")
        if runtime["offline_flag_required"] is not True:
            blockers.append("runtime must require its offline flag")
        if runtime["bind"] != "loopback":
            blockers.append("runtime must bind to loopback only")

    gate = _section(document, "activation_gate", GATE_KEYS, blockers)
    for key, value in gate.items():
        if value is not True:
            blockers.append(f"activation_gate.{key} must stay true")

    record = document.get("promotion_record")
    if not isinstance(record, str) or not PROMOTION_RECORD.fullmatch(record) or ".." in record:
        blockers.append("promotion_record must name a configs/runtime/*.promotion.json file")
    elif not (repository_root / record).is_file():
        blockers.append("promotion_record file is absent")
    return blockers


def synthetic_complete_lock() -> dict:
    """A fully read-back lock with synthetic values; it describes no real artifact."""

    return {
        "schema_version": "embedding-model-lock.v1",
        "status": ACTIVE_STATUS,
        "purpose": "local_rag_embedding_separate_from_core",
        "governance": {
            "decision": "D-028",
            "adr": "docs/architecture/adr-0007-rag-embedding-reranker-index.md",
            "adr_status": "accepted",
            "introduced_by_commit": "d7cc78c",
            "owner_ratification": "D-000",
        },
        "model": {
            "name": "Synthetic-Embedding",
            "quantization": "Q8_0",
            "embedding_dimensions": 1024,
            "repository": "example-publisher/synthetic-embedding",
            "revision": "b" * 40,
            "filename": "synthetic-embedding.gguf",
            "byte_size": 1,
            "sha256": "a" * 64,
            "license": "Synthetic-License",
            "license_claimed_by_commit": "Synthetic-License",
            "license_evidence_url": "https://example.invalid/license",
            "source_url": "https://example.invalid/model",
        },
        "runtime": {
            "name": "llama.cpp",
            "release_declared_by_unit": "synthetic",
            "device": "cpu",
            "network_download_at_runtime": False,
            "offline_flag_required": True,
            "bind": "loopback",
            "pooling": "last",
            "context_size": 8192,
        },
        "activation_gate": {key: True for key in sorted(GATE_KEYS)},
        "promotion_record": "configs/runtime/synthetic-embedding.promotion.json",
        "deployment_state": "verified_by_readback",
    }


class EmbeddingModelLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = load_lock(LOCK_PATH)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        record = self.root / "configs" / "runtime" / "synthetic-embedding.promotion.json"
        record.parent.mkdir(parents=True)
        record.write_text("{}\n", encoding="utf-8")

    def test_candidate_lock_is_refused_while_readback_is_pending(self) -> None:
        blockers = activation_blockers(self.document, repository_root=REPOSITORY_ROOT)
        for field in ("model.sha256", "model.byte_size", "model.revision"):
            with self.subTest(field=field):
                self.assertIn(f"{field} is pending", blockers)
        self.assertIn(f"status is not {ACTIVE_STATUS}", blockers)

    def test_candidate_lock_records_the_three_readback_fields_as_pending(self) -> None:
        for field in ("sha256", "byte_size", "revision"):
            with self.subTest(field=field):
                self.assertEqual(self.document["model"][field], "pending_raw_readback")
        self.assertTrue(self.document["status"].startswith("candidate"))
        self.assertNotEqual(self.document["status"], ACTIVE_STATUS)

    def test_complete_synthetic_lock_passes_the_same_check(self) -> None:
        self.assertEqual(activation_blockers(synthetic_complete_lock(), repository_root=self.root), [])

    def test_any_single_pending_field_blocks_activation(self) -> None:
        paths = [
            ("model", "sha256"), ("model", "byte_size"), ("model", "revision"),
            ("model", "repository"), ("model", "filename"), ("model", "license"),
            ("model", "license_evidence_url"), ("governance", "owner_ratification"),
            ("runtime", "pooling"), ("promotion_record",),
        ]
        for path in paths:
            with self.subTest(path=".".join(path)):
                document = synthetic_complete_lock()
                target = document
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = "pending_raw_readback"
                self.assertIn(f"{'.'.join(path)} is pending", activation_blockers(document, repository_root=self.root))

    def test_malformed_readback_values_are_refused(self) -> None:
        cases = {
            "sha256": ["A" * 64, "a" * 63, "g" * 64, 0],
            "byte_size": [0, -1, True, "1", 1.0],
            "revision": ["b" * 39, "B" * 40, "main"],
            "filename": ["models/synthetic.gguf", "synthetic.bin", ""],
            "repository": ["single-name", "a/b/c"],
            "embedding_dimensions": [0, 1025, True],
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    document = synthetic_complete_lock()
                    document["model"][field] = value
                    self.assertNotEqual(activation_blockers(document, repository_root=self.root), [])

    def test_activation_gate_flags_cannot_be_weakened_or_removed(self) -> None:
        for key in sorted(GATE_KEYS):
            with self.subTest(flag=key, change="false"):
                document = synthetic_complete_lock()
                document["activation_gate"][key] = False
                self.assertIn(f"activation_gate.{key} must stay true", activation_blockers(document, repository_root=self.root))
            with self.subTest(flag=key, change="removed"):
                document = synthetic_complete_lock()
                del document["activation_gate"][key]
                self.assertNotEqual(activation_blockers(document, repository_root=self.root), [])

    def test_runtime_policy_must_stay_offline_cpu_and_loopback(self) -> None:
        changes = {
            "device": "gpu",
            "network_download_at_runtime": True,
            "offline_flag_required": False,
            "bind": "all_interfaces",
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                document = synthetic_complete_lock()
                document["runtime"][field] = value
                self.assertNotEqual(activation_blockers(document, repository_root=self.root), [])
        runtime = self.document["runtime"]
        self.assertEqual(runtime["device"], "cpu")
        self.assertIs(runtime["network_download_at_runtime"], False)
        self.assertIs(runtime["offline_flag_required"], True)
        self.assertEqual(runtime["bind"], "loopback")

    def test_missing_or_escaping_promotion_record_is_refused(self) -> None:
        for value in (
            "configs/runtime/absent-embedding.promotion.json",
            "configs/runtime/../runtime/synthetic-embedding.promotion.json",
            "/configs/runtime/synthetic-embedding.promotion.json",
            "configs/other/synthetic-embedding.promotion.json",
        ):
            with self.subTest(value=value):
                document = synthetic_complete_lock()
                document["promotion_record"] = value
                self.assertNotEqual(activation_blockers(document, repository_root=self.root), [])

    def test_unexpected_or_missing_keys_are_refused(self) -> None:
        extra = synthetic_complete_lock()
        extra["model"]["mirror_url"] = "https://example.invalid/mirror"
        missing = synthetic_complete_lock()
        del missing["deployment_state"]
        for document in (extra, missing, [], "lock"):
            with self.subTest(document=type(document).__name__):
                self.assertNotEqual(activation_blockers(copy.deepcopy(document), repository_root=self.root), [])

    def test_lock_file_is_strict_json_without_internal_details(self) -> None:
        raw = LOCK_PATH.read_text(encoding="utf-8")
        self.assertIsNone(IPV4.search(raw))
        for marker in INTERNAL_PATH_MARKERS:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, raw)
        with tempfile.TemporaryDirectory() as directory:
            duplicate = Path(directory) / "duplicate.json"
            duplicate.write_text('{"status": "a", "status": "b"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_lock(duplicate)
            non_finite = Path(directory) / "non-finite.json"
            non_finite.write_text('{"byte_size": NaN}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_lock(non_finite)

    def test_governance_points_to_a_proposed_adr_with_a_unique_number(self) -> None:
        governance = self.document["governance"]
        self.assertEqual(governance["decision"], "D-028")
        self.assertEqual(governance["owner_ratification"], "pending_owner_decision")
        adr = REPOSITORY_ROOT / governance["adr"]
        self.assertTrue(adr.is_file())
        self.assertIn("Statut : **PROPOSÉ**", adr.read_text(encoding="utf-8"))
        numbers = [
            re.match(r"adr-(\d{4})-", path.name).group(1)
            for path in sorted((REPOSITORY_ROOT / "docs" / "architecture").glob("adr-*.md"))
        ]
        self.assertEqual(len(numbers), len(set(numbers)), "two ADR files share a number")
        self.assertEqual(adr.name.split("-")[1], "0007")


if __name__ == "__main__":
    unittest.main()
