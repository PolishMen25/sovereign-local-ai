import json
import tempfile
import unittest
from pathlib import Path

from services.arena import league
from services.arena.store import ArenaStore
from tools import recheck_packet_health as recheck


class RecheckTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        self.packets = self.base / "packets"
        self.packets.mkdir()

    def _packet(self, packet_id: str, sources: list[tuple[str, str]], *, status: str, unique_ratio: float = 0.4) -> Path:
        packet = self.packets / packet_id
        packet.mkdir()
        body = "".join(json.dumps({"task_id": task, "source": source}, sort_keys=True) + "\n" for task, source in sources)
        (packet / "solutions.jsonl").write_text(body, encoding="utf-8")
        (packet / "manifest.json").write_text(json.dumps({
            "packet_id": packet_id, "solutions_sha256": league.sha256_text(body), "status": status,
            "solutions": len(sources), "metrics": {"unique_ratio": unique_ratio, "max_repetition": 0.01},
        }), encoding="utf-8")
        return packet

    def _clean_sources(self, count: int = 25) -> list[tuple[str, str]]:
        return [(f"t{i}", f"def f{i}():\n    return {i}\n") for i in range(count)]

    def test_a_clean_packet_flagged_by_the_old_gate_is_unblocked(self):
        self._packet("p-clean", self._clean_sources(), status="flagged")
        outcome = recheck.run(self.packets, None, apply=True)
        self.assertEqual(outcome["unblocked"], ["p-clean"])
        manifest = json.loads((self.packets / "p-clean" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "awaiting_owner_approval")
        self.assertEqual(manifest["metrics"]["unique_ratio"], 1.0)

    def test_dry_run_writes_nothing(self):
        self._packet("p-clean", self._clean_sources(), status="flagged")
        outcome = recheck.run(self.packets, None, apply=False)
        self.assertEqual(outcome["unblocked"], ["p-clean"])
        manifest = json.loads((self.packets / "p-clean" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "flagged")  # untouched

    def test_a_genuinely_collapsed_packet_stays_flagged(self):
        same = "def f():\n    return 1\n"
        sources = [(f"t{i}", same) for i in range(20)] + [(f"u{i}", f"def g{i}():\n    return {i}\n") for i in range(10)]
        self._packet("p-collapsed", sources, status="flagged")
        outcome = recheck.run(self.packets, None, apply=True)
        self.assertEqual(outcome["still_flagged"], ["p-collapsed"])
        manifest = json.loads((self.packets / "p-collapsed" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "flagged")

    def test_a_tampered_packet_is_skipped(self):
        packet = self._packet("p-tampered", self._clean_sources(), status="flagged")
        (packet / "solutions.jsonl").write_text('{"task_id": "t", "source": "x"}\n', encoding="utf-8")
        outcome = recheck.run(self.packets, None, apply=True)
        self.assertEqual(len(outcome["skipped"]), 1)
        self.assertEqual(outcome["skipped"][0]["packet_id"], "p-tampered")
        manifest = json.loads((packet / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "flagged")

    def test_an_approved_packet_is_never_touched(self):
        self._packet("p-approved", self._clean_sources(), status="approved")
        outcome = recheck.run(self.packets, None, apply=True)
        self.assertEqual(outcome["unchanged"], ["p-approved"])
        manifest = json.loads((self.packets / "p-approved" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "approved")

    def test_pool_metrics_are_not_invented_from_a_packed_packet(self):
        # The raw accepted pool is gone; recomputing it here would always say
        # 1.0. The tool must refuse to write that number rather than flatter.
        self._packet("p-clean", self._clean_sources(), status="flagged")
        recheck.run(self.packets, None, apply=True)
        manifest = json.loads((self.packets / "p-clean" / "manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("pool_unique_ratio", manifest["metrics"])
        self.assertNotIn("accepted", manifest["metrics"])
        self.assertIn("unavailable", manifest["metrics"]["pool_metrics"])
        self.assertEqual(manifest["metrics"]["distinct_tasks"], 25)

    def test_comments_do_not_count_as_diversity(self):
        # Same code, different comments: normalize_source must see one solution.
        sources = [(f"t{i}", f"# variant {i}\ndef f():\n    return 1\n") for i in range(30)]
        self._packet("p-comments", sources, status="flagged")
        outcome = recheck.run(self.packets, None, apply=True)
        self.assertEqual(outcome["still_flagged"], ["p-comments"])


class RestatePacketTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = ArenaStore(Path(directory.name) / "arena.sqlite3")
        self.store.initialize()

    def _insert(self, packet_id: str, status: str) -> None:
        self.store.record_packet({"packet_id": packet_id, "created_at": "2026-09-13T00:00:00Z", "path": "/tmp/p",
                                  "solutions_sha256": "a" * 64, "solutions": 30, "unique_ratio": 0.4,
                                  "max_repetition": 0.02, "status": status}, [])

    def test_updates_health_only(self):
        self._insert("p1", "flagged")
        ok = self.store.restate_packet("p1", "a" * 64, {"unique_ratio": 1.0, "max_repetition": 0.02},
                                       "awaiting_owner_approval")
        self.assertTrue(ok)
        packet = next(row for row in self.store.overview()["packets"] if row["packet_id"] == "p1")
        self.assertEqual((packet["status"], packet["unique_ratio"]), ("awaiting_owner_approval", 1.0))

    def test_refuses_an_approved_packet_and_a_wrong_digest(self):
        self._insert("p-approved", "approved")
        self._insert("p-flagged", "flagged")
        metrics = {"unique_ratio": 1.0, "max_repetition": 0.02}
        self.assertFalse(self.store.restate_packet("p-approved", "a" * 64, metrics, "awaiting_owner_approval"))
        self.assertFalse(self.store.restate_packet("p-flagged", "b" * 64, metrics, "awaiting_owner_approval"))
        self.assertFalse(self.store.restate_packet("p-missing", "a" * 64, metrics, "awaiting_owner_approval"))

    def test_cannot_be_used_to_approve(self):
        self._insert("p1", "flagged")
        with self.assertRaises(ValueError):
            self.store.restate_packet("p1", "a" * 64, {"unique_ratio": 1.0, "max_repetition": 0.0}, "approved")


if __name__ == "__main__":
    unittest.main()
