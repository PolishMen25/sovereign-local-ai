import tempfile
import unittest
from pathlib import Path

from services.web import health


class FakeRuntime:
    def __init__(self, status):
        self._status = status

    def status(self):
        if isinstance(self._status, Exception):
            raise self._status
        return self._status


class FakeState:
    def __init__(self, **kwargs):
        self.runtime = kwargs.get("runtime")
        self.qwen_runtime = kwargs.get("qwen_runtime")
        self.embed_runtime = kwargs.get("embed_runtime")
        self.core_runtime = kwargs.get("core_runtime")
        self.knowledge = kwargs.get("knowledge")
        self.workspace_dir = kwargs.get("workspace_dir")
        self.tools_enabled = kwargs.get("tools_enabled", True)

    def arena_overview(self):
        return {"available": True, "matches": 12}

    def corpus_increments(self):
        return {"available": True, "increments": [{"status": "validated"}, {"status": "raw"}]}


class FakeKnowledge:
    def status(self):
        return {"ready": True, "documents": 413, "mode": "hybrid"}


class ResourcesTests(unittest.TestCase):
    def test_parses_meminfo_and_loadavg(self):
        with tempfile.TemporaryDirectory() as tmp:
            meminfo = Path(tmp) / "meminfo"
            meminfo.write_text("MemTotal:       1024 kB\nMemAvailable:    512 kB\nOther: 1\n", encoding="utf-8")
            loadavg = Path(tmp) / "loadavg"
            loadavg.write_text("1.50 2.00 3.25 1/200 1234\n", encoding="utf-8")
            snapshot = health.resources(Path(tmp), meminfo=meminfo, loadavg=loadavg)
        self.assertEqual(snapshot["memory"]["total_bytes"], 1024 * 1024)
        self.assertEqual(snapshot["memory"]["used_percent"], 50.0)
        self.assertEqual(snapshot["load"], [1.5, 2.0, 3.25])
        self.assertIn("disk", snapshot)

    def test_missing_files_degrade(self):
        snapshot = health.resources(None, meminfo=Path("/nonexistent"), loadavg=Path("/nonexistent"))
        self.assertEqual(snapshot, {"load": []})


class SnapshotTests(unittest.TestCase):
    def test_collects_every_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = FakeState(
                runtime=FakeRuntime({"available": True, "state": "ready"}),
                qwen_runtime=FakeRuntime({"available": False, "state": "unavailable"}),
                embed_runtime=None,
                core_runtime=FakeRuntime(RuntimeError("boom")),
                knowledge=FakeKnowledge(),
                workspace_dir=Path(tmp),
            )
            snapshot = health.snapshot(state, state_root=Path(tmp), sandbox_available=True)
        engines = {row["engine"]: row for row in snapshot["engines"]}
        self.assertTrue(engines["CHAT-14B"]["available"])
        self.assertFalse(engines["QWEN-CODER"]["available"])
        self.assertEqual(engines["EMBED"]["state"], "non configuré")
        self.assertEqual(engines["CORE-700M"]["state"], "injoignable")  # a raising probe never breaks the page
        self.assertEqual(snapshot["knowledge"], {"ready": True, "documents": 413, "mode": "hybrid"})
        self.assertEqual(snapshot["arena"]["matches"], 12)
        self.assertEqual((snapshot["corpus"]["total"], snapshot["corpus"]["validated"]), (2, 1))
        self.assertTrue(snapshot["workspace"]["configured"])
        self.assertTrue(snapshot["actions"]["sandbox"])

    def test_survives_a_broken_state(self):
        class Broken(FakeState):
            def arena_overview(self):
                raise RuntimeError("nope")

            def corpus_increments(self):
                raise RuntimeError("nope")

        state = Broken(knowledge=FakeRuntime(RuntimeError("nope")))
        snapshot = health.snapshot(state)
        self.assertFalse(snapshot["arena"]["available"])
        self.assertFalse(snapshot["corpus"]["available"])
        self.assertFalse(snapshot["knowledge"]["ready"])


if __name__ == "__main__":
    unittest.main()
