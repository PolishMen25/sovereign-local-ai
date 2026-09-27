import tempfile
import unittest

from services.inference.core_server import bind_address
from tests._private_endpoint_support import CORE_ENDPOINT, QWEN_ENDPOINT, write_private_endpoints


class BindAddressTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.directory = self._directory.name

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
            with self.subTest(case=index), self.assertRaises(SystemExit) as caught:
                bind_address(environ)
            self.assertIn("refusing to start", str(caught.exception.code))
            self.assertNotIn(CORE_ENDPOINT.host, str(caught.exception.code))
            self.assertNotIn(self.directory, str(caught.exception.code))


if __name__ == "__main__":
    unittest.main()
