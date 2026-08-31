from pathlib import Path
import unittest

from services.orchestrator.dispatch import prepare_request
from services.orchestrator.registry import load_registry


ROOT = Path(__file__).parents[1]


class OrchestratorDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = load_registry(ROOT / "configs" / "agents" / "registry.json")

    def test_draft_profile_cannot_be_called(self) -> None:
        with self.assertRaisesRegex(ValueError, "not enabled"):
            prepare_request(self.registry, {"schema_version": "local-chat-request.v1", "request_id": "req-123456", "profile_id": "code_reviewer", "message": "analyse"})

    def test_unknown_profile_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown profile"):
            prepare_request(self.registry, {"schema_version": "local-chat-request.v1", "request_id": "req-123456", "profile_id": "unknown_agent", "message": "analyse"})


if __name__ == "__main__":
    unittest.main()
