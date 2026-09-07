from pathlib import Path
import subprocess
import sys
import unittest


PROJECT_ROOT = Path(__file__).parents[1]


class CliEntrypointTests(unittest.TestCase):
    def test_bounded_training_entrypoints_offer_help_when_run_as_files(self) -> None:
        scripts = (
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

    def test_numa_benchmark_entrypoint_is_independent_of_working_directory(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(PROJECT_ROOT / "tools" / "core_mini_numa_benchmark.py"),
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


if __name__ == "__main__":
    unittest.main()
