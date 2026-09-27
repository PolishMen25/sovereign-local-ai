import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from services.common import private_endpoints as pe
from tests._temp_support import sovereign_temporary_directory


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = PROJECT_ROOT / "configs" / "runtime" / "private-endpoints.example.json"
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "private-endpoints.schema.json"
MODULE_PATH = PROJECT_ROOT / "services" / "common" / "private_endpoints.py"


def synthetic_address(*octets: int) -> str:
    # Built at runtime: the public repository must not carry a private literal
    # (see test_no_private_infrastructure_identifiers).
    return ".".join(str(octet) for octet in octets)


PRIVATE_HOST = synthetic_address(10, 20, 30, 43)
OTHER_PRIVATE_HOST = synthetic_address(172, 16, 5, 44)


def document(**endpoints: dict) -> dict:
    return {"schema_version": pe.SCHEMA_VERSION, "endpoints": endpoints}


def valid_document() -> dict:
    return document(
        core_inference={"host": PRIVATE_HOST, "port": 9000},
        qwen_coder={"host": OTHER_PRIVATE_HOST, "port": 8790},
    )


class PrivateEndpointsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = sovereign_temporary_directory()
        self.root = Path(self._directory.__enter__())
        self.addCleanup(self._directory.__exit__, None, None, None)
        self.path = self.root / "private-endpoints.json"

    def write(self, value: object, *, raw: bytes | None = None, mode: int = 0o600) -> Path:
        payload = raw if raw is not None else json.dumps(value).encode("utf-8")
        self.path.write_bytes(payload)
        os.chmod(self.path, mode)
        return self.path

    def environ(self, path: Path | None = None) -> dict[str, str]:
        return {pe.PRIVATE_ENDPOINTS_ENV: str(path or self.path)}

    def assert_refused(self, *, content_markers: tuple[str, ...] = ()) -> str:
        with self.assertRaises(pe.PrivateEndpointsError) as caught:
            pe.load_private_endpoints(self.environ())
        message = str(caught.exception)
        self.assertNotIn(str(self.root), message)
        self.assertNotIn(self.path.name, message)
        for marker in content_markers:
            self.assertNotIn(marker, message)
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__ or caught.exception.__context__ is None)
        return message


