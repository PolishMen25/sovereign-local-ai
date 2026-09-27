"""D-035: the chat actions switch is strict, fail-closed and read once."""

from __future__ import annotations

import dataclasses
import unittest

from services.web import action_switch
from services.web.action_switch import ActionSwitch, ENVIRONMENT_VARIABLE
from services.web.app import WebState


class ParseTests(unittest.TestCase):
    def parse(self, raw):
        journal: list[str] = []
        return action_switch.parse(raw, log=journal.append), journal

    def test_absent_empty_and_zero_disable_silently(self) -> None:
        for raw in (None, "", "0"):
            switch, journal = self.parse(raw)
            self.assertFalse(switch.enabled, raw)
            self.assertEqual(journal, [], raw)

    def test_only_the_exact_value_one_enables(self) -> None:
        switch, journal = self.parse("1")
        self.assertTrue(switch.enabled)
        self.assertEqual(journal, [])

    def test_any_other_value_disables_with_a_warning(self) -> None:
        for raw in ("true", "TRUE", "yes", "on", "enabled", " 1", "1 ", "1\n", "01", "10", "2", "-1", "１", "0x1", " ", "00", "false"):
            switch, journal = self.parse(raw)
            self.assertFalse(switch.enabled, repr(raw))
            self.assertEqual(len(journal), 1, repr(raw))
            self.assertIn("warning", journal[0])
            self.assertIn(ENVIRONMENT_VARIABLE, journal[0])

    def test_the_warning_never_echoes_the_rejected_value(self) -> None:
        switch, journal = self.parse("pasted-token-4f9c2a")
        self.assertFalse(switch.enabled)
        self.assertNotIn("pasted-token-4f9c2a", journal[0])

    def test_the_switch_is_immutable(self) -> None:
        switch = action_switch.parse("1", log=lambda _: None)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            switch.enabled = False  # type: ignore[misc]


class EnvironmentTests(unittest.TestCase):
    def read(self, environ):
        journal: list[str] = []
        return action_switch.from_environment(environ, log=journal.append), journal

    def test_disabled_by_default(self) -> None:
        switch, journal = self.read({})
        self.assertFalse(switch.enabled)
        self.assertEqual(journal, ["web config actions_enabled=0"])

    def test_enabled_by_the_exact_value(self) -> None:
        switch, journal = self.read({ENVIRONMENT_VARIABLE: "1"})
        self.assertTrue(switch.enabled)
        self.assertEqual(journal, ["web config actions_enabled=1"])

    def test_garbage_disables_and_warns_before_the_state_line(self) -> None:
        switch, journal = self.read({ENVIRONMENT_VARIABLE: "true"})
        self.assertFalse(switch.enabled)
        self.assertEqual(len(journal), 2)
        self.assertIn("warning", journal[0])
        self.assertEqual(journal[1], "web config actions_enabled=0")

    def test_other_variables_do_not_enable_actions(self) -> None:
        switch, _ = self.read({"SOVEREIGN_TOOLS_ENABLED": "1", "SOVEREIGN_ACTIONS": "1", "sovereign_actions_enabled": "1"})
        self.assertFalse(switch.enabled)


class WebStateTests(unittest.TestCase):
    def test_gateway_state_is_disabled_unless_given_an_enabled_switch(self) -> None:
        self.assertFalse(WebState(None, None, None, None, None, "x" * 32).actions_enabled)
        self.assertFalse(WebState(None, None, None, None, None, "x" * 32, action_switch=ActionSwitch()).actions_enabled)
        self.assertTrue(WebState(None, None, None, None, None, "x" * 32, action_switch=ActionSwitch(enabled=True)).actions_enabled)

    def test_a_truthy_non_boolean_does_not_enable_actions(self) -> None:
        state = WebState(None, None, None, None, None, "x" * 32, action_switch=ActionSwitch(enabled="1"))  # type: ignore[arg-type]
        self.assertFalse(state.actions_enabled)


if __name__ == "__main__":
    unittest.main()
