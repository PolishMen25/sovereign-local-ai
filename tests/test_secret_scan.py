"""Tests for the candidate collector-secret-scan-v1 scanner.

This repository is public.  Every secret-shaped value below is assembled at
runtime from a hash of a fixed synthetic seed, so no token, key header or
signed URL appears as a literal in the source.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest import mock

from tests._temp_support import sovereign_temporary_directory


PROJECT_ROOT = Path(__file__).parents[1]
MODULE_PATH = PROJECT_ROOT / "services" / "quarantine" / "secret_scan.py"
SPEC = importlib.util.spec_from_file_location("secret_scan", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

RELAY_PATH = PROJECT_ROOT / "tools" / "codex_conversation_sync.py"
RELAY_SPEC = importlib.util.spec_from_file_location("codex_conversation_sync_for_secret_scan", RELAY_PATH)
assert RELAY_SPEC is not None and RELAY_SPEC.loader is not None
RELAY = importlib.util.module_from_spec(RELAY_SPEC)
RELAY_SPEC.loader.exec_module(RELAY)

S = MODULE


def synthetic(length: int, seed: str = "value") -> str:
    """Deterministic mixed-case alphanumeric filler with a letter and a digit."""

    material = ""
    counter = 0
    while len(material) < length:
        material += hashlib.sha256(f"sovereign-synthetic-{seed}-{counter}".encode()).hexdigest()
        counter += 1
    mixed = "".join(c.upper() if i % 3 == 0 else c for i, c in enumerate(material))
    return ("Aa1" + mixed)[:length]


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def jwt_shape() -> str:
    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64url(json.dumps({"sub": "synthetic", "iat": 0}).encode())
    return f"{header}.{payload}.{b64url(hashlib.sha256(b'synthetic').digest())}"


VALUE = synthetic(40)
PEM_HEADER = "-----" + "BEGIN " + "PRIVATE KEY" + "-----"

# Five shapes that SECRET_PATTERN in services/quarantine/conversation_import.py
# (main) does not match.  Read from the code, not from a live probe: the
# deployment state is not re-verified here.
FIVE_MAIN_PATTERN_GAPS = (
    ("gh" + "p_" + synthetic(36, "ghp"), S.KNOWN_PREFIX),
    ("Authorization: " + "Bea" + "rer " + VALUE, S.BEARER_TOKEN),
    ("https://bucket.example.com/object?X-Amz-" + "Signature=" + hashlib.sha256(b"sig").hexdigest(), S.SIGNED_URL),
    ("tok" + "en = " + synthetic(24, "token"), S.TOKEN_ASSIGNMENT),
    (PEM_HEADER + "\n" + synthetic(64, "pem") + "\n", S.PRIVATE_KEY),
)

MORE_SHAPES = (
    ("github" + "_pat_" + synthetic(40, "pat"), S.KNOWN_PREFIX),
    ("glp" + "at-" + synthetic(20, "gl"), S.KNOWN_PREFIX),
    ("xo" + "xb-" + synthetic(30, "slack"), S.KNOWN_PREFIX),
    ("s" + "k-" + synthetic(40, "sk"), S.KNOWN_PREFIX),
    ("cf" + "pat_" + synthetic(30, "cf"), S.KNOWN_PREFIX),
    ("h" + "f_" + synthetic(34, "hf"), S.KNOWN_PREFIX),
    ("AK" + "IA" + synthetic(16, "aws").upper(), S.KNOWN_PREFIX),
    ("AI" + "za" + synthetic(35, "google"), S.KNOWN_PREFIX),
    ("-----" + "BEGIN RSA " + "PRIVATE KEY" + "-----", S.PRIVATE_KEY),
    ("-----" + "BEGIN OPENSSH " + "PRIVATE KEY" + "-----", S.PRIVATE_KEY),
    ("-----" + "BEGIN PGP " + "PRIVATE KEY BLOCK" + "-----", S.PRIVATE_KEY),
    ("pass" + "word: ", S.CREDENTIAL_ASSIGNMENT),
    ("Le mot de pa" + "sse = " + synthetic(8, "fr"), S.CREDENTIAL_ASSIGNMENT),
    ("md" + "p: " + synthetic(8, "mdp"), S.CREDENTIAL_ASSIGNMENT),
    ('{"api' + '_key": "' + synthetic(20, "json") + '"}', S.CREDENTIAL_ASSIGNMENT),
    ("ACCESS" + "_TOKEN=" + synthetic(20, "env"), S.CREDENTIAL_ASSIGNMENT),
    ("client" + "Secret: '" + synthetic(20, "camel") + "'", S.TOKEN_ASSIGNMENT),
    ("X-Api-" + "Token: " + synthetic(20, "header"), S.TOKEN_ASSIGNMENT),
    (jwt_shape(), S.JWT),
    ("Authorization: " + "Basic " + base64.b64encode(("user:" + synthetic(12, "basic")).encode()).decode(), S.BASIC_AUTH),
    ("https://api.example.com/v1?access" + "_token=" + synthetic(20, "qs"), S.URL_CREDENTIAL_PARAM),
    ("https://cdn.example.com/v?Policy=p&Signa" + "ture=" + synthetic(20, "cf-sig") + "&Key-Pair-Id=k", S.SIGNED_URL),
    ("postgres://app:" + synthetic(16, "db") + "@db.example.com/prod", S.URL_USERINFO),
    ("nonce " + synthetic(20, "mixed") + " fin", S.MIXED_TOKEN),
)

CLEAN_SAMPLES = (
    "Le tokenizer produit 32000 tokens ; max_tokens: 4096 et key_size = 256.",
    "token = tokenizer.encode(text)",
    "Le secret : la régularité des mesures.",
    "sort key: name",
    "Bearer tokens are short-lived.",
    "La politique de mot de passe exige douze caractères.",
    "Voir https://example.com/search?q=secret+policy#key et https://docs.example.org/terms#policy",
    "Dépôt : ssh://git@example.com/depot.git",
    "sha256 " + hashlib.sha256(b"clean").hexdigest(),
    "uuid 123e4567-e89b-42d3-a456-426614174000",
    "-----BEGIN PUBLIC KEY-----",
    "Les mesures détaillées restent dans l'inventaire interne.",
    "",
)


class SecretScanDetectionTests(unittest.TestCase):
    def test_detects_the_five_shapes_main_secret_pattern_accepts(self) -> None:
        for text, category in FIVE_MAIN_PATTERN_GAPS:
            with self.subTest(category=category):
                result = S.scan_text(text)
                self.assertEqual(S.POLICY_ID, result.policy_id)
                self.assertIn(category, result.categories)
                self.assertFalse(result.clean)

    def test_detects_every_documented_category(self) -> None:
        seen = set()
        for text, category in FIVE_MAIN_PATTERN_GAPS + MORE_SHAPES:
            with self.subTest(category=category, index=len(seen)):
                categories = S.scan_text(text).categories
                self.assertIn(category, categories)
                self.assertEqual(tuple(sorted(categories)), categories)
                self.assertTrue(set(categories) <= S.CATEGORIES)
                seen.add(category)
        self.assertEqual(set(S.CATEGORIES), seen)

    def test_clean_text_yields_no_category(self) -> None:
        for text in CLEAN_SAMPLES:
            with self.subTest(text=text[:40]):
                self.assertEqual((), S.scan_text(text).categories)
                self.assertTrue(S.scan_text(text).clean)

    def test_policy_id_is_versioned(self) -> None:
        self.assertEqual("collector-secret-scan-v1", S.POLICY_ID)

    def test_documents_are_scanned_in_keys_values_and_pairs(self) -> None:
        document = {
            "schema_version": "0.1.0",
            "messages": [
                {"role": "user", "content": "Bonjour"},
                {"role": "assistant", "content": FIVE_MAIN_PATTERN_GAPS[0][0]},
            ],
            "usage": {"input_tokens": 12, "output_tokens": 34, "ratio": 0.5, "cached": None, "final": True},
        }
        self.assertEqual((S.KNOWN_PREFIX, S.MIXED_TOKEN), S.scan_document(document).categories)
        self.assertEqual((S.CREDENTIAL_ASSIGNMENT,), S.scan_document({"password": ""}).categories)
        self.assertIn(S.TOKEN_ASSIGNMENT, S.scan_document({"refresh_token": synthetic(24, "pair")}).categories)
        self.assertEqual((), S.scan_document({"session_key": "short", "max_tokens": 4096}).categories)
        self.assertIn(S.PRIVATE_KEY, S.scan_document({PEM_HEADER: 1}).categories)
        self.assertEqual((), S.scan_document({"messages": [{"content": text} for text in CLEAN_SAMPLES]}).categories)

    def test_coverage_is_at_least_the_client_relay_redaction(self) -> None:
        borderline = (
            "passwd: x",
            "api-key = y",
            "mdp=z",
            "Bea" + "rer " + synthetic(12, "short"),
            "s" + "k-abcdefghijkl",
            "XO" + "XS-" + synthetic(14, "upper"),
            synthetic(16, "mixed-only"),
            "a!" + synthetic(10, "symbol"),
        )
        for text in tuple(text for text, _ in FIVE_MAIN_PATTERN_GAPS + MORE_SHAPES) + borderline:
            with self.subTest(index=hashlib.sha256(text.encode()).hexdigest()[:8]):
                if "://" in text and "@" not in text.partition("://")[2].partition("/")[0]:
                    # The relay strips every query string; only signed or
                    # credential parameters are secrets for the scanner.
                    continue
                if RELAY.sanitize_text(text) != text:
                    self.assertFalse(S.scan_text(text).clean)


class SecretScanHygieneTests(unittest.TestCase):
    def test_results_never_contain_the_matched_text(self) -> None:
        for text, _category in FIVE_MAIN_PATTERN_GAPS + MORE_SHAPES:
            result = S.scan_text(text)
            rendered = repr(result) + str(result) + json.dumps(result.categories)
            secret_part = text.split()[-1] if " " in text.strip() else text
            for fragment in {secret_part[-12:], VALUE, text.strip()}:
                if len(fragment) >= 8:
                    self.assertNotIn(fragment, rendered)
            for category in result.categories:
                self.assertRegex(category, r"^SECRET_[A-Z_]+$")

    def test_refusals_never_contain_the_scanned_text(self) -> None:
        secret = FIVE_MAIN_PATTERN_GAPS[0][0]
        cases = (
            (lambda: S.scan_text(b"bytes are not text"), "NOT_TEXT"),
            (lambda: S.scan_text(secret + "x" * S.MAX_SCAN_CHARS), "SIZE_EXCEEDED"),
            (lambda: S.scan_document({"a": secret, "b": b"raw"}), "UNSUPPORTED_TYPE"),
            (lambda: S.scan_document({"a": secret, 7: "x"}), "UNSUPPORTED_TYPE"),
            (lambda: S.scan_document({"a": secret, "b": (1, 2)}), "UNSUPPORTED_TYPE"),
            (lambda: S.scan_document([secret, "y" * S.MAX_SCAN_CHARS]), "SIZE_EXCEEDED"),
        )
        for call, code in cases:
            with self.subTest(code=code), self.assertRaises(S.SecretScanError) as caught:
                call()
            error = caught.exception
            self.assertEqual(code, error.code)
            self.assertNotIn(secret, str(error))
            self.assertNotIn(secret, repr(error.args))
            self.assertIsNone(error.__cause__)
            self.assertIsNone(error.__context__)

        nested: list = [secret]
        for _ in range(S.MAX_DEPTH + 1):
            nested = [nested]
        with self.assertRaises(S.SecretScanError) as caught:
            S.scan_document(nested)
        self.assertEqual("DEPTH_EXCEEDED", caught.exception.code)
        self.assertNotIn(secret, str(caught.exception))

    def test_scanning_never_touches_the_network(self) -> None:
        names = ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "create_connection", "socket")
        with contextlib.ExitStack() as stack:
            mocks = [stack.enter_context(mock.patch.object(socket, name, side_effect=AssertionError(name))) for name in names]
            for text, _ in FIVE_MAIN_PATTERN_GAPS + MORE_SHAPES:
                S.scan_text(text)
        for patched in mocks:
            patched.assert_not_called()
        source = MODULE_PATH.read_text(encoding="utf-8")
        for forbidden in ("import socket", "urllib.request", "http.client", "import ssl"):
            self.assertNotIn(forbidden, source)

    def test_signed_url_detection_reuses_the_url_policy(self) -> None:
        url_policy = S._URL_POLICY
        self.assertEqual("url-ssrf-policy-v1", url_policy.POLICY_ID)
        self.assertTrue(set(S._URL_REASON_TO_CATEGORY) <= url_policy.CREDENTIAL_REASON_CODES)


class SecretScanCommandLineTests(unittest.TestCase):
    def run_cli(self, *arguments: str) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = S.main(list(arguments))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_cli_reports_categories_only(self) -> None:
        secret = FIVE_MAIN_PATTERN_GAPS[1][0]
        with sovereign_temporary_directory() as directory:
            text_path = Path(directory) / "export.txt"
            text_path.write_text("Bonjour\n" + secret + "\n", encoding="utf-8")
            json_path = Path(directory) / "export.json"
            json_path.write_text(json.dumps({"messages": [{"content": secret}]}), encoding="utf-8")
            clean_path = Path(directory) / "clean.txt"
            clean_path.write_text("Rien de sensible.\n", encoding="utf-8")
            broken_path = Path(directory) / "broken.json"
            broken_path.write_text('{"content": "' + secret, encoding="utf-8")
            results = {
                "text": self.run_cli(str(text_path)),
                "json": self.run_cli("--json", str(json_path)),
                "clean": self.run_cli(str(clean_path)),
                "broken": self.run_cli("--json", str(broken_path)),
            }
        self.assertEqual(1, results["text"][0])
        self.assertEqual(1, results["json"][0])
        self.assertEqual(0, results["clean"][0])
        self.assertEqual(2, results["broken"][0])
        self.assertIn(S.BEARER_TOKEN, json.loads(results["text"][1])["categories"])
        self.assertEqual(S.POLICY_ID, json.loads(results["json"][1])["policy_id"])
        for _code, stdout, stderr in results.values():
            self.assertNotIn(VALUE, stdout + stderr)

    def test_cli_json_mode_refuses_what_would_hide_a_value(self) -> None:
        secret = FIVE_MAIN_PATTERN_GAPS[0][0]
        with sovereign_temporary_directory() as directory:
            duplicate = Path(directory) / "duplicate.json"
            # json.loads would keep only the last "a" and never scan the secret.
            duplicate.write_text('{"a": "' + secret + '", "a": "x"}', encoding="utf-8")
            deep = Path(directory) / "deep.json"
            deep.write_text("[" * 200_000 + "]" * 200_000, encoding="utf-8")
            nested = Path(directory) / "nested.json"
            nested.write_text("[" * (S.MAX_DEPTH + 2) + "]" * (S.MAX_DEPTH + 2), encoding="utf-8")
            text_mode = self.run_cli(str(duplicate))
            results = {
                "duplicate": self.run_cli("--json", str(duplicate)),
                "deep": self.run_cli("--json", str(deep)),
                "nested": self.run_cli("--json", str(nested)),
            }
        self.assertEqual(1, text_mode[0])
        self.assertIn(S.KNOWN_PREFIX, json.loads(text_mode[1])["categories"])
        expected = {"duplicate": "DUPLICATE_KEY", "deep": "DEPTH_EXCEEDED", "nested": "DEPTH_EXCEEDED"}
        for name, (code, stdout, stderr) in results.items():
            with self.subTest(case=name):
                self.assertEqual(2, code)
                self.assertEqual("", stdout)
                self.assertIn(expected[name], stderr)
                self.assertNotIn(secret, stderr)
                self.assertNotIn("Traceback", stderr)


if __name__ == "__main__":
    unittest.main()
