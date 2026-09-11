import json
from pathlib import Path
import random
import tempfile
import unittest

from services.arena import league
from services.arena.engines import ChatEngine, EngineUnavailable
from services.arena.runner import APPROVAL_SCHEMA, Arena, ArenaConfig
from services.arena.store import ArenaStore

TASKS = [
    {"id": "python-01-double", "function_name": "double", "prompt": "Write double(x) that returns 2 * x.",
     "test_source": "assert module['double'](2) == 4\n"},
    {"id": "python-02-upper", "function_name": "upper", "prompt": "Write upper(text) that returns text in upper case.",
     "test_source": "assert module['upper']('a') == 'A'\n"},
]
GOOD = {"python-01-double": "def double(x):\n    return 2 * x", "python-02-upper": "def upper(text):\n    return text.upper()"}


class FakeEngine:
    """Answers correctly on repair or when told to; the referee decides nothing here."""

    def __init__(self, name: str, *, first_pass: bool = True, busy: bool = False, fail: bool = False) -> None:
        self.name, self.first_pass, self._busy, self.fail = name, first_pass, busy, fail
        self.calls: list[str] = []

    def busy(self) -> bool:
        return self._busy

    def chat(self, system_prompt: str, user_prompt: str, *, temperature: float, max_tokens: int, seed: int) -> str:
        self.calls.append(user_prompt)
        if self.fail:
            raise EngineUnavailable("down")
        if "improve the instructions" in user_prompt:
            return "You are a meticulous Python programmer who checks every edge case before answering."
        if user_prompt.startswith("Task:\n"):
            return "The function returns the wrong value; multiply instead."
        task = next(t for t in TASKS if t["prompt"] in user_prompt)
        correct = self.first_pass or "failed its tests" in user_prompt
        code = GOOD[task["id"]] if correct else f"def {task['function_name']}(*a):\n    return None"
        return f"```python\n{code}\n```"


def referee(task: dict, source: str) -> dict:
    passed = source.strip() == GOOD[task["id"]]
    return {"passed": passed, "failure": "" if passed else "AssertionError: wrong value"}


class ArenaTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)
        self.store = ArenaStore(self.root / "arena.sqlite3")
        self.store.initialize()
        self.config = ArenaConfig(state_dir=self.root, inbox_dir=self.root / "inbox", packet_size=4, evolve_every=3,
                                  max_matches_per_hour=100)

    def arena(self, engines: dict) -> Arena:
        arena = Arena(self.store, engines, referee, TASKS, self.config, rng=random.Random(1))
        arena.seed()
        return arena


class LeagueRulesTests(unittest.TestCase):
    def test_elo_is_zero_sum_and_rewards_the_higher_score(self) -> None:
        a, b = league.elo_update(1000, 1000, 1.0, 0.0)
        self.assertAlmostEqual(a + b, 2000)
        self.assertGreater(a, b)
        self.assertEqual(league.elo_update(1000, 1000, 0.6, 0.6), (1000.0, 1000.0))

    def test_scores(self) -> None:
        self.assertEqual([league.attempt_score(True, False), league.attempt_score(False, True), league.attempt_score(False, False)],
                         [1.0, 0.6, 0.0])

    def test_normalization_ignores_comments_and_blank_lines(self) -> None:
        self.assertEqual(league.normalize_source("def f():\n\n    # note\n    return 1   \n"), "def f():\n    return 1")
        self.assertEqual(league.extract_source("text\n```python\nx = 1\n```\nmore"), "x = 1")

    def test_pairing_and_task_choice(self) -> None:
        authors = [{"profile_id": "a", "rating": 1000, "last_played_at": "2026-01-02"},
                   {"profile_id": "b", "rating": 1200, "last_played_at": None},
                   {"profile_id": "c", "rating": 1190, "last_played_at": "2026-01-01"}]
        first, second = league.choose_pair(authors, random.Random(0))
        self.assertEqual((first["profile_id"], second["profile_id"]), ("b", "c"))
        with self.assertRaises(ValueError):
            league.choose_pair(authors[:1], random.Random(0))
        self.assertEqual(league.choose_task(TASKS, {}, ["python-01-double"], random.Random(0))["id"], "python-02-upper")

    def test_evolution_plan_breeds_the_best_and_retires_the_weakest_veteran(self) -> None:
        authors = [{"profile_id": f"p{i}", "rating": 1000 + i * 10, "matches": 10} for i in range(league.POPULATION_CAP)]
        plan = league.evolution_plan(authors)
        self.assertEqual((plan["parent"]["profile_id"], plan["retire"]["profile_id"]), ("p5", "p0"))
        self.assertEqual(league.evolution_plan([{"profile_id": "x", "rating": 1000, "matches": 1}]), {"retire": None, "parent": None})

    def test_child_profile_keeps_output_rules_and_bounds(self) -> None:
        parent = dict(league.SEED_PROFILES[0], rating=1100.0, generation=0)
        child = league.child_profile(parent, "You write small, correct Python functions and check edge cases.", 1, random.Random(0))
        self.assertIn(league.BASE_RULES, child["system_prompt"])
        self.assertEqual((child["parent_id"], child["generation"], child["rating"]), (parent["profile_id"], 1, 1100.0))
        self.assertIsNone(league.child_profile(parent, "too short", 2, random.Random(0)))
        self.assertIsNone(league.child_profile(parent, "x" * 2000, 3, random.Random(0)))

    def test_packet_selection_dedupes_and_flags_low_diversity(self) -> None:
        rows = [{"task_id": "t1", "normalized_sha256": "n1"}, {"task_id": "t1", "normalized_sha256": "n1"},
                {"task_id": "t2", "normalized_sha256": "n2"}]
        selection, metrics = league.packet_selection(rows)
        self.assertEqual(len(selection), 2)
        self.assertEqual(metrics, {"unique_ratio": round(2 / 3, 4), "max_repetition": 0.5})
        self.assertEqual(league.packet_status(metrics), "flagged")
        diverse = [{"task_id": f"t{i}", "normalized_sha256": f"n{i}"} for i in range(25)]
        self.assertEqual(league.packet_status(league.packet_selection(diverse)[1]), "awaiting_owner_approval")


