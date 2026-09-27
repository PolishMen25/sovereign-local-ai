import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools import build_core_increment_from_arena as bridge

REPO = Path(__file__).resolve().parents[1]
PRACTICE_SUITE = REPO / "configs" / "arena" / "practice-suite.v1.json"
SEALED_E2_SUITE = REPO / "configs" / "evaluation" / "core-python-e2.candidate.json"

SUITE = {
    "schema_version": "arena-practice-suite.v1",
    "tasks": [
        {"id": "arena-001-double", "function_name": "double", "prompt": "Write double(x) that returns 2 * x.", "test_source": "assert True\n"},
        {"id": "arena-002-upper", "function_name": "upper", "prompt": "Write upper(t) that upper-cases t.", "test_source": "assert True\n"},
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
        # Exact bytes: the digest below is taken over this string, on every platform.
        (packet / "solutions.jsonl").write_bytes(body.encode("utf-8"))
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
            self.solution("arena-001-double", "def double(x):\n    return 2 * x"),
            self.solution("arena-002-upper", "def upper(t):\n    return t.upper()"),
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
        packet = self.write_packet("arena-p2", [self.solution("arena-001-double", same), self.solution("arena-001-double", same)])
        increment = bridge.build(packet, self.suite, self.raw)
        self.assertEqual(increment["record_count"], 1)

    def test_refuses_unapproved_packet(self) -> None:
        packet = self.write_packet("arena-p3", [self.solution("arena-001-double", "def double(x):\n    return 2 * x")], approve=False)
        with self.assertRaisesRegex(bridge.IncrementRefused, "approved in the gateway"):
            bridge.build(packet, self.suite, self.raw)

    def test_refuses_digest_mismatch(self) -> None:
        packet = self.write_packet("arena-p4", [self.solution("arena-001-double", "def double(x):\n    return 2 * x")], tamper=True)
        with self.assertRaisesRegex(bridge.IncrementRefused, "approval digest"):
            bridge.build(packet, self.suite, self.raw)

    def test_refuses_tampered_solutions_file(self) -> None:
        packet = self.write_packet("arena-p5", [self.solution("arena-001-double", "def double(x):\n    return 2 * x")])
        (packet / "solutions.jsonl").write_text("garbage\n", encoding="utf-8")
        with self.assertRaisesRegex(bridge.IncrementRefused, "does not match the approved digest"):
            bridge.build(packet, self.suite, self.raw)

    def test_refuses_task_not_in_suite(self) -> None:
        packet = self.write_packet("arena-p6", [self.solution("arena-999-unknown", "def f():\n    return 1")])
        with self.assertRaisesRegex(bridge.IncrementRefused, "not in the suite"):
            bridge.build(packet, self.suite, self.raw)

    def test_manifest_records_the_suite_sha256(self) -> None:
        packet = self.write_packet("arena-p8", [self.solution("arena-001-double", "def double(x):\n    return 2 * x")])
        increment = bridge.build(packet, self.suite, self.raw)
        expected = hashlib.sha256(self.suite.read_bytes()).hexdigest()
        self.assertEqual(increment["task_suite_sha256"], expected)
        on_disk = json.loads((self.raw / "arena-arena-p8" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["task_suite_sha256"], expected)

    def test_refuses_the_sealed_e2_schema_whatever_the_file_name(self) -> None:
        sealed = dict(SUITE, schema_version="core-code-evaluation-suite.v1")
        self.suite.write_text(json.dumps(sealed), encoding="utf-8")
        packet = self.write_packet("arena-p9", [self.solution("arena-001-double", "def double(x):\n    return 2 * x")])
        with self.assertRaisesRegex(bridge.IncrementRefused, "sealed evaluation suite"):
            bridge.build(packet, self.suite, self.raw)
        self.assertFalse(self.raw.exists())

    def test_refuses_the_versioned_e2_suite(self) -> None:
        with self.assertRaisesRegex(bridge.IncrementRefused, "sealed evaluation suite"):
            bridge.load_task_suite(SEALED_E2_SUITE)

    def test_refuses_a_suite_holding_an_e2_task_id(self) -> None:
        mixed = {"tasks": SUITE["tasks"] + [{"id": "python-07-leak", "prompt": "Write leak().", "test_source": "assert True\n"}]}
        self.suite.write_text(json.dumps(mixed), encoding="utf-8")
        with self.assertRaisesRegex(bridge.IncrementRefused, "python-07-leak belongs to the sealed evaluation suite"):
            bridge.load_task_suite(self.suite)

    def test_refuses_a_packet_holding_an_e2_solution(self) -> None:
        packet = self.write_packet("arena-p10", [
            self.solution("arena-001-double", "def double(x):\n    return 2 * x"),
            self.solution("python-01-reverse-text", "def reverse_text(value):\n    return value[::-1]"),
        ])
        with self.assertRaisesRegex(bridge.IncrementRefused, "sealed evaluation task python-01-reverse-text"):
            bridge.build(packet, self.suite, self.raw)
        self.assertFalse(self.raw.exists())

    def test_refuses_a_packet_holding_a_solution_for_an_e2_overlapping_task(self) -> None:
        overlapping = {"id": "arena-017-clamp", "function_name": "clamp",
                       "prompt": "Write clamp(x, lo, hi) bounding x.", "test_source": "assert True\n"}
        self.suite.write_text(json.dumps(dict(SUITE, tasks=SUITE["tasks"] + [overlapping])), encoding="utf-8")
        packet = self.write_packet("arena-p11", [
            self.solution("arena-001-double", "def double(x):\n    return 2 * x"),
            self.solution("arena-017-clamp", "def clamp(x, lo, hi):\n    return max(lo, min(hi, x))"),
        ])
        with self.assertRaisesRegex(bridge.IncrementRefused, "arena-017-clamp refused: function clamp .*D-040"):
            bridge.build(packet, self.suite, self.raw)
        self.assertFalse(self.raw.exists())
        clean = self.write_packet("arena-p12", [self.solution("arena-001-double", "def double(x):\n    return 2 * x")])
        self.assertEqual(1, bridge.build(clean, self.suite, self.raw)["record_count"])

    def test_refuses_everything_when_the_sealed_suite_cannot_be_read(self) -> None:
        packet = self.write_packet("arena-p13", [self.solution("arena-001-double", "def double(x):\n    return 2 * x")])
        broken = self.root / "e2.json"
        for name, payload in (("missing", None), ("not json", b"{not json"), ("nested", b"[" * 100_000),
                              ("no function name", json.dumps({"schema_version": bridge.SEALED_SUITE_SCHEMA,
                                                                "tasks": [{"id": "python-01-x"}]}).encode("utf-8")),
                              ("wrong schema", json.dumps({"schema_version": "other",
                                                           "tasks": [{"function_name": "x"}]}).encode("utf-8"))):
            with self.subTest(name=name):
                if payload is None:
                    broken.unlink(missing_ok=True)
                else:
                    broken.write_bytes(payload)
                with self.assertRaisesRegex(bridge.IncrementRefused, "D-040 overlap cannot be checked"):
                    bridge.build(packet, self.suite, self.raw, sealed_path=broken)
                self.assertFalse(self.raw.exists())

    def test_default_practice_suite_withholds_every_e2_overlapping_task(self) -> None:
        _, _, withheld = bridge.load_task_suite(PRACTICE_SUITE)
        sealed = {task["function_name"] for task in json.loads(SEALED_E2_SUITE.read_text(encoding="utf-8"))["tasks"]}
        practice = json.loads(PRACTICE_SUITE.read_text(encoding="utf-8"))["tasks"]
        self.assertEqual(withheld, {task["id"]: task["function_name"] for task in practice if task["function_name"] in sealed})
        self.assertEqual("clamp", withheld["arena-017-clamp"])
        self.assertEqual(14, len(withheld))

    def test_refuses_a_malformed_suite(self) -> None:
        for document in ([], {"tasks": []}, {"tasks": [{"id": "arena-001-double"}]}, {"tasks": [{"id": 7, "prompt": "x"}]},
                         {"tasks": [{"id": "arena-001-double", "prompt": "x"}]},
                         {"tasks": [{"id": "arena-001-double", "prompt": "x", "function_name": "not a name"}]}):
            with self.subTest(document=document):
                self.suite.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaisesRegex(bridge.IncrementRefused, "malformed"):
                    bridge.load_task_suite(self.suite)

    def test_default_suite_is_the_practice_suite(self) -> None:
        self.assertEqual(bridge.build_parser().parse_args(["packet"]).suite, Path("configs/arena/practice-suite.v1.json"))
        self.assertEqual(REPO / bridge.DEFAULT_SUITE, PRACTICE_SUITE)
        prompts, digest, _ = bridge.load_task_suite(PRACTICE_SUITE)
        self.assertGreaterEqual(len(prompts), 50)
        self.assertTrue(all(task_id.startswith("arena-") for task_id in prompts))
        self.assertEqual(digest, hashlib.sha256(PRACTICE_SUITE.read_bytes()).hexdigest())

    def test_never_writes_outside_raw_root(self) -> None:
        packet = self.write_packet("arena-p7", [self.solution("arena-001-double", "def double(x):\n    return 2 * x")])
        bridge.build(packet, self.suite, self.raw)
        written = [p for p in self.raw.rglob("*") if p.is_file()]
        self.assertTrue(all(str(p).startswith(str(self.raw)) for p in written))
        self.assertEqual({p.name for p in written}, {"records.jsonl", "manifest.json"})


if __name__ == "__main__":
    unittest.main()
