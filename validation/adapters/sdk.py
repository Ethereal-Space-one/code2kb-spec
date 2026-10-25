"""Small public contract for conservative source candidate adapters."""

from __future__ import annotations

from typing import Protocol


class CandidateAdapter(Protocol):
    """Adapter implementations read one pinned repository and return candidates."""

    name: str
    version: str

    def scan(self, repository_id: str, repository: dict, *, scope: str | None = None,
             uniapp_manifest: str | None = None) -> dict:
        ...


def validate_result(result: dict) -> dict:
    if not isinstance(result, dict) or set(result) != {"schema_version", "adapter", "snapshot", "coverage", "candidates", "edges", "unresolved"} or result["schema_version"] != "0.2":
        raise ValueError("Adapter 输出结构无效")
    snapshot = result["snapshot"]
    if not isinstance(snapshot, dict) or set(snapshot) != {"repository_id", "commit", "scope"} or not all(isinstance(snapshot.get(key), str) and snapshot[key] for key in ("repository_id", "commit")):
        raise ValueError("Adapter 缺少固定源码快照")
    adapter = result["adapter"]
    if not isinstance(adapter, dict) or set(adapter) != {"name", "version", "capabilities"} or not isinstance(adapter["capabilities"], list):
        raise ValueError("Adapter 能力声明无效")
    candidates = result["candidates"]
    edges = result["edges"]
    if not isinstance(candidates, list) or not isinstance(edges, list):
        raise ValueError("Adapter 候选或关系列表无效")
    ids = set()
    anchors = {}
    for item in candidates:
        if not isinstance(item, dict) or not {"candidate_id", "repository_id", "source_path", "line", "kind", "language", "expression", "status", "capability", "rule_id", "rule_version", "anchor", "unresolved_reason"} <= set(item):
            raise ValueError("Adapter 候选字段不完整")
        if item["candidate_id"] in ids or item["status"] not in {"candidate", "unresolved"} or item["capability"] not in {"L1", "L2", "L3"} or item["repository_id"] != snapshot["repository_id"] or not isinstance(item["line"], int) or item["line"] < 1:
            raise ValueError("Adapter 候选身份、等级或状态无效")
        if item["anchor"] != f"{item['repository_id']}:{item['source_path']}:{item['line']}":
            raise ValueError("Adapter 候选锚点不一致")
        if item["status"] == "unresolved" and not item["unresolved_reason"]:
            raise ValueError("未解候选缺少原因")
        ids.add(item["candidate_id"])
        anchors[item["candidate_id"]] = item["anchor"]
    edge_ids = set()
    for edge in edges:
        if not isinstance(edge, dict) or set(edge) != {"edge_id", "from_candidate_id", "to_candidate_id", "status", "basis", "evidence", "unresolved_reason"} or edge["edge_id"] in edge_ids or edge["from_candidate_id"] not in ids or edge["to_candidate_id"] not in ids or edge["status"] not in {"candidate", "unresolved"} or edge["evidence"] != [anchors[edge["from_candidate_id"]], anchors[edge["to_candidate_id"]]] or (edge["status"] == "unresolved" and not edge["unresolved_reason"]):
            raise ValueError("Adapter 桥接关系缺少两端、证据或有效状态")
        edge_ids.add(edge["edge_id"])
    if result["unresolved"] != sum(item["status"] == "unresolved" for item in candidates):
        raise ValueError("Adapter 未解计数与候选不一致")
    return result
