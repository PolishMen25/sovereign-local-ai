"""Arena daemon: play refereed matches, evolve authors, bundle gated packets.

One match: two author profiles solve the same task; each answer runs in the
offline sandbox against the task's own tests.  A failed first answer goes to a
critic profile, whose advice the author uses for a single repair.  Ratings move
head to head (Elo).  Every few matches the best author breeds a variant written
by a coach prompt, and the weakest veteran retires.  Accepted solutions are
bundled into packets that wait for the owner's approval; nothing here trains a
model or promotes data.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import random
import shutil
import tempfile
import time
from typing import Any, Callable, Protocol

from services.arena import league
from services.arena.engines import ChatEngine, EngineUnavailable
from services.arena.store import ArenaStore, utc_now

APPROVAL_SCHEMA = "arena-approval.v1"
MAX_TOKENS_AUTHOR = 700
MAX_TOKENS_CRITIC = 220
MAX_TOKENS_COACH = 400
FAILURE_EXCERPT = 1_500
IDLE_SECONDS = 30


class Engine(Protocol):
    name: str

    def busy(self) -> bool: ...

    def chat(self, system_prompt: str, user_prompt: str, *, temperature: float, max_tokens: int, seed: int) -> str: ...


Referee = Callable[[dict[str, str], str], dict[str, Any]]


@dataclass
class ArenaConfig:
    state_dir: Path
    inbox_dir: Path
    packet_size: int = 50
    evolve_every: int = 12
    max_matches_per_hour: int = 12


def load_suite(path: Path) -> list[dict[str, str]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    tasks = document.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("arena task suite is empty")
    for task in tasks:
        if not isinstance(task, dict) or not {"id", "prompt", "test_source"} <= set(task):
            raise ValueError("arena task shape is invalid")
    return tasks


def sandbox_referee(workspace: Path) -> Referee:
    """Run candidates with the project's bwrap sandbox; refuse if it cannot run known-good code."""

    from tools import run_code_agent_loop as loop
    from tools import run_code_evaluation as evaluation

    binary = evaluation.require_sandbox()
    workspace.mkdir(parents=True, exist_ok=True)
    budget = evaluation.process_limit()
    evaluation.sandbox_selftest(binary, output_dir=workspace, process_budget=budget)

    def referee(task: dict[str, str], source: str) -> dict[str, Any]:
        return loop.execute(binary, task=task, source=source, workspace=workspace, process_budget=evaluation.process_limit())

    return referee


