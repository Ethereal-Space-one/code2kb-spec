"""Run an actual SQLite FTS5 trigram query over an audited retrieval release.

This is an offline conformance probe, not a production indexing service.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

try:
    from .retrieval_audit import audit_in_release
    from .retrieval_model import read_unit, strict_json
except ImportError:
    from retrieval_audit import audit_in_release
    from retrieval_model import read_unit, strict_json


def probe(project: Path, release_id: str, audience: str, queries: list[str], top_k: int = 3) -> dict:
    if audience not in {"business", "engineering"} or not 1 <= top_k <= 20:
        raise ValueError("受众或 top-k 无效")
    release = project / "发布"
    audit_in_release(release, release_id, require_ready=False)
    manifest = strict_json(release / "检索清单" / f"{release_id}.json")
    rows = []
    for item in manifest["units"]:
        if item["audience"] != audience:
            continue
        meta, body = read_unit(project / item["path"])
        rows.append((meta["unit_id"], meta["topic"], body))
    rows.sort(key=lambda row: row[0])
    corpus = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE VIRTUAL TABLE units USING fts5(unit_id UNINDEXED, topic, body, tokenize='trigram')")
        connection.executemany("INSERT INTO units(unit_id, topic, body) VALUES (?, ?, ?)", rows)
        results = []
        for query in queries:
            if not query.strip():
                raise ValueError("检索词不能为空")
            hits = connection.execute(
                "SELECT unit_id, topic, bm25(units) FROM units WHERE units MATCH ? ORDER BY bm25(units), unit_id LIMIT ?",
                (query, top_k),
            ).fetchall()
            results.append({"query": query, "ranking": [{"rank": index + 1, "unit_id": unit_id,
                                                              "topic": topic, "score": score}
                                                             for index, (unit_id, topic, score) in enumerate(hits)]})
    finally:
        connection.close()
    return {"engine": "SQLite FTS5", "sqlite_version": sqlite3.sqlite_version,
            "tokenizer": "trigram", "indexed_fields": ["topic", "body"],
            "audience": audience, "release_id": release_id, "top_k": top_k,
            "unit_count": len(rows), "corpus_sha256": hashlib.sha256(corpus).hexdigest(), "queries": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--audience", choices=("business", "engineering"), default="business")
    parser.add_argument("--query", action="append", required=True)
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(probe(args.project, args.release_id, args.audience, args.query, args.top_k), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
