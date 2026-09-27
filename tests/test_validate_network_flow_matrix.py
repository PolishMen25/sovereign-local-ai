"""Tests for the static default-deny network flow matrix validator.

Every matrix here is synthetic. Address-like and host-like probes are built at
runtime from documentation-reserved ranges and names (RFC 5737, RFC 3849,
RFC 2606) so that this file carries no infrastructure literal.
"""

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from tests._temp_support import sovereign_temporary_directory
from tools import validate_network_flow_matrix as matrix_tool


PROJECT_ROOT = Path(__file__).parents[1]
EXAMPLE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "network-flow-matrix.synthetic.json"
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "network-flow-matrix.schema.json"
TOOL_PATH = PROJECT_ROOT / "tools" / "validate_network_flow_matrix.py"
JUSTIFICATION = "Flux synthétique de test, sans adresse ni nom d'hôte."


def example() -> dict:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def flow(flow_id: str, origin: str, destination: str, direction: str, identity: str,
         data_class: str = "management") -> dict:
    return {
        "flow_id": flow_id,
        "origin_zone": origin,
        "destination_zone": destination,
        "direction": direction,
        "identity": identity,
        "data_class": data_class,
        "justification": JUSTIFICATION,
        "approval_ref": "pending-owner-approval",
    }


def with_flows(*extra: dict) -> dict:
    document = example()
    document["flows"].extend(extra)
    return document


class ExampleAndSchemaTests(unittest.TestCase):
    def test_synthetic_example_is_valid_and_stays_proposed(self) -> None:
        summary = matrix_tool.validate(example())
        self.assertEqual({"status": "proposed", "synthetic": True, "flows": 8}, summary)
        document = example()
        self.assertEqual("deny", document["default_policy"])
        self.assertEqual({"pending-owner-approval"}, {item["approval_ref"] for item in document["flows"]})

    def test_example_uses_only_abstract_zones_and_redacted_text(self) -> None:
        document = example()
        for item in document["flows"]:
            self.assertIn(item["origin_zone"], matrix_tool.ZONES)
            self.assertIn(item["destination_zone"], matrix_tool.ZONES)
            for pattern in matrix_tool.REDACTION_PATTERNS:
                self.assertIsNone(pattern.search(item["justification"]))

    def test_schema_tracks_the_validator_contract(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(matrix_tool.TOP_LEVEL_KEYS))
        properties = schema["properties"]
        self.assertEqual(matrix_tool.SCHEMA_VERSION, properties["schema_version"]["const"])
        self.assertEqual(matrix_tool.DEFAULT_POLICY, properties["default_policy"]["const"])
        self.assertEqual(set(properties["status"]["enum"]), set(matrix_tool.STATUSES))
        self.assertEqual(matrix_tool.MATRIX_ID_PATTERN, properties["matrix_id"]["pattern"])
        self.assertEqual(
            list(matrix_tool.MATRIX_ID_LENGTH),
            [properties["matrix_id"]["minLength"], properties["matrix_id"]["maxLength"]],
        )
        self.assertEqual(matrix_tool.MINIMUM_FLOWS, properties["flows"]["minItems"])
        self.assertEqual(matrix_tool.MAXIMUM_FLOWS, properties["flows"]["maxItems"])
        definitions = schema["$defs"]
        self.assertEqual(set(definitions["zone"]["enum"]), set(matrix_tool.ZONES))
        flow_schema = definitions["flow"]
        self.assertFalse(flow_schema["additionalProperties"])
        self.assertEqual(set(flow_schema["required"]), set(matrix_tool.FLOW_KEYS))
        flow_properties = flow_schema["properties"]
        self.assertEqual(set(flow_properties["direction"]["enum"]), set(matrix_tool.DIRECTIONS))
        self.assertEqual(set(flow_properties["data_class"]["enum"]), set(matrix_tool.DATA_CLASSES))
        self.assertEqual(matrix_tool.FLOW_ID_PATTERN, flow_properties["flow_id"]["pattern"])
        self.assertEqual(matrix_tool.IDENTITY_PATTERN, flow_properties["identity"]["pattern"])
        self.assertEqual(matrix_tool.APPROVAL_REF_PATTERN, flow_properties["approval_ref"]["pattern"])
        self.assertEqual(
            list(matrix_tool.IDENTITY_LENGTH),
            [flow_properties["identity"]["minLength"], flow_properties["identity"]["maxLength"]],
        )
        self.assertEqual(
            list(matrix_tool.JUSTIFICATION_LENGTH),
            [flow_properties["justification"]["minLength"], flow_properties["justification"]["maxLength"]],
        )
        synthetic_rule, approved_rule = schema["allOf"]
        self.assertEqual(
            matrix_tool.PENDING_APPROVAL,
            synthetic_rule["then"]["properties"]["flows"]["items"]["properties"]["approval_ref"]["const"],
        )
        self.assertEqual(
            matrix_tool.APPROVED_REF_PATTERN,
            approved_rule["then"]["properties"]["flows"]["items"]["properties"]["approval_ref"]["pattern"],
        )
        conditions = {
            (json.dumps(rule["if"], sort_keys=True), json.dumps(rule["then"], sort_keys=True))
            for rule in flow_schema["allOf"]
        }
        expected = {
            (
                json.dumps({"properties": {"destination_zone": {"const": matrix_tool.APPEND_ONLY_ZONE}}, "required": ["destination_zone"]}, sort_keys=True),
                json.dumps({"properties": {"direction": {"const": "push"}}}, sort_keys=True),
            ),
            (
                json.dumps({"properties": {"origin_zone": {"const": matrix_tool.INTERNET_ZONE}}, "required": ["origin_zone"]}, sort_keys=True),
                json.dumps({"properties": {"destination_zone": {"const": matrix_tool.INTERNET_PEER_ZONE}}}, sort_keys=True),
            ),
            (
                json.dumps({"properties": {"destination_zone": {"const": matrix_tool.INTERNET_ZONE}}, "required": ["destination_zone"]}, sort_keys=True),
                json.dumps({"properties": {"origin_zone": {"const": matrix_tool.INTERNET_PEER_ZONE}}}, sort_keys=True),
            ),
        }
        self.assertEqual(expected, conditions)

    def test_graph_zone_roles_only_name_known_zones(self) -> None:
        for zones in (
            matrix_tool.EXPOSED_ZONES,
            matrix_tool.PROTECTED_ZONES,
            matrix_tool.NO_EGRESS_ZONES,
            matrix_tool.RELAY_GUARDED_ZONES,
            {matrix_tool.INSPECTION_ZONE, matrix_tool.APPEND_ONLY_ZONE},
        ):
            self.assertTrue(set(zones) <= matrix_tool.ZONES)
        self.assertFalse(matrix_tool.EXPOSED_ZONES & matrix_tool.PROTECTED_ZONES)

    def test_tool_has_no_network_capability(self) -> None:
        source = TOOL_PATH.read_text(encoding="utf-8")
        for module in ("socket", "urllib", "http.client", "ssl", "subprocess"):
            self.assertNotIn(f"import {module}", source)


