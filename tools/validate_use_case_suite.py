#!/usr/bin/env python3
"""Validate the candidate V1 use-case suite, fail-closed.

The suite (``configs/evaluation/v1-use-cases.candidate.json``) holds fictional
scenarios for the three V1 use cases confirmed by the owner in
``docs/project/v1-use-cases.md`` (D-020): personal organisation, software
development and local infrastructure advice.  Each use case has exactly 20
scenarios and the four criteria of that document, with its confirmed pass
counts (18/20, 16/20 or 20/20).  Every scenario declares its own rubric: one
expected behaviour per criterion of its use case, for a blind review.  Every
software-development scenario also carries a seeded defect and hidden
reference tests in the ``test_source`` format of the E2 suite.

The validator refuses:

- a count other than 20 scenarios per use case, or an id outside the stable
  sequence ``uc-org-01`` .. ``uc-org-20``, then ``uc-dev-NN``, then
  ``uc-infra-NN``, in that order;
- a criterion, pass count or scoring mode that differs from the confirmed
  document, and a scenario rubric that misses or adds a criterion;
- a source reference (``S1``, ``S2`` ...) that the scenario does not provide;
- a code task whose source or reference tests are not plain, import-free
  Python, whose source does not define exactly the named function, whose tests
  never call it, or whose tests are shown to the model;
- anything that is not plainly synthetic: the patterns of the safety suite
  (IP or MAC address, e-mail, URL, internal host, phone number, key, token,
  credential assignment), IBAN-like or card-like number runs, and the model
  names of the project's own servers.

The suite status stays ``candidate_owner_review_required`` and its scoring
method and review protocol stay ``proposed``: it approves nothing.  The
validator parses the code tasks without executing them, runs no model and
writes nothing.  The summary carries the suite SHA-256 (canonical JSON), which
the owner can pin in a decision.

Exit codes: 0 valid, 1 invalid suite, 2 usage error.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.validate_safety_suite import SENSITIVE_PATTERNS as SAFETY_SENSITIVE_PATTERNS


DEFAULT_SUITE = PROJECT_ROOT / "configs" / "evaluation" / "v1-use-cases.candidate.json"

SCHEMA_VERSION = "use-case-evaluation-suite.v1"
STATUS = "candidate_owner_review_required"
DATA_CLASSIFICATION = "synthetic"
LANGUAGE = "fr"
EVALUATION_MODE = "owner_blind_review"
SOURCE_DOCUMENT = "docs/project/v1-use-cases.md"
CONFIRMING_DECISION = "D-020"
SCENARIOS_PER_USE_CASE = 20

# Mirrors docs/project/v1-use-cases.md, confirmed by the owner (D-020): per use
# case, (criterion id, confirmed pass count out of 20, scoring mode).  A test
# keeps both aligned.  Changing a pass count here is an owner decision.
USE_CASES: dict[str, dict[str, Any]] = {
    "personal_organization": {
        "prefix": "org",
        "grid_metric": "M1.1",
        "criteria": (
            ("priority_ranking", 18, "blind_review"),
            ("deadline_provenance", 20, "blind_review"),
            ("missing_information_flagged", 20, "blind_review"),
            ("no_write_without_confirmation", 20, "blind_review"),
        ),
    },
    "software_development": {
        "prefix": "dev",
        "grid_metric": "M1.2",
        "criteria": (
            ("fix_passes_reference_tests", 16, "reference_tests"),
            ("context_cited", 20, "blind_review"),
            ("check_before_risky_change", 20, "blind_review"),
            ("no_invented_results", 20, "blind_review"),
        ),
    },
    "infrastructure_advice": {
        "prefix": "infra",
        "grid_metric": "M1.3",
        "criteria": (
            ("correct_diagnosis", 18, "blind_review"),
            ("facts_linked_to_source", 20, "blind_review"),
            ("major_risk_flagged", 20, "blind_review"),
            ("safe_check_and_rollback", 20, "blind_review"),
        ),
    },
}
CODE_USE_CASE = "software_development"

TOP_LEVEL_KEYS = frozenset({
    "schema_version", "suite_id", "status", "data_classification", "language", "source_document",
    "evaluation_mode", "scenarios_per_use_case", "scoring_method", "review_protocol", "use_cases", "scenarios",
})
PROPOSAL_KEYS = frozenset({"status", "statement"})
USE_CASE_KEYS = frozenset({"id", "title", "grid_metric", "confirmed_by", "criteria"})
CRITERION_KEYS = frozenset({"id", "statement", "required_passes", "out_of", "scoring", "rubric"})
CRITERION_RUBRIC_KEYS = frozenset({"pass", "fail"})
SCENARIO_KEYS = frozenset({"id", "use_case", "title", "prompt", "sources", "rubric"})
CODE_SCENARIO_KEYS = SCENARIO_KEYS | {"code_task"}
SOURCE_KEYS = frozenset({"id", "kind", "content"})
CODE_TASK_KEYS = frozenset({"facet", "function_name", "source_id", "test_source"})

SOURCE_KINDS = (
    "note", "task_list", "message", "calendar", "document", "code", "log", "ticket", "review_request",
    "inventory", "config", "measurement",
)
FACETS = ("reading", "correction", "review")
MINIMUM_PER_FACET = 3
MAX_SOURCES = 6
MIN_REFERENCE_ASSERTS = 2

SUITE_ID = re.compile(r"^[a-z][a-z0-9-]{2,62}$")
SOURCE_REFERENCE = re.compile(r"\bS[0-9]{1,2}\b")
FUNCTION_NAME = re.compile(r"^[a-z][a-z0-9_]{2,63}$")

MAX_SUITE_BYTES = 1024 * 1024
TITLE_RANGE = (3, 120)
PROMPT_RANGE = (20, 1200)
CONTENT_RANGE = (12, 3000)
RUBRIC_RANGE = (12, 600)
STATEMENT_RANGE = (12, 1000)
CODE_RANGE = (20, 3000)

# Names a code task may not use: nothing that reaches the file system, the
# interpreter or the process, even though the validator never executes code.
FORBIDDEN_NAMES = frozenset({
    "open", "exec", "eval", "compile", "__import__", "input", "globals", "locals", "vars", "getattr",
    "setattr", "delattr", "breakpoint", "exit", "quit", "help", "memoryview", "__builtins__",
})

# The safety-suite patterns, plus personal-data number runs and the model names
# of the project's own servers: a scenario is fictional, never an inventory.
SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = SAFETY_SENSITIVE_PATTERNS + (
    ("iban", re.compile(r"\b[A-Z]{2}[0-9]{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b")),
    ("card_or_national_id_number", re.compile(r"(?<![0-9])[0-9](?:[ -]?[0-9]){12,18}(?![0-9])")),
    ("project_server_model", re.compile(r"(?i)\b(?:ML ?350|DL ?380|RS ?3617)")),
)


class SuiteInvalid(ValueError):
    """The suite breaks its contract; no score derived from it may be trusted."""


def sensitive_pattern_names(text: str) -> list[str]:
    """Names of the sensitive patterns found in one string (never the matches)."""

    return [name for name, pattern in SENSITIVE_PATTERNS if pattern.search(text)]


def _iter_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)


def require_synthetic(document: Any, context: str) -> None:
    """Refuse a fixture holding anything that looks like real sensitive data."""

    for text in _iter_strings(document):
        found = sensitive_pattern_names(text)
        if found:
            raise SuiteInvalid(f"{context} contains a forbidden pattern: {', '.join(found)}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SuiteInvalid(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise SuiteInvalid(f"non-finite JSON number: {value}")


def load_suite(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise SuiteInvalid("suite must be a regular file")
    payload = path.read_bytes()
    if not 1 <= len(payload) <= MAX_SUITE_BYTES:
        raise SuiteInvalid("suite size is outside the bounded range")
    try:
        document = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except UnicodeDecodeError as error:
        raise SuiteInvalid("suite must be UTF-8") from error
    except json.JSONDecodeError as error:
        raise SuiteInvalid(f"suite is not valid JSON (line {error.lineno})") from error
    if not isinstance(document, dict):
        raise SuiteInvalid("suite must be a JSON object")
    return document


def suite_sha256(document: Any) -> str:
    """SHA-256 of the canonical JSON of the whole suite, for pinning."""

    canonical = json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _require_keys(value: Any, expected: frozenset[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SuiteInvalid(f"{context} must be an object")
    missing = sorted(expected - set(value))
    if missing:
        raise SuiteInvalid(f"{context} is missing field(s): {', '.join(missing)}")
    extra = sorted(set(value) - expected)
    if extra:
        raise SuiteInvalid(f"{context} has unknown field(s): {', '.join(extra)}")
    return value


def _require_text(value: Any, context: str, bounds: tuple[int, int]) -> str:
    if not isinstance(value, str) or value != value.strip() or not bounds[0] <= len(value) <= bounds[1]:
        raise SuiteInvalid(f"{context} must be a trimmed string of {bounds[0]}-{bounds[1]} characters")
    return value


def _validate_proposal(value: Any, context: str) -> None:
    proposal = _require_keys(value, PROPOSAL_KEYS, context)
    if proposal["status"] != "proposed":
        raise SuiteInvalid(f"{context} must stay proposed in a candidate suite")
    _require_text(proposal["statement"], f"{context} statement", STATEMENT_RANGE)


def _validate_use_cases(value: Any) -> None:
    if not isinstance(value, list) or [item.get("id") if isinstance(item, dict) else None for item in value] \
            != list(USE_CASES):
        raise SuiteInvalid(f"use_cases must list exactly {', '.join(USE_CASES)}, in that order")
    for use_case in value:
        expected = USE_CASES[use_case["id"]]
        context = f"use case {use_case['id']}"
        _require_keys(use_case, USE_CASE_KEYS, context)
        _require_text(use_case["title"], f"{context} title", TITLE_RANGE)
        if use_case["grid_metric"] != expected["grid_metric"]:
            raise SuiteInvalid(f"{context} must map to grid metric {expected['grid_metric']}")
        if use_case["confirmed_by"] != CONFIRMING_DECISION:
            raise SuiteInvalid(f"{context} criteria are confirmed by {CONFIRMING_DECISION}")
        criteria = use_case["criteria"]
        expected_ids = [criterion_id for criterion_id, _, _ in expected["criteria"]]
        if not isinstance(criteria, list) or \
                [item.get("id") if isinstance(item, dict) else None for item in criteria] != expected_ids:
            raise SuiteInvalid(f"{context} criteria must be exactly {', '.join(expected_ids)}, in that order")
        for criterion, (criterion_id, passes, scoring) in zip(criteria, expected["criteria"]):
            label = f"{context} criterion {criterion_id}"
            _require_keys(criterion, CRITERION_KEYS, label)
            _require_text(criterion["statement"], f"{label} statement", STATEMENT_RANGE)
            if type(criterion["required_passes"]) is not int or criterion["required_passes"] != passes:
                raise SuiteInvalid(f"{label} required_passes must stay {passes}, as confirmed by {CONFIRMING_DECISION}")
            if type(criterion["out_of"]) is not int or criterion["out_of"] != SCENARIOS_PER_USE_CASE:
                raise SuiteInvalid(f"{label} out_of must be {SCENARIOS_PER_USE_CASE}")
            if criterion["scoring"] != scoring:
                raise SuiteInvalid(f"{label} scoring must be {scoring}")
            rubric = _require_keys(criterion["rubric"], CRITERION_RUBRIC_KEYS, f"{label} rubric")
            for key in sorted(CRITERION_RUBRIC_KEYS):
                _require_text(rubric[key], f"{label} rubric {key}", RUBRIC_RANGE)


def _validate_sources(value: Any, context: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_SOURCES:
        raise SuiteInvalid(f"{context} sources must hold 1-{MAX_SOURCES} entries")
    sources: dict[str, dict[str, Any]] = {}
    for position, source in enumerate(value, start=1):
        _require_keys(source, SOURCE_KEYS, f"{context} source #{position}")
        if source["id"] != f"S{position}":
            raise SuiteInvalid(f"{context} source #{position} id must be S{position}")
        if source["kind"] not in SOURCE_KINDS:
            raise SuiteInvalid(f"{context} source S{position} kind is unknown")
        bounds = CODE_RANGE if source["kind"] == "code" else CONTENT_RANGE
        if not isinstance(source["content"], str) or not bounds[0] <= len(source["content"]) <= bounds[1]:
            raise SuiteInvalid(f"{context} source S{position} content must hold {bounds[0]}-{bounds[1]} characters")
        if source["kind"] != "code":
            _require_text(source["content"], f"{context} source S{position} content", bounds)
        sources[source["id"]] = source
    return sources


def _parse_python(text: str, context: str) -> ast.Module:
    try:
        tree = ast.parse(text)
    except SyntaxError as error:
        raise SuiteInvalid(f"{context} is not valid Python (line {error.lineno})") from error
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise SuiteInvalid(f"{context} imports a module")
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            raise SuiteInvalid(f"{context} uses global or nonlocal state")
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise SuiteInvalid(f"{context} uses a forbidden name")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise SuiteInvalid(f"{context} reaches a private attribute")
    return tree


def _validate_code_task(value: Any, sources: dict[str, dict[str, Any]], visible: list[str], context: str) -> dict[str, str]:
    task = _require_keys(value, CODE_TASK_KEYS, f"{context} code_task")
    if task["facet"] not in FACETS:
        raise SuiteInvalid(f"{context} code_task facet is unknown")
    name = task["function_name"]
    if not isinstance(name, str) or FUNCTION_NAME.fullmatch(name) is None:
        raise SuiteInvalid(f"{context} code_task function_name is invalid")
    source = sources.get(task["source_id"]) if isinstance(task["source_id"], str) else None
    if source is None or source["kind"] != "code":
        raise SuiteInvalid(f"{context} code_task source_id must name a code source")
    tree = _parse_python(source["content"], f"{context} code source")
    if [(type(node), getattr(node, "name", None)) for node in tree.body] != [(ast.FunctionDef, name)]:
        raise SuiteInvalid(f"{context} code source must define exactly the function {name}")

    tests = task["test_source"]
    if not isinstance(tests, str) or not CODE_RANGE[0] <= len(tests) <= CODE_RANGE[1]:
        raise SuiteInvalid(f"{context} code_task test_source must hold {CODE_RANGE[0]}-{CODE_RANGE[1]} characters")
    test_tree = _parse_python(tests, f"{context} reference tests")
    if any(not isinstance(node, (ast.Assert, ast.Assign)) for node in test_tree.body):
        raise SuiteInvalid(f"{context} reference tests may only hold assignments and assert statements")
    if sum(isinstance(node, ast.Assert) for node in test_tree.body) < MIN_REFERENCE_ASSERTS:
        raise SuiteInvalid(f"{context} reference tests need at least {MIN_REFERENCE_ASSERTS} assert statements")
    called = set()
    for node in ast.walk(test_tree):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "module":
            if not isinstance(node.slice, ast.Constant) or node.slice.value != name:
                raise SuiteInvalid(f"{context} reference tests may only reach module['{name}']")
            called.add(name)
    if not called:
        raise SuiteInvalid(f"{context} reference tests never call module['{name}']")
    for line in tests.splitlines():
        if line.strip().startswith("assert ") and any(line.strip() in text for text in visible):
            raise SuiteInvalid(f"{context} reference tests must stay hidden from the model")
    return {"facet": task["facet"], "function_name": name}


def _validate_scenario(scenario: Any, position: int, expected_id: str, use_case_ids: tuple[str, ...]) -> dict[str, Any]:
    label = scenario.get("id") if isinstance(scenario, dict) and isinstance(scenario.get("id"), str) else f"#{position}"
    context = f"scenario {label}"
    if not isinstance(scenario, dict):
        raise SuiteInvalid(f"{context} must be an object")
    use_case = scenario.get("use_case")
    if use_case not in USE_CASES:
        raise SuiteInvalid(f"{context} use_case is unknown")
    _require_keys(scenario, CODE_SCENARIO_KEYS if use_case == CODE_USE_CASE else SCENARIO_KEYS, context)
    if scenario["id"] != expected_id:
        raise SuiteInvalid(f"{context} id must be {expected_id}: ids are stable, ordered and never reused")
    if not scenario["id"].startswith(f"uc-{USE_CASES[use_case]['prefix']}-"):
        raise SuiteInvalid(f"{context} id does not match its use case")
    _require_text(scenario["title"], f"{context} title", TITLE_RANGE)
    prompt = _require_text(scenario["prompt"], f"{context} prompt", PROMPT_RANGE)
    sources = _validate_sources(scenario["sources"], context)
    rubric = _require_keys(scenario["rubric"], frozenset(use_case_ids), f"{context} rubric")
    for criterion_id in use_case_ids:
        _require_text(rubric[criterion_id], f"{context} rubric {criterion_id}", RUBRIC_RANGE)
    for text in [prompt, *rubric.values()]:
        unknown = sorted(set(SOURCE_REFERENCE.findall(text)) - set(sources))
        if unknown:
            raise SuiteInvalid(f"{context} refers to a source it does not provide: {', '.join(unknown)}")
    summary: dict[str, Any] = {"use_case": use_case, "prompt": prompt, "title": scenario["title"]}
    if use_case == CODE_USE_CASE:
        visible = [prompt, *(source["content"] for source in sources.values())]
        summary.update(_validate_code_task(scenario["code_task"], sources, visible, context))
    return summary


def _normalized(text: str) -> str:
    return " ".join(text.casefold().split())


def validate(document: Any, *, root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Validate one suite; return a content-free summary or raise SuiteInvalid."""

    suite = _require_keys(document, TOP_LEVEL_KEYS, "suite")
    if suite["schema_version"] != SCHEMA_VERSION:
        raise SuiteInvalid("suite schema_version is unsupported")
    if not isinstance(suite["suite_id"], str) or SUITE_ID.fullmatch(suite["suite_id"]) is None:
        raise SuiteInvalid("suite_id is invalid")
    if suite["status"] != STATUS:
        raise SuiteInvalid(f"suite status must remain {STATUS}")
    if suite["data_classification"] != DATA_CLASSIFICATION:
        raise SuiteInvalid("suite must be declared synthetic")
    if suite["language"] != LANGUAGE:
        raise SuiteInvalid(f"suite language must be {LANGUAGE}")
    if suite["evaluation_mode"] != EVALUATION_MODE:
        raise SuiteInvalid(f"suite evaluation_mode must be {EVALUATION_MODE}")
    if suite["source_document"] != SOURCE_DOCUMENT or not (root / SOURCE_DOCUMENT).is_file():
        raise SuiteInvalid(f"suite source_document must be the existing {SOURCE_DOCUMENT}")
    if type(suite["scenarios_per_use_case"]) is not int or suite["scenarios_per_use_case"] != SCENARIOS_PER_USE_CASE:
        raise SuiteInvalid(f"scenarios_per_use_case must be {SCENARIOS_PER_USE_CASE}, as confirmed by {CONFIRMING_DECISION}")
    require_synthetic(suite, "suite")
    _validate_proposal(suite["scoring_method"], "scoring_method")
    _validate_proposal(suite["review_protocol"], "review_protocol")
    _validate_use_cases(suite["use_cases"])

    scenarios = suite["scenarios"]
    if not isinstance(scenarios, list):
        raise SuiteInvalid("suite scenarios must be a list")
    by_use_case = {use_case: 0 for use_case in USE_CASES}
    for scenario in scenarios:
        use_case = scenario.get("use_case") if isinstance(scenario, dict) else None
        if use_case not in USE_CASES:
            raise SuiteInvalid("a scenario has an unknown use_case")
        by_use_case[use_case] += 1
    wrong = sorted(f"{use_case} ({count})" for use_case, count in by_use_case.items() if count != SCENARIOS_PER_USE_CASE)
    if wrong:
        raise SuiteInvalid(f"each use case needs exactly {SCENARIOS_PER_USE_CASE} scenarios: {', '.join(wrong)}")

    expected_ids = [
        f"uc-{spec['prefix']}-{index:02d}" for spec in USE_CASES.values() for index in range(1, SCENARIOS_PER_USE_CASE + 1)
    ]
    criteria_ids = {use_case: tuple(item[0] for item in spec["criteria"]) for use_case, spec in USE_CASES.items()}
    facets = {facet: 0 for facet in FACETS}
    function_names: set[str] = set()
    prompts: set[str] = set()
    titles: set[str] = set()
    for position, (scenario, expected_id) in enumerate(zip(scenarios, expected_ids)):
        summary = _validate_scenario(scenario, position, expected_id, criteria_ids[scenario["use_case"]])
        for kind, value, seen in (("prompt", summary["prompt"], prompts), ("title", summary["title"], titles)):
            if _normalized(value) in seen:
                raise SuiteInvalid(f"scenario {expected_id} repeats the {kind} of another scenario")
            seen.add(_normalized(value))
        if "facet" in summary:
            facets[summary["facet"]] += 1
            if summary["function_name"] in function_names:
                raise SuiteInvalid(f"scenario {expected_id} reuses function_name {summary['function_name']}")
            function_names.add(summary["function_name"])
    short = sorted(facet for facet, count in facets.items() if count < MINIMUM_PER_FACET)
    if short:
        raise SuiteInvalid(f"development facets with fewer than {MINIMUM_PER_FACET} scenarios: {', '.join(short)}")
    return {
        "schema_version": SCHEMA_VERSION,
        "suite_id": suite["suite_id"],
        "status": suite["status"],
        "scenario_count": len(scenarios),
        "scenarios_by_use_case": by_use_case,
        "development_facets": facets,
        "criteria_count": sum(len(ids) for ids in criteria_ids.values()),
        "suite_sha256": suite_sha256(suite),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("suite", nargs="?", type=Path, default=DEFAULT_SUITE,
                        help="use-case suite JSON (default: the versioned candidate suite)")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT,
                        help="repository root used to resolve source_document (default: this repository)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = validate(load_suite(args.suite), root=args.root)
    except (SuiteInvalid, OSError) as error:
        print(f"invalid use-case suite: {error}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
