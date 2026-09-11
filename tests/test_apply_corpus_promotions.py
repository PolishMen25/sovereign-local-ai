import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools import apply_corpus_promotions as applier
from tools import promote_arena_increment as promote


class ApplyCorpusPromotionsTests(unittest.TestCase):
    def setUp(self) -> None:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = Path(d.name)
        self.raw = self.root / "raw"
        self.validated = self.root / "validated"
        self.inbox = self.root / "inbox"
        self.inbox.mkdir()

    def make_increment(self, increment_id: str) -> str:
        body = json.dumps({"record_id": f"{increment_id}-0000", "text": "x"}, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        digest = hashlib.sha256(body).hexdigest()
        directory = self.raw / f"dir-{increment_id}"  # dir name intentionally != increment_id
        directory.mkdir(parents=True)
        (directory / "records.jsonl").write_bytes(body)
        (directory / "manifest.json").write_text(json.dumps({
            "schema_version": promote.INCREMENT_SCHEMA, "increment_id": increment_id,
            "lifecycle_state": "RAW", "record_count": 1, "content_sha256": digest,
            "max_share_in_corpus_increment": 0.20, "training_authorization": "not_approved",
        }), encoding="utf-8")
        return digest

    def drop_approval(self, name: str, increment_id: str, digest: str) -> None:
        (self.inbox / name).write_text(json.dumps({
            "schema_version": promote.APPROVAL_SCHEMA, "kind": "increment",
            "target_id": increment_id, "target_sha256": digest, "approved_by": "victor",
        }), encoding="utf-8")

    def test_applies_a_matching_approval_and_files_it(self) -> None:
        digest = self.make_increment("corpus-arena-a")
        self.drop_approval("a.json", "corpus-arena-a", digest)
        outcomes = applier.apply_inbox(self.inbox, self.raw, self.validated)
        self.assertEqual(outcomes[0]["outcome"], "applied")
        self.assertTrue((self.validated / "corpus-arena-a" / "manifest.json").is_file())
        self.assertTrue((self.inbox / "processed" / "a.applied.json").is_file())
        self.assertFalse((self.inbox / "a.json").exists())

    def test_refuses_unknown_increment(self) -> None:
        self.drop_approval("b.json", "corpus-arena-missing", "0" * 64)
        outcomes = applier.apply_inbox(self.inbox, self.raw, self.validated)
        self.assertEqual(outcomes[0]["outcome"], "refused")
        self.assertTrue((self.inbox / "processed" / "b.refused.json").is_file())

    def test_refuses_digest_mismatch(self) -> None:
        self.make_increment("corpus-arena-c")
        self.drop_approval("c.json", "corpus-arena-c", "0" * 64)
        outcomes = applier.apply_inbox(self.inbox, self.raw, self.validated)
        self.assertEqual(outcomes[0]["outcome"], "refused")
        self.assertFalse((self.validated / "corpus-arena-c").exists())


if __name__ == "__main__":
    unittest.main()