class FlowContractTests(unittest.TestCase):
    def assertRefused(self, document: dict, message: str) -> None:
        with self.assertRaisesRegex(matrix_tool.MatrixRefused, message):
            matrix_tool.validate(document)

    def test_unknown_zones_are_refused(self) -> None:
        for field in ("origin_zone", "destination_zone"):
            with self.subTest(field=field):
                document = example()
                document["flows"][1][field] = "guest-wifi"
                self.assertRefused(document, f"{field} is not a known zone")

    def test_missing_or_blank_justification_is_refused(self) -> None:
        missing = example()
        del missing["flows"][0]["justification"]
        self.assertRefused(missing, "keys must be exactly")
        for value in ("", " " * 40, "trop court", 42, None):
            with self.subTest(value=value):
                blank = example()
                blank["flows"][0]["justification"] = value
                self.assertRefused(blank, "justification is missing")

    def test_intrazone_flow_is_refused(self) -> None:
        self.assertRefused(with_flows(flow("NF-90", "admin", "admin", "push", "loop-probe")), "two distinct zones")

    def test_invalid_enumerations_and_identifiers_are_refused(self) -> None:
        cases = (
            ("direction", "both", "direction is invalid"),
            ("data_class", "anything", "data_class is invalid"),
            ("flow_id", "F-1", "flow_id is invalid"),
            ("identity", "Collector_01", "identity is invalid"),
            ("identity", "ct-one-two-three-four-five-six", "identity is invalid"),
            ("approval_ref", "approved", "approval_ref is invalid"),
        )
        for field, value, message in cases:
            with self.subTest(field=field, value=value):
                document = example()
                document["flows"][2][field] = value
                self.assertRefused(document, message)

    def test_top_level_contract_is_exact(self) -> None:
        cases = (
            ("default_policy", "allow", "default_policy must be deny"),
            ("schema_version", "network-flow-matrix.v0", "unsupported schema_version"),
            ("status", "accepted", "status is invalid"),
            ("synthetic", "yes", "synthetic must be a boolean"),
            ("matrix_id", "Matrix One", "matrix_id is invalid"),
            ("flows", [], "bounded non-empty list"),
        )
        for field, value, message in cases:
            with self.subTest(field=field):
                document = example()
                document[field] = value
                self.assertRefused(document, message)
        extra = example()
        extra["allow_all"] = True
        self.assertRefused(extra, "matrix keys must be exactly")
        self.assertRefused([], "matrix keys must be exactly")

    def test_flow_count_is_bounded(self) -> None:
        document = example()
        document["flows"] = [
            flow(f"NF-{index:03d}", "admin", "coding-agent", "push", "probe-" + "".join(
                chr(ord("a") + int(digit)) for digit in f"{index:03d}"
            ))
            for index in range(matrix_tool.MAXIMUM_FLOWS + 1)
        ]
        self.assertRefused(document, "bounded non-empty list")

    def test_flow_ids_and_identities_are_unique(self) -> None:
        duplicate_id = with_flows(flow("NF-01", "admin", "coding-agent", "push", "admin-probe"))
        self.assertRefused(duplicate_id, "flow_id values must be unique")
        shared_identity = with_flows(flow("NF-90", "admin", "coding-agent", "push", "raw-archiver"))
        self.assertRefused(shared_identity, "dedicated to exactly one flow")

    def test_redaction_refuses_infrastructure_tokens_without_echoing_them(self) -> None:
        probes = {
            "ipv4": ".".join(["192", "0", "2", "17"]),
            "ipv4-prefix": ".".join(["198", "51", "100"]) + ".0/24",
            "ipv6": ":".join(["2001", "db8", "", "5"]),
            "mac": "-".join(["00", "00", "5e", "00", "53", "af"]),
            "url": "https" + "://" + "portal",
            "hostname": "nas" + "." + "example" + "." + "invalid",
            "short-hostname": "core" + "." + "lan",
            "email": "owner" + "@" + "example",
            "unix-path": "partage " + "/" + "volume1" + "/" + "raw",
            "windows-path": "C:" + "\\" + "data",
            "container-id": "CT" + " " + "9" + "9" + "9",
            "vm-id": "vm" + "-" + "4" + "2",
            "control": "texte‮gaid",
        }
        for label, probe in probes.items():
            with self.subTest(probe=label):
                document = example()
                document["flows"][3]["justification"] = f"Flux synthétique de test qui mentionne {probe} ici."
                with self.assertRaisesRegex(matrix_tool.MatrixRefused, "NF-04: justification contains") as caught:
                    matrix_tool.validate(document)
                self.assertNotIn(probe, str(caught.exception))
        matrix_probe = example()
        matrix_probe["matrix_id"] = "lab-ct-" + "1" + "0" + "3"
        self.assertRefused(matrix_probe, "matrix_id contains")

    def test_plain_french_text_is_accepted(self) -> None:
        document = example()
        document["flows"][0]["justification"] = (
            "F0/F1 : requête déclassifiée, p. ex. une recherche documentaire ; "
            "licence Etalab-2.0 vérifiée, voir ADR-0004 point 4 et D-029."
        )
        matrix_tool.validate(document)


