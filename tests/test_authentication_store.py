from pathlib import Path
import hashlib
import unittest

from services.web.authentication import AuthenticationStore
from tests._temp_support import sovereign_temporary_directory


class FakeArgon2idHasher:
    def hash(self, password: str) -> str:
        return f"$argon2id$test${hashlib.sha256(password.encode()).hexdigest()}"

    def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == self.hash(password)


class AuthenticationStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = sovereign_temporary_directory()
        temporary_path = self.temporary.__enter__()
        self.store = AuthenticationStore(
            Path(temporary_path) / "auth.sqlite3",
            hasher=FakeArgon2idHasher(),
        )
        self.store.initialize()

    def tearDown(self) -> None:
        self.temporary.__exit__(None, None, None)

    def test_first_run_owner_and_csrf_bound_session(self) -> None:
        self.assertTrue(self.store.setup_required())
        self.store.initialize_owner("owner", "correct-horse-battery-staple")
        self.assertFalse(self.store.setup_required())
        session = self.store.authenticate("owner", "correct-horse-battery-staple")
        self.assertEqual(
            "owner",
            self.store.validate_session(
                session["session_token"],
                csrf_token=session["csrf_token"],
                require_csrf=True,
            ),
        )
        with self.assertRaises(PermissionError):
            self.store.validate_session(
                session["session_token"], csrf_token="wrong", require_csrf=True
            )
        details = self.store.session_details(session["session_token"])
        self.assertEqual("owner", details["username"])
        self.assertEqual(session["csrf_token"], details["csrf_token"])

    def test_password_is_never_stored_in_plaintext_and_setup_is_single_use(self) -> None:
        password = "unique-owner-password-123"
        self.store.initialize_owner("owner", password)
        raw = self.store.database.read_bytes()
        self.assertNotIn(password.encode(), raw)
        with self.assertRaises(RuntimeError):
            self.store.initialize_owner("second", "another-owner-password-456")

    def test_wrong_password_and_logged_out_session_are_refused(self) -> None:
        self.store.initialize_owner("owner", "correct-horse-battery-staple")
        with self.assertRaises(PermissionError):
            self.store.authenticate("owner", "wrong")
        session = self.store.authenticate("owner", "correct-horse-battery-staple")
        self.store.logout(session["session_token"])
        with self.assertRaises(PermissionError):
            self.store.validate_session(session["session_token"])


if __name__ == "__main__":
    unittest.main()
