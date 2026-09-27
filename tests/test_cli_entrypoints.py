from pathlib import Path
import subprocess
import sys
import unittest


PROJECT_ROOT = Path(__file__).parents[1]


class CliEntrypointTests(unittest.TestCase):
    def test_bounded_training_entrypoints_offer_help_when_run_as_files(self) -> None:
        scripts = (
            "tools/compare_core_mini_numa_evidence.py",
            "tools/core_mini_numa_child.py",
            "tools/core_mini_numa_benchmark.py",
            "tools/summarize_training_metrics.py",
            "tools/train_byte_bpe.py",
            "tools/train_core_mini.py",
            "tools/verify_core_checkpoint_compatibility.py",
        )
        for relative_path in scripts:
            with self.subTest(script=relative_path):
                completed = subprocess.run(
                    [sys.executable, "-B", relative_path, "--help"],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("usage:", completed.stdout.lower())

    def test_numa_entrypoints_are_independent_of_working_directory(self) -> None:
        for name in ("core_mini_numa_benchmark.py", "compare_core_mini_numa_evidence.py"):
            with self.subTest(script=name):
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(PROJECT_ROOT / "tools" / name),
                        "--help",
                    ],
                    cwd=PROJECT_ROOT.parent,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("usage:", completed.stdout.lower())

    def test_numa_comparator_refuses_as_a_file_without_traceback_or_path(self) -> None:
        marker = "private-marker-path-4c1d"
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "tools/compare_core_mini_numa_evidence.py",
                "--placement-a",
                marker,
                "--placement-b",
                marker,
                "--output",
                marker,
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(completed.stderr, "CORE-MINI NUMA comparison refused\n")


if __name__ == "__main__":
    unittest.main()
