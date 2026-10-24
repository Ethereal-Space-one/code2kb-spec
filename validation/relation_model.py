"""Optional, reviewed relations between existing knowledge IDs and retrieval topics."""

from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
import re

try:
    from .evidence_snapshot import EvidenceError, verify as verify_evidence
except ImportError:
    from evidence_snapshot import EvidenceError, verify as verify_evidence


SCHEMA = "0.1"
SOURCE_FIELDS = {"schema_version", "module_id", "topics", "nodes", "links", "identity_history"}
TOPIC_FIELDS = {"topic_id", "audience", "source_document", "source_heading"}
NODE_FIELDS = {"node_id", "kind", "label", "evidence"}
LINK_FIELDS = {"from_type", "from_id", "to_type", "to_id", "status", "evidence", "reviewed_by", "reviewed_at"}
HISTORY_FIELDS = {"old_id", "new_ids", "reason"}
ID = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*\Z")
MODULE = re.compile(r"[a-z][a-z0-9_.-]*\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
KINDS = {"entry", "interface", "method", "event", "task", "config", "field", "fact", "topic"}
EDGES = {
    ("entry", "interface"), ("interface", "method"), ("method", "fact"),
    ("fact", "topic"), ("event", "method"), ("task", "method"),
    ("config", "fact"), ("field", "fact"),
}
STATUSES = {"verified", "candidate", "unresolved"}


class RelationError(ValueError):
    pass


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def strict_object(raw: bytes) -> dict:
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise RelationError(f"关系映射包含重复字段：{key}")
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RelationError("关系映射不是有效 UTF-8 JSON") from exc
    if not isinstance(value, dict) or set(value) != SOURCE_FIELDS or value["schema_version"] != SCHEMA:
        raise RelationError("关系映射字段或版本无效")
    return value


def mapping_path(source: Path, spec) -> Path:
    return source / spec.relative.parent / "关系映射.json"


def load(source: Path, spec) -> tuple[dict, bytes] | None:
    path = mapping_path(source, spec)
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise RelationError("关系映射文件无效、过大或为符号链接")
    raw = path.read_bytes()
    data = strict_object(raw)
    if data["module_id"] != spec.module_id:
        raise RelationError("关系映射 module_id 与结构化规格不一致")
    return data, raw


def catalog(core, spec, outline) -> tuple[dict[str, set[str]], dict[tuple[str, str, str, str], dict], dict[str, str]]:
    """Import existing IDs as candidates; old row presence never proves a relation."""
    entries = {row[0] for row in outline.entries if row[3] == spec.module_id}
    facts = {row[0] for row in core.table_rows(spec.body, "## 入口与调用链", "| fact_id | 单一结论与条件 | 证据等级 | 固定提交锚点 | 影响的知识文件 |")}
    actions = core.table_rows(spec.body, "## 入口与接口", "| entry_id | api_id | 调用条件 | 证据 |")
    apis = core.table_rows(spec.body, "## 接口契约", "| api_id | 接口标识 | 调用方 | 服务入口 | 主处理方法 | 证据 |")
    methods = core.table_rows(spec.body, "## 方法职责", "| method_id | 符号 | 职责 | 关键性 | 关联接口 | 源码锚点 |")
    matches = core.table_rows(spec.body, "## 调用匹配", "| api_id | 匹配状态 | 调用方证据 | 服务方证据 | 部署配对 | 差异或边界 |")
    match_status = {row[0]: row[1] for row in matches}
    api_ids = {row[0] for row in apis}
    method_ids = {row[0] for row in methods}
    known = {"entry": entries, "interface": api_ids, "method": method_ids, "fact": facts}
    derived = {}
    for entry_id, api_id, *_ in actions:
        key = ("entry", entry_id, "interface", api_id)
        status = "unresolved" if match_status.get(api_id) in {"未匹配", "外部依赖"} else "candidate"
        derived[key] = {"from_type": key[0], "from_id": key[1], "to_type": key[2], "to_id": key[3], "status": status, "evidence": [], "reviewed_by": "", "reviewed_at": ""}
    for api_id, _, _, _, linked, _ in apis:
        if linked == "无":
            continue
        for method_id in (item.strip() for item in linked.split(",")):
            key = ("interface", api_id, "method", method_id)
            status = "unresolved" if match_status.get(api_id) in {"未匹配", "外部依赖"} else "candidate"
            derived[key] = {"from_type": key[0], "from_id": key[1], "to_type": key[2], "to_id": key[3], "status": status, "evidence": [], "reviewed_by": "", "reviewed_at": ""}
    return known, derived, match_status


def validate(data: dict, *, known: dict[str, set[str]], module_dir: Path, repositories: dict) -> None:
    if not isinstance(data["topics"], list) or not isinstance(data["nodes"], list) or not isinstance(data["links"], list) or not isinstance(data["identity_history"], list):
        raise RelationError("关系主题、连接和身份历史须为列表")
    known = {kind: set(values) for kind, values in known.items()}
    for node in data["nodes"]:
        if not isinstance(node, dict) or set(node) != NODE_FIELDS or not isinstance(node["kind"], str) or node["kind"] not in {"event", "task", "config", "field"}:
            raise RelationError("扩展节点字段或类型无效")
        node_id = node["node_id"]
        if not isinstance(node_id, str) or not ID.fullmatch(node_id) or node_id in known.get(node["kind"], set()) or not isinstance(node["label"], str) or not node["label"].strip() or not isinstance(node["evidence"], list) or not node["evidence"]:
            raise RelationError("扩展节点身份、标签或证据无效")
        for record in node["evidence"]:
            try:
                verify_evidence(record, repositories)
            except EvidenceError as exc:
                raise RelationError(f"扩展节点证据无法重建：{exc}") from exc
        known.setdefault(node["kind"], set()).add(node_id)
    topics = set()
    for topic in data["topics"]:
        if not isinstance(topic, dict) or set(topic) != TOPIC_FIELDS:
            raise RelationError("关系主题字段无效")
        topic_id = topic["topic_id"]
        if not isinstance(topic_id, str) or not topic_id.startswith("topic.") or not ID.fullmatch(topic_id) or topic_id in topics:
            raise RelationError("主题 ID 无效或重复")
        if not isinstance(topic["audience"], str) or topic["audience"] not in {"business", "engineering"}:
            raise RelationError("主题受众无效")
        name = topic["source_document"]
        if not isinstance(name, str) or "/" in name or "\\" in name or name in {".", ".."} or not name.endswith(".md"):
            raise RelationError("主题来源文档路径无效")
        path = module_dir / name
        if path.is_symlink() or not path.is_file():
            raise RelationError("主题来源文档缺失或为符号链接")
        heading = topic["source_heading"]
        if not isinstance(heading, str) or not heading.strip() or not re.search(rf"(?m)^#{{2,4}} {re.escape(heading)}\s*$", path.read_text(encoding="utf-8")):
            raise RelationError("主题来源标题不存在")
        topics.add(topic_id)
    known["topic"] = topics
    seen = set()
    for link in data["links"]:
        if not isinstance(link, dict) or set(link) != LINK_FIELDS:
            raise RelationError("关系连接字段无效")
        if any(not isinstance(link[key], str) for key in ("from_type", "from_id", "to_type", "to_id", "status", "reviewed_by", "reviewed_at")):
            raise RelationError("关系连接身份或状态类型无效")
        pair = (link["from_type"], link["to_type"])
        if pair not in EDGES:
            raise RelationError("关系连接类型无效")
        source_id, target_id = link["from_id"], link["to_id"]
        if "#" in source_id or "#" in target_id:
            if pair != ("fact", "topic") or "#" not in source_id or "#" in target_id:
                raise RelationError("跨模块身份仅能用于事实到主题的连接")
        if source_id not in known.get(pair[0], set()) or target_id not in known.get(pair[1], set()):
            raise RelationError("关系连接引用未知身份")
        key = (*pair, source_id, target_id)
        if key in seen:
            raise RelationError("关系连接重复")
        seen.add(key)
        if link["status"] not in STATUSES or not isinstance(link["evidence"], list):
            raise RelationError("关系状态或证据格式无效")
        if link["status"] == "verified":
            if not link["evidence"] or not isinstance(link["reviewed_by"], str) or not link["reviewed_by"].strip():
                raise RelationError("已证实关系缺少固定证据或复核身份")
            try:
                date.fromisoformat(link["reviewed_at"])
            except (ValueError, TypeError) as exc:
                raise RelationError("已证实关系缺少复核日期") from exc
        elif link["reviewed_by"] or link["reviewed_at"]:
            raise RelationError("候选或未解关系不能带已证实复核标记")
        for record in link["evidence"]:
            try:
                verify_evidence(record, repositories)
            except EvidenceError as exc:
                raise RelationError(f"关系证据无法从固定提交重建：{exc}") from exc
    replaced = set()
    active_ids = set().union(*known.values()) if known else set()
    for item in data["identity_history"]:
        if not isinstance(item, dict) or set(item) != HISTORY_FIELDS or not isinstance(item["old_id"], str) or not ID.fullmatch(item["old_id"]) or item["old_id"] in replaced:
            raise RelationError("身份历史无效或重复")
        replaced.add(item["old_id"])
        new_ids = item["new_ids"]
        if not isinstance(new_ids, list) or not new_ids or any(not isinstance(value, str) or not ID.fullmatch(value) or value not in active_ids or value == item["old_id"] for value in new_ids) or len(new_ids) != len(set(new_ids)) or item["old_id"] in active_ids or not isinstance(item["reason"], str) or not item["reason"].strip():
            raise RelationError("身份历史新 ID 或原因无效")


def merged_links(data: dict, derived: dict, match_status: dict[str, str]) -> list[dict]:
    combined = dict(derived)
    for link in data["links"]:
        if not isinstance(link, dict) or set(link) != LINK_FIELDS:
            raise RelationError("关系连接字段无效")
        key = (link["from_type"], link["from_id"], link["to_type"], link["to_id"])
        if key[0] in {"entry", "interface"}:
            if key not in derived:
                raise RelationError("入口或接口关系缺少既有规格映射")
            if link["status"] == "verified" and match_status.get(key[3] if key[0] == "entry" else key[1]) != "已匹配":
                raise RelationError("未匹配或疑似匹配接口不能升级为已证实关系")
        combined[key] = link
    return [combined[key] for key in sorted(combined)]


def coverage(module_id: str, known: dict[str, set[str]], topics: list[dict], links: list[dict]) -> dict:
    """Report gaps, never infer a missing edge from similar names."""
    verified = [link for link in links if link["status"] == "verified"]
    incoming = {(link["to_type"], link["to_id"]) for link in verified}
    outgoing = {(link["from_type"], link["from_id"]) for link in verified}
    return {
        "module_id": module_id,
        "entry_without_verified_interface": sorted(value for value in known.get("entry", set()) if ("entry", value) not in outgoing),
        "interface_without_verified_method": sorted(value for value in known.get("interface", set()) if ("interface", value) not in outgoing),
        "method_without_verified_fact": sorted(value for value in known.get("method", set()) if ("method", value) not in outgoing),
        "fact_without_verified_topic": sorted(value for value in known.get("fact", set()) if ("fact", value) not in outgoing),
        "topic_without_verified_fact": sorted(item["topic_id"] for item in topics if ("topic", item["topic_id"]) not in incoming),
        "candidate_edges": sum(link["status"] == "candidate" for link in links),
        "unresolved_edges": sum(link["status"] == "unresolved" for link in links),
        "verified_edges": len(verified),
    }


def manifest(data: dict, raw: bytes, *, release_id: str, registry_sha256: str, retrieval_sha256: str | None, links: list[dict] | None = None) -> dict:
    if not SHA.fullmatch(registry_sha256) or (retrieval_sha256 is not None and not SHA.fullmatch(retrieval_sha256)):
        raise RelationError("关系清单基础摘要无效")
    return {
        "relation_schema_version": SCHEMA,
        "release_id": release_id,
        "module_id": data["module_id"],
        "source_mapping_sha256": digest(raw),
        "base_registry_sha256": registry_sha256,
        "retrieval_manifest_sha256": retrieval_sha256,
        "topics": sorted(data["topics"], key=lambda item: item["topic_id"]),
        "nodes": sorted(data["nodes"], key=lambda item: (item["kind"], item["node_id"])),
        "links": links if links is not None else sorted(data["links"], key=lambda item: (item["from_type"], item["from_id"], item["to_type"], item["to_id"])),
        "identity_history": sorted(data["identity_history"], key=lambda item: item["old_id"]),
    }
