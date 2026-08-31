import json
from pathlib import Path
import unittest

from services.web.authz import allowed


ROOT = Path(__file__).parents[1]


class AuthzPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = json.loads((ROOT / "configs" / "security" / "roles.json").read_text(encoding="utf-8"))

    def test_default_role_can_search_but_not_confirm(self) -> None:
        self.assertTrue(allowed(self.policy, "read_only", "knowledge.search_validated"))
        self.assertFalse(allowed(self.policy, "read_only", "proposal.confirm"))

    def test_unknown_roles_and_capabilities_are_denied(self) -> None:
        self.assertFalse(allowed(self.policy, "unknown", "chat.use"))
        self.assertFalse(allowed(self.policy, "owner", "shell"))


if __name__ == "__main__":
    unittest.main()
