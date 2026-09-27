import copy
import json
from pathlib import Path
import re
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
EVAL_SUITE_DIR = ROOT / "configs" / "evaluation" / "agents"
EVAL_SUITE_ID = re.compile(r"^agent-[a-z0-9_]+\.v1$")
EVAL_SUITE_SCHEMA = "agent-evaluation-suite.v1"
EVAL_SUITE_SECTIONS = ("quality", "least_privilege", "isolation")
EVAL_SUITE_KEYS = frozenset({"schema_version", "eval_suite", "profile_id", "profile_version", *EVAL_SUITE_SECTIONS})


def eval_suite_violations(registry: dict, suite_dir: Path) -> list[str]:
    """Why each non-draft profile lacks a usable per-profile suite; empty means compliant.

    Contract (docs/agents/overview.md): a profile that leaves ``draft`` must name
    a file ``<suite_dir>/<eval_suite>.json`` bound to its id and version, with at
    least one quality, one least-privilege and one isolation case.  Any status
    other than ``draft`` is covered, so an unknown status fails closed too.
    """

    violations = []
    for profile in registry["profiles"]:
        if profile.get("status") == "draft":
            continue
        identifier = profile.get("id")
        suite_id = profile.get("eval_suite")
        if not isinstance(suite_id, str) or EVAL_SUITE_ID.fullmatch(suite_id) is None:
            violations.append(f"{identifier}: eval_suite is missing or not a safe suite id")
            continue
        path = suite_dir / f"{suite_id}.json"
        if path.is_symlink() or not path.is_file():
            violations.append(f"{identifier}: suite file {suite_id}.json is missing")
            continue
        try:
            suite = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            violations.append(f"{identifier}: suite file {suite_id}.json is not valid JSON")
            continue
        if not isinstance(suite, dict) or set(suite) != EVAL_SUITE_KEYS:
            violations.append(f"{identifier}: suite {suite_id} must hold exactly {', '.join(sorted(EVAL_SUITE_KEYS))}")
            continue
        if suite["schema_version"] != EVAL_SUITE_SCHEMA:
            violations.append(f"{identifier}: suite {suite_id} schema_version is unsupported")
            continue
        if (suite["eval_suite"], suite["profile_id"], suite["profile_version"]) != (suite_id, identifier, profile.get("version")):
            violations.append(f"{identifier}: suite {suite_id} is not bound to this profile id and version")
            continue
        case_ids = []
        for section in EVAL_SUITE_SECTIONS:
            cases = suite[section]
            if not isinstance(cases, list) or not cases or any(
                    not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"] for case in cases):
                violations.append(f"{identifier}: suite {suite_id} has no valid {section} case")
                break
            case_ids.extend(case["id"] for case in cases)
        else:
            if len(case_ids) != len(set(case_ids)):
                violations.append(f"{identifier}: suite {suite_id} repeats a case id")
    return violations


def bound_suite(profile: dict) -> dict:
    return {
        "schema_version": EVAL_SUITE_SCHEMA,
        "eval_suite": profile["eval_suite"],
        "profile_id": profile["id"],
        "profile_version": profile["version"],
        "quality": [{"id": "quality-01"}],
        "least_privilege": [{"id": "least-privilege-01"}],
        "isolation": [{"id": "isolation-01"}],
    }


class AgentRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = json.loads((ROOT / "configs" / "agents" / "registry.json").read_text(encoding="utf-8"))

    def test_registry_contains_sixty_unique_logical_profiles(self) -> None:
        profiles = self.registry["profiles"]
        self.assertEqual(self.registry["schema_version"], "agent-profile-registry.v1")
        self.assertEqual(len(profiles), 60)
        self.assertEqual(len({profile["id"] for profile in profiles}), 60)

    def test_profiles_are_proposal_only_and_have_no_dangerous_capability(self) -> None:
        forbidden = {"shell", "filesystem.read_arbitrary", "filesystem.write_arbitrary", "network.arbitrary", "secrets.read"}
        for profile in self.registry["profiles"]:
            self.assertEqual(profile["status"], "draft")
            self.assertEqual(profile["action_policy"], "proposal_only")
            self.assertFalse(profile["memory_policy"]["writes"])
            self.assertTrue(forbidden.isdisjoint(profile["capabilities"]))
            self.assertTrue(forbidden.isdisjoint(profile["tool_allowlist"]))

    def test_profiles_have_stable_eval_and_output_contracts(self) -> None:
        for profile in self.registry["profiles"]:
            self.assertRegex(profile["version"], r"^\d+\.\d+\.\d+$")
            self.assertRegex(profile["eval_suite"], EVAL_SUITE_ID)
            self.assertEqual(profile["output_schema"], "local-assistant-response.v1")


class AgentEvalSuiteGateTests(unittest.TestCase):
    """A profile may leave ``draft`` only with its own evaluation suite (G8, M5.1)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = json.loads((ROOT / "configs" / "agents" / "registry.json").read_text(encoding="utf-8"))

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.suite_dir = Path(self.directory.name)
        self.changed = copy.deepcopy(self.registry)
        self.profile = self.changed["profiles"][0]

    def tearDown(self) -> None:
        self.directory.cleanup()

    def write_suite(self, suite) -> None:
        text = suite if isinstance(suite, str) else json.dumps(suite)
        (self.suite_dir / f"{self.profile['eval_suite']}.json").write_text(text, encoding="utf-8")

    def test_every_non_draft_profile_of_the_registry_has_a_suite(self) -> None:
        self.assertEqual([], eval_suite_violations(self.registry, EVAL_SUITE_DIR))
        drafts = [profile for profile in self.registry["profiles"] if profile["status"] == "draft"]
        self.assertEqual(60, len(drafts))

    def test_non_draft_profile_without_a_suite_is_refused(self) -> None:
        for status in ("enabled", "disabled", "retired", "active", None):
            with self.subTest(status=status):
                self.profile["status"] = status
                violations = eval_suite_violations(self.changed, self.suite_dir)
                self.assertEqual([f"{self.profile['id']}: suite file {self.profile['eval_suite']}.json is missing"], violations)
        self.profile["status"] = "draft"
        self.assertEqual([], eval_suite_violations(self.changed, self.suite_dir))

    def test_non_draft_profile_with_a_bound_suite_is_accepted(self) -> None:
        self.profile["status"] = "enabled"
        self.write_suite(bound_suite(self.profile))
        self.assertEqual([], eval_suite_violations(self.changed, self.suite_dir))

    def test_unsafe_or_missing_suite_id_is_refused(self) -> None:
        self.profile["status"] = "enabled"
        for suite_id in ("../../secrets", "agent-coordination.v1/../x", "", None, "coordination.v1"):
            with self.subTest(suite_id=suite_id):
                self.profile["eval_suite"] = suite_id
                self.assertRegex(eval_suite_violations(self.changed, self.suite_dir)[0], "not a safe suite id")

    def test_incomplete_or_unbound_suite_is_refused(self) -> None:
        self.profile["status"] = "enabled"
        mutations = (
            (lambda suite: suite.pop("isolation"), "must hold exactly"),
            (lambda suite: suite.update(notes="libre"), "must hold exactly"),
            (lambda suite: suite.update(schema_version="agent-evaluation-suite.v0"), "unsupported"),
            (lambda suite: suite.update(profile_id="task_planner"), "not bound"),
            (lambda suite: suite.update(profile_version="9.9.9"), "not bound"),
            (lambda suite: suite.update(eval_suite="agent-other.v1"), "not bound"),
            (lambda suite: suite.update(quality=[]), "no valid quality case"),
            (lambda suite: suite.update(least_privilege=[{"label": "sans id"}]), "no valid least_privilege case"),
            (lambda suite: suite.update(isolation="aucun"), "no valid isolation case"),
            (lambda suite: suite.update(isolation=[{"id": "quality-01"}]), "repeats a case id"),
        )
        for mutate, pattern in mutations:
            with self.subTest(pattern=pattern):
                suite = bound_suite(self.profile)
                mutate(suite)
                self.write_suite(suite)
                violations = eval_suite_violations(self.changed, self.suite_dir)
                self.assertEqual(1, len(violations))
                self.assertRegex(violations[0], pattern)
        self.write_suite("{not json")
        self.assertRegex(eval_suite_violations(self.changed, self.suite_dir)[0], "not valid JSON")
        self.write_suite("[]")
        self.assertRegex(eval_suite_violations(self.changed, self.suite_dir)[0], "must hold exactly")


if __name__ == "__main__":
    unittest.main()