class Arena:
    def __init__(self, store: ArenaStore, engines: dict[str, Engine], referee: Referee, tasks: list[dict[str, str]],
                 config: ArenaConfig, *, rng: random.Random | None = None) -> None:
        self.store, self.engines, self.referee, self.tasks, self.config = store, engines, referee, tasks, config
        self.tasks_by_id = {task["id"]: task for task in tasks}
        self.rng = rng or random.Random()
        self.children = 0

    # --- setup ------------------------------------------------------------

    def seed(self) -> None:
        existing = {profile["profile_id"] for profile in self.store.profiles(status=None)}
        for profile in league.SEED_PROFILES:
            if profile["profile_id"] not in existing and profile["engine"] in self.engines:
                self.store.add_profile(dict(profile))
                self.store.add_event("profile_created", {"profile_id": profile["profile_id"], "display_name": profile["display_name"],
                                                         "role": profile["role"], "engine": profile["engine"], "parent_id": None})
        self.children = sum(1 for p in self.store.profiles(status=None) if p["parent_id"])

    # --- one match --------------------------------------------------------

    def _engine(self, profile: dict[str, Any]) -> Engine:
        return self.engines[profile["engine"]]

    def _author_answer(self, profile: dict[str, Any], prompt: str) -> str:
        answer = self._engine(profile).chat(profile["system_prompt"], prompt, temperature=profile["temperature"],
                                            max_tokens=MAX_TOKENS_AUTHOR, seed=self.rng.randrange(2**31))
        return league.extract_source(answer) or "# no code produced"

    def _play_author(self, match_id: int, profile: dict[str, Any], task: dict[str, str],
                     critic: dict[str, Any] | None) -> dict[str, Any]:
        source = self._author_answer(profile, task["prompt"])
        verdict = self.referee(task, source)
        failure = str(verdict.get("failure", ""))[-FAILURE_EXCERPT:]
        self._record(match_id, profile, task, 1, verdict["passed"], source, failure)
        if verdict["passed"]:
            return {"first_pass": True, "repaired": False, "advised": False}
        if critic is None:
            return {"first_pass": False, "repaired": False, "advised": False}
        critique = self._engine(critic).chat(
            critic["system_prompt"],
            f"Task:\n{task['prompt']}\n\nCode:\n```python\n{source}\n```\n\nTest failure:\n```\n{failure or '(no output)'}\n```",
            temperature=critic["temperature"], max_tokens=MAX_TOKENS_CRITIC, seed=self.rng.randrange(2**31)).strip()[:1_200]
        self.store.add_event("critique", {"match_id": match_id, "critic_id": critic["profile_id"], "author_id": profile["profile_id"],
                                          "task_id": task["id"], "text": critique})
        repair_prompt = (f"{task['prompt']}\n\nYour previous answer failed its tests:\n```python\n{source}\n```\n"
                         f"Test output:\n```\n{failure or '(no output)'}\n```\nA reviewer says:\n{critique}\n\nFix the function.")
        fixed = self._author_answer(profile, repair_prompt)
        second = self.referee(task, fixed)
        self._record(match_id, profile, task, 2, second["passed"], fixed, str(second.get("failure", ""))[-FAILURE_EXCERPT:], critique)
        return {"first_pass": False, "repaired": bool(second["passed"]), "advised": True}

    def _record(self, match_id: int, profile: dict[str, Any], task: dict[str, str], attempt: int, passed: bool,
                source: str, failure: str, critique: str = "") -> None:
        normalized = league.normalize_source(source)
        self.store.record_attempt(match_id, profile["profile_id"], task["id"], attempt, passed=passed, source=source,
                                  source_sha256=league.sha256_text(source), normalized_sha256=league.sha256_text(normalized),
                                  failure_excerpt="" if passed else failure, critique=critique)
        self.store.add_event("attempt", {"match_id": match_id, "profile_id": profile["profile_id"], "task_id": task["id"],
                                         "attempt": attempt, "passed": bool(passed), "source": source[:2_000],
                                         "failure": "" if passed else failure[-600:]})

    def play_match(self) -> dict[str, Any]:
        authors = self.store.profiles(role="author")
        critics = self.store.profiles(role="critic")
        a, b = league.choose_pair(authors, self.rng)
        critic = self.rng.choice(critics) if critics else None
        task = league.choose_task(self.tasks, self.store.task_solve_counts(), self.store.recent_task_ids(), self.rng)
        match_id = self.store.start_match(task["id"], a["profile_id"], b["profile_id"], critic["profile_id"] if critic else None)
        self.store.add_event("match_started", {"match_id": match_id, "task_id": task["id"], "prompt": task["prompt"],
                                               "authors": [a["profile_id"], b["profile_id"]],
                                               "critic_id": critic["profile_id"] if critic else None})
        outcomes = {profile["profile_id"]: self._play_author(match_id, profile, task, critic) for profile in (a, b)}
        scores = {pid: league.attempt_score(o["first_pass"], o["repaired"]) for pid, o in outcomes.items()}
        new_a, new_b = league.elo_update(a["rating"], b["rating"], scores[a["profile_id"]], scores[b["profile_id"]])
        results = {
            a["profile_id"]: {"score": scores[a["profile_id"]], "rating": new_a, "won": scores[a["profile_id"]] > scores[b["profile_id"]],
                              "first_pass": outcomes[a["profile_id"]]["first_pass"], "repaired": outcomes[a["profile_id"]]["repaired"]},
            b["profile_id"]: {"score": scores[b["profile_id"]], "rating": new_b, "won": scores[b["profile_id"]] > scores[a["profile_id"]],
                              "first_pass": outcomes[b["profile_id"]]["first_pass"], "repaired": outcomes[b["profile_id"]]["repaired"]},
        }
        critic_result = None
        if critic is not None:
            advised = sum(1 for o in outcomes.values() if o["advised"])
            critic_result = {"profile_id": critic["profile_id"], "advised": advised,
                             "success": sum(1 for o in outcomes.values() if o["advised"] and o["repaired"])}
        self.store.finish_match(match_id, results, critic_result)
        summary = {"match_id": match_id, "task_id": task["id"],
                   "results": {pid: {"score": r["score"], "rating": round(r["rating"], 1),
                                     "delta": round(r["rating"] - (a if pid == a["profile_id"] else b)["rating"], 1)}
                               for pid, r in results.items()}}
        self.store.add_event("match_finished", summary)
        return summary

    # --- evolution --------------------------------------------------------

    def evolve(self) -> dict[str, Any] | None:
        plan = league.evolution_plan(self.store.profiles(role="author"))
        parent = plan["parent"]
        if parent is None:
            return None
        coach = self.engines.get("QWEN-CODER") or next(iter(self.engines.values()))
        proposal = coach.chat("You write concise instructions for automated programmers.",
                              league.coach_prompt(parent, self.store.recent_failures(parent["profile_id"])),
                              temperature=0.7, max_tokens=MAX_TOKENS_COACH, seed=self.rng.randrange(2**31))
        child = league.child_profile(parent, proposal, self.children + 1, self.rng)
        if child is None:
            self.store.add_event("evolution_rejected", {"parent_id": parent["profile_id"], "reason": "invalid instructions"})
            return None
        if plan["retire"] is not None:
            self.store.retire_profile(plan["retire"]["profile_id"])
            self.store.add_event("profile_retired", {"profile_id": plan["retire"]["profile_id"],
                                                     "rating": round(plan["retire"]["rating"], 1)})
        self.store.add_profile(child)
        self.children += 1
        self.store.add_event("profile_created", {"profile_id": child["profile_id"], "display_name": child["display_name"],
                                                 "role": "author", "engine": child["engine"], "parent_id": parent["profile_id"],
                                                 "system_prompt": child["system_prompt"]})
        return child

    # --- packets and approvals -------------------------------------------

    def maybe_packet(self) -> dict[str, Any] | None:
        accepted = [dict(row) for row in self.store.unpacked_accepted()]
        if len(accepted) < self.config.packet_size:
            return None
        selection, metrics = league.packet_selection(accepted)
        created_at = utc_now()
        sequence = self.store.packet_count() + 1
        packet_id = f"arena-{created_at.replace(':', '').replace('-', '').lower()}-{sequence:04d}"
        directory = self.config.state_dir / "packets" / packet_id
        directory.mkdir(parents=True, exist_ok=False)
        body = league.packet_lines(selection, self.tasks_by_id)
        (directory / "solutions.jsonl").write_text(body, encoding="utf-8")
        status = league.packet_status(metrics)
        manifest = {
            "schema_version": "arena-packet.v1", "packet_id": packet_id, "created_at": created_at,
            "solutions": len(selection), "accepted_in_window": len(accepted),
            "solutions_sha256": league.sha256_text(body), "metrics": metrics,
            "thresholds": {"min_unique_ratio": league.MIN_UNIQUE_RATIO, "max_repetition": league.MAX_REPETITION},
            "synthetic": True, "max_share_in_corpus_increment": league.SYNTHETIC_SHARE_CAP,
            "referee": "task tests in the offline bwrap sandbox", "status": status,
            "rule": "RAW until the owner approves it; never promoted automatically",
        }
        (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        packet = {"packet_id": packet_id, "created_at": created_at, "path": str(directory),
                  "solutions_sha256": manifest["solutions_sha256"], "solutions": len(selection), **metrics, "status": status}
        self.store.record_packet(packet, [row["attempt_id"] for row in accepted])
        self.store.add_event("packet_created", {k: packet[k] for k in ("packet_id", "solutions", "unique_ratio", "max_repetition", "status")})
        return packet

    def apply_approvals(self) -> int:
        inbox = self.config.inbox_dir
        if not inbox.is_dir():
            return 0
        processed = inbox / "processed"
        applied = 0
        for path in sorted(inbox.glob("*.json")):
            try:
                approval = json.loads(path.read_text(encoding="utf-8"))
                valid = isinstance(approval, dict) and approval.get("schema_version") == APPROVAL_SCHEMA
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                valid, approval = False, {}
            outcome = "refused"
            if valid and approval.get("kind") == "packet":
                row = self.store.approve_packet(str(approval.get("target_id")), str(approval.get("target_sha256")),
                                                str(approval.get("approved_by")))
                if row is not None:
                    Path(row["path"], "approval.json").write_text(json.dumps(approval, ensure_ascii=False, indent=2) + "\n",
                                                                  encoding="utf-8")
                    outcome = "applied"
            elif valid and approval.get("kind") == "profile_chat":
                outcome = "applied" if self.store.approve_profile_for_chat(str(approval.get("target_id"))) else "refused"
            self.store.add_event("approval", {"kind": approval.get("kind"), "target_id": approval.get("target_id"),
                                              "approved_by": approval.get("approved_by"), "outcome": outcome})
            processed.mkdir(exist_ok=True)
            shutil.move(str(path), str(processed / f"{path.stem}.{outcome}.json"))
            applied += outcome == "applied"
        return applied

    # --- main loop --------------------------------------------------------

    def step(self) -> str:
        """Run one scheduling step and return what happened (for the status bar)."""

        self.apply_approvals()
        busy = [engine.name for engine in self.engines.values() if engine.busy()]
        if busy:
            self.store.set_state(status="paused", reason="engine_busy", engines=busy, heartbeat=utc_now())
            return "paused"
        played = self.store.overview()["totals"]["matches_last_hour"]
        if played >= self.config.max_matches_per_hour:
            self.store.set_state(status="paused", reason="hourly_budget", heartbeat=utc_now())
            return "budget"
        if len(self.store.profiles(role="author")) < 2:
            self.store.set_state(status="paused", reason="not_enough_authors", heartbeat=utc_now())
            return "waiting"
        self.store.set_state(status="running", reason="match", heartbeat=utc_now())
        try:
            self.play_match()
            if self.store.match_count() % self.config.evolve_every == 0:
                self.evolve()
            self.maybe_packet()
        except EngineUnavailable as failure:
            self.store.set_state(status="paused", reason="engine_unavailable", detail=str(failure), heartbeat=utc_now())
            self.store.add_event("engine_unavailable", {"detail": str(failure)})
            return "engine_unavailable"
        return "played"


def main() -> int:
    state_dir = Path(os.environ.get("SOVEREIGN_ARENA_STATE", "/var/lib/sovereign-arena"))
    config = ArenaConfig(
        state_dir=state_dir,
        inbox_dir=Path(os.environ.get("SOVEREIGN_ARENA_INBOX", str(state_dir / "inbox"))),
        packet_size=int(os.environ.get("SOVEREIGN_ARENA_PACKET_SIZE", "50")),
        evolve_every=int(os.environ.get("SOVEREIGN_ARENA_EVOLVE_EVERY", "12")),
        max_matches_per_hour=int(os.environ.get("SOVEREIGN_ARENA_MAX_MATCHES_PER_HOUR", "12")),
    )
    suite = Path(os.environ.get("SOVEREIGN_ARENA_SUITE", "configs/evaluation/core-python-e2.candidate.json"))
    engines: dict[str, Engine] = {"BOOTSTRAP": ChatEngine("BOOTSTRAP", os.environ.get("SOVEREIGN_BOOTSTRAP_ENDPOINT", "http://127.0.0.1:8080"))}
    qwen_token = os.environ.get("SOVEREIGN_QWEN_TOKEN", "")
    if len(qwen_token) >= 32:
        engines["QWEN-CODER"] = ChatEngine("QWEN-CODER", os.environ.get("SOVEREIGN_QWEN_ENDPOINT", "http://192.168.0.144:8790"), qwen_token)
    store = ArenaStore(state_dir / "arena.sqlite3")
    store.initialize()
    try:
        referee = sandbox_referee(Path(tempfile.gettempdir()) / "sovereign-arena")
    except Exception as failure:  # the status must reach the page, whatever refused
        store.set_state(status="stopped", reason="sandbox_unavailable", detail=str(failure)[:300], heartbeat=utc_now())
        raise SystemExit(f"arena refused to start: {failure}")
    arena = Arena(store, engines, referee, load_suite(suite), config)
    arena.seed()
    store.set_state(status="running", reason="started", engines=sorted(engines), heartbeat=utc_now())
    store.add_event("arena_started", {"engines": sorted(engines), "tasks": len(arena.tasks)})
    while True:
        outcome = arena.step()
        time.sleep(IDLE_SECONDS if outcome != "played" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
