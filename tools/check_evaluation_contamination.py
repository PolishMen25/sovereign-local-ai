#!/usr/bin/env python3
"""Check one training source for overlap with the sealed evaluation sets E1 and E2.

Static and read-only.  The tool reads a single training source: an arena
corpus increment, an authorized-text split with its corpus manifest, or a
conversation learning-candidate packet.  It verifies the source against the
digest its own manifest declares, then compares every record with the E1
prompts and with the E2 prompts and function names.  It writes nothing: the
report goes to standard output and is content-free (identifiers and SHA-256
only, never a prompt, a record or a solution).

Overlap levels, strongest first:

  exact_prompt         the evaluation prompt appears verbatim in one record;
  normalized_prompt    it appears once case, punctuation and spacing are
                       normalized;
  ngram_prompt         at least the threshold share of its word n-grams appears
                       in one record (partial copy);
  function_definition  a record defines an E2 function (``def name(``).

These are heuristics: a paraphrase sharing few n-grams stays invisible.

Exit codes: 0 no overlap, 1 overlap found (report printed), 2 input refused
(nothing printed on standard output).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Callable
import unicodedata


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.validate_training_corpus_manifest import validate as validate_corpus_manifest


REPORT_SCHEMA = "evaluation-contamination-report.v1"
E1_SCHEMA = "core-language-evaluation-suite.v1"
E2_SCHEMA = "core-code-evaluation-suite.v1"
ARENA_SCHEMAS = frozenset({"arena-corpus-increment.v1", "arena-corpus-increment.validated.v1"})
CANDIDATE_MANIFEST_SCHEMA = "conversation-learning-candidate-manifest.v1"
CANDIDATE_RECORD_SCHEMA = "conversation-learning-record.v1"
CANDIDATE_MANIFEST_FILE = "manifest.candidate.json"
CANDIDATE_DATA_FILE = "learning-candidates.jsonl"
CANDIDATE_RECORD_KEYS = frozenset({"conversation_sha256", "record_id", "schema_version", "source_message_sha256", "text"})
PLAIN_RECORD_KEYS = frozenset({"record_id", "text"})
DEFAULT_E1 = PROJECT_ROOT / "configs" / "evaluation" / "core-30m-e1.candidate.json"
DEFAULT_E2 = PROJECT_ROOT / "configs" / "evaluation" / "core-python-e2.candidate.json"

DEFAULT_NGRAM_SIZE = 8
DEFAULT_NGRAM_THRESHOLD = 0.5
DEFAULT_MAX_RECORDS_PER_FINDING = 20
NGRAM_SIZE_RANGE = (3, 32)
MAX_RECORDS_PER_FINDING_RANGE = (1, 1_000)
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024
MAX_RECORDS = 1_000_000
MAX_EVAL_ITEMS = 10_000
MAX_PROMPT_CHARS = 20_000

SHA256 = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
FUNCTION_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
NON_WORD = re.compile(r"[\W_]+")
LEVELS = ("exact_prompt", "normalized_prompt", "ngram_prompt", "function_definition")

EXIT_CLEAN = 0
EXIT_OVERLAP = 1
EXIT_REFUSED = 2


class CheckRefused(ValueError):
    """The input cannot be checked safely; no report is produced."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def normalize(text: str) -> str:
    """NFKC, case-folded, every run of non-alphanumeric characters as one space."""

    return " ".join(NON_WORD.sub(" ", unicodedata.normalize("NFKC", text).casefold()).split())


