"""Pure arena rules: seed profiles, ratings, pairing, evolution, packets.

Nothing here touches the network, a model or the sandbox, so every rule is
unit-testable and deterministic for a given random generator.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import random
import re
from typing import Any, Sequence

ELO_K = 24.0
SCORE_FIRST_PASS = 1.0
SCORE_REPAIRED = 0.6
SCORE_FAILED = 0.0
POPULATION_CAP = 6
RETIRE_AFTER_MATCHES = 8
PARENT_MIN_MATCHES = 4
PROMPT_MIN_CHARS = 40
PROMPT_MAX_CHARS = 1_200
# Anti-collapse thresholds from docs/model/self-training-loop-spec.md, section 5.
MIN_UNIQUE_RATIO = 0.80
MAX_REPETITION = 0.05
SYNTHETIC_SHARE_CAP = 0.20

BASE_RULES = "Answer with a single Python code block and nothing else. No tests, no explanation, no example usage."

SEED_PROFILES: tuple[dict[str, Any], ...] = (
    {"profile_id": "author-direct", "display_name": "Direct", "role": "author", "engine": "QWEN-CODER", "temperature": 0.2,
     "system_prompt": "You are a precise Python programmer. Write exactly the requested function, as simply as possible. " + BASE_RULES},
    {"profile_id": "author-edge-cases", "display_name": "Cas limites", "role": "author", "engine": "QWEN-CODER", "temperature": 0.3,
     "system_prompt": "You are a careful Python programmer. Before writing, think about empty inputs, zero, negative numbers, "
                      "Unicode and very large values, then write a function that handles all of them. " + BASE_RULES},
    {"profile_id": "author-spec-reader", "display_name": "Lecteur de spec", "role": "author", "engine": "QWEN-CODER", "temperature": 0.2,
     "system_prompt": "You are a Python programmer who follows specifications literally: exact function name, exact argument order, "
                      "exact return type, no extra behaviour. " + BASE_RULES},
    {"profile_id": "author-bootstrap", "display_name": "Bootstrap", "role": "author", "engine": "BOOTSTRAP", "temperature": 0.2,
     "system_prompt": "You are a Python programmer. Write the requested function. " + BASE_RULES},
    {"profile_id": "author-bootstrap-careful", "display_name": "Bootstrap prudent", "role": "author", "engine": "BOOTSTRAP", "temperature": 0.1,
     "system_prompt": "You are a careful Python programmer. Re-read the task, respect the exact function name and handle empty "
                      "and edge inputs. " + BASE_RULES},
    {"profile_id": "critic-qwen", "display_name": "Relecteur Qwen", "role": "critic", "engine": "QWEN-CODER", "temperature": 0.2,
     "system_prompt": "You review failing Python code. Read the task, the code and the test failure, then explain in at most five "
                      "short lines what is wrong and how to fix it. Do not write the full solution."},
    {"profile_id": "critic-bootstrap", "display_name": "Relecteur Bootstrap", "role": "critic", "engine": "BOOTSTRAP", "temperature": 0.2,
     "system_prompt": "You review failing Python code. In at most five short lines, say which requirement the code breaks and how "
                      "to fix it. Do not write the full solution."},
)

CODE_BLOCK = re.compile(r"```(?:python)?\s*\n(.*?)```", re.S)
COMMENT_LINE = re.compile(r"^\s*#.*$")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def extract_source(answer: str) -> str:
    match = CODE_BLOCK.search(answer)
    return (match.group(1) if match else answer).strip()


def normalize_source(source: str) -> str:
    """Comparable form of a solution: no comments, no blank lines, no trailing spaces."""

    lines = [line.rstrip() for line in source.replace("\r\n", "\n").split("\n")]
    return "\n".join(line for line in lines if line.strip() and not COMMENT_LINE.match(line))


# --- scoring ---------------------------------------------------------------

def attempt_score(first_passed: bool, repaired: bool) -> float:
    if first_passed:
        return SCORE_FIRST_PASS
    return SCORE_REPAIRED if repaired else SCORE_FAILED


def elo_update(rating_a: float, rating_b: float, score_a: float, score_b: float, k: float = ELO_K) -> tuple[float, float]:
    """Head-to-head update: the higher score wins, equal scores draw."""

    expected_a = 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))
    outcome_a = 1.0 if score_a > score_b else (0.5 if score_a == score_b else 0.0)
    delta = k * (outcome_a - expected_a)
    return rating_a + delta, rating_b - delta


# --- scheduling ------------------------------------------------------------

def choose_task(tasks: Sequence[dict[str, str]], solve_counts: dict[str, int], recent: Sequence[str],
                rng: random.Random) -> dict[str, str]:
    """Favour tasks the arena solves least, and avoid the last ones played."""

    pool = [task for task in tasks if task["id"] not in set(recent)] or list(tasks)
    weights = [1.0 / (1 + solve_counts.get(task["id"], 0)) for task in pool]
    return rng.choices(pool, weights=weights, k=1)[0]


def choose_pair(authors: Sequence[dict[str, Any]], rng: random.Random) -> tuple[dict[str, Any], dict[str, Any]]:
    """The least recently played author meets the opponent closest in rating."""

    if len(authors) < 2:
        raise ValueError("the arena needs at least two active authors")
    first = min(authors, key=lambda p: (p.get("last_played_at") or "", rng.random()))
    others = [p for p in authors if p["profile_id"] != first["profile_id"]]
    second = min(others, key=lambda p: (abs(p["rating"] - first["rating"]), rng.random()))
    return first, second


# --- evolution -------------------------------------------------------------

def evolution_plan(authors: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Decide which author to retire (if any) and which one breeds a variant."""

    ranked = sorted(authors, key=lambda p: p["rating"], reverse=True)
    parents = [p for p in ranked if p["matches"] >= PARENT_MIN_MATCHES]
    if not parents:
        return {"retire": None, "parent": None}
    retire = None
    if len(ranked) >= POPULATION_CAP:
        veterans = [p for p in reversed(ranked) if p["matches"] >= RETIRE_AFTER_MATCHES and p["profile_id"] != parents[0]["profile_id"]]
        if not veterans:
            return {"retire": None, "parent": None}
        retire = veterans[0]
    return {"retire": retire, "parent": parents[0]}


