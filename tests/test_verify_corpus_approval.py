import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.verify_corpus_approval import verify_corpus_approval


def source(name: str = "Example", license_name: str = "MIT", sha256: str = "a" * 64) -> dict:
    return {"name": name, "url": "https://example.invalid/repo", "license_detected": license_name, "sha256": sha256}


class CorpusApprovalTests(unittest.TestCase):
    def write_json(self, path: Path, value: dict) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")

    def candidate(self) -> dict:
        return {"sources": [source()]}

    def approved(self, item: dict | None = None) -> dict:
        return {"approved_by": "owner", "approved_at": "2026-09-08T12:00:00Z", "candidate_policy_commit": "bf690bd", "sources": [item or source()]}

    def test_absent_approval_is_refused(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory); candidate = root / "candidate.json"
            self.write_json(candidate, self.candidate())
            with self.assertRaisesRegex(ValueError, "absent"):
                verify_corpus_approval(candidate_path=candidate, approved_path=root / "approved.json")

    def test_pending_sha_is_refused(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory); candidate = root / "candidate.json"; approved = root / "approved.json"
            self.write_json(candidate, self.candidate()); self.write_json(approved, self.approved(source(sha256="pending")))
            with self.assertRaisesRegex(ValueError, "unapproved sha256"):
                verify_corpus_approval(candidate_path=candidate, approved_path=approved)

    def test_non_permissive_license_is_refused(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory); candidate = root / "candidate.json"; approved = root / "approved.json"
            item = source(license_name="CC-BY-4.0"); self.write_json(candidate, {"sources": [item]}); self.write_json(approved, self.approved(item))
            with self.assertRaisesRegex(ValueError, "non-permissive"):
                verify_corpus_approval(candidate_path=candidate, approved_path=approved)

    def test_divergent_source_list_is_refused(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory); candidate = root / "candidate.json"; approved = root / "approved.json"
            self.write_json(candidate, self.candidate()); self.write_json(approved, self.approved(source(name="Different")))
            with self.assertRaisesRegex(ValueError, "differs"):
                verify_corpus_approval(candidate_path=candidate, approved_path=approved)

    def test_matching_approved_sources_succeed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory); candidate = root / "candidate.json"; approved = root / "approved.json"
            self.write_json(candidate, self.candidate()); self.write_json(approved, self.approved())
            self.assertEqual(verify_corpus_approval(candidate_path=candidate, approved_path=approved)["source_count"], 1)