class GraphRuleTests(unittest.TestCase):
    def assertRefused(self, document: dict, message: str) -> None:
        with self.assertRaisesRegex(matrix_tool.MatrixRefused, message):
            matrix_tool.validate(document)

    def test_direct_internet_links_outside_the_dmz_are_refused(self) -> None:
        for origin, destination in (
            ("internet", "ia-core"),
            ("ia-core", "internet"),
            ("admin", "internet"),
            ("internet", "storage-raw"),
            ("local-clients", "internet"),
        ):
            with self.subTest(origin=origin, destination=destination):
                document = with_flows(flow("NF-90", origin, destination, "push", "shortcut-probe"))
                self.assertRefused(document, "only the dmz zone may exchange with the internet zone")

    def test_internet_to_ia_core_paths_that_bypass_quarantine_are_refused(self) -> None:
        cases = {
            "dmz-to-core": [flow("NF-90", "dmz", "ia-core", "push", "bypass-probe")],
            "dmz-via-transfer": [
                flow("NF-90", "dmz", "transfer-airlock", "push", "bypass-writer"),
                flow("NF-91", "ia-core", "transfer-airlock", "pull", "bypass-reader"),
            ],
            "dmz-via-internal-storage": [
                flow("NF-90", "dmz", "storage-internal", "push", "bypass-writer"),
            ],
            "core-reads-raw-archive": [
                flow("NF-90", "storage-raw", "ia-core", "push", "raw-replayer"),
            ],
            "single-admin-plane": [
                flow("NF-90", "admin", "dmz", "bidirectional", "dmz-operator"),
                flow("NF-91", "admin", "ia-core", "bidirectional", "core-operator"),
            ],
        }
        for label, extra in cases.items():
            with self.subTest(case=label):
                self.assertRefused(with_flows(*extra), "reaches (ia-core|storage-internal) without crossing quarantine")

    def test_internal_data_never_reaches_the_dmz_or_internet(self) -> None:
        cases = {
            "core-pushes-to-quarantine-which-feeds-dmz": [
                flow("NF-90", "ia-core", "quarantine", "push", "core-exporter"),
                flow("NF-91", "quarantine", "dmz", "push", "quarantine-exporter"),
            ],
            "dmz-reads-raw-archive": [flow("NF-90", "storage-raw", "dmz", "push", "raw-reader")],
            "dmz-pulls-internal-storage": [flow("NF-90", "dmz", "storage-internal", "pull", "internal-reader")],
            "client-relays-sessions-to-collector": [
                flow("NF-90", "local-clients", "dmz", "push", "conversation-relay", "conversation-export"),
            ],
        }
        for label, extra in cases.items():
            with self.subTest(case=label):
                self.assertRefused(with_flows(*extra), "a data path from an internal zone reaches (dmz|internet)")

    def test_raw_archive_is_append_only(self) -> None:
        for direction in ("pull", "bidirectional"):
            with self.subTest(direction=direction):
                document = example()
                document["flows"][2]["direction"] = direction
                self.assertRefused(document, "storage-raw is append-only")

    def test_bidirectional_relay_through_storage_is_refused(self) -> None:
        internal = with_flows(flow("NF-90", "admin", "storage-internal", "bidirectional", "storage-operator"))
        self.assertRefused(internal, "storage-internal would relay data both ways")
        raw = with_flows(
            flow("NF-90", "storage-raw", "quarantine", "push", "raw-to-quarantine"),
            flow("NF-91", "quarantine", "storage-raw", "push", "quarantine-to-raw"),
            flow("NF-92", "storage-raw", "admin", "push", "raw-to-admin"),
            flow("NF-93", "admin", "storage-raw", "push", "admin-to-raw"),
        )
        self.assertRefused(raw, "storage-raw would relay data both ways")
        transfer = with_flows(
            flow("NF-90", "quarantine", "transfer-airlock", "push", "quarantine-writer"),
            flow("NF-91", "coding-agent", "transfer-airlock", "bidirectional", "agent-exchange"),
            flow("NF-92", "transfer-airlock", "quarantine", "push", "airlock-feedback"),
        )
        self.assertRefused(transfer, "transfer-airlock would relay data both ways")

    def test_one_way_relays_that_keep_the_quarantine_break_are_accepted(self) -> None:
        document = with_flows(
            flow("NF-90", "quarantine", "transfer-airlock", "push", "airlock-writer", "promoted-derivative"),
            flow("NF-91", "transfer-airlock", "storage-internal", "push", "import-writer", "promoted-derivative"),
            flow("NF-92", "admin", "ia-core", "bidirectional", "core-operator"),
        )
        self.assertEqual(11, matrix_tool.validate(document)["flows"])

    def test_pull_reverses_the_data_edge(self) -> None:
        edges = matrix_tool.data_edges([
            flow("NF-01", "ia-core", "storage-internal", "pull", "reader"),
            flow("NF-02", "dmz", "quarantine", "push", "writer"),
            flow("NF-03", "local-clients", "interface-airlock", "bidirectional", "session"),
        ])
        self.assertEqual(
            {
                ("storage-internal", "ia-core"),
                ("dmz", "quarantine"),
                ("local-clients", "interface-airlock"),
                ("interface-airlock", "local-clients"),
            },
            edges,
        )