def coach_prompt(parent: dict[str, Any], failures: Sequence[dict[str, str]]) -> str:
    lines = "\n".join(f"- task {item['task_id']}: {item['failure_excerpt'][-300:]}" for item in failures) or "- (no recent failure)"
    return (
        "You improve the instructions given to an automated Python programmer.\n"
        "Here are its current instructions:\n<<<\n" + parent["system_prompt"] + "\n>>>\n"
        "Here are its recent test failures:\n" + lines + "\n\n"
        "Write improved instructions that avoid these mistakes. Keep the same output rules "
        "(a single Python code block, no tests, no explanation). At most 900 characters. "
        "Answer with the new instructions only, without quotes or markdown."
    )


def child_profile(parent: dict[str, Any], new_prompt: str, index: int, rng: random.Random) -> dict[str, Any] | None:
    prompt = new_prompt.strip().strip("`").strip()
    if not PROMPT_MIN_CHARS <= len(prompt) <= PROMPT_MAX_CHARS:
        return None
    if BASE_RULES not in prompt:
        prompt = prompt.rstrip(".") + ". " + BASE_RULES
    if len(prompt) > PROMPT_MAX_CHARS:
        return None
    temperature = round(min(0.8, max(0.0, parent["temperature"] + rng.choice((-0.1, 0.0, 0.1)))), 2)
    generation = int(parent.get("generation", 0)) + 1
    return {
        "profile_id": f"author-g{generation}-{index:04d}",
        "display_name": f"{parent['display_name']} · v{generation}.{index}",
        "role": "author", "engine": parent["engine"], "temperature": temperature,
        "system_prompt": prompt, "parent_id": parent["profile_id"], "generation": generation,
        "rating": float(parent["rating"]),
    }


# --- packets ---------------------------------------------------------------

def packet_selection(accepted: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, float]]:
    """Keep one solution per (task, normalized source) and measure diversity.

    ``unique_ratio`` is unique normalized solutions / accepted solutions in the
    window; ``max_repetition`` is the share of the most frequent normalized
    solution among the kept ones.
    """

    kept: dict[tuple[str, str], dict[str, Any]] = {}
    for row in accepted:
        kept.setdefault((row["task_id"], row["normalized_sha256"]), row)
    selection = list(kept.values())
    unique_ratio = len({row["normalized_sha256"] for row in accepted}) / len(accepted) if accepted else 0.0
    counts = Counter(row["normalized_sha256"] for row in selection)
    max_repetition = max(counts.values()) / len(selection) if selection else 0.0
    return selection, {"unique_ratio": round(unique_ratio, 4), "max_repetition": round(max_repetition, 4)}


def packet_status(metrics: dict[str, float]) -> str:
    healthy = metrics["unique_ratio"] >= MIN_UNIQUE_RATIO and metrics["max_repetition"] <= MAX_REPETITION
    return "awaiting_owner_approval" if healthy else "flagged"


def packet_lines(selection: Sequence[dict[str, Any]], tasks: dict[str, dict[str, str]]) -> str:
    lines = []
    for row in selection:
        task = tasks[row["task_id"]]
        lines.append(json.dumps({
            "task_id": row["task_id"],
            "prompt_sha256": sha256_text(task["prompt"]),
            "test_sha256": sha256_text(task["test_source"]),
            "source": row["source"],
            "source_sha256": row["source_sha256"],
            "profile_id": row["profile_id"],
            "engine": row["engine"],
            "attempt": row["attempt"],
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return "\n".join(lines) + "\n"