def read_bounded(path: Path, *, maximum: int, context: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise CheckRefused(f"{context} must be a regular file")
    size = path.stat().st_size
    if not 1 <= size <= maximum:
        raise CheckRefused(f"{context} size is outside the bounded range")
    payload = path.read_bytes()
    if len(payload) != size:
        raise CheckRefused(f"{context} changed while it was read")
    return payload


def read_json_object(path: Path, *, context: str) -> tuple[dict[str, Any], bytes]:
    payload = read_bounded(path, maximum=MAX_JSON_BYTES, context=context)
    try:
        document = json.loads(payload.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise CheckRefused(f"{context} must be UTF-8") from error
    except json.JSONDecodeError as error:
        raise CheckRefused(f"{context} is not valid JSON (line {error.lineno})") from error
    if not isinstance(document, dict):
        raise CheckRefused(f"{context} must be a JSON object")
    return document, payload


def require_directory(path: Path, context: str) -> None:
    if path.is_symlink() or not path.is_dir():
        raise CheckRefused(f"{context} must be a directory")


def require_sha256(value: Any, context: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise CheckRefused(f"{context} must be a lowercase SHA-256")
    return value


def require_count(value: Any, context: str) -> int:
    if type(value) is not int or not 1 <= value <= MAX_RECORDS:
        raise CheckRefused(f"{context} is outside the bounded range")
    return value


@dataclass(frozen=True)
class EvalItem:
    eval_set: str
    eval_id: str
    eval_sha256: str
    prompt: str = field(repr=False)
    normalized: str = field(repr=False)
    gram_size: int
    grams: frozenset[tuple[str, ...]] = field(repr=False)


@dataclass(frozen=True)
class EvalSet:
    name: str
    schema_version: str
    sha256: str
    items: tuple[EvalItem, ...]
    function_names: tuple[tuple[str, str], ...] = ()

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "schema_version": self.schema_version,
            "sha256": self.sha256,
            "prompt_count": len(self.items),
            "function_name_count": len(self.function_names),
        }


def make_item(eval_set: str, eval_id: Any, prompt: Any, gram_size: int, seen: set[str]) -> EvalItem:
    if not isinstance(eval_id, str) or SAFE_ID.fullmatch(eval_id) is None or eval_id in seen:
        raise CheckRefused(f"{eval_set} item identifiers must be unique and safe")
    seen.add(eval_id)
    if not isinstance(prompt, str) or not 1 <= len(prompt) <= MAX_PROMPT_CHARS:
        raise CheckRefused(f"{eval_set} item {eval_id} has an invalid prompt")
    prompt = prompt.strip()
    normalized = normalize(prompt)
    words = normalized.split()
    if not words:
        raise CheckRefused(f"{eval_set} item {eval_id} has no comparable word")
    size = min(gram_size, len(words))
    grams = frozenset(tuple(words[start:start + size]) for start in range(len(words) - size + 1))
    return EvalItem(eval_set, eval_id, sha256_text(prompt), prompt, normalized, size, grams)


def bounded_entries(value: Any, context: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_EVAL_ITEMS:
        raise CheckRefused(f"{context} must be a non-empty bounded list")
    if any(not isinstance(entry, dict) for entry in value):
        raise CheckRefused(f"{context} entries must be objects")
    return value


def load_e1(path: Path, gram_size: int) -> EvalSet:
    document, payload = read_json_object(path, context="E1 suite")
    if document.get("schema_version") != E1_SCHEMA:
        raise CheckRefused(f"E1 suite schema must be {E1_SCHEMA}")
    seen: set[str] = set()
    items = tuple(
        make_item("E1", entry.get("id"), entry.get("prompt"), gram_size, seen)
        for entry in bounded_entries(document.get("prompts"), "E1 prompts")
    )
    return EvalSet("E1", E1_SCHEMA, sha256_bytes(payload), items)


def load_e2(path: Path, gram_size: int) -> EvalSet:
    document, payload = read_json_object(path, context="E2 suite")
    if document.get("schema_version") != E2_SCHEMA:
        raise CheckRefused(f"E2 suite schema must be {E2_SCHEMA}")
    seen: set[str] = set()
    items: list[EvalItem] = []
    functions: list[tuple[str, str]] = []
    for entry in bounded_entries(document.get("tasks"), "E2 tasks"):
        item = make_item("E2", entry.get("id"), entry.get("prompt"), gram_size, seen)
        name = entry.get("function_name")
        if not isinstance(name, str) or FUNCTION_NAME.fullmatch(name) is None:
            raise CheckRefused(f"E2 item {item.eval_id} has an invalid function name")
        items.append(item)
        functions.append((name, item.eval_id))
    return EvalSet("E2", E2_SCHEMA, sha256_bytes(payload), tuple(items), tuple(functions))


@dataclass
class Finding:
    eval_set: str
    eval_id: str
    field: str
    eval_sha256: str
    level: str
    records: list[dict[str, Any]] = field(default_factory=list)
    record_count: int = 0


class Scanner:
    """Compare records with evaluation items, keeping only identifiers and digests."""

    def __init__(self, eval_sets: list[EvalSet], *, threshold: float, max_records_per_finding: int) -> None:
        self.items = [item for eval_set in eval_sets for item in eval_set.items]
        self.threshold = threshold
        self.max_records = max_records_per_finding
        self.index: dict[int, dict[tuple[str, ...], list[int]]] = {}
        for position, item in enumerate(self.items):
            table = self.index.setdefault(item.gram_size, {})
            for gram in item.grams:
                table.setdefault(gram, []).append(position)
        self.functions: dict[str, list[tuple[str, str]]] = {}
        for eval_set in eval_sets:
            for name, eval_id in eval_set.function_names:
                self.functions.setdefault(name, []).append((eval_set.name, eval_id))
        alternatives = "|".join(re.escape(name) for name in sorted(self.functions))
        self.function_pattern = re.compile(rf"\bdef\s+({alternatives})\s*\(") if alternatives else None
        self.findings: dict[tuple[str, str, str, str], Finding] = {}
        self.records_with_findings: set[int] = set()

    def add(self, *, eval_set: str, eval_id: str, field_name: str, eval_sha256: str, level: str,
            record: dict[str, Any]) -> None:
        key = (eval_set, eval_id, field_name, level)
        finding = self.findings.setdefault(key, Finding(eval_set, eval_id, field_name, eval_sha256, level))
        finding.record_count += 1
        if len(finding.records) < self.max_records:
            finding.records.append(record)
        self.records_with_findings.add(record["record_index"])

    def visit(self, record_index: int, record_id: str, text: str) -> None:
        normalized = normalize(text)
        words = normalized.split()
        matched: dict[int, set[tuple[str, ...]]] = {}
        for size, table in self.index.items():
            for start in range(len(words) - size + 1):
                gram = tuple(words[start:start + size])
                for position in table.get(gram, ()):
                    matched.setdefault(position, set()).add(gram)
        padded = f" {normalized} "
        safe_id = record_id if SAFE_ID.fullmatch(record_id) else None
        text_sha256 = sha256_text(text)
        for position in sorted(matched):
            item = self.items[position]
            ratio = len(matched[position]) / len(item.grams)
            if ratio < self.threshold:
                continue
            if item.prompt in text:
                level = "exact_prompt"
            elif f" {item.normalized} " in padded:
                level = "normalized_prompt"
            else:
                level = "ngram_prompt"
            self.add(eval_set=item.eval_set, eval_id=item.eval_id, field_name="prompt",
                     eval_sha256=item.eval_sha256, level=level,
                     record={"record_index": record_index, "record_id": safe_id,
                             "record_sha256": text_sha256, "ngram_ratio": round(ratio, 4)})
        if self.function_pattern is not None:
            for name in sorted(set(self.function_pattern.findall(text))):
                for eval_set, eval_id in self.functions[name]:
                    self.add(eval_set=eval_set, eval_id=eval_id, field_name="function_name",
                             eval_sha256=sha256_text(name), level="function_definition",
                             record={"record_index": record_index, "record_id": safe_id,
                                     "record_sha256": text_sha256})

    def report_findings(self) -> list[dict[str, Any]]:
        ordered = sorted(self.findings.values(), key=lambda f: (f.eval_set, f.eval_id, f.field, LEVELS.index(f.level)))
        return [
            {
                "eval_set": finding.eval_set,
                "eval_id": finding.eval_id,
                "field": finding.field,
                "eval_sha256": finding.eval_sha256,
                "level": finding.level,
                "record_count": finding.record_count,
                "records": finding.records,
                "records_truncated": finding.record_count > len(finding.records),
            }
            for finding in ordered
        ]


RecordCheck = Callable[[dict[str, Any], int], None]


def scan_records(path: Path, *, context: str, check: RecordCheck, visit: Callable[[int, str, str], None]) -> tuple[str, int, int]:
    """Stream a JSONL file once: validate, visit and hash every record."""

    if path.is_symlink() or not path.is_file():
        raise CheckRefused(f"{context} must be a regular file")
    size = path.stat().st_size
    if not 1 <= size <= MAX_SOURCE_BYTES:
        raise CheckRefused(f"{context} size is outside the bounded range")
    digest = hashlib.sha256()
    total = 0
    count = 0
    record_ids: set[str] = set()
    with path.open("rb") as handle:
        line_number = 0
        while True:
            raw = handle.readline(MAX_LINE_BYTES + 2)
            if not raw:
                break
            line_number += 1
            total += len(raw)
            digest.update(raw)
            if total > MAX_SOURCE_BYTES:
                raise CheckRefused(f"{context} grew beyond the bounded size")
            if len(raw) > MAX_LINE_BYTES + 1:
                raise CheckRefused(f"{context} line {line_number} exceeds the line size limit")
            line = raw[:-1] if raw.endswith(b"\n") else raw
            if not line.strip():
                raise CheckRefused(f"{context} line {line_number} is blank")
            try:
                record = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise CheckRefused(f"{context} line {line_number} is not valid UTF-8 JSON") from error
            if not isinstance(record, dict):
                raise CheckRefused(f"{context} line {line_number} is not a JSON object")
            check(record, line_number)
            record_id, text = record.get("record_id"), record.get("text")
            if not isinstance(record_id, str) or not 1 <= len(record_id) <= 128:
                raise CheckRefused(f"{context} line {line_number} has an invalid record_id")
            if record_id in record_ids:
                raise CheckRefused(f"{context} line {line_number} repeats a record_id")
            if not isinstance(text, str) or not text:
                raise CheckRefused(f"{context} line {line_number} has an invalid text")
            record_ids.add(record_id)
            count += 1
            if count > MAX_RECORDS:
                raise CheckRefused(f"{context} holds too many records")
            visit(line_number, record_id, text)
    if total != size:
        raise CheckRefused(f"{context} changed while it was read")
    return digest.hexdigest(), total, count


def plain_record(context: str) -> RecordCheck:
    def check(record: dict[str, Any], line_number: int) -> None:
        if set(record) != PLAIN_RECORD_KEYS:
            raise CheckRefused(f"{context} line {line_number} must hold only record_id and text")
    return check


def candidate_record(record: dict[str, Any], line_number: int) -> None:
    if set(record) != CANDIDATE_RECORD_KEYS or record.get("schema_version") != CANDIDATE_RECORD_SCHEMA:
        raise CheckRefused(f"conversation candidate line {line_number} is not a {CANDIDATE_RECORD_SCHEMA} record")
    if not isinstance(record.get("record_id"), str) or SHA256.fullmatch(record["record_id"]) is None:
        raise CheckRefused(f"conversation candidate line {line_number} has an invalid record_id")


def check_arena_increment(directory: Path, scanner: Scanner) -> dict[str, Any]:
    require_directory(directory, "arena increment")
    manifest, payload = read_json_object(directory / "manifest.json", context="arena increment manifest")
    schema = manifest.get("schema_version")
    if schema not in ARENA_SCHEMAS:
        raise CheckRefused("arena increment manifest has an unknown schema")
    declared = require_sha256(manifest.get("content_sha256"), "arena increment content_sha256")
    declared_count = require_count(manifest.get("record_count"), "arena increment record_count")
    digest, _, count = scan_records(directory / "records.jsonl", context="arena increment records",
                                    check=plain_record("arena increment records"), visit=scanner.visit)
    if digest != declared:
        raise CheckRefused("records.jsonl does not match the manifest content_sha256")
    if count != declared_count:
        raise CheckRefused("records.jsonl does not match the manifest record_count")
    increment_id = manifest.get("increment_id")
    return {
        "kind": "arena-increment",
        "schema_version": schema,
        "increment_id": increment_id if isinstance(increment_id, str) and SAFE_ID.fullmatch(increment_id) else None,
        "manifest_sha256": sha256_bytes(payload),
        "content_sha256": digest,
        "record_count": count,
    }


def check_authorized_text(manifest_path: Path, split_path: Path, scanner: Scanner) -> dict[str, Any]:
    manifest, payload = read_json_object(manifest_path, context="training corpus manifest")
    try:
        validate_corpus_manifest(manifest)
    except ValueError as error:
        raise CheckRefused(f"training corpus manifest is invalid: {error}") from error
    digest, size, count = scan_records(split_path, context="corpus split",
                                       check=plain_record("corpus split"), visit=scanner.visit)
    declared = {name: split for name, split in manifest["splits"].items()}
    declared["materialization"] = manifest["materialization"]
    name = next((name for name, split in declared.items() if split["content_sha256"] == digest), None)
    if name is None:
        raise CheckRefused("the split matches no digest declared by the manifest")
    if declared[name]["byte_size"] != size or declared[name]["record_count"] != count:
        raise CheckRefused(f"the split does not match the manifest size or record count for {name}")
    return {
        "kind": "authorized-text",
        "corpus_id": manifest["corpus_id"],
        "manifest_sha256": sha256_bytes(payload),
        "split": name,
        "content_sha256": digest,
        "record_count": count,
    }


def check_conversation_candidates(directory: Path, scanner: Scanner) -> dict[str, Any]:
    require_directory(directory, "conversation candidate packet")
    manifest, payload = read_json_object(directory / CANDIDATE_MANIFEST_FILE, context="conversation candidate manifest")
    if manifest.get("schema_version") != CANDIDATE_MANIFEST_SCHEMA:
        raise CheckRefused("conversation candidate manifest has an unknown schema")
    if manifest.get("data_file") != CANDIDATE_DATA_FILE:
        raise CheckRefused(f"conversation candidate data_file must be {CANDIDATE_DATA_FILE}")
    declared = require_sha256(manifest.get("data_sha256"), "conversation candidate data_sha256")
    declared_count = require_count(manifest.get("record_count"), "conversation candidate record_count")
    digest, _, count = scan_records(directory / CANDIDATE_DATA_FILE, context="conversation candidates",
                                    check=candidate_record, visit=scanner.visit)
    if digest != declared:
        raise CheckRefused(f"{CANDIDATE_DATA_FILE} does not match the manifest data_sha256")
    if count != declared_count:
        raise CheckRefused(f"{CANDIDATE_DATA_FILE} does not match the manifest record_count")
    return {
        "kind": "conversation-candidates",
        "schema_version": CANDIDATE_MANIFEST_SCHEMA,
        "manifest_sha256": sha256_bytes(payload),
        "content_sha256": digest,
        "record_count": count,
    }


def check(source_kind: str, source_paths: tuple[Path, ...], *, e1_path: Path = DEFAULT_E1,
          e2_path: Path = DEFAULT_E2, ngram_size: int = DEFAULT_NGRAM_SIZE,
          ngram_threshold: float = DEFAULT_NGRAM_THRESHOLD,
          max_records_per_finding: int = DEFAULT_MAX_RECORDS_PER_FINDING) -> dict[str, Any]:
    """Return the content-free report; raise CheckRefused when the input cannot be trusted."""

    if type(ngram_size) is not int or not NGRAM_SIZE_RANGE[0] <= ngram_size <= NGRAM_SIZE_RANGE[1]:
        raise CheckRefused("ngram size is outside the bounded range")
    if not isinstance(ngram_threshold, float) or not math.isfinite(ngram_threshold) or not 0.0 < ngram_threshold <= 1.0:
        raise CheckRefused("ngram threshold must be in (0, 1]")
    low, high = MAX_RECORDS_PER_FINDING_RANGE
    if type(max_records_per_finding) is not int or not low <= max_records_per_finding <= high:
        raise CheckRefused("max records per finding is outside the bounded range")
    eval_sets = [load_e1(e1_path, ngram_size), load_e2(e2_path, ngram_size)]
    scanner = Scanner(eval_sets, threshold=ngram_threshold, max_records_per_finding=max_records_per_finding)
    if source_kind == "arena-increment" and len(source_paths) == 1:
        source = check_arena_increment(source_paths[0], scanner)
    elif source_kind == "authorized-text" and len(source_paths) == 2:
        source = check_authorized_text(source_paths[0], source_paths[1], scanner)
    elif source_kind == "conversation-candidates" and len(source_paths) == 1:
        source = check_conversation_candidates(source_paths[0], scanner)
    else:
        raise CheckRefused("unknown source kind or wrong number of source paths")
    findings = scanner.report_findings()
    return {
        "schema_version": REPORT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "evaluation_sets": [eval_set.describe() for eval_set in eval_sets],
        "parameters": {
            "normalization": "NFKC, casefold, non-alphanumeric runs as one space",
            "ngram_size": ngram_size,
            "ngram_threshold": ngram_threshold,
            "max_records_per_finding": max_records_per_finding,
        },
        "summary": {
            "contaminated": bool(findings),
            "finding_count": len(findings),
            "items_with_findings": len({(f["eval_set"], f["eval_id"]) for f in findings}),
            "records_with_findings": len(scanner.records_with_findings),
            "findings_by_level": {level: sum(1 for f in findings if f["level"] == level) for level in LEVELS},
        },
        "findings": findings,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--e1", type=Path, default=DEFAULT_E1, help="E1 language suite (default: the versioned candidate)")
    parser.add_argument("--e2", type=Path, default=DEFAULT_E2, help="E2 code suite (default: the versioned candidate)")
    parser.add_argument("--ngram-size", type=int, default=DEFAULT_NGRAM_SIZE,
                        help=f"word n-gram size, {NGRAM_SIZE_RANGE[0]}-{NGRAM_SIZE_RANGE[1]} (default {DEFAULT_NGRAM_SIZE})")
    parser.add_argument("--ngram-threshold", type=float, default=DEFAULT_NGRAM_THRESHOLD,
                        help=f"share of a prompt's n-grams found in one record that counts as overlap (default {DEFAULT_NGRAM_THRESHOLD})")
    parser.add_argument("--max-records-per-finding", type=int, default=DEFAULT_MAX_RECORDS_PER_FINDING,
                        help=f"records listed per finding; the total is always counted (default {DEFAULT_MAX_RECORDS_PER_FINDING})")
    sources = parser.add_subparsers(dest="source_kind", required=True, metavar="SOURCE")
    arena = sources.add_parser("arena-increment", help="RAW or VALIDATED arena corpus increment directory")
    arena.add_argument("increment_dir", type=Path)
    text = sources.add_parser("authorized-text", help="training corpus manifest (0.2.0) and one of its JSONL splits")
    text.add_argument("manifest", type=Path)
    text.add_argument("split_jsonl", type=Path)
    conversation = sources.add_parser("conversation-candidates", help="exported conversation learning-candidate directory")
    conversation.add_argument("candidate_dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.source_kind == "authorized-text":
        paths: tuple[Path, ...] = (args.manifest, args.split_jsonl)
    elif args.source_kind == "arena-increment":
        paths = (args.increment_dir,)
    else:
        paths = (args.candidate_dir,)
    try:
        report = check(args.source_kind, paths, e1_path=args.e1, e2_path=args.e2, ngram_size=args.ngram_size,
                       ngram_threshold=args.ngram_threshold, max_records_per_finding=args.max_records_per_finding)
    except (CheckRefused, OSError) as error:
        print(f"evaluation contamination check refused: {error}", file=sys.stderr)
        return EXIT_REFUSED
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return EXIT_OVERLAP if report["summary"]["contaminated"] else EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