class ArenaRunnerTests(ArenaTestCase):
    def test_seed_uses_only_configured_engines(self) -> None:
        self.arena({"BOOTSTRAP": FakeEngine("BOOTSTRAP")})
        self.assertEqual({p["engine"] for p in self.store.profiles()}, {"BOOTSTRAP"})
        self.assertEqual(len(self.store.profiles(role="author")), 2)

    def test_match_rates_authors_and_the_critic_repair(self) -> None:
        arena = self.arena({"QWEN-CODER": FakeEngine("QWEN-CODER", first_pass=False)})
        summary = arena.play_match()
        self.assertEqual([r["score"] for r in summary["results"].values()], [0.6, 0.6])  # both repaired after advice
        kinds = [e["kind"] for e in self.store.events_after(0)]
        self.assertEqual(kinds.count("critique"), 2)
        self.assertEqual(kinds[-1], "match_finished")
        critic = self.store.profiles(role="critic")[0]
        self.assertEqual((critic["advised"], critic["advice_success"]), (2, 2))
        attempts = [e["payload"] for e in self.store.events_after(0) if e["kind"] == "attempt"]
        self.assertEqual([(a["attempt"], a["passed"]) for a in attempts], [(1, False), (2, True), (1, False), (2, True)])
        self.assertEqual(self.store.overview()["totals"]["matches"], 1)

    def test_evolution_packets_and_owner_approval(self) -> None:
        engines = {"QWEN-CODER": FakeEngine("QWEN-CODER"), "BOOTSTRAP": FakeEngine("BOOTSTRAP")}
        arena = self.arena(engines)
        for profile in self.store.profiles(role="author"):
            with self.store._connect() as connection:
                connection.execute("UPDATE profiles SET matches=5 WHERE profile_id=?", (profile["profile_id"],))
        self.assertEqual(arena.step(), "played")
        self.assertEqual(arena.step(), "played")
        self.assertEqual(arena.step(), "played")  # third match triggers evolution
        children = [p for p in self.store.profiles() if p["parent_id"]]
        self.assertEqual(len(children), 1)
        packets = self.store.overview()["packets"]
        self.assertEqual(len(packets), 1)
        packet = packets[0]
        manifest = json.loads((self.root / "packets" / packet["packet_id"] / "manifest.json").read_text())
        self.assertEqual(manifest["solutions_sha256"], packet["solutions_sha256"])
        self.assertEqual(manifest["rule"], "RAW until the owner approves it; never promoted automatically")
        self.config.inbox_dir.mkdir()
        approval = {"schema_version": APPROVAL_SCHEMA, "kind": "packet", "target_id": packet["packet_id"],
                    "target_sha256": "0" * 64, "approved_by": "victor", "approved_at": "2026-09-11T12:00:00Z"}
        (self.config.inbox_dir / "a.json").write_text(json.dumps(approval))
        self.assertEqual(arena.apply_approvals(), 0)  # wrong digest is refused
        approval["target_sha256"] = packet["solutions_sha256"]
        (self.config.inbox_dir / "b.json").write_text(json.dumps(approval))
        self.assertEqual(packet["status"], "flagged")  # two tasks only: not diverse enough to ever feed training
        self.assertEqual(arena.apply_approvals(), 0)  # a flagged packet can never be approved
        self.assertEqual(sorted(p.name for p in (self.config.inbox_dir / "processed").iterdir())[0], "a.refused.json")

    def test_healthy_packet_is_approved_only_with_its_exact_digest(self) -> None:
        arena = self.arena({"BOOTSTRAP": FakeEngine("BOOTSTRAP")})
        directory = self.root / "packets" / "arena-test"
        directory.mkdir(parents=True)
        self.store.record_packet({"packet_id": "arena-test", "created_at": "2026-09-11T12:00:00Z", "path": str(directory),
                                  "solutions_sha256": "a" * 64, "solutions": 30, "unique_ratio": 0.9, "max_repetition": 0.03,
                                  "status": "awaiting_owner_approval"}, [])
        self.config.inbox_dir.mkdir()
        base = {"schema_version": APPROVAL_SCHEMA, "kind": "packet", "target_id": "arena-test", "approved_by": "victor"}
        (self.config.inbox_dir / "1.json").write_text(json.dumps({**base, "target_sha256": "b" * 64}))
        (self.config.inbox_dir / "2.json").write_text("not json")
        self.assertEqual(arena.apply_approvals(), 0)
        (self.config.inbox_dir / "3.json").write_text(json.dumps({**base, "target_sha256": "a" * 64}))
        self.assertEqual(arena.apply_approvals(), 1)
        self.assertEqual(self.store.overview()["packets"][0]["status"], "approved")
        self.assertEqual(json.loads((directory / "approval.json").read_text())["approved_by"], "victor")
        (self.config.inbox_dir / "4.json").write_text(json.dumps({**base, "target_sha256": "a" * 64}))
        self.assertEqual(arena.apply_approvals(), 0)  # already approved: nothing to do twice
        outcomes = sorted(path.name for path in (self.config.inbox_dir / "processed").iterdir())
        self.assertEqual(outcomes, ["1.refused.json", "2.refused.json", "3.applied.json", "4.refused.json"])

    def test_profile_chat_approval(self) -> None:
        arena = self.arena({"BOOTSTRAP": FakeEngine("BOOTSTRAP")})
        self.config.inbox_dir.mkdir()
        (self.config.inbox_dir / "p.json").write_text(json.dumps(
            {"schema_version": APPROVAL_SCHEMA, "kind": "profile_chat", "target_id": "author-bootstrap", "approved_by": "victor"}))
        self.assertEqual(arena.apply_approvals(), 1)
        self.assertEqual(next(p for p in self.store.profiles() if p["profile_id"] == "author-bootstrap")["chat_approved"], 1)

    def test_pauses_when_the_owner_uses_an_engine_or_an_engine_is_down(self) -> None:
        arena = self.arena({"BOOTSTRAP": FakeEngine("BOOTSTRAP", busy=True)})
        self.assertEqual(arena.step(), "paused")
        self.assertEqual(self.store.overview()["state"]["reason"], "engine_busy")
        arena = self.arena({"BOOTSTRAP": FakeEngine("BOOTSTRAP", fail=True)})
        self.assertEqual(arena.step(), "engine_unavailable")
        self.assertEqual(self.store.overview()["state"]["status"], "paused")

    def test_hourly_budget(self) -> None:
        self.config.max_matches_per_hour = 1
        arena = self.arena({"BOOTSTRAP": FakeEngine("BOOTSTRAP")})
        self.assertEqual(arena.step(), "played")
        self.assertEqual(arena.step(), "budget")

    def test_read_only_store_refuses_writes(self) -> None:
        self.arena({"BOOTSTRAP": FakeEngine("BOOTSTRAP")})
        reader = ArenaStore(self.root / "arena.sqlite3", read_only=True)
        self.assertEqual(len(reader.overview()["profiles"]), 3)
        with self.assertRaises(Exception):
            reader.add_event("x", {})
        with self.assertRaises(FileNotFoundError):
            ArenaStore(self.root / "missing.sqlite3", read_only=True).overview()


class EngineTests(unittest.TestCase):
    def test_engines_must_stay_local(self) -> None:
        with self.assertRaises(ValueError):
            ChatEngine("X", "https://api.example.com")
        ChatEngine("X", "http://192.168.0.144:8790", "t" * 32)

    def test_unreachable_engine_is_not_busy_and_raises_on_chat(self) -> None:
        engine = ChatEngine("X", "http://127.0.0.1:9", timeout=2)
        self.assertFalse(engine.busy())
        with self.assertRaises(EngineUnavailable):
            engine.chat("s", "u", temperature=0, max_tokens=1, seed=0)


if __name__ == "__main__":
    unittest.main()