class ApprovalStateTests(unittest.TestCase):
    def test_synthetic_matrix_can_never_be_approved(self) -> None:
        approved = example()
        approved["status"] = "approved"
        with self.assertRaisesRegex(matrix_tool.MatrixRefused, "synthetic matrix stays proposed"):
            matrix_tool.validate(approved)
        cited = example()
        cited["flows"][0]["approval_ref"] = "D-000"
        with self.assertRaisesRegex(matrix_tool.MatrixRefused, "synthetic matrix stays proposed"):
            matrix_tool.validate(cited)

    def test_approved_matrix_needs_a_recorded_reference_for_every_flow(self) -> None:
        real = example()
        real["synthetic"] = False
        real["status"] = "approved"
        with self.assertRaisesRegex(matrix_tool.MatrixRefused, "approved matrix must be real"):
            matrix_tool.validate(real)
        for item in real["flows"]:
            item["approval_ref"] = "D-000"
        real["flows"][-1]["approval_ref"] = "ADR-0000"
        self.assertEqual("approved", matrix_tool.validate(real)["status"])

    def test_real_proposed_matrix_may_mix_pending_and_recorded_references(self) -> None:
        proposed = example()
        proposed["synthetic"] = False
        proposed["flows"][0]["approval_ref"] = "D-000"
        self.assertEqual("proposed", matrix_tool.validate(proposed)["status"])


