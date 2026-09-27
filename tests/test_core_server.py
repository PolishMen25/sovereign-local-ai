import contextlib
import io
import tempfile
import unittest

from services.common.private_endpoints import EXIT_CONFIGURATION_REFUSED
from services.inference.core_server import bind_address
from tests._private_endpoint_support import CORE_ENDPOINT, QWEN_ENDPOINT, trust_test_account, write_private_endpoints


class BindAddressTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.directory = self._directory.name
        trust_test_account(self)

    def test_binds_to_the_configured_private_address(self) -> None:
        environ = write_private_endpoints(self.directory, CORE_ENDPOINT)
        self.assertEqual(bind_address(environ), (CORE_ENDPOINT.host, CORE_ENDPOINT.port))
        environ["SOVEREIGN_CORE_PORT"] = str(CORE_ENDPOINT.port)
        self.assertEqual(bind_address(environ), (CORE_ENDPOINT.host, CORE_ENDPOINT.port))

    def test_refuses_to_start_without_configuration_or_on_port_mismatch(self) -> None:
        cases = (
            lambda: {},
            lambda: write_private_endpoints(self.directory, QWEN_ENDPOINT),
            lambda: {**write_private_endpoints(self.directory, CORE_ENDPOINT), "SOVEREIGN_CORE_PORT": "9001"},
            lambda: {**write_private_endpoints(self.directory, CORE_ENDPOINT), "SOVEREIGN_CORE_PORT": ""},
        )
        for index, case in enumerate(cases):
            environ = case()  # each case rewrites the private file before use
            stderr = io.StringIO()
            with self.subTest(case=index), self.assertRaises(SystemExit) as caught, contextlib.redirect_stderr(stderr):
                bind_address(environ)
            self.assertEqual(caught.exception.code, EXIT_CONFIGURATION_REFUSED)
            self.assertIn("refusing to start", stderr.getvalue())
            self.assertNotIn(CORE_ENDPOINT.host, stderr.getvalue())
            self.assertNotIn(self.directory, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
