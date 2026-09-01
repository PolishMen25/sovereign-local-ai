import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import unittest
import uuid
from unittest.mock import patch

from tests._temp_support import sovereign_temporary_directory
from tools import core_mini_numa_benchmark as benchmark
from tools import core_mini_numa_child as child


PROJECT_ROOT = Path(__file__).parents[1]
SESSION_ID = "session-12345678-1234-4234-8234-123456789abc"
PROOF_UUID = uuid.UUID("87654321-4321-4321-8321-cba987654321")


def private_contract() -> dict:
    return {
        "schema_version": "core-mini-private-placement.v1",
        "placement_id": "placement-a",
        "cpu_ids": [0, 1],
        "allowed_memory_nodes": [0],
        "memory_policy": "bind",
        "policy_memory_nodes": [0],
    }


def arguments() -> argparse.Namespace:
    return argparse.Namespace(
        repetitions=3,
        steps=8,
        warmup_steps=2,
        batch_size=2,
        sequence_length=32,
        threads=2,
        seed=20260831,
        timeout_seconds=600,
        benchmark_session_id=SESSION_ID,
    )


def repetition(index: int, throughput: float) -> dict:
    return {
        "repetition_id": index,
        "status": "completed",
        "metrics_sha256": f"{index:x}" * 64,
        "summary_sha256": f"{index + 3:x}" * 64,
        "verification_sha256": f"{index + 4:x}" * 64,
        "checkpoint_sha256": f"{index + 6:x}" * 64,
        "steps_total": 8,
        "steps_measured": 6,
        "tokens_measured": 384,
        "timing_seconds": {
            "total": 2.0,
            "mean_step": 1.0 / 3.0,
            "median_step": 1.0 / 3.0,
            "minimum_step": 0.3,
            "maximum_step": 0.4,
            "population_standard_deviation": 0.01,
            "median_absolute_deviation": 0.01,
        },
        "tokens_per_second": throughput,
    }


