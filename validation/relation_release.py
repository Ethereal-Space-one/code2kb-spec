"""Freeze and audit the optional relation extension beside one base release."""

from __future__ import annotations

from pathlib import Path

try:
    from . import relation_model
    from .retrieval_model import contained_file, digest, json_bytes, read_unit, strict_json
except ImportError:
    import relation_model
    from retrieval_model import contained_file, digest, json_bytes, read_unit, strict_json


SCHEMA = "0.1"
MANIFEST_FIELDS = {"relation_manifest_schema_version", "release_id", "base_registry_sha256", "retrieval_manifest_sha256", "modules", "mapping_files"}
POINTER_FIELDS = {"relation_schema_version", "release_id", "manifest_path", "manifest_sha256"}
MODULE_FIELDS = {"relation_schema_version", "release_id", "module_id", "source_mapping_sha256", "base_registry_sha256", "retrieval_manifest_sha256", "topics", "nodes", "links", "identity_history"}


def build(release_root: Path, release_id: str, relations: dict, specs: dict) -> dict | None:
    if not relations:
        return None
    registry_path = release_root / "版本清单" / f"{release_id}.json"
    registry = strict_json(registry_path)
    registry_sha = digest(registry_path.read_bytes())
    retrieval_path = release_root / "检索清单" / f"{release_id}.json"
    retrieval_sha = digest(retrieval_path.read_bytes()) if retrieval_path.is_file() else None
    retrieval = strict_json(retrieval_path) if retrieval_sha else None
    inputs = release_root / "关系输入" / release_id
    if inputs.exists() or inputs.is_symlink():
        raise relation_model.RelationError("关系输入发布路径已存在")
    inputs.mkdir(parents=True)
    modules = {}
    files = {}
    for module_id, item in sorted(relations.items()):
        spec = specs[module_id]
        local = spec.relative.parent.as_posix()
        copied = inputs / f"{module_id}.json"
        copied.write_bytes(item["raw"])
        files[f"发布/关系输入/{release_id}/{module_id}.json"] = digest(item["raw"])
        value = relation_model.manifest(item["data"], item["raw"], release_id=release_id, registry_sha256=registry_sha, retrieval_sha256=retrieval_sha, links=item["links"])
        for topic in value["topics"]:
            source = f"{local}/{topic['source_document']}"
            audience = topic["audience"]
            if source not in registry["views"][audience]["files"]:
                raise relation_model.RelationError(f"主题来源没有进入对应受众的发布版：{source}")
            topic["published_source"] = source
            unit_ids = []
            if retrieval:
                for unit in retrieval["units"]:
                    if unit["module_id"] == module_id and unit["audience"] == audience and source in unit["source_documents"]:
                        unit_path = contained_file(release_root.parent, unit["path"])
                        meta, _ = read_unit(unit_path)
                        if topic["source_heading"] in meta["source_headings"].split(" | "):
                            unit_ids.append(unit["unit_id"])
                if not unit_ids:
                    raise relation_model.RelationError(f"主题没有对应的已发布检索单元：{topic['topic_id']}")
            topic["unit_ids"] = sorted(unit_ids)
        modules[module_id] = value
    manifest = {
        "relation_manifest_schema_version": SCHEMA,
        "release_id": release_id,
        "base_registry_sha256": registry_sha,
        "retrieval_manifest_sha256": retrieval_sha,
        "modules": modules,
        "mapping_files": files,
    }
    manifest_path = release_root / "关系清单" / f"{release_id}.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(json_bytes(manifest))
    pointer = {
        "relation_schema_version": SCHEMA,
        "release_id": release_id,
        "manifest_path": f"发布/关系清单/{release_id}.json",
        "manifest_sha256": digest(manifest_path.read_bytes()),
    }
    (release_root / "当前关系版本.json").write_bytes(json_bytes(pointer))
    return {"release_id": release_id, "modules": len(modules), "manifest_sha256": pointer["manifest_sha256"]}


def audit(release_root: Path, release_id: str) -> dict:
    try:
        return _audit(release_root, release_id)
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise relation_model.RelationError("关系发布物结构无效") from exc