class StrictInputTests(unittest.TestCase):
    def test_parser_refuses_non_strict_json(self) -> None:
        cases = {
            "duplicate-key": b'{"status": "proposed", "status": "approved"}',
            "nan": b'{"value": NaN}',
            "infinity": b'{"value": -Infinity}',
            "bom": b"\xef\xbb\xbf{}",
            "latin-1": '{"note": "é"}'.encode("latin-1"),
            "nul": b'{"a": "\x00"}',
            "truncated": b'{"a": ',
            "empty": b"",
            "deep": b"[" * 100000 + b"]" * 100000,
        }
        for label, payload in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(matrix_tool.MatrixRefused):
                    matrix_tool.parse_matrix(payload)

    def test_reader_bounds_size_and_file_type(self) -> None:
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            oversize = root / "oversize.json"
            oversize.write_bytes(b" " * (matrix_tool.MAXIMUM_MATRIX_BYTES + 1))
            empty = root / "empty.json"
            empty.write_bytes(b"")
            for path in (oversize, empty, root, root / "missing.json"):
                with self.subTest(path=path.name):
                    with self.assertRaises(matrix_tool.MatrixRefused):
                        matrix_tool.read_matrix_bytes(path)
            valid = root / "valid.json"
            valid.write_bytes(EXAMPLE_PATH.read_bytes())
            self.assertEqual(EXAMPLE_PATH.read_bytes(), matrix_tool.read_matrix_bytes(valid))

    def test_reader_refuses_symbolic_links(self) -> None:
        with sovereign_temporary_directory() as directory:
            root = Path(directory)
            target = root / "target.json"
            target.write_bytes(EXAMPLE_PATH.read_bytes())
            link = root / "link.json"
            try:
                os.symlink(target, link)
            except (OSError, NotImplementedError):
                self.skipTest("symbolic links are unavailable on this platform")
            with self.assertRaisesRegex(matrix_tool.MatrixRefused, "regular file"):
                matrix_tool.read_matrix_bytes(link)


class CommandLineTests(unittest.TestCase):
    def run_main(self, argv: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = matrix_tool.main(argv)
            except SystemExit as exit_request:
                code = exit_request.code
        return code, stdout.getvalue(), stderr.getvalue()

    def test_exit_codes_and_content_free_messages(self) -> None:
        code, stdout, stderr = self.run_main([str(EXAMPLE_PATH)])
        self.assertEqual(0, code, stderr)
        self.assertEqual("valid network flow matrix: status=proposed synthetic=true flows=8\n", stdout)
        with sovereign_temporary_directory() as directory:
            document = example()
            secret_like = "marqueur-" + "confidentiel-" + "9f3a"
            document["flows"][0]["justification"] = "Flux sans relais : " + secret_like + " et nas" + "." + "invalid"
            invalid = Path(directory) / "invalid.json"
            invalid.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            code, stdout, stderr = self.run_main([str(invalid)])
        self.assertEqual(1, code)
        self.assertEqual("", stdout)
        self.assertTrue(stderr.startswith("invalid network flow matrix: "))
        self.assertNotIn(secret_like, stderr)
        code, _, _ = self.run_main([])
        self.assertEqual(2, code)

    def test_file_entrypoint_is_independent_of_working_directory(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-B", str(TOOL_PATH), str(EXAMPLE_PATH)],
            cwd=PROJECT_ROOT.parent,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("valid network flow matrix", completed.stdout)


if __name__ == "__main__":
    unittest.main()
