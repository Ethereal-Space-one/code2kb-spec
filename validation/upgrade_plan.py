"""Read-only, conservative upgrade planning over the existing source preview."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _file_digest(path: Path) -> str | None:
    return _digest(path.read_bytes()) if path.is_file() else None


def _tree_digest(root: Path) -> str:
    rows = [(path.relative_to(root).as_posix(), _digest(path.read_bytes()))
            for path in root.rglob("*") if path.is_file()]
    return _digest(_canonical(sorted(rows)))


def _matching_digest(root: Path, name: str) -> str:
    rows = [(path.relative_to(root).as_posix(), _digest(path.read_bytes()))
            for path in root.rglob(name) if path.is_file()]
    return _digest(_canonical(sorted(rows)))


def _git_baseline(project: Path) -> tuple[str | None, bool]:
    head = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"],
                          text=True, capture_output=True)
    if head.returncode:
        return None, True
    state = subprocess.run(["git", "-C", str(project), "status", "--porcelain", "--untracked-files=all"],
                           text=True, capture_output=True)
    return head.stdout.strip(), bool(state.returncode or state.stdout)


def _release_inputs(project: Path) -> dict[str, str | None]:
    release = project / "发布"
    pointer = release / "当前版本.json"
    result = {"pointer_sha256": _file_digest(pointer), "registry_sha256": None,
              "relation_pointer_sha256": _file_digest(release / "当前关系版本.json")}
    if pointer.is_file():
        try:
            value = json.loads(pointer.read_text(encoding="utf-8"))
            release_id = value.get("release_id")
            if isinstance(release_id, str) and release_id and "/" not in release_id:
                result["registry_sha256"] = _file_digest(release / "版本清单" / f"{release_id}.json")
        except (UnicodeError, ValueError):
            pass
    return result


def _migration_scope(project: Path, source: Path, preview: dict, docs: list, relations: dict,
                     full_project_review: bool) -> dict:
    """Expose the global write set even when semantic review selects one module."""
    source_name = source.relative_to(project).as_posix()
    repository_id = preview["repository_id"]
    changed = {row["path"] for row in preview["changed_files"]}
    by_module: dict[str, dict] = {}
    for doc in docs:
        module_id = doc.module_id
        if not module_id:
            continue
        row = by_module.setdefault(module_id, {"module_id": module_id, "source_revision_files": [],
                                               "review_reset_files": [], "manifest_files": [],
                                               "relation_file": None, "evidence_records_requiring_review": 0,
                                               "evidence_records_rebuildable": 0})
        local = f"{source_name}/{doc.relative.as_posix()}"
        revisions = doc.meta.get("source_revisions", "")
        if f"{repository_id}=" in revisions:
            row["source_revision_files"].append(local)
        if doc.meta.get("review_status") in {"reviewed", "policy_reviewed"}:
            row["review_reset_files"].append(local)
        if doc.doc_type == "release_manifest":
            row["manifest_files"].append(local)
        if doc.doc_type == "spec":
            relation_path = source / doc.relative.parent / "关系映射.json"
            if relation_path.is_file():
                row["relation_file"] = relation_path.relative_to(project).as_posix()
    for module_id, relation in relations.items():
        row = by_module.get(module_id)
        if row is None:
            continue
        data = relation["data"]
        records = [record for node in data.get("nodes", []) for record in node.get("evidence", [])]
        records += [record for link in relation["links"] for record in link.get("evidence", [])]
        for record in records:
            if record["repository_id"] != repository_id:
                continue
            key = "evidence_records_requiring_review" if record["path"] in changed else "evidence_records_rebuildable"
            row[key] += 1
    modules = []
    for row in by_module.values():
        for key in ("source_revision_files", "review_reset_files", "manifest_files"):
            row[key].sort()
        row["semantic_review_required"] = full_project_review or row["module_id"] in preview["possible_modules"]
        modules.append(row)
    return {"global_write_set": ["知识库配置.json", f"{source_name}/功能大纲.md"],
            "modules": sorted(modules, key=lambda row: row["module_id"]),
            "status": "read_only_proposal_not_applied",
            "approval_rule": "all_changed_packages_require_new_explicit_review"}


def build(project: Path, source: Path, preview: dict, docs: list, relations: dict) -> dict:
    """Describe a review candidate; never mutate the project or authorize execution."""
    head, dirty = _git_baseline(project)
    snapshot = {
        "knowledge_git_head": head,
        "knowledge_worktree_dirty": dirty,
        "config_sha256": _file_digest(project / "知识库配置.json"),
        "source_tree_sha256": _tree_digest(source),
        "relations_sha256": _matching_digest(source, "关系映射.json"),
        "approval_manifests_sha256": _matching_digest(source, "发布清单.md"),
        **_release_inputs(project),
    }
    reasons = []
    if head is None:
        reasons.append("knowledge_git_baseline_missing")
    if dirty:
        reasons.append("knowledge_worktree_dirty")
    if preview["unattributed_paths"]:
        reasons.append("unattributed_changed_paths")
    if preview["explicit_exclusions"]:
        reasons.append("manual_exclusions_are_not_proof")
    if preview["adapter"]["unresolved"]:
        reasons.append("adapter_unresolved")
    if preview["needs_evidence"]:
        reasons.append("unverified_relation")
    if any(item["status"] != "M" for item in preview["changed_files"]):
        reasons.append("added_deleted_or_type_changed_path")
    if not preview["changed_files"]:
        reasons.append("no_change_is_not_approval")
    uncertain = [item["path"] for item in preview["changed_files"]
                 if item["coverage"] != "verified_evidence_changed"]
    if uncertain:
        reasons.append("changed_paths_lack_verified_evidence")
    selected = preview["possible_modules"] if not reasons else []
    if not selected and not reasons:
        reasons.append("no_attributed_modules")
    result = {
        "schema_version": "1.0",
        "kind": "source_upgrade_review_plan",
        "repository_id": preview["repository_id"],
        "old_commit": preview["old_commit"],
        "proposed_commit": preview["proposed_commit"],
        "input_snapshot": snapshot,
        "decision": "selected_modules" if selected else "full_project_review",
        "selected_modules": selected,
        "fallback_reasons": sorted(set(reasons)),
        "changed_paths": [{"path": item["path"], "status": item["status"],
                           "coverage": item["coverage"], "modules": item["modules"]}
                          for item in preview["changed_files"]],
        "must_review_facts": preview["must_review_facts"],
        "affected_topics": preview["affected_topics"],
        "published_unit_ids": preview["published_unit_ids"],
        "needs_evidence": preview["needs_evidence"],
        "baseline_migration": _migration_scope(project, source, preview, docs, relations, not bool(selected)),
        "execution_gate": "baseline_migration_and_explicit_review_required",
        "note": "只读候选计划；未选模块仍需迁移固定提交与证据，旧批准不得自动继承。",
    }
    result["plan_sha256"] = _digest(_canonical(result))
    return result
