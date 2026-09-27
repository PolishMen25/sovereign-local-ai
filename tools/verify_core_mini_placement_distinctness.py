#!/usr/bin/env python3
"""Verify offline that two CORE-MINI proofs used distinct private placements.

Each runner proof publishes only a salted commitment of its private placement
contract, with a fresh random salt per run. Public proofs therefore cannot
show that placement-a and placement-b really designated different CPU sets or
memory nodes. This tool reads both private contracts and their salts,
recomputes both commitments against the two public 0.2.0 proofs and emits a
public receipt (schemas/core-mini-placement-distinctness.schema.json) holding
only the two commitments and two booleans. It never publishes a CPU id, a
node id, a count, a salt or a path.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.inference.cli import PathFreeArgumentParser
from tools import compare_core_mini_numa_evidence as comparison
from tools import core_mini_numa_benchmark as benchmark


RECEIPT_SCHEMA_VERSION = "core-mini-placement-distinctness.v1"
# Domain separator used by the runner in _placement_contract_commitment.
COMMITMENT_SCHEME = "core-mini-placement-commitment-v1"
SALT_BYTES = 32
LABEL_A, LABEL_B = benchmark.PLACEMENT_IDS


def _require_regular_non_link(path: Path) -> None:
    # Same lstat rule as the comparator, which applies it to both proofs too.
    comparison._require_regular_non_link(path, "distinctness input")


def _require_outside_source_tree(path: Path) -> None:
    # Same rule as the runner: private contracts and salts never live in the
    # repository tree, where they could be committed by mistake.
    try:
        resolved = path.resolve(strict=True)
        project_root = PROJECT_ROOT.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise benchmark.BenchmarkRefused(
            "private distinctness input is unavailable"
        ) from None
    if resolved == project_root or project_root in resolved.parents:
        raise benchmark.BenchmarkRefused(
            "private distinctness inputs must remain outside the source tree"
        )


def _read_proof(path: Path) -> tuple[dict[str, Any], str]:
    _require_regular_non_link(path)
    return comparison._read_evidence(path)


def _read_contract(path: Path) -> tuple[str, bytes, benchmark.PlacementSnapshot]:
    _require_regular_non_link(path)
    _require_outside_source_tree(path)
    try:
        return benchmark.load_private_placement_contract(path)
    except benchmark.BenchmarkRefused:
        raise
    except (TypeError, ValueError, RecursionError):
        # Oversized integers, deep nesting or unhashable values escape the
        # runner's strict parser; they are refused the same way.
        raise benchmark.BenchmarkRefused(
            "private placement contract is invalid"
        ) from None


def _read_salt(path: Path) -> bytes:
    _require_regular_non_link(path)
    _require_outside_source_tree(path)
    return benchmark._read_regular_bytes(
        path, maximum_bytes=SALT_BYTES, minimum_bytes=SALT_BYTES
    )


def _verified_placement(
    proof: dict[str, Any], contract_path: Path, salt_path: Path
) -> tuple[benchmark.PlacementSnapshot, bytes]:
    label = proof["placement"]["label"]
    contract_label, payload, snapshot = _read_contract(contract_path)
    salt = _read_salt(salt_path)
    # The commitment covers the exact contract bytes the runner read; they are
    # hashed as-is, never re-serialized.
    recomputed = benchmark._placement_contract_commitment(payload, salt)
    if recomputed != proof["placement"]["contract_commitment_sha256"]:
        raise benchmark.BenchmarkRefused(
            f"private contract or salt does not match the {label} commitment"
        )
    if contract_label != label:
        raise benchmark.BenchmarkRefused(
            f"private contract label does not match the {label} proof"
        )
    return snapshot, salt


def verify(
    placement_a: Path,
    contract_a: Path,
    salt_a: Path,
    placement_b: Path,
    contract_b: Path,
    salt_b: Path,
) -> dict[str, Any]:
    proof_a, proof_a_sha256 = _read_proof(placement_a)
    proof_b, proof_b_sha256 = _read_proof(placement_b)
    # A receipt only makes sense for a pair the comparator would accept:
    # distinct files and proof_id, placement-a then placement-b, same session
    # and workload, and two different public commitments.
    comparison._require_comparable(proof_a, proof_a_sha256, proof_b, proof_b_sha256)
    snapshot_a, salt_a_bytes = _verified_placement(proof_a, contract_a, salt_a)
    snapshot_b, salt_b_bytes = _verified_placement(proof_b, contract_b, salt_b)
    if salt_a_bytes == salt_b_bytes:
        # The runner draws 32 random bytes per run: equal salts mean one salt
        # file was reused, not two independent runs.
        raise benchmark.BenchmarkRefused(
            "the two placements share one commitment salt"
        )
    # Identifier arrays are strictly increasing without duplicates (enforced
    # by the runner's loader), so tuple equality is set equality.
    cpu_sets_differ = snapshot_a.cpu_ids != snapshot_b.cpu_ids
    policy_nodes_differ = (
        snapshot_a.policy_memory_nodes != snapshot_b.policy_memory_nodes
    )
    if not cpu_sets_differ and not policy_nodes_differ:
        raise benchmark.BenchmarkRefused(
            "placements do not differ on CPU set or policy memory nodes"
        )
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "artifact_type": "private-placement-distinctness-receipt",
        "canonicalization": "canonical-json-v1",
        "evidence_schema_version": comparison.EVIDENCE_SCHEMA_VERSION,
        "commitment_scheme": COMMITMENT_SCHEME,
        "placements": {
            LABEL_A: {
                "contract_commitment_sha256": proof_a["placement"][
                    "contract_commitment_sha256"
                ],
            },
            LABEL_B: {
                "contract_commitment_sha256": proof_b["placement"][
                    "contract_commitment_sha256"
                ],
            },
        },
        "distinctness": {
            "cpu_sets_differ": cpu_sets_differ,
            "policy_nodes_differ": policy_nodes_differ,
        },
        "verification": "private-contracts-and-salts-matched-public-commitments",
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = PathFreeArgumentParser(description=__doc__)
    parser.add_argument("--placement-a", type=Path, required=True)
    parser.add_argument("--contract-a", type=Path, required=True)
    parser.add_argument("--salt-a", type=Path, required=True)
    parser.add_argument("--placement-b", type=Path, required=True)
    parser.add_argument("--contract-b", type=Path, required=True)
    parser.add_argument("--salt-b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        document = verify(
            args.placement_a,
            args.contract_a,
            args.salt_a,
            args.placement_b,
            args.contract_b,
            args.salt_b,
        )
        encoded = benchmark._canonical_json_bytes(document) + b"\n"
        benchmark._write_atomic_exclusive(args.output, encoded)
        sys.stdout.buffer.write(encoded)
        return 0
    except Exception:
        # Fail closed: argument errors, refusals, OSError and any unexpected
        # parsing error become the same message, without path, value or trace.
        print("CORE-MINI placement distinctness refused", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
