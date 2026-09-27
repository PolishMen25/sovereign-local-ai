import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import unittest
from unittest.mock import patch

from tests._temp_support import sovereign_temporary_directory
from tests.test_compare_core_mini_numa_evidence import (
    PROOF_A,
    PROOF_B,
    SAMPLES_A,
    SAMPLES_B,
    check_against_schema,
    encode,
    evidence,
)
from tools import compare_core_mini_numa_evidence as comparison
from tools import core_mini_numa_benchmark as benchmark
from tools import verify_core_mini_placement_distinctness as verifier


PROJECT_ROOT = Path(__file__).parents[1]
SCHEMA_ROOT = PROJECT_ROOT / "schemas"
REFUSAL_LINE = "CORE-MINI placement distinctness refused\n"
# Synthetic salts; the runner draws 32 random bytes per run.
SALT_A = bytes(range(32))
SALT_B = bytes(range(100, 132))
INPUT_KEYS = ("placement_a", "contract_a", "salt_a", "placement_b", "contract_b", "salt_b")


def contract(label: str, cpu_ids: list, allowed: list, policy: str, nodes: list) -> dict:
    return {
        "schema_version": "core-mini-private-placement.v1",
        "placement_id": label,
        "cpu_ids": cpu_ids,
        "allowed_memory_nodes": allowed,
        "memory_policy": policy,
        "policy_memory_nodes": nodes,
    }


def contract_a(**changes) -> dict:
    return contract("placement-a", [0, 1, 2, 3], [0], "bind", [0]) | changes


def contract_b(**changes) -> dict:
    return contract("placement-b", [4, 5, 6, 7], [1], "bind", [1]) | changes


