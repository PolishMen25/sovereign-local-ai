"""RFC 8785 canonicalization, strict parsing and the three hash scopes.

Every document here is synthetic.  Number vectors are the IEEE 754 examples
published in RFC 8785 appendix B.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import unittest

from tests._temp_support import sovereign_temporary_directory


PROJECT_ROOT = Path(__file__).parents[1]
MODULE_PATH = PROJECT_ROOT / "services" / "quarantine" / "canonical_json.py"
SPEC = importlib.util.spec_from_file_location("canonical_json", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

CanonicalJSONError = MODULE.CanonicalJSONError


# RFC 8785 appendix B: IEEE 754 binary64 (hex) -> ECMAScript serialization.
NUMBER_VECTORS = {
    "0000000000000000": "0",
    "8000000000000000": "0",
    "0000000000000001": "5e-324",
    "8000000000000001": "-5e-324",
    "7fefffffffffffff": "1.7976931348623157e+308",
    "ffefffffffffffff": "-1.7976931348623157e+308",
    "4340000000000000": "9007199254740992",
    "c340000000000000": "-9007199254740992",
    "4430000000000000": "295147905179352830000",
    "44b52d02c7e14af5": "9.999999999999997e+22",
    "44b52d02c7e14af6": "1e+23",
    "44b52d02c7e14af7": "1.0000000000000001e+23",
    "444b1ae4d6e2ef4e": "999999999999999700000",
    "444b1ae4d6e2ef4f": "999999999999999900000",
    "444b1ae4d6e2ef50": "1e+21",
    "3eb0c6f7a0b5ed8c": "9.999999999999997e-7",
    "3eb0c6f7a0b5ed8d": "0.000001",
    "41b3de4355555553": "333333333.3333332",
    "41b3de4355555554": "333333333.33333325",
    "41b3de4355555555": "333333333.3333333",
    "41b3de4355555556": "333333333.3333334",
    "41b3de4355555557": "333333333.33333343",
    "becbf647612f3696": "-0.0000033333333333333333",
    "43143ff3c1cb0959": "1424953923781206.2",
}


def double(hex_bits: str) -> float:
    return struct.unpack(">d", bytes.fromhex(hex_bits))[0]


def synthetic_package() -> dict:
    return {
        "schema_version": "0.1.0",
        "package_id": "00000000-0000-4000-8000-000000000001",
        "lifecycle_state": "RAW",
        "response": {"text": "Réponse synthétique 😀", "integrity": "nested member is kept"},
        "usage": {"input_tokens": 12, "output_tokens": 34},
        "cost": {"amount": 0.1, "currency": "EUR"},
        "integrity": {
            "algorithm": "SHA-256",
            "canonicalization": "RFC8785",
            "hash_scope": "canonical-package-excluding-integrity",
            "package_sha256": "0" * 64,
        },
    }


class NumberSerializationTests(unittest.TestCase):
    def test_rfc8785_appendix_b_vectors(self) -> None:
        for hex_bits, expected in NUMBER_VECTORS.items():
            with self.subTest(hex_bits=hex_bits):
                self.assertEqual(expected, MODULE.serialize_number(double(hex_bits)))

    def test_nan_and_infinity_vectors_are_refused(self) -> None:
        for hex_bits in ("7fffffffffffffff", "7ff0000000000000", "fff0000000000000"):
            with self.subTest(hex_bits=hex_bits), self.assertRaises(CanonicalJSONError) as caught:
                MODULE.canonicalize([double(hex_bits)])
            self.assertEqual("NON_FINITE_NUMBER", caught.exception.code)

    def test_required_number_examples(self) -> None:
        cases = [
            (1e21, b"1e+21"),
            (1e20, b"100000000000000000000"),
            (0.1, b"0.1"),
            (-0.0, b"0"),
            (1.0, b"1"),
            (1e-7, b"1e-7"),
            (-1.5, b"-1.5"),
            (0, b"0"),
            (-42, b"-42"),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(expected, MODULE.canonicalize(value))

    def test_parsed_numbers_serialize_per_rfc8785(self) -> None:
        self.assertEqual(b"[1e+21,0.1,0,0,1,4.5,0.002]", MODULE.canonicalize(MODULE.loads_strict("[1e21, 0.1, -0, -0.0, 1.0, 4.50, 2e-3]")))

    def test_integers_are_limited_to_the_i_json_safe_range(self) -> None:
        limit = MODULE.MAX_SAFE_INTEGER
        self.assertEqual(str(limit).encode(), MODULE.canonicalize(MODULE.loads_strict(str(limit))))
        self.assertEqual(str(-limit).encode(), MODULE.canonicalize(-limit))
        for text in (str(limit + 1), str(-limit - 1), "1" * 5000):
            with self.subTest(length=len(text)), self.assertRaises(CanonicalJSONError) as caught:
                MODULE.loads_strict(text)
            self.assertEqual("INTEGER_OUT_OF_RANGE", caught.exception.code)
        with self.assertRaises(CanonicalJSONError) as caught:
            MODULE.canonicalize({"n": limit + 1})
        self.assertEqual("INTEGER_OUT_OF_RANGE", caught.exception.code)


class CanonicalFormTests(unittest.TestCase):
    def test_rfc8785_example_document(self) -> None:
        source = (
            '{"numbers": [333333333.33333329, 1E30, 4.50, 2e-3, 0.000000000000000000000000001],'
            ' "string": "\\u20ac$\\u000F\\u000aA\'\\u0042\\u0022\\u005c\\\\\\"\\/",'
            ' "literals": [null, true, false]}'
        )
        expected = (
            '{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],'
            '"string":"€$\\u000f\\nA\'B\\"\\\\\\\\\\"/"}'
        ).encode("utf-8")
        self.assertEqual(expected, MODULE.canonicalize(MODULE.loads_strict(source)))

    def test_keys_are_sorted_by_utf16_code_units_including_non_bmp(self) -> None:
        document = MODULE.loads_strict(
            '{"\\u20ac": "Euro Sign", "\\r": "Carriage Return", "\\ufb33": "Hebrew Letter Dalet With Dagesh",'
            ' "1": "One", "\\ud83d\\ude00": "Emoji: Grinning Face", "\\u0080": "Control",'
            ' "\\u00f6": "Latin Small Letter O With Diaeresis"}'
        )
        values = [value for _, value in json.loads(MODULE.canonicalize(document)).items()]
        self.assertEqual(
            [
                "Carriage Return",
                "One",
                "Control",
                "Latin Small Letter O With Diaeresis",
                "Euro Sign",
                "Emoji: Grinning Face",
                "Hebrew Letter Dalet With Dagesh",
            ],
            values,
        )

    def test_nested_objects_are_sorted_and_arrays_keep_their_order(self) -> None:
        document = {"b": [{"z": 1, "a": {"y": None, "x": True}}, 3, "s"], "a": {}}
        self.assertEqual(b'{"a":{},"b":[{"a":{"x":true,"y":null},"z":1},3,"s"]}', MODULE.canonicalize(document))

    def test_string_escaping_matches_rfc8785(self) -> None:
        text = "".join(chr(code) for code in range(0x20)) + '"\\/\u007f é😀'
        expected = (
            '"\\u0000\\u0001\\u0002\\u0003\\u0004\\u0005\\u0006\\u0007\\b\\t\\n\\u000b\\f\\r'
            "\\u000e\\u000f\\u0010\\u0011\\u0012\\u0013\\u0014\\u0015\\u0016\\u0017\\u0018\\u0019"
            '\\u001a\\u001b\\u001c\\u001d\\u001e\\u001f\\"\\\\/\u007f é😀"'
        ).encode("utf-8")
        self.assertEqual(expected, MODULE.canonicalize(text))

    def test_json_dumps_sort_keys_is_not_rfc8785(self) -> None:
        document = {"דּ": 1.0, "\U0001f600": 1e-7}
        naive = json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.assertEqual('{"\U0001f600":1e-7,"דּ":1}'.encode("utf-8"), MODULE.canonicalize(document))
        self.assertNotEqual(naive, MODULE.canonicalize(document))

    def test_whitespace_and_member_order_do_not_change_the_canonical_hash(self) -> None:
        first = MODULE.loads_strict(b'{"a": 1, "b": [true, null]}')
        second = MODULE.loads_strict(b'{\n  "b" : [ true , null ],\n  "a" : 1.0\n}')
        self.assertEqual(MODULE.canonical_sha256(first), MODULE.canonical_sha256(second))


class StrictParsingRefusalTests(unittest.TestCase):
    def assert_refused(self, data, code: str) -> CanonicalJSONError:
        with self.assertRaises(CanonicalJSONError) as caught:
            MODULE.loads_strict(data)
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def test_duplicate_keys_are_refused_at_any_depth(self) -> None:
        self.assert_refused('{"a": 1, "a": 1}', "DUPLICATE_KEY")
        self.assert_refused('{"outer": [{"k": 1, "k": 2}]}', "DUPLICATE_KEY")
        self.assert_refused('{"\\u0061": 1, "a": 2}', "DUPLICATE_KEY")

    def test_nan_infinity_and_overflow_are_refused(self) -> None:
        for text in ("NaN", "[Infinity]", '{"x": -Infinity}', "1e400", "-1E400"):
            with self.subTest(text=text):
                self.assert_refused(text, "NON_FINITE_NUMBER")

    def test_lone_surrogates_are_refused(self) -> None:
        for text in ('"\\ud800"', '["\\udfff"]', '{"\\udc00": 1}', '"\\ude00\\ud83d"'):
            with self.subTest(text=text):
                self.assert_refused(text, "LONE_SURROGATE")
        self.assert_refused("\ud800", "LONE_SURROGATE")
        for value in ("\ud800", {"\udfff": 1}, ["ok", "\udc80"]):
            with self.subTest(value=repr(value)), self.assertRaises(CanonicalJSONError) as caught:
                MODULE.canonicalize(value)
            self.assertEqual("LONE_SURROGATE", caught.exception.code)

    def test_a_valid_surrogate_pair_is_accepted(self) -> None:
        self.assertEqual('"😀"'.encode("utf-8"), MODULE.canonicalize(MODULE.loads_strict('"\\ud83d\\ude00"')))

    def test_encoding_and_syntax_errors_are_refused(self) -> None:
        self.assert_refused(b"\xef\xbb\xbf{}", "BOM_REFUSED")
        self.assert_refused(b'{"a": "\xff"}', "INVALID_UTF8")
        self.assert_refused(b'"\xed\xa0\x80"', "INVALID_UTF8")
        for text in ("", "{", "{'a': 1}", '{"a": 1,}', "[1 2]", '"raw\ncontrol"', "01", "{} {}"):
            with self.subTest(text=text):
                self.assert_refused(text, "MALFORMED_JSON")
        self.assert_refused(12, "NOT_BYTES")

    def test_depth_and_size_limits(self) -> None:
        limit = MODULE.MAX_DEPTH
        self.assertEqual(b"[" * (limit + 1) + b"]" * (limit + 1), MODULE.canonicalize(MODULE.loads_strict("[" * (limit + 1) + "]" * (limit + 1))))
        self.assert_refused("[" * (limit + 2) + "]" * (limit + 2), "DEPTH_EXCEEDED")
        self.assert_refused("[" * 200_000 + "]" * 200_000, "DEPTH_EXCEEDED")
        with self.assertRaises(CanonicalJSONError) as caught:
            MODULE.loads_strict(b"[1, 2, 3]", max_bytes=8)
        self.assertEqual("SIZE_EXCEEDED", caught.exception.code)
        nested: list = []
        for _ in range(limit + 1):
            nested = [nested]
        with self.assertRaises(CanonicalJSONError) as caught:
            MODULE.canonicalize(nested)
        self.assertEqual("DEPTH_EXCEEDED", caught.exception.code)

    def test_values_json_cannot_represent_are_refused(self) -> None:
        class Number(int):
            pass

        for value, code in (
            ((1, 2), "UNSUPPORTED_TYPE"),
            ({1, 2}, "UNSUPPORTED_TYPE"),
            (b"bytes", "UNSUPPORTED_TYPE"),
            (Number(3), "UNSUPPORTED_TYPE"),
            ({1: "x"}, "NON_STRING_KEY"),
        ):
            with self.subTest(value=repr(value)), self.assertRaises(CanonicalJSONError) as caught:
                MODULE.canonicalize(value)
            self.assertEqual(code, caught.exception.code)

    def test_refusals_never_echo_the_document(self) -> None:
        marker = "synthetic-marker-7f3a"
        for text in (
            f'{{"{marker}": 1, "{marker}": 2}}',
            f'{{"{marker}": NaN}}',
            f'{{"{marker}": "\\ud800"}}',
            f'{{"{marker}": oops}}',
        ):
            with self.subTest(text=text):
                with self.assertRaises(CanonicalJSONError) as caught:
                    MODULE.loads_strict(text)
                error = caught.exception
                self.assertNotIn(marker, str(error))
                self.assertNotIn(marker, repr(error.args))
                self.assertIsNone(error.__cause__)
                self.assertIsNone(error.__context__)


class HashScopeTests(unittest.TestCase):
    def test_package_hash_excludes_only_the_top_level_integrity_member(self) -> None:
        package = synthetic_package()
        original = json.loads(json.dumps(package))
        digest = MODULE.package_sha256(package)
        self.assertEqual(original, package, "hashing must not modify the package")
        self.assertRegex(digest, r"^[a-f0-9]{64}$")

        without = {key: value for key, value in package.items() if key != "integrity"}
        self.assertEqual(hashlib.sha256(MODULE.canonicalize(without)).hexdigest(), digest)

        rewritten = synthetic_package()
        rewritten["integrity"]["package_sha256"] = digest
        rewritten["integrity"]["provider_raw_response_sha256"] = "f" * 64
        self.assertEqual(digest, MODULE.package_sha256(rewritten))
        self.assertEqual(digest, MODULE.package_sha256(without))

        nested_changed = synthetic_package()
        nested_changed["response"]["integrity"] = "a nested member is part of the hash"
        self.assertNotEqual(digest, MODULE.package_sha256(nested_changed))

        content_changed = synthetic_package()
        content_changed["usage"]["output_tokens"] = 35
        self.assertNotEqual(digest, MODULE.package_sha256(content_changed))

    def test_package_hash_requires_an_object(self) -> None:
        for value in ([], "text", None):
            with self.subTest(value=value), self.assertRaises(CanonicalJSONError) as caught:
                MODULE.package_sha256(value)
            self.assertEqual("NOT_AN_OBJECT", caught.exception.code)

    def test_ingress_hash_covers_the_exact_bytes_received(self) -> None:
        compact = b'{"a":1}'
        spaced = b'{ "a" : 1 }\n'
        self.assertEqual(hashlib.sha256(spaced).hexdigest(), MODULE.ingress_sha256(spaced))
        self.assertNotEqual(MODULE.ingress_sha256(compact), MODULE.ingress_sha256(spaced))
        self.assertEqual(MODULE.canonical_sha256(MODULE.loads_strict(compact)), MODULE.canonical_sha256(MODULE.loads_strict(spaced)))
        self.assertEqual(hashlib.sha256(b"\x00raw").hexdigest(), MODULE.provider_response_sha256(b"\x00raw"))
        for function in (MODULE.ingress_sha256, MODULE.provider_response_sha256):
            with self.subTest(function=function.__name__), self.assertRaises(CanonicalJSONError) as caught:
                function('{"a":1}')
            self.assertEqual("NOT_BYTES", caught.exception.code)


class SchemaContractTests(unittest.TestCase):
    def load_schema(self, name: str) -> dict:
        return MODULE.loads_strict((PROJECT_ROOT / "schemas" / name).read_bytes())

    def test_module_constants_match_the_research_package_integrity_contract(self) -> None:
        integrity = self.load_schema("research-package.schema.json")["$defs"]["integrity"]["properties"]
        self.assertEqual(MODULE.HASH_ALGORITHM, integrity["algorithm"]["const"])
        self.assertEqual(MODULE.CANONICALIZATION, integrity["canonicalization"]["const"])
        self.assertEqual(MODULE.SCOPE_PACKAGE, integrity["hash_scope"]["const"])

    def test_collector_receipt_schema_is_closed_and_minimal(self) -> None:
        schema = self.load_schema("collector-receipt.schema.json")
        expected = {"submission_id", "received_at", "ingress_payload_sha256", "status"}
        self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
        self.assertEqual("object", schema["type"])
        self.assertIs(False, schema["additionalProperties"])
        self.assertEqual(expected, set(schema["required"]))
        self.assertEqual(len(expected), len(schema["required"]))
        self.assertEqual(expected, set(schema["properties"]))
        properties = schema["properties"]
        self.assertEqual("uuid", properties["submission_id"]["format"])
        self.assertEqual("date-time", properties["received_at"]["format"])
        self.assertEqual("^[a-f0-9]{64}$", properties["ingress_payload_sha256"]["pattern"])
        self.assertEqual(["accepted", "rejected"], properties["status"]["enum"])
        self.assertIn("PROVISOIRE", schema["description"])


class CommandLineTests(unittest.TestCase):
    def run_cli(self, *arguments: str) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = MODULE.main(list(arguments))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_package_scope_prints_the_canonical_package_digest(self) -> None:
        package = synthetic_package()
        with sovereign_temporary_directory() as directory:
            path = Path(directory) / "package.json"
            path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
            code, stdout, stderr = self.run_cli("--scope", "package", str(path))
            ingress_code, ingress_stdout, _ = self.run_cli("--scope", "ingress", str(path))
            raw = path.read_bytes()
        self.assertEqual(0, code, stderr)
        self.assertEqual(
            {"algorithm": "SHA-256", "hash_scope": "canonical-package-excluding-integrity", "sha256": MODULE.package_sha256(package)},
            json.loads(stdout),
        )
        self.assertEqual(0, ingress_code)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), json.loads(ingress_stdout)["sha256"])

    def test_refused_documents_exit_non_zero_without_echoing_content(self) -> None:
        with sovereign_temporary_directory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"synthetic-marker-7f3a": 1, "synthetic-marker-7f3a": 2}', encoding="utf-8")
            code, stdout, stderr = self.run_cli("--scope", "canonical", str(path))
            missing_code, _, missing_stderr = self.run_cli("--scope", "package", str(Path(directory) / "absent.json"))
        self.assertEqual(1, code)
        self.assertEqual("", stdout)
        self.assertIn("DUPLICATE_KEY", stderr)
        self.assertNotIn("synthetic-marker-7f3a", stderr)
        self.assertEqual(1, missing_code)
        self.assertNotIn("absent.json", missing_stderr)


if __name__ == "__main__":
    unittest.main()