def _audit(release_root: Path, release_id: str) -> dict:
    pointer = strict_json(release_root / "当前关系版本.json")
    if set(pointer) != POINTER_FIELDS or pointer["relation_schema_version"] != SCHEMA or pointer["release_id"] != release_id or pointer["manifest_path"] != f"发布/关系清单/{release_id}.json" or not isinstance(pointer["manifest_sha256"], str):
        raise relation_model.RelationError("关系版本指针无效")
    manifest_path = contained_file(release_root.parent, pointer["manifest_path"])
    if digest(manifest_path.read_bytes()) != pointer["manifest_sha256"]:
        raise relation_model.RelationError("关系清单摘要与指针不一致")
    manifest = strict_json(manifest_path)
    if set(manifest) != MANIFEST_FIELDS or manifest["relation_manifest_schema_version"] != SCHEMA or manifest["release_id"] != release_id:
        raise relation_model.RelationError("关系清单结构或版本无效")
    registry_path = release_root / "版本清单" / f"{release_id}.json"
    registry = strict_json(registry_path)
    if digest(registry_path.read_bytes()) != manifest["base_registry_sha256"]:
        raise relation_model.RelationError("关系清单与基础发布摘要不一致")
    retrieval_path = release_root / "检索清单" / f"{release_id}.json"
    actual_retrieval = digest(retrieval_path.read_bytes()) if retrieval_path.is_file() else None
    retrieval = strict_json(retrieval_path) if actual_retrieval else None
    if actual_retrieval != manifest["retrieval_manifest_sha256"]:
        raise relation_model.RelationError("关系清单与检索清单摘要不一致")
    if not isinstance(manifest["modules"], dict) or not manifest["modules"] or not isinstance(manifest["mapping_files"], dict):
        raise relation_model.RelationError("关系模块或冻结输入无效")
    input_root = release_root / "关系输入" / release_id
    if input_root.is_symlink() or not input_root.is_dir():
        raise relation_model.RelationError("关系输入目录缺失或为符号链接")
    actual_files = {}
    for path in input_root.rglob("*"):
        if path.is_symlink():
            raise relation_model.RelationError("关系输入含符号链接")
        if path.is_file():
            relative = path.relative_to(release_root.parent).as_posix()
            actual_files[relative] = digest(path.read_bytes())
    if actual_files != manifest["mapping_files"] or set(manifest["modules"]) != {Path(path).stem for path in actual_files}:
        raise relation_model.RelationError("关系输入被增删改")
    for module_id, item in manifest["modules"].items():
        local_input = f"发布/关系输入/{release_id}/{module_id}.json"
        if not isinstance(item, dict) or set(item) != MODULE_FIELDS or item.get("module_id") != module_id or item.get("source_mapping_sha256") != actual_files.get(local_input) or item.get("base_registry_sha256") != manifest["base_registry_sha256"] or item.get("retrieval_manifest_sha256") != actual_retrieval or item.get("release_id") != release_id or item.get("relation_schema_version") != SCHEMA:
            raise relation_model.RelationError("关系模块与冻结输入或发布摘要不一致")
        raw = (input_root / f"{module_id}.json").read_bytes()
        data = relation_model.strict_object(raw)
        if data["module_id"] != module_id or not isinstance(data["identity_history"], list) or item.get("identity_history") != sorted(data["identity_history"], key=lambda value: value["old_id"]):
            raise relation_model.RelationError("关系模块与冻结映射内容不一致")
        if not isinstance(item.get("topics"), list) or not isinstance(item.get("nodes"), list) or not isinstance(item.get("links"), list) or item["nodes"] != sorted(data["nodes"], key=lambda value: (value["kind"], value["node_id"])):
            raise relation_model.RelationError("关系模块主题或边无效")
        if len(item["topics"]) != len(data["topics"]):
            raise relation_model.RelationError("关系主题数量与冻结输入不一致")
        for topic in item["topics"]:
            if not isinstance(topic, dict) or set(topic) != relation_model.TOPIC_FIELDS | {"published_source", "unit_ids"} or not isinstance(topic["unit_ids"], list):
                raise relation_model.RelationError("关系主题字段无效")
            original = next((source for source in data["topics"] if source["topic_id"] == topic.get("topic_id")), None)
            if original is None or any(topic.get(key) != value for key, value in original.items()) or topic["audience"] not in {"business", "engineering"}:
                raise relation_model.RelationError("关系主题与冻结映射不一致")
            if topic["published_source"] not in registry["views"][topic["audience"]]["files"]:
                raise relation_model.RelationError("关系主题来源不在已发布受众版")
            expected_units = []
            if retrieval:
                for unit in retrieval["units"]:
                    if unit["module_id"] == module_id and unit["audience"] == topic["audience"] and topic["published_source"] in unit["source_documents"]:
                        meta, _ = read_unit(contained_file(release_root.parent, unit["path"]))
                        if topic["source_heading"] in meta["source_headings"].split(" | "):
                            expected_units.append(unit["unit_id"])
                if not expected_units:
                    raise relation_model.RelationError("关系主题没有对应检索单元")
            if topic["unit_ids"] != sorted(expected_units):
                raise relation_model.RelationError("关系主题检索单元映射不一致")
        if any(link not in item["links"] for link in data["links"]):
            raise relation_model.RelationError("关系连接与冻结映射不一致")
    return {"release_id": release_id, "modules": len(manifest["modules"]), "base_registry_sha256": manifest["base_registry_sha256"], "evidence_rebuild": "not_assessed_without_source_repositories"}
