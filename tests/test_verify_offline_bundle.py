import hashlib
from pathlib import Path
import unittest

from tools.verify_offline_bundle import validate_lock, verify_bundle


class VerifyOfflineBundleTests(unittest.TestCase):
    VALID_FIXTURE = Path(__file__).parent / "fixtures" / "offline-bundle-valid"
    INVALID_FIXTURE = Path(__file__).parent / "fixtures" / "offline-bundle-invalid"

    def _lock(self, filename: str, content: bytes) -> dict:
        return {
            "schema_version": "0.1.0",
            "policy": {
                "cpu_only": True,
                "offline_install_only": True,
                "forbidden_filename_markers": ["cuda", "nvidia", "rocm"],
            },
            "packages": [
                {
                    "filename": filename,
                    "bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            ],
        }

    def test_accepts_exact_bundle(self) -> None:
        filename = "demo-1.0-py3-none-any.whl"
        content = (self.VALID_FIXTURE / filename).read_bytes()
        self.assertEqual(
            verify_bundle(self._lock(filename, content), self.VALID_FIXTURE),
            [],
        )

    def test_rejects_hash_mismatch_and_unexpected_wheel(self) -> None:
        filename = "demo-1.0-py3-none-any.whl"
        content = (self.INVALID_FIXTURE / filename).read_bytes()
        lock = self._lock(filename, content)
        lock["packages"][0]["sha256"] = "0" * 64
        errors = verify_bundle(lock, self.INVALID_FIXTURE)
        self.assertIn("sha256 mismatch: demo-1.0-py3-none-any.whl", errors)
        self.assertIn("unexpected wheel: extra-1.0-py3-none-any.whl", errors)

    def test_rejects_forbidden_accelerator_marker(self) -> None:
        content = b"fixture"
        filename = "nvidia-runtime-1.0-py3-none-any.whl"
        errors = verify_bundle(self._lock(filename, content), self.VALID_FIXTURE)
        self.assertIn(
            "forbidden marker 'nvidia' in nvidia-runtime-1.0-py3-none-any.whl",
            errors,
        )

    def test_rejects_non_cpu_lock(self) -> None:
        with self.assertRaisesRegex(ValueError, "CPU-only"):
            validate_lock(
                {
                    "schema_version": "0.1.0",
                    "policy": {"cpu_only": False, "offline_install_only": True},
                    "packages": [],
                }
            )

    def test_rejects_path_traversal_from_lock(self) -> None:
        lock = self._lock("../outside-1.0-py3-none-any.whl", b"fixture")
        errors = verify_bundle(lock, self.VALID_FIXTURE)
        self.assertIn(
            "unsafe package filename in lock: ../outside-1.0-py3-none-any.whl",
            errors,
        )


if __name__ == "__main__":
    unittest.main()
