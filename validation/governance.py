"""Module approval snapshots, claim impact, evidence, and Git-backed releases."""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from types import SimpleNamespace
from urllib.parse import quote

try:
    from . import relation_model, fact_render, run_state
except ImportError:
    import relation_model, fact_render, run_state


FILES_HEADER = "| 文件 | document_type | 内容摘要 |"
CLAIMS_HEADER = "| fact_id | 知识文件 | 结论摘要 | 文件摘要 | 复核结果 |"
MATCH_HEADER = "| api_id | 匹配状态 | 调用方证据 | 服务方证据 | 部署配对 | 差异或边界 |"
AUDIENCE_HEADER = "| entry_id | 受众 | 范围 |"
FACT_HEADER = "| fact_id | 单一结论与条件 | 证据等级 | 固定提交锚点 | 影响的知识文件 |"
RELATION_HEADER = "| 文件 | 内容摘要 |"
RELATION_REVIEW_HEADER = "| 文件 | 内容摘要 | 复核结果 |"
SHA = re.compile(r"[0-9a-f]{64}\Z")
RELEASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")
EVIDENCE_ID = re.compile(r"EVID-[A-Za-z0-9-]+\Z")
HUMAN_REVIEW_KEYS = {"review_status", "reviewed_by", "reviewed_at"}
POLICY_REVIEW_KEYS = {
    "review_status", "review_mode", "review_policy", "policy_version", "policy_owner",
    "executed_by", "reviewed_at", "review_evidence", "review_evidence_digest", "policy_digest",
}
REVIEW_KEYS = HUMAN_REVIEW_KEYS | POLICY_REVIEW_KEYS
REVIEW_STAMP_KEYS = REVIEW_KEYS | {
    "approval_note", "approval_snapshot", "policy_review_snapshot", "review_subject_digest",
}
POLICY_ID = re.compile(r"[a-z][a-z0-9_.-]{2,79}\Z")
POLICY_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,119}\Z")
CHECK_ID = re.compile(r"(?:[a-z][a-z0-9_]{1,63}|external\.[a-z][a-z0-9_.-]{1,63})\Z")
RISK_LEVELS = {"low", "medium", "high", "critical"}
FINDING_STATUSES = {"resolved", "accepted_boundary", "blocking"}
NATIVE_CHECKS = {
    "knowledge_check", "impact_clear", "qa_four_categories", "source_traceability",
    "cross_module_consistency", "sensitive_scan",
}
POLICY_FIELDS = {
    "schema_version", "policy_id", "policy_version", "policy_owner", "authorized_at",
    "authorization_note", "expires_at", "allowed_module_ids", "allowed_risk_levels",
    "required_checks", "manual_gate_categories",
}
REVIEW_RECORD_FIELDS = {
    "schema_version", "run_id", "module_id", "policy_id", "policy_version",
    "review_subject_digest", "risk_level", "source_revisions", "checks", "findings",
    "external_reports", "completed_at", "executed_by",
}


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def scan_business_terms(core, text: str, where: str, *, source_urls: bool = True) -> None:
    """业务版生成文本不得出现过程用语、内部编号或实现术语（研发版不受此限）。"""
    for number, line in enumerate(text.split("\n"), 1):
        if core.TECHNICAL.search(line) or core.BUSINESS_FORBIDDEN.search(line):
            raise ValueError(f"业务版生成内容含禁用表述（{where}:{number}）：{line.strip()[:80]}；请修正发布清单主题或发布信息边界文案后重试")
        if source_urls and core.contains_source_repository_url(line):
            raise ValueError(f"业务版生成内容含源码仓库链接（{where}:{number}）；请移至研发专属内容")


def release_checks_source_urls(version: str) -> bool:
    """New releases enforce the URL rule; older frozen releases keep their rules."""
    match = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)", version)
    return not match or tuple(int(part) for part in match.groups()) >= (1, 0, 0)


def content_digest(original: str) -> str:
    """Review stamps do not change the content the human approved."""
    lines = original.splitlines(keepends=True)
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), 0)
    return digest("".join(line for i, line in enumerate(lines) if not (0 < i < end and line.split(":", 1)[0] in REVIEW_KEYS)))


def replace_meta(original: str, updates: dict[str, str | None]) -> str:
    lines = original.splitlines(keepends=True)
    end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    kept = [line for line in lines[1:end] if line.split(":", 1)[0] not in updates]
    return lines[0] + "".join(kept) + "".join(f"{key}: {value}\n" for key, value in updates.items() if value is not None) + "".join(lines[end:])


def replace_section(original: str, heading: str, section: str) -> str:
    pattern = re.compile(rf"(?ms)^{re.escape(heading)}\n.*?(?=^## |\Z)")
    if pattern.search(original):
        return pattern.sub(lambda _: section.rstrip() + "\n\n", original, count=1)
    return original.rstrip() + "\n\n" + section.rstrip() + "\n"


def atomic_write(path: Path, value: str) -> None:
    if path.is_symlink():
        raise ValueError(f"治理文件不能是符号链接：{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    if temp.exists() or temp.is_symlink():
        raise ValueError(f"发现未处理的临时治理文件：{temp}")
    run_state.record_governance_write(path, value.encode("utf-8"))
    try:
        with temp.open("x", encoding="utf-8") as stream:
            stream.write(value)
        os.replace(temp, path)
    finally:
        if temp.is_file() and not temp.is_symlink():
            temp.unlink()


def json_text(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def approval_digest(original: str) -> str:
    # The record covers its topics, unknowns, approval identity and note as well as file hashes.
    return digest(replace_meta(original, {"approval_snapshot": None}))


def review_subject_digest(original: str) -> str:
    """Bind candidate contents and boundaries without binding later review stamps."""
    return digest(replace_meta(original, {key: None for key in REVIEW_STAMP_KEYS}))


def policy_review_digest(original: str) -> str:
    return digest(replace_meta(original, {"policy_review_snapshot": None}))


def clear_review_meta(original: str, *, keep_subject: bool = True) -> str:
    keys = REVIEW_STAMP_KEYS - ({"review_subject_digest"} if keep_subject else set())
    return replace_meta(original, {key: None for key in keys})


def draft_review_meta(original: str, *, keep_subject: bool = False) -> str:
    return replace_meta(clear_review_meta(original, keep_subject=keep_subject), {"review_status": "draft"})


def strict_json(path: Path, allowed: set[str], label: str) -> tuple[dict, bytes]:
    raw = path.read_bytes()

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"{label}包含重复字段：{key}")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}不是有效 UTF-8 JSON") from exc
    if not isinstance(value, dict) or set(value) != allowed:
        raise ValueError(f"{label}字段不完整或含未知字段")
    return value, raw