class LoadTests(PrivateEndpointsTestCase):
    def test_loads_a_valid_configuration(self) -> None:
        self.write(valid_document())
        endpoints = pe.load_private_endpoints(self.environ())
        self.assertEqual(set(endpoints), {"core_inference", "qwen_coder"})
        self.assertEqual(endpoints["core_inference"].url, f"http://{PRIVATE_HOST}:9000")
        self.assertEqual(endpoints["qwen_coder"].host, OTHER_PRIVATE_HOST)
        self.assertEqual(endpoints["qwen_coder"].port, 8790)

    def test_accepts_loopback_and_a_single_endpoint(self) -> None:
        self.write(document(core_inference={"host": "127.0.0.2", "port": 9000}))
        self.assertEqual(pe.require_endpoint("core_inference", self.environ()).url, "http://127.0.0.2:9000")

    def test_requires_the_environment_variable_and_an_absolute_path(self) -> None:
        for environ in ({}, {pe.PRIVATE_ENDPOINTS_ENV: ""}, {pe.PRIVATE_ENDPOINTS_ENV: "relative/endpoints.json"}):
            with self.subTest(environ=environ), self.assertRaises(pe.PrivateEndpointsError) as caught:
                pe.load_private_endpoints(environ)
            self.assertNotIn("relative", str(caught.exception))

    def test_missing_file_is_refused_without_its_path(self) -> None:
        message = self.assert_refused()
        self.assertIn("unavailable", message)

    def test_directory_is_refused(self) -> None:
        self.path.mkdir()
        self.assert_refused()

    def test_malformed_json_is_refused_without_its_content(self) -> None:
        for raw in (b"{", b"not json " + PRIVATE_HOST.encode(), b"\xff\xfe", b'{"a": NaN}', b"[]", b"null"):
            with self.subTest(raw=raw):
                self.write(None, raw=raw)
                self.assert_refused(content_markers=(PRIVATE_HOST, "not json"))

    def test_duplicate_keys_are_refused(self) -> None:
        raw = ('{"schema_version": "%s", "schema_version": "%s", "endpoints": {}}' % (pe.SCHEMA_VERSION, pe.SCHEMA_VERSION)).encode()
        self.write(None, raw=raw)
        self.assert_refused()

    def test_empty_and_oversized_files_are_refused(self) -> None:
        self.write(None, raw=b"")
        self.assert_refused()
        padded = json.dumps(valid_document()).encode() + b" " * pe.MAXIMUM_FILE_BYTES
        self.write(None, raw=padded)
        self.assertIn("size", self.assert_refused())

    def test_public_and_reserved_addresses_are_refused(self) -> None:
        refused = (
            "192.0.2.10",  # RFC 5737 documentation
            "198.51.100.7",  # RFC 5737 documentation
            "8.8.8.8",
            "0.0.0.0",
            "255.255.255.255",
            "169.254.1.1",
            synthetic_address(100, 64, 0, 5),  # RFC 6598 shared space
            synthetic_address(10, 0, 0, 0),  # network address
            synthetic_address(192, 168, 255, 255),  # broadcast address
        )
        for host in refused:
            with self.subTest(host=host):
                self.write(document(core_inference={"host": host, "port": 9000}))
                self.assert_refused(content_markers=(host,))

    def test_hostnames_and_non_canonical_hosts_are_refused(self) -> None:
        refused = (
            "localhost",
            "core.invalid",
            "::1",
            "0" + synthetic_address(10, 1, 2, 3),
            synthetic_address(10, 1, 2, 3) + " ",
            f"http://{PRIVATE_HOST}",
            f"{PRIVATE_HOST}:9000",
            "",
            42,
            None,
        )
        for host in refused:
            with self.subTest(host=host):
                self.write(document(core_inference={"host": host, "port": 9000}))
                self.assert_refused(content_markers=tuple(item for item in (host,) if isinstance(item, str) and item))

    def test_invalid_ports_are_refused(self) -> None:
        for port in (0, 65536, -1, "9000", True, 9000.0, None):
            with self.subTest(port=port):
                self.write(document(core_inference={"host": PRIVATE_HOST, "port": port}))
                self.assert_refused()

    def test_extra_or_missing_keys_are_refused(self) -> None:
        candidates = (
            {**valid_document(), "comment": "x"},
            {"endpoints": valid_document()["endpoints"]},
            {"schema_version": "private-endpoints.v2", "endpoints": valid_document()["endpoints"]},
            document(),
            {"schema_version": pe.SCHEMA_VERSION, "endpoints": []},
            document(core_inference={"host": PRIVATE_HOST, "port": 9000, "scheme": "http"}),
            document(core_inference={"host": PRIVATE_HOST}),
            document(core_inference=[PRIVATE_HOST, 9000]),
            document(embedding={"host": PRIVATE_HOST, "port": 8082}),
        )
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                self.write(candidate)
                self.assert_refused(content_markers=(PRIVATE_HOST,))

    def test_two_names_on_the_same_address_are_refused(self) -> None:
        self.write(document(
            core_inference={"host": PRIVATE_HOST, "port": 9000},
            qwen_coder={"host": PRIVATE_HOST, "port": 9000},
        ))
        self.assert_refused()

    @unittest.skipUnless(os.name == "posix", "POSIX permission bits")
    def test_group_or_world_writable_files_are_refused(self) -> None:
        for mode in (0o620, 0o602, 0o666):
            with self.subTest(mode=oct(mode)):
                self.write(valid_document(), mode=mode)
                self.assertIn("writable", self.assert_refused())
        self.write(valid_document(), mode=0o640)
        self.assertIn("core_inference", pe.load_private_endpoints(self.environ()))

    @unittest.skipUnless(os.name == "posix", "POSIX symbolic links")
    def test_symbolic_link_is_refused(self) -> None:
        target = self.root / "target.json"
        target.write_text(json.dumps(valid_document()), encoding="utf-8")
        os.chmod(target, 0o600)
        self.path.symlink_to(target)
        self.assert_refused()


