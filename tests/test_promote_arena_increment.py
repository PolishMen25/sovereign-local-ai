import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools import promote_arena_increment as promote


def sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


class PromoteArenaIncrementTests(unittest.TestCase):
    def setUp(self) -> None:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = Path(d.name)
        self.validated = self.root / "validated"

    def write_increment(self, increment_id: str, *, records: list[dict] | None = None, state: str = "RAW") -> tuple[Path, str]:
        rows = records or [{"record_id": f"{increment_id}-0000", "text": "### Instruction\ndouble\n\n### Réponse\n```python\ndef double(x):\n    return 2 * x\n```\n"}]
        body = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for r in rows).encode("utf-8")
        digest = sha(body)
        directory = self.root / "raw" / increment_id
        directory.mkdir(parents=True)
        (directory / "records.jsonl").write_bytes(body)
        (directory / "manifest.json").write_text(json.dumps({
            "schema_version": promote.INCREMENT_SCHEMA,
            "increment_id": increment_id,
            "lifecycle_state": state,
            "classification": "synthetic",
            "record_count": len(rows),
            "content_sha256": digest,
            "max_share_in_corpus_increment": 0.20,
            "training_authorization": "not_approved",
        }), encoding="utf-8")
        return directory, digest

    def approval(self, increment_id: str, digest: str, *, by: str = "victor") -> Path:
        path = self.root / f"approval-{increment_id}.json"
        path.write_text(json.dumps({
            "schema_version": promote.APPROVAL_SCHEMA, "kind": "increment",
            "target_id": increment_id, "target_sha256": digest, "approved_by": by,
        }), encoding="utf-8")
        return path

    def test_promotes_an_approved_increment(self) -> None:
        directory, digest = self.write_increment("corpus-arena-p1")
        approval = self.approval("corpus-arena-p1", digest)
        result = promote.promote(directory, approval, self.validated)
        self.assertEqual((result["lifecycle_state"], result["training_authorization"]), ("VALIDATED", "approved"))
        self.assertEqual(result["approved_by"], "victor")
        self.assertEqual(result["max_share_in_corpus_increment"], 0.20)
        out = self.validated / "corpus-arena-p1"
        self.assertEqual((out / "records.jsonl").read_bytes(), (directory / "records.jsonl").read_bytes())
        self.assertTrue((out / "approval.json").is_file())
        self.assertEqual(result["content_sha256"], digest)

    def test_refuses_without_approval_match(self) -> None:
        directory, digest = self.write_increment("corpus-arena-p2")
        bad = self.approval("corpus-arena-p2", "0" * 64)
        with self.assertRaisesRegex(promote.PromotionRefused, "approval digest"):
            promote.promote(directory, bad, self.validated)

    def test_refuses_wrong_increment_id(self) -> None:
        directory, digest = self.write_increment("corpus-arena-p3")
        other = self.approval("corpus-arena-OTHER", digest)
        with self.assertRaisesRegex(promote.PromotionRefused, "increment id"):
            promote.promote(directory, other, self.validated)

    def test_refuses_tampered_records(self) -> None:
        directory, digest = self.write_increment("corpus-arena-p4")
        approval = self.approval("corpus-arena-p4", digest)
        (directory / "records.jsonl").write_text("garbage\n", encoding="utf-8")
        with self.assertRaisesRegex(promote.PromotionRefused, "content digest"):
            promote.promote(directory, approval, self.validated)

    def test_refuses_non_raw_increment(self) -> None:
        directory, digest = self.write_increment("corpus-arena-p5", state="VALIDATED")
        approval = self.approval("corpus-arena-p5", digest)
        with self.assertRaisesRegex(promote.PromotionRefused, "not RAW"):
            promote.promote(directory, approval, self.validated)

    def test_refuses_double_promotion(self) -> None:
        directory, digest = self.write_increment("corpus-arena-p6")
        approval = self.approval("corpus-arena-p6", digest)
        promote.promote(directory, approval, self.validated)
        with self.assertRaisesRegex(promote.PromotionRefused, "already promoted"):
            promote.promote(directory, approval, self.validated)

    def test_never_writes_outside_validated_root(self) -> None:
        directory, digest = self.write_increment("corpus-arena-p7")
        approval = self.approval("corpus-arena-p7", digest)
        promote.promote(directory, approval, self.validated)
        written = [p for p in self.validated.rglob("*") if p.is_file()]
        self.assertTrue(all(str(p).startswith(str(self.validated)) for p in written))
        self.assertEqual({p.name for p in written}, {"records.jsonl", "manifest.json", "approval.json"})


if __name__ == "__main__":
    unittest.main()
