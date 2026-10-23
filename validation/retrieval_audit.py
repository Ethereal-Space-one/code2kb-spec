"""Audit retrieval files, base binding, evaluation and current pointer."""

from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import unquote

try:
    from .retrieval_model import AUDIENCES, RetrievalError, contained_file, digest, inventory, json_bytes, read_unit, strict_json, SHA
except ImportError:
    from retrieval_model import AUDIENCES, RetrievalError, contained_file, digest, inventory, json_bytes, read_unit, strict_json, SHA


MANIFEST_FIELDS = {
    "retrieval_manifest_schema_version", "retrieval_schema_version", "release_id",
    "base_registry_path", "base_registry_sha256", "generated_by", "generated_at",
    "profile", "views", "units", "duplicates", "evaluation", "gate_status",
    "duplicate_candidates", "route_index",
}
LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def audit_in_release(release_root: Path, release_id: str, *, require_ready: bool = True) -> dict:
    base_pointer = strict_json(release_root / "当前版本.json")
    if base_pointer.get("release_id") != release_id:
        raise RetrievalError("检索扩展与当前基础发布不一致")
    registry_path = release_root / "版本清单" / f"{release_id}.json"
    registry = strict_json(registry_path)
    manifest_path = release_root / "检索清单" / f"{release_id}.json"
    manifest = strict_json(manifest_path)
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS or manifest["retrieval_manifest_schema_version"] != "0.1" or manifest["retrieval_schema_version"] != "0.1" or manifest["release_id"] != release_id or manifest["profile"] not in {"full", "compact"} or not isinstance(manifest["generated_by"], dict) or set(manifest["generated_by"]) != {"name", "version"}:
        raise RetrievalError("检索清单结构或身份无效")
    if manifest["base_registry_path"] != base_pointer["registry_path"] or manifest["base_registry_sha256"] != digest(registry_path.read_bytes()) or manifest["base_registry_sha256"] != base_pointer["registry_sha256"]:
        raise RetrievalError("检索清单与基础版本清单摘要不一致")
    if not isinstance(manifest["views"], dict) or set(manifest["views"]) != set(AUDIENCES) or not isinstance(manifest["units"], list) or not isinstance(manifest["duplicates"], list) or not isinstance(manifest["duplicate_candidates"], list):
        raise RetrievalError("检索视图或单元目录无效")
    route = manifest["route_index"]
    if not isinstance(route, dict) or set(route) != {"path", "sha256"} or route["path"] != f"发布/检索索引/{release_id}.json" or not isinstance(route["sha256"], str) or not SHA.fullmatch(route["sha256"]):
        raise RetrievalError("检索路由索引引用无效")
    route_path = contained_file(release_root.parent, route["path"])
    route_data = strict_json(route_path)
    if digest(route_path.read_bytes()) != route["sha256"] or set(route_data) != {"schema_version", "release_id", "audiences"} or route_data["release_id"] != release_id or not isinstance(route_data["audiences"], dict) or set(route_data["audiences"]) != set(AUDIENCES):
        raise RetrievalError("检索路由索引与清单不一致")
    file_set = set()
    for audience in AUDIENCES:
        view = manifest["views"][audience]
        expected_path = f"发布/检索版/{'业务' if audience == 'business' else '研发'}"
        if not isinstance(view, dict) or set(view) != {"path", "files"} or view["path"] != expected_path or not isinstance(view["files"], dict) or (audience == "business" and not view["files"]) or not all(isinstance(key, str) and isinstance(value, str) and SHA.fullmatch(value) for key, value in view["files"].items()):
            raise RetrievalError("检索视图路径或摘要表无效")
        root = release_root / "检索版" / ("业务" if audience == "business" else "研发")
        if inventory(root) != view["files"]:
            raise RetrievalError(f"检索视图被增删改：{audience}")
        file_set.update(f"{expected_path}/{local}" for local in view["files"])
    seen = set()
    for entry in manifest["units"]:
        if (not isinstance(entry, dict) or set(entry) != {"unit_id", "module_id", "audience", "path", "topic", "source_documents"}
            or any(not isinstance(entry[key], str) or not entry[key] for key in ("unit_id", "module_id", "audience", "path", "topic"))
            or not isinstance(entry["source_documents"], list) or not entry["source_documents"]
            or any(not isinstance(item, str) or not item for item in entry["source_documents"])
            or entry["audience"] not in AUDIENCES or entry["path"] not in file_set or entry["unit_id"] in seen):
            raise RetrievalError("检索单元目录重复或路径无效")
        audience_root = manifest["views"][entry["audience"]]["path"] + "/"
        if not entry["path"].startswith(audience_root):
            raise RetrievalError("检索单元受众与目录不一致")
        seen.add(entry["unit_id"])
        path = contained_file(release_root.parent, entry["path"])
        meta, body = read_unit(path)
        if any(meta[key] != entry[key] for key in ("unit_id", "module_id", "audience", "topic")) or meta["release_id"] != release_id or meta["source_documents"].split(" | ") != entry["source_documents"]:
            raise RetrievalError("检索单元元数据与清单不一致")
        base_files = registry["views"][entry["audience"]]["files"]
        if any(source not in base_files for source in entry["source_documents"]):
            raise RetrievalError("检索单元出处不在基础发布中")
        for target in LINK.findall(body):
            if target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            local = unquote(target.split("#", 1)[0])
            linked = (path.parent / local).resolve()
            if not linked.is_relative_to(release_root.resolve()) or not linked.is_file():
                raise RetrievalError(f"检索单元包含失效或越界链接：{entry['path']} → {target}")
    if len(seen) != len(file_set):
        raise RetrievalError("检索目录与视图文件数量不一致")
    for audience in AUDIENCES:
        expected_routes = [
            {"unit_id": item["unit_id"], "module_id": item["module_id"], "topic": item["topic"], "path": item["path"]}
            for item in manifest["units"] if item["audience"] == audience
        ]
        if route_data["audiences"][audience] != expected_routes:
            raise RetrievalError("路由索引单元与清单不一致")
    evaluation = manifest["evaluation"]
    if evaluation is not None:
        required = {"suite_id", "suite_path", "suite_sha256", "report_path", "report_sha256", "report_markdown_path", "report_markdown_sha256", "external_results_path", "external_results_sha256", "retriever_id", "corpus_sha256"}
        if not isinstance(evaluation, dict) or set(evaluation) != required or evaluation["report_path"] != f"发布/检索评测/{release_id}.json" or evaluation["report_markdown_path"] != f"发布/检索评测/{release_id}.md" or evaluation["suite_path"] != f"发布/检索评测/套件/{release_id}.json" or not all(isinstance(evaluation[key], str) and SHA.fullmatch(evaluation[key]) for key in ("suite_sha256", "report_sha256", "report_markdown_sha256", "corpus_sha256")):
            raise RetrievalError("检索评测引用无效")
        suite_path = contained_file(release_root.parent, evaluation["suite_path"])
        if digest(suite_path.read_bytes()) != evaluation["suite_sha256"]:
            raise RetrievalError("检索问题集摘要不一致")
        if (evaluation["external_results_path"] is None) != (evaluation["external_results_sha256"] is None):
            raise RetrievalError("外部检索结果引用不完整")
        if evaluation["external_results_path"] is not None:
            if evaluation["external_results_path"] != f"发布/检索评测/外部结果/{release_id}.json" or not isinstance(evaluation["external_results_sha256"], str) or not SHA.fullmatch(evaluation["external_results_sha256"]):
                raise RetrievalError("外部检索结果引用无效")
            external_path = contained_file(release_root.parent, evaluation["external_results_path"])
            if digest(external_path.read_bytes()) != evaluation["external_results_sha256"]:
                raise RetrievalError("外部检索结果摘要不一致")
        report_path = contained_file(release_root.parent, evaluation["report_path"])
        markdown_path = contained_file(release_root.parent, evaluation["report_markdown_path"])
        report = strict_json(report_path)
        if digest(markdown_path.read_bytes()) != evaluation["report_markdown_sha256"]:
            raise RetrievalError("检索评测 Markdown 报告摘要不一致")
        if digest(report_path.read_bytes()) != evaluation["report_sha256"] or report.get("release_id") != release_id or report.get("suite_id") != evaluation["suite_id"] or report.get("suite_sha256") != evaluation["suite_sha256"] or report.get("retriever_id") != evaluation["retriever_id"] or report.get("corpus_sha256") != evaluation["corpus_sha256"] or report.get("manifest_units_sha256") != digest(json_bytes(manifest["units"])) or evaluation["corpus_sha256"] != digest(json_bytes(manifest["views"])) or report.get("gate_status") != manifest["gate_status"]:
            raise RetrievalError("检索评测报告与清单不一致")
    elif manifest["gate_status"] != "unevaluated":
        raise RetrievalError("缺少检索评测报告")
    pointer_path = release_root / "当前检索版本.json"
    if manifest["gate_status"] == "passed":
        pointer = strict_json(pointer_path)
        expected = {"retrieval_schema_version": "0.1", "release_id": release_id,
                    "base_registry_sha256": manifest["base_registry_sha256"],
                    "manifest_path": f"发布/检索清单/{release_id}.json",
                    "manifest_sha256": digest(manifest_path.read_bytes())}
        if pointer != expected:
            raise RetrievalError("当前检索指针与清单不一致")
    elif pointer_path.exists():
        raise RetrievalError("未通过评测却存在当前检索指针")
    if require_ready and manifest["gate_status"] != "passed":
        raise RetrievalError("检索评测未通过，不能标为检索就绪")
    return {"release_id": release_id, "units": len(seen), "gate_status": manifest["gate_status"], "base_registry_sha256": manifest["base_registry_sha256"]}
