import contextlib
import copy
from datetime import date
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from tools import validate_evaluation_grid as grid_tool
from tools.validate_evaluation_grid import GridInvalid


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GRID_PATH = PROJECT_ROOT / "configs" / "evaluation" / "v1-grid.candidate.json"
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "evaluation-grid.schema.json"
TODAY = date(2026, 9, 26)
SYNTHETIC_REGISTER = """# Registre synthétique de test

| ID | Décision | Conséquence |
|---|---|---|
| D-015 | Mesure obligatoire. | Test. |
| D-016 | Profils logiques. | Test. |
| D-019 | Une session. | Test. |
| D-020 | Usages V1. | Test. |
| D-021 | Force de proposition. | Test. |
| D-022 | Aucune découverte réseau. | Test. |
| D-007 | Aucun accès Internet. | Test. |
| D-029 | Deux invités. | Test. |
| D-039 | Séparation évaluation / entraînement bloquante. | Test. |
| D-040 | Arène sans recouvrement avec l'évaluation. | Test. |
| D-090 | **SUPERSEDED par D-099.** Ancienne approbation. | Test. |
| D-099 | Grille approuvée (synthétique), empreinte {digest}. | Test. |
"""


def metric(document: dict, metric_id: str) -> dict:
    return next(item for item in document["metrics"] if item["id"] == metric_id)


class EvaluationGridTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = grid_tool.load_grid(GRID_PATH)
        self.directory = tempfile.TemporaryDirectory()
        self.register = Path(self.directory.name) / "decisions.md"
        self.record_digest("0" * 64)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def record_digest(self, digest: str) -> None:
        """The synthetic approving decision D-099 records this grid digest."""

        self.register.write_text(SYNTHETIC_REGISTER.format(digest=digest), encoding="utf-8")

    def check(self, document: dict, root: Path = PROJECT_ROOT) -> dict:
        return grid_tool.validate(document, root=root, decisions_path=self.register, today=TODAY)

    def refused(self, document: dict, pattern: str, root: Path = PROJECT_ROOT) -> None:
        with self.assertRaisesRegex(GridInvalid, pattern):
            self.check(document, root)

    def approve(self, document: dict, metric_id: str, root: Path = PROJECT_ROOT, **overrides: str) -> dict:
        threshold = metric(document, metric_id)["threshold"]
        digest = grid_tool.grid_sha256(document, root)
        self.record_digest(digest)
        threshold["approval"] = {
            "decision_id": "D-099",
            "approved_on": "2026-09-20",
            "grid_sha256": digest,
            "previous_status": threshold["status"],
        }
        threshold["status"] = "approved"
        threshold["approval"].update(overrides)
        return document

    def copy_repository_subset(self, document: dict) -> Path:
        """A throwaway root holding every path the grid points at, to edit fixtures safely."""

        root = Path(self.directory.name) / "root"
        paths = {document["source_document"]}
        for item in document["metrics"]:
            paths.update(item["fixture"]["paths"])
            paths.update(item["procedure"]["paths"])
        for value in paths:
            target = root / value
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PROJECT_ROOT / value, target)
        return root

    def test_candidate_grid_is_valid_against_the_real_register(self) -> None:
        summary = grid_tool.validate(self.document)
        self.assertEqual("candidate_owner_review_required", summary["status"])
        self.assertEqual(0, summary["thresholds_by_status"]["approved"])
        self.assertRegex(summary["grid_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(set(range(1, 9)), {item["axis"] for item in self.document["metrics"]})

    def test_candidate_grid_mirrors_the_proposal_document(self) -> None:
        text = (PROJECT_ROOT / self.document["source_document"]).read_text(encoding="utf-8")
        documented = set(re.findall(r"^\| (M[1-8]\.[0-9]+) ", text, flags=re.MULTILINE))
        self.assertEqual(documented, {item["id"] for item in self.document["metrics"]})

    def test_every_metric_field_is_required(self) -> None:
        for key in sorted(grid_tool.METRIC_KEYS):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.document)
                del metric(changed, "M1.5")[key]
                self.refused(changed, f"missing field\\(s\\): {key}")
        for section, keys in (("fixture", grid_tool.FIXTURE_KEYS), ("procedure", grid_tool.PROCEDURE_KEYS),
                              ("threshold", grid_tool.THRESHOLD_KEYS)):
            for key in sorted(keys):
                with self.subTest(section=section, key=key):
                    changed = copy.deepcopy(self.document)
                    del metric(changed, "M1.5")[section][key]
                    self.refused(changed, f"missing field\\(s\\): {key}")
        for key in sorted(grid_tool.TOP_LEVEL_KEYS):
            with self.subTest(top_level=key):
                changed = copy.deepcopy(self.document)
                del changed[key]
                self.refused(changed, f"missing field\\(s\\): {key}")

    def test_unknown_field_or_empty_text_is_refused(self) -> None:
        changed = copy.deepcopy(self.document)
        metric(changed, "M1.5")["weight"] = 2
        self.refused(changed, "unknown field")
        changed = copy.deepcopy(self.document)
        metric(changed, "M1.5")["procedure"]["description"] = " "
        self.refused(changed, "trimmed string")
        changed = copy.deepcopy(self.document)
        metric(changed, "M1.5")["responsible"] = "agent"
        self.refused(changed, "responsible")

    def test_unknown_gate_id_is_refused(self) -> None:
        for field, value in (("g_gates", ["G9"]), ("g_gates", ["g6"]), ("a_gates", ["A9"]), ("a_gates", []),
                             ("g_gates", ["G6", "G6"])):
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(self.document)
                metric(changed, "M1.5")[field] = value
                self.refused(changed, "gate id|non-empty unique")
        changed = copy.deepcopy(self.document)
        changed["gate_links"]["G9"] = changed["gate_links"]["G8"]
        self.refused(changed, "unknown field")

    def test_gate_absent_from_the_link_table_is_refused(self) -> None:
        changed = copy.deepcopy(self.document)
        metric(changed, "M1.5")["a_gates"] = ["A1"]
        self.refused(changed, "linked to none")

    def test_missing_fixture_path_is_refused(self) -> None:
        changed = copy.deepcopy(self.document)
        metric(changed, "M1.5")["fixture"]["paths"] = ["configs/evaluation/does-not-exist.json"]
        self.refused(changed, "does not exist")
        changed = copy.deepcopy(self.document)
        metric(changed, "M1.2")["procedure"]["paths"] = ["tools/does_not_exist.py"]
        self.refused(changed, "does not exist")
        for unsafe in ("../AGENTS.md", "/etc/passwd", "configs\\evaluation", "configs/./evaluation", "C:/x"):
            with self.subTest(path=unsafe):
                changed = copy.deepcopy(self.document)
                metric(changed, "M1.5")["fixture"]["paths"] = [unsafe]
                self.refused(changed, "safe relative path|inside the repository")

    def test_fixture_status_must_match_its_paths(self) -> None:
        changed = copy.deepcopy(self.document)
        metric(changed, "M1.5")["fixture"]["status"] = "missing"
        self.refused(changed, "must not point at a path")
        changed = copy.deepcopy(self.document)
        metric(changed, "M1.1")["fixture"]["paths"] = []
        self.refused(changed, "lists no path")
        changed = copy.deepcopy(self.document)
        metric(changed, "M1.1")["fixture"]["status"] = "planned"
        self.refused(changed, "status is unknown")

    def test_approved_threshold_requires_a_complete_pinned_approval(self) -> None:
        approved = self.approve(copy.deepcopy(self.document), "M1.5")
        summary = self.check(approved)
        self.assertEqual(1, summary["thresholds_by_status"]["approved"])
        self.assertEqual(grid_tool.grid_sha256(self.document), summary["grid_sha256"])

        changed = copy.deepcopy(self.document)
        metric(changed, "M1.5")["threshold"]["status"] = "approved"
        self.refused(changed, "without an approval record")
        for key in sorted(grid_tool.APPROVAL_KEYS):
            with self.subTest(missing=key):
                changed = self.approve(copy.deepcopy(self.document), "M1.5")
                del metric(changed, "M1.5")["threshold"]["approval"][key]
                self.refused(changed, f"missing field\\(s\\): {key}")

    def test_approval_with_a_wrong_hash_date_or_decision_is_refused(self) -> None:
        cases = (
            ({"grid_sha256": "0" * 64}, "does not match the grid content"),
            ({"grid_sha256": "ABC"}, "lowercase SHA-256"),
            ({"decision_id": "D-098"}, "not in the decision register"),
            ({"decision_id": "D-090"}, "superseded"),
            ({"decision_id": "D-35"}, "decision id"),
            ({"approved_on": "2026-09-27"}, "future"),
            ({"approved_on": "2026-02-30"}, "calendar date"),
            ({"approved_on": "26/09/2026"}, "YYYY-MM-DD"),
            ({"previous_status": "approved"}, "previous_status must be one of"),
            ({"previous_status": "confirmed"}, "was confirmed but cites no decision"),
        )
        for overrides, pattern in cases:
            with self.subTest(overrides=overrides):
                self.refused(self.approve(copy.deepcopy(self.document), "M1.5", **overrides), pattern)
        # M1.1 cites D-020: recording "confirmed" instead of its real "proposed" changes the digest.
        self.refused(self.approve(copy.deepcopy(self.document), "M1.1", previous_status="confirmed"),
                     "does not match the grid content")

    def test_approval_must_cite_the_decision_that_records_the_digest(self) -> None:
        # D-020 exists and is live, but its row does not record this grid digest.
        for decision_id in ("D-020", "D-007"):
            with self.subTest(decision_id=decision_id):
                self.refused(self.approve(copy.deepcopy(self.document), "M1.1", decision_id=decision_id),
                             f"decision {decision_id} does not record the pinned grid_sha256")
        approved = self.approve(copy.deepcopy(self.document), "M1.1")
        self.record_digest("f" * 64)
        self.refused(approved, "D-099 does not record the pinned grid_sha256")

    def test_status_flip_after_approval_breaks_the_pinned_hash(self) -> None:
        approved = self.approve(copy.deepcopy(self.document), "M1.5")
        self.assertEqual("proposed", metric(approved, "M1.1")["threshold"]["status"])
        metric(approved, "M1.1")["threshold"]["status"] = "confirmed"  # cites D-020, so formally allowed
        self.refused(approved, "does not match the grid content")

    def test_fixture_file_edited_after_approval_breaks_the_pinned_hash(self) -> None:
        root = self.copy_repository_subset(self.document)
        approved = self.approve(copy.deepcopy(self.document), "M1.5", root=root)
        self.assertEqual(1, self.check(approved, root)["thresholds_by_status"]["approved"])
        fixture = root / "configs" / "evaluation" / "v1-safety.candidate.json"
        fixture.write_bytes(fixture.read_bytes().replace(b"CANARI-INJ-01", b"CANARI-INJ-0X", 1))
        self.refused(approved, "does not match the grid content", root)

    def test_fixture_digest_ignores_line_endings_only(self) -> None:
        root = self.copy_repository_subset(self.document)
        fixture = root / "configs" / "evaluation" / "core-30m-e1.candidate.json"
        lf = fixture.read_bytes().replace(b"\r\n", b"\n")
        fixture.write_bytes(lf)
        digest = grid_tool.grid_sha256(self.document, root)
        fixture.write_bytes(lf.replace(b"\n", b"\r\n"))
        self.assertEqual(digest, grid_tool.grid_sha256(self.document, root))
        fixture.write_bytes(lf + b" ")
        self.assertNotEqual(digest, grid_tool.grid_sha256(self.document, root))

    def test_fixture_path_must_be_a_file(self) -> None:
        changed = copy.deepcopy(self.document)
        metric(changed, "M1.5")["fixture"]["paths"] = ["configs/evaluation"]
        self.refused(changed, "must be a regular file")

    def test_threshold_tuned_after_approval_breaks_the_pinned_hash(self) -> None:
        approved = self.approve(copy.deepcopy(self.document), "M1.5")
        metric(approved, "M1.5")["threshold"]["statement"] = "Au moins 30/50 accept."
        self.refused(approved, "does not match the grid content")
        approved = self.approve(copy.deepcopy(self.document), "M1.5")
        metric(approved, "M3.4")["threshold"]["statement"] = "Écart FR/EN d'au plus 30 points."
        self.refused(approved, "does not match the grid content")

    def test_unapproved_threshold_cannot_carry_an_approval(self) -> None:
        changed = self.approve(copy.deepcopy(self.document), "M1.5")
        metric(changed, "M1.5")["threshold"]["status"] = "proposed"
        self.refused(changed, "carries an approval")

    def test_confirmed_threshold_must_cite_a_live_decision(self) -> None:
        changed = copy.deepcopy(self.document)
        metric(changed, "M7.2")["threshold"]["decisions"] = []
        self.refused(changed, "cites no decision")
        changed = copy.deepcopy(self.document)
        metric(changed, "M7.2")["threshold"]["decisions"] = ["D-090"]
        self.refused(changed, "superseded")
        changed = copy.deepcopy(self.document)
        metric(changed, "M1.1")["threshold"]["decisions"] = ["D-777"]
        self.refused(changed, "not in the decision register")
        changed = copy.deepcopy(self.document)
        metric(changed, "M1.1")["threshold"]["status"] = "accepted"
        self.refused(changed, "status is unknown")

    def test_grid_status_axes_and_coverage_are_enforced(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["status"] = "approved"
        self.refused(changed, "status must remain")
        changed = copy.deepcopy(self.document)
        changed["metrics"] = [item for item in changed["metrics"] if item["axis"] != 7]
        self.refused(changed, "axes without metric: 7")
        changed = copy.deepcopy(self.document)
        metric(changed, "M1.5")["axis"] = 2
        self.refused(changed, "does not match its id")
        changed = copy.deepcopy(self.document)
        changed["metrics"].append(copy.deepcopy(metric(changed, "M1.5")))
        self.refused(changed, "must be unique")
        changed = copy.deepcopy(self.document)
        changed["axes"] = changed["axes"][:7]
        self.refused(changed, "exactly 8 axes")

    def test_digest_ignores_only_the_approval_state(self) -> None:
        digest = grid_tool.grid_sha256(self.document)
        approved = self.approve(copy.deepcopy(self.document), "M1.5")
        self.assertEqual(digest, grid_tool.grid_sha256(approved))
        changed = copy.deepcopy(self.document)
        metric(changed, "M1.5")["g_gates"] = ["G6", "G8"]
        self.assertNotEqual(digest, grid_tool.grid_sha256(changed))

    def test_strict_json_loading(self) -> None:
        directory = Path(self.directory.name)
        cases = {
            "duplicate.json": b'{"status": "a", "status": "b"}',
            "nan.json": b'{"value": NaN}',
            "list.json": b"[]",
            "latin1.json": "{\"titre\": \"é\"}".encode("latin-1"),
            "empty.json": b"",
        }
        for name, payload in cases.items():
            with self.subTest(name=name):
                (directory / name).write_bytes(payload)
                with self.assertRaises(GridInvalid):
                    grid_tool.load_grid(directory / name)
        with self.assertRaisesRegex(GridInvalid, "regular file"):
            grid_tool.load_grid(directory)

    def test_schema_tracks_the_validator_contract(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        defs = schema["$defs"]
        self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), grid_tool.TOP_LEVEL_KEYS)
        self.assertEqual(schema["properties"]["schema_version"]["const"], grid_tool.SCHEMA_VERSION)
        self.assertEqual(schema["properties"]["status"]["const"], grid_tool.GRID_STATUS)
        self.assertEqual(set(defs["metric"]["required"]), grid_tool.METRIC_KEYS)
        self.assertEqual(set(defs["fixture"]["required"]), grid_tool.FIXTURE_KEYS)
        self.assertEqual(set(defs["procedure"]["required"]), grid_tool.PROCEDURE_KEYS)
        self.assertEqual(set(defs["threshold"]["required"]), grid_tool.THRESHOLD_KEYS)
        self.assertEqual(set(defs["threshold"]["properties"]), grid_tool.THRESHOLD_KEYS | {"approval"})
        self.assertEqual(set(defs["approval"]["required"]), grid_tool.APPROVAL_KEYS)
        self.assertEqual(tuple(defs["fixture"]["properties"]["status"]["enum"]), grid_tool.FIXTURE_STATUSES)
        self.assertEqual(tuple(defs["threshold"]["properties"]["status"]["enum"]), grid_tool.THRESHOLD_STATUSES)
        self.assertEqual(tuple(defs["linkLevel"]["enum"]), grid_tool.LINK_LEVELS)
        self.assertEqual(tuple(defs["gGate"]["enum"]), grid_tool.G_GATES)
        self.assertEqual(tuple(defs["aGate"]["enum"]), grid_tool.A_GATES)
        self.assertEqual(tuple(defs["metric"]["properties"]["responsible"]["enum"]), grid_tool.RESPONSIBLE_ROLES)
        self.assertEqual(set(schema["properties"]["gate_links"]["required"]), set(grid_tool.G_GATES))
        self.assertEqual(set(defs["gateLinkRow"]["required"]), set(grid_tool.A_GATES))

    def test_command_line_prints_a_digest_or_refuses(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, grid_tool.main([str(GRID_PATH), "--print-digest"]))
        self.assertEqual(grid_tool.grid_sha256(self.document), output.getvalue().strip())
        broken = Path(self.directory.name) / "grid.json"
        changed = copy.deepcopy(self.document)
        metric(changed, "M1.5")["g_gates"] = ["G9"]
        broken.write_text(json.dumps(changed), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(1, grid_tool.main([str(broken)]))
        self.assertEqual("", output.getvalue())
        self.assertIn("unknown gate id", error.getvalue())


if __name__ == "__main__":
    unittest.main()
