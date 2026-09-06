"""Build a lexical provenance index from operator-approved Markdown documents."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from services.knowledge.hybrid_index import HybridKnowledgeIndex


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-directory", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    source = args.source_directory.resolve()
    if not source.is_dir():
        raise SystemExit("source directory is invalid")
    index = HybridKnowledgeIndex(args.database)
    index.initialize()
    count = 0
    for path in sorted(source.rglob("*.md")):
        content = path.read_text(encoding="utf-8")
        if not content.strip():
            continue
        relative = path.relative_to(source).as_posix()
        title = next((line[2:].strip() for line in content.splitlines() if line.startswith("# ")), relative)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        index.upsert_validated(
            document_id=f"project:{relative}",
            title=title[:500],
            content=content,
            provenance_id=f"project-sha256:{digest}",
            embedding=None,
        )
        count += 1
    print(f"indexed_documents={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
