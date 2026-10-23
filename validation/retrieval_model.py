"""Strict, deterministic data contract for the optional retrieval extension."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re


SCHEMA = "0.1"
AUDIENCES = ("business", "engineering")
UNIT_FIELDS = {
    "document_type", "retrieval_schema_version", "unit_id", "module_id",
    "audience", "topic", "question_variants", "source_documents",
    "source_headings", "fact_ids", "traceability_level", "release_id",
}
SAFE_ID = re.compile(r"[a-z][a-z0-9_.-]*\Z")
FACT_ID = re.compile(r"(?:F-[0-9]+[a-z]?|FACT-[0-9]+)\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX_UNIT_BYTES = 256 * 1024


class RetrievalError(ValueError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def strict_json(path: Path) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise RetrievalError(f"重复 JSON 字段：{path}: {key}")
            result[key] = value
        return result

    if path.is_symlink() or not path.is_file():
        raise RetrievalError(f"文件缺失或为符号链接：{path}")
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise RetrievalError(f"JSON 顶层须为对象：{path}")
    return value


def safe_relative(value: str) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return (bool(path.parts) and not path.is_absolute() and path.as_posix() == value
            and all(part not in {"", ".", ".."} for part in path.parts)
            and ":" not in path.parts[0])


def contained_file(root: Path, relative: str) -> Path:
    if not safe_relative(relative):
        raise RetrievalError(f"不安全的相对路径：{relative}")
    path = root / relative
    if any(part.is_symlink() for part in (path, *path.parents) if part == root or root in part.parents):
        raise RetrievalError(f"路径包含符号链接：{relative}")
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise RetrievalError(f"文件缺失或越界：{relative}")
    return path


def read_unit(path: Path) -> tuple[dict[str, str], str]:
    if path.is_symlink() or path.stat().st_size > MAX_UNIT_BYTES:
        raise RetrievalError(f"检索单元过大或为符号链接：{path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise RetrievalError(f"检索单元缺少 front matter：{path}")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise RetrievalError(f"检索单元 front matter 未闭合：{path}") from exc
    meta = {}
    for line in lines[1:end]:
        match = re.fullmatch(r"([a-z][a-z0-9_]*):\s*(.*)", line)
        if not match or match[1] in meta:
            raise RetrievalError(f"检索单元元数据无效或重复：{path}: {line}")
        meta[match[1]] = match[2]
    if set(meta) != UNIT_FIELDS or meta["document_type"] != "retrieval_unit" or meta["retrieval_schema_version"] != SCHEMA:
        raise RetrievalError(f"检索单元字段无效：{path}")
    if meta["audience"] not in AUDIENCES or not SAFE_ID.fullmatch(meta["module_id"]) or not SAFE_ID.fullmatch(meta["unit_id"]):
        raise RetrievalError(f"检索单元身份无效：{path}")
    if meta["traceability_level"] not in {"fact", "document"}:
        raise RetrievalError(f"检索单元追溯等级无效：{path}")
    if not meta["topic"] or not meta["source_headings"] or not meta["source_documents"]:
        raise RetrievalError(f"检索单元缺少主题或出处：{path}")
    sources = meta["source_documents"].split(" | ")
    if not all(safe_relative(item) for item in sources):
        raise RetrievalError(f"检索单元出处路径无效：{path}")
    facts = [item for item in meta["fact_ids"].split(",") if item]
    if not all(FACT_ID.fullmatch(item) for item in facts) or (meta["traceability_level"] == "fact") != bool(facts):
        raise RetrievalError(f"检索单元事实追溯无效：{path}")
    body = "\n".join(lines[end + 1:]).strip() + "\n"
    if not body.startswith("# ") or "## 出处" not in body:
        raise RetrievalError(f"检索单元正文结构无效：{path}")
    return meta, body


def render_unit(meta: dict[str, str], body: str) -> bytes:
    if set(meta) != UNIT_FIELDS:
        raise RetrievalError("检索单元元数据字段不完整")
    for value in meta.values():
        if "\n" in value or "\r" in value or value.startswith(("[", "{", "&", "*", "!")):
            raise RetrievalError("检索单元元数据包含不安全值")
    return ("---\n" + "\n".join(f"{key}: {meta[key]}" if meta[key] else f"{key}:" for key in sorted(meta)) + "\n---\n\n" + body.rstrip() + "\n").encode("utf-8")


def inventory(root: Path) -> dict[str, str]:
    if not root.is_dir() or root.is_symlink():
        raise RetrievalError(f"检索视图目录缺失或为符号链接：{root}")
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RetrievalError(f"检索视图含符号链接：{path}")
        if path.is_file():
            local = path.relative_to(root).as_posix()
            if path.suffix != ".md":
                raise RetrievalError(f"检索视图只能包含 Markdown：{path}")
            files[local] = digest(path.read_bytes())
    return files