class RequireTests(PrivateEndpointsTestCase):
    def test_require_refuses_unknown_and_absent_names(self) -> None:
        self.write(document(core_inference={"host": PRIVATE_HOST, "port": 9000}))
        with self.assertRaises(pe.PrivateEndpointsError):
            pe.require_endpoint("embedding", self.environ())
        with self.assertRaises(pe.PrivateEndpointsError) as caught:
            pe.require_endpoint("qwen_coder", self.environ())
        self.assertNotIn(PRIVATE_HOST, str(caught.exception))

    def test_endpoint_or_exit_refuses_to_start_without_content(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            pe.endpoint_or_exit("core_inference", self.environ())
        self.assertIn("refusing to start", str(caught.exception.code))
        self.assertNotIn(str(self.root), str(caught.exception.code))

    def test_direct_construction_is_validated(self) -> None:
        self.assertEqual(pe.PrivateEndpoint("qwen_coder", "127.0.0.3", 8790).url, "http://127.0.0.3:8790")
        for arguments in (("qwen_coder", "0.0.0.0", 8790), ("qwen_coder", "127.0.0.3", 0), ("other", "127.0.0.3", 8790)):
            with self.subTest(arguments=arguments), self.assertRaises(pe.PrivateEndpointsError):
                pe.PrivateEndpoint(*arguments)


class PublishedContractTests(unittest.TestCase):
    def test_example_is_well_formed_but_cannot_be_installed_as_is(self) -> None:
        payload = EXAMPLE_PATH.read_bytes()
        with self.assertRaises(pe.PrivateEndpointsError) as caught:
            pe.parse_private_endpoints(payload)
        self.assertIn("private or loopback", str(caught.exception))
        example = json.loads(payload)
        for index, entry in enumerate(example["endpoints"].values(), start=2):
            self.assertTrue(entry["host"].startswith("192.0.2."))
            entry["host"] = f"127.0.0.{index}"
        self.assertEqual(set(pe.parse_private_endpoints(json.dumps(example).encode())), pe.ENDPOINT_NAMES)

    def test_schema_matches_the_loader(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema_version"]["const"], pe.SCHEMA_VERSION)
        self.assertEqual(set(schema["properties"]["endpoints"]["properties"]), pe.ENDPOINT_NAMES)
        self.assertFalse(schema["additionalProperties"])
        self.assertFalse(schema["properties"]["endpoints"]["additionalProperties"])
        self.assertEqual(set(schema["$defs"]["endpoint"]["required"]), {"host", "port"})
        self.assertFalse(schema["$defs"]["endpoint"]["additionalProperties"])


class CheckCommandTests(PrivateEndpointsTestCase):
    def run_check(self, *arguments: str, environ: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        # Run the module as a standalone file: operators validate the private
        # file with the new revision before it is deployed.
        env = {key: value for key, value in os.environ.items() if key != pe.PRIVATE_ENDPOINTS_ENV}
        env.update(environ if environ is not None else self.environ())
        return subprocess.run(
            [sys.executable, "-B", str(MODULE_PATH), *arguments],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=30, check=False,
        )

    def test_check_accepts_a_valid_file_and_prints_names_only(self) -> None:
        self.write(valid_document())
        completed = self.run_check("--check", "--require", "core_inference", "--require", "qwen_coder")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "valid: core_inference, qwen_coder")
        self.assertNotIn(PRIVATE_HOST, completed.stdout + completed.stderr)

    def test_check_refuses_missing_required_endpoint_and_invalid_files(self) -> None:
        self.write(document(core_inference={"host": PRIVATE_HOST, "port": 9000}))
        completed = self.run_check("--check", "--require", "qwen_coder")
        self.assertEqual(completed.returncode, 2)
        self.assertIn("qwen_coder", completed.stderr)
        self.assertNotIn(PRIVATE_HOST, completed.stdout + completed.stderr)
        self.write(None, raw=b"{" + PRIVATE_HOST.encode())
        completed = self.run_check("--check")
        self.assertEqual(completed.returncode, 2)
        for marker in (PRIVATE_HOST, str(self.root)):
            self.assertNotIn(marker, completed.stdout + completed.stderr)
        completed = self.run_check("--check", environ={})
        self.assertEqual(completed.returncode, 2)
        self.assertIn(pe.PRIVATE_ENDPOINTS_ENV, completed.stderr)

    def test_check_offers_help(self) -> None:
        completed = self.run_check("--help", environ={})
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("usage:", completed.stdout.lower())


if __name__ == "__main__":
    unittest.main()
