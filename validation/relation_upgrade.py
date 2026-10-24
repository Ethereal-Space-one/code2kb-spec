"""Read-only preview of relation evidence against a proposed new Git commit."""

from __future__ import annotations

try:
    from .evidence_snapshot import EvidenceError, snapshot, verify
    from . import relation_model
except ImportError:
    from evidence_snapshot import EvidenceError, snapshot, verify
    import relation_model


def preview(data: dict, repositories: dict, repository_id: str, new_commit: str) -> dict:
    if repository_id not in repositories:
        raise relation_model.RelationError("升级预览仓库 ID 未配置")
    proposed = {key: dict(value) for key, value in repositories.items()}
    proposed[repository_id]["commit"] = new_commit
    changed = []
    affected_facts = set()
    for link in data["links"]:
        for record in link["evidence"]:
            if record["repository_id"] != repository_id:
                continue
            verify(record, repositories)
            anchor = f"{repository_id}:{record['path']}:{record['line_start']}-{record['line_end']}"
            try:
                newer = snapshot(anchor, proposed)
            except EvidenceError:
                outcome = "missing_or_unreadable"
                newer = None
            else:
                outcome = "unchanged_excerpt" if newer["snippet_sha256"] == record["snippet_sha256"] else "changed_excerpt"
            if newer != record:
                changed.append({
                    "from_type": link["from_type"], "from_id": link["from_id"],
                    "to_type": link["to_type"], "to_id": link["to_id"],
                    "old_anchor": anchor, "outcome": outcome,
                    "old_blob_oid": record["blob_oid"], "new_blob_oid": newer["blob_oid"] if newer else None,
                })
                if link["from_type"] == "fact":
                    affected_facts.add(link["from_id"])
                if link["to_type"] == "fact":
                    affected_facts.add(link["to_id"])
    topics = {link["to_id"] for link in data["links"] if link["from_type"] == "fact" and link["to_type"] == "topic" and link["from_id"] in affected_facts}
    return {
        "schema_version": "0.1", "module_id": data["module_id"], "repository_id": repository_id,
        "old_commit": repositories[repository_id]["commit"], "proposed_commit": new_commit,
        "changed_evidence": sorted(changed, key=lambda item: (item["from_type"], item["from_id"], item["old_anchor"])),
        "affected_fact_ids": sorted(affected_facts), "affected_topic_ids": sorted(topics),
        "coverage": "explicit_relation_evidence_only",
        "note": "仅预览显式关系证据；未归类路径与隐含调用需另行取证，不能自动迁移为已证实",
    }
