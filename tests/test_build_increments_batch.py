import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools import build_increments_for_approved_packets as batch


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class BatchBuildTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        self.packets = self.base / "packets"
        self.packets.mkdir()
        # raw root's share anchor must exist (require_share)
        self.raw_root = self.base / "raw" / "corpus" / "arena"
        (self.base / "raw").mkdir()
        self.suite = self.base / "suite.json"
        self.suite.write_text(json.dumps({"tasks": [{"id": "t1", "prompt": "Écris f()"}]}), encoding="utf-8")

    def _packet(self, packet_id: str, *, approved: bool, status: str = "awaiting_owner_approval") -> Path:
        packet = self.packets / packet_id
        packet.mkdir()
        solutions = json.dumps({"task_id": "t1", "source": "def f():\n    return 1\n"}) + "\n"
        body = solutions.encode("utf-8")
        (packet / "solutions.jsonl").write_bytes(body)
        (packet / "manifest.json").write_text(json.dumps({
            "packet_id": packet_id, "solutions_sha256": sha(body), "status": status,
            "solutions": 1, "unique_ratio": 0.95, "max_repetition": 0.01,
        }), encoding="utf-8")
        if approved:
            (packet / "approval.json").write_text(json.dumps({
                "schema_version": "arena-approval.v1", "kind": "packet",
                "target_id": packet_id, "target_sha256": sha(body),
            }), encoding="utf-8")
        return packet

    def test_builds_only_approved_packets(self):
        self._packet("p-approved", approved=True)
        self._packet("p-pending", approved=False)
        outcome = batch.run(self.packets, self.suite, self.raw_root, dry_run=False)
        self.assertEqual(len(outcome["built"]), 1)
        self.assertEqual(outcome["not_approved"], ["p-pending"])
        self.assertTrue((self.raw_root / "arena-p-approved").is_dir())
        self.assertFalse((self.raw_root / "arena-p-pending").exists())

    def test_is_idempotent(self):
        self._packet("p1", approved=True)
        batch.run(self.packets, self.suite, self.raw_root, dry_run=False)
        again = batch.run(self.packets, self.suite, self.raw_root, dry_run=False)
        self.assertEqual(again["built"], [])
        self.assertEqual(again["already"], ["p1"])

    def test_dry_run_writes_nothing(self):
        self._packet("p1", approved=True)
        outcome = batch.run(self.packets, self.suite, self.raw_root, dry_run=True)
        self.assertEqual(outcome["built"], [])
        self.assertFalse(self.raw_root.exists())

    def test_reports_health_and_approval(self):
        packet = self._packet("p1", approved=False, status="flagged")
        report = batch.packet_report(packet, self.raw_root)
        self.assertEqual((report["status"], report["approved"], report["built"]), ("flagged", False, False))
        self.assertEqual(report["unique_ratio"], 0.95)

    def test_refused_packet_does_not_stop_the_batch(self):
        good = self._packet("p-good", approved=True)
        broken = self._packet("p-broken", approved=True)
        (broken / "solutions.jsonl").write_bytes(b'{"task_id": "t1", "source": "x"}\n')  # digest no longer matches
        outcome = batch.run(self.packets, self.suite, self.raw_root, dry_run=False)
        self.assertEqual(len(outcome["built"]), 1)
        self.assertEqual(len(outcome["refused"]), 1)
        self.assertEqual(outcome["refused"][0]["packet_id"], "p-broken")
        self.assertTrue((self.raw_root / "arena-p-good").is_dir())
        self.assertTrue(good.is_dir())


if __name__ == "__main__":
    unittest.main()
