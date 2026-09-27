import contextlib
import copy
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tools import validate_use_case_suite as use_cases
from tools.validate_use_case_suite import SuiteInvalid


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = PROJECT_ROOT / "configs" / "evaluation" / "v1-use-cases.candidate.json"
GRID_PATH = PROJECT_ROOT / "configs" / "evaluation" / "v1-grid.candidate.json"
USE_CASE_DOCUMENT = PROJECT_ROOT / "docs" / "project" / "v1-use-cases.md"
E2_PATH = PROJECT_ROOT / "configs" / "evaluation" / "core-python-e2.candidate.json"
PRACTICE_SUITE_PATH = PROJECT_ROOT / "configs" / "arena" / "practice-suite.v1.json"

# One minimal patch per seeded defect, as (exact text to replace, replacement).
# They prove that each hidden reference test is satisfiable by a small fix; they
# are kept here, never in the suite shown to a model.
MINIMAL_FIXES = {
    "uc-dev-01": ("    total = 0\n    for sample in samples:\n        total += sample['ms']\n    return total / len(samples)\n",
                  "    durations = [sample['ms'] for sample in samples if sample['ok']]\n"
                  "    return sum(durations) / len(durations) if durations else None\n"),
    "uc-dev-02": ("start = page * size", "start = (page - 1) * size"),
    "uc-dev-03": ("        if tag not in result and tag.strip():\n            result.append(tag.strip().lower())\n",
                  "        value = tag.strip().lower()\n        if value and value not in result:\n            result.append(value)\n"),
    "uc-dev-04": ("    return [share] * parts\n",
                  "    remainder = total_cents - share * parts\n    return [share + 1] * remainder + [share] * (parts - remainder)\n"),
    "uc-dev-05": ("def collect_errors(message, errors=[]):\n",
                  "def collect_errors(message, errors=None):\n    errors = [] if errors is None else errors\n"),
    "uc-dev-06": ("    return (int(end_hours) * 60 + int(end_minutes)) - (int(start_hours) * 60 + int(start_minutes))\n",
                  "    return ((int(end_hours) * 60 + int(end_minutes)) - (int(start_hours) * 60 + int(start_minutes))) % 1440\n"),
    "uc-dev-07": ("        remaining[product] = remaining.get(product, 0) - quantity\n",
                  "        if remaining.get(product, 0) < quantity:\n            refused.append((product, quantity))\n"
                  "            continue\n        remaining[product] -= quantity\n"),
    "uc-dev-08": ("    return sum(1 for message_id in message_ids if message_id >= last_read_id)\n",
                  "    if last_read_id is None:\n        return len(message_ids)\n"
                  "    return sum(1 for message_id in message_ids if message_id > last_read_id)\n"),
    "uc-dev-09": ("{mapping[key]: value for key, value in record.items() if key in mapping}",
                  "{mapping.get(key, key): value for key, value in record.items()}"),
    "uc-dev-10": ("        latest[reading['device']] = reading\n",
                  "        current = latest.get(reading['device'])\n        if current is None or reading['at'] > current['at']:\n"
                  "            latest[reading['device']] = reading\n"),
    "uc-dev-11": ("    if ratio >= 0.8:\n        return 'warning'\n    if ratio >= 1:\n        return 'full'\n",
                  "    if ratio >= 1:\n        return 'full'\n    if ratio >= 0.8:\n        return 'warning'\n"),
    "uc-dev-12": ("text.split('x')", "text.lower().replace('×', 'x').split('x')"),
    "uc-dev-13": ("if remainder else minute", "if remainder else (minute + interval) % 60"),
    "uc-dev-14": ("    visible = identifier[-4:]\n",
                  "    if len(identifier) <= 4:\n        return '*' * len(identifier)\n    visible = identifier[-4:]\n"),
    "uc-dev-15": ("sorted(names)", "sorted(names, key=lambda name: int(name.split()[-1]))"),
    "uc-dev-16": ("text[:limit] + '…'", "text[:limit - 1] + '…'"),
    "uc-dev-17": ("total += unit_cents", "total += quantity * unit_cents"),
    "uc-dev-18": ("if task['due'] < today]", "if task['due'] < today and not task['done']]"),
    "uc-dev-19": ("return ordered[keep:]", "return ordered[:max(len(ordered) - keep, 0)]"),
    "uc-dev-20": ("    cleaned = name.replace('/', '_')\n    return cleaned.strip() or 'sans-nom'\n",
                  "    cleaned = name.replace('/', '_').replace('\\\\', '_')\n    return cleaned.strip().lstrip('.') or 'sans-nom'\n"),
}


