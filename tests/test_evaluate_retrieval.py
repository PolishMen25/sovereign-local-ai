"""Tests for the offline retrieval evaluation harness.

Embedders here are deterministic test doubles. The loopback path is exercised
through a recording opener, so no test opens a socket. Non-loopback probes are
built at runtime from the documentation range of RFC 5737.
"""

import contextlib
import hashlib
import io
import json
import math
from pathlib import Path
import re
import socket
import subprocess
import sys
import unittest
from unittest import mock

from services.knowledge.hybrid_index import HybridKnowledgeIndex
from services.web.embed_client import QUERY_INSTRUCTION
from tests._temp_support import sovereign_temporary_directory
from tools import evaluate_retrieval as tool


PROJECT_ROOT = Path(__file__).parents[1]
GOLD_PATH = PROJECT_ROOT / "configs" / "knowledge" / "retrieval-eval.synthetic.jsonl"
TOOL_PATH = PROJECT_ROOT / "tools" / "evaluate_retrieval.py"
HYBRID_INDEX_PATH = PROJECT_ROOT / "services" / "knowledge" / "hybrid_index.py"
DIMENSIONS = 32


def hashed_vector(text: str) -> list[float]:
    vector = [0.0] * DIMENSIONS
    for word in re.findall(r"\w+", text.casefold()):
        vector[hashlib.sha256(word.encode("utf-8")).digest()[0] % DIMENSIONS] += 1.0
    vector[0] += 0.01
    return vector


class HashingEmbedder:
    """Deterministic bag-of-words double; not a model and not a benchmark."""

    def __init__(self) -> None:
        self.calls: list[bool] = []

    def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        self.calls.append(is_query)
        return hashed_vector(text)


class UnavailableEmbedder:
    def __init__(self, fail_after: int = 0) -> None:
        self.remaining = fail_after

    def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        if self.remaining <= 0:
            raise RuntimeError("embedding runtime is unavailable")
        self.remaining -= 1
        return hashed_vector(text)


class ScriptedEmbedder:
    def __init__(self, document_vector, query_vector=None) -> None:
        self.document_vector = document_vector
        self.query_vector = query_vector

    def embed(self, text: str, *, is_query: bool = False):
        if is_query and self.query_vector is not None:
            return self.query_vector
        return self.document_vector if not is_query else hashed_vector(text)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


class RecordingOpener:
    """Answers like a loopback embedding runtime and records every URL."""

    def __init__(self) -> None:
        self.urls: list[str] = []
        self.inputs: list[str] = []

    def open(self, outgoing, timeout=None):
        self.urls.append(outgoing.full_url)
        text = json.loads(outgoing.data)["input"]
        self.inputs.append(text)
        body = {"data": [{"embedding": hashed_vector(text), "index": 0}]}
        return FakeResponse(json.dumps(body).encode("utf-8"))


def gold_lines() -> list[dict]:
    return [json.loads(line) for line in GOLD_PATH.read_text(encoding="utf-8").splitlines()]


def jsonl(records: list[dict]) -> bytes:
    return "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records).encode("utf-8")


class RetrievalCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = sovereign_temporary_directory()
        self.root = Path(self._temporary.__enter__())
        self.work = self.root / "work"
        self.work.mkdir()

    def tearDown(self) -> None:
        self._temporary.__exit__(None, None, None)

    def evaluate(self, **arguments) -> dict:
        arguments.setdefault("gold_path", GOLD_PATH)
        arguments.setdefault("work_parent", self.work)
        if arguments.get("embedder") is not None:
            arguments.setdefault("embedder_label", "hashing-test-double")
        return tool.evaluate(**arguments)

    def write_gold(self, records: list[dict] | bytes) -> Path:
        path = self.root / "gold.jsonl"
        path.write_bytes(records if isinstance(records, bytes) else jsonl(records))
        return path

    def cli(self, arguments: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = tool.main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()


class GoldSetTests(unittest.TestCase):
    def test_synthetic_gold_set_is_valid_bilingual_and_self_consistent(self) -> None:
        gold = tool.parse_gold_set(GOLD_PATH.read_bytes())
        self.assertTrue(gold.synthetic)
        self.assertEqual({"fr", "en", "mul"}, {query.language for query in gold.queries})
        self.assertTrue(all(document.provenance_id.startswith("synthetic-") for document in gold.documents))
        self.assertTrue(all(tool.query_terms(query.query) for query in gold.queries))
        self.assertGreaterEqual(len(gold.documents), 20)
        self.assertGreaterEqual(len(gold.queries), 12)

    def test_production_constants_are_mirrored_exactly(self) -> None:
        source = HYBRID_INDEX_PATH.read_text(encoding="utf-8")
        self.assertIn("score = 0.45 * lexical_score + 0.55 * vector_score", source)
        self.assertIn(f"else {tool.HYBRID_LEXICAL_DEPTH}", source)
        self.assertEqual(0.45, tool.PRODUCTION_LEXICAL_PERCENT / 100)
        self.assertEqual(0.55, (100 - tool.PRODUCTION_LEXICAL_PERCENT) / 100)
        self.assertIn(tool.PRODUCTION_LEXICAL_PERCENT, tool.SWEEP_LEXICAL_PERCENTS)
        self.assertEqual((0, 100), (tool.SWEEP_LEXICAL_PERCENTS[0], tool.SWEEP_LEXICAL_PERCENTS[-1]))

    def test_query_metrics_match_a_hand_computed_case(self) -> None:
        metrics = tool.query_metrics(["d2", "d1", "d3"], {"d1": 3, "d3": 1}, (1, 3))
        self.assertEqual({"1": 0.0, "3": 1.0}, metrics["recall_at_k"])
        self.assertEqual(0.5, metrics["reciprocal_rank"])
        ideal = 7 / math.log2(2) + 1 / math.log2(3)
        self.assertAlmostEqual((7 / math.log2(3) + 1 / math.log2(4)) / ideal, metrics["ndcg_at_k"]["3"])
        self.assertEqual(0.0, metrics["ndcg_at_k"]["1"])
        missed = tool.query_metrics(["d9"], {"d1": 2}, (1,))
        self.assertEqual(0.0, missed["reciprocal_rank"])


class ThreeModeTests(RetrievalCase):
    def test_lexical_vector_and_hybrid_are_measured_with_a_parity_checked_sweep(self) -> None:
        embedder = HashingEmbedder()
        report = self.evaluate(embedder=embedder)
        gold = tool.parse_gold_set(GOLD_PATH.read_bytes())
        self.assertEqual(
            [False] * len(gold.documents) + [True] * len(gold.queries), embedder.calls
        )
        modes = report["modes"]
        for mode in ("lexical", "vector", "hybrid"):
            self.assertEqual("measured", modes[mode]["status"], mode)
            self.assertEqual(len(gold.queries), modes[mode]["overall"]["queries"])
            self.assertEqual({"fr", "en", "mul"}, set(modes[mode]["by_language"]))
            self.assertEqual(["1", "3", "5", "10"], list(modes[mode]["overall"]["recall_at_k"]))
        sweep = report["weight_sweep"]
        self.assertTrue(sweep["parity_with_hybrid_index"])
        weights = [point["lexical_weight"] for point in sweep["points"]]
        self.assertEqual([percent / 100 for percent in tool.SWEEP_LEXICAL_PERCENTS], weights)
        at_production = sweep["points"][weights.index(0.45)]
        self.assertEqual(modes["hybrid"]["overall"], at_production["overall"])
        self.assertEqual(modes["vector"]["overall"], sweep["points"][0]["overall"])
        self.assertEqual("available", report["embedder"]["state"])
        self.assertEqual(DIMENSIONS, report["embedder"]["dimensions"])
        self.assertFalse(report["embedder"]["model_identity_verified"])
        self.assertEqual("none_decided", report["thresholds"])

    def test_report_is_reproducible_hashed_and_content_free(self) -> None:
        first = tool.canonical_json_bytes(self.evaluate(embedder=HashingEmbedder()))
        second = tool.canonical_json_bytes(self.evaluate(embedder=HashingEmbedder()))
        self.assertEqual(first, second)
        report = json.loads(first)
        self.assertEqual(hashlib.sha256(GOLD_PATH.read_bytes()).hexdigest(), report["gold_set"]["sha256"])
        self.assertEqual(
            hashlib.sha256(HYBRID_INDEX_PATH.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
            report["retrieval_code"]["hybrid_index_sha256"],
        )
        self.assertRegex(report["embedder"]["vectors_sha256"], r"^[0-9a-f]{64}$")
        text = first.decode("utf-8")
        for fragment in ("quarantaine", "Restore drills", "carte graphique", str(self.work), "q-fr-001"):
            self.assertNotIn(fragment, text)
        self.assertEqual([], list(self.work.iterdir()))

    def test_lexical_only_command_line_report_is_stable(self) -> None:
        outputs = []
        for name in ("one.json", "two.json"):
            output = self.root / name
            code, stdout, stderr = self.cli(
                ["--gold", str(GOLD_PATH), "--output", str(output), "--work-dir", str(self.work)]
            )
            self.assertEqual(0, code, stderr)
            summary = json.loads(stdout)
            self.assertEqual("not_configured", summary["embedder_state"])
            self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), summary["report_sha256"])
            outputs.append(output.read_bytes())
        self.assertEqual(outputs[0], outputs[1])
        report = json.loads(outputs[0])
        self.assertEqual("measured", report["modes"]["lexical"]["status"])
        self.assertEqual("embedder_not_configured", report["modes"]["hybrid"]["reason"])

    def test_command_line_script_runs_without_an_embedder(self) -> None:
        output = self.root / "script.json"
        completed = subprocess.run(
            [sys.executable, "-B", str(TOOL_PATH), "--gold", str(GOLD_PATH), "--output", str(output),
             "--work-dir", str(self.work), "--k", "1", "--k", "6"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=120, check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual([1, 6], json.loads(output.read_text(encoding="utf-8"))["k_values"])


class FallbackAndRefusalTests(RetrievalCase):
    def test_unavailable_embedder_falls_back_to_lexical(self) -> None:
        baseline = self.evaluate()
        for embedder in (UnavailableEmbedder(), UnavailableEmbedder(fail_after=30)):
            with self.subTest(fail_after=embedder.remaining):
                report = self.evaluate(embedder=embedder)
                self.assertEqual("unavailable", report["embedder"]["state"])
                self.assertIsNone(report["embedder"]["vectors_sha256"])
                for mode in ("vector", "hybrid"):
                    self.assertEqual(
                        {"status": "unavailable", "reason": "embedder_unavailable", "fallback": "lexical"},
                        report["modes"][mode],
                    )
                self.assertEqual("unavailable", report["weight_sweep"]["status"])
                self.assertEqual(baseline["modes"]["lexical"], report["modes"]["lexical"])

    def test_invalid_vectors_are_refused(self) -> None:
        cases = {
            "non-finite": ScriptedEmbedder([1.0, float("nan")]),
            "infinite": ScriptedEmbedder([float("inf"), 1.0]),
            "norm must be finite": ScriptedEmbedder([1e308] * 4),
            "norm must be finite and non-zero": ScriptedEmbedder([0.0, 0.0]),
            "dimension is outside": ScriptedEmbedder([]),
            "too many": ScriptedEmbedder([1.0] * (tool.MAX_VECTOR_DIMENSIONS + 1)),
            "boolean": ScriptedEmbedder([True, 1.0]),
            "text": ScriptedEmbedder("1.0,2.0"),
            "missing": ScriptedEmbedder(None),
            "dimensions differ": ScriptedEmbedder([1.0] * DIMENSIONS, query_vector=[1.0] * 8),
        }
        expected = {
            "non-finite": "non-finite", "infinite": "non-finite",
            "norm must be finite": "norm must be finite", "norm must be finite and non-zero": "non-zero",
            "dimension is outside": "dimension is outside", "too many": "dimension is outside",
            "boolean": "non-numeric", "text": "list of numbers", "missing": "list of numbers",
            "dimensions differ": "dimensions differ",
        }
        for name, embedder in cases.items():
            with self.subTest(case=name), self.assertRaisesRegex(tool.EvaluationRefused, expected[name]):
                self.evaluate(embedder=embedder)
        self.assertEqual([], list(self.work.iterdir()))

    def test_sweep_that_diverges_from_production_is_refused(self) -> None:
        original = HybridKnowledgeIndex.search

        def reordered(index, query, *, query_embedding, limit=5):
            result = original(index, query, query_embedding=query_embedding, limit=limit)
            if query_embedding is not None and len(result["hits"]) > 1:
                result["hits"] = list(reversed(result["hits"]))
            return result

        with mock.patch.object(HybridKnowledgeIndex, "search", reordered), \
                self.assertRaisesRegex(tool.EvaluationRefused, "diverges from HybridKnowledgeIndex.search"):
            self.evaluate(embedder=HashingEmbedder())
        self.assertEqual([], list(self.work.iterdir()))

    def test_arguments_are_validated(self) -> None:
        cases = (
            ({"k_values": (0, 3)}, "every k"),
            ({"k_values": (3, 21)}, "every k"),
            ({"k_values": (3, 3)}, "unique"),
            ({"k_values": ()}, "k values are required"),
            ({"embedder": HashingEmbedder(), "embedder_label": "Bad Label"}, "embedder label"),
            ({"embedder": HashingEmbedder(), "embedder_kind": "remote"}, "embedder kind"),
            ({"gold_sha256": "f" * 64}, "pinned SHA-256"),
            ({"gold_sha256": "F" * 64}, "64 lowercase"),
            ({"work_parent": Path("absent-directory-for-test")}, "existing directory"),
        )
        for arguments, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(tool.EvaluationRefused, message):
                self.evaluate(**arguments)

    def test_existing_report_is_never_overwritten(self) -> None:
        output = self.root / "existing.json"
        output.write_bytes(b"keep\n")
        code, _stdout, stderr = self.cli(["--gold", str(GOLD_PATH), "--output", str(output)])
        self.assertEqual(1, code)
        self.assertIn("already exists", stderr)
        self.assertEqual(b"keep\n", output.read_bytes())


class MalformedGoldSetTests(RetrievalCase):
    def test_malformed_gold_sets_are_refused(self) -> None:
        lines = gold_lines()
        header, documents = lines[0], [line for line in lines if line["record_type"] == "document"]
        queries = [line for line in lines if line["record_type"] == "query"]
        document, query = documents[0], queries[0]

        def with_query(**changes) -> list[dict]:
            return [header, *documents, dict(query, **changes)]

        cases = {
            "line 1 must be the header": [document, header, query],
            "schema_version": [dict(header, schema_version="v0"), document, query],
            "document_id values must be unique": [header, document, document, query],
            "unknown document": with_query(relevant=[{"document_id": "absent-001", "grade": 1}]),
            "grade must be": with_query(relevant=[{"document_id": document["document_id"], "grade": 0}]),
            "grade must be an integer": with_query(relevant=[{"document_id": document["document_id"], "grade": True}]),
            "grade must be an integer from": with_query(relevant=[{"document_id": document["document_id"], "grade": 4}]),
            "invalid or repeated": with_query(relevant=[{"document_id": document["document_id"], "grade": 1}] * 2),
            "query_id values must be unique": [header, *documents, query, query],
            "synthetic- provenance_id": [header, dict(document, provenance_id="approved-knowledge-v1"), query],
            "outside the search bounds": with_query(query="a"),
            "language is invalid": with_query(language="de"),
            "document keys": [header, dict(document, url="x"), query],
            "document_id is invalid": [header, dict(document, document_id="bad id"), query],
            "record_type must be": [header, dict(document, record_type="note"), query],
            "at least one document and one query": [header, *documents],
        }
        for message, records in cases.items():
            path = self.write_gold(records)
            with self.subTest(case=message), self.assertRaisesRegex(tool.EvaluationRefused, message):
                self.evaluate(gold_path=path)
        raw_cases = {
            "not strict JSON": GOLD_PATH.read_bytes() + b'{"record_type":"query","record_type":"query"}\n',
            "byte order mark": b"\xef\xbb\xbf" + GOLD_PATH.read_bytes(),
            "not valid UTF-8": GOLD_PATH.read_bytes() + b"\xff\n",
            "size is outside": b"",
        }
        for message, payload in raw_cases.items():
            path = self.write_gold(payload)
            with self.subTest(case=message), self.assertRaisesRegex(tool.EvaluationRefused, message):
                self.evaluate(gold_path=path)


class LoopbackTests(RetrievalCase):
    def test_non_loopback_endpoints_are_refused_before_any_connection(self) -> None:
        documentation_address = ".".join(["192", "0", "2", "10"])
        endpoints = (
            f"http://{documentation_address}:8082",
            "http://localhost:8082",
            "https://127.0.0.1:8082",
            "http://127.0.0.1",
            "http://127.0.0.1:8082/v1",
            "http://127.0.0.2:8082",
            "http://user@127.0.0.1:8082",
        )
        refused = AssertionError("network access attempted")
        with mock.patch.object(socket, "socket", side_effect=refused), \
                mock.patch.object(socket, "create_connection", side_effect=refused), \
                mock.patch.object(socket, "getaddrinfo", side_effect=refused):
            for endpoint in endpoints:
                with self.subTest(endpoint=endpoint), self.assertRaises(tool.EvaluationRefused):
                    tool.LoopbackEmbedder(endpoint)
                output = self.root / "refused.json"
                code, _stdout, _stderr = self.cli(
                    ["--gold", str(GOLD_PATH), "--output", str(output), "--embed-endpoint", endpoint,
                     "--embedder-label", "qwen3-embedding"]
                )
                self.assertEqual(1, code)
                self.assertFalse(output.exists())

    def test_endpoint_and_label_go_together(self) -> None:
        code, _stdout, stderr = self.cli(
            ["--gold", str(GOLD_PATH), "--output", str(self.root / "x.json"),
             "--embed-endpoint", "http://127.0.0.1:8082"]
        )
        self.assertEqual(1, code)
        self.assertIn("together", stderr)

    def test_loopback_embedder_only_calls_the_loopback_runtime(self) -> None:
        opener = RecordingOpener()
        embedder = tool.LoopbackEmbedder("http://127.0.0.1:8082", opener=opener)
        report = self.evaluate(embedder=embedder, embedder_kind="loopback", embedder_label="qwen3-embedding")
        gold = tool.parse_gold_set(GOLD_PATH.read_bytes())
        self.assertEqual(len(gold.documents) + len(gold.queries), len(opener.urls))
        self.assertEqual({"http://127.0.0.1:8082/v1/embeddings"}, set(opener.urls))
        self.assertEqual(len(gold.queries), sum(text.startswith(QUERY_INSTRUCTION) for text in opener.inputs))
        self.assertEqual("loopback", report["embedder"]["kind"])
        self.assertEqual("measured", report["modes"]["hybrid"]["status"])
        tool.LoopbackEmbedder("http://[::1]:8082", opener=RecordingOpener())

    def test_evaluation_opens_no_socket(self) -> None:
        refused = AssertionError("network access attempted")
        with mock.patch.object(socket, "socket", side_effect=refused), \
                mock.patch.object(socket, "create_connection", side_effect=refused), \
                mock.patch.object(socket, "getaddrinfo", side_effect=refused):
            report = self.evaluate(embedder=HashingEmbedder())
        self.assertTrue(report["weight_sweep"]["parity_with_hybrid_index"])


if __name__ == "__main__":
    unittest.main()
