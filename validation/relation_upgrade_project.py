"""Read-only, conservative project-wide preview for a proposed source commit."""

from __future__ import annotations

import re

try:
    from .evidence_snapshot import EvidenceError, git, parse_anchor, safe_path, snapshot, verify
    from .relation_model import RelationError
except ImportError:
    from evidence_snapshot import EvidenceError, git, parse_anchor, safe_path, snapshot, verify
    from relation_model import RelationError


def _blob(repo: str, commit: str, path: str) -> str | None:
    rows = [part for part in git(repo, "ls-tree", "-z", commit, "--", path).split(b"\0") if part]
    if not rows:
        return None
    if len(rows) != 1:
        raise RelationError("源码差异路径不是唯一 Git 对象")
    try:
        descriptor, listed = rows[0].split(b"\t", 1)
        mode, kind, oid = descriptor.decode("ascii").split(" ")
        actual = listed.decode("utf-8")
    except (UnicodeError, ValueError) as exc:
        raise RelationError("源码差异 Git 对象无效") from exc
    if actual != path or mode not in {"100644", "100755"} or kind != "blob":
        return None
    return oid


def changed_paths(repository: dict, new_commit: str) -> tuple[str, str, list[dict]]:
    repo = repository["path"]
    try:
        old = git(repo, "rev-parse", "--verify", f"{repository['commit']}^{{commit}}").decode("ascii").strip()
        new = git(repo, "rev-parse", "--verify", f"{new_commit}^{{commit}}").decode("ascii").strip()
        raw = git(repo, "diff", "--no-ext-diff", "--no-renames", "--name-status", "-z", old, new)
    except (EvidenceError, KeyError, UnicodeError) as exc:
        raise RelationError("升级预览的固定提交无法读取") from exc
    tokens = raw.split(b"\0")
    if tokens[-1:] == [b""]:
        tokens.pop()
    if len(tokens) % 2:
        raise RelationError("源码差异列表结构无效")
    files = []
    for index in range(0, len(tokens), 2):
        try:
            status, path = tokens[index].decode("ascii"), tokens[index + 1].decode("utf-8")
        except UnicodeError as exc:
            raise RelationError("源码差异路径不是 UTF-8") from exc
        if status not in {"A", "M", "D", "T"} or not safe_path(path):
            raise RelationError("源码差异状态或路径不受支持")
        files.append({"status": status, "path": path,
                      "old_blob_oid": _blob(repo, old, path), "new_blob_oid": _blob(repo, new, path)})
    return old, new, sorted(files, key=lambda item: item["path"])


def _anchors(value: str, repository_id: str):
    for candidate in re.split(r"[,，]\s*", value):
        try:
            role, path, _, _ = parse_anchor(candidate.strip())
        except EvidenceError:
            continue
        if role == repository_id:
            yield path


def _new_evidence(record: dict, proposed: dict) -> str:
    anchor = f"{record['repository_id']}:{record['path']}:{record['line_start']}-{record['line_end']}"
    try:
        newer = snapshot(anchor, proposed)
    except EvidenceError:
        return "missing_or_unreadable"
    return "unchanged_excerpt" if newer["snippet_sha256"] == record["snippet_sha256"] else "changed_excerpt"


def _relocation_lines(record: dict, repository: dict, new_blob: str | None) -> list[int]:
    """Offer exact-text line candidates; never transfer a verified identity."""
    if not new_blob:
        return []
    repo = repository["path"]
    old = git(repo, "cat-file", "blob", record["blob_oid"])
    new = git(repo, "cat-file", "blob", new_blob)
    needle = old.splitlines(keepends=True)[record["line_start"] - 1:record["line_end"]]
    lines = new.splitlines(keepends=True)
    if not needle:
        return []
    return [index + 1 for index in range(len(lines) - len(needle) + 1)
            if lines[index:index + len(needle)] == needle][:8]


def _new_file_candidates(repository_id: str, proposed: dict, paths: list[str]) -> tuple[str, list[dict], list[dict]]:
    try:
        from .adapters import get_adapter
    except ImportError:
        from adapters import get_adapter
    adapter = get_adapter("builtin-mixed")
    discoveries = []
    unresolved = []
    # Large upgrades require a separate scoped inventory; never silently drop files.
    for path in paths[:32]:
        try:
            result = adapter.scan(repository_id, proposed[repository_id], scope=path)
        except (ValueError, EvidenceError) as exc:
            unresolved.append({"path": path, "reason": "adapter_scan_failed", "detail": str(exc)})
            continue
        candidates = result["candidates"]
        if not candidates:
            unresolved.append({"path": path, "reason": "adapter_no_candidate", "detail": result["coverage"]["skipped"]})
        for item in candidates:
            discoveries.append({"path": path, "kind": item["kind"], "language": item["language"],
                                "capability": item["capability"], "status": item["status"],
                                "anchor": item["anchor"]})
    unresolved.extend({"path": path, "reason": "adapter_scan_limit", "detail": "单次预览最多扫描 32 个新增路径"}
                      for path in paths[32:])
    return adapter.name, sorted(discoveries, key=lambda item: (item["path"], item["anchor"], item["kind"])), unresolved


