"""Table-driven tests for the static URL/SSRF policy (url-ssrf-policy-v1).

Addresses and names come from reserved or generic examples: RFC 5737
(192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24), RFC 3849 (2001:db8::/32),
RFC 2606 (example.com/.org, .test, .example, .invalid, .localhost) and the
generic special-purpose ranges each class describes.  No real
infrastructure identifier is used.
"""

from __future__ import annotations

import contextlib
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
MODULE_PATH = PROJECT_ROOT / "services" / "quarantine" / "url_policy.py"
SPEC = importlib.util.spec_from_file_location("url_policy", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

M = MODULE

ALLOWED = (
    "https://example.com/",
    "https://www.example.org/wiki/Page?lang=fr&page=2#section",
    "https://docs.example.net/terms#policy",
    "https://xn--caf-dma.example.com/menu",
    "https://example.com/path;version=2",
    "https://11.22.33.44/public-literal",
    "https://[2a01:5:9::1]/public-literal",
)

# (url, exact set of expected reason codes)
REFUSALS = (
    # Not a string, too long, malformed.
    (None, {M.NOT_A_STRING}),
    (b"https://example.com/", {M.NOT_A_STRING}),
    ("https://example.com/" + "a" * M.MAX_URL_CHARS, {M.TOO_LONG}),
    ("", {M.MALFORMED}),
    ("https://exa mple.com/", {M.MALFORMED}),
    ("https://example.com/\npath", {M.MALFORMED}),
    ("https://example.com\\@example.org/", {M.MALFORMED, M.USERINFO}),
    ("https://exa​mple.com/", {M.MALFORMED}),
    ("https://[::1/", {M.MALFORMED}),
    ("https://::1/", {M.MALFORMED}),
    ("https://example.com:99999/", {M.MALFORMED}),
    ("https://example.com:44x/", {M.MALFORMED}),
    # Scheme.
    ("http://example.com/", {M.SCHEME_NOT_HTTPS}),
    ("ftp://example.com/", {M.SCHEME_NOT_HTTPS}),
    ("//example.com/", {M.SCHEME_NOT_HTTPS}),
    ("file:///etc/hosts", {M.SCHEME_NOT_HTTPS, M.HOST_MISSING}),
    ("javascript:alert(1)", {M.SCHEME_NOT_HTTPS, M.HOST_MISSING}),
    # Canonical form (refused, never rewritten).
    ("HTTPS://example.com/", {M.NOT_CANONICAL}),
    ("https://Example.COM/", {M.NOT_CANONICAL}),
    ("https://example.com./", {M.NOT_CANONICAL}),
    ("https://example.com:443/", {M.NOT_CANONICAL}),
    ("https://example.com:/", {M.NOT_CANONICAL}),
    ("https://example.com/café", {M.NOT_CANONICAL}),
    ("https://example.com/a|b", {M.NOT_CANONICAL}),
    ("https://café.example.com/", {M.NOT_CANONICAL}),
    ("https://[2001:DB8::1]/", {M.NOT_CANONICAL, M.IP_RESERVED}),
    # Userinfo.
    ("https://user:pass@example.com/", {M.USERINFO}),
    ("https://user@example.com/", {M.USERINFO}),
    ("https://@example.com/", {M.USERINFO}),
    ("https://example.org@example.com/", {M.USERINFO}),
    # Port.
    ("https://example.com:8443/", {M.PORT_NOT_DEFAULT}),
    ("https://example.com:80/", {M.PORT_NOT_DEFAULT}),
    # Host missing or invalid.
    ("https:///path", {M.HOST_MISSING}),
    ("https:example.com", {M.HOST_MISSING}),
    ("https://:8443/", {M.PORT_NOT_DEFAULT, M.HOST_MISSING}),
    ("https://exa_mple.com/", {M.HOST_INVALID}),
    ("https://-bad.example.com/", {M.HOST_INVALID}),
    ("https://a..b.example.com/", {M.HOST_INVALID}),
    ("https://" + "a" * 64 + ".example.com/", {M.HOST_INVALID}),
    ("https://%6c%6f%63%61%6c%68%6f%73%74/", {M.HOST_INVALID}),
    ("https://xn--abc-.example.com/", {M.HOST_INVALID}),
    ("https://ab--cd.example.com/", {M.HOST_INVALID}),
    ("https://[not-an-address]/", {M.HOST_INVALID}),
    ("https://[fe80::1%25eth0]/", {M.HOST_INVALID}),
    ("https://1.2.3.4.5/", {M.HOST_INVALID}),
    ("https://08.0.0.1/", {M.HOST_INVALID}),
    ("https://example.123/", {M.HOST_INVALID}),
    # Special-use and single-label names (RFC 2606, 6761, 6762, 8375).
    ("https://localhost/", {M.HOST_SINGLE_LABEL, M.HOST_SPECIAL_USE}),
    ("https://LOCALHOST./", {M.HOST_SINGLE_LABEL, M.HOST_SPECIAL_USE, M.NOT_CANONICAL}),
    ("https://ｌｏｃａｌｈｏｓｔ/", {M.HOST_SINGLE_LABEL, M.HOST_SPECIAL_USE, M.NOT_CANONICAL}),
    ("https://loc­alhost/", {M.MALFORMED}),
    ("https://api.localhost/", {M.HOST_SPECIAL_USE}),
    ("https://printer.local/", {M.HOST_SPECIAL_USE}),
    ("https://service.internal/", {M.HOST_SPECIAL_USE}),
    ("https://router.home.arpa/", {M.HOST_SPECIAL_USE}),
    ("https://1.0.0.127.in-addr.arpa/", {M.HOST_SPECIAL_USE}),
    ("https://site.test/", {M.HOST_SPECIAL_USE}),
    ("https://www.example/", {M.HOST_SPECIAL_USE}),
    ("https://host.invalid/", {M.HOST_SPECIAL_USE}),
    ("https://fileserver/", {M.HOST_SINGLE_LABEL}),
    # IPv4 literals by class.
    ("https://0.0.0.0/", {M.IP_UNSPECIFIED}),
    ("https://127.0.0.1/", {M.IP_LOOPBACK}),
    ("https://127.255.255.254/", {M.IP_LOOPBACK}),
    ("https://10.0.0.1/", {M.IP_PRIVATE}),
    ("https://172.16.5.4/", {M.IP_PRIVATE}),
    ("https://192.168.254.1/", {M.IP_PRIVATE}),
    ("https://169.254.10.20/", {M.IP_LINK_LOCAL}),
    ("https://100.64.0.1/", {M.IP_CGNAT}),
    ("https://224.0.0.251/", {M.IP_MULTICAST}),
    ("https://192.0.2.10/", {M.IP_RESERVED}),
    ("https://198.51.100.7/", {M.IP_RESERVED}),
    ("https://203.0.113.200/", {M.IP_RESERVED}),
    ("https://198.18.0.1/", {M.IP_RESERVED}),
    ("https://240.0.0.1/", {M.IP_RESERVED}),
    ("https://255.255.255.255/", {M.IP_RESERVED}),
    # IPv4 decimal, octal, hexadecimal and short forms.
    ("https://2130706433/", {M.IP_NONSTANDARD_FORM, M.IP_LOOPBACK}),
    ("https://0x7f000001/", {M.IP_NONSTANDARD_FORM, M.IP_LOOPBACK}),
    ("https://0177.0.0.1/", {M.IP_NONSTANDARD_FORM, M.IP_LOOPBACK}),
    ("https://127.1/", {M.IP_NONSTANDARD_FORM, M.IP_LOOPBACK}),
    ("https://0X0A.0.0.1/", {M.IP_NONSTANDARD_FORM, M.IP_PRIVATE, M.NOT_CANONICAL}),
    ("https://012.0.0.1/", {M.IP_NONSTANDARD_FORM, M.IP_PRIVATE}),
    ("https://１２７.0.0.1/", {M.IP_LOOPBACK, M.NOT_CANONICAL}),
    # IPv6 literals by class.
    ("https://[::]/", {M.IP_UNSPECIFIED}),
    ("https://[::1]/", {M.IP_LOOPBACK}),
    ("https://[fe80::1]/", {M.IP_LINK_LOCAL}),
    ("https://[fd12:3456:789a::1]/", {M.IP_UNIQUE_LOCAL}),
    ("https://[ff02::1]/", {M.IP_MULTICAST}),
    ("https://[2001:db8::1]/", {M.IP_RESERVED}),
    ("https://[3fff::1]/", {M.IP_RESERVED}),
    ("https://[2002:c000:201::1]/", {M.IP_RESERVED}),
    ("https://[2001::1]/", {M.IP_RESERVED}),
    ("https://[64:ff9b::a00:1]/", {M.IP_RESERVED}),
    ("https://[100::1]/", {M.IP_RESERVED}),
    ("https://[fec0::1]/", {M.IP_RESERVED}),
    # IPv4-mapped IPv6.
    ("https://[::ffff:127.0.0.1]/", {M.IP_IPV4_MAPPED, M.IP_LOOPBACK}),
    ("https://[::ffff:7f00:1]/", {M.IP_IPV4_MAPPED, M.IP_LOOPBACK, M.NOT_CANONICAL}),
    ("https://[::ffff:10.0.0.1]/", {M.IP_IPV4_MAPPED, M.IP_PRIVATE}),
    ("https://[::ffff:192.0.2.1]/", {M.IP_IPV4_MAPPED, M.IP_RESERVED}),
    # Cloud metadata endpoints.
    ("https://169.254.169.254/latest/meta-data/", {M.IP_LINK_LOCAL, M.IP_METADATA}),
    ("https://0xa9fea9fe/", {M.IP_NONSTANDARD_FORM, M.IP_LINK_LOCAL, M.IP_METADATA}),
    ("https://[::ffff:169.254.169.254]/", {M.IP_IPV4_MAPPED, M.IP_LINK_LOCAL, M.IP_METADATA}),
    ("https://[fd00:ec2::254]/", {M.IP_UNIQUE_LOCAL, M.IP_METADATA}),
    ("https://100.100.100.200/", {M.IP_CGNAT, M.IP_METADATA}),
    ("https://168.63.129.16/", {M.IP_METADATA}),
    ("https://metadata.google.internal/", {M.HOST_SPECIAL_USE, M.HOST_METADATA}),
    ("https://instance-data/", {M.HOST_SINGLE_LABEL, M.HOST_METADATA}),
    # Signed and credential parameters (names only; values are placeholders).
    ("https://files.example.com/o?X-Amz-Algorithm=a&X-Amz-Credential=c&X-Amz-Signature=s", {M.PARAM_SIGNED}),
    ("https://files.example.com/o?x-amz-security-token=t", {M.PARAM_SIGNED}),
    ("https://storage.example.com/o?X-Goog-Signature=s", {M.PARAM_SIGNED}),
    ("https://blob.example.com/c/b?sv=v&se=e&sp=r&sig=s", {M.PARAM_SIGNED}),
    ("https://cdn.example.com/v?Policy=p&Signature=s&Key-Pair-Id=k", {M.PARAM_SIGNED}),
    ("https://api.example.com/v1?token=t", {M.PARAM_CREDENTIAL}),
    ("https://api.example.com/v1?TOKEN=t", {M.PARAM_CREDENTIAL}),
    ("https://api.example.com/v1?%74oken=t", {M.PARAM_CREDENTIAL}),
    ("https://api.example.com/v1?q=x;access_token=t", {M.PARAM_CREDENTIAL}),
    ("https://maps.example.com/js?key=k", {M.PARAM_CREDENTIAL}),
    ("https://api.example.com/v1?api_key=k", {M.PARAM_CREDENTIAL}),
    ("https://app.example.com/cb#access_token=t&state=s", {M.PARAM_CREDENTIAL}),
    ("https://app.example.com/#/cb?id_token=t", {M.PARAM_CREDENTIAL}),
    ("https://shop.example.com/cart;jsessionid=s", {M.PARAM_CREDENTIAL}),
    # Several classes at once.
    ("http://user:pass@10.0.0.1:8080/?token=t", {M.SCHEME_NOT_HTTPS, M.USERINFO, M.PORT_NOT_DEFAULT, M.IP_PRIVATE, M.PARAM_CREDENTIAL}),
)


class UrlPolicyTableTests(unittest.TestCase):
    def test_allowed_urls_pass(self) -> None:
        for url in ALLOWED:
            with self.subTest(url=url):
                self.assertEqual((), M.evaluate_url(url))
                self.assertTrue(M.is_allowed(url))
                M.check_url(url)

    def test_each_refusal_yields_exactly_the_expected_reasons(self) -> None:
        for url, expected in REFUSALS:
            with self.subTest(url=url if not isinstance(url, str) or len(url) < 120 else url[:40] + "..."):
                reasons = M.evaluate_url(url)
                self.assertEqual(expected, set(reasons))
                self.assertEqual(tuple(sorted(reasons)), reasons)
                self.assertFalse(M.is_allowed(url))

    def test_the_table_exercises_every_reason_code(self) -> None:
        exercised = set().union(*(expected for _, expected in REFUSALS))
        self.assertEqual(set(M.REASON_CODES), exercised)

    def test_credential_reasons_tolerate_malformed_text(self) -> None:
        self.assertEqual((M.PARAM_SIGNED,), M.credential_reasons("https://exa mple/?X-Amz-Signature=s"))
        self.assertEqual((M.USERINFO,), M.credential_reasons("http://user:pass@host.example/"))
        self.assertEqual((), M.credential_reasons("https://example.com/about#key"))
        self.assertEqual((), M.credential_reasons(None))
        self.assertTrue(M.CREDENTIAL_REASON_CODES <= M.REASON_CODES)


class UrlPolicySafetyTests(unittest.TestCase):
    def test_no_name_resolution_or_socket_is_ever_used(self) -> None:
        names = ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "create_connection", "socket")
        with contextlib.ExitStack() as stack:
            mocks = [stack.enter_context(mock.patch.object(socket, name, side_effect=AssertionError(name))) for name in names]
            for url in ALLOWED + tuple(url for url, _ in REFUSALS):
                M.evaluate_url(url)
                M.credential_reasons(url)
        for patched in mocks:
            patched.assert_not_called()
        source = MODULE_PATH.read_text(encoding="utf-8")
        for forbidden in ("import socket", "urllib.request", "http.client", "import ssl", "getaddrinfo"):
            self.assertNotIn(forbidden, source)

    def test_refusals_never_contain_the_url(self) -> None:
        marker = "synthetic-marker-51d2"
        url = f"https://{marker}.internal:8443/o?X-Amz-Signature={marker}&token={marker}"
        with self.assertRaises(M.UrlPolicyError) as caught:
            M.check_url(url)
        error = caught.exception
        self.assertNotIn(marker, str(error))
        self.assertTrue(set(error.reasons) <= M.REASON_CODES)
        for reason in M.evaluate_url(url):
            self.assertNotIn(marker, reason)

    def test_the_specification_documents_every_reason_code(self) -> None:
        text = (PROJECT_ROOT / "docs" / "security" / "url-ssrf-policy.md").read_text(encoding="utf-8")
        self.assertIn(M.POLICY_ID, text)
        self.assertIn("PROVISOIRE", text)
        for code in M.REASON_CODES:
            self.assertIn(f"`{code}`", text)

    def test_threat_model_t09_links_the_specification(self) -> None:
        text = (PROJECT_ROOT / "docs" / "security" / "threat-model.md").read_text(encoding="utf-8")
        row = next(line for line in text.splitlines() if line.startswith("| T09 |"))
        self.assertIn("url-ssrf-policy.md", row)


class UrlPolicyCommandLineTests(unittest.TestCase):
    def test_cli_reports_codes_without_echoing_urls(self) -> None:
        marker = "synthetic-marker-51d2"
        with sovereign_temporary_directory() as directory:
            path = Path(directory) / "urls.txt"
            path.write_text(f"https://example.com/\nhttps://example.com/?token={marker}\n", encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = M.main([str(path)])
            clean = Path(directory) / "clean.txt"
            clean.write_text("https://example.com/\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                clean_code = M.main([str(clean)])
        self.assertEqual(1, code)
        self.assertEqual(0, clean_code)
        self.assertNotIn(marker, stdout.getvalue())
        rows = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual([[], [M.PARAM_CREDENTIAL]], [row["reasons"] for row in rows])


if __name__ == "__main__":
    unittest.main()