def contract_bytes(document: dict) -> bytes:
    # Operator contracts need not be canonical: the runner hashes the exact
    # bytes it read, so the verifier must hash the same bytes, never a re-dump.
    return json.dumps(document, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def commitment(payload: bytes, salt: bytes) -> str:
    return benchmark._placement_contract_commitment(payload, salt)


def write_case(
    root: Path,
    *,
    payload_a: bytes | None = None,
    payload_b: bytes | None = None,
    salt_a: bytes = SALT_A,
    salt_b: bytes = SALT_B,
) -> dict[str, Path]:
    """Write two consistent runs: public proofs plus private contracts and salts."""

    payload_a = contract_bytes(contract_a()) if payload_a is None else payload_a
    payload_b = contract_bytes(contract_b()) if payload_b is None else payload_b
    public, private = root / "public", root / "private"
    public.mkdir(exist_ok=True)
    private.mkdir(exist_ok=True)
    paths = {
        "placement_a": public / "evidence-a.json",
        "contract_a": private / "contract-a.json",
        "salt_a": private / "salt-a.bin",
        "placement_b": public / "evidence-b.json",
        "contract_b": private / "contract-b.json",
        "salt_b": private / "salt-b.bin",
    }
    paths["placement_a"].write_bytes(encode(evidence(
        "placement-a", PROOF_A, SAMPLES_A, commitment=commitment(payload_a, salt_a)
    )))
    paths["placement_b"].write_bytes(encode(evidence(
        "placement-b", PROOF_B, SAMPLES_B, commitment=commitment(payload_b, salt_b)
    )))
    paths["contract_a"].write_bytes(payload_a)
    paths["contract_b"].write_bytes(payload_b)
    paths["salt_a"].write_bytes(salt_a)
    paths["salt_b"].write_bytes(salt_b)
    return paths


@contextlib.contextmanager
def case_directory():
    """Yield a temporary root whose private files sit outside the patched source tree."""

    with sovereign_temporary_directory() as directory:
        root = Path(directory)
        source = root / "source-tree"
        source.mkdir()
        # SOVEREIGN_TEST_TMP may live inside the checkout, so the verifier's
        # source tree is pinned to a sibling directory for these fixtures.
        with patch.object(verifier, "PROJECT_ROOT", source):
            yield root


def verify_paths(paths: dict[str, Path]) -> dict:
    return verifier.verify(*(paths[key] for key in INPUT_KEYS))


def cli_argv(paths: dict[str, Path], output: Path) -> list[str]:
    argv: list[str] = []
    for key in INPUT_KEYS:
        argv += ["--" + key.replace("_", "-"), str(paths[key])]
    return argv + ["--output", str(output)]


def run_cli(argv: list[str]) -> tuple[int, bytes, str]:
    stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = verifier.main(argv)
    stdout.flush()
    return code, stdout.buffer.getvalue(), stderr.getvalue()


def load_receipt_schema() -> dict:
    return json.loads(
        (SCHEMA_ROOT / "core-mini-placement-distinctness.schema.json").read_text(
            encoding="utf-8"
        )
    )


class DistinctnessTests(unittest.TestCase):
    def assertRefused(self, paths: dict[str, Path], fragment: str) -> None:
        with self.assertRaises(benchmark.BenchmarkRefused) as caught:
            verify_paths(paths)
        self.assertIn(fragment, str(caught.exception))

    def test_receipt_binds_both_public_commitments(self) -> None:
        with case_directory() as root:
            paths = write_case(root)
            receipt = verify_paths(paths)
            proofs = {
                label: json.loads(paths[key].read_bytes())
                for label, key in (("placement-a", "placement_a"), ("placement-b", "placement_b"))
            }
        self.assertEqual(receipt["schema_version"], "core-mini-placement-distinctness.v1")
        self.assertEqual(receipt["commitment_scheme"], "core-mini-placement-commitment-v1")
        self.assertEqual(
            receipt["distinctness"],
            {"cpu_sets_differ": True, "policy_nodes_differ": True},
        )
        for label, proof in proofs.items():
            self.assertEqual(
                receipt["placements"][label]["contract_commitment_sha256"],
                proof["placement"]["contract_commitment_sha256"],
            )
        self.assertEqual(
            receipt["placements"]["placement-a"]["contract_commitment_sha256"],
            commitment(contract_bytes(contract_a()), SALT_A),
        )
        check_against_schema(receipt, load_receipt_schema())

    def test_each_axis_is_reported_on_its_own(self) -> None:
        cases = {
            "same CPUs, other policy nodes": (
                contract_a(allowed_memory_nodes=[0, 1]),
                contract_b(cpu_ids=[0, 1, 2, 3], allowed_memory_nodes=[0, 1]),
                {"cpu_sets_differ": False, "policy_nodes_differ": True},
            ),
            "other CPUs, same policy nodes": (
                contract_a(),
                contract_b(allowed_memory_nodes=[0], policy_memory_nodes=[0]),
                {"cpu_sets_differ": True, "policy_nodes_differ": False},
            ),
        }
        for name, (document_a, document_b, expected) in cases.items():
            with self.subTest(case=name), case_directory() as root:
                paths = write_case(
                    root,
                    payload_a=contract_bytes(document_a),
                    payload_b=contract_bytes(document_b),
                )
                receipt = verify_paths(paths)
                self.assertEqual(receipt["distinctness"], expected)
                check_against_schema(receipt, load_receipt_schema())

    def test_refuses_identical_placements(self) -> None:
        # Only the opaque label differs: this is exactly the hole the random
        # salt leaves open in the public proofs.
        same = contract_b(cpu_ids=[0, 1, 2, 3], allowed_memory_nodes=[0], policy_memory_nodes=[0])
        # Differences outside the two published axes are refused too
        # (fail closed): the receipt could not state them.
        policy_mode_only = same | {"memory_policy": "preferred"}
        allowed_nodes_only = same | {"allowed_memory_nodes": [0, 1]}
        for name, document_b in (
            ("label only", same),
            ("memory policy mode only", policy_mode_only),
            ("allowed memory nodes only", allowed_nodes_only),
        ):
            with self.subTest(case=name), case_directory() as root:
                paths = write_case(root, payload_b=contract_bytes(document_b))
                self.assertRefused(paths, "do not differ")

    def test_refuses_one_contract_file_presented_for_both_placements(self) -> None:
        with case_directory() as root:
            payload = contract_bytes(contract_a())
            paths = write_case(root, payload_a=payload, payload_b=payload)
            paths["contract_b"] = paths["contract_a"]
            self.assertRefused(paths, "label does not match the placement-b proof")

    def test_refuses_a_commitment_mismatch(self) -> None:
        def wrong_salt(paths: dict[str, Path]) -> None:
            paths["salt_a"].write_bytes(bytes(32))

        def reformatted_contract(paths: dict[str, Path]) -> None:
            # Same meaning, different bytes: the commitment covers exact bytes.
            paths["contract_a"].write_bytes(
                benchmark._canonical_json_bytes(contract_a()) + b"\n"
            )

        def swapped_contracts(paths: dict[str, Path]) -> None:
            paths["contract_a"], paths["contract_b"] = paths["contract_b"], paths["contract_a"]

        def swapped_salts(paths: dict[str, Path]) -> None:
            paths["salt_a"], paths["salt_b"] = paths["salt_b"], paths["salt_a"]

        def forged_public_commitment(paths: dict[str, Path]) -> None:
            forged = json.loads(paths["placement_a"].read_bytes())
            forged["placement"]["contract_commitment_sha256"] = "c" * 64
            paths["placement_a"].write_bytes(encode(forged))

        for mutate in (
            wrong_salt, reformatted_contract, swapped_contracts, swapped_salts,
            forged_public_commitment,
        ):
            with self.subTest(case=mutate.__name__), case_directory() as root:
                paths = write_case(root)
                mutate(paths)
                self.assertRefused(paths, "does not match the placement-a commitment")

    def test_refuses_a_contract_label_that_contradicts_its_proof(self) -> None:
        with case_directory() as root:
            relabelled = contract_a(placement_id="placement-b")
            paths = write_case(root, payload_a=contract_bytes(relabelled))
            self.assertRefused(paths, "label does not match the placement-a proof")

    def test_refuses_one_salt_reused_for_both_runs(self) -> None:
        with case_directory() as root:
            paths = write_case(root, salt_b=SALT_A)
            self.assertRefused(paths, "share one commitment salt")

    def test_refuses_symbolic_links_for_every_input(self) -> None:
        for key in INPUT_KEYS:
            with self.subTest(input=key), case_directory() as root:
                paths = write_case(root)
                target = paths[key].with_name("target-" + paths[key].name)
                paths[key].rename(target)
                try:
                    os.symlink(target, paths[key])
                except (OSError, NotImplementedError):
                    self.skipTest("symbolic links are unavailable on this platform")
                self.assertRefused(paths, "not a link")

    def test_refuses_a_link_where_links_cannot_be_created(self) -> None:
        # Windows test hosts often lack the symlink privilege: simulate what
        # lstat reports for a link so the refusal is exercised everywhere.
        link_mode = stat.S_IFLNK | 0o777
        real_lstat = os.lstat

        for key in INPUT_KEYS:
            with self.subTest(input=key), case_directory() as root:
                paths = write_case(root)
                target = paths[key]

                def fake_lstat(path, *args, **kwargs):
                    result = real_lstat(path, *args, **kwargs)
                    if Path(path) == target:
                        fields = list(result)
                        fields[stat.ST_MODE] = link_mode
                        return os.stat_result(fields)
                    return result

                # The check lives in the comparator, shared with the verifier.
                with patch.object(comparison.os, "lstat", fake_lstat):
                    self.assertRefused(paths, "not a link")

    def test_refuses_a_directory_or_missing_input(self) -> None:
        with case_directory() as root:
            paths = write_case(root)
            missing = dict(paths, salt_b=root / "private" / "absent.bin")
            self.assertRefused(missing, "unavailable")
            directory = dict(paths, contract_a=root / "private")
            self.assertRefused(directory, "not a link")

    def test_refuses_oversized_or_truncated_inputs(self) -> None:
        def oversized_contract(paths: dict[str, Path]) -> None:
            payload = contract_bytes(contract_a())
            paths["contract_a"].write_bytes(
                payload + b" " * (benchmark.MAXIMUM_SOURCE_BYTES + 1 - len(payload))
            )

        def oversized_proof(paths: dict[str, Path]) -> None:
            paths["placement_b"].write_bytes(
                b" " * (benchmark.MAXIMUM_CHILD_OUTPUT_BYTES + 1)
            )

        mutations = {
            "contract over the runner limit": oversized_contract,
            "proof over the comparator limit": oversized_proof,
            "long salt": lambda paths: paths["salt_a"].write_bytes(SALT_A + b"\x00"),
            "short salt": lambda paths: paths["salt_b"].write_bytes(SALT_B[:31]),
            "empty salt": lambda paths: paths["salt_b"].write_bytes(b""),
            "empty contract": lambda paths: paths["contract_b"].write_bytes(b""),
        }
        for name, mutate in mutations.items():
            with self.subTest(case=name), case_directory() as root:
                paths = write_case(root)
                mutate(paths)
                # The bounded read refuses before any parsing or hashing.
                self.assertRefused(paths, "outside the allowed range")

    def test_refuses_non_canonical_proofs_and_contracts(self) -> None:
        def indented_proof(root: Path) -> dict[str, Path]:
            paths = write_case(root)
            document = json.loads(paths["placement_a"].read_bytes())
            paths["placement_a"].write_bytes(
                json.dumps(document, indent=2, sort_keys=True).encode("utf-8") + b"\n"
            )
            return paths

        def proof_with_double_lf(root: Path) -> dict[str, Path]:
            paths = write_case(root)
            paths["placement_b"].write_bytes(paths["placement_b"].read_bytes() + b"\n")
            return paths

        def contract_case(payload: bytes):
            # The proof commits to these exact bytes, so only the runner's
            # strict contract loader can refuse them.
            return lambda root: write_case(root, payload_a=payload)

        base = benchmark._canonical_json_bytes(contract_a())
        cpu_ids = b'"cpu_ids":[0,1,2,3]'
        cases = {
            "indented proof": (indented_proof, "evidence bytes are not canonical"),
            "proof with a doubled LF": (proof_with_double_lf, "evidence bytes are not canonical"),
            "unsorted CPU ids": (
                contract_case(contract_bytes(contract_a(cpu_ids=[3, 2, 1, 0]))),
                "identifiers are not canonical",
            ),
            "duplicated CPU id": (
                contract_case(contract_bytes(contract_a(cpu_ids=[0, 0, 1]))),
                "identifiers are not canonical",
            ),
            "boolean CPU id": (
                contract_case(contract_bytes(contract_a(cpu_ids=[True]))),
                "identifiers are invalid",
            ),
            "unknown key": (
                contract_case(contract_bytes(contract_a(hostname="x"))),
                "contract is incompatible",
            ),
            "policy escaping allowed nodes": (
                contract_case(contract_bytes(contract_a(policy_memory_nodes=[1]))),
                "escapes allowed nodes",
            ),
            "list as memory policy": (
                contract_case(contract_bytes(contract_a(memory_policy=["bind"]))),
                "contract is invalid",
            ),
            "duplicated key": (
                contract_case(base[:-1] + b',"placement_id":"placement-a"}'),
                "JSON output is invalid",
            ),
            "non-finite value": (
                contract_case(base.replace(cpu_ids, b'"cpu_ids":[NaN]')),
                "JSON output is invalid",
            ),
            "oversized integer": (
                contract_case(base.replace(cpu_ids, b'"cpu_ids":[' + b"7" * 5000 + b"]")),
                "contract is invalid",
            ),
            "deep nesting": (
                contract_case(
                    base.replace(cpu_ids, b'"cpu_ids":' + b"[" * 100_000 + b"]" * 100_000)
                ),
                "contract is invalid",
            ),
        }
        for name, (build, fragment) in cases.items():
            with self.subTest(case=name), case_directory() as root:
                self.assertRefused(build(root), fragment)

    def test_refuses_private_inputs_inside_the_source_tree(self) -> None:
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            paths = write_case(root)
            with patch.object(verifier, "PROJECT_ROOT", root):
                self.assertRefused(paths, "outside the source tree")

    def test_refuses_a_pair_the_comparator_would_refuse(self) -> None:
        with case_directory() as root:
            paths = write_case(root)
            self.assertRefused(dict(paths, placement_b=paths["placement_a"]), "two distinct proof files")
            drifted = json.loads(paths["placement_b"].read_bytes())
            drifted["benchmark_session_id"] = "session-99999999-8888-4777-b666-555555555555"
            paths["placement_b"].write_bytes(encode(drifted))
            self.assertRefused(paths, "benchmark_session_id")

    def test_receipt_holds_no_identifier_count_salt_or_path(self) -> None:
        with case_directory() as root:
            paths = write_case(root)
            receipt = verify_paths(paths)
            private_markers = [
                str(root), paths["contract_a"].name, paths["salt_a"].name,
                SALT_A.hex(), SALT_B.hex(),
            ]
        schema = load_receipt_schema()
        constants = {
            value["const"] for value in schema["properties"].values() if "const" in value
        }
        leaves: list = []

        def walk(node) -> None:
            if isinstance(node, dict):
                for value in node.values():
                    walk(value)
            else:
                leaves.append(node)

        walk(receipt)
        for value in leaves:
            with self.subTest(value=value):
                if isinstance(value, bool):
                    continue
                # No integer or list can carry an id or a count: every other
                # leaf is a fixed constant or a public commitment.
                self.assertIsInstance(value, str)
                self.assertTrue(
                    value in constants or re.fullmatch(r"[0-9a-f]{64}", value), value
                )
        self.assertEqual(
            {key: set(value) for key, value in receipt.items() if isinstance(value, dict)},
            {
                "placements": {"placement-a", "placement-b"},
                "distinctness": {"cpu_sets_differ", "policy_nodes_differ"},
            },
        )
        rendered = benchmark._canonical_json_bytes(receipt).decode("utf-8")
        for forbidden in ["/", "\\", "cpu_ids", "memory_nodes", *private_markers]:
            self.assertNotIn(forbidden, rendered)

    def test_refusal_messages_never_echo_paths_or_values(self) -> None:
        marker = "private-marker-5e9b"
        with case_directory() as root:
            nested = root / marker
            nested.mkdir()
            paths = write_case(nested)
            paths["salt_a"].write_bytes(bytes(32))
            with self.assertRaises(benchmark.BenchmarkRefused) as caught:
                verify_paths(paths)
        message = str(caught.exception)
        for forbidden in (marker, SALT_A.hex(), bytes(32).hex(), "0, 1, 2, 3"):
            self.assertNotIn(forbidden, message)


class CliTests(unittest.TestCase):
    def test_cli_writes_the_stdout_bytes_once_and_never_overwrites(self) -> None:
        with case_directory() as root:
            paths = write_case(root)
            output = root / "public" / "distinctness.json"
            argv = cli_argv(paths, output)
            code, stdout, stderr = run_cli(argv)
            self.assertEqual((code, stderr), (0, ""))
            written = output.read_bytes()
            self.assertEqual(written, stdout)
            self.assertEqual(
                benchmark._canonical_json_bytes(json.loads(written)) + b"\n", written
            )
            check_against_schema(json.loads(written), load_receipt_schema())
            self.assertEqual(run_cli(argv), (1, b"", REFUSAL_LINE))
            self.assertEqual(output.read_bytes(), written)

    def test_cli_refusal_writes_nothing_and_echoes_no_path(self) -> None:
        marker = "private-marker-2d71"
        code, stdout, stderr = run_cli(["--placement-a", marker])
        self.assertEqual((code, stdout, stderr), (1, b"", REFUSAL_LINE))
        with case_directory() as root:
            paths = write_case(root, salt_b=SALT_A)
            output = root / marker
            self.assertEqual(run_cli(cli_argv(paths, output)), (1, b"", REFUSAL_LINE))
            self.assertFalse(output.exists())

    def test_entrypoint_runs_as_a_file_without_traceback_or_path(self) -> None:
        help_run = subprocess.run(
            [sys.executable, "-B", str(PROJECT_ROOT / "tools" / "verify_core_mini_placement_distinctness.py"), "--help"],
            cwd=PROJECT_ROOT.parent,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(help_run.returncode, 0, help_run.stderr)
        self.assertIn("usage:", help_run.stdout.lower())
        marker = "private-marker-path-9a0e"
        argv = []
        for key in INPUT_KEYS:
            argv += ["--" + key.replace("_", "-"), marker]
        refused = subprocess.run(
            [sys.executable, "-B", "tools/verify_core_mini_placement_distinctness.py", *argv, "--output", marker],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(
            (refused.returncode, refused.stdout, refused.stderr), (1, "", REFUSAL_LINE)
        )


class ReceiptSchemaTests(unittest.TestCase):
    def test_schema_is_closed_and_every_property_is_required(self) -> None:
        schema = load_receipt_schema()

        def walk(node: dict, where: str) -> None:
            if node.get("type") == "object":
                self.assertIs(node.get("additionalProperties"), False, where)
                self.assertEqual(set(node["required"]), set(node["properties"]), where)
                for key, child in node["properties"].items():
                    walk(child, f"{where}.{key}")

        walk(schema, "$")
        for name, definition in schema["$defs"].items():
            walk(definition, f"$defs.{name}")

    def test_schema_constants_track_the_tools(self) -> None:
        schema = load_receipt_schema()
        evidence_schema = json.loads(
            (SCHEMA_ROOT / "core-mini-numa-evidence.schema.json").read_text(encoding="utf-8")
        )
        properties = schema["properties"]
        self.assertEqual(properties["schema_version"]["const"], verifier.RECEIPT_SCHEMA_VERSION)
        self.assertEqual(properties["commitment_scheme"]["const"], verifier.COMMITMENT_SCHEME)
        self.assertEqual(
            properties["evidence_schema_version"]["const"],
            evidence_schema["properties"]["schema_version"]["const"],
        )
        self.assertEqual(schema["$defs"]["sha256"], evidence_schema["$defs"]["sha256"])
        # The published scheme name is the runner's domain separator.
        payload = contract_bytes(contract_a())
        self.assertEqual(
            commitment(payload, SALT_A),
            hashlib.sha256(
                verifier.COMMITMENT_SCHEME.encode("ascii") + b"\x00" + SALT_A + payload
            ).hexdigest(),
        )
        self.assertEqual(verifier.SALT_BYTES, 32)

    def test_the_checker_rejects_contract_violations(self) -> None:
        schema = load_receipt_schema()
        with case_directory() as root:
            valid = verify_paths(write_case(root))
        check_against_schema(valid, schema)

        def mutated(change) -> dict:
            document = json.loads(json.dumps(valid))
            change(document)
            return document

        violations = {
            "no differing axis": lambda d: d.update(
                distinctness={"cpu_sets_differ": False, "policy_nodes_differ": False}
            ),
            "integer for a boolean": lambda d: d["distinctness"].update(cpu_sets_differ=1),
            "CPU ids": lambda d: d["distinctness"].update(cpu_ids=[0, 1]),
            "node count": lambda d: d["placements"]["placement-a"].update(node_count=1),
            "salt": lambda d: d["placements"]["placement-b"].update(salt="00" * 32),
            "path": lambda d: d.update(contract_path="/private/contract.json"),
            "uppercase commitment": lambda d: d["placements"]["placement-a"].update(
                contract_commitment_sha256="A" * 64
            ),
            "missing placement": lambda d: d["placements"].pop("placement-b"),
            "wrong version": lambda d: d.update(schema_version="core-mini-placement-distinctness.v2"),
        }
        for name, change in violations.items():
            with self.subTest(violation=name):
                with self.assertRaises(AssertionError):
                    check_against_schema(mutated(change), schema)


if __name__ == "__main__":
    unittest.main()
