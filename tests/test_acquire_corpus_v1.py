from __future__ import annotations

import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.acquire_corpus_v1 import acquire, archive_url


def source(name: str = "FastAPI") -> dict[str, str]:
    return {"name": name, "url": "https://github.com/fastapi/fastapi/tree/0.115.0", "version_or_commit_pin": "0.115.0"}


class AcquireCorpusV1Tests(unittest.TestCase):
    def test_builds_exact_tag_archive_url(self) -> None:
        self.assertEqual(archive_url(source()), "https://github.com/fastapi/fastapi/archive/refs/tags/0.115.0.tar.gz")

    def test_rejects_url_pin_mismatch(self) -> None:
        bad = source()
        bad["version_or_commit_pin"] = "0.114.0"
        with self.assertRaisesRegex(ValueError, "does not match"):
            archive_url(bad)

    def test_requires_exactly_ten_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = root / "policy.json"
            policy.write_text(json.dumps({"sources": [source()]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exactly 10"):
                acquire(policy, root)

    def test_refuses_existing_destination_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = root / "policy.json"
            entries = [source(f"Source-{index}") for index in range(10)]
            for entry in entries:
                entry["url"] = "https://github.com/fastapi/fastapi/tree/0.115.0"
            policy.write_text(json.dumps({"sources": entries}), encoding="utf-8")
            (root / "source-0-0.115.0.tar.gz").write_bytes(b"existing")
            with self.assertRaisesRegex(ValueError, "existing"):
                acquire(policy, root)


if __name__ == "__main__":
    unittest.main()