class Governance:
    def __init__(self, project, source, config, docs, outline, core):
        self.project, self.source, self.config = project, source, config
        self.docs, self.outline, self.core = docs, outline, core
        self.by_path = {doc.relative.as_posix(): doc for doc in docs}
        self.evidence = {}
        self.evidence_dependencies = {}
        self.policy_inputs = set()
        self.module_reviews = {}
        self.relations = {}
        self.release_root = project / "发布"
        if self.release_root.is_symlink():
            raise ValueError("发布治理目录不能是符号链接")

    def project_json(self, local, label, required_root=None):
        if not isinstance(local, str) or not self.core.safe_repo_path(local) or not local.endswith(".json"):
            raise ValueError(f"{label}须为项目内相对 JSON 路径")
        relative = Path(*PurePosixPath(local).parts)
        if required_root and (not relative.parts or relative.parts[0] != required_root):
            raise ValueError(f"{label}须位于 {required_root}/")
        path = self.project / relative
        if not path.is_file():
            raise ValueError(f"{label}不存在：{local}")
        current = path
        while current != self.project:
            if current.is_symlink():
                raise ValueError(f"{label}不能是符号链接：{local}")
            current = current.parent
        return path

    def git_head_matches(self, path, label):
        root = subprocess.run(["git", "-C", str(self.project), "rev-parse", "--show-toplevel"], text=True, capture_output=True)
        if root.returncode or Path(root.stdout.strip()).resolve() != self.project:
            raise ValueError("策略审核需要独立的文档 Git 仓库")
        local = path.relative_to(self.project).as_posix()
        saved = subprocess.run(["git", "-C", str(self.project), "show", f"HEAD:{local}"], capture_output=True)
        if saved.returncode or saved.stdout != path.read_bytes():
            raise ValueError(f"{label}未提交或与当前 Git HEAD 不一致：{local}")

    def sensitive_patterns(self):
        return [r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", r"\bAKIA[0-9A-Z]{16}\b", *self.config.get("sensitive_patterns", [])]

    def scan_sensitive_files(self, paths):
        for path in sorted(set(paths)):
            body = path.read_text(encoding="utf-8")
            for index, pattern in enumerate(self.sensitive_patterns()):
                if re.search(pattern, body):
                    try:
                        local = path.relative_to(self.project)
                    except ValueError:
                        local = path
                    raise ValueError(f"审核输入命中敏感信息规则 {index + 1}：{local}；先脱敏后重新审核")

    def read_policy(self, *, require_head=True):
        settings = self.config.get("policy_review")
        if not isinstance(settings, dict) or settings.get("enabled") is not True:
            raise ValueError("项目没有启用策略化自动审核")
        config_path = self.project / "知识库配置.json"
        path = self.project_json(settings.get("policy_file"), "自动审核策略")
        if require_head:
            self.git_head_matches(config_path, "知识库配置")
            self.git_head_matches(path, "自动审核策略")
        policy, raw = strict_json(path, POLICY_FIELDS, "自动审核策略")
        if policy["schema_version"] != "1.0" or not isinstance(policy["policy_id"], str) or not POLICY_ID.fullmatch(policy["policy_id"]):
            raise ValueError("自动审核策略 schema_version 或 policy_id 无效")
        if not isinstance(policy["policy_version"], str) or not POLICY_VERSION.fullmatch(policy["policy_version"]):
            raise ValueError("自动审核策略 policy_version 须为三段数字版本")
        for key in ("policy_owner", "authorization_note"):
            if not isinstance(policy[key], str) or not policy[key].strip() or any(char in policy[key] for char in "\r\n"):
                raise ValueError(f"自动审核策略 {key} 无效")
        try:
            authorized = date.fromisoformat(policy["authorized_at"])
            expires = date.fromisoformat(policy["expires_at"])
        except (TypeError, ValueError) as exc:
            raise ValueError("自动审核策略日期须为 YYYY-MM-DD") from exc
        if expires < authorized or expires < date.today():
            raise ValueError("自动审核策略已过期或日期范围无效")
        arrays = ("allowed_module_ids", "allowed_risk_levels", "required_checks", "manual_gate_categories")
        if any(not isinstance(policy[key], list) or not policy[key] or not all(isinstance(item, str) and item for item in policy[key]) or len(policy[key]) != len(set(policy[key])) for key in arrays):
            raise ValueError("自动审核策略数组须非空且不得重复")
        modules = policy["allowed_module_ids"]
        if modules != ["*"] and any(not re.fullmatch(r"[a-z][a-z0-9_.-]*", item) for item in modules):
            raise ValueError("自动审核策略 allowed_module_ids 无效")
        if not set(policy["allowed_risk_levels"]) <= RISK_LEVELS:
            raise ValueError("自动审核策略包含未知风险等级")
        checks = set(policy["required_checks"])
        if not NATIVE_CHECKS <= checks or any(not CHECK_ID.fullmatch(item) or (item not in NATIVE_CHECKS and not item.startswith("external.")) for item in checks):
            raise ValueError("自动审核策略必须包含全部参考实现内置检查，外部检查须使用 external.*")
        if any(not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", item) for item in policy["manual_gate_categories"]):
            raise ValueError("自动审核策略 manual_gate_categories 无效")
        self.scan_sensitive_files([config_path, path])
        return policy, path, digest(raw), authorized, expires

    def read_review_record(self, local):
        path = self.project_json(local, "自动审核记录", "自动审核记录")
        record, raw = strict_json(path, REVIEW_RECORD_FIELDS, "自动审核记录")
        return record, path, digest(raw)

    def validate_review_record(self, module_id, manifest, policy, record, executed_by, authorized, expires):
        if record["schema_version"] != "1.0" or not isinstance(record["run_id"], str) or not RUN_ID.fullmatch(record["run_id"]):
            raise ValueError("自动审核记录 schema_version 或 run_id 无效")
        if record["module_id"] != module_id or record["policy_id"] != policy["policy_id"] or record["policy_version"] != policy["policy_version"]:
            raise ValueError("自动审核记录的模块或策略版本不匹配")
        subject = manifest.meta.get("review_subject_digest")
        if not SHA.fullmatch(subject or "") or subject != review_subject_digest(manifest.original) or record["review_subject_digest"] != subject:
            raise ValueError("自动审核记录与当前候选内容摘要不一致")
        if modules := policy["allowed_module_ids"]:
            if modules != ["*"] and module_id not in modules:
                raise ValueError("当前模块不在自动审核策略范围内")
        if not isinstance(record["risk_level"], str) or record["risk_level"] not in RISK_LEVELS or record["risk_level"] not in policy["allowed_risk_levels"]:
            raise ValueError("自动审核记录风险等级不在策略允许范围")
        spec = self.spec(module_id)
        roles = self.core.document_revisions(spec, self.config)
        expected_sources = {role: self.config["repositories"][role]["commit"] for role in sorted(roles)}
        if record["source_revisions"] != expected_sources:
            raise ValueError("自动审核记录源码提交与模块固定基线不一致")
        if not isinstance(record["executed_by"], str) or record["executed_by"] != executed_by or not executed_by or any(char in executed_by for char in "\r\n"):
            raise ValueError("自动审核记录 executed_by 与命令执行身份不一致")
        if executed_by == policy["policy_owner"]:
            raise ValueError("自动执行身份不得冒充策略授权人")
        try:
            completed = datetime.fromisoformat(record["completed_at"].replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise ValueError("自动审核记录 completed_at 须为带时区时间") from exc
        if completed.tzinfo is None or completed.utcoffset() is None:
            raise ValueError("自动审核记录 completed_at 须带时区")
        completed_date = completed.date()
        if completed_date < authorized or completed_date > expires or completed.astimezone(timezone.utc) > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("自动审核记录时间超出策略授权范围或明显在未来")
        checks = record["checks"]
        if not isinstance(checks, list) or not checks:
            raise ValueError("自动审核记录缺少 checks")
        found = {}
        for item in checks:
            if not isinstance(item, dict) or set(item) != {"check_id", "status", "report_sha256"}:
                raise ValueError("自动审核记录 check 结构无效")
            check_id = item["check_id"]
            if not isinstance(check_id, str) or not CHECK_ID.fullmatch(check_id) or (check_id not in NATIVE_CHECKS and not check_id.startswith("external.")) or check_id in found or item["status"] != "passed" or not SHA.fullmatch(item["report_sha256"] if isinstance(item["report_sha256"], str) else ""):
                raise ValueError("自动审核记录 check 重复、失败或摘要无效")
            found[check_id] = item
        if not set(policy["required_checks"]) <= set(found):
            raise ValueError("自动审核记录缺少策略要求的通过检查")
        reports = record["external_reports"]
        if not isinstance(reports, list):
            raise ValueError("自动审核记录 external_reports 须为数组")
        report_names = set()
        for item in reports:
            if not isinstance(item, dict) or set(item) != {"name", "result", "sha256"} or not isinstance(item["name"], str) or not item["name"].startswith("external.") or not CHECK_ID.fullmatch(item["name"]) or item["name"] in report_names or item["result"] != "passed" or not SHA.fullmatch(item["sha256"] if isinstance(item["sha256"], str) else ""):
                raise ValueError("自动审核记录外部报告结构、结果或摘要无效")
            report_names.add(item["name"])
        required_external = {item for item in policy["required_checks"] if item.startswith("external.")}
        if not required_external <= report_names:
            raise ValueError("自动审核记录缺少外部检查报告摘要")
        reports_by_name = {item["name"]: item for item in reports}
        if any(found[name]["report_sha256"] != reports_by_name[name]["sha256"] for name in required_external):
            raise ValueError("自动审核记录的外部检查摘要与报告摘要不一致")
        findings = record["findings"]
        if not isinstance(findings, list):
            raise ValueError("自动审核记录 findings 须为数组")
        finding_ids = set()
        gates = set(policy["manual_gate_categories"])
        for item in findings:
            required = {"finding_id", "category", "severity", "status", "summary"}
            if not isinstance(item, dict) or set(item) != required:
                raise ValueError("自动审核记录 finding 结构无效")
            if not isinstance(item["finding_id"], str) or not RUN_ID.fullmatch(item["finding_id"]) or item["finding_id"] in finding_ids:
                raise ValueError("自动审核记录 finding_id 无效或重复")
            if not isinstance(item["category"], str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", item["category"]) or not isinstance(item["severity"], str) or item["severity"] not in RISK_LEVELS or not isinstance(item["status"], str) or item["status"] not in FINDING_STATUSES or not isinstance(item["summary"], str) or not item["summary"].strip():
                raise ValueError("自动审核记录 finding 字段无效")
            if item["severity"] == "critical" or item["status"] == "blocking" or (item["category"] in gates and item["status"] != "resolved"):
                raise ValueError("自动审核记录包含必须转人工处理的发现")
            finding_ids.add(item["finding_id"])
        if self.impacts(module_id):
            raise ValueError("模块存在待复核结论，不能策略审核")
        self.core.validate_qa(spec)
        return completed_date.isoformat()

    def module_docs(self, module_id):
        items = [doc for doc in self.docs if doc.module_id == module_id]
        if not items:
            raise ValueError(f"没有已取证的模块：{module_id}")
        return items

    def spec(self, module_id):
        return next(doc for doc in self.module_docs(module_id) if doc.doc_type == "spec")

    def audiences(self):
        if self.outline.meta["inventory_status"] != "complete":
            return {}
        outline_doc = next(doc for doc in self.docs if doc.doc_type == "outline")
        rows = self.core.table_rows(outline_doc.body, "## 入口受众", AUDIENCE_HEADER)
        found = {}
        for entry, audience, scope in rows:
            if entry in found or audience not in {"用户操作", "后台操作", "系统自动", "外部依赖", "待核查"} or scope not in {"范围内", "关联影响", "范围外"}:
                raise ValueError(f"入口受众/范围无效或重复：{entry}")
            found[entry] = audience
        if set(found) != {entry[0] for entry in self.outline.entries}:
            raise ValueError("入口受众必须逐项覆盖入口索引，不能用代表条目替代已登记入口")
        return dict(Counter(found.values()))

    def read_evidence(self):
        root = self.project / "运行证据"
        if not root.exists():
            return
        self.core.ensure_no_symlinks(root)
        if root.is_symlink():
            raise ValueError("运行证据目录不能是符号链接")
        for path in sorted(root.rglob("*.md")):
            meta, body, original = self.core.parse_frontmatter(path)
            if meta.get("applicability", "current") == "superseded":
                continue
            if meta.get("applicability", "current") != "current":
                raise ValueError(f"运行证据 applicability 无效：{path}")
            evidence_id = meta.get("evidence_id", "")
            if not EVIDENCE_ID.fullmatch(evidence_id) or evidence_id in self.evidence:
                raise ValueError(f"运行证据 ID 无效或重复：{path}")
            if meta.get("document_type") != "runtime_evidence" or meta.get("evidence_type") not in {"runtime", "business", "deployment"}:
                raise ValueError(f"运行证据类型无效：{path}")
            if meta.get("module_id") not in self.outline.modules or not meta.get("environment") or not meta.get("fact_ids"):
                raise ValueError(f"运行证据缺少模块、环境或限定事实：{path}")
            observed = date.fromisoformat(meta.get("observed_at", ""))
            expiry = date.fromisoformat(meta["valid_until"]) if meta.get("valid_until") else None
            if observed > date.today() or (expiry and expiry < observed):
                raise ValueError(f"运行证据日期范围无效：{path}")
            if meta.get("evidence_type") == "business":
                required = ("source_type", "source_title", "source_locator", "source_sha256", "content_mode", "intent_ids", "valid_until")
                if any(not meta.get(key) for key in required):
                    raise ValueError(f"业务证据缺少来源、摘要、脱敏或意图绑定字段：{path}")
                if meta["source_type"] not in {"document", "human"} or meta["content_mode"] != "redacted_excerpt" or not SHA.fullmatch(meta["source_sha256"]):
                    raise ValueError(f"业务证据的 source_type、content_mode 或 source_sha256 无效：{path}")
                if any(meta[key].strip() in {"UNKNOWN", "无", "待确认"} for key in ("source_title", "source_locator")):
                    raise ValueError(f"业务证据必须提供可回查的来源标题与位置：{path}")
                intent_ids = {value.strip() for value in meta["intent_ids"].split(",") if value.strip()}
                if not intent_ids or any(not self.core.INTENT_ID.fullmatch(value) for value in intent_ids):
                    raise ValueError(f"业务证据 intent_ids 无效：{path}")
                if meta["source_type"] == "human":
                    if any(not meta.get(key) for key in ("confirmed_by", "confirmed_at", "confirmation_note")):
                        raise ValueError(f"人工确认证据缺少确认人、时间或边界：{path}")
                    date.fromisoformat(meta["confirmed_at"])
            if meta.get("source_revisions"):
                sources = self.core.document_revisions(SimpleNamespace(relative=path.relative_to(self.project), meta=meta), self.config)
            elif meta.get("evidence_type") == "business":
                sources = set()
            else:
                raise ValueError(f"运行或部署证据必须绑定 source_revisions：{path}")
            for heading in ("来源与方法", "观察或确认结果", "适用范围与不能证明的事项", "脱敏说明"):
                match = re.search(rf"(?ms)^## {heading}\n(.+?)(?=^## |\Z)", body)
                if not match or not match.group(1).strip():
                    raise ValueError(f"运行证据缺少有效章节 {heading}：{path}")
            self.evidence[evidence_id] = {"meta": meta, "path": path, "original": original, "sources": sources, "expired": bool(expiry and expiry < date.today())}
        self.scan_sensitive_files(item["path"] for item in self.evidence.values())

    def evidence_ref(self, evidence_id, module_id, fact_id=None, kind=None, for_publish=False):
        item = self.evidence.get(evidence_id)
        if not item or item["meta"]["module_id"] != module_id:
            raise ValueError(f"证据未登记或模块不符：{evidence_id}")
        ids = {value.strip() for value in item["meta"]["fact_ids"].split(",")}
        if fact_id and fact_id not in ids:
            raise ValueError(f"证据不覆盖该事实：{evidence_id} → {fact_id}")
        if kind and item["meta"]["evidence_type"] not in kind:
            raise ValueError(f"证据类型不支持该结论：{evidence_id}")
        if for_publish and item["expired"]:
            raise ValueError(f"运行证据已失效：{evidence_id}")
        self.evidence_dependencies.setdefault(module_id, set()).add(evidence_id)
        return item

    def validate_evidence(self, for_publish=False):
        released_modules = {doc.module_id for doc in self.docs if doc.publishable}
        for spec in (doc for doc in self.docs if doc.doc_type == "spec"):
            rows = self.core.table_rows(spec.body, "## 入口与调用链", FACT_HEADER)
            facts = {row[0] for row in rows}
            for item in self.evidence.values():
                if item["meta"]["module_id"] == spec.module_id:
                    declared = {value.strip() for value in item["meta"]["fact_ids"].split(",") if value.strip() and value.strip() != "无"}
                    if not declared <= facts:
                        raise ValueError(f"运行证据引用不存在的 fact_id：{declared - facts}")
            for fact_id, _, level, anchors, _ in rows:
                if level in {"RUN_VERIFIED", "BUSINESS_CONFIRMED"}:
                    ids = [value.strip() for value in anchors.split(",")]
                    kinds = {"runtime", "deployment"} if level == "RUN_VERIFIED" else {"business"}
                    for evidence_id in ids:
                        item = self.evidence_ref(evidence_id, spec.module_id, fact_id, kinds, for_publish and spec.module_id in released_modules)
                        if not item["sources"] <= self.core.document_revisions(spec, self.config):
                            raise ValueError(f"运行证据超出模块源码基线：{evidence_id}")
        for doc in (doc for doc in self.docs if doc.doc_type in self.core.ENGINEERING):
            status = doc.meta.get("runtime_status")
            if status == "runtime_verified":
                ids = [value.strip() for value in doc.meta.get("runtime_evidence", "").split(",") if value.strip()]
                if not ids:
                    raise ValueError(f"{doc.relative}: runtime_verified 需要限定范围的 runtime_evidence")
                for evidence_id in ids:
                    self.evidence_ref(evidence_id, doc.module_id, kind={"runtime", "deployment"}, for_publish=for_publish and doc.publishable)
            elif status == "verified_deployment":
                self.evidence_ref(doc.meta.get("deployment_evidence", ""), doc.module_id, kind={"deployment"}, for_publish=for_publish and doc.publishable)

    def validate_intents(self, for_publish=False):
        """Require a complete business-evidence -> intent -> behavior-fact chain for published intent text."""
        for spec in (doc for doc in self.docs if doc.doc_type == "spec"):
            rows = self.core.intent_rows(spec)
            module_business_evidence = {
                evidence_id: item
                for evidence_id, item in self.evidence.items()
                if item["meta"]["module_id"] == spec.module_id
                and item["meta"]["evidence_type"] == "business"
            }
            if not rows:
                if module_business_evidence and self.core.protocol.supports(self.config["standard_version"], "business_evidence"):
                    raise ValueError(f"{spec.relative}: 已登记业务证据但没有业务意图表")
                continue
            fact_rows = {
                row[0]: row
                for row in self.core.table_rows(spec.body, "## 入口与调用链", FACT_HEADER)
            }
            defined_intents = {row[0] for row in rows}
            for evidence_id, item in module_business_evidence.items():
                covered = {value.strip() for value in item["meta"].get("intent_ids", "").split(",") if value.strip()}
                if not covered <= defined_intents:
                    raise ValueError(f"{spec.relative}: {evidence_id} 引用了未定义意图：{covered - defined_intents}")
            for intent_id, _, _, level, basis, _, scope in rows:
                refs = [value.strip() for value in re.split(r"[,，]", basis) if value.strip() and value.strip() != "无"]
                evidences = [value for value in refs if EVIDENCE_ID.fullmatch(value)]
                facts = [value for value in refs if value in fact_rows]
                unknown = [value for value in refs if value not in evidences and value not in facts]
                if unknown:
                    raise ValueError(f"{spec.relative}: {intent_id} 依据含未定义引用：{unknown}")
                if scope != "机器人知识库":
                    continue
                if not evidences or not facts:
                    raise ValueError(f"{spec.relative}: {intent_id} 进入机器人知识库须同时引用业务证据和行为事实")
                expected_source = "human" if level == "BUSINESS_CONFIRMED" else "document"
                for evidence_id in evidences:
                    item = self.evidence_ref(evidence_id, spec.module_id, kind={"business"}, for_publish=for_publish)
                    if item["meta"].get("source_type") != expected_source:
                        raise ValueError(f"{spec.relative}: {intent_id} 证据来源与证据等级不匹配")
                    covered = {value.strip() for value in item["meta"].get("intent_ids", "").split(",") if value.strip()}
                    if intent_id not in covered:
                        raise ValueError(f"{spec.relative}: {evidence_id} 未明确覆盖 {intent_id}")
                    if not covered <= defined_intents:
                        raise ValueError(f"{spec.relative}: {evidence_id} 引用了未定义意图：{covered - defined_intents}")
                for fact_id in facts:
                    affected = {value.strip().strip("`") for value in re.split(r"[,，、]", fact_rows[fact_id][4])}
                    if "业务意图.md" not in affected:
                        raise ValueError(f"{spec.relative}: {fact_id} 未在影响文件中登记业务意图.md")

    def bound_evidence_ids(self, module_id):
        return set(self.evidence_dependencies.get(module_id, set()))

    def validate_relations(self):
        specs = [doc for doc in self.docs if doc.doc_type == "spec"]
        qualified_facts = {
            f"{spec.module_id}#{row[0]}"
            for spec in specs
            for row in self.core.table_rows(spec.body, "## 入口与调用链", FACT_HEADER)
        }
        for spec in specs:
            loaded = relation_model.load(self.source, spec)
            if loaded is None:
                continue
            data, raw = loaded
            known, derived, matches = relation_model.catalog(self.core, spec, self.outline)
            external_facts = {value for value in qualified_facts if not value.startswith(f"{spec.module_id}#")}
            validation_known = {**known, "fact": known["fact"] | external_facts}
            relation_model.validate(data, known=validation_known, module_dir=self.source / spec.relative.parent, repositories=self.config["repositories"])
            links = relation_model.merged_links(data, derived, matches)
            path = relation_model.mapping_path(self.source, spec)
            self.scan_sensitive_files([path])
            self.relations[spec.module_id] = {
                "path": path, "data": data, "raw": raw, "links": links, "sha256": digest(raw),
                "coverage": relation_model.coverage(spec.module_id, known, data["topics"], links),
            }

    def validate_matches(self, for_publish=False):
        cache = {}
        released_modules = {doc.module_id for doc in self.docs if doc.publishable}
        for spec in (doc for doc in self.docs if doc.doc_type == "spec"):
            api_ids = {row[0] for row in self.core.table_rows(spec.body, "## 接口契约", "| api_id | 接口标识 | 调用方 | 服务入口 | 主处理方法 | 证据 |")}
            rows = self.core.table_rows(spec.body, "## 调用匹配", MATCH_HEADER)
            found = set()
            sources = self.core.document_revisions(spec, self.config)
            for api_id, status, caller, service, deployment, boundary in rows:
                if api_id in found or status not in {"已匹配", "疑似匹配", "未匹配", "外部依赖"} or not boundary:
                    raise ValueError(f"调用匹配状态无效：{api_id}")
                for value in (caller, service):
                    if value not in {"无", "UNKNOWN"}:
                        self.core.verify_anchors(value, self.config, cache, api_id, sources)
                if status == "已匹配" and (caller in {"无", "UNKNOWN"} or service in {"无", "UNKNOWN"}):
                    raise ValueError(f"已匹配须有调用方和服务方证据：{api_id}")
                if deployment != "未验证":
                    self.evidence_ref(deployment, spec.module_id, kind={"deployment"}, for_publish=for_publish and spec.module_id in released_modules)
                found.add(api_id)
            if found != api_ids:
                raise ValueError(f"调用匹配表须覆盖全部接口：{spec.relative}")
            for doc in self.module_docs(spec.module_id):
                if doc.doc_type == "api_catalog" and doc.publishable:
                    if self.core.table_rows(doc.body, "## 调用匹配", MATCH_HEADER) != rows:
                        raise ValueError(f"{doc.relative}: 调用匹配与结构化规格不一致")

    def expected_claims(self, spec):
        rows = self.core.table_rows(spec.body, "## 入口与调用链", FACT_HEADER)
        normalized = fact_render.normalized_facts(spec, self.core)
        targets = {}
        for row in rows:
            fact_id, _, _, _, affected = row
            fingerprint_input = [row, normalized[fact_id]] if fact_id in normalized else row
            fingerprint = digest(json.dumps(fingerprint_input, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
            for local in re.split(r"[、,，]", affected):
                local = local.strip().strip("`")
                if not self.core.safe_repo_path(local) or not local.endswith(".md"):
                    raise ValueError(f"{spec.relative}: 影响文件须为模块内相对 Markdown 路径：{local}")
                relative = (spec.relative.parent / local).as_posix()
                doc = self.by_path.get(relative)
                if doc and doc.doc_type in {"spec", "release_manifest"}:
                    raise ValueError(f"结论不能以自身规格或发布清单作为知识投影：{relative}")
                targets[(fact_id, local)] = [fact_id, local, fingerprint, content_digest(doc.original) if doc else "缺失", "已复核"]
        return targets

    def cross_module_fact_digest(self, module_id):
        """Fingerprint only explicitly referenced foreign facts, never similar text."""
        relation = self.relations.get(module_id)
        if not relation:
            return None
        references = sorted({
            link["from_id"] for link in relation["data"]["links"]
            if link["from_type"] == "fact" and link["to_type"] == "topic" and "#" in link["from_id"]
        })
        if not references:
            return None
        specs = {doc.module_id: doc for doc in self.docs if doc.doc_type == "spec"}
        values = []
        for reference in references:
            owner, fact_id = reference.split("#", 1)
            spec = specs.get(owner)
            if spec is None:
                values.append([reference, "MISSING_SPEC"])
                continue
            rows = {row[0]: row for row in self.core.table_rows(spec.body, "## 入口与调用链", FACT_HEADER)}
            if fact_id not in rows:
                values.append([reference, "MISSING_FACT"])
                continue
            normalized = fact_render.normalized_facts(spec, self.core)
            values.append([reference, rows[fact_id], normalized.get(fact_id), spec.meta.get("source_revisions")])
        return digest(json.dumps(values, ensure_ascii=False, separators=(",", ":"), sort_keys=True))

    def expected_relation_reviews(self, module_id):
        relation = self.relations.get(module_id)
        rows = [["关系映射.json", relation["sha256"], "已复核"]] if relation else []
        external = self.cross_module_fact_digest(module_id)
        if external:
            rows.append(["跨模块事实引用", external, "已复核"])
        return rows

    def impacts(self, module_id=None):
        queue = []
        for spec in (doc for doc in self.docs if doc.doc_type == "spec" and (not module_id or doc.module_id == module_id)):
            expected = self.expected_claims(spec)
            stored = {}
            if "## 结论复核" in spec.body:
                for row in self.core.table_rows(spec.body, "## 结论复核", CLAIMS_HEADER):
                    key = tuple(row[:2])
                    if key in stored:
                        raise ValueError(f"重复结论复核记录：{key}")
                    stored[key] = row
            for key, row in expected.items():
                prior = stored.get(key)
                if row[3] == "缺失" or prior != row:
                    reason = "影响文件缺失" if row[3] == "缺失" else "未复核或结论/正文已变化"
                    queue.append({"module_id": spec.module_id, "fact_id": key[0], "file": key[1], "reason": reason})
            for key in stored.keys() - expected.keys():
                queue.append({"module_id": spec.module_id, "fact_id": key[0], "file": key[1], "reason": "结论或影响关系已删除，需复核删除影响"})
            recorded = self.core.table_rows(spec.body, "## 关系复核", RELATION_REVIEW_HEADER) if "## 关系复核" in spec.body else []
            expected_relation = self.expected_relation_reviews(spec.module_id)
            if recorded != expected_relation:
                queue.append({"module_id": spec.module_id, "fact_id": "RELATION", "file": "关系映射.json", "reason": "关系映射新增、删除或变化，需复核"})
        return queue

    def confirm_claims(self, module_id):
        spec = self.spec(module_id)
        rows = self.expected_claims(spec)
        if any(row[3] == "缺失" for row in rows.values()):
            raise ValueError("受影响知识文件未生成；先完成正文再记录语义复核")
        section = "## 结论复核\n\n" + CLAIMS_HEADER + "\n| --- | --- | --- | --- | --- |\n"
        section += "\n".join("| " + " | ".join(row) + " |" for _, row in sorted(rows.items()))
        updated = replace_section(spec.original, "## 结论复核", section)
        relation = self.relations.get(module_id)
        if relation or "## 关系复核" in spec.body:
            review = "## 关系复核\n\n" + RELATION_REVIEW_HEADER + "\n| --- | --- | --- |\n"
            for row in self.expected_relation_reviews(module_id):
                review += "| " + " | ".join(row) + " |\n"
            updated = replace_section(updated, "## 关系复核", review)
        atomic_write(self.source / spec.relative, updated)
        return {"module_id": module_id, "claim_projections": len(rows), "note": "仅记录已完成的 AI 语义复核；摘要不证明自然语言正确"}

    def manifest_rows(self, manifest):
        if any(key in manifest.meta for key in ("answerable_topics", "uncertain_topics", "retrieval_keywords")):
            raise ValueError("发布清单包含当前知识规范不支持的旧字段")
        result = {}
        for heading in ("## 发布文件", "## 审核依据"):
            rows = self.core.table_rows(manifest.body, heading, FILES_HEADER)
            for path, doc_type, sha in rows:
                if path in result or not self.core.safe_repo_path(path) or not SHA.fullmatch(sha):
                    raise ValueError(f"发布清单路径或摘要无效：{path}")
                relative = (manifest.relative.parent / path).as_posix()
                doc = self.by_path.get(relative)
                if not doc or doc.doc_type != doc_type or content_digest(doc.original) != sha:
                    raise ValueError(f"发布清单已过期，正文或审核依据已变化：{relative}")
                if heading == "## 发布文件" and doc_type not in self.core.BUSINESS | self.core.ENGINEERING:
                    raise ValueError(f"发布清单不得发布过程文件：{relative}")
                if heading == "## 审核依据" and doc_type not in {"spec", "questions"}:
                    raise ValueError(f"审核依据类型无效：{relative}")
                result[path] = (doc, heading)
        relation = self.relations.get(manifest.module_id)
        relation_rows = self.core.table_rows(manifest.body, "## 关系依据", RELATION_HEADER) if "## 关系依据" in manifest.body else []
        expected_relation = [["关系映射.json", relation["sha256"]]] if relation else []
        if relation_rows != expected_relation:
            raise ValueError("发布清单关系依据已变化；重新准备模块发布包")
        required = {doc.relative for doc in self.module_docs(manifest.module_id) if doc.doc_type in {"spec", "questions"}}
        actual = {doc.relative for doc, heading in result.values() if heading == "## 审核依据"}
        if actual != required:
            raise ValueError("发布清单审核依据须包含本模块规格和已有待确认事项")
        evidence_rows = self.core.table_rows(manifest.body, "## 运行依据", "| evidence_id | 文件 | 内容摘要 |")
        evidence_ids = set()
        for evidence_id, local, sha in evidence_rows:
            item = self.evidence.get(evidence_id)
            if evidence_id in evidence_ids or not item or item["meta"]["module_id"] != manifest.module_id or local != item["path"].relative_to(self.project).as_posix() or sha != content_digest(item["original"]):
                raise ValueError(f"发布清单运行依据已变化：{evidence_id}")
            evidence_ids.add(evidence_id)
        if evidence_ids != self.bound_evidence_ids(manifest.module_id):
            raise ValueError("运行证据清单变化；重新准备模块发布包")
        intent_doc = next((doc for doc in self.module_docs(manifest.module_id) if doc.doc_type == "intent"), None)
        if self.core.protocol.supports(self.config["standard_version"], "intent_included"):
            intent_included = manifest.meta.get("intent_included")
            if intent_included not in {"true", "false"}:
                raise ValueError("发布清单须记录 intent_included")
            selected_intent = any(doc.doc_type == "intent" and heading == "## 发布文件" for doc, heading in result.values())
            if (intent_included == "true") != selected_intent or (intent_included == "true" and not intent_doc):
                raise ValueError("发布清单的 intent_included 与本次候选文件不一致")
        for key in (
            "business_topics", "business_unknowns", "business_keywords",
            "engineering_topics", "engineering_unknowns", "engineering_keywords",
        ):
            value = manifest.meta.get(key, "")
            if not value or any(char in value for char in "\n\r|"):
                raise ValueError(f"发布清单缺少有效的 {key}")
            if key.startswith("business_") and (self.core.TECHNICAL.search(value) or self.core.BUSINESS_FORBIDDEN.search(value) or self.core.contains_source_repository_url(value)):
                raise ValueError(f"发布清单须有业务语言的 {key}（不得含过程用语或内部编号）")
        return result

    def prepare(self, module_id, business_topics, business_unknowns, business_keywords,
                engineering_topics=None, engineering_unknowns=None, engineering_keywords=None,
                files=None, refresh=False):
        items = self.module_docs(module_id)
        spec = self.spec(module_id)
        existing = [doc for doc in items if doc.doc_type == "release_manifest"]
        if existing and not refresh:
            raise ValueError("发布清单已存在；需要更新时显式使用 --refresh")
        candidates = [doc for doc in items if doc.doc_type in self.core.BUSINESS | self.core.ENGINEERING and doc.meta["applicability"] == "current"]
        if files:
            requested = {value.strip() for value in files.split(",")}
            candidates = [doc for doc in candidates if doc.relative.relative_to(spec.relative.parent).as_posix() in requested]
            if len(candidates) != len(requested):
                raise ValueError("--files 含不存在、非当前或不能发布的文件")
        required = {"overview", "scope"} if self.config.get("_content_profile") != "compact" else {"overview", "rules", "faq"}
        if not required <= {doc.doc_type for doc in candidates}:
            raise ValueError(f"模块发布包缺少 {sorted(required - {doc.doc_type for doc in candidates})}；请核对 full/compact profile")
        chosen = {doc.relative for doc in candidates}
        prospective = [replace(doc, meta={**doc.meta, "review_status": "reviewed" if doc.relative in chosen else "draft"}) if doc.module_id == module_id and doc.doc_type in self.core.BUSINESS | self.core.ENGINEERING else doc for doc in self.docs]
        self.core.validate_project(prospective, self.outline, self.config, self.core.registered_adapter_entries(self.config))
        for value in (business_topics, business_unknowns, business_keywords):
            if not value or any(char in value for char in "\n\r|") or self.core.TECHNICAL.search(value) or self.core.BUSINESS_FORBIDDEN.search(value) or self.core.contains_source_repository_url(value):
                raise ValueError("业务主题、未知和关键词须为单行业务语言，且不得含过程用语或内部编号")
        engineering_topics = engineering_topics or business_topics
        engineering_unknowns = engineering_unknowns or business_unknowns
        engineering_keywords = engineering_keywords or business_keywords
        if any(any(char in value for char in "\n\r|") for value in (engineering_topics, engineering_unknowns, engineering_keywords)):
            raise ValueError("研发主题、未知和关键词须为单行文字")
        if self.impacts(module_id):
            raise ValueError("结论影响尚未复核；先查看 impact 并完成语义核对后 confirm-claims")
        self.core.validate_qa(spec)
        apis, methods, cores = self.core.validate_spec_catalog(spec, self.outline, self.config, {}, self.core.document_revisions(spec, self.config))
        technical = {doc.doc_type: doc for doc in candidates if doc.doc_type in self.core.ENGINEERING}
        if technical and "implementation" not in technical:
            raise ValueError("研发发布包缺少技术实现导航")
        if "implementation" in technical and ((apis and "api_catalog" not in technical) or (methods and "method_catalog" not in technical and self.config.get("_content_profile") != "compact")):
            raise ValueError("研发发布包不能遗漏规格已有的接口或方法正文")
        for doc in technical.values():
            if self.core.document_revisions(doc, self.config) != self.core.document_revisions(spec, self.config):
                raise ValueError("研发文件与模块规格基线不一致")
            if doc.meta.get("runtime_status") not in {"source_only", "runtime_verified", "verified_deployment"}:
                raise ValueError("研发文件缺少 runtime_status")
            if doc.doc_type in {"api_catalog", "method_catalog"}:
                self.core.validate_catalog(doc, apis if doc.doc_type == "api_catalog" else methods, cores, self.config, {}, self.core.document_revisions(spec, self.config))
            if doc.doc_type == "api_catalog" and self.core.table_rows(doc.body, "## 调用匹配", MATCH_HEADER) != self.core.table_rows(spec.body, "## 调用匹配", MATCH_HEADER):
                raise ValueError("接口与调用的匹配状态须与规格一致")
        intent_included = any(doc.doc_type == "intent" for doc in candidates)
        text = (f"---\nmodule_id: {module_id}\ndocument_type: release_manifest\nreview_status: draft\napplicability: current\n"
                f"intent_included: {'true' if intent_included else 'false'}\n"
                f"business_topics: {business_topics}\nbusiness_unknowns: {business_unknowns}\nbusiness_keywords: {business_keywords}\n"
                f"engineering_topics: {engineering_topics}\nengineering_unknowns: {engineering_unknowns}\nengineering_keywords: {engineering_keywords}\n"
                f"---\n\n# {spec.module}：发布清单\n\n")
        for heading, docs in (("## 发布文件", candidates), ("## 审核依据", [doc for doc in items if doc.doc_type in {"spec", "questions"}])):
            text += heading + "\n\n" + FILES_HEADER + "\n| --- | --- | --- |\n"
            for doc in sorted(docs, key=lambda item: str(item.relative)):
                local = doc.relative.relative_to(spec.relative.parent).as_posix()
                text += f"| {local} | {doc.doc_type} | {content_digest(doc.original)} |\n"
            text += "\n"
        relation = self.relations.get(module_id)
        if relation:
            text += "## 关系依据\n\n" + RELATION_HEADER + "\n| --- | --- |\n"
            text += f"| 关系映射.json | {relation['sha256']} |\n\n"
        text += "## 运行依据\n\n| evidence_id | 文件 | 内容摘要 |\n| --- | --- | --- |\n"
        for evidence_id in sorted(self.bound_evidence_ids(module_id)):
            item = self.evidence[evidence_id]
            text += f"| {evidence_id} | {item['path'].relative_to(self.project).as_posix()} | {content_digest(item['original'])} |\n"
        text += "\n"
        text += "## 批准边界\n\n审核须覆盖上述文件、关键未知和证据边界；源代码证据不自动等于线上事实。脚本核对内容摘要，不能认证现实身份。\n"
        text = replace_meta(text, {"review_subject_digest": review_subject_digest(text)})
        path = self.source / spec.relative.parent / "发布清单.md"
        for doc in items:
            if doc.doc_type in self.core.BUSINESS | self.core.ENGINEERING:
                atomic_write(self.source / doc.relative, draft_review_meta(doc.original))
        atomic_write(path, text)
        return {"module_id": module_id, "manifest": str(path), "candidate_files": len(candidates), "review_status": "draft", "review_subject_digest": review_subject_digest(text)}

    def approve(self, module_id, reviewer, reviewed_at, note):
        date.fromisoformat(reviewed_at)
        if not reviewer or not note or any(char in reviewer + note for char in "\r\n"):
            raise ValueError("approve 须记录真实审核人、日期和人明确批准的原话")
        manifest = next((doc for doc in self.module_docs(module_id) if doc.doc_type == "release_manifest"), None)
        if not manifest:
            raise ValueError("先 prepare 生成可审阅的模块发布清单")
        rows = self.manifest_rows(manifest)
        if not any(doc.doc_type == "spec" for doc, heading in rows.values() if heading == "## 审核依据"):
            raise ValueError("发布清单缺少规格审核依据")
        stamps = {"review_status": "reviewed", "reviewed_by": reviewer, "reviewed_at": reviewed_at}
        updates = [(self.source / doc.relative, replace_meta(clear_review_meta(doc.original, keep_subject=False), stamps)) for doc, heading in rows.values() if heading == "## 发布文件"]
        included = {doc.relative for doc, heading in rows.values() if heading == "## 发布文件"}
        updates.extend((self.source / doc.relative, draft_review_meta(doc.original)) for doc in self.module_docs(module_id) if doc.doc_type in self.core.BUSINESS | self.core.ENGINEERING and doc.relative not in included)
        approved_manifest = replace_meta(clear_review_meta(manifest.original), {**stamps, "approval_note": note, "approval_snapshot": None})
        approved_manifest = replace_meta(approved_manifest, {"approval_snapshot": approval_digest(approved_manifest)})
        updates.append((self.source / manifest.relative, approved_manifest))
        for path, value in updates:
            atomic_write(path, value)
        return {"module_id": module_id, "approved_files": len(included), "reviewed_by": reviewer, "reviewed_at": reviewed_at, "warning": "记录既有人工授权；命令本身不认证人的身份"}

    def policy_review(self, module_id, evidence_file, executed_by):
        manifest = next((doc for doc in self.module_docs(module_id) if doc.doc_type == "release_manifest"), None)
        if not manifest or manifest.meta.get("review_status") != "draft":
            raise ValueError("先 prepare 生成 draft 模块发布清单")
        rows = self.manifest_rows(manifest)
        subject = manifest.meta.get("review_subject_digest")
        if not SHA.fullmatch(subject or "") or subject != review_subject_digest(manifest.original):
            raise ValueError("发布清单候选摘要缺失或已变化；重新 prepare")
        policy, policy_path, policy_sha, authorized, expires = self.read_policy(require_head=True)
        record, record_path, record_sha = self.read_review_record(evidence_file)
        reviewed_at = self.validate_review_record(module_id, manifest, policy, record, executed_by, authorized, expires)
        candidate_paths = [self.source / doc.relative for doc, heading in rows.values() if heading == "## 发布文件"]
        self.scan_sensitive_files([*candidate_paths, policy_path, record_path])
        stamps = {
            "review_status": "policy_reviewed",
            "review_mode": "policy_auto",
            "review_policy": policy["policy_id"],
            "policy_version": policy["policy_version"],
            "policy_owner": policy["policy_owner"],
            "executed_by": executed_by,
            "reviewed_at": reviewed_at,
            "review_evidence": record_path.relative_to(self.project).as_posix(),
            "review_evidence_digest": record_sha,
            "policy_digest": policy_sha,
        }
        included = {doc.relative for doc, heading in rows.values() if heading == "## 发布文件"}
        updates = [
            (self.source / doc.relative, replace_meta(clear_review_meta(doc.original, keep_subject=False), stamps))
            for doc, heading in rows.values() if heading == "## 发布文件"
        ]
        updates.extend(
            (self.source / doc.relative, draft_review_meta(doc.original))
            for doc in self.module_docs(module_id)
            if doc.doc_type in self.core.BUSINESS | self.core.ENGINEERING and doc.relative not in included
        )
        reviewed_manifest = replace_meta(clear_review_meta(manifest.original), stamps)
        reviewed_manifest = replace_meta(reviewed_manifest, {"policy_review_snapshot": policy_review_digest(reviewed_manifest)})
        updates.append((self.source / manifest.relative, reviewed_manifest))
        for path, value in updates:
            atomic_write(path, value)
        return {
            "module_id": module_id,
            "reviewed_files": len(included),
            "review_status": "policy_reviewed",
            "review_policy": policy["policy_id"],
            "executed_by": executed_by,
            "reviewed_at": reviewed_at,
            "warning": "记录预授权策略的自动审核结果；不构成人工批准或运行验证",
        }

    def approvals(self, selected, for_publish=False):
        modules = {doc.module_id for doc in selected if doc.module_id}
        for module_id in modules:
            manifest = next((doc for doc in self.module_docs(module_id) if doc.doc_type == "release_manifest"), None)
            if not manifest or manifest.meta.get("review_status") not in {"reviewed", "policy_reviewed"}:
                raise ValueError(f"模块缺少明确批准的发布清单或完整策略审核：{module_id}")
            if any(key in manifest.meta for key in ("answerable_topics", "uncertain_topics", "retrieval_keywords")):
                raise ValueError("发布清单包含当前知识规范不支持的旧字段")
            rows = self.manifest_rows(manifest)
            listed = {doc.relative for doc, heading in rows.values() if heading == "## 发布文件"}
            actual = {doc.relative for doc in selected if doc.module_id == module_id}
            if listed != actual:
                raise ValueError(f"已审文件与模块发布清单不一致：{module_id}")
            if manifest.meta["review_status"] == "reviewed":
                if not manifest.meta.get("approval_note") or manifest.meta.get("approval_snapshot") != approval_digest(manifest.original):
                    raise ValueError(f"发布清单的主题、边界或批准记录已变化：{module_id}")
                keys = HUMAN_REVIEW_KEYS
                self.module_reviews[module_id] = {"mode": "human", "reviewed_by": manifest.meta["reviewed_by"]}
            else:
                if manifest.meta.get("policy_review_snapshot") != policy_review_digest(manifest.original):
                    raise ValueError(f"发布清单的主题、边界或策略审核记录已变化：{module_id}")
                policy, policy_path, policy_sha, authorized, expires = self.read_policy(require_head=True)
                record, record_path, record_sha = self.read_review_record(manifest.meta.get("review_evidence"))
                if manifest.meta.get("policy_digest") != policy_sha or manifest.meta.get("review_evidence_digest") != record_sha:
                    raise ValueError(f"策略或自动审核记录已变化：{module_id}")
                reviewed_at = self.validate_review_record(module_id, manifest, policy, record, manifest.meta.get("executed_by"), authorized, expires)
                expected = {
                    "review_mode": "policy_auto", "review_policy": policy["policy_id"],
                    "policy_version": policy["policy_version"], "policy_owner": policy["policy_owner"],
                    "reviewed_at": reviewed_at,
                }
                if any(manifest.meta.get(key) != value for key, value in expected.items()):
                    raise ValueError(f"发布清单策略审核字段与策略或记录不一致：{module_id}")
                self.scan_sensitive_files([policy_path, record_path, *(self.source / doc.relative for doc, heading in rows.values() if heading == "## 发布文件")])
                self.policy_inputs.update({policy_path, record_path})
                keys = POLICY_REVIEW_KEYS
                self.module_reviews[module_id] = {
                    "mode": "policy_auto", "policy_id": policy["policy_id"],
                    "policy_version": policy["policy_version"], "executed_by": manifest.meta["executed_by"],
                }
            for doc in selected:
                if doc.module_id == module_id and any(doc.meta.get(key) != manifest.meta.get(key) for key in keys):
                    raise ValueError(f"{doc.relative}: 文件审核信息与模块发布清单不一致")
            if for_publish and self.impacts(module_id):
                raise ValueError(f"模块存在待复核结论：{module_id}")

    def document_commit(self, selected):
        root = subprocess.run(["git", "-C", str(self.project), "rev-parse", "--show-toplevel"], text=True, capture_output=True)
        if root.returncode or Path(root.stdout.strip()).resolve() != self.project:
            raise ValueError("发布需要独立的文档 Git 仓库；先初始化并提交发布输入")
        head = subprocess.run(["git", "-C", str(self.project), "rev-parse", "HEAD"], text=True, capture_output=True)
        if head.returncode:
            raise ValueError("文档 Git 仓库尚无提交；先提交发布输入")
        commit = head.stdout.strip()
        paths = {self.project / "知识库配置.json", self.source / "功能大纲.md"}
        paths.update(self.source / doc.relative for doc in selected)
        modules = {doc.module_id for doc in selected if doc.module_id}
        paths.update(self.source / doc.relative for doc in self.docs if doc.module_id in modules and doc.doc_type in {"spec", "questions", "release_manifest"})
        evidence_ids = set().union(*(self.bound_evidence_ids(module_id) for module_id in modules)) if modules else set()
        paths.update(self.evidence[evidence_id]["path"] for evidence_id in evidence_ids)
        paths.update(self.policy_inputs)
        paths.update(item["path"] for module_id, item in self.relations.items() if module_id in modules)
        for path in sorted(paths):
            local = path.relative_to(self.project).as_posix()
            saved = subprocess.run(["git", "-C", str(self.project), "show", f"{commit}:{local}"], capture_output=True)
            if saved.returncode or saved.stdout != path.read_bytes():
                raise ValueError(f"发布输入未提交或与文档提交不一致：{local}")
        return commit

    def retrieval_index(self, root, selected, engineering):
        lines = ["# 检索索引", "", "先按主题找到文件，再读取对应正文和标题段落。索引只提供定位信息；确定答案须依据正文。", ""]
        for module_id in sorted({doc.module_id for doc in selected if doc.module_id}):
            items = [doc for doc in selected if doc.module_id == module_id and (engineering or doc.doc_type in self.core.BUSINESS)]
            manifest = next(doc for doc in self.docs if doc.module_id == module_id and doc.doc_type == "release_manifest")
            prefix = "engineering" if engineering else "business"
            lines.extend([f"## {manifest.domain}／{manifest.module}", "", f"关键词：{manifest.meta[prefix + '_keywords']}", f"可回答主题：{manifest.meta[prefix + '_topics']}", f"需限定或仍未知：{manifest.meta[prefix + '_unknowns']}", ""])
            for doc in sorted(items, key=lambda item: str(item.relative)):
                link = quote(doc.relative.as_posix(), safe="/")
                lines.append(f"- [{doc.relative.stem}]({link})")
                headings = re.findall(r"(?m)^#{2,3} (.+)$", doc.body)
                if headings:
                    lines.append("  标题定位：" + "；".join(headings))
            if engineering:
                glossary = Path(manifest.domain, manifest.module, "事实编号对照.md")
                if (root / glossary).is_file():
                    lines.append(f"- [事实编号对照]({quote(glossary.as_posix(), safe='/')})")
            lines.append("")
        for doc in selected:
            if doc.doc_type == "glossary":
                lines.append(f"- [术语表]({quote(doc.relative.as_posix(), safe='/')})")
        if not engineering:
            scan_business_terms(self.core, "\n".join(lines), "检索索引.md")
        (root / "检索索引.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def registry_path(self, release_id):
        if not RELEASE_ID.fullmatch(release_id):
            raise ValueError("release-id 须为安全的字母/数字/点/横线标识")
        path = self.release_root / "版本清单" / f"{release_id}.json"
        if path.parent.is_symlink() or path.is_symlink():
            raise ValueError("版本清单不能是符号链接")
        return path

    def ensure_release_history_committed(self):
        """Do not replace the current snapshot until Git can recover it."""
        if not self.release_root.exists():
            return
        files = [path for path in self.release_root.rglob("*") if path.is_file()]
        if not files:
            return
        status = subprocess.run(
            ["git", "-C", str(self.project), "status", "--porcelain=v1", "--untracked-files=all", "--", "发布"],
            text=True,
            capture_output=True,
        )
        if status.returncode or status.stdout.strip():
            raise ValueError("覆盖当前发布前，须先把现有 发布/ 完整提交到 Git；该提交就是旧版本恢复点")
        tracked = subprocess.run(
            ["git", "-C", str(self.project), "ls-files", "--", "发布"],
            text=True,
            capture_output=True,
        )
        if tracked.returncode or not tracked.stdout.strip():
            raise ValueError("现有 发布/ 尚未纳入 Git；先提交当前版本后再覆盖")

    def release_id_used_in_git(self, release_id):
        local = self.registry_path(release_id).relative_to(self.project).as_posix()
        history = subprocess.run(
            ["git", "-C", str(self.project), "log", "--all", "--format=%H", "--", local],
            text=True,
            capture_output=True,
        )
        if history.returncode:
            raise ValueError("无法检查 Git 中的历史 release-id")
        return bool(history.stdout.strip())

    def scan_sensitive(self, root):
        self.scan_sensitive_files(path for path in root.rglob("*.md"))

    def view_path(self, local):
        if not isinstance(local, str) or not self.core.safe_repo_path(local):
            raise ValueError("版本目录须为项目内相对路径")
        path = (self.project / local).resolve(strict=True)
        if path == self.release_root.resolve() or not path.is_relative_to(self.release_root.resolve()):
            raise ValueError("版本目录必须位于项目发布目录下")
        self.core.ensure_no_symlinks(path)
        return path

    def generator_identity(self):
        version = self.core.IMPLEMENTATION_VERSION
        if not version:
            raise ValueError("Code2KB Spec VERSION 不能为空")
        return {"name": "Code2KB Spec", "version": version}

    def record(self, release_id, business_stage, engineering_stage, business_out, engineering_out, document_commit):
        summary = Counter(item["mode"] for item in self.module_reviews.values())
        value = {
            "standard_version": self.config["standard_version"],
            "registry_schema_version": "2.0",
            "release_id": release_id,
            "document_commit": document_commit,
            "generated_by": self.generator_identity(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "review_summary": {"human": summary.get("human", 0), "policy_auto": summary.get("policy_auto", 0)},
            "module_reviews": {key: self.module_reviews[key] for key in sorted(self.module_reviews)},
            "views": {},
        }
        for name, stage, output in (("business", business_stage, business_out), ("engineering", engineering_stage, engineering_out)):
            inventory = {path.relative_to(stage).as_posix(): digest(path.read_bytes()) for path in sorted(stage.rglob("*")) if path.is_file()}
            value["views"][name] = {"path": output.relative_to(self.project).as_posix(), "files": inventory}
        return value

    def audit_release(self, release_id):
        current = None
        if release_id is None:
            current = self.core.strict_json_object(self.release_root / "当前版本.json", label="当前版本指针")
            pointer_fields = {
                "standard_version", "release_id", "business_path", "engineering_path",
                "document_commit", "registry_path", "registry_sha256", "history_backend", "generated_by",
            }
            if set(current) != pointer_fields:
                raise ValueError("当前版本指针字段不完整或含未知字段")
            if not isinstance(current, dict) or not isinstance(current.get("release_id"), str):
                raise ValueError("当前版本指针结构无效")
            release_id = current["release_id"]
        path = self.registry_path(release_id)
        value = self.core.strict_json_object(path, label="版本清单")
        registry_fields = {
            "standard_version", "registry_schema_version", "release_id", "document_commit",
            "generated_by", "created_at", "review_summary", "module_reviews", "views",
        }
        if set(value) != registry_fields:
            raise ValueError("版本清单字段不完整或含未知字段")
        generated_by = value.get("generated_by")
        if not isinstance(value, dict) or value.get("release_id") != release_id or not self.core.protocol.supports(value.get("standard_version"), "registry_2") or not isinstance(generated_by, dict) or set(generated_by) != {"name", "version"} or generated_by.get("name") != "Code2KB Spec" or not isinstance(generated_by.get("version"), str) or not generated_by["version"] or not isinstance(value.get("created_at"), str) or not isinstance(value.get("views"), dict) or set(value["views"]) != {"business", "engineering"} or not self.core.HEX_COMMIT.fullmatch(value.get("document_commit", "")):
            raise ValueError("版本清单结构或身份无效")
        schema = value.get("registry_schema_version")
        if schema != "2.0":
            raise ValueError("版本清单 registry_schema_version 无效")
        review_summary, module_reviews = value.get("review_summary"), value.get("module_reviews")
        if not isinstance(review_summary, dict) or set(review_summary) != {"human", "policy_auto"} or not all(isinstance(item, int) and item >= 0 for item in review_summary.values()) or not isinstance(module_reviews, dict) or len(module_reviews) != sum(review_summary.values()):
            raise ValueError("版本清单审核溯源结构无效")
        counted = Counter()
        for module_id, item in module_reviews.items():
            if not re.fullmatch(r"[a-z][a-z0-9_.-]*", module_id) or not isinstance(item, dict) or item.get("mode") not in {"human", "policy_auto"}:
                raise ValueError("版本清单模块审核溯源无效")
            if item["mode"] == "human":
                if set(item) != {"mode", "reviewed_by"} or not isinstance(item["reviewed_by"], str) or not item["reviewed_by"]:
                    raise ValueError("版本清单人工审核溯源无效")
            elif set(item) != {"mode", "policy_id", "policy_version", "executed_by"} or not POLICY_ID.fullmatch(item.get("policy_id", "")) or not POLICY_VERSION.fullmatch(item.get("policy_version", "")) or not isinstance(item.get("executed_by"), str) or not item["executed_by"]:
                raise ValueError("版本清单策略审核溯源无效")
            counted[item["mode"]] += 1
        if review_summary != {"human": counted.get("human", 0), "policy_auto": counted.get("policy_auto", 0)}:
            raise ValueError("版本清单审核数量与模块明细不一致")
        roots = []
        for view in value["views"].values():
            if not isinstance(view, dict) or set(view) != {"path", "files"} or not isinstance(view.get("files"), dict) or not view["files"] or not all(isinstance(local, str) and self.core.safe_repo_path(local) and isinstance(sha, str) and SHA.fullmatch(sha) for local, sha in view["files"].items()):
                raise ValueError("版本文件摘要清单无效")
            root = self.view_path(view.get("path"))
            roots.append(root)
            found = {item.relative_to(root).as_posix(): digest(item.read_bytes()) for item in root.rglob("*") if item.is_file()}
            if found != view["files"]:
                raise ValueError(f"发布目录内容已被修改、缺失或增加：{view['path']}")
        if self.core.path_is_nested(*roots):
            raise ValueError("版本的业务与研发目录不得相交")
        if current and (not isinstance(current.get("generated_by"), dict) or set(current["generated_by"]) != {"name", "version"} or current.get("standard_version") != value["standard_version"] or current.get("generated_by") != generated_by or current.get("registry_sha256") != digest(path.read_bytes()) or current.get("business_path") != value["views"]["business"]["path"] or current.get("engineering_path") != value["views"]["engineering"]["path"] or current.get("document_commit") != value["document_commit"]):
            raise ValueError("当前版本指针与版本清单不一致")
        if current:
            if current.get("history_backend") != "git":
                raise ValueError("当前版本的历史管理方式无效")
            registry_local = current.get("registry_path")
            if registry_local is not None and registry_local != path.relative_to(self.project).as_posix():
                raise ValueError("当前版本指向的版本清单路径无效")
        source_urls = release_checks_source_urls(generated_by["version"])
        for audience, view in value["views"].items():
            self.core.validate_bundle(self.view_path(view["path"]), audience == "engineering", source_urls=source_urls)
        return value

    def current_pointer(self, release_id, value, registry_sha256):
        return {
            "standard_version": value["standard_version"],
            "release_id": release_id,
            "business_path": value["views"]["business"]["path"],
            "engineering_path": value["views"]["engineering"]["path"],
            "document_commit": value["document_commit"],
            "registry_path": f"发布/版本清单/{release_id}.json",
            "registry_sha256": registry_sha256,
            "history_backend": "git",
            "generated_by": value["generated_by"],
        }

    def current_markdown(self, pointer):
        return (
            f"# 当前版本\n\n内容版本：{pointer['release_id']}\n\n"
            f"知识规范：{pointer['standard_version']}\n\n"
            f"生成工具：{pointer['generated_by']['name']} {pointer['generated_by']['version']}\n\n"
            f"- [业务版](../{pointer['business_path']}/目录.md)\n"
            f"- [研发版](../{pointer['engineering_path']}/目录.md)\n\n"
            "机器读取同目录的 `当前版本.json`，只检索指定受众目录。"
            "工作树只保留当前快照；历史版本由 Git 提交或标签管理。\n"
        )
