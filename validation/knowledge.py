#!/usr/bin/env python3
"""Validate supported Code2KB projects and publish governed knowledge views."""

from __future__ import annotations

import argparse
import contextlib
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
import json
import io
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import shutil
import sys
import tempfile
from urllib.parse import unquote

try:
    from .adapters.ts_java import scan as scan_candidates
    from .adapters import ADAPTER_NAMES, get_adapter
    from .evidence_snapshot import snapshot as source_snapshot
    from .governance import Governance, json_text, atomic_write, digest, scan_business_terms
    from . import retrieval_build, retrieval_evaluate, retrieval_audit, retrieval_profile, retrieval_query, relation_release, relation_model, relation_upgrade, fact_render, run_state, workflow, host_adapter, protocol, protocol_migration
    from .retrieval_model import strict_json as retrieval_json
except ImportError:  # 兼容直接执行 validation/knowledge.py
    from adapters.ts_java import scan as scan_candidates
    from adapters import ADAPTER_NAMES, get_adapter
    from evidence_snapshot import snapshot as source_snapshot
    from governance import Governance, json_text, atomic_write, digest, scan_business_terms
    import retrieval_build, retrieval_evaluate, retrieval_audit, retrieval_profile, retrieval_query, relation_release, relation_model, relation_upgrade, fact_render, run_state, workflow, host_adapter, protocol, protocol_migration
    from retrieval_model import strict_json as retrieval_json


_VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"
if _VERSION_FILE.is_file():
    IMPLEMENTATION_VERSION = _VERSION_FILE.read_text(encoding="utf-8").strip()
else:
    from importlib.metadata import version

    IMPLEMENTATION_VERSION = version("code2kb-spec")
