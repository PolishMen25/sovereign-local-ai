import importlib.util
from pathlib import Path
import sys
import unittest
from uuid import uuid4


MODULE_PATH = Path(__file__).parents[1] / "services" / "quarantine" / "conversation_import.py"
SPEC = importlib.util.spec_from_file_location("conversation_import", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def conversation() -> dict:
    return {"schema_version": "0.1.0", "conversation_id": str(uuid4()), "captured_at": "2026-08-31T12:00:00Z", "messages": [{"role": "user", "content": "Documente le NAS."}]}


class ConversationImportTests(unittest.TestCase):
    def test_clean_conversation_is_valid(self) -> None:
        MODULE.validate(conversation())

    def test_secret_is_rejected_before_storage(self) -> None:
        document = conversation()
        document["messages"][0]["content"] = "password: do-not-store"
        with self.assertRaises(ValueError):
            MODULE.validate(document)

    def test_unknown_fields_are_rejected(self) -> None:
        document = conversation()
        document["file_path"] = "/etc/passwd"
        with self.assertRaises(ValueError):
            MODULE.validate(document)