class CoreMiniNumaBenchmarkTests(unittest.TestCase):
    def test_schema_roots_track_the_runner_contracts(self) -> None:
        public_schema = json.loads(
            (PROJECT_ROOT / "schemas" / "core-mini-numa-evidence.schema.json").read_text(
                encoding="utf-8"
            )
        )
        private_schema = json.loads(
            (
                PROJECT_ROOT
                / "schemas"
                / "core-mini-private-placement.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertFalse(public_schema["additionalProperties"])
        self.assertEqual(
            set(public_schema["required"]),
            {
                "schema_version",
                "artifact_type",
                "proof_id",
                "created_at_utc",
                "benchmark_session_id",
                "canonicalization",
                "placement",
                "workload",
                "workload_contract_sha256",
                "repetitions",
                "aggregate",
                "evidence_scope",
            },
        )
        self.assertFalse(private_schema["additionalProperties"])
        self.assertEqual(set(private_schema["required"]), benchmark.PLACEMENT_CONTRACT_KEYS)
        self.assertEqual(
            set(private_schema["properties"]["placement_id"]["enum"]),
            set(benchmark.PLACEMENT_IDS),
        )

    def test_source_archive_binds_pax_commit_and_exact_tree(self) -> None:
        commit = "a" * 40
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            archive = root / "source.tar.gz"
            with tarfile.open(
                archive,
                "w:gz",
                format=tarfile.PAX_FORMAT,
                pax_headers={"comment": commit},
            ) as bundle:
                bundle.add(source / "module.py", arcname="source/module.py")

            with patch.object(benchmark, "PROJECT_ROOT", source):
                revision, archive_digest, manifest_digest = benchmark.verify_source_archive(
                    archive
                )
            self.assertEqual(revision, commit)
            self.assertRegex(archive_digest, r"^[0-9a-f]{64}$")
            self.assertRegex(manifest_digest, r"^[0-9a-f]{64}$")

            (source / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
            with patch.object(benchmark, "PROJECT_ROOT", source):
                with self.assertRaises(benchmark.BenchmarkRefused):
                    benchmark.verify_source_archive(archive)

    def test_source_archive_without_pax_commit_is_refused(self) -> None:
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            archive = root / "source.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                bundle.add(source / "module.py", arcname="source/module.py")

            with patch.object(benchmark, "PROJECT_ROOT", source):
                with self.assertRaises(benchmark.BenchmarkRefused):
                    benchmark.verify_source_archive(archive)

    def test_offline_runtime_lock_and_observed_runtime_are_strict(self) -> None:
        lock_path = PROJECT_ROOT / "configs" / "runtime" / "pytorch-2.13.0-cpu-cp313-linux-x86_64.lock.json"
        _, digest, expected_python, architecture, minimum_glibc, torch_version = (
            benchmark.load_offline_runtime_lock(lock_path)
        )
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        runtime = {
            "device": "cpu_only",
            "accelerator_backend": "absent",
            "python_version": expected_python + ".1",
            "platform_machine": architecture,
            "platform_system": "Linux",
            "glibc_version": minimum_glibc,
            "torch_version": torch_version,
        }
        benchmark.validate_runtime_observation(
            runtime,
            expected_python=expected_python,
            expected_architecture=architecture,
            minimum_glibc=minimum_glibc,
            expected_torch=torch_version,
        )
        runtime["torch_version"] = "0.0.0+cpu"
        with self.assertRaises(benchmark.BenchmarkRefused):
            benchmark.validate_runtime_observation(
                runtime,
                expected_python=expected_python,
                expected_architecture=architecture,
                minimum_glibc=minimum_glibc,
                expected_torch=torch_version,
            )

    def test_private_contract_is_strict_and_hashes_exact_bytes(self) -> None:
        payload = json.dumps(private_contract(), sort_keys=True).encode("utf-8") + b"\n"
        with sovereign_temporary_directory() as directory:
            path = Path(directory) / "placement.json"
            path.write_bytes(payload)

            label, exact_payload, placement = benchmark.load_private_placement_contract(path)

            self.assertEqual(label, "placement-a")
            self.assertEqual(exact_payload, payload)
            self.assertEqual(placement.cpu_ids, (0, 1))
            self.assertEqual(placement.allowed_memory_nodes, (0,))
            self.assertEqual(placement.memory_policy, "bind")
            self.assertEqual(placement.policy_memory_nodes, (0,))

        first = benchmark._placement_contract_commitment(payload, b"a" * 32)
        second = benchmark._placement_contract_commitment(payload, b"b" * 32)
        self.assertNotEqual(first, second)
        with self.assertRaises(benchmark.BenchmarkRefused):
            benchmark._placement_contract_commitment(payload, b"short")

    def test_private_contract_rejects_unknown_duplicate_and_noncanonical_values(self) -> None:
        cases = []
        unknown = private_contract()
        unknown["hostname"] = "forbidden"
        cases.append(json.dumps(unknown).encode("utf-8"))
        cases.append(
            b'{"schema_version":"core-mini-private-placement.v1",'
            b'"schema_version":"core-mini-private-placement.v1",'
            b'"placement_id":"placement-a","cpu_ids":[0],'
            b'"allowed_memory_nodes":[0],"memory_policy":"bind",'
            b'"policy_memory_nodes":[0]}'
        )
        noncanonical = private_contract()
        noncanonical["cpu_ids"] = [1, 0]
        cases.append(json.dumps(noncanonical).encode("utf-8"))
        boolean = private_contract()
        boolean["cpu_ids"] = [True]
        cases.append(json.dumps(boolean).encode("utf-8"))

        with sovereign_temporary_directory() as directory:
            for index, payload in enumerate(cases):
                with self.subTest(case=index):
                    path = Path(directory) / f"placement-{index}.json"
                    path.write_bytes(payload)
                    with self.assertRaises(benchmark.BenchmarkRefused):
                        benchmark.load_private_placement_contract(path)

    def test_placement_observation_requires_three_matching_sources(self) -> None:
        expected = benchmark.PlacementSnapshot((0, 1), (0,), "bind", (0,))
        with (
            patch.object(benchmark.sys, "platform", "linux"),
            patch.object(
                benchmark.os, "sched_getaffinity", return_value={0, 1}, create=True
            ),
            patch.object(
                benchmark,
                "_read_proc_status_lists",
                return_value=((0, 1), (0,)),
            ),
            patch.object(benchmark, "_read_memory_policy", return_value=("bind", (0,))),
        ):
            self.assertEqual(benchmark.capture_placement("bind"), expected)

        with (
            patch.object(benchmark.sys, "platform", "linux"),
            patch.object(
                benchmark.os, "sched_getaffinity", return_value={0}, create=True
            ),
            patch.object(
                benchmark,
                "_read_proc_status_lists",
                return_value=((0, 1), (0,)),
            ),
            patch.object(benchmark, "_read_memory_policy", return_value=("bind", (0,))),
        ):
            with self.assertRaises(benchmark.BenchmarkRefused):
                benchmark.capture_placement("bind")

    def test_procfs_reader_accepts_zero_advertised_size_but_stays_bounded(self) -> None:
        metadata = type("Metadata", (), {"st_mode": 0o100400})()
        chunks = [b"Cpus_allowed_list:\t0-1\nMems_allowed_list:\t0\n", b""]
        with (
            patch.object(benchmark.os, "open", return_value=42),
            patch.object(benchmark.os, "fstat", return_value=metadata),
            patch.object(benchmark.os, "read", side_effect=chunks),
            patch.object(benchmark.os, "close"),
        ):
            payload = benchmark._read_bounded_stream(
                Path("/proc/self/status"), maximum_bytes=1024
            )
        self.assertIn(b"Cpus_allowed_list", payload)

    def test_network_preflight_requires_both_inet_families_to_be_denied(self) -> None:
        def denied(*args, **kwargs):
            del args, kwargs
            raise OSError(errno.EPERM, "denied")

        benchmark.require_inet_sockets_denied(denied)

        class OpenSocket:
            def close(self) -> None:
                pass

        with self.assertRaisesRegex(benchmark.BenchmarkRefused, "Internet"):
            benchmark.require_inet_sockets_denied(lambda *args: OpenSocket())

        def exhausted(*args, **kwargs):
            del args, kwargs
            raise OSError(errno.EMFILE, "exhausted")

        with self.assertRaisesRegex(benchmark.BenchmarkRefused, "proven"):
            benchmark.require_inet_sockets_denied(exhausted)

    def test_child_environment_is_an_allowlist_without_inherited_secrets(self) -> None:
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            with patch.dict(
                os.environ,
                {
                    "HTTPS_PROXY": "private-proxy",
                    "PYTHONPATH": "private-python-path",
                    "LD_PRELOAD": "private-library",
                    "PRIVATE_TOKEN": "private-secret",
                },
            ):
                environment = benchmark._safe_child_environment(root, threads=4)

            self.assertEqual(environment["OMP_NUM_THREADS"], "4")
            self.assertEqual(environment["MKL_NUM_THREADS"], "4")
            self.assertTrue((root / "home").is_dir())
            self.assertTrue((root / "tmp").is_dir())
            self.assertTrue((root / "cache").is_dir())
            for forbidden in (
                "HTTPS_PROXY",
                "PYTHONPATH",
                "PYTHONHOME",
                "LD_PRELOAD",
                "PRIVATE_TOKEN",
            ):
                self.assertNotIn(forbidden, environment)

    def test_strict_json_parser_rejects_duplicates_constants_and_extra_keys(self) -> None:
        with self.assertRaises(benchmark.BenchmarkRefused):
            benchmark._parse_json_object(
                b'{"value":1,"value":2}', expected_keys={"value"}
            )
        with self.assertRaises(benchmark.BenchmarkRefused):
            benchmark._parse_json_object(b'{"value":NaN}', expected_keys={"value"})
        with self.assertRaises(benchmark.BenchmarkRefused):
            benchmark._parse_json_object(
                b'{"value":1,"extra":2}', expected_keys={"value"}
            )

    def test_fixed_child_wrapper_has_no_arbitrary_command_surface(self) -> None:
        args = argparse.Namespace(
            phase="train",
            attestation=Path("attestation.json"),
            required_memory_policy="bind",
            config=Path("config.json"),
            output_dir=Path("training"),
            steps=8,
            batch_size=2,
            sequence_length=32,
            seed=1,
            threads=2,
            metrics=None,
            warmup_steps=None,
            output=None,
            checkpoint=None,
        )
        command = child.build_phase_command(args)
        self.assertEqual(command[:3], [sys.executable, "-I", "-B"])
        self.assertEqual(Path(command[3]).name, "train_core_mini.py")
        self.assertIn("synthetic", command)
        self.assertNotIn("--resume", command)

        args.metrics = Path("unexpected.jsonl")
        with self.assertRaises(benchmark.BenchmarkRefused):
            child.build_phase_command(args)

    def test_child_attestation_binds_cpu_memory_policy_phase_and_network(self) -> None:
        placement = benchmark.PlacementSnapshot((0, 1), (0,), "bind", (0,))
        document = {
            "schema_version": "core-mini-child-placement.v1",
            "phase": "train",
            "cpu_ids": [0, 1],
            "allowed_memory_nodes": [0],
            "memory_policy": "bind",
            "policy_memory_nodes": [0],
            "inet_socket_policy": "stream-and-dgram-denied",
        }
        with sovereign_temporary_directory() as directory:
            path = Path(directory) / "attestation.json"
            path.write_bytes(benchmark._canonical_json_bytes(document) + b"\n")
            digest = benchmark.validate_child_attestation(
                path, expected_phase="train", expected_placement=placement
            )
            self.assertRegex(digest, r"^[0-9a-f]{64}$")

            document["allowed_memory_nodes"] = [1]
            changed = Path(directory) / "changed.json"
            changed.write_bytes(benchmark._canonical_json_bytes(document) + b"\n")
            with self.assertRaises(benchmark.BenchmarkRefused):
                benchmark.validate_child_attestation(
                    changed, expected_phase="train", expected_placement=placement
                )

    def test_build_evidence_matches_the_closed_public_contract(self) -> None:
        args = arguments()
        runs = [repetition(1, 100.0), repetition(2, 110.0), repetition(3, 90.0)]

        evidence = benchmark.build_evidence(
            args,
            placement_id="placement-a",
            placement_contract_commitment_sha256="b" * 64,
            model_name="CORE-MINI-1M",
            source_revision="a" * 40,
            source_archive_sha256="1" * 64,
            source_tree_manifest_sha256="2" * 64,
            config_sha256="c" * 64,
            offline_runtime_lock_sha256="d" * 64,
            runtime_observation_sha256="f" * 64,
            environment_contract_sha256="e" * 64,
            repetitions=runs,
            proof_uuid=PROOF_UUID,
            created_at_utc="2026-09-01T12:00:00Z",
        )

        self.assertEqual(
            set(evidence),
            {
                "schema_version",
                "artifact_type",
                "proof_id",
                "created_at_utc",
                "benchmark_session_id",
                "canonicalization",
                "placement",
                "workload",
                "workload_contract_sha256",
                "repetitions",
                "aggregate",
                "evidence_scope",
            },
        )
        self.assertEqual(evidence["aggregate"]["repetitions_completed"], 3)
        distribution = evidence["aggregate"]["tokens_per_second"]
        self.assertEqual(set(distribution), {
            "mean", "median", "minimum", "maximum",
            "population_standard_deviation", "median_absolute_deviation",
        })
        self.assertEqual(distribution["median"], 100.0)
        self.assertEqual(
            evidence["workload_contract_sha256"],
            hashlib.sha256(
                benchmark._canonical_json_bytes(evidence["workload"])
            ).hexdigest(),
        )
        encoded = benchmark._canonical_json_bytes(evidence)
        self.assertEqual(json.loads(encoded), evidence)
        forbidden_keys = (
            "hostname",
            "cpu_ids",
            "allowed_memory_nodes",
            "command",
            "run_root",
            "environment",
        )
        encoded_text = encoded.decode("utf-8")
        self.assertTrue(
            all(f'"{value}":' not in encoded_text for value in forbidden_keys)
        )

    def test_build_evidence_rejects_missing_or_reordered_repetitions(self) -> None:
        args = arguments()
        with self.assertRaises(benchmark.BenchmarkRefused):
            benchmark.build_evidence(
                args,
                placement_id="placement-a",
                placement_contract_commitment_sha256="b" * 64,
                model_name="CORE-MINI-1M",
                source_revision="a" * 40,
                source_archive_sha256="1" * 64,
                source_tree_manifest_sha256="2" * 64,
                config_sha256="c" * 64,
                offline_runtime_lock_sha256="d" * 64,
                runtime_observation_sha256="f" * 64,
                environment_contract_sha256="e" * 64,
                repetitions=[repetition(2, 100.0)] * 3,
                proof_uuid=PROOF_UUID,
                created_at_utc="2026-09-01T12:00:00Z",
            )

    def test_argument_bounds_reject_booleans_and_too_little_measurement(self) -> None:
        args = arguments()
        args.threads = True
        with self.assertRaises(benchmark.BenchmarkRefused):
            benchmark._validate_arguments(args)

        args = arguments()
        args.warmup_steps = args.steps - 2
        with self.assertRaises(benchmark.BenchmarkRefused):
            benchmark._validate_arguments(args)

        args = arguments()
        args.benchmark_session_id = "private-session-name"
        with self.assertRaises(benchmark.BenchmarkRefused):
            benchmark._validate_arguments(args)

    def test_run_root_is_create_only_and_child_argv_must_be_absolute(self) -> None:
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            target = root / "new-run"
            with patch.object(benchmark, "PROJECT_ROOT", source):
                self.assertEqual(
                    benchmark._create_run_root(target.resolve()), target.resolve()
                )
                with self.assertRaises(benchmark.BenchmarkRefused):
                    benchmark._create_run_root(target.resolve())
            with self.assertRaises(benchmark.BenchmarkRefused):
                benchmark.run_child(
                    ["python", "-c", "pass"],
                    cwd=root,
                    environment={},
                    timeout_seconds=30,
                    stdout_path=root / "stdout",
                    stderr_path=root / "stderr",
                )

    def test_evidence_write_is_atomic_and_never_overwrites(self) -> None:
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            output = root / "evidence.json"
            benchmark._write_atomic_exclusive(output, b'{"status":"complete"}\n')
            self.assertEqual(output.read_bytes(), b'{"status":"complete"}\n')
            self.assertEqual(list(root.glob(".evidence.json.*.tmp")), [])

            with self.assertRaises(benchmark.BenchmarkRefused):
                benchmark._write_atomic_exclusive(output, b'{"status":"changed"}\n')
            self.assertEqual(output.read_bytes(), b'{"status":"complete"}\n')

    def test_cli_refusal_never_echoes_private_argument_values(self) -> None:
        marker = "private-benchmark-path-marker"
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "tools/core_mini_numa_benchmark.py",
                "--run-root",
                marker,
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        self.assertEqual(completed.returncode, 1)
        self.assertNotIn(marker, completed.stdout + completed.stderr)
        self.assertEqual(completed.stderr.strip(), "CORE-MINI NUMA benchmark refused")


if __name__ == "__main__":
    unittest.main()