STANDARD_VERSION = protocol.DEFAULT_VERSION
LEGACY_STANDARD_VERSION = protocol.LEGACY_VERSION
SUPPORTED_STANDARD_VERSIONS = protocol.SUPPORTED_VERSIONS
ACTIONS = (
    "check", "publish", "impact", "confirm-claims", "prepare", "approve", "policy-review", "audit-release",
    "retrieval-build", "retrieval-evaluate", "retrieval-audit", "retrieval-compare", "retrieval-query",
    "relation-audit", "analyze-candidates", "evidence-snapshot", "render-facts", "preview-upgrade",
    "relation-report", "recover", "run-create", "run-status", "run-next", "run-begin", "run-complete",
    "run-resume", "run-cancel", "run-execute", "host-next", "migrate-protocol",
)
TYPES = {
    "模块概览.md": "overview",
    "功能与范围.md": "scope",
    "业务流程.md": "flow",
    "规则与限制.md": "rules",
    "常见问答.md": "faq",
    "业务意图.md": "intent",
    "技术实现.md": "implementation",
    "接口与调用.md": "api_catalog",
    "方法与源码.md": "method_catalog",
    "结构化规格.md": "spec",
    "待确认事项.md": "questions",
    "发布清单.md": "release_manifest",
}
BUSINESS = {"overview", "scope", "flow", "rules", "faq", "intent", "glossary"}
INTERNAL = {"spec", "questions", "release_manifest"}
ENGINEERING = {"implementation", "api_catalog", "method_catalog"}
POLICY_METADATA = {
    "review_mode", "review_policy", "policy_version", "policy_owner", "executed_by",
    "review_evidence", "review_evidence_digest", "policy_digest",
}
BUSINESS_METADATA = {"module_id", "scene_id", "document_type", "review_status", "applicability", "reviewed_by", "reviewed_at", "aliases"} | POLICY_METADATA
STATES = {"待归类", "待提取", "待核查", "知识草稿", "可发布", "已发布"}
ENTRY_TYPES = {"页面", "按钮", "自动", "手势", "动态", "后端入口", "HTTP入口", "消息入口", "定时入口", "命令入口", "其他"}
ENTRY_STATES = {"已归类", "待核查"}
QA_CATEGORIES = {"正常", "失败", "未知", "越权"}
SEMANTIC_TYPES = {"字段", "业务术语", "状态", "权限", "归属", "金额", "名额", "指标"}
SEMANTIC_REVIEW_CATEGORIES = {"字段副作用", "配置键", "正文一致性"}
SEMANTIC_ID = re.compile(r"SEM-[A-Za-z0-9-]+\Z")
CONFIG_ID = re.compile(r"CFG-[A-Za-z0-9-]+\Z")
INTENT_ID = re.compile(r"INT-[0-9]{3}\Z")
INTENT_LEVELS = {"BUSINESS_CONFIRMED", "DOCUMENTED", "INFERRED", "UNKNOWN"}
INTENT_SCOPES = {"机器人知识库", "仅内部"}
SOURCE_ID = re.compile(r"[a-z][a-z0-9_-]*\Z")
ANCHOR = re.compile(r"^([a-z][a-z0-9_-]*):(.+):([1-9][0-9]*)$")
API_ID = re.compile(r"API-[A-Za-z0-9-]+\Z")
ENV_REPOSITORY_PATH = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}\Z")
METHOD_ID = re.compile(r"METHOD-[A-Za-z0-9-]+\Z")
HEX_COMMIT = re.compile(r"[0-9a-f]{7,40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
TECHNICAL = re.compile(
    r"```|\b(?:BE|FE|UC|API|METHOD|FACT|INT|EVID)-[A-Za-z0-9-]+|\bfact_id\b|\b(?:GET|POST|PUT|PATCH|DELETE)\s+/|"
    r"\b(?:SELECT|INSERT|UPDATE|DELETE)\s+.{0,40}\b(?:FROM|INTO|SET)\b|"
    r"\.(?:java|php|vue|tsx?|jsx?)(?:\b|:)|"
    r"(?:源码|代码|接口|类名|数据库字段|SQL|commit|Git 提交|技术实现\.md|接口与调用\.md|方法与源码\.md|结构化规格\.md|待确认事项\.md)|"
    r"\b[a-z][a-z0-9_-]*:[^\s:]+:[1-9][0-9]*|"
    r"(?:src|backend|frontend|app)/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+|"
    r"\b[0-9a-f]{40}\b",
    re.IGNORECASE,
)
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
PLAIN_MD_REF = re.compile(r"(?<![\w./])(?:[\w\u4e00-\u9fff-]+/)*[\w\u4e00-\u9fff-]+\.md")
FACT_REF = re.compile(r"(?<![\w.-])(?:(?P<module>[a-z][a-z0-9_.-]*)#)?(?P<fact>F-[0-9]+[a-z]?|FACT-[0-9]+)(?![\w-])")
# 业务受众禁用内容：过程用语、内部事实编号与实现术语。业务正文与生成的业务版文本
# （检索索引、发布信息等）都不得出现；研发版保留必要技术信息，不受此规则限制。
BUSINESS_FORBIDDEN = re.compile(
    r"(?:集中审核|审核队列|发布包|发布清单|待确认事项|结构化规格|裁决稿|源稿|已登记|内部清单|"
    r"事务注解|行锁|自身代理|标识拼接|逻辑删除|端点|鉴权|数仓|子模块|缓存键|开发注释|实现旁|"
    r"\bF-[0-9]+[a-z]?\b|\bENT-[A-Za-z]?[0-9]+\b|\bSH-[0-9]+\b)"
)


class KnowledgeError(Exception):
    pass


_last_error_code: ContextVar[str | None] = ContextVar("code2kb_last_error_code", default=None)


@dataclass(frozen=True)
class Document:
    relative: Path
    module_id: str | None
    domain: str | None
    module: str | None
    doc_type: str
    meta: dict[str, str]
    body: str
    original: str

    @property
    def publishable(self) -> bool:
        return self.meta["review_status"] in {"reviewed", "policy_reviewed"} and self.meta["applicability"] == "current" and self.doc_type not in INTERNAL | {"outline"}


@dataclass(frozen=True)
class Outline:
    modules: dict[str, tuple[str, str, str]]
    entries: list[tuple[str, str, str, str, str, str]]
    meta: dict[str, str]


def parse_frontmatter(path: Path) -> tuple[dict[str, str], str, str]:
    original = path.read_bytes().decode("utf-8")
    lines = original.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise KnowledgeError(f"{path}: 缺少 front matter")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise KnowledgeError(f"{path}: front matter 未闭合")
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.fullmatch(r"([a-z][a-z0-9_]*):\s*(.*)", line.rstrip("\r\n"))
        if not match:
            raise KnowledgeError(f"{path}: 只支持单层 key: value 元数据：{stripped}")
        key, value = match.groups()
        if key in meta:
            raise KnowledgeError(f"{path}: 重复元数据 {key}")
        meta[key] = value.strip().strip('"\'')
    body = "".join(lines[end + 1 :]).replace("\r\n", "\n")
    return meta, body, original


def strict_json_object(path: Path, *, allowed: set[str] | None = None, label: str = "JSON") -> dict:
    """Read deterministic JSON and reject duplicate or unexpected top-level fields."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise KnowledgeError(f"{label}包含重复字段：{key}")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise KnowledgeError(f"{label}不是有效 UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise KnowledgeError(f"{label}顶层必须是对象")
    if allowed is not None and (unknown := set(value) - allowed):
        raise KnowledgeError(f"{label}包含未知字段：{sorted(unknown)}")
    return value


def resolve_repository_path(raw: str, *, resolve: bool, environ: dict[str, str] | None = None) -> str:
    match = ENV_REPOSITORY_PATH.fullmatch(raw)
    if match:
        if not resolve:
            return raw
        name = match.group(1)
        value = (os.environ if environ is None else environ).get(name)
        if not value:
            raise KnowledgeError(f"仓库路径环境变量 {name} 未设置或为空")
        path = Path(value)
        if not path.is_absolute():
            raise KnowledgeError(f"仓库路径环境变量 {name} 必须指向绝对路径")
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            raise KnowledgeError(f"仓库路径环境变量 {name} 未指向已存在目录") from None
        if not resolved.is_dir():
            raise KnowledgeError(f"仓库路径环境变量 {name} 未指向已存在目录")
        return str(resolved)
    if "$" in raw or chr(96) in raw or raw.startswith("~"):
        raise KnowledgeError("仓库 path 只支持绝对路径或完整的 ${大写环境变量名}，不执行 shell 表达式")
    if not Path(raw).is_absolute():
        raise KnowledgeError("仓库 path 须为绝对路径或完整的 ${大写环境变量名}")
    return raw


def read_config(project: Path, *, resolve_repository_paths: bool = True, environ: dict[str, str] | None = None) -> tuple[Path, dict]:
    config_path = project / "知识库配置.json"
    allowed = {
        "standard_version", "knowledge_source_root", "repositories", "coverage_terms",
        "sensitive_patterns", "boundary_notes", "inventory_adapter", "policy_review",
        "semantic_quality",
    }
    config = strict_json_object(config_path, allowed=allowed, label="知识库配置")
    profile_path = project / "Code2KB工程配置.json"
    if profile_path.exists():
        if profile_path.is_symlink():
            raise KnowledgeError("工程配置不能是符号链接")
        profile = strict_json_object(profile_path, allowed={"schema_version", "content_profile"}, label="工程配置")
        if set(profile) != {"schema_version", "content_profile"} or profile["schema_version"] != "0.1" or profile["content_profile"] not in {"full", "compact"}:
            raise KnowledgeError("工程配置仅支持 schema_version: 0.1 与 content_profile: full|compact")
        config["_content_profile"] = profile["content_profile"]
    else:
        config["_content_profile"] = "full"
    if not isinstance(config.get("standard_version"), str) or config["standard_version"] not in SUPPORTED_STANDARD_VERSIONS:
        raise KnowledgeError(f"{config_path}: standard_version 必须为受支持的协议标识：{', '.join(sorted(SUPPORTED_STANDARD_VERSIONS))}")
    if "publish_boundary" in config:
        raise KnowledgeError("兼容文件协议使用 boundary_notes；发布范围数字由大纲自动生成")
    notes = config.get("boundary_notes", {})
    if not isinstance(notes, dict) or any(key not in {"business", "engineering"} or not isinstance(value, str) for key, value in notes.items()):
        raise KnowledgeError("boundary_notes 须为 business/engineering 字符串")
    name = config.get("knowledge_source_root")
    if not isinstance(name, str) or not name or Path(name).is_absolute() or ".." in Path(name).parts:
        raise KnowledgeError("knowledge_source_root 必须是项目内相对路径")
    raw_source = project / name
    if raw_source.is_symlink():
        raise KnowledgeError("知识源目录不能是符号链接")
    source = raw_source.resolve(strict=True)
    if not source.is_relative_to(project) or not source.is_dir():
        raise KnowledgeError("知识源目录不存在或越出文档项目")
    repos = config.get("repositories")
    if not isinstance(repos, dict) or not repos:
        raise KnowledgeError("repositories 至少需要一个带固定提交的源码仓库")
    for role, settings in repos.items():
        if not isinstance(role, str) or not SOURCE_ID.fullmatch(role):
            raise KnowledgeError(f"无效仓库 ID：{role}")
        if not isinstance(settings, dict) or set(settings) != {"path", "commit"} or not isinstance(settings.get("path"), str) or not isinstance(settings.get("commit"), str):
            raise KnowledgeError(f"repositories.{role}: 需要 path 与 commit")
        try:
            settings["path"] = resolve_repository_path(settings["path"], resolve=resolve_repository_paths, environ=environ)
        except KnowledgeError as exc:
            raise KnowledgeError(f"repositories.{role}: {exc}") from exc
        if not HEX_COMMIT.fullmatch(settings["commit"]):
            raise KnowledgeError(f"repositories.{role}: commit 须为 Git SHA，不能使用环境变量")
    adapter = config.get("inventory_adapter")
    if adapter is not None:
        if not isinstance(adapter, dict) or set(adapter) - {"name", "repository", "manifest_path", "entry_type"} or adapter.get("name") != "uniapp_pages" or adapter.get("repository") not in repos:
            raise KnowledgeError("inventory_adapter 目前仅支持 uniapp_pages，且须指定已配置的 repository")
        manifest = adapter.get("manifest_path")
        if not isinstance(manifest, str) or not manifest or not safe_repo_path(manifest):
            raise KnowledgeError("inventory_adapter.manifest_path 须为仓库内相对路径")
        if adapter.get("entry_type", "页面") not in ENTRY_TYPES:
            raise KnowledgeError("inventory_adapter.entry_type 无效")
    terms = config.get("coverage_terms", [])
    if not isinstance(terms, list) or any(not isinstance(term, str) or not term.strip() for term in terms):
        raise KnowledgeError("coverage_terms 须为非空字符串组成的列表")
    patterns = config.get("sensitive_patterns", [])
    if not isinstance(patterns, list) or any(not isinstance(pattern, str) or not pattern for pattern in patterns):
        raise KnowledgeError("sensitive_patterns 须为正则字符串列表")
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise KnowledgeError("sensitive_patterns 存在无效正则") from exc
    policy_review = config.get("policy_review")
    if policy_review is not None:
        if not isinstance(policy_review, dict) or set(policy_review) - {"enabled", "policy_file"} or type(policy_review.get("enabled")) is not bool:
            raise KnowledgeError("policy_review 只支持 enabled 与 policy_file")
        policy_file = policy_review.get("policy_file")
        if policy_review["enabled"] and (not isinstance(policy_file, str) or not safe_repo_path(policy_file) or not policy_file.endswith(".json")):
            raise KnowledgeError("启用 policy_review 时 policy_file 须为项目内相对 JSON 路径")
        if policy_file is not None and (not isinstance(policy_file, str) or not safe_repo_path(policy_file) or not policy_file.endswith(".json")):
            raise KnowledgeError("policy_review.policy_file 须为项目内相对 JSON 路径")
    semantic_quality = config.get("semantic_quality")
    if semantic_quality is not None:
        if (
            not isinstance(semantic_quality, dict)
            or set(semantic_quality) != {"enabled", "module_ids"}
            or type(semantic_quality.get("enabled")) is not bool
            or not isinstance(semantic_quality.get("module_ids"), list)
            or not semantic_quality["module_ids"]
            or any(not isinstance(item, str) or not item for item in semantic_quality["module_ids"])
            or len(semantic_quality["module_ids"]) != len(set(semantic_quality["module_ids"]))
        ):
            raise KnowledgeError("semantic_quality 只支持 enabled 与非空且不重复的 module_ids")
        modules = semantic_quality["module_ids"]
        if modules != ["*"] and any(not re.fullmatch(r"[a-z][a-z0-9_.-]*", item) for item in modules):
            raise KnowledgeError("semantic_quality.module_ids 须为 module_id 列表或单独的 *")
    return source, config


def safe_repo_path(path: str) -> bool:
    relative = PurePosixPath(path)
    return not relative.is_absolute() and bool(path) and not any(part in {".", ".."} for part in relative.parts) and "\\" not in path


def expected_revisions(config: dict) -> str:
    return ", ".join(f"{role}={settings['commit']}" for role, settings in sorted(config["repositories"].items()))


def document_revisions(doc: Document, config: dict) -> set[str]:
    value = doc.meta.get("source_revisions", "")
    parts = [part.strip() for part in value.split(",") if part.strip()]
    pairs = [part.split("=", 1) for part in parts]
    if not pairs or any(len(pair) != 2 or pair[0] not in config["repositories"] or pair[1] != config["repositories"][pair[0]]["commit"] for pair in pairs):
        raise KnowledgeError(f"{doc.relative}: source_revisions 与项目配置不一致；先对照提交差异重核模块")
    roles = [pair[0] for pair in pairs]
    canonical = ", ".join(f"{role}={config['repositories'][role]['commit']}" for role in sorted(set(roles)))
    if len(roles) != len(set(roles)) or value != canonical:
        raise KnowledgeError(f"{doc.relative}: source_revisions 应按仓库 ID 排序且不重复：{canonical}")
    return set(roles)


def ensure_no_symlinks(source: Path) -> None:
    for path in source.rglob("*"):
        if path.is_symlink():
            raise KnowledgeError(f"知识源不允许符号链接：{path}")


def read_documents(source: Path) -> tuple[list[Document], Outline]:
    ensure_no_symlinks(source)
    docs: list[Document] = []
    outline: Outline | None = None
    if not (source / "功能大纲.md").is_file():
        raise KnowledgeError("缺少知识源/功能大纲.md")
    for path in sorted(source.rglob("*.md")):
        relative = path.relative_to(source)
        parts = relative.parts
        if len(parts) == 1:
            expected = {"功能大纲.md": "outline", "术语表.md": "glossary"}.get(parts[0])
            domain = module = None
        elif len(parts) in {3, 4}:
            expected = TYPES.get(parts[-1])
            domain, module = parts[0], parts[1]
            if len(parts) == 4 and expected in {"overview", "spec", "questions", "release_manifest", "implementation", "api_catalog", "method_catalog"}:
                raise KnowledgeError(f"{relative}: 场景目录不放模块概览、内部过程文件或研发索引；请放在模块根目录")
        else:
            expected = None
            domain = module = None
        if expected is None or any(p.startswith(".") for p in parts):
            raise KnowledgeError(f"{relative}: 不符合中文知识目录与规定文件类型")
        meta, body, original = parse_frontmatter(path)
        if meta.get("document_type") != expected:
            raise KnowledgeError(f"{relative}: document_type 应为 {expected}")
        if meta.get("review_status") not in {"draft", "reviewed", "policy_reviewed"} or meta.get("applicability") not in {"current", "superseded"}:
            raise KnowledgeError(f"{relative}: review_status/applicability 无效")
        if not re.search(r"(?m)^# \S", body):
            raise KnowledgeError(f"{relative}: 缺少一级标题")
        module_id = meta.get("module_id") if domain else None
        if domain and (not module_id or not re.fullmatch(r"[a-z][a-z0-9_.-]*", module_id)):
            raise KnowledgeError(f"{relative}: 缺少稳定 module_id")
        if len(parts) == 4 and not meta.get("scene_id"):
            raise KnowledgeError(f"{relative}: 场景文件需要 scene_id")
        if meta["review_status"] == "reviewed":
            reviewer, reviewed_at = meta.get("reviewed_by"), meta.get("reviewed_at")
            if not reviewer or not reviewed_at:
                raise KnowledgeError(f"{relative}: reviewed 文件须填真实审核人和日期")
            try:
                date.fromisoformat(reviewed_at)
            except ValueError as exc:
                raise KnowledgeError(f"{relative}: reviewed_at 须为 YYYY-MM-DD") from exc
            if any(meta.get(key) for key in POLICY_METADATA):
                raise KnowledgeError(f"{relative}: 人工 reviewed 文件不能混入策略审核字段")
        if meta["review_status"] == "policy_reviewed":
            required = POLICY_METADATA | {"reviewed_at"}
            if any(not meta.get(key) for key in required) or meta.get("review_mode") != "policy_auto" or meta.get("reviewed_by"):
                raise KnowledgeError(f"{relative}: policy_reviewed 文件缺少独立策略审核字段或混入人工审核人")
            if not SHA256.fullmatch(meta.get("review_evidence_digest", "")) or not SHA256.fullmatch(meta.get("policy_digest", "")):
                raise KnowledgeError(f"{relative}: 策略或审核记录摘要无效")
            try:
                date.fromisoformat(meta["reviewed_at"])
            except ValueError as exc:
                raise KnowledgeError(f"{relative}: reviewed_at 须为 YYYY-MM-DD") from exc
        if expected in BUSINESS:
            if set(meta) - BUSINESS_METADATA or TECHNICAL.search(body) or BUSINESS_FORBIDDEN.search(body):
                raise KnowledgeError(f"{relative}: 业务文件含明显技术内容或过程用语；请移至技术实现或过程文件")
        if expected in ENGINEERING and meta["review_status"] in {"reviewed", "policy_reviewed"}:
            if meta.get("runtime_status") not in {"source_only", "runtime_verified", "verified_deployment"}:
                raise KnowledgeError(f"{relative}: 研发文件须有有效 runtime_status")
            if meta["runtime_status"] == "verified_deployment" and not meta.get("deployment_evidence"):
                raise KnowledgeError(f"{relative}: 已验证部署需要 deployment_evidence")
        doc = Document(relative, module_id, domain, module, expected, meta, body, original)
        docs.append(doc)
        if expected == "outline":
            outline = parse_outline(body, meta)
    if outline is None or not outline.modules:
        raise KnowledgeError("功能大纲没有有效模块条目")
    return docs, outline


def table_rows(body: str, heading: str, header: str) -> list[list[str]]:
    lines = body.splitlines()
    try:
        start = lines.index(heading)
    except ValueError as exc:
        raise KnowledgeError(f"缺少章节 {heading}") from exc
    stop = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    section = lines[start + 1 : stop]
    try:
        header_index = section.index(header)
    except ValueError as exc:
        raise KnowledgeError(f"{heading} 缺少规定表头：{header}") from exc
    if header_index + 1 >= len(section) or not re.fullmatch(r"[|\s:-]+", section[header_index + 1]):
        raise KnowledgeError(f"{heading} 缺少 Markdown 表格分隔行")
    rows: list[list[str]] = []
    expected_cells = len(header.strip("|").split("|"))
    for line in section[header_index + 2 :]:
        if not line.startswith("|"):
            break
        cells = [part.strip() for part in line.strip("|").split("|")]
        if len(cells) != expected_cells:
            raise KnowledgeError(f"{heading} 表格列数错误：{line}")
        rows.append(cells)
    return rows


def parse_outline(body: str, meta: dict[str, str]) -> Outline:
    rows: dict[str, tuple[str, str, str]] = {}
    module_header = "| module_id | 业务域 | 子模块 | 发现入口 | 状态 |"
    for cells in table_rows(body, "## 模块清单", module_header):
        if not re.fullmatch(r"[a-z][a-z0-9_.-]*", cells[0]) or cells[4] not in STATES or not all(cells[:4]):
            raise KnowledgeError(f"功能大纲模块条目无效：{cells}")
        if cells[0] in rows:
            raise KnowledgeError(f"功能大纲重复 module_id: {cells[0]}")
        rows[cells[0]] = (cells[1], cells[2], cells[4])
    entry_header = "| entry_id | 类型 | 入口或动作 | module_id | 证据 | 状态 |"
    entries = []
    seen_entries: set[str] = set()
    for cells in table_rows(body, "## 入口证据索引", entry_header):
        entry_id, kind, action, module_id, evidence, status = cells
        if not re.fullmatch(r"ENT-[A-Za-z0-9-]+", entry_id) or entry_id in seen_entries:
            raise KnowledgeError(f"入口 ID 无效或重复：{entry_id}")
        if kind not in ENTRY_TYPES or status not in ENTRY_STATES or not action:
            raise KnowledgeError(f"入口类型、动作或状态无效：{entry_id}")
        if module_id != "未归类" and module_id not in rows:
            raise KnowledgeError(f"{entry_id}: module_id 未列入模块清单")
        if module_id == "未归类" and status != "待核查":
            raise KnowledgeError(f"{entry_id}: 未归类入口状态须为待核查")
        if not ANCHOR.fullmatch(evidence):
            raise KnowledgeError(f"{entry_id}: 证据须为 仓库ID:相对路径:行号")
        seen_entries.add(entry_id)
        entries.append((entry_id, kind, action, module_id, evidence, status))
    if meta.get("inventory_status") not in {"draft", "complete"}:
        raise KnowledgeError("功能大纲 inventory_status 须为 draft 或 complete")
    if meta["inventory_status"] == "complete":
        if not entries:
            raise KnowledgeError("完整功能大纲缺少入口证据索引")
        missing = set(rows) - {entry[3] for entry in entries}
        if missing:
            raise KnowledgeError(f"功能大纲模块缺少入口证据：{sorted(missing)}")
        if "## 盘点覆盖说明" not in body:
            raise KnowledgeError("完整功能大纲缺少盘点覆盖说明")
        coverage = body.split("## 盘点覆盖说明", 1)[1].split("## ", 1)[0].strip()
        if not coverage:
            raise KnowledgeError("完整功能大纲的盘点覆盖说明不能为空")
    return Outline(rows, entries, meta)


def verify_repos(config: dict) -> None:
    for role, settings in config["repositories"].items():
        repo = Path(settings["path"])
        if not repo.is_dir():
            raise KnowledgeError(f"{role} 仓库不存在：{repo}")
        result = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-e", f"{settings['commit']}^{{commit}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise KnowledgeError(f"{role} 固定 commit 不存在：{settings['commit']}")


def registered_adapter_entries(config: dict) -> set[str] | None:
    adapter = config.get("inventory_adapter")
    if adapter is None:
        return None
    if adapter["name"] == "uniapp_pages":
        return get_adapter("builtin-mixed").inventory_entries(config["repositories"][adapter["repository"]], adapter["manifest_path"])
    raise KnowledgeError(f"未知入口盘点适配器：{adapter['name']}")


def verify_anchor(anchor: str, config: dict, cache: dict[tuple[str, str], list[str]], allowed_sources: set[str] | None = None) -> None:
    match = ANCHOR.fullmatch(anchor)
    if not match:
        raise KnowledgeError(f"无效源码锚点：{anchor}")
    role, path, number = match.groups()
    if role not in config["repositories"]:
        raise KnowledgeError(f"源码锚点仓库 ID 未配置：{anchor}")
    if allowed_sources is not None and role not in allowed_sources:
        raise KnowledgeError(f"源码锚点仓库 ID 未列入文件 source_revisions：{anchor}")
    if not safe_repo_path(path):
        raise KnowledgeError(f"源码锚点路径须为仓库内相对路径：{anchor}")
    key = (role, path)
    if key not in cache:
        settings = config["repositories"][role]
        result = subprocess.run(
            ["git", "-C", settings["path"], "show", f"{settings['commit']}:{path}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode or "\x00" in result.stdout:
            raise KnowledgeError(f"固定提交中找不到文本证据：{anchor}")
        cache[key] = result.stdout.splitlines()
    if int(number) > len(cache[key]):
        raise KnowledgeError(f"源码锚点行号越界：{anchor}")


def validate_spec_facts(doc: Document, config: dict, cache: dict[tuple[str, str], list[str]], sources: set[str]) -> int:
    header = "| fact_id | 单一结论与条件 | 证据等级 | 固定提交锚点 | 影响的知识文件 |"
    rows = table_rows(doc.body, "## 入口与调用链", header)
    seen: set[str] = set()
    levels = {"CODE_VERIFIED", "RUN_VERIFIED", "INFERRED", "BUSINESS_CONFIRMED", "UNKNOWN"}
    for fact_id, conclusion, level, anchors, affected in rows:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]+", fact_id) or fact_id in seen:
            raise KnowledgeError(f"{doc.relative}: fact_id 无效或重复：{fact_id}")
        if not conclusion or level not in levels or not affected:
            raise KnowledgeError(f"{doc.relative}: {fact_id} 缺少结论、证据等级或影响文件")
        if level == "CODE_VERIFIED":
            cited = [item.strip() for item in anchors.split(",") if item.strip()]
            if not cited:
                raise KnowledgeError(f"{doc.relative}: {fact_id} 缺少源码锚点")
            for anchor in cited:
                verify_anchor(anchor, config, cache, sources)
        seen.add(fact_id)
    return len(rows)


def id_list(value: str, pattern: re.Pattern[str], context: str) -> list[str]:
    if value == "无":
        return []
    ids = [item.strip() for item in value.split(",")]
    if not ids or any(not pattern.fullmatch(item) for item in ids) or len(set(ids)) != len(ids):
        raise KnowledgeError(f"{context}: ID 格式无效或重复：{value}")
    return ids


def verify_anchors(value: str, config: dict, cache: dict[tuple[str, str], list[str]], context: str, sources: set[str]) -> None:
    anchors = [item.strip() for item in value.split(",") if item.strip()]
    if not anchors:
        raise KnowledgeError(f"{context}: 缺少源码锚点")
    for anchor in anchors:
        verify_anchor(anchor, config, cache, sources)


def detail_section(body: str, item_id: str) -> str | None:
    match = re.search(rf"(?m)^### {re.escape(item_id)}(?:\s|$)", body)
    if not match:
        return None
    tail = body[match.end() :]
    end = re.search(r"(?m)^#{2,3} ", tail)
    return tail[: end.start()] if end else tail


def validate_spec_catalog(
    doc: Document, outline: Outline, config: dict, cache: dict[tuple[str, str], list[str]], sources: set[str]
) -> tuple[dict[str, list[str]], dict[str, list[str]], set[str]]:
    action_header = "| entry_id | api_id | 调用条件 | 证据 |"
    api_header = "| api_id | 接口标识 | 调用方 | 服务入口 | 主处理方法 | 证据 |"
    method_header = "| method_id | 符号 | 职责 | 关键性 | 关联接口 | 源码锚点 |"
    actions = table_rows(doc.body, "## 入口与接口", action_header)
    apis = table_rows(doc.body, "## 接口契约", api_header)
    methods = table_rows(doc.body, "## 方法职责", method_header)
    api_ids: set[str] = set()
    method_ids: set[str] = set()
    core_ids: set[str] = set()
    api_rows: dict[str, list[str]] = {}
    method_rows: dict[str, list[str]] = {}
    api_to_methods: dict[str, list[str]] = {}
    method_to_apis: dict[str, list[str]] = {}
    known_entries = {entry[0]: entry[3] for entry in outline.entries}
    for api_id, route, frontend_call, backend_entry, main_methods, anchors in apis:
        if not API_ID.fullmatch(api_id) or api_id in api_ids or not all((route, frontend_call, backend_entry)):
            raise KnowledgeError(f"{doc.relative}: 接口 ID、标识或调用信息无效：{api_id}")
        api_to_methods[api_id] = id_list(main_methods, METHOD_ID, f"{doc.relative}: {api_id}")
        verify_anchors(anchors, config, cache, f"{doc.relative}: {api_id}", sources)
        api_ids.add(api_id)
        api_rows[api_id] = [api_id, route, frontend_call, backend_entry, main_methods, anchors]
    for method_id, symbol, purpose, importance, related_apis, anchor in methods:
        if not METHOD_ID.fullmatch(method_id) or method_id in method_ids or not symbol or not purpose or importance not in {"核心", "辅助"}:
            raise KnowledgeError(f"{doc.relative}: 方法 ID、符号、职责或关键性无效：{method_id}")
        method_to_apis[method_id] = id_list(related_apis, API_ID, f"{doc.relative}: {method_id}")
        verify_anchors(anchor, config, cache, f"{doc.relative}: {method_id}", sources)
        method_ids.add(method_id)
        method_rows[method_id] = [method_id, symbol, purpose, importance, related_apis, anchor]
        if importance == "核心":
            core_ids.add(method_id)
    for api_id, references in api_to_methods.items():
        for method_id in references:
            if method_id not in method_ids or api_id not in method_to_apis[method_id]:
                raise KnowledgeError(f"{doc.relative}: {api_id} 与 {method_id} 关联不一致")
    for method_id, references in method_to_apis.items():
        for api_id in references:
            if api_id not in api_ids or method_id not in api_to_methods[api_id]:
                raise KnowledgeError(f"{doc.relative}: {method_id} 与 {api_id} 关联不一致")
    seen_actions: set[tuple[str, str]] = set()
    for entry_id, api_id, condition, evidence in actions:
        if known_entries.get(entry_id) != doc.module_id or api_id not in api_ids or not condition or (entry_id, api_id) in seen_actions:
            raise KnowledgeError(f"{doc.relative}: 入口与接口映射无效：{entry_id} → {api_id}")
        verify_anchors(evidence, config, cache, f"{doc.relative}: {entry_id} → {api_id}", sources)
        seen_actions.add((entry_id, api_id))
    if api_ids and not seen_actions:
        raise KnowledgeError(f"{doc.relative}: 有接口却没有入口映射；无页面入口的接口仍须在大纲登记对应入口并说明")
    unmapped_apis = api_ids - {api_id for _, api_id in seen_actions}
    if unmapped_apis:
        raise KnowledgeError(f"{doc.relative}: 接口缺少入口映射：{sorted(unmapped_apis)}")
    for item_id in api_ids | core_ids:
        if detail_section(doc.body, item_id) is None:
            raise KnowledgeError(f"{doc.relative}: 缺少 {item_id} 的详细小节")
    return api_rows, method_rows, core_ids


def validate_catalog(
    doc: Document, expected_rows: dict[str, list[str]], core_ids: set[str], config: dict, cache: dict[tuple[str, str], list[str]], sources: set[str]
) -> None:
    if doc.doc_type == "api_catalog":
        header = "| api_id | 接口标识 | 调用方 | 主处理方法 | 源码锚点 |"
        rows = table_rows(doc.body, "## 接口索引", header)
        pattern = API_ID
    else:
        header = "| method_id | 符号 | 职责 | 关键性 | 关联接口 | 源码锚点 |"
        rows = table_rows(doc.body, "## 方法索引", header)
        pattern = METHOD_ID
    found: set[str] = set()
    for cells in rows:
        item_id = cells[0]
        if not pattern.fullmatch(item_id) or item_id in found or any(not cell for cell in cells):
            raise KnowledgeError(f"{doc.relative}: 索引 ID 无效、重复或有空单元格：{item_id}")
        verify_anchors(cells[-1], config, cache, f"{doc.relative}: {item_id}", sources)
        if doc.doc_type == "method_catalog" and cells[3] not in {"核心", "辅助"}:
            raise KnowledgeError(f"{doc.relative}: {item_id} 关键性只能是核心或辅助")
        expected = expected_rows.get(item_id)
        if expected:
            indexed = [expected[0], expected[1], expected[2], expected[4]] if doc.doc_type == "api_catalog" else expected[:5]
            if cells[:-1] != indexed:
                raise KnowledgeError(f"{doc.relative}: {item_id} 路由/符号/职责/关联与结构化规格不一致")
        found.add(item_id)
    expected_ids = set(expected_rows)
    if found != expected_ids:
        raise KnowledgeError(f"{doc.relative}: 索引 ID 与结构化规格不一致；缺少 {sorted(expected_ids - found)}，多出 {sorted(found - expected_ids)}")
    for item_id in found if doc.doc_type == "api_catalog" else core_ids:
        section = detail_section(doc.body, item_id)
        if section is None:
            raise KnowledgeError(f"{doc.relative}: 缺少 {item_id} 的详细小节")
        required = ("请求", "响应", "校验与权限", "失败", "数据副作用", "调用关系", "源码证据") if doc.doc_type == "api_catalog" else ("输入与输出", "关键分支", "调用关系", "数据副作用", "失败与限制", "源码证据")
        missing = [label for label in required if not re.search(rf"(?m)^[-*] {re.escape(label)}：\S", section)]
        if missing:
            raise KnowledgeError(f"{doc.relative}: {item_id} 详细小节缺少字段 {missing}；未知可填 UNKNOWN")


def validate_qa(doc: Document) -> None:
    header = "| 类别 | 真实问题 | 预期行为 | 实测结果 | 结论 |"
    rows = table_rows(doc.body, "## 问答自测", header)
    passed: set[str] = set()
    for category, question, expected, actual, result in rows:
        if category not in QA_CATEGORIES or not question or not expected or not actual:
            raise KnowledgeError(f"{doc.relative}: 问答自测类别或内容无效")
        if result != "通过":
            raise KnowledgeError(f"{doc.relative}: {category} 问答自测未通过")
        passed.add(category)
    if passed != QA_CATEGORIES:
        raise KnowledgeError(f"{doc.relative}: 问答自测须覆盖正常、失败、未知、越权四类")


def semantic_quality_enabled(config: dict, module_id: str) -> bool:
    settings = config.get("semantic_quality")
    if not isinstance(settings, dict) or settings.get("enabled") is not True:
        return False
    modules = settings["module_ids"]
    return modules == ["*"] or module_id in modules


def validate_semantic_quality(
    spec: Document,
    items: list[Document],
    facts: set[str],
    config: dict,
    cache: dict[tuple[str, str], list[str]],
    sources: set[str],
) -> tuple[int, int, int]:
    """Validate auditable semantic-review records without claiming language understanding."""
    if not semantic_quality_enabled(config, spec.module_id or ""):
        return 0, 0, 0

    closure_header = "| semantic_id | fact_id | 类型 | 名称 | 生产或写入 | 条件与顺序 | 消费或读取 | 固定提交锚点 | 未知边界 |"
    closure_rows = table_rows(spec.body, "## 高影响字段与术语闭环", closure_header)
    if not closure_rows:
        raise KnowledgeError(f"{spec.relative}: 已启用语义质量门槛，至少登记一条高影响字段或业务术语闭环")
    seen_closures: set[str] = set()
    for semantic_id, fact_id, kind, name, producer, condition, consumer, anchors, boundary in closure_rows:
        if not SEMANTIC_ID.fullmatch(semantic_id) or semantic_id in seen_closures:
            raise KnowledgeError(f"{spec.relative}: semantic_id 无效或重复：{semantic_id}")
        if fact_id not in facts or kind not in SEMANTIC_TYPES or any(not value for value in (name, producer, condition, consumer, boundary)):
            raise KnowledgeError(f"{spec.relative}: {semantic_id} 缺少有效事实、类型、生产消费条件或未知边界")
        verify_anchors(anchors, config, cache, f"{spec.relative}: {semantic_id}", sources)
        seen_closures.add(semantic_id)

    config_header = "| config_id | fact_id | 命名空间 | 键名 | 使用方式 | 缺失或异常行为 | 运行取值 | 固定提交锚点 |"
    config_rows = table_rows(spec.body, "## 动态配置闭环", config_header)
    seen_configs: set[str] = set()
    def unknown_identifier(value: str) -> bool:
        normalized = value.strip().upper()
        return normalized == "无" or "UNKNOWN" in normalized or "未知" in value or "未取证" in value

    for config_id, fact_id, namespace, key, purpose, failure, runtime_value, anchors in config_rows:
        if not CONFIG_ID.fullmatch(config_id) or config_id in seen_configs:
            raise KnowledgeError(f"{spec.relative}: config_id 无效或重复：{config_id}")
        if fact_id not in facts or unknown_identifier(namespace) or unknown_identifier(key) or any(not value for value in (namespace, key, purpose, failure, runtime_value)):
            raise KnowledgeError(f"{spec.relative}: {config_id} 须记录已取证的命名空间和键名；运行取值未知可写 UNKNOWN 并说明边界")
        verify_anchors(anchors, config, cache, f"{spec.relative}: {config_id}", sources)
        seen_configs.add(config_id)

    review_header = "| 类别 | 检查问题 | 对照文件 | 实测结果 | 结论 |"
    review_rows = table_rows(spec.body, "## 语义一致性自测", review_header)
    available = {
        doc.relative.relative_to(spec.relative.parent).as_posix()
        for doc in items
        if doc.relative.is_relative_to(spec.relative.parent)
    }
    seen_categories: set[str] = set()
    for category, question, compared, actual, result in review_rows:
        if category not in SEMANTIC_REVIEW_CATEGORIES or category in seen_categories or not question or not actual:
            raise KnowledgeError(f"{spec.relative}: 语义一致性自测类别重复、未知或内容为空")
        files = [item.strip().strip("`") for item in re.split(r"[、,，]", compared) if item.strip()]
        if not files or any(not safe_repo_path(item) or not item.endswith(".md") or item not in available for item in files):
            raise KnowledgeError(f"{spec.relative}: {category} 自测的对照文件须为本模块已有 Markdown 文件")
        if result != "通过":
            raise KnowledgeError(f"{spec.relative}: {category} 语义一致性自测未通过")
        if category == "正文一致性":
            compared_types = {TYPES.get(Path(item).name) for item in files}
            if "spec" not in compared_types or not (compared_types & BUSINESS):
                raise KnowledgeError(f"{spec.relative}: 正文一致性须同时对照结构化规格和至少一份业务正文")
        seen_categories.add(category)
    if seen_categories != SEMANTIC_REVIEW_CATEGORIES:
        missing = sorted(SEMANTIC_REVIEW_CATEGORIES - seen_categories)
        raise KnowledgeError(f"{spec.relative}: 语义一致性自测缺少类别：{missing}")
    return len(closure_rows), len(config_rows), len(review_rows)


INTENT_HEADER = "| intent_id | 业务意图标题 | 业务原因摘要 | 证据等级 | 依据 | 对应正文标题 | 发布范围 |"


def intent_rows(spec: Document) -> list[list[str]]:
    if "## 业务意图" not in spec.body:
        return []
    return table_rows(spec.body, "## 业务意图", INTENT_HEADER)


def validate_intent_structure(spec: Document, items: list[Document], config: dict) -> dict[str, int]:
    """Validate publication projection; evidence semantics are checked by Governance."""
    rows = intent_rows(spec)
    intents = [doc for doc in items if doc.doc_type == "intent"]
    if not protocol.supports(config["standard_version"], "business_intent"):
        if intents or rows:
            raise KnowledgeError(f"{spec.relative}: 当前 standard_version 不支持业务意图")
        return {"claims": 0, "published": 0, "internal": 0}
    if len(intents) > 1:
        raise KnowledgeError(f"{spec.relative}: 模块只允许一份业务意图.md")
    intent_doc = intents[0] if intents else None
    headings: list[str] = []
    if intent_doc:
        for heading in ("## 角色与目标", "## 关键规则的原因", "## 业务影响与边界"):
            if heading not in intent_doc.body:
                raise KnowledgeError(f"{intent_doc.relative}: 缺少固定章节 {heading}")
        match = re.search(r"(?ms)^## 关键规则的原因\n(.*?)(?=^## [^#]|\Z)", intent_doc.body)
        section = match.group(1) if match else ""
        headings = re.findall(r"(?m)^### (\S.+)$", section)
        if not headings or len(headings) != len(set(headings)):
            raise KnowledgeError(f"{intent_doc.relative}: 关键规则标题不得为空或重复")
    if intent_doc and not rows:
        raise KnowledgeError(f"{spec.relative}: 有业务意图正文时必须登记业务意图表")

    seen: set[str] = set()
    published_titles: list[str] = []
    questions = next((doc for doc in items if doc.doc_type == "questions"), None)
    for intent_id, title, summary, level, basis, body_title, scope in rows:
        if not INTENT_ID.fullmatch(intent_id) or intent_id in seen:
            raise KnowledgeError(f"{spec.relative}: intent_id 无效或重复：{intent_id}")
        if not title or not summary or level not in INTENT_LEVELS or scope not in INTENT_SCOPES or not basis:
            raise KnowledgeError(f"{spec.relative}: {intent_id} 缺少标题、原因、证据等级、依据或发布范围")
        if scope == "机器人知识库":
            if level not in {"BUSINESS_CONFIRMED", "DOCUMENTED"}:
                raise KnowledgeError(f"{spec.relative}: {intent_id} 未确认意图不得进入机器人知识库")
            if body_title != title:
                raise KnowledgeError(f"{spec.relative}: {intent_id} 发布意图的正文标题须与意图标题一致")
            published_titles.append(title)
        else:
            if level not in {"INFERRED", "UNKNOWN"} or body_title != "无":
                raise KnowledgeError(f"{spec.relative}: {intent_id} 仅内部意图须为 INFERRED/UNKNOWN 且不得投影到正文")
            if not questions or (intent_id not in questions.body and title not in questions.body):
                raise KnowledgeError(f"{spec.relative}: {intent_id} 未确认意图必须进入待确认事项")
        seen.add(intent_id)
    if headings != published_titles:
        raise KnowledgeError(f"{spec.relative}: 业务意图正文标题须与机器人知识库意图按表格顺序一一对应")
    return {"claims": len(rows), "published": len(published_titles), "internal": len(rows) - len(published_titles)}


def semantic_quality_counts(docs: list[Document], config: dict) -> dict[str, int]:
    counts = {"closures": 0, "configs": 0, "reviews": 0}
    for spec in (doc for doc in docs if doc.doc_type == "spec" and semantic_quality_enabled(config, doc.module_id or "")):
        counts["closures"] += len(table_rows(spec.body, "## 高影响字段与术语闭环", "| semantic_id | fact_id | 类型 | 名称 | 生产或写入 | 条件与顺序 | 消费或读取 | 固定提交锚点 | 未知边界 |"))
        counts["configs"] += len(table_rows(spec.body, "## 动态配置闭环", "| config_id | fact_id | 命名空间 | 键名 | 使用方式 | 缺失或异常行为 | 运行取值 | 固定提交锚点 |"))
        counts["reviews"] += len(table_rows(spec.body, "## 语义一致性自测", "| 类别 | 检查问题 | 对照文件 | 实测结果 | 结论 |"))
    return counts


def intent_counts(docs: list[Document], config: dict) -> dict[str, int]:
    counts = {"claims": 0, "published": 0, "internal": 0}
    by_module = {doc.module_id: [item for item in docs if item.module_id == doc.module_id] for doc in docs if doc.doc_type == "spec"}
    for spec in (doc for doc in docs if doc.doc_type == "spec"):
        value = validate_intent_structure(spec, by_module[spec.module_id], config)
        for key in counts:
            counts[key] += value[key]
    return counts


def validate_project(docs: list[Document], outline: Outline, config: dict, adapter_entries: set[str] | None, *, for_publish: bool = False) -> list[Document]:
    revisions = expected_revisions(config)
    if outline.meta.get("source_revisions") != revisions:
        raise KnowledgeError("功能大纲 source_revisions 与项目配置不一致")
    semantic_settings = config.get("semantic_quality", {})
    semantic_modules = semantic_settings.get("module_ids", [])
    if semantic_settings.get("enabled") is True and semantic_modules and semantic_modules != ["*"]:
        unknown_semantic_modules = set(semantic_modules) - set(outline.modules)
        if unknown_semantic_modules:
            raise KnowledgeError(f"semantic_quality.module_ids 未在功能大纲登记：{sorted(unknown_semantic_modules)}")
    if outline.meta["inventory_status"] == "complete":
        section = next((doc.body.split("## 盘点覆盖说明", 1)[1].split("## ", 1)[0] for doc in docs if doc.doc_type == "outline"), "")
        missing_terms = [term for term in config.get("coverage_terms", []) if term not in section]
        if missing_terms:
            raise KnowledgeError(f"盘点覆盖说明未交代配置要求的入口类别：{missing_terms}")
    if any(doc.module_id for doc in docs) and outline.meta["inventory_status"] != "complete":
        raise KnowledgeError("完整功能大纲尚未通过自检；先完成入口盘点并标记 inventory_status: complete，再写模块文件")
    cache: dict[tuple[str, str], list[str]] = {}
    for entry in outline.entries:
        verify_anchor(entry[4], config, cache)
    if outline.meta["inventory_status"] == "complete" and adapter_entries is not None:
        kind = config["inventory_adapter"].get("entry_type", "页面")
        indexed = {entry[2] for entry in outline.entries if entry[1] == kind}
        missing_entries = adapter_entries - indexed
        if missing_entries:
            sample = sorted(missing_entries)[:8]
            raise KnowledgeError(f"入口适配器有 {len(missing_entries)} 条已登记入口未列入证据索引：{sample}")
    by_module: dict[str, list[Document]] = {}
    facts_by_module = {
        doc.module_id: {row[0] for row in table_rows(doc.body, "## 入口与调用链", "| fact_id | 单一结论与条件 | 证据等级 | 固定提交锚点 | 影响的知识文件 |")}
        for doc in docs if doc.doc_type == "spec"
    }
    for doc in docs:
        if doc.module_id:
            assert doc.domain and doc.module
            known = outline.modules.get(doc.module_id)
            if not known or known[:2] != (doc.domain, doc.module):
                raise KnowledgeError(f"{doc.relative}: 未在功能大纲中以相同业务域/子模块登记")
            by_module.setdefault(doc.module_id, []).append(doc)
    for module_id, items in by_module.items():
        paths = {(doc.doc_type, doc.relative.parent) for doc in items}
        if len(paths) != len(items):
            raise KnowledgeError(f"{module_id}: 同一路径下重复文档类型")
        specs = [doc for doc in items if doc.doc_type == "spec"]
        if len(specs) != 1:
            raise KnowledgeError(f"{module_id}: 模块需要唯一的结构化规格.md")
        spec = specs[0]
        sources = document_revisions(spec, config)
        fact_count = validate_spec_facts(spec, config, cache, sources)
        fact_render.normalized_facts(spec, sys.modules[__name__])
        api_rows, method_rows, core_ids = validate_spec_catalog(spec, outline, config, cache, sources)
        validate_semantic_quality(spec, items, facts_by_module[module_id], config, cache, sources)
        validate_intent_structure(spec, items, config)
        api_ids, method_ids = set(api_rows), set(method_rows)
        published = [doc for doc in items if doc.publishable]
        if published:
            required = {"overview", "scope"} if config.get("_content_profile") != "compact" else {"overview", "rules", "faq"}
            root = Path(items[0].domain, items[0].module)
            available = {doc.doc_type for doc in published if doc.relative.parent == root}
            if not required <= available:
                raise KnowledgeError(f"{module_id}: 发布模块缺少 {sorted(required - available)}；请核对 full/compact profile")
            if for_publish:
                if not fact_count:
                    raise KnowledgeError(f"{module_id}: 发布模块的结构化规格没有事实条目")
                validate_qa(spec)
        technical = {doc.doc_type: doc for doc in published if doc.doc_type in ENGINEERING}
        for technical_doc in technical.values():
            if document_revisions(technical_doc, config) != sources:
                raise KnowledgeError(f"{technical_doc.relative}: source_revisions 须与本模块结构化规格一致")
            for match in FACT_REF.finditer(technical_doc.body):
                target = match.group("module") or module_id
                if match.group("fact") not in facts_by_module.get(target, set()):
                    raise KnowledgeError(f"{technical_doc.relative}: 事实编号未在 {target} 的规格中定义：{match.group(0)}")
        if ("api_catalog" in technical or "method_catalog" in technical) and "implementation" not in technical:
            raise KnowledgeError(f"{module_id}: 发布接口/方法知识需要已审的技术实现导航")
        if "implementation" in technical:
            if api_ids and "api_catalog" not in technical:
                raise KnowledgeError(f"{module_id}: 结构化规格有接口，发布研发知识须包含已审的接口与调用.md")
            if method_ids and "method_catalog" not in technical and config.get("_content_profile") != "compact":
                raise KnowledgeError(f"{module_id}: 结构化规格有方法，发布研发知识须包含已审的方法与源码.md")
            if method_ids and "method_catalog" not in technical and config.get("_content_profile") == "compact":
                missing = sorted(method_ids - set(re.findall(r"METHOD-[A-Za-z0-9-]+", technical["implementation"].body)))
                if missing:
                    raise KnowledgeError(f"{module_id}: compact 技术实现缺少方法定位 {missing}")
        if "api_catalog" in technical:
            validate_catalog(technical["api_catalog"], api_rows, core_ids, config, cache, sources)
        if "method_catalog" in technical:
            validate_catalog(technical["method_catalog"], method_rows, core_ids, config, cache, sources)
    selected = [doc for doc in docs if doc.publishable]
    selected_paths = {doc.relative for doc in selected}
    for doc in selected:
        without_links = LINK.sub("", doc.body)
        reference = PLAIN_MD_REF.search(without_links)
        if reference:
            line = without_links.count("\n", 0, reference.start()) + 1
            raise KnowledgeError(f"{doc.relative}: 正文第 {line} 行有纯文字文件引用 {reference.group(0)}；请改成指向发布文件的 Markdown 链接或就地说明")
        for target in LINK.findall(doc.body):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            local = unquote(target.split("#", 1)[0])
            if not local.endswith(".md"):
                continue
            joined = Path(*((doc.relative.parent / local).parts))
            normalized = Path(*[p for p in joined.parts if p != "."])
            # Resolve relative path segments without following filesystem links.
            stack: list[str] = []
            for part in normalized.parts:
                if part == "..":
                    if not stack:
                        raise KnowledgeError(f"{doc.relative}: 链接越出知识源：{target}")
                    stack.pop()
                else:
                    stack.append(part)
            if Path(*stack) not in selected_paths:
                raise KnowledgeError(f"{doc.relative}: 链接目标未发布：{target}")
    return selected


def path_is_nested(a: Path, b: Path) -> bool:
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def make_release(root: Path, selected: list[Document], release_id: str, engineering: bool,
                 config: dict, document_commit: str, outline: Outline, runtime_evidence: int,
                 specs: dict[str, Document]) -> None:
    root.mkdir(parents=True, exist_ok=False)
    docs = [doc for doc in selected if engineering or doc.doc_type in BUSINESS]
    groups: dict[tuple[str, str], list[Document]] = {}
    for doc in docs:
        target = root / doc.relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(doc.original.encode("utf-8"))
        if doc.domain and doc.module:
            groups.setdefault((doc.domain, doc.module), []).append(doc)
    domains = sorted({domain for domain, _ in groups})
    root_index = ["# 知识库目录", "", "仅列本次已审核并发布的模块。", ""]
    outline_lines = ["# 功能大纲（已发布部分）", "", "这里只列本次已审核并发布的模块；未发布范围与待处理内容不在本目录内。", ""]
    for domain in domains:
        root_index.append(f"- [{domain}]({domain}/目录.md)")
        domain_lines = [f"# {domain}：目录", ""]
        for _, module in sorted(key for key in groups if key[0] == domain):
            module_docs = groups[(domain, module)]
            domain_lines.append(f"- [{module}]({module}/目录.md)")
            outline_lines.append(f"- {domain} / [{module}]({domain}/{module}/模块概览.md)")
            module_lines = [f"# {domain} / {module}", ""]
            for doc in sorted(module_docs, key=lambda item: str(item.relative)):
                local = doc.relative.relative_to(Path(domain, module))
                module_lines.append(f"- [{local.stem}]({local.as_posix()})")
            if engineering and any(doc.doc_type in ENGINEERING for doc in module_docs):
                spec = specs[module_docs[0].module_id]
                facts = table_rows(spec.body, "## 入口与调用链", "| fact_id | 单一结论与条件 | 证据等级 | 固定提交锚点 | 影响的知识文件 |")
                fact_lines = [f"# {domain} / {module}：事实编号对照", "", "本表由已审核规格生成，仅用于定位研发正文中的事实编号。", "", "| fact_id | 结论与条件 | 证据等级 | 证据 |", "| --- | --- | --- | --- |"]
                fact_lines.extend(f"| {fact_id} | {claim} | {level} | {anchor} |" for fact_id, claim, level, anchor, _ in facts)
                (root / domain / module / "事实编号对照.md").write_text("\n".join(fact_lines) + "\n", encoding="utf-8")
                module_lines.append("- [事实编号对照](事实编号对照.md)")
            (root / domain / module / "目录.md").write_text("\n".join(module_lines) + "\n", encoding="utf-8")
        (root / domain / "目录.md").write_text("\n".join(domain_lines) + "\n", encoding="utf-8")
    (root / "目录.md").write_text("\n".join(root_index) + "\n", encoding="utf-8")
    (root / "功能大纲.md").write_text("\n".join(outline_lines) + "\n", encoding="utf-8")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    audience = "研发" if engineering else "业务"
    release = [
        "# 发布信息",
        "",
        f"内容版本：{release_id}",
        f"知识规范：{config['standard_version']}",
        f"生成工具：Code2KB Spec {IMPLEMENTATION_VERSION}",
        f"生成时间（UTC）：{stamp}",
        "",
        f"本目录由已审核内容构建，只面向{audience}读者；检索范围限于本目录。",
    ]
    boundary = publish_boundary(config, engineering, outline, selected, runtime_evidence)
    if boundary:
        release.extend(["", "## 覆盖与边界", ""] + boundary)
    if engineering:
        release.extend(["", f"文档提交：{document_commit}", "", "源码基线："])
        for role, settings in sorted(config["repositories"].items()):
            release.append(f"- {role}: {settings['commit']}")
    (root / "发布信息.md").write_text("\n".join(release) + "\n", encoding="utf-8")
    if not engineering:
        for generated in sorted(root.rglob("*.md")):
            if generated.name in {"目录.md", "功能大纲.md", "发布信息.md"}:
                scan_business_terms(sys.modules[__name__], generated.read_text(encoding="utf-8"), generated.relative_to(root).as_posix())


def publish_boundary(config: dict, engineering: bool, outline: Outline,
                     selected: list[Document], runtime_evidence: int) -> list[str]:
    modules = {doc.module_id for doc in selected if doc.module_id}
    unclassified = sum(entry[3] == "未归类" for entry in outline.entries)
    pending = sum(entry[5] == "待核查" for entry in outline.entries)
    lines = [
        f"本目录覆盖 {len(modules)} 个模块；功能大纲有 {pending} 条待核查入口，其中 {unclassified} 条尚未归类。归类不证明线上可达。",
    ]
    if engineering:
        lines.append(f"已登记运行依据 {runtime_evidence} 条；没有对应依据的结论只代表固定源码版本，不证明线上实际结果。")
        lines.append("研发正文按模块标明证据等级与运行状态；源码锚点须配合发布信息中的固定提交定位。")
    else:
        lines.append(f"运行观测资料：{runtime_evidence} 条；缺少对应观测时，不能认定线上实际结果。")
        lines.append("回答时保留正文的适用条件与未知边界；动态配置和外部服务的实际取值须另行核对。")
    text = config.get("boundary_notes", {}).get("engineering" if engineering else "business", "")
    notes = [line.strip() for line in text.replace("\\n", "\n").splitlines() if line.strip()]
    if any(re.search(r"\d+\s*(?:个模块|条(?:未归类|待核查|入口|运行依据))", line) for line in notes):
        raise KnowledgeError("boundary_notes 不得手写覆盖数量；由发布工具自动生成")
    return lines + notes


def validate_bundle(root: Path, engineering: bool) -> None:
    """Check the actual reader-visible tree, including generated navigation."""
    root = root.resolve(strict=True)
    for path in root.rglob("*.md"):
        body = path.read_text(encoding="utf-8")
        relative = path.relative_to(root)
        if path.name == "业务意图.md":
            meta, intent_body, _ = parse_frontmatter(path)
            if meta.get("document_type") != "intent":
                raise KnowledgeError(f"发布物业务意图类型无效：{relative}")
            required = ("## 角色与目标", "## 关键规则的原因", "## 业务影响与边界")
            if any(heading not in intent_body for heading in required):
                raise KnowledgeError(f"发布物业务意图缺少固定章节：{relative}")
            match = re.search(r"(?ms)^## 关键规则的原因\n(.*?)(?=^## [^#]|\Z)", intent_body)
            section = match.group(1) if match else ""
            if not re.search(r"(?m)^### \S", section):
                raise KnowledgeError(f"发布物业务意图没有已确认规则：{relative}")
        plain = PLAIN_MD_REF.search(LINK.sub("", body))
        if plain:
            raise KnowledgeError(f"发布物有未链接的文件引用：{relative} → {plain.group(0)}")
        if not engineering:
            scan_business_terms(sys.modules[__name__], body, relative.as_posix())
        for target in LINK.findall(body):
            if target.startswith(("http://", "https://", "mailto:")) or target.startswith("#"):
                continue
            local = unquote(target.split("#", 1)[0])
            if not local:
                continue
            resolved = (path.parent / local).resolve(strict=False)
            if not resolved.is_relative_to(root) or not resolved.is_file():
                raise KnowledgeError(f"发布物链接无效：{path.relative_to(root)} → {target}")
    if not engineering:
        return
    indices: dict[str, set[str]] = {}
    technical: list[tuple[Path, str, str]] = []
    for path in root.rglob("*.md"):
        if path.name not in {"技术实现.md", "接口与调用.md", "方法与源码.md"}:
            continue
        meta, body, _ = parse_frontmatter(path)
        module_id = meta.get("module_id", "")
        index_path = path.parent / "事实编号对照.md"
        if not index_path.is_file():
            raise KnowledgeError(f"研发模块缺少事实编号对照：{path.parent.relative_to(root)}")
        indices[module_id] = set(re.findall(r"(?m)^\| ((?:F-[0-9]+[a-z]?|FACT-[0-9]+)) \|", index_path.read_text(encoding="utf-8")))
        technical.append((path, module_id, body))
    for path, module_id, body in technical:
        for match in FACT_REF.finditer(body):
            target = match.group("module") or module_id
            if match.group("fact") not in indices.get(target, set()):
                raise KnowledgeError(f"发布物事实编号无定义：{path.relative_to(root)} → {match.group(0)}")


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {IMPLEMENTATION_VERSION} (default file protocol {STANDARD_VERSION}; legacy {LEGACY_STANDARD_VERSION})")
    subs = parser.add_subparsers(dest="action", required=True)
    for action in ACTIONS:
        sub = subs.add_parser(action)
        sub.add_argument("--project-root", type=Path, required=True)
        sub.add_argument("--output", choices=("text", "json"), default="text", help="可选机器响应；默认保持既有输出")
        if action.startswith("run-"):
            sub.add_argument("--run-id", required=True)
        if action == "host-next":
            sub.add_argument("--run-id", required=True)
            sub.add_argument("--host", choices=tuple(sorted(host_adapter.HOSTS)), required=True)
        if action == "run-create":
            selection = sub.add_mutually_exclusive_group(required=True)
            selection.add_argument("--module-id", action="append", help="可重复指定功能大纲中的模块")
            selection.add_argument("--all-modules", action="store_true", help="按功能大纲顺序纳入全部模块")
            sub.add_argument("--release-id", required=True)
            sub.add_argument("--batch-size", type=int, default=5)
            sub.add_argument("--business-intent", action="store_true", help="按需增加业务意图证据任务")
            sub.add_argument("--retrieval-suite", type=Path, help="显式启用发布时检索评测")
        if action in {"run-begin", "run-complete", "run-execute"}:
            sub.add_argument("--task-id", required=True)
        if action == "run-complete":
            sub.add_argument("--actor", default="")
            sub.add_argument("--note", default="")
        if action == "publish":
            sub.add_argument("--business-out", type=Path, help="兼容参数；只接受固定路径 发布/业务版")
            sub.add_argument("--engineering-out", type=Path, help="兼容参数；只接受固定路径 发布/研发版")
            sub.add_argument("--release-id", required=True)
            sub.add_argument("--with-retrieval", action="store_true")
            sub.add_argument("--retrieval-suite", type=Path)
            sub.add_argument("--retrieval-profile", choices=("full", "compact"))
        if action in {"retrieval-build", "retrieval-evaluate", "retrieval-audit"}:
            sub.add_argument("--release-id", required=True)
        if action == "relation-audit":
            sub.add_argument("--release-id", required=True)
        if action == "retrieval-build":
            sub.add_argument("--profile", choices=("full", "compact"))
        if action == "retrieval-evaluate":
            sub.add_argument("--suite", type=Path, required=True)
            sub.add_argument("--results", type=Path)
        if action == "retrieval-compare":
            sub.add_argument("--compact-project-root", type=Path, required=True)
        if action == "retrieval-query":
            sub.add_argument("--query", required=True)
            sub.add_argument("--audience", choices=("business", "engineering"), default="business")
            sub.add_argument("--top-k", type=int, default=3)
        if action == "analyze-candidates":
            sub.add_argument("--repository-id", required=True)
            sub.add_argument("--uniapp-manifest")
            sub.add_argument("--candidate-schema", choices=("0.1", "0.2"), default="0.1")
            sub.add_argument("--scope", help="0.2 格式可用的仓库内相对扫描路径")
            sub.add_argument("--adapter", choices=ADAPTER_NAMES, default="builtin-mixed", help="0.2 格式的内置 Adapter")
        if action == "migrate-protocol":
            sub.add_argument("--to", choices=(protocol.DEFAULT_VERSION,), required=True)
            mode = sub.add_mutually_exclusive_group(required=True)
            mode.add_argument("--dry-run", action="store_true")
            mode.add_argument("--apply", action="store_true")
            sub.add_argument("--plan-sha256", help="正式执行时填写预演返回的摘要")
        if action == "evidence-snapshot":
            sub.add_argument("--anchor", required=True)
        if action == "render-facts":
            sub.add_argument("--module-id", required=True)
        if action == "relation-report":
            sub.add_argument("--module-id", required=True)
        if action == "preview-upgrade":
            sub.add_argument("--module-id", required=True)
            sub.add_argument("--repository-id", required=True)
            sub.add_argument("--new-commit", required=True)
        if action in {"confirm-claims", "prepare", "approve", "policy-review"}:
            sub.add_argument("--module-id", required=True)
        if action == "impact":
            sub.add_argument("--module-id")
        if action == "prepare":
            sub.add_argument("--business-topics")
            sub.add_argument("--business-unknowns")
            sub.add_argument("--business-keywords")
            sub.add_argument("--engineering-topics")
            sub.add_argument("--engineering-unknowns")
            sub.add_argument("--engineering-keywords")
            sub.add_argument("--files", help="可选：模块内相对文件名，逗号分隔；默认全部当前正文")
            sub.add_argument("--refresh", action="store_true")
            sub.add_argument("--auto-retrieval-metadata", action="store_true")
        if action == "approve":
            sub.add_argument("--reviewed-by", required=True)
            sub.add_argument("--reviewed-at", required=True)
            sub.add_argument("--approval-note", required=True, help="人已明确批准的原话；不自动生成授权")
        if action == "policy-review":
            sub.add_argument("--evidence-file", required=True, help="项目内 自动审核记录/ 下的相对 JSON 路径")
            sub.add_argument("--executed-by", required=True, help="实际执行自动审核的 CI 或服务身份")
        if action == "audit-release":
            sub.add_argument("--release-id")
    args = parser.parse_args()
    lock = None
    locked = False
    try:
        project = args.project_root.resolve(strict=True)
        if args.action == "migrate-protocol":
            if args.apply and not args.plan_sha256 or args.dry_run and args.plan_sha256:
                raise KnowledgeError("预演不接收 --plan-sha256；执行必须提供预演摘要")
            result = protocol_migration.apply(project, args.plan_sha256) if args.apply else protocol_migration.preview(project)
            result.pop("after", None)
            print(json_text(result))
            return 0
        if args.action in {"confirm-claims", "prepare", "approve", "policy-review", "publish", "retrieval-build", "retrieval-evaluate", "recover", "run-create", "run-begin", "run-complete", "run-resume", "run-cancel"}:
            lock = run_state.project_lock(project)
            lock.__enter__()
            locked = True
            if args.action != "recover":
                run_state.require_recovered(project)
        if args.action == "recover":
            def audit_recovered_release(release_id):
                governance = Governance(project, project / "知识源", {}, [], None, sys.modules[__name__])
                result = governance.audit_release(release_id)
                actual_id = result["release_id"]
                release_root = project / "发布"
                retrieval_pointer = release_root / "当前检索版本.json"
                if retrieval_pointer.is_file() and retrieval_json(retrieval_pointer).get("release_id") == actual_id:
                    retrieval_audit.audit_in_release(release_root, actual_id)
                relation_pointer = release_root / "当前关系版本.json"
                if relation_pointer.is_file() and retrieval_json(relation_pointer).get("release_id") == actual_id:
                    relation_release.audit(release_root, actual_id)

            print(json_text({"recovered": run_state.recover_pending(project, audit_recovered_release)}))
            return 0
        if args.action == "run-create":
            _, run_config = read_config(project)
            run_docs, run_outline = read_documents(project / "知识源")
            del run_docs, run_config
            selected = list(run_outline.modules) if args.all_modules else args.module_id
            print(json_text(workflow.create(project, args.run_id, run_outline.modules, selected, args.release_id, args.batch_size, args.business_intent, args.retrieval_suite, run_outline.entries)))
            return 0
        if args.action in {"run-status", "run-next"}:
            record = workflow.load(project, args.run_id)
            status = workflow.inspect(project, record)
            print(json_text(status if args.action == "run-status" else {"next_task": status["next_task"], "conflicts": status.get("conflicts", [])}))
            return 0
        if args.action == "host-next":
            record = workflow.load(project, args.run_id)
            status = workflow.inspect(project, record)
            next_task = workflow._next(record) if status["next_task"] is not None else None
            rendered = host_adapter.render(record, next_task, args.host)
            rendered["conflicts"] = status.get("conflicts", [])
            print(json_text(rendered))
            return 0
        if args.action == "run-begin":
            print(json_text(workflow.begin(project, args.run_id, args.task_id)))
            return 0
        if args.action == "run-complete":
            print(json_text(workflow.complete(project, args.run_id, args.task_id, args.actor, args.note)))
            return 0
        if args.action == "run-execute":
            result = workflow.execute(project, args.run_id, args.task_id)
            print(json_text(result))
            return 0 if result["status"] == "completed" else 1
        if args.action == "run-resume":
            print(json_text(workflow.resume(project, args.run_id)))
            return 0
        if args.action == "run-cancel":
            print(json_text(workflow.cancel(project, args.run_id)))
            return 0
        if args.action == "evidence-snapshot":
            _, snapshot_config = read_config(project)
            verify_repos(snapshot_config)
            print(json_text(source_snapshot(args.anchor, snapshot_config["repositories"])))
            return 0
        if args.action == "preview-upgrade":
            preview_source, preview_config = read_config(project)
            verify_repos(preview_config)
            preview_docs, _ = read_documents(preview_source)
            preview_spec = next((doc for doc in preview_docs if doc.doc_type == "spec" and doc.module_id == args.module_id), None)
            if preview_spec is None:
                raise KnowledgeError("升级预览模块没有结构化规格")
            loaded = relation_model.load(preview_source, preview_spec)
            if loaded is None:
                raise KnowledgeError("升级预览模块没有关系映射")
            print(json_text(relation_upgrade.preview(loaded[0], preview_config["repositories"], args.repository_id, args.new_commit)))
            return 0
        if args.action == "analyze-candidates":
            _, candidate_config = read_config(project)
            verify_repos(candidate_config)
            repository = candidate_config["repositories"].get(args.repository_id)
            if repository is None:
                raise KnowledgeError("候选扫描的仓库 ID 未配置")
            if args.uniapp_manifest and not safe_repo_path(args.uniapp_manifest):
                raise KnowledgeError("UniApp 页面清单路径无效")
            if args.scope and (args.candidate_schema != "0.2" or not safe_repo_path(args.scope)):
                raise KnowledgeError("--scope 只用于 0.2 格式且须是安全的仓库相对路径")
            if args.candidate_schema == "0.1" and args.adapter != "builtin-mixed":
                raise KnowledgeError("--adapter 只用于候选格式 0.2")
            result = (get_adapter(args.adapter).scan(args.repository_id, repository, scope=args.scope, uniapp_manifest=args.uniapp_manifest)
                      if args.candidate_schema == "0.2" else scan_candidates(args.repository_id, repository, uniapp_manifest=args.uniapp_manifest))
            print(json_text(result))
            return 0
        if args.action == "retrieval-query":
            print(json_text(retrieval_query.query_current(project, args.query, args.audience, args.top_k, sys.modules[__name__])))
            return 0
        if args.action == "retrieval-compare":
            compact_project = args.compact_project_root.resolve(strict=True)
            releases = {}
            for target in (project, compact_project):
                base = Governance(target, target / "知识源", {}, [], None, sys.modules[__name__]).audit_release(None)
                retrieval_audit.audit_in_release(target / "发布", base["release_id"])
                releases[target] = base["release_id"]
            full_release, compact_release = project / "发布", compact_project / "发布"
            full_manifest = retrieval_json(full_release / "检索清单" / f"{releases[project]}.json")
            compact_manifest = retrieval_json(compact_release / "检索清单" / f"{releases[compact_project]}.json")
            if full_manifest["profile"] != "full" or compact_manifest["profile"] != "compact":
                raise KnowledgeError("retrieval-compare 要求分别输入 full 与 compact 检索发布项目")
            result = retrieval_profile.compare(retrieval_evaluate.load_units(full_release, full_manifest), retrieval_evaluate.load_units(compact_release, compact_manifest))
            print(json_text(result))
            return 0 if result["passed"] else 1
        if args.action == "retrieval-audit":
            governance = Governance(project, project / "知识源", {}, [], None, sys.modules[__name__])
            governance.audit_release(None)
            print(json_text(retrieval_audit.audit_in_release(project / "发布", args.release_id)))
            return 0
        if args.action == "relation-audit":
            governance = Governance(project, project / "知识源", {}, [], None, sys.modules[__name__])
            governance.audit_release(args.release_id)
            print(json_text(relation_release.audit(project / "发布", args.release_id)))
            return 0
        if args.action == "retrieval-build":
            release_root = project / "发布"
            if any(path.exists() for path in (
                release_root / "当前关系版本.json",
                release_root / "关系清单" / f"{args.release_id}.json",
                release_root / "关系输入" / args.release_id,
            )):
                raise KnowledgeError("当前发布已绑定关系清单；检索扩展须随新发布一起生成")
            result = retrieval_build.build(project, args.release_id, args.profile, sys.modules[__name__])
            retrieval_audit.audit_in_release(project / "发布", args.release_id, require_ready=False)
            print(json_text(result))
            return 0
        if args.action == "retrieval-evaluate":
            governance = Governance(project, project / "知识源", {}, [], None, sys.modules[__name__])
            governance.audit_release(None)
            retrieval_audit.audit_in_release(project / "发布", args.release_id, require_ready=False)
            report = retrieval_evaluate.evaluate_in_release(project / "发布", args.release_id, args.suite.resolve(strict=True), args.results.resolve(strict=True) if args.results else None)
            retrieval_audit.audit_in_release(project / "发布", args.release_id, require_ready=False)
            print(json_text(report))
            return 0 if report["gate_status"] == "passed" else 1
        if args.action == "audit-release":
            governance = Governance(project, project / "知识源", {}, [], None, sys.modules[__name__])
            result = governance.audit_release(args.release_id)
            release_root = project / "发布"
            relation_pointer = release_root / "当前关系版本.json"
            relation_artifacts = any(path.exists() for path in (
                release_root / "关系清单" / f"{result['release_id']}.json",
                release_root / "关系输入" / result["release_id"],
            ))
            if relation_pointer.exists() and retrieval_json(relation_pointer).get("release_id") == result["release_id"]:
                relation_artifacts = True
            if relation_artifacts:
                result["relations"] = relation_release.audit(project / "发布", result["release_id"])
            print(json_text(result))
            return 0
        source, config = read_config(project)
        docs, outline = read_documents(source)
        verify_repos(config)
        adapter_entries = registered_adapter_entries(config)
        preparing = args.action in {"impact", "confirm-claims", "prepare", "approve", "policy-review"}
        validation_docs = [replace(doc, meta={**doc.meta, "review_status": "draft"}) if preparing and doc.doc_type in BUSINESS | ENGINEERING else doc for doc in docs]
        selected = validate_project(validation_docs, outline, config, adapter_entries, for_publish=args.action == "publish")
        governance = Governance(project, source, config, docs, outline, sys.modules[__name__])
        audiences = governance.audiences()
        governance.read_evidence()
        governance.validate_evidence(for_publish=args.action == "publish")
        governance.validate_intents(for_publish=args.action == "publish")
        governance.validate_matches(for_publish=args.action == "publish")
        governance.validate_relations()
        if args.action == "relation-report":
            relation = governance.relations.get(args.module_id)
            if not relation:
                raise KnowledgeError("模块没有经校验的关系映射")
            print(json_text(relation["coverage"]))
            return 0
        if args.action == "render-facts":
            relation = governance.relations.get(args.module_id)
            if not relation:
                raise KnowledgeError("模块没有经校验的关系映射")
            external_specs = {doc.module_id: doc for doc in docs if doc.doc_type == "spec"}
            segments = fact_render.render_mapped(governance.spec(args.module_id), relation["data"], sys.modules[__name__], external_specs)
            if not segments:
                raise KnowledgeError("模块没有可生成的已证实主题事实")
            for segment in segments:
                scan_business_terms(sys.modules[__name__], segment["business"], segment["topic_id"])
            print(json_text({"module_id": args.module_id, "segments": segments}))
            return 0
        if args.action == "impact":
            print(json_text({"pending_impacts": governance.impacts(args.module_id)}))
            return 0
        if args.action == "confirm-claims":
            module_dir = source / governance.spec(args.module_id).relative.parent
            with run_state.GovernanceTransaction(project, module_dir, args.action):
                response = governance.confirm_claims(args.module_id)
            print(json_text(response))
            return 0
        if args.action == "prepare":
            if args.auto_retrieval_metadata:
                auto = retrieval_build.metadata_candidates(governance.module_docs(args.module_id))
                args.business_topics = args.business_topics or auto["business_topics"]
                args.business_unknowns = args.business_unknowns or auto["business_unknowns"]
                args.business_keywords = args.business_keywords or auto["business_keywords"]
                args.engineering_topics = args.engineering_topics or auto.get("engineering_topics")
                args.engineering_unknowns = args.engineering_unknowns or auto.get("engineering_unknowns")
                args.engineering_keywords = args.engineering_keywords or auto.get("engineering_keywords")
            if not all((args.business_topics, args.business_unknowns, args.business_keywords)):
                raise KnowledgeError("prepare 需提供业务检索字段，或启用 --auto-retrieval-metadata 并在正文中找到依据")
            module_dir = source / governance.spec(args.module_id).relative.parent
            with run_state.GovernanceTransaction(project, module_dir, args.action):
                response = governance.prepare(
                    args.module_id, args.business_topics, args.business_unknowns, args.business_keywords,
                    args.engineering_topics, args.engineering_unknowns, args.engineering_keywords,
                    args.files, args.refresh,
                )
            print(json_text(response))
            return 0
        if args.action == "approve":
            module_dir = source / governance.spec(args.module_id).relative.parent
            with run_state.GovernanceTransaction(project, module_dir, args.action):
                response = governance.approve(args.module_id, args.reviewed_by, args.reviewed_at, args.approval_note)
            print(json_text(response))
            return 0
        if args.action == "policy-review":
            module_dir = source / governance.spec(args.module_id).relative.parent
            with run_state.GovernanceTransaction(project, module_dir, args.action):
                response = governance.policy_review(args.module_id, args.evidence_file, args.executed_by)
            print(json_text(response))
            return 0
        governance.approvals(selected, for_publish=args.action == "publish")
        qa_rows = [row for doc in docs if doc.doc_type == "spec" and "## 问答自测" in doc.body for row in table_rows(doc.body, "## 问答自测", "| 类别 | 真实问题 | 预期行为 | 实测结果 | 结论 |")]
        semantic_counts = semantic_quality_counts(docs, config)
        intents = intent_counts(docs, config)
        result = {
            "implementation_version": IMPLEMENTATION_VERSION,
            "standard_version": config["standard_version"],
            "content_profile": config["_content_profile"],
            "outline_modules": len(outline.modules),
            "outline_entries": len(outline.entries),
            "unclassified_entries": sum(entry[3] == "未归类" for entry in outline.entries),
            "registered_adapter_entries": len(adapter_entries) if adapter_entries is not None else None,
            "inventory_status": outline.meta["inventory_status"],
            "qa_cases": len(qa_rows),
            "qa_passed": sum(row[4] == "通过" for row in qa_rows),
            "semantic_quality_enabled": bool(config.get("semantic_quality", {}).get("enabled")),
            "semantic_closures": semantic_counts["closures"],
            "semantic_configs": semantic_counts["configs"],
            "semantic_reviews": semantic_counts["reviews"],
            "intent_claims": intents["claims"],
            "intent_published": intents["published"],
            "intent_internal": intents["internal"],
            "entry_audiences": audiences,
            "pending_claim_impacts": len(governance.impacts()),
            "runtime_evidence": len(governance.evidence),
            "expired_runtime_evidence": [key for key, item in governance.evidence.items() if item["expired"]],
            "publishable_business": sum(doc.doc_type in BUSINESS for doc in selected),
            "publishable_technical": sum(doc.doc_type in ENGINEERING for doc in selected),
            "files": [str(doc.relative) for doc in selected],
            "warning": "锚点仅证实固定提交中存在该行；机器无法证明静态盘点穷尽、语义正确或审核人真实身份",
        }
        if governance.relations:
            result["relation_coverage"] = [item["coverage"] for _, item in sorted(governance.relations.items())]
        if args.action == "check":
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if not any(doc.doc_type == "overview" for doc in selected):
            raise KnowledgeError("没有可发布的已审业务模块")
        if args.with_retrieval and not args.retrieval_suite:
            raise KnowledgeError("--with-retrieval 需要 --retrieval-suite")
        if args.retrieval_suite and not args.with_retrieval:
            raise KnowledgeError("--retrieval-suite 只能与 --with-retrieval 一起使用")
        if args.retrieval_profile and args.retrieval_profile != config["_content_profile"]:
            raise KnowledgeError("--retrieval-profile 与项目工程配置不一致")
        expected_business = project / "发布" / "业务版"
        expected_engineering = project / "发布" / "研发版"
        supplied_business = args.business_out or expected_business
        supplied_engineering = args.engineering_out or expected_engineering
        if supplied_business.is_symlink() or supplied_engineering.is_symlink():
            raise KnowledgeError("发布输出不能是符号链接")
        business_out = supplied_business.resolve(strict=False)
        engineering_out = supplied_engineering.resolve(strict=False)
        if business_out != expected_business.resolve(strict=False) or engineering_out != expected_engineering.resolve(strict=False):
            raise KnowledgeError("兼容文件协议使用固定发布路径：发布/业务版 与 发布/研发版；历史版本由 Git 管理")
        if any(path_is_nested(a, b) for a, b in ((business_out, engineering_out), (business_out, source), (engineering_out, source))):
            raise KnowledgeError("两个输出目录与知识源目录必须彼此不相交")
        for role, settings in config["repositories"].items():
            repo = Path(settings["path"]).resolve(strict=True)
            if path_is_nested(business_out, repo) or path_is_nested(engineering_out, repo):
                raise KnowledgeError(f"发布输出不得写入 {role} 源码仓库")
        registry = governance.registry_path(args.release_id)
        if registry.exists() or governance.release_id_used_in_git(args.release_id):
            raise KnowledgeError("release-id 已作为当前或历史版本使用；请为本次发布使用新 ID")
        current_path = governance.release_root / "当前版本.json"
        if current_path.exists():
            current = json.loads(current_path.read_text(encoding="utf-8"))
            if current.get("release_id") == args.release_id:
                raise KnowledgeError("release-id 与当前版本相同；每次覆盖发布须使用新 ID")
            governance.audit_release(None)
        governance.ensure_release_history_committed()
        document_commit = governance.document_commit(selected)
        staging = Path(tempfile.mkdtemp(prefix=".发布待替换-", dir=project))
        stage_release = staging / "发布"
        backup_release = staging / "原发布"
        installed = False
        publish_transaction = None
        transaction_closed = False
        try:
            business_stage, engineering_stage = stage_release / "业务版", stage_release / "研发版"
            specs = {doc.module_id: doc for doc in docs if doc.doc_type == "spec"}
            published_modules = {doc.module_id for doc in selected if doc.module_id}
            runtime_count = sum(
                item["meta"]["module_id"] in published_modules
                and item["meta"]["evidence_type"] in {"runtime", "deployment"}
                and not item["expired"]
                for item in governance.evidence.values()
            )
            make_release(business_stage, selected, args.release_id, False, config, document_commit, outline, runtime_count, specs)
            make_release(engineering_stage, selected, args.release_id, True, config, document_commit, outline, runtime_count, specs)
            governance.retrieval_index(business_stage, selected, False)
            governance.retrieval_index(engineering_stage, selected, True)
            validate_bundle(business_stage, False)
            validate_bundle(engineering_stage, True)
            governance.scan_sensitive(business_stage)
            governance.scan_sensitive(engineering_stage)
            for doc in selected:
                if doc.doc_type in BUSINESS:
                    if (business_stage / doc.relative).read_bytes() != (engineering_stage / doc.relative).read_bytes():
                        raise KnowledgeError("业务正文在两版中必须逐字相同")
            record = governance.record(args.release_id, business_stage, engineering_stage, business_out, engineering_out, document_commit)
            stage_registry = stage_release / "版本清单" / f"{args.release_id}.json"
            atomic_write(stage_registry, json_text(record))
            pointer = governance.current_pointer(args.release_id, record, digest(stage_registry.read_bytes()))
            atomic_write(stage_release / "当前版本.json", json_text(pointer))
            atomic_write(stage_release / "当前版本.md", governance.current_markdown(pointer))
            if args.with_retrieval:
                suite_path = args.retrieval_suite.resolve(strict=True)
                retrieval_build.build_in_release(stage_release, args.release_id, config["_content_profile"], governance.generator_identity(), lambda value, where: scan_business_terms(sys.modules[__name__], value, where))
                report = retrieval_evaluate.evaluate_in_release(stage_release, args.release_id, suite_path)
                if report["gate_status"] != "passed":
                    raise KnowledgeError("检索评测未通过；基础发布和检索扩展均未替换")
                retrieval_audit.audit_in_release(stage_release, args.release_id)
            if governance.relations:
                relation_release.build(stage_release, args.release_id, governance.relations, specs)
                relation_release.audit(stage_release, args.release_id)
            publish_transaction = run_state.PublishTransaction(project, staging, args.release_id)
            if governance.release_root.exists():
                os.replace(governance.release_root, backup_release)
            os.replace(stage_release, governance.release_root)
            installed = True
            governance.audit_release(None)
            if args.with_retrieval:
                result["retrieval"] = retrieval_audit.audit_in_release(governance.release_root, args.release_id)
            if governance.relations:
                result["relations"] = relation_release.audit(governance.release_root, args.release_id)
            result["current_release"] = pointer
            result["next_step"] = f"提交整个 发布/ 并建议创建标签 kb-{args.release_id}；提交前不要开始下一次发布"
            publish_transaction.finish()
            transaction_closed = True
        except Exception:
            if publish_transaction is not None:
                if installed and governance.release_root.exists():
                    os.replace(governance.release_root, stage_release)
                if backup_release.exists() and not governance.release_root.exists():
                    os.replace(backup_release, governance.release_root)
                publish_transaction.finish()
                transaction_closed = True
            raise
        finally:
            if publish_transaction is None or transaction_closed:
                shutil.rmtree(staging)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError, KnowledgeError) as exc:
        _last_error_code.set(getattr(exc, "code", None) or (
            "E_IO" if isinstance(exc, OSError) else
            "E_VALIDATION" if isinstance(exc, KnowledgeError) else
            "E_INVALID_STATE" if isinstance(exc, ValueError) else "E_COMMAND_FAILED"
        ))
        print(f"知识库处理失败：{exc}", file=sys.stderr)
        return 1
    finally:
        if locked:
            lock.__exit__(None, None, None)


def main() -> int:
    arguments = sys.argv[1:]
    _last_error_code.set(None)
    if not any(arguments[index:index + 2] == ["--output", "json"] for index in range(len(arguments) - 1)):
        return _main()
    standard, diagnostic = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(standard), contextlib.redirect_stderr(diagnostic):
            code = _main()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    raw = standard.getvalue().strip()
    try:
        result = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        result = {"text": raw}
    message = diagnostic.getvalue().strip()
    command = next((item for item in arguments if item in ACTIONS), None)
    envelope = {"response_schema_version": "0.1", "command": command,
                "status": "completed" if code == 0 else "failed",
                "error_code": None if code == 0 else "E_ARGUMENT" if "usage:" in message else _last_error_code.get() or "E_COMMAND_FAILED",
                "result": result, "diagnostics": message.splitlines() if message else [],
                "next_steps": [] if code == 0 else ["先检查诊断信息；如有未完成事务，执行 recover 后再重试"]}
    print(json_text(envelope))
    if message:
        print(message, file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
