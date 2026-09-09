from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.build_extended_corpus_splits import MANIFEST_NAME, build


def record_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


class ExtendedCorpusSplitTests(unittest.TestCase):
    def inputs(self, root: Path) -> tuple[Path, Path, Path]:
        extended, validation, test = root / "extended.jsonl", root / "validation.jsonl", root / "test.jsonl"
        write_jsonl(extended, [
            {"text": "keep alpha", "package": "alpha"},
            {"text": "leaked validation", "package": "prometheus"},
            {"text": "leaked test", "package": "docker"},
            *({"text": f"keep {number}", "package": "beta"} for number in range(300)),
        ])
        write_jsonl(validation, [{"record_id": record_id("leaked validation"), "text": "leaked validation"}])
        write_jsonl(test, [{"record_id": record_id("leaked test"), "text": "leaked test"}])
        return extended, validation, test

    def test_removes_holdouts_and_keeps_package_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            extended, validation, test = self.inputs(root)
            output = root / "output"
            manifest = build(extended_path=extended, pilot_validation_path=validation, pilot_test_path=test, output_dir=output)
            self.assertEqual(manifest["excluded"]["pilot_v3_holdout"], 2)
            self.assertEqual(sum(item["record_count"] for item in manifest["splits"].values()), 301)
            combined = "".join((output / f"{split}.jsonl").read_text(encoding="utf-8") for split in ("train", "validation", "test"))
            self.assertNotIn("leaked validation", combined)
            self.assertNotIn("leaked test", combined)
            self.assertIn('"package":"beta"', combined)
            self.assertTrue((output / MANIFEST_NAME).is_file())

    def test_refuses_duplicate_extended_text_and_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            extended, validation, test = self.inputs(root)
            with extended.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"text": "keep alpha", "package": "other"}) + "\n")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                build(extended_path=extended, pilot_validation_path=validation, pilot_test_path=test, output_dir=root / "output")
            (root / "existing").mkdir()
            with self.assertRaisesRegex(ValueError, "already exists"):
                build(extended_path=extended, pilot_validation_path=validation, pilot_test_path=test, output_dir=root / "existing")

    def test_refuses_holdout_identity_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            extended, validation, test = self.inputs(root)
            write_jsonl(test, [{"record_id": "0" * 64, "text": "leaked test"}])
            with self.assertRaisesRegex(ValueError, "identity"):
                build(extended_path=extended, pilot_validation_path=validation, pilot_test_path=test, output_dir=root / "output")


if __name__ == "__main__":
    unittest.main()