def preview_project(relations: dict[str, dict], facts: dict[str, list[dict]], entries: list[tuple],
                    repositories: dict, repository_id: str, new_commit: str,
                    topic_units: dict[str, list[str]] | None = None,
                    exclusions: dict[str, str] | None = None) -> dict:
    """Locate review work, never claim an incomplete graph proves no impact."""
    if repository_id not in repositories:
        raise RelationError("升级预览仓库 ID 未配置")
    old, new, files = changed_paths(repositories[repository_id], new_commit)
    changed = {item["path"]: item for item in files}
    exclusions = exclusions or {}
    if any(path not in changed or not safe_path(path) or not isinstance(reason, str) or not reason.strip()
           for path, reason in exclusions.items()):
        raise RelationError("明确排除必须对应变化路径并填写原因")
    proposed = {key: dict(value) for key, value in repositories.items()}
    proposed[repository_id]["commit"] = new
    adapter_name, added_candidates, adapter_unresolved = _new_file_candidates(
        repository_id, proposed, [item["path"] for item in files if item["status"] == "A" and item["path"] not in exclusions])
    relocation_candidates = []
    added_by_blob = {}
    for item in files:
        if item["status"] == "A" and item["new_blob_oid"]:
            added_by_blob.setdefault(item["new_blob_oid"], []).append(item["path"])
    for item in files:
        if item["status"] == "D" and item["old_blob_oid"] in added_by_blob:
            relocation_candidates.extend({"old_path": item["path"], "new_path": target,
                                          "basis": "identical_blob_only", "status": "candidate"}
                                         for target in added_by_blob[item["old_blob_oid"]])
    modules_by_path: dict[str, set[str]] = {}
    changed_nodes: set[tuple[str, str]] = set()
    possible_nodes: set[tuple[str, str]] = set()
    possible_modules: set[str] = set()
    evidence_results = []
    fact_documents: dict[str, set[str]] = {}
    for module_id, rows in facts.items():
        for row in rows:
            key = f"{module_id}#{row['fact_id']}"
            fact_documents[key] = set(row.get("documents", []))
            for path in _anchors(row.get("anchors", ""), repository_id):
                modules_by_path.setdefault(path, set()).add(module_id)
                if path in changed:
                    possible_modules.add(module_id)
                    possible_nodes.add(("fact", key))
    for row in entries:
        if len(row) < 5:
            continue
        for path in _anchors(row[4], repository_id):
            modules_by_path.setdefault(path, set()).add(row[3])
            if path in changed:
                possible_modules.add(row[3])
                possible_nodes.add(("entry", f"{row[3]}#{row[0]}"))
    def endpoint(module_id, link, end):
        value = link[end + "_id"]
        return (link[end + "_type"], value if "#" in value else f"{module_id}#{value}")

    verified_links = []
    pending_links = []
    node_results = []
    for module_id, data in sorted(relations.items()):
        for node in data.get("nodes", []):
            for record in node["evidence"]:
                if record["repository_id"] != repository_id:
                    continue
                verify(record, repositories)
                path = record["path"]
                modules_by_path.setdefault(path, set()).add(module_id)
                if path not in changed:
                    continue
                possible_nodes.add((node["kind"], f"{module_id}#{node['node_id']}"))
                outcome = _new_evidence(record, proposed)
                node_results.append({"module_id": module_id, "kind": node["kind"],
                                     "node_id": node["node_id"], "source_path": path,
                                     "line_start": record["line_start"], "line_end": record["line_end"],
                                     "outcome": outcome,
                                     "relocation_line_candidates": (
                                         _relocation_lines(record, proposed[repository_id], changed[path]["new_blob_oid"])
                                         if outcome != "unchanged_excerpt" else [])})
                if outcome != "unchanged_excerpt":
                    changed_nodes.add((node["kind"], f"{module_id}#{node['node_id']}"))
        for link in data["links"]:
            if link["status"] == "verified":
                verified_links.append((module_id, link))
            else:
                pending_links.append((module_id, link))
            for record in link["evidence"]:
                if record["repository_id"] != repository_id:
                    continue
                verify(record, repositories)
                path = record["path"]
                modules_by_path.setdefault(path, set()).add(module_id)
                if path not in changed:
                    continue
                possible_nodes.update(endpoint(module_id, link, end) for end in ("from", "to"))
                outcome = _new_evidence(record, proposed)
                evidence_results.append({
                    "module_id": module_id, "from_type": link["from_type"], "from_id": link["from_id"],
                    "to_type": link["to_type"], "to_id": link["to_id"], "status": link["status"],
                    "source_path": path, "line_start": record["line_start"],
                    "line_end": record["line_end"], "outcome": outcome,
                    "relocation_line_candidates": (
                        _relocation_lines(record, proposed[repository_id], changed[path]["new_blob_oid"])
                        if outcome != "unchanged_excerpt" else []),
                })
                if outcome != "unchanged_excerpt":
                    possible_modules.add(module_id)
                    if link["status"] == "verified":
                        for end in ("from", "to"):
                            changed_nodes.add(endpoint(module_id, link, end))
    # A changed file can affect unlinked behavior even if an old excerpt is unchanged.
    affected_nodes = set(changed_nodes)
    while True:
        reached = {endpoint(module_id, link, "to") for module_id, link in verified_links
                   if endpoint(module_id, link, "from") in affected_nodes}
        if reached <= affected_nodes:
            break
        affected_nodes.update(reached)
    affected_facts = {value for kind, value in affected_nodes if kind == "fact"}
    topics = {value for kind, value in affected_nodes if kind == "topic"}
    # An old snippet staying equal does not exclude changes elsewhere in its file.
    # Follow possible consumers too, but never promote them into must-review facts.
    possible_nodes.update(affected_nodes)
    while True:
        reached = {endpoint(module_id, link, "to") for module_id, link in verified_links + pending_links
                   if endpoint(module_id, link, "from") in possible_nodes}
        if reached <= possible_nodes:
            break
        possible_nodes.update(reached)
    possible_modules.update(value.split("#", 1)[0] for _, value in possible_nodes)
    needs_evidence = []
    for module_id, link in pending_links:
        if (endpoint(module_id, link, "from") in possible_nodes
                or any(record["repository_id"] == repository_id and record["path"] in changed
                       for record in link["evidence"])):
            possible_modules.add(module_id)
            needs_evidence.append({"module_id": module_id,
                                   **{key: link[key] for key in ("from_type", "from_id", "to_type", "to_id", "status")},
                                   "reason": "unverified_relation_requires_evidence"})
    units = topic_units or {}
    impact = []
    for fact in sorted(affected_facts):
        impact.append({"fact_id": fact, "documents": sorted(fact_documents.get(fact, set()))})
    path_report = []
    unattributed = []
    excluded = []
    for file in files:
        path = file["path"]
        attached = sorted(modules_by_path.get(path, set()))
        possible_modules.update(attached)
        records = [item for item in evidence_results if item["source_path"] == path]
        if path in exclusions:
            if attached:
                raise RelationError("已有模块或证据关联的路径不能直接排除")
            coverage = "explicitly_excluded"
            excluded.append({"path": path, "reason": exclusions[path]})
        elif not attached:
            coverage = "unattributed"
            unattributed.append(path)
        elif (any(item["status"] == "verified" and item["outcome"] != "unchanged_excerpt" for item in records)
              or any(item["source_path"] == path and item["outcome"] != "unchanged_excerpt" for item in node_results)):
            coverage = "verified_evidence_changed"
        elif records:
            coverage = "relation_evidence_unchanged_or_unverified"
        else:
            coverage = "module_anchor_without_verified_relation"
        path_report.append({**file, "modules": attached, "coverage": coverage,
                            "exclusion_reason": exclusions.get(path)})
    return {
        "schema_version": "0.2", "repository_id": repository_id, "old_commit": old,
        "proposed_commit": new, "changed_files": path_report,
        "changed_evidence": sorted(evidence_results, key=lambda item: (item["module_id"], item["source_path"], item["line_start"], item["from_id"])),
        "changed_node_evidence": sorted(node_results, key=lambda item: (item["module_id"], item["source_path"], item["node_id"], item["line_start"])),
        "needs_evidence": sorted(needs_evidence, key=lambda item: (item["module_id"], item["from_type"], item["from_id"], item["to_id"])),
        "relocation_candidates": sorted(relocation_candidates, key=lambda item: (item["old_path"], item["new_path"])),
        "adapter": {"name": adapter_name, "capability_limit": "candidate_discovery_only",
                    "added_file_candidates": added_candidates, "unresolved": adapter_unresolved},
        "must_review_facts": impact, "affected_topics": sorted(topics),
        "published_unit_ids": sorted({unit for topic in topics for unit in units.get(topic, [])}),
        "possible_modules": sorted(possible_modules), "unattributed_paths": unattributed,
        "explicit_exclusions": sorted(excluded, key=lambda item: item["path"]),
        "fallback": "full_project_review" if unattributed else ("module_review" if possible_modules else "none_observed"),
        "coverage": "partial_source_mapping" if files else "no_source_changes",
        "note": "只读影响预览；未归类路径、未证实关系和隐含调用不能由空影响列表排除",
    }
