import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from services.common import private_endpoints as pe
from tests._private_endpoint_support import trust_test_account
from tests._temp_support import sovereign_temporary_directory


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = PROJECT_ROOT / "configs" / "runtime" / "private-endpoints.example.json"
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "private-endpoints.schema.json"
MODULE_PATH = PROJECT_ROOT / "services" / "common" / "private_endpoints.py"
# Loads the module from its file alone, as an operator runs it, and trusts the
# unprivileged test account instead of root on POSIX (test runs only).
STANDALONE_BOOTSTRAP = (
    "import importlib.util, os, sys\n"
    "spec = importlib.util.spec_from_file_location('private_endpoints_standalone', sys.argv.pop(1))\n"
    "module = importlib.util.module_from_spec(spec)\n"
    "sys.modules[spec.name] = module\n"
    "spec.loader.exec_module(module)\n"
    "if os.name == 'posix':\n"
    "    module.TRUSTED_OWNER_UID = os.geteuid()\n"
    "raise SystemExit(module.main())\n"
)


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
        trust_test_account(self)

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

    @unittest.skipUnless(os.name == "posix", "POSIX ownership")
    def test_file_or_directory_not_owned_by_root_is_refused(self) -> None:
        # The service account must not own its pin: it could rewrite it.
        self.write(valid_document())
        with patch.object(pe, "TRUSTED_OWNER_UID", os.geteuid() + 1):
            self.assertIn("owned by root", self.assert_refused())

    @unittest.skipUnless(os.name == "posix", "POSIX permission bits")
    def test_group_or_world_writable_directory_is_refused(self) -> None:
        self.write(valid_document())
        self.addCleanup(os.chmod, self.root, 0o700)
        for mode in (0o770, 0o707, 0o1777):
            with self.subTest(mode=oct(mode)):
                os.chmod(self.root, mode)
                message = self.assert_refused()
                self.assertIn("directory", message)
                self.assertIn("writable", message)

    def test_file_changed_while_read_is_refused(self) -> None:
        self.write(valid_document())
        real_fstat = os.fstat
        seen: list[int] = []

        def shifting_fstat(descriptor: int):
            status = real_fstat(descriptor)
            seen.append(descriptor)
            if seen.count(descriptor) < 2:
                return status
            # Second look at the same descriptor: the file was rewritten.
            return SimpleNamespace(st_mode=status.st_mode, st_uid=status.st_uid,
                                   st_size=status.st_size, st_mtime_ns=status.st_mtime_ns + 1)

        with patch.object(pe.os, "fstat", side_effect=shifting_fstat):
            self.assertIn("changed while it was read", self.assert_refused())

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
        stderr = io.StringIO()
        with self.assertRaises(SystemExit) as caught, contextlib.redirect_stderr(stderr):
            pe.endpoint_or_exit("core_inference", self.environ())
        # EX_CONFIG: the units list it in RestartPreventExitStatus (no restart loop).
        self.assertEqual(caught.exception.code, pe.EXIT_CONFIGURATION_REFUSED)
        self.assertEqual(pe.EXIT_CONFIGURATION_REFUSED, 78)
        self.assertIn("refusing to start", stderr.getvalue())
        self.assertNotIn(str(self.root), stderr.getvalue())

    def test_direct_construction_is_validated(self) -> None:
        self.assertEqual(pe.PrivateEndpoint("qwen_coder", "127.0.0.3", 8790).url, "http://127.0.0.3:8790")
        for arguments in (("qwen_coder", "0.0.0.0", 8790), ("qwen_coder", "127.0.0.3", 0), ("other", "127.0.0.3", 8790)):
            with self.subTest(arguments=arguments), self.assertRaises(pe.PrivateEndpointsError):
                pe.PrivateEndpoint(*arguments)