def scenario(document: dict, scenario_id: str) -> dict:
    return next(item for item in document["scenarios"] if item["id"] == scenario_id)


def use_case(document: dict, use_case_id: str) -> dict:
    return next(item for item in document["use_cases"] if item["id"] == use_case_id)


def code_of(item: dict) -> str:
    return next(source["content"] for source in item["sources"] if source["id"] == item["code_task"]["source_id"])


REFERENCE_RUNNER = (
    "import json, sys\n"
    "payload = json.loads(sys.stdin.read())\n"
    "module = {}\n"
    "exec(compile(payload['source'], 'candidate.py', 'exec'), module)\n"
    "exec(compile(payload['tests'], 'tests.py', 'exec'), {'module': module})\n"
)
REFERENCE_TIMEOUT_SECONDS = 10


def run_reference_tests(source: str, tests: str) -> bool:
    """Run one committed, validator-checked code task; True when its hidden tests pass.

    This is the repository's static self-check of its own fixtures, never the
    evaluation of a model (that one belongs to the code-evaluation sandbox).
    It still stays out of the test process: a separate isolated interpreter
    (-I -S), an empty environment, a temporary working directory and a
    timeout, so a looping or hostile fixture edit cannot hang or touch the run.
    """

    environment = {"SYSTEMROOT": os.environ["SYSTEMROOT"]} if os.name == "nt" and "SYSTEMROOT" in os.environ else {}
    payload = json.dumps({"source": source, "tests": tests}, ensure_ascii=True).encode("ascii")
    with tempfile.TemporaryDirectory() as directory:
        completed = subprocess.run(
            [sys.executable, "-I", "-S", "-c", REFERENCE_RUNNER], input=payload, capture_output=True,
            timeout=REFERENCE_TIMEOUT_SECONDS, cwd=directory, env=environment, check=False,
        )
    if completed.returncode not in (0, 1):
        raise RuntimeError(f"reference test runner ended abnormally (exit {completed.returncode})")
    return completed.returncode == 0


class UseCaseSuiteValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = use_cases.load_suite(SUITE_PATH)

    def refused(self, document: dict, pattern: str) -> None:
        with self.assertRaisesRegex(SuiteInvalid, pattern):
            use_cases.validate(document)

    def test_candidate_suite_has_twenty_scenarios_per_use_case_and_a_rubric_per_criterion(self) -> None:
        summary = use_cases.validate(self.document)
        self.assertEqual("candidate_owner_review_required", summary["status"])
        self.assertEqual({key: 20 for key in use_cases.USE_CASES}, summary["scenarios_by_use_case"])
        self.assertEqual(60, summary["scenario_count"])
        self.assertEqual(12, summary["criteria_count"])
        self.assertRegex(summary["suite_sha256"], r"^[0-9a-f]{64}$")
        for item in self.document["use_cases"]:
            for criterion in item["criteria"]:
                with self.subTest(criterion=criterion["id"]):
                    self.assertEqual({"pass", "fail"}, set(criterion["rubric"]))
        for item in self.document["scenarios"]:
            expected = {criterion["id"] for criterion in use_case(self.document, item["use_case"])["criteria"]}
            with self.subTest(scenario=item["id"]):
                self.assertEqual(expected, set(item["rubric"]))

    def test_scenario_count_must_be_exactly_twenty(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["scenarios"].remove(scenario(changed, "uc-org-20"))
        self.refused(changed, "exactly 20 scenarios: personal_organization \\(19\\)")
        changed = copy.deepcopy(self.document)
        extra = copy.deepcopy(scenario(changed, "uc-infra-20"))
        extra.update(id="uc-infra-21", title="Scénario surnuméraire", prompt="Une question de plus sur le lab (S1).")
        changed["scenarios"].append(extra)
        self.refused(changed, "infrastructure_advice \\(21\\)")

    def test_ids_are_stable_ordered_and_unique(self) -> None:
        changed = copy.deepcopy(self.document)
        scenarios = changed["scenarios"]
        scenarios[0], scenarios[1] = scenarios[1], scenarios[0]
        self.refused(changed, "id must be uc-org-01")
        changed = copy.deepcopy(self.document)
        scenario(changed, "uc-dev-03")["id"] = "uc-dev-21"
        self.refused(changed, "id must be uc-dev-03")
        changed = copy.deepcopy(self.document)
        scenario(changed, "uc-dev-04")["id"] = "uc-dev-03"
        self.refused(changed, "id must be uc-dev-04")
        changed = copy.deepcopy(self.document)
        scenarios = changed["scenarios"]
        scenarios[19], scenarios[40] = scenarios[40], scenarios[19]
        self.refused(changed, "id must be uc-org-20")

    def test_confirmed_criteria_and_pass_counts_are_pinned(self) -> None:
        mutations = (
            (lambda doc: use_case(doc, "personal_organization")["criteria"][0].update(required_passes=17), "must stay 18"),
            (lambda doc: use_case(doc, "software_development")["criteria"][0].update(required_passes=15), "must stay 16"),
            (lambda doc: use_case(doc, "infrastructure_advice")["criteria"][3].update(required_passes=True), "must stay 20"),
            (lambda doc: use_case(doc, "software_development")["criteria"][1].update(out_of=19), "out_of must be 20"),
            (lambda doc: use_case(doc, "software_development")["criteria"][0].update(scoring="blind_review"),
             "scoring must be reference_tests"),
            (lambda doc: use_case(doc, "infrastructure_advice")["criteria"][0].update(id="diagnosis"), "criteria must be exactly"),
            (lambda doc: use_case(doc, "infrastructure_advice")["criteria"].pop(), "criteria must be exactly"),
            (lambda doc: use_case(doc, "personal_organization").update(confirmed_by="D-099"), "confirmed by D-020"),
            (lambda doc: use_case(doc, "personal_organization").update(grid_metric="M1.3"), "grid metric M1.1"),
            (lambda doc: doc["use_cases"].reverse(), "use_cases must list exactly"),
            (lambda doc: doc.update(scenarios_per_use_case=19), "scenarios_per_use_case must be 20"),
        )
        for mutate, pattern in mutations:
            with self.subTest(pattern=pattern):
                changed = copy.deepcopy(self.document)
                mutate(changed)
                self.refused(changed, pattern)

    def test_every_rubric_is_complete(self) -> None:
        changed = copy.deepcopy(self.document)
        del scenario(changed, "uc-org-05")["rubric"]["deadline_provenance"]
        self.refused(changed, "rubric is missing field\\(s\\): deadline_provenance")
        changed = copy.deepcopy(self.document)
        scenario(changed, "uc-infra-02")["rubric"]["priority_ranking"] = "Critère d'un autre cas d'usage."
        self.refused(changed, "rubric has unknown field\\(s\\): priority_ranking")
        changed = copy.deepcopy(self.document)
        scenario(changed, "uc-dev-07")["rubric"]["context_cited"] = " "
        self.refused(changed, "trimmed string")
        changed = copy.deepcopy(self.document)
        del use_case(changed, "software_development")["criteria"][2]["rubric"]["fail"]
        self.refused(changed, "rubric is missing field\\(s\\): fail")
        changed = copy.deepcopy(self.document)
        del scenario(changed, "uc-org-05")["rubric"]
        self.refused(changed, "missing field\\(s\\): rubric")

    def test_candidate_state_stays_unapproved(self) -> None:
        mutations = (
            (lambda doc: doc.update(status="approved"), "must remain"),
            (lambda doc: doc["scoring_method"].update(status="approved"), "scoring_method must stay proposed"),
            (lambda doc: doc["review_protocol"].update(status="confirmed"), "review_protocol must stay proposed"),
            (lambda doc: doc.update(data_classification="real"), "declared synthetic"),
            (lambda doc: doc.update(language="en"), "language must be fr"),
            (lambda doc: doc.update(evaluation_mode="automatic"), "evaluation_mode"),
            (lambda doc: doc.update(source_document="docs/project/decisions.md"), "source_document"),
            (lambda doc: doc.update(schema_version="use-case-evaluation-suite.v2"), "unsupported"),
            (lambda doc: doc.update(extra=1), "unknown field\\(s\\): extra"),
        )
        for mutate, pattern in mutations:
            with self.subTest(pattern=pattern):
                changed = copy.deepcopy(self.document)
                mutate(changed)
                self.refused(changed, pattern)

    def test_sources_and_references_must_resolve(self) -> None:
        changed = copy.deepcopy(self.document)
        scenario(changed, "uc-infra-01")["rubric"]["facts_linked_to_source"] = "Relie l'échec à S1 et la rétention à S7."
        self.refused(changed, "does not provide: S7")
        changed = copy.deepcopy(self.document)
        scenario(changed, "uc-org-01")["prompt"] += " Voir aussi S3."
        self.refused(changed, "does not provide: S3")
        changed = copy.deepcopy(self.document)
        scenario(changed, "uc-org-01")["sources"][1]["id"] = "S5"
        self.refused(changed, "id must be S2")
        changed = copy.deepcopy(self.document)
        scenario(changed, "uc-org-01")["sources"][0]["kind"] = "database_dump"
        self.refused(changed, "kind is unknown")
        changed = copy.deepcopy(self.document)
        scenario(changed, "uc-org-14")["sources"] = []
        self.refused(changed, "sources must hold 1-6 entries")

    def test_code_task_contract(self) -> None:
        def with_code(scenario_id: str, text: str):
            return lambda doc: scenario(doc, scenario_id)["sources"][0].update(content=text)

        def with_tests(scenario_id: str, text: str):
            return lambda doc: scenario(doc, scenario_id)["code_task"].update(test_source=text)

        mutations = (
            (lambda doc: scenario(doc, "uc-org-01").update(code_task=scenario(doc, "uc-dev-01")["code_task"]),
             "unknown field\\(s\\): code_task"),
            (lambda doc: scenario(doc, "uc-dev-01").pop("code_task"), "missing field\\(s\\): code_task"),
            (with_code("uc-dev-02", "import os\n\ndef paginate(items, page, size):\n    return items\n"), "imports a module"),
            (with_code("uc-dev-02", "def paginate(items, page, size):\n    return open('x').read()\n"), "forbidden name"),
            (with_code("uc-dev-02", "def paginate(items, page, size):\n    return items.__class__\n"), "private attribute"),
            (with_code("uc-dev-02", "def paginate(items, page, size:\n    return items\n"), "not valid Python"),
            (with_code("uc-dev-02", "def other(items, page, size):\n    return items\n"), "exactly the function paginate"),
            (with_code("uc-dev-02", "def paginate(items, page, size):\n    return items\n\nVALUE = 1\n"),
             "exactly the function paginate"),
            (with_tests("uc-dev-02", "assert 1 == 1\nassert 2 == 2\n"), "never call module\\['paginate'\\]"),
            (with_tests("uc-dev-02", "assert module['paginate']([1], 1, 1) == [1]\n"), "at least 2 assert"),
            (with_tests("uc-dev-02", "for value in (1, 2):\n    assert module['paginate']([value], 1, 1) == [value]\n"),
             "only hold assignments and assert"),
            (with_tests("uc-dev-02", "assert module['paginate']([1], 1, 1) == [1]\nassert module['other'] is None\n"),
             "may only reach module\\['paginate'\\]"),
            (lambda doc: scenario(doc, "uc-dev-02")["code_task"].update(source_id="S2"), "must name a code source"),
            (lambda doc: scenario(doc, "uc-dev-02")["code_task"].update(facet="refactoring"), "facet is unknown"),
            (lambda doc: scenario(doc, "uc-dev-02")["code_task"].update(function_name="Paginate!"),
             "function_name is invalid"),
            (lambda doc: scenario(doc, "uc-dev-02").update(
                prompt=scenario(doc, "uc-dev-02")["prompt"] + " "
                + scenario(doc, "uc-dev-02")["code_task"]["test_source"].splitlines()[1]),
             "must stay hidden"),
        )
        for mutate, pattern in mutations:
            with self.subTest(pattern=pattern):
                changed = copy.deepcopy(self.document)
                mutate(changed)
                self.refused(changed, pattern)

    def test_development_facets_and_function_names(self) -> None:
        changed = copy.deepcopy(self.document)
        for item in changed["scenarios"]:
            if "code_task" in item:
                item["code_task"]["facet"] = "reading" if item["code_task"]["facet"] == "review" else item["code_task"]["facet"]
        self.refused(changed, "fewer than 3 scenarios: review")
        changed = copy.deepcopy(self.document)
        duplicate = scenario(changed, "uc-dev-03")
        duplicate["code_task"] = copy.deepcopy(scenario(changed, "uc-dev-02")["code_task"])
        duplicate["sources"][0]["content"] = scenario(changed, "uc-dev-02")["sources"][0]["content"]
        self.refused(changed, "reuses function_name paginate")

    def test_duplicate_prompt_or_title_is_refused(self) -> None:
        changed = copy.deepcopy(self.document)
        scenario(changed, "uc-org-02")["prompt"] = scenario(changed, "uc-org-01")["prompt"].upper()
        self.refused(changed, "uc-org-02 repeats the prompt")
        changed = copy.deepcopy(self.document)
        scenario(changed, "uc-infra-02")["title"] = scenario(changed, "uc-infra-01")["title"]
        self.refused(changed, "uc-infra-02 repeats the title")

    def test_non_synthetic_content_is_refused_without_echoing_it(self) -> None:
        samples = {
            "ipv4_address": "La passerelle répond sur " + ".".join(("192", "0", "2", "1")) + " depuis hier.",
            "email_address": "Écrire à bob@example.invalid pour valider.",
            "url": "Voir https" + "://exemple.invalid/procedure avant la mise à jour.",
            "internal_host_suffix": "Le NAS répond sous le nom nas-1.lan depuis ce matin.",
            "phone_number": "Rappeler le 06 12 34 56 78 demain.",
            "credential_assignment": "Le mot de passe = Soleil2026 est noté sur le post-it.",
            "iban": "Virement sur FR00 " + "0000 0000 0000 0000 0000 000" + " prévu.",
            "card_or_national_id_number": "Carte " + "0000 1111 2222 3333" + " enregistrée.",
            "project_server_model": "Le serveur " + "ML" + "350 affiche une alerte.",
        }
        for name, text in samples.items():
            with self.subTest(pattern=name):
                self.assertIn(name, use_cases.sensitive_pattern_names(text))
                changed = copy.deepcopy(self.document)
                scenario(changed, "uc-infra-01")["sources"][0]["content"] = text
                with self.assertRaises(SuiteInvalid) as caught:
                    use_cases.validate(changed)
                self.assertIn(name, str(caught.exception))
                self.assertNotIn(text, str(caught.exception))

    def test_ordinary_text_is_not_flagged(self) -> None:
        for text in ("VLAN 30 des invités", "port 22 externe vers HV-1", "la version 1.10.0 face à 1.9.3",
                     "échéance au 2026-04-01", "exécutée deux fois à 15 h 15", "Import de 1 001 enregistrements",
                     "facture n° 12 envoyée il y a 40 jours", "uc-infra-01", "configs/evaluation/v1-grid.candidate.json"):
            with self.subTest(text=text):
                self.assertEqual([], use_cases.sensitive_pattern_names(text))

    def test_strict_json_loading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for name, payload in {"dup.json": b'{"a": 1, "a": 2}', "nan.json": b'{"a": NaN}', "list.json": b"[]",
                                  "latin1.json": '{"a": "é"}'.encode("latin-1"), "empty.json": b""}.items():
                with self.subTest(name=name):
                    path = Path(directory) / name
                    path.write_bytes(payload)
                    with self.assertRaises(SuiteInvalid):
                        use_cases.load_suite(path)

    def test_pinned_criteria_mirror_the_owner_confirmed_document(self) -> None:
        text = USE_CASE_DOCUMENT.read_text(encoding="utf-8")
        self.assertIn("confirmé par le propriétaire", text)
        sections = re.split(r"^## [0-9]\. ", text, flags=re.MULTILINE)[1:4]
        self.assertEqual(3, len(sections))
        for section, (use_case_id, spec) in zip(sections, use_cases.USE_CASES.items()):
            evaluation = section.split("### Évaluation initiale", 1)[1]
            self.assertRegex(evaluation, r"Sur 20 ")
            counts = []
            for line in evaluation.splitlines():
                at_least = re.match(r"^- au moins ([0-9]+) ", line)
                every = re.match(r"^- ([0-9]+) sur 20 ", line)
                if at_least or every:
                    counts.append(int((at_least or every).group(1)))
            with self.subTest(use_case=use_case_id):
                self.assertEqual([passes for _, passes, _ in spec["criteria"]], counts)

    def test_grid_points_axis_one_at_the_suite(self) -> None:
        grid = json.loads(GRID_PATH.read_text(encoding="utf-8"))
        metrics = {item["id"]: item for item in grid["metrics"]}
        relative = SUITE_PATH.relative_to(PROJECT_ROOT).as_posix()
        for spec in use_cases.USE_CASES.values():
            metric = metrics[spec["grid_metric"]]
            with self.subTest(metric=spec["grid_metric"]):
                self.assertIn(relative, metric["fixture"]["paths"])
                self.assertIn("tools/validate_use_case_suite.py", metric["procedure"]["paths"])
                self.assertIn("D-020", metric["threshold"]["decisions"])

    def test_command_line(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, use_cases.main([str(SUITE_PATH)]))
        summary = json.loads(output.getvalue())
        self.assertEqual(60, summary["scenario_count"])
        self.assertEqual(use_cases.suite_sha256(self.document), summary["suite_sha256"])
        with tempfile.TemporaryDirectory() as directory:
            broken = Path(directory) / "suite.json"
            changed = copy.deepcopy(self.document)
            changed["scenarios"].pop()
            broken.write_text(json.dumps(changed), encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(1, use_cases.main([str(broken)]))
        self.assertIn("exactly 20 scenarios", error.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                use_cases.main(["--unknown"])
        self.assertEqual(2, caught.exception.code)
        hidden = "/srv/internal-share/suite.json"
        with mock.patch.object(use_cases, "load_suite", side_effect=PermissionError(13, "Permission denied", hidden)), \
                contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(1, use_cases.main([str(SUITE_PATH)]))
        self.assertIn("Permission denied", error.getvalue())
        self.assertNotIn("internal-share", error.getvalue())

    def test_refusal_never_echoes_a_malformed_scenario_id(self) -> None:
        odd = "Ceci n'est pas un identifiant de scénario"
        changed = copy.deepcopy(self.document)
        changed["scenarios"][3]["id"] = odd
        with self.assertRaisesRegex(SuiteInvalid, "scenario #3 ") as caught:
            use_cases.validate(changed)
        self.assertNotIn(odd, str(caught.exception))


class DevelopmentReferenceTestsTests(unittest.TestCase):
    """The hidden reference tests must catch each seeded defect and accept a fix."""

    def setUp(self) -> None:
        self.document = use_cases.load_suite(SUITE_PATH)
        use_cases.validate(self.document)  # static contract first: import-free, no forbidden name
        self.tasks = [item for item in self.document["scenarios"] if item["use_case"] == "software_development"]

    def test_every_development_scenario_has_a_minimal_fix(self) -> None:
        self.assertEqual({item["id"] for item in self.tasks}, set(MINIMAL_FIXES))

    def test_reference_tests_catch_the_seeded_defect(self) -> None:
        for item in self.tasks:
            with self.subTest(scenario=item["id"]):
                self.assertFalse(run_reference_tests(code_of(item), item["code_task"]["test_source"]))

    def test_reference_tests_accept_a_minimal_fix(self) -> None:
        for item in self.tasks:
            old, new = MINIMAL_FIXES[item["id"]]
            source = code_of(item)
            with self.subTest(scenario=item["id"]):
                self.assertEqual(1, source.count(old))
                self.assertTrue(run_reference_tests(source.replace(old, new), item["code_task"]["test_source"]))

    def test_reference_runner_is_isolated_and_bounded(self) -> None:
        self.assertTrue(run_reference_tests("def f():\n    return 1\n", "assert module['f']() == 1\n"))
        self.assertFalse(run_reference_tests("def f():\n    return 2\n", "assert module['f']() == 1\n"))
        self.assertTrue(run_reference_tests("import os\ndef f():\n    return sorted(os.environ)\n",
                                            "assert module['f']() in ([], ['SYSTEMROOT'])\n"))
        with mock.patch(f"{__name__}.REFERENCE_TIMEOUT_SECONDS", 1), self.assertRaises(subprocess.TimeoutExpired):
            run_reference_tests("def f():\n    while True:\n        pass\n", "module['f']()\n")

    def test_function_names_stay_apart_from_existing_benchmarks(self) -> None:
        names = {item["code_task"]["function_name"] for item in self.tasks}
        e2 = {task["function_name"] for task in json.loads(E2_PATH.read_text(encoding="utf-8"))["tasks"]}
        practice = {task["function_name"] for task in json.loads(PRACTICE_SUITE_PATH.read_text(encoding="utf-8"))["tasks"]}
        self.assertEqual(set(), names & e2)
        self.assertEqual(set(), names & practice)


if __name__ == "__main__":
    unittest.main()
