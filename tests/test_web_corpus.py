import json
import os
from pathlib import Path
import tempfile
import unittest

from services.web.app import WebState


def make_state(root: Path) -> WebState:
    raw = root / "raw"
    validated = root / "validated"
    inbox = root / "inbox"
    for d in (raw, validated, inbox):
        d.mkdir(parents=True, exist_ok=True)
    return WebState(None, None, None, None, None, "x" * 32, None, None, None, raw, validated, inbox)


def write_raw(raw: Path, increment_id: str) -> None:
    directory = raw / f"dir-{increment_id}"
    directory.mkdir(parents=True)
    (directory / "records.jsonl").write_text("{}\n", encoding="utf-8")
    (directory / "manifest.json").write_text(json.dumps({
        "schema_version": "arena-corpus-increment.v1", "increment_id": increment_id,
        "lifecycle_state": "RAW", "classification": "synthetic", "record_count": 1,
        "content_sha256": "a" * 64, "max_share_in_corpus_increment": 0.20,
        "arena_packet_id": "arena-p", "training_authorization": "not_approved",
    }), encoding="utf-8")


class WebCorpusTests(unittest.TestCase):
    def setUp(self) -> None:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = Path(d.name)
        self.state = make_state(self.root)

    def test_lists_increments_with_promotion_status(self) -> None:
        write_raw(self.root / "raw", "corpus-arena-a")
        write_raw(self.root / "raw", "corpus-arena-b")
        (self.root / "validated" / "corpus-arena-a").mkdir()
        result = self.state.corpus_increments()
        self.assertTrue(result["available"])
        by_id = {i["increment_id"]: i for i in result["increments"]}
        self.assertEqual(by_id["corpus-arena-a"]["status"], "validated")
        self.assertEqual(by_id["corpus-arena-b"]["status"], "raw")
        self.assertEqual(by_id["corpus-arena-b"]["record_count"], 1)

    def test_records_a_group_readable_approval(self) -> None:
        approval = {
            "schema_version": "arena-increment-approval.v1", "kind": "increment",
            "target_id": "corpus-arena-a", "target_sha256": "a" * 64, "approved_by": "victor",
            "approved_at": "2026-09-11T15:00:00Z",
        }
        self.state.record_corpus_approval(approval)
        files = list((self.root / "inbox").glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(oct(files[0].stat().st_mode & 0o777), "0o640")
        self.assertEqual(json.loads(files[0].read_text())["target_id"], "corpus-arena-a")

    def test_unavailable_when_raw_root_missing(self) -> None:
        self.state.corpus_raw_root = self.root / "nope"
        self.assertEqual(self.state.corpus_increments(), {"available": False, "increments": []})


if __name__ == "__main__":
    unittest.main()
