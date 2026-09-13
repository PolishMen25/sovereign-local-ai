import unittest

from services.web import code_sandbox as cs


class CodeSandboxTests(unittest.TestCase):
    def test_available_is_bool(self):
        self.assertIn(cs.available(), (True, False))

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            cs.run_python("   ")

    def test_rejects_too_long(self):
        with self.assertRaises(ValueError):
            cs.run_python("x" * (cs.MAX_CODE_CHARS + 1))

    def test_runs_or_reports_unavailable(self):
        try:
            result = cs.run_python("print('hello_sbx')")
        except RuntimeError:
            self.skipTest("bwrap sandbox indisponible dans cet environnement")
        self.assertTrue(result["ok"])
        self.assertIn("hello_sbx", result["output"])


if __name__ == "__main__":
    unittest.main()