class LegacyOverrideTests(unittest.TestCase):
    ENDPOINTS = {
        "core_inference": pe.PrivateEndpoint("core_inference", PRIVATE_HOST, 9000),
        "qwen_coder": pe.PrivateEndpoint("qwen_coder", OTHER_PRIVATE_HOST, 8790),
    }

    def test_matching_or_absent_legacy_variables_are_accepted(self) -> None:
        self.assertEqual(pe.check_legacy_overrides(self.ENDPOINTS, {}), [])
        environ = {
            "SOVEREIGN_CORE_ENDPOINT": f"http://{PRIVATE_HOST}:9000",
            "SOVEREIGN_QWEN_ENDPOINT": f"http://{OTHER_PRIVATE_HOST}:8790",
            "SOVEREIGN_CORE_PORT": "9000",
            "SOVEREIGN_BOOTSTRAP_ENDPOINT": "http://127.0.0.1:8080",
        }
        self.assertEqual(pe.check_legacy_overrides(self.ENDPOINTS, environ),
                         ["SOVEREIGN_CORE_ENDPOINT", "SOVEREIGN_QWEN_ENDPOINT", "SOVEREIGN_CORE_PORT"])

    def test_inexact_legacy_variables_are_refused_without_their_value(self) -> None:
        qwen = f"http://{OTHER_PRIVATE_HOST}:8790"
        refused = (
            ("SOVEREIGN_QWEN_ENDPOINT", qwen + "/"),
            ("SOVEREIGN_QWEN_ENDPOINT", qwen + "/v1"),
            ("SOVEREIGN_QWEN_ENDPOINT", f"http://{OTHER_PRIVATE_HOST}:8791"),
            ("SOVEREIGN_QWEN_ENDPOINT", "https://" + qwen[len("http://"):]),
            ("SOVEREIGN_QWEN_ENDPOINT", ""),
            ("SOVEREIGN_CORE_ENDPOINT", qwen),
            ("SOVEREIGN_CORE_PORT", "09000"),
            ("SOVEREIGN_CORE_PORT", "9000 "),
            ("SOVEREIGN_CORE_PORT", ""),
        )
        for variable, value in refused:
            with self.subTest(variable=variable, value=value), self.assertRaises(pe.PrivateEndpointsError) as caught:
                pe.check_legacy_overrides(self.ENDPOINTS, {variable: value})
            message = str(caught.exception)
            self.assertIn(variable, message)
            self.assertIn("does not match", message)
            for marker in (PRIVATE_HOST, OTHER_PRIVATE_HOST):
                self.assertNotIn(marker, message)

    def test_legacy_variable_without_its_endpoint_is_refused(self) -> None:
        only_core = {"core_inference": self.ENDPOINTS["core_inference"]}
        with self.assertRaises(pe.PrivateEndpointsError) as caught:
            pe.check_legacy_overrides(only_core, {"SOVEREIGN_QWEN_ENDPOINT": f"http://{OTHER_PRIVATE_HOST}:8790"})
        self.assertIn("qwen_coder is not configured", str(caught.exception))
        self.assertNotIn(OTHER_PRIVATE_HOST, str(caught.exception))


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

    def test_unit_templates_stop_restarting_on_a_configuration_refusal(self) -> None:
        for unit in ("infra/gateway/sovereign-gateway-web.service", "infra/arena/sovereign-arena.service"):
            with self.subTest(unit=unit):
                lines = (PROJECT_ROOT / unit).read_text(encoding="utf-8").splitlines()
                self.assertIn(f"RestartPreventExitStatus={pe.EXIT_CONFIGURATION_REFUSED}", lines)
                self.assertTrue(any(line.startswith(f"Environment={pe.PRIVATE_ENDPOINTS_ENV}=/") for line in lines))

    def test_schema_matches_the_loader(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema_version"]["const"], pe.SCHEMA_VERSION)
        self.assertEqual(set(schema["properties"]["endpoints"]["properties"]), pe.ENDPOINT_NAMES)
        self.assertFalse(schema["additionalProperties"])
        self.assertFalse(schema["properties"]["endpoints"]["additionalProperties"])
        self.assertEqual(set(schema["$defs"]["endpoint"]["required"]), {"host", "port"})
        self.assertFalse(schema["$defs"]["endpoint"]["additionalProperties"])


class CheckCommandTests(PrivateEndpointsTestCase):
    LEGACY = frozenset({**pe.LEGACY_URL_VARIABLES, **pe.LEGACY_PORT_VARIABLES})

    def run_check(self, *arguments: str, environ: dict[str, str] | None = None,
                  direct: bool = False) -> subprocess.CompletedProcess:
        # Run the module from its file alone, in isolated mode (-I), as the
        # migration guide does from the staged release before it is switched.
        env = {key: value for key, value in os.environ.items()
               if key != pe.PRIVATE_ENDPOINTS_ENV and key not in self.LEGACY}
        env.update(environ if environ is not None else self.environ())
        entry = [str(MODULE_PATH)] if direct else ["-c", STANDALONE_BOOTSTRAP, str(MODULE_PATH)]
        return subprocess.run(
            [sys.executable, "-I", "-B", *entry, *arguments],
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
        completed = self.run_check("--check", environ={}, direct=True)
        self.assertEqual(completed.returncode, 2)
        self.assertIn(pe.PRIVATE_ENDPOINTS_ENV, completed.stderr)

    def test_legacy_env_accepts_exact_overrides_and_names_them_only(self) -> None:
        self.write(valid_document())
        completed = self.run_check("--check", "--legacy-env", environ={
            **self.environ(),
            "SOVEREIGN_QWEN_ENDPOINT": f"http://{OTHER_PRIVATE_HOST}:8790",
            "SOVEREIGN_CORE_PORT": "9000",
        })
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.splitlines(), [
            "valid: core_inference, qwen_coder",
            "legacy variables matching: SOVEREIGN_QWEN_ENDPOINT, SOVEREIGN_CORE_PORT",
        ])
        self.assertNotIn(OTHER_PRIVATE_HOST, completed.stdout + completed.stderr)
        completed = self.run_check("--check", "--legacy-env")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("legacy variables matching: none", completed.stdout)

    def test_legacy_env_refuses_an_inexact_override_without_echoing_it(self) -> None:
        # The former arena accepted any private-LAN prefix: a trailing slash
        # passed there but now stops the service at start-up.
        self.write(valid_document())
        for variable, value in (("SOVEREIGN_QWEN_ENDPOINT", f"http://{OTHER_PRIVATE_HOST}:8790/"),
                                ("SOVEREIGN_CORE_ENDPOINT", f"http://{PRIVATE_HOST}:9001"),
                                ("SOVEREIGN_CORE_PORT", "9001")):
            with self.subTest(variable=variable):
                completed = self.run_check("--check", "--legacy-env", environ={**self.environ(), variable: value})
                self.assertEqual(completed.returncode, 2)
                self.assertIn(f"refused: {variable} does not match the pinned endpoint", completed.stderr)
                for marker in (PRIVATE_HOST, OTHER_PRIVATE_HOST, value):
                    self.assertNotIn(marker, completed.stdout + completed.stderr)
                # Without --legacy-env the same environment is not examined.
                completed = self.run_check("--check", environ={**self.environ(), variable: value})
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_check_offers_help(self) -> None:
        completed = self.run_check("--help", environ={}, direct=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("usage:", completed.stdout.lower())
        self.assertIn("--legacy-env", completed.stdout)


if __name__ == "__main__":
    unittest.main()
