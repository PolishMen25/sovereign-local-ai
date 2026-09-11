import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools import build_core_increment_from_arena as bridge

SUITE = {
    "tasks": [
        {"id": "python-01-double", "function_name": "double", "prompt": "Write double(x) that returns 2 * x.", "test_source": "assert True\n"},
        {"id": "python-02-upper", "function_name": "upper", "prompt": "Write upper(t) that upper-cases t.", "test_source": "assert True\n"},
    ]
}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class BuildIncrementTests(unittest.TestCase):
    def setUp(self) -> None:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = Path(d.name)
        self.suite = self.root / "suite.json"
        self.suite.write_text(json.dumps(SUITE), encoding="utf-8")
        self.raw = self.root / "raw"

    def write_packet(self, packet_id: str, solutions: list[dict], *, approve: bool = True, tamper: bool = False) -> Path:
        packet = self.root / "packets" / packet_id
        packet.mkdir(parents=True)
        body = "".join(json.dumps(s, sort_keys=True, separators=(",", ":")) + "\n" for s in solutions)
        (packet / "solutions.jsonl").write_text(body, encoding="utf-8")
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        (packet / "manifest.json").write_text(json.dumps({"packet_id": packet_id, "solutions_sha256": digest}), encoding="utf-8")
        if approve:
            approval_digest = "0" * 64 if tamper else digest
            (packet / "approval.json").write_text(json.dumps({
                "schema_version": "arena-approval.v1", "kind": "packet", "target_id": packet_id,
                "target_sha256": approval_digest, "approved_by": "victor"}), encoding="utf-8")
        return packet

    def solution(self, task_id: str, source: str) -> dict:
        return {"task_id": task_id, "source": source, "source_sha256": sha(source),
                "profile_id": "author-direct", "engine": "QWEN-CODER", "attempt": 1}

    def test_builds_records_and_manifest_from_an_approved_packet(self) -> None:
        packet = self.write_packet("arena-p1", [
            self.solution("python-01-double", "def double(x):\n    return 2 * x"),
            self.solution("python-02-upper", "def upper(t):\n    return t.upper()"),
        ])
        increment = bridge.build(packet, self.suite, self.raw)
        self.assertEqual((increment["lifecycle_state"], increment["classification"]), ("RAW", "synthetic"))
        self.assertEqual(increment["record_count"], 2)
        self.assertEqual(increment["training_authorization"], "not_approved")
        out = self.raw / "arena-arena-p1"
        lines = [json.loads(l) for l in (out / "records.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(lines), 2)
        self.assertIn("### Instruction", lines[0]["text"])
        self.assertIn("def double", lines[0]["text"])
        self.assertEqual(increment["content_sha256"], hashlib.sha256((out / "records.jsonl").read_bytes()).hexdigest())

    def test_deduplicates_identical_solutions(self) -> None:
        same = "def double(x):\n    return 2 * x"
        packet = self.write_packet("arena-p2", [self.solution("python-01-double", same), self.solution("python-01-double", same)])
        increment = bridge.build(packet, self.suite, self.raw)
        self.assertEqual(increment["record_count"], 1)

    def test_refuses_unapproved_packet(self) -> None:
        packet = self.write_packet("arena-p3", [self.solution("python-01-double", "def double(x):\n    return 2 * x")], approve=False)
        with self.assertRaisesRegex(bridge.IncrementRefused, "approved in the gateway"):
            bridge.build(packet, self.suite, self.raw)

    def test_refuses_digest_mismatch(self) -> None:
        packet = self.write_packet("arena-p4", [self.solution("python-01-double", "def double(x):\n    return 2 * x")], tamper=True)
        with self.assertRaisesRegex(bridge.IncrementRefused, "approval digest"):
            bridge.build(packet, self.suite, self.raw)

    def test_refuses_tampered_solutions_file(self) -> None:
        packet = self.write_packet("arena-p5", [self.solution("python-01-double", "def double(x):\n    return 2 * x")])
        (packet / "solutions.jsonl").write_text("garbage\n", encoding="utf-8")
        with self.assertRaisesRegex(bridge.IncrementRefused, "does not match the approved digest"):
            bridge.build(packet, self.suite, self.raw)

    def test_refuses_task_not_in_suite(self) -> None:
        packet = self.write_packet("arena-p6", [self.solution("python-99-unknown", "def f():\n    return 1")])
        with self.assertRaisesRegex(bridge.IncrementRefused, "not in the suite"):
            bridge.build(packet, self.suite, self.raw)

    def test_never_writes_outside_raw_root(self) -> None:
        packet = self.write_packet("arena-p7", [self.solution("python-01-double", "def double(x):\n    return 2 * x")])
        bridge.build(packet, self.suite, self.raw)
        written = [p for p in self.raw.rglob("*") if p.is_file()]
        self.assertTrue(all(str(p).startswith(str(self.raw)) for p in written))
        self.assertEqual({p.name for p in written}, {"records.jsonl", "manifest.json"})


if __name__ == "__main__":
    unittest.main()
