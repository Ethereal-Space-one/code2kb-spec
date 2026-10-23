"""Read-only evidence lookup from the audited current retrieval release."""

from __future__ import annotations

from pathlib import Path

try:
    from .retrieval_evaluate import lexical, load_units
    from .retrieval_model import RetrievalError, digest, strict_json
except ImportError:
    from retrieval_evaluate import lexical, load_units
    from retrieval_model import RetrievalError, digest, strict_json


def query_current(project: Path, query: str, audience: str, top_k: int, core) -> dict:
    if not isinstance(query, str) or not query.strip() or len(query) > 1000:
        raise RetrievalError("查询文本须为 1–1000 个字符")
    if audience not in {"business", "engineering"} or type(top_k) is not int or not 1 <= top_k <= 20:
        raise RetrievalError("检索受众或 top-k 无效")
    try:
        from .governance import Governance
        from .retrieval_audit import audit_in_release
    except ImportError:
        from governance import Governance
        from retrieval_audit import audit_in_release

    release = project / "发布"
    base = Governance(project, project / "知识源", {}, [], None, core).audit_release(None)
    release_id = base["release_id"]
    audit_in_release(release, release_id, require_ready=True)
    manifest_path = release / "检索清单" / f"{release_id}.json"
    manifest = strict_json(manifest_path)
    units = load_units(release, manifest)
    allowed = [unit for unit in units.values() if audience == "engineering" or unit["meta"]["audience"] == "business"]
    ranked = lexical(query.strip(), allowed, top_k)
    hits = []
    for rank, unit_id in enumerate(ranked, start=1):
        unit = units[unit_id]
        meta, entry = unit["meta"], unit["entry"]
        base_view = "业务版" if meta["audience"] == "business" else "研发版"
        hits.append({
            "rank": rank,
            "unit_id": unit_id,
            "module_id": meta["module_id"],
            "audience": meta["audience"],
            "topic": meta["topic"],
            "unit_path": entry["path"],
            "source_paths": [f"发布/{base_view}/{path}" for path in entry["source_documents"]],
            "text": unit["body"],
        })
    return {
        "schema_version": "0.1",
        "release_id": release_id,
        "base_registry_sha256": manifest["base_registry_sha256"],
        "retrieval_manifest_sha256": digest(manifest_path.read_bytes()),
        "audience": audience,
        "query": query.strip(),
        "retriever_id": "lexical-v1",
        "answerability": "not_assessed",
        "hits": hits,
    }
