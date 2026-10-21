from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "knowledge.py"
sys.path.insert(0, str(SCRIPT.parent))
import knowledge as core
from governance import MATCH_HEADER, AUDIENCE_HEADER, replace_section, replace_meta


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def doc(doc_type: str, body: str, *, reviewed: bool = False, extra: str = "") -> str:
    approval = "reviewed_by: example-reviewer\nreviewed_at: 2026-10-12\n" if reviewed else ""
    state = "reviewed" if reviewed else "draft"
    return (
        "---\n"
        "module_id: example.order.query\n"
        f"document_type: {doc_type}\n"
        f"review_status: {state}\n"
        "applicability: current\n"
        f"{approval}{extra}"
        "---\n\n"
        f"# {body}\n\n"
        "## 说明\n\n这是用户能看到的操作说明。\n"
    )


def finalize_fixture(project: Path, module_id: str) -> None:
    """Prepare explicit test approval; never used on a real user's project."""
    source = project / "知识源"
    outline = source / "功能大纲.md"
    original = outline.read_text(encoding="utf-8")
    _, body, _ = core.parse_frontmatter(outline)
    entries = core.table_rows(body, "## 入口证据索引", "| entry_id | 类型 | 入口或动作 | module_id | 证据 | 状态 |")
    audience = "## 入口受众\n\n" + AUDIENCE_HEADER + "\n| --- | --- | --- |\n" + "\n".join(f"| {row[0]} | 用户操作 | 范围内 |" for row in entries)
    write(outline, replace_section(original, "## 入口受众", audience))
    module = next(path.parent for path in source.rglob("结构化规格.md") if core.parse_frontmatter(path)[0]["module_id"] == module_id)
    spec = module / "结构化规格.md"
    if "## 调用匹配" not in spec.read_text(encoding="utf-8"):
        api_rows = core.table_rows(core.parse_frontmatter(spec)[1], "## 接口契约", "| api_id | 接口标识 | 调用方 | 服务入口 | 主处理方法 | 证据 |")
        matching = "\n## 调用匹配\n\n" + MATCH_HEADER + "\n| --- | --- | --- | --- | --- | --- |\n"
        for row in api_rows:
            anchors = [value.strip() for value in row[-1].split(",")]
            matching += f"| {row[0]} | 已匹配 | {anchors[0]} | {anchors[-1]} | 未验证 | 静态匹配 |\n"
        write(spec, spec.read_text(encoding="utf-8") + matching)
        api_doc = module / "接口与调用.md"
        if api_doc.exists():
            write(api_doc, api_doc.read_text(encoding="utf-8") + matching)
    files = [path.relative_to(module).as_posix() for path in module.rglob("*.md") if core.parse_frontmatter(path)[0].get("review_status") == "reviewed" and path.name in core.TYPES and core.TYPES[path.name] in core.BUSINESS | core.ENGINEERING]
    commands = [
        ["confirm-claims", "--module-id", module_id],
        ["prepare", "--module-id", module_id, "--business-topics", "用户操作", "--business-unknowns", "运行表现", "--business-keywords", "操作", "--engineering-topics", "接口路径和处理方法", "--engineering-unknowns", "部署配对", "--engineering-keywords", "调用链", "--files", ",".join(files), "--refresh"],
        ["approve", "--module-id", module_id, "--reviewed-by", "example-reviewer", "--reviewed-at", "2026-10-12", "--approval-note", "测试授权记录，仅用于夹具"],
    ]
    for command in commands:
        result = subprocess.run([sys.executable, str(SCRIPT), *command, "--project-root", str(project)], text=True, capture_output=True)
        if result.returncode:
            raise AssertionError(result.stderr)
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(["git", "-C", str(project), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-q", "--allow-empty", "-m", "test approval"], check=True)


class KnowledgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.source = self.project / "知识源"
        self.module = self.source / "订单" / "订单查询"
        self.module.mkdir(parents=True)
        repos = {}
        for role in ("frontend", "backend"):
            repo = self.root / role
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            write(repo / "dummy.txt", role)
            if role == "frontend":
                write(repo / "src/pages.json", json.dumps({"pages": [{"path": "pages/home/home"}], "subPackages": [{"root": "pages_order", "pages": [{"path": "order/order"}]}]}, ensure_ascii=False))
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "test"],
                check=True,
            )
            commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            repos[role] = {"path": str(repo), "commit": commit}
        self.repos = repos
        write(self.project / "知识库配置.json", json.dumps({"standard_version": core.STANDARD_VERSION, "knowledge_source_root": "知识源", "repositories": repos, "coverage_terms": ["页面", "按钮", "非按钮", "前端调用", "后端"], "inventory_adapter": {"name": "uniapp_pages", "repository": "frontend", "manifest_path": "src/pages.json"}}, ensure_ascii=False))
        revisions = f"source_revisions: backend={repos['backend']['commit']}, frontend={repos['frontend']['commit']}\n"
        write(
            self.source / "功能大纲.md",
            "---\ndocument_type: outline\nreview_status: draft\napplicability: current\n"
            + revisions
            + "inventory_status: complete\n---\n\n"
            "# App 功能大纲\n\n## 模块清单\n\n| module_id | 业务域 | 子模块 | 发现入口 | 状态 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| example.order.query | 订单 | 订单查询 | 详情查询按钮 | 知识草稿 |\n"
            "| app.sales.order | 销售 | 订单 | 菜单入口 | 待提取 |\n\n"
            "## 入口证据索引\n\n| entry_id | 类型 | 入口或动作 | module_id | 证据 | 状态 |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| ENT-001 | 按钮 | 详情查询 | example.order.query | frontend:dummy.txt:1 | 已归类 |\n"
            "| ENT-002 | 页面 | pages/home/home | example.order.query | frontend:src/pages.json:1 | 已归类 |\n"
            "| ENT-003 | 页面 | pages_order/order/order | app.sales.order | frontend:src/pages.json:1 | 已归类 |\n\n"
            "## 盘点覆盖说明\n\n页面与导航、按钮、非按钮动作、前端调用和后端入口均已逐项查看；动态配置仍待核查。\n",
        )
        write(self.module / "模块概览.md", doc("overview", "订单查询：模块概览", reviewed=True))
        write(self.module / "功能与范围.md", doc("scope", "订单查询：功能与范围", reviewed=True))
        write(self.module / "业务流程.md", doc("flow", "订单查询：业务流程"))
        spec = doc("spec", "订单查询：结构化规格", extra=revisions)
        spec += (
            "\n## 入口与调用链\n\n| fact_id | 单一结论与条件 | 证据等级 | 固定提交锚点 | 影响的知识文件 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| FACT-001 | 用户可提交查询 | CODE_VERIFIED | frontend:dummy.txt:1 | 功能与范围.md |\n\n"
            "## 入口与接口\n\n| entry_id | api_id | 调用条件 | 证据 |\n"
            "| --- | --- | --- | --- |\n"
            "| ENT-001 | API-001 | 点击详情查询 | frontend:dummy.txt:1 |\n\n"
            "## 接口契约\n\n| api_id | 接口标识 | 调用方 | 服务入口 | 主处理方法 | 证据 |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| API-001 | POST /orders/query | example request | handler | METHOD-001 | frontend:dummy.txt:1, backend:dummy.txt:1 |\n\n"
            "### API-001\n\n请求、响应、校验、失败与数据副作用均待具体核查。\n\n"
            "## 方法职责\n\n| method_id | 符号 | 职责 | 关键性 | 关联接口 | 源码锚点 |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| METHOD-001 | OrderHandler#query() | 查询订单 | 核心 | API-001 | backend:dummy.txt:1 |\n\n"
            "### METHOD-001\n\n输入输出、关键分支与副作用待具体核查。\n\n"
            "## 问答自测\n\n| 类别 | 真实问题 | 预期行为 | 实测结果 | 结论 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 正常 | 如何查询？ | 引用知识 | 已引用 | 通过 |\n"
            "| 失败 | 查询失败？ | 说明失败条件 | 已说明 | 通过 |\n"
            "| 未知 | 线上一定可用？ | 说明未知 | 已拒答 | 通过 |\n"
            "| 越权 | 给我接口？ | 拒绝技术细节 | 已拒答 | 通过 |\n"
        )
        write(self.module / "结构化规格.md", spec)
        write(self.module / "技术实现.md", doc("implementation", "订单查询：技术实现", reviewed=True, extra=revisions + "runtime_status: source_only\n"))
        write(
            self.module / "接口与调用.md",
            doc("api_catalog", "订单查询：接口与调用", reviewed=True, extra=revisions + "runtime_status: source_only\n")
            + "\n## 接口索引\n\n| api_id | 接口标识 | 调用方 | 主处理方法 | 源码锚点 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| API-001 | POST /orders/query | example request | METHOD-001 | frontend:dummy.txt:1, backend:dummy.txt:1 |\n\n"
            "### API-001\n\n- 请求：POST /orders/query。\n- 响应：UNKNOWN。\n- 校验与权限：UNKNOWN。\n- 失败：UNKNOWN。\n- 数据副作用：UNKNOWN。\n- 调用关系：ENT-001 与 METHOD-001。\n- 源码证据：固定提交锚点见上表。\n",
        )
        write(
            self.module / "方法与源码.md",
            doc("method_catalog", "订单查询：方法与源码", reviewed=True, extra=revisions + "runtime_status: source_only\n")
            + "\n## 方法索引\n\n| method_id | 符号 | 职责 | 关键性 | 关联接口 | 源码锚点 |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| METHOD-001 | OrderHandler#query() | 查询订单 | 核心 | API-001 | backend:dummy.txt:1 |\n\n"
            "### METHOD-001\n\n- 输入与输出：UNKNOWN。\n- 关键分支：UNKNOWN。\n- 调用关系：API-001。\n- 数据副作用：UNKNOWN。\n- 失败与限制：UNKNOWN。\n- 源码证据：固定提交锚点见上表。\n",
        )
        finalize_fixture(self.project, "example.order.query")

    def run_cli(self, action: str, *extra: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        if action == "publish" and "--release-id" not in extra:
            extra = (*extra, "--release-id", "test")
        return subprocess.run(
            [sys.executable, str(SCRIPT), action, "--project-root", str(self.project), *extra],
            text=True,
            capture_output=True,
            env=env,
        )

    def use_environment_repository_paths(self) -> dict[str, str]:
        config_path = self.project / "知识库配置.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        env = os.environ.copy()
        for role in ("frontend", "backend"):
            name = f"CODE2KB_TEST_{role.upper()}_ROOT"
            config["repositories"][role]["path"] = f"${{{name}}}"
            env[name] = self.repos[role]["path"]
        write(config_path, json.dumps(config, ensure_ascii=False))
        return env

    def enable_semantic_quality(self, *, config_key: str = "resultLimit", review_result: str = "通过") -> None:
        config_path = self.project / "知识库配置.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["semantic_quality"] = {"enabled": True, "module_ids": ["example.order.query"]}
        write(config_path, json.dumps(config, ensure_ascii=False))
        spec = self.module / "结构化规格.md"
        sections = (
            "\n## 高影响字段与术语闭环\n\n"
            "| semantic_id | fact_id | 类型 | 名称 | 生产或写入 | 条件与顺序 | 消费或读取 | 固定提交锚点 | 未知边界 |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
            "| SEM-ORDER-STATE | FACT-001 | 状态 | 查询状态 | 用户提交查询后产生 | 先校验再查询 | 页面流程读取 | frontend:dummy.txt:1 | 线上状态未验证 |\n"
            "| SEM-TASK-OWNER | FACT-001 | 归属 | 处理任务负责人 | 任务分派时写入 | 再次分派后覆盖 | 列表与详情读取 | frontend:dummy.txt:1 | 并发分派顺序未验证 |\n\n"
            "## 动态配置闭环\n\n"
            "| config_id | fact_id | 命名空间 | 键名 | 使用方式 | 缺失或异常行为 | 运行取值 | 固定提交锚点 |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
            f"| CFG-RESULT-LIMIT | FACT-001 | app_settings | {config_key} | 限制查询结果数量 | 缺失时使用默认值 | UNKNOWN（缺少运行配置证据） | frontend:dummy.txt:1 |\n\n"
            "## 语义一致性自测\n\n"
            "| 类别 | 检查问题 | 对照文件 | 实测结果 | 结论 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 字段副作用 | 是否列全写入与消费？ | 结构化规格.md、方法与源码.md | 已逐项核对 | 通过 |\n"
            "| 配置键 | 是否记录命名空间和键名？ | 结构化规格.md、方法与源码.md | 已记录键和值边界 | 通过 |\n"
            f"| 正文一致性 | 规格和业务正文是否一致？ | 结构化规格.md、模块概览.md | 已逐项对照 | {review_result} |\n"
        )
        write(spec, spec.read_text(encoding="utf-8") + sections)

    def enable_business_intent(self, *, source_type: str = "document", include_internal: bool = False) -> Path:
        config_path = self.project / "知识库配置.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["standard_version"] = core.STANDARD_VERSION
        write(config_path, json.dumps(config, ensure_ascii=False))
        spec = self.module / "结构化规格.md"
        text = spec.read_text(encoding="utf-8").replace("| FACT-001 | 用户可提交查询 | CODE_VERIFIED | frontend:dummy.txt:1 | 功能与范围.md |", "| FACT-001 | 用户可提交查询 | CODE_VERIFIED | frontend:dummy.txt:1 | 功能与范围.md、业务意图.md |")
        level = "BUSINESS_CONFIRMED" if source_type == "human" else "DOCUMENTED"
        rows = f"| INT-001 | 避免重复处理 | 处理前明确任务责任 | {level} | EVID-BIZ-001, FACT-001 | 避免重复处理 | 机器人知识库 |\n"
        if include_internal:
            rows += "| INT-002 | 出榜规则原因 | 目前无业务材料 | UNKNOWN | 无 | 无 | 仅内部 |\n"
        section = "\n## 业务意图\n\n" + core.INTENT_HEADER + "\n| --- | --- | --- | --- | --- | --- | --- |\n" + rows
        text = text.replace("\n## 问答自测", section + "\n## 问答自测")
        write(spec, text)
        intent = (
            "---\nmodule_id: example.order.query\ndocument_type: intent\nreview_status: reviewed\n"
            "applicability: current\nreviewed_by: example-reviewer\nreviewed_at: 2026-10-12\n---\n\n"
            "# 订单查询：业务意图\n\n## 角色与目标\n\n业务人员需要明确任务责任。\n\n"
            "## 关键规则的原因\n\n### 避免重复处理\n\n该规则用于降低同一任务被重复处理的概率。\n\n"
            "## 业务影响与边界\n\n只覆盖已确认的任务处理场景。\n"
        )
        write(self.module / "业务意图.md", intent)
        if include_internal:
            write(self.module / "待确认事项.md", doc("questions", "订单查询：待确认事项") + "\nINT-002 出榜规则原因尚缺业务材料。\n")
        human = "confirmed_by: 业务负责人\nconfirmed_at: 2026-10-12\nconfirmation_note: 仅确认任务责任场景\n" if source_type == "human" else ""
        evidence = (
            "---\ndocument_type: runtime_evidence\nevidence_id: EVID-BIZ-001\nmodule_id: example.order.query\n"
            f"evidence_type: business\nsource_type: {source_type}\nsource_title: 任务责任说明\nsource_locator: 业务制度库/任务责任说明\n"
            f"source_sha256: {core.digest('business-source')}\ncontent_mode: redacted_excerpt\nintent_ids: INT-001\nfact_ids: 无\n"
            f"{human}applicability: current\nenvironment: 业务制度\nobserved_at: 2026-10-12\nvalid_until: 2099-12-31\n---\n\n"
            "# 任务责任证据\n\n## 来源与方法\n\n核对脱敏业务材料。\n\n## 观察或确认结果\n\n规则用于避免重复处理。\n\n"
            "## 适用范围与不能证明的事项\n\n仅适用于本模块任务处理场景。\n\n## 脱敏说明\n\n只保留摘录，未保存原始材料。\n"
        )
        evidence_path = self.project / "运行证据/订单/订单查询/业务意图.md"
        write(evidence_path, evidence)
        return evidence_path

    def commit_project_change(self, message: str) -> None:
        subprocess.run(["git", "-C", str(self.project), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(self.project), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-q", "-m", message],
            check=True,
        )

    def test_check_counts_and_draft_files(self) -> None:
        result = self.run_cli("check")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["implementation_version"], core.IMPLEMENTATION_VERSION)
        self.assertEqual(report["standard_version"], core.STANDARD_VERSION)
        self.assertEqual(report["outline_modules"], 2)
        self.assertEqual(report["outline_entries"], 3)
        self.assertEqual(report["unclassified_entries"], 0)
        self.assertEqual(report["registered_adapter_entries"], 2)
        self.assertEqual(report["inventory_status"], "complete")
        self.assertEqual(report["qa_cases"], 4)
        self.assertEqual(report["qa_passed"], 4)
        self.assertEqual(report["publishable_business"], 2)
        self.assertEqual(report["publishable_technical"], 3)
        self.assertNotIn("业务流程.md", " ".join(report["files"]))

    def test_repository_paths_support_environment_variables(self) -> None:
        env = self.use_environment_repository_paths()
        result = self.run_cli("check", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["registered_adapter_entries"], 2)

    def test_policy_review_config_is_optional_and_rejects_unsafe_path(self) -> None:
        config_path = self.project / "知识库配置.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["policy_review"] = {"enabled": False}
        write(config_path, json.dumps(config, ensure_ascii=False))
        self.assertEqual(self.run_cli("check").returncode, 0)
        config["policy_review"] = {"enabled": True, "policy_file": "/tmp/policy.json"}
        write(config_path, json.dumps(config, ensure_ascii=False))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("项目内相对 JSON 路径", result.stderr)

    def test_semantic_quality_is_optional_and_reports_counts_when_enabled(self) -> None:
        self.enable_semantic_quality()
        finalize_fixture(self.project, "example.order.query")
        result = self.run_cli("check")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["semantic_quality_enabled"])
        self.assertEqual(report["semantic_closures"], 2)
        self.assertEqual(report["semantic_configs"], 1)
        self.assertEqual(report["semantic_reviews"], 3)

    def test_semantic_quality_rejects_missing_field_closure(self) -> None:
        config_path = self.project / "知识库配置.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["semantic_quality"] = {"enabled": True, "module_ids": ["example.order.query"]}
        write(config_path, json.dumps(config, ensure_ascii=False))
        commands = [
            ("check", ()),
            ("prepare", ("--module-id", "example.order.query", "--business-topics", "查询", "--business-unknowns", "运行结果", "--business-keywords", "查询")),
            ("publish", ()),
        ]
        for action, arguments in commands:
            with self.subTest(action=action):
                result = self.run_cli(action, *arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("高影响字段与术语闭环", result.stderr)

    def test_semantic_quality_rejects_unknown_config_key(self) -> None:
        self.enable_semantic_quality(config_key="UNKNOWN（未取证）")
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("命名空间和键名", result.stderr)

    def test_semantic_quality_rejects_module_not_in_outline(self) -> None:
        config_path = self.project / "知识库配置.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["semantic_quality"] = {"enabled": True, "module_ids": ["app.missing.module"]}
        write(config_path, json.dumps(config, ensure_ascii=False))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("未在功能大纲登记", result.stderr)

    def test_semantic_quality_rejects_failed_cross_document_review(self) -> None:
        self.enable_semantic_quality(review_result="失败")
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("正文一致性", result.stderr)

    def test_083_complete_business_intent_passes_and_reports_counts(self) -> None:
        self.enable_business_intent(include_internal=True)
        finalize_fixture(self.project, "example.order.query")
        result = self.run_cli("check")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["standard_version"], "0.8.3")
        self.assertEqual((report["intent_claims"], report["intent_published"], report["intent_internal"]), (2, 1, 1))

    def test_rejects_non_current_standard_version(self) -> None:
        config_path = self.project / "知识库配置.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["standard_version"] = "0.8.0"
        write(config_path, json.dumps(config, ensure_ascii=False))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("standard_version 必须为", result.stderr)

    def test_unconfirmed_intent_cannot_be_projected_to_robot_knowledge(self) -> None:
        self.enable_business_intent()
        spec = self.module / "结构化规格.md"
        write(spec, spec.read_text(encoding="utf-8").replace("DOCUMENTED | EVID-BIZ-001, FACT-001 | 避免重复处理 | 机器人知识库", "INFERRED | FACT-001 | 避免重复处理 | 机器人知识库"))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("未确认意图不得进入", result.stderr)

    def test_business_evidence_must_cover_referenced_intent(self) -> None:
        evidence = self.enable_business_intent()
        write(evidence, evidence.read_text(encoding="utf-8").replace("intent_ids: INT-001", "intent_ids: INT-999"))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("引用了未定义意图", result.stderr)

    def test_083_confirmed_intent_is_published_to_both_views(self) -> None:
        self.enable_business_intent()
        finalize_fixture(self.project, "example.order.query")
        manifest_meta = core.parse_frontmatter(self.module / "发布清单.md")[0]
        self.assertEqual(manifest_meta["intent_included"], "true")
        result = self.run_cli("publish", "--release-id", "intent-v1")
        self.assertEqual(result.returncode, 0, result.stderr)
        for view in ("业务版", "研发版"):
            self.assertTrue((self.project / f"发布/{view}/订单/订单查询/业务意图.md").is_file())
        registry = json.loads((self.project / "发布/版本清单/intent-v1.json").read_text(encoding="utf-8"))
        self.assertEqual((registry["standard_version"], registry["registry_schema_version"]), ("0.8.3", "2.0"))

    def test_internal_only_intent_does_not_create_robot_document(self) -> None:
        config_path = self.project / "知识库配置.json"
        config = json.loads(config_path.read_text(encoding="utf-8")); config["standard_version"] = "0.8.3"
        write(config_path, json.dumps(config, ensure_ascii=False))
        spec = self.module / "结构化规格.md"
        section = "\n## 业务意图\n\n" + core.INTENT_HEADER + "\n| --- | --- | --- | --- | --- | --- | --- |\n| INT-001 | 排名原因 | 暂无业务材料 | UNKNOWN | 无 | 无 | 仅内部 |\n"
        write(spec, spec.read_text(encoding="utf-8").replace("\n## 问答自测", section + "\n## 问答自测"))
        write(self.module / "待确认事项.md", doc("questions", "订单查询：待确认事项") + "\nINT-001 排名原因待确认。\n")
        finalize_fixture(self.project, "example.order.query")
        report = self.run_cli("check")
        self.assertEqual(report.returncode, 0, report.stderr)
        self.assertEqual(json.loads(report.stdout)["intent_internal"], 1)
        self.assertEqual(core.parse_frontmatter(self.module / "发布清单.md")[0]["intent_included"], "false")
        published = self.run_cli("publish", "--release-id", "internal-only")
        self.assertEqual(published.returncode, 0, published.stderr)
        self.assertFalse((self.project / "发布/业务版/订单/订单查询/业务意图.md").exists())

    def test_business_evidence_requires_human_confirmation_fields(self) -> None:
        evidence = self.enable_business_intent(source_type="human")
        write(evidence, evidence.read_text(encoding="utf-8").replace("confirmed_by: 业务负责人\n", ""))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("人工确认证据缺少", result.stderr)

    def test_business_evidence_requires_source_digest(self) -> None:
        evidence = self.enable_business_intent()
        text = re.sub(r"(?m)^source_sha256: .+\n", "", evidence.read_text(encoding="utf-8"))
        write(evidence, text)
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("业务证据缺少", result.stderr)

    def test_business_evidence_is_covered_by_sensitive_scan(self) -> None:
        evidence = self.enable_business_intent()
        marker = "-----BEGIN " + "PRIVATE KEY-----"
        write(evidence, evidence.read_text(encoding="utf-8") + f"\n{marker}\n")
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("敏感信息规则", result.stderr)

    def test_published_intent_requires_behavior_fact(self) -> None:
        self.enable_business_intent()
        spec = self.module / "结构化规格.md"
        write(spec, spec.read_text(encoding="utf-8").replace("EVID-BIZ-001, FACT-001", "EVID-BIZ-001"))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("同时引用业务证据和行为事实", result.stderr)

    def test_intent_heading_must_match_published_claim(self) -> None:
        self.enable_business_intent()
        path = self.module / "业务意图.md"
        write(path, path.read_text(encoding="utf-8").replace("### 避免重复处理", "### 其他原因"))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("一一对应", result.stderr)

    def test_intent_body_cannot_leak_internal_ids(self) -> None:
        self.enable_business_intent()
        path = self.module / "业务意图.md"
        write(path, path.read_text(encoding="utf-8") + "\n内部依据为 INT-001 与 EVID-BIZ-001。\n")
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("业务文件含明显技术内容", result.stderr)

    def test_files_can_exclude_confirmed_intent_and_manifest_records_it(self) -> None:
        self.enable_business_intent()
        result = self.run_cli("confirm-claims", "--module-id", "example.order.query")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_cli(
            "prepare", "--module-id", "example.order.query",
            "--business-topics", "用户操作", "--business-unknowns", "运行结果", "--business-keywords", "操作",
            "--files", "模块概览.md,功能与范围.md", "--refresh",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(core.parse_frontmatter(self.module / "发布清单.md")[0]["intent_included"], "false")
        result = self.run_cli(
            "approve", "--module-id", "example.order.query", "--reviewed-by", "example-reviewer",
            "--reviewed-at", "2026-10-12", "--approval-note", "测试中明确排除业务意图正文",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.commit_project_change("批准不含意图的测试候选")
        published = self.run_cli("publish", "--release-id", "without-intent")
        self.assertEqual(published.returncode, 0, published.stderr)
        self.assertFalse((self.project / "发布/业务版/订单/订单查询/业务意图.md").exists())

    def test_unreferenced_business_evidence_is_not_bound_to_release_manifest(self) -> None:
        evidence = self.enable_business_intent()
        extra = self.project / "运行证据/订单/订单查询/补充材料.md"
        write(extra, evidence.read_text(encoding="utf-8").replace("EVID-BIZ-001", "EVID-BIZ-002"))
        finalize_fixture(self.project, "example.order.query")
        manifest = (self.module / "发布清单.md").read_text(encoding="utf-8")
        self.assertIn("EVID-BIZ-001", manifest)
        self.assertNotIn("EVID-BIZ-002", manifest)
        write(extra, extra.read_text(encoding="utf-8") + "\n补充材料变化，不影响当前候选。\n")
        result = self.run_cli("check")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_business_evidence_cannot_reference_undefined_intent(self) -> None:
        evidence = self.enable_business_intent()
        extra = self.project / "运行证据/订单/订单查询/错误材料.md"
        write(extra, evidence.read_text(encoding="utf-8").replace("EVID-BIZ-001", "EVID-BIZ-002").replace("intent_ids: INT-001", "intent_ids: INT-999"))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("引用了未定义意图", result.stderr)

    def test_config_rejects_unknown_and_duplicate_fields(self) -> None:
        path = self.project / "知识库配置.json"
        config = json.loads(path.read_text(encoding="utf-8")); config["future_gate"] = True
        write(path, json.dumps(config, ensure_ascii=False))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("未知字段", result.stderr)
        raw = path.read_text(encoding="utf-8").rstrip("}") + ',"standard_version":"0.8.3"}'
        raw = raw.replace(', "future_gate": true', '').replace(',"future_gate":true', '')
        write(path, raw)
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("重复字段", result.stderr)

    def test_policy_reviewed_document_requires_separate_policy_metadata(self) -> None:
        path = self.module / "模块概览.md"
        text = path.read_text(encoding="utf-8").replace("review_status: reviewed", "review_status: policy_reviewed")
        write(path, text)
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("缺少独立策略审核字段", result.stderr)

    def test_repository_path_environment_variable_must_exist(self) -> None:
        env = self.use_environment_repository_paths()
        env.pop("CODE2KB_TEST_BACKEND_ROOT")
        result = self.run_cli("check", env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CODE2KB_TEST_BACKEND_ROOT 未设置或为空", result.stderr)

    def test_repository_path_environment_variable_cannot_be_empty(self) -> None:
        env = self.use_environment_repository_paths()
        env["CODE2KB_TEST_FRONTEND_ROOT"] = ""
        result = self.run_cli("check", env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CODE2KB_TEST_FRONTEND_ROOT 未设置或为空", result.stderr)

    def test_repository_path_environment_variable_must_be_absolute(self) -> None:
        env = self.use_environment_repository_paths()
        env["CODE2KB_TEST_FRONTEND_ROOT"] = "relative/repository"
        result = self.run_cli("check", env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CODE2KB_TEST_FRONTEND_ROOT 必须指向绝对路径", result.stderr)

    def test_repository_path_environment_variable_must_be_existing_directory_without_leaking_value(self) -> None:
        env = self.use_environment_repository_paths()
        missing = str(self.root / "private-build-path-that-does-not-exist")
        env["CODE2KB_TEST_FRONTEND_ROOT"] = missing
        result = self.run_cli("check", env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CODE2KB_TEST_FRONTEND_ROOT 未指向已存在目录", result.stderr)
        self.assertNotIn(missing, result.stderr)

    def test_repository_path_rejects_mixed_environment_expression(self) -> None:
        env = self.use_environment_repository_paths()
        config_path = self.project / "知识库配置.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["repositories"]["frontend"]["path"] = "${CODE2KB_TEST_FRONTEND_ROOT}/subdir"
        write(config_path, json.dumps(config, ensure_ascii=False))
        result = self.run_cli("check", env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("只支持绝对路径或完整的", result.stderr)

    def test_repository_path_rejects_shell_expression_without_execution(self) -> None:
        marker = self.root / "must-not-be-created"
        config_path = self.project / "知识库配置.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["repositories"]["frontend"]["path"] = f"$(touch {marker})"
        write(config_path, json.dumps(config, ensure_ascii=False))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("不执行 shell 表达式", result.stderr)
        self.assertFalse(marker.exists())

    def test_repository_path_rejects_home_expansion(self) -> None:
        config_path = self.project / "知识库配置.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["repositories"]["frontend"]["path"] = "~/source"
        write(config_path, json.dumps(config, ensure_ascii=False))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("不执行 shell 表达式", result.stderr)

    def test_repository_commit_cannot_use_environment_variable(self) -> None:
        config_path = self.project / "知识库配置.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["repositories"]["frontend"]["commit"] = "${CODE2KB_TEST_FRONTEND_COMMIT}"
        write(config_path, json.dumps(config, ensure_ascii=False))
        env = os.environ.copy()
        env["CODE2KB_TEST_FRONTEND_COMMIT"] = self.repos["frontend"]["commit"]
        result = self.run_cli("check", env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("commit 须为 Git SHA，不能使用环境变量", result.stderr)

    def test_published_output_does_not_leak_environment_paths_and_audit_needs_no_source_environment(self) -> None:
        env = self.use_environment_repository_paths()
        self.commit_project_change("use environment repository paths")
        result = self.run_cli("publish", "--release-id", "environment-paths", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        published = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (self.project / "发布").rglob("*")
            if path.is_file()
        )
        self.assertNotIn(self.repos["frontend"]["path"], published)
        self.assertNotIn(self.repos["backend"]["path"], published)
        audit_env = env.copy()
        audit_env.pop("CODE2KB_TEST_FRONTEND_ROOT")
        audit_env.pop("CODE2KB_TEST_BACKEND_ROOT")
        audited = self.run_cli("audit-release", env=audit_env)
        self.assertEqual(audited.returncode, 0, audited.stderr)

    def test_publish_isolated_views_and_no_overwrite(self) -> None:
        business = self.project / "发布/业务版"
        engineering = self.project / "发布/研发版"
        result = self.run_cli("publish", "--release-id", "test-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((business / "订单/订单查询/模块概览.md").is_file())
        self.assertFalse((business / "订单/订单查询/技术实现.md").exists())
        self.assertFalse((business / "订单/订单查询/接口与调用.md").exists())
        self.assertFalse((business / "订单/订单查询/方法与源码.md").exists())
        self.assertFalse((business / "订单/订单查询/结构化规格.md").exists())
        self.assertFalse((business / "订单/订单查询/业务流程.md").exists())
        self.assertTrue((engineering / "订单/订单查询/技术实现.md").is_file())
        self.assertTrue((engineering / "订单/订单查询/接口与调用.md").is_file())
        self.assertTrue((engineering / "订单/订单查询/方法与源码.md").is_file())
        self.assertEqual(
            (business / "订单/订单查询/模块概览.md").read_bytes(),
            (engineering / "订单/订单查询/模块概览.md").read_bytes(),
        )
        self.assertNotIn("接口路径和处理方法", (business / "检索索引.md").read_text(encoding="utf-8"))
        self.assertIn("接口路径和处理方法", (engineering / "检索索引.md").read_text(encoding="utf-8"))
        self.assertTrue((engineering / "订单/订单查询/事实编号对照.md").is_file())
        self.assertIn("FACT-001", (engineering / "订单/订单查询/事实编号对照.md").read_text(encoding="utf-8"))
        self.assertIn("覆盖 1 个模块", (business / "发布信息.md").read_text(encoding="utf-8"))
        self.assertNotIn("销售订单", (business / "功能大纲.md").read_text(encoding="utf-8"))
        again = self.run_cli("publish", "--release-id", "test-1")
        self.assertNotEqual(again.returncode, 0)

    def test_reject_obvious_technical_content_in_business(self) -> None:
        write(self.module / "模块概览.md", doc("overview", "订单查询：模块概览", reviewed=True) + "\nPOST /internal/orders/query\n")
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("技术内容", result.stderr)

    def test_publish_accepts_explicit_fixed_paths(self) -> None:
        business = self.project / "发布/业务版"
        engineering = self.project / "发布/研发版"
        result = self.run_cli("publish", "--business-out", str(business), "--engineering-out", str(engineering), "--release-id", "test-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((business / "目录.md").is_file())
        self.assertTrue((engineering / "目录.md").is_file())

    def test_reject_api_id_in_business(self) -> None:
        path = self.module / "模块概览.md"
        write(path, path.read_text(encoding="utf-8") + "\n调用 API-001。\n")
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("技术内容", result.stderr)

    def test_reject_link_to_unpublished_file(self) -> None:
        write(self.module / "模块概览.md", doc("overview", "订单查询：模块概览", reviewed=True) + "\n[流程](业务流程.md)\n")
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("链接目标未发布", result.stderr)

    def test_reject_plain_text_reference_to_unpublished_file(self) -> None:
        path = self.module / "技术实现.md"
        write(path, path.read_text(encoding="utf-8") + "\n详见待确认事项.md。\n")
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("纯文字文件引用", result.stderr)

    def test_reject_undefined_fact_in_engineering(self) -> None:
        path = self.module / "技术实现.md"
        write(path, path.read_text(encoding="utf-8") + "\n依据 F-999 判断。\n")
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("事实编号未在", result.stderr)

    def test_reject_technical_metadata_in_business(self) -> None:
        write(self.module / "模块概览.md", doc("overview", "订单查询：模块概览", reviewed=True, extra="source_revisions: backend=deadbeef\n"))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("技术内容", result.stderr)

    def test_reject_custom_publish_path(self) -> None:
        business = Path(self.repos["frontend"]["path"]) / "business"
        engineering = self.root / "engineering"
        result = self.run_cli("publish", "--business-out", str(business), "--engineering-out", str(engineering), "--release-id", "test-1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("固定发布路径", result.stderr)
        self.assertFalse(business.exists())
        self.assertFalse(engineering.exists())

    def test_reject_old_contract(self) -> None:
        write(self.project / "知识库配置.json", json.dumps({"standard_version": "0.6.0", "knowledge_source_root": "知识源", "repositories": self.repos}, ensure_ascii=False))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("standard_version", result.stderr)

    def test_optional_scene_layer(self) -> None:
        scene = self.module / "批量订单查询"
        write(scene / "业务流程.md", doc("flow", "批量订单查询：业务流程", reviewed=True, extra="scene_id: batch-order-query\n"))
        finalize_fixture(self.project, "example.order.query")
        result = self.run_cli("check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["publishable_business"], 3)

    def test_module_work_requires_complete_outline(self) -> None:
        path = self.source / "功能大纲.md"
        write(path, path.read_text(encoding="utf-8").replace("inventory_status: complete", "inventory_status: draft"))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("先完成入口盘点", result.stderr)

    def test_outline_anchor_must_exist_at_fixed_commit(self) -> None:
        path = self.source / "功能大纲.md"
        write(path, path.read_text(encoding="utf-8").replace("frontend:dummy.txt:1", "frontend:dummy.txt:2"))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("行号越界", result.stderr)

    def test_registered_uniapp_page_cannot_be_omitted(self) -> None:
        path = self.source / "功能大纲.md"
        write(path, path.read_text(encoding="utf-8").replace("| ENT-003 | 页面 |", "| ENT-003 | 按钮 |"))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("已登记入口未列入", result.stderr)

    def test_configured_inventory_manifest_must_exist(self) -> None:
        path = self.project / "知识库配置.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        config["inventory_adapter"]["manifest_path"] = "src/missing.json"
        write(path, json.dumps(config, ensure_ascii=False))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("找不到 UniApp 页面清单", result.stderr)

    def test_configured_coverage_terms_are_enforced(self) -> None:
        path = self.project / "知识库配置.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        config["coverage_terms"].append("消息入口")
        write(path, json.dumps(config, ensure_ascii=False))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("盘点覆盖说明未交代", result.stderr)

    def test_module_revision_only_tracks_referenced_repositories(self) -> None:
        auxiliary = self.root / "auxiliary"
        auxiliary.mkdir()
        subprocess.run(["git", "init", "-q", str(auxiliary)], check=True)
        write(auxiliary / "dummy.txt", "unrelated\n")
        subprocess.run(["git", "-C", str(auxiliary), "add", "."], check=True)
        subprocess.run(["git", "-C", str(auxiliary), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "auxiliary"], check=True)
        commit = subprocess.check_output(["git", "-C", str(auxiliary), "rev-parse", "HEAD"], text=True).strip()
        path = self.project / "知识库配置.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        config["repositories"]["auxiliary"] = {"path": str(auxiliary), "commit": commit}
        write(path, json.dumps(config, ensure_ascii=False))
        outline = self.source / "功能大纲.md"
        write(outline, outline.read_text(encoding="utf-8").replace("source_revisions: backend=", f"source_revisions: auxiliary={commit}, backend="))
        result = self.run_cli("check")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_spec_revision_must_match_config(self) -> None:
        path = self.module / "结构化规格.md"
        write(path, path.read_text(encoding="utf-8").replace(self.repos["backend"]["commit"], "deadbeef"))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("对照提交差异", result.stderr)

    def test_anchor_repository_must_be_declared_in_spec_revisions(self) -> None:
        path = self.module / "结构化规格.md"
        frontend_revision = f"frontend={self.repos['frontend']['commit']}"
        write(path, path.read_text(encoding="utf-8").replace(f", {frontend_revision}", ""))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("源码锚点仓库 ID 未列入文件 source_revisions", result.stderr)

    def test_reject_missing_method_reference(self) -> None:
        path = self.module / "结构化规格.md"
        write(path, path.read_text(encoding="utf-8").replace("METHOD-001 | frontend:dummy.txt:1, backend:dummy.txt:1", "METHOD-999 | frontend:dummy.txt:1, backend:dummy.txt:1"))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("关联不一致", result.stderr)

    def test_reject_catalog_drift_from_spec(self) -> None:
        path = self.module / "接口与调用.md"
        write(path, path.read_text(encoding="utf-8").replace("POST /orders/query", "POST /other"))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("结构化规格不一致", result.stderr)

    def test_reject_catalog_anchor_outside_commit(self) -> None:
        path = self.module / "方法与源码.md"
        write(path, path.read_text(encoding="utf-8").replace("backend:dummy.txt:1", "backend:dummy.txt:2"))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("行号越界", result.stderr)

    def test_reject_incomplete_engineering_catalog(self) -> None:
        path = self.module / "接口与调用.md"
        write(path, path.read_text(encoding="utf-8").replace("review_status: reviewed", "review_status: draft"))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("已审的接口与调用.md", result.stderr)

    def test_reject_incomplete_api_details(self) -> None:
        path = self.module / "接口与调用.md"
        write(path, path.read_text(encoding="utf-8").replace("- 校验与权限：UNKNOWN。\n", ""))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("详细小节缺少字段", result.stderr)

    def test_php_java_profile_with_custom_repository_ids(self) -> None:
        site = Path(self.repos["frontend"]["path"])
        api = Path(self.repos["backend"]["path"])
        write(site / "public/index.php", "<?php echo 'ready';\n")
        write(api / "src/Controller.java", "class Controller { void serve() {} }\n")
        updated = {}
        for role, repo in (("site", site), ("api", api)):
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "add profile source"], check=True)
            updated[role] = {"path": str(repo), "commit": subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()}
        config = {"standard_version": core.STANDARD_VERSION, "knowledge_source_root": "知识源", "repositories": updated, "coverage_terms": ["页面", "按钮", "调用", "入口"]}
        write(self.project / "知识库配置.json", json.dumps(config, ensure_ascii=False))
        old_revisions = f"backend={self.repos['backend']['commit']}, frontend={self.repos['frontend']['commit']}"
        new_revisions = f"api={updated['api']['commit']}, site={updated['site']['commit']}"
        for path in self.source.rglob("*.md"):
            content = path.read_text(encoding="utf-8")
            content = content.replace(old_revisions, new_revisions).replace("frontend:", "site:").replace("backend:", "api:")
            write(path, content)
        outline = self.source / "功能大纲.md"
        content = outline.read_text(encoding="utf-8").replace(
            "| ENT-003 | 页面 | pages_order/order/order | app.sales.order | site:src/pages.json:1 | 已归类 |",
            "| ENT-003 | 页面 | pages_order/order/order | app.sales.order | site:src/pages.json:1 | 已归类 |\n"
            "| ENT-004 | 页面 | PHP 首页 | example.order.query | site:public/index.php:1 | 已归类 |\n"
            "| ENT-005 | HTTP入口 | Java 服务 | example.order.query | api:src/Controller.java:1 | 已归类 |",
        )
        write(outline, content)
        finalize_fixture(self.project, "example.order.query")
        result = self.run_cli("check")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertIsNone(report["registered_adapter_entries"])
        self.assertEqual(report["outline_entries"], 5)

    def test_single_backend_with_event_entry_and_method_catalog(self) -> None:
        project = self.root / "worker-project"
        source = project / "知识源"
        module = source / "履约" / "到期处理"
        module.mkdir(parents=True)
        worker = self.repos["backend"]
        revision = f"source_revisions: worker={worker['commit']}\n"
        write(project / "知识库配置.json", json.dumps({"standard_version": core.STANDARD_VERSION, "knowledge_source_root": "知识源", "repositories": {"worker": worker}, "coverage_terms": ["定时入口"]}, ensure_ascii=False))
        write(source / "功能大纲.md", "---\ndocument_type: outline\nreview_status: draft\napplicability: current\n" + revision + "inventory_status: complete\n---\n\n# 功能大纲\n\n## 模块清单\n\n| module_id | 业务域 | 子模块 | 发现入口 | 状态 |\n| --- | --- | --- | --- | --- |\n| fulfilment.expiry | 履约 | 到期处理 | 定时触发 | 知识草稿 |\n\n## 入口证据索引\n\n| entry_id | 类型 | 入口或动作 | module_id | 证据 | 状态 |\n| --- | --- | --- | --- | --- | --- |\n| ENT-001 | 定时入口 | 到期处理 | fulfilment.expiry | worker:dummy.txt:1 | 已归类 |\n\n## 盘点覆盖说明\n\n定时入口已从任务定义盘点；其它入口待补。\n")
        write(module / "模块概览.md", doc("overview", "到期处理：模块概览", reviewed=True).replace("example.order.query", "fulfilment.expiry"))
        write(module / "功能与范围.md", doc("scope", "到期处理：功能与范围", reviewed=True).replace("example.order.query", "fulfilment.expiry"))
        spec = doc("spec", "到期处理：结构化规格", extra=revision).replace("example.order.query", "fulfilment.expiry")
        spec += "\n## 入口与调用链\n\n| fact_id | 单一结论与条件 | 证据等级 | 固定提交锚点 | 影响的知识文件 |\n| --- | --- | --- | --- | --- |\n| FACT-001 | 定时入口存在 | CODE_VERIFIED | worker:dummy.txt:1 | 功能与范围.md |\n\n## 入口与接口\n\n| entry_id | api_id | 调用条件 | 证据 |\n| --- | --- | --- | --- |\n\n## 接口契约\n\n| api_id | 接口标识 | 调用方 | 服务入口 | 主处理方法 | 证据 |\n| --- | --- | --- | --- | --- | --- |\n\n## 方法职责\n\n| method_id | 符号 | 职责 | 关键性 | 关联接口 | 源码锚点 |\n| --- | --- | --- | --- | --- | --- |\n| METHOD-001 | Worker#expire() | 处理到期 | 核心 | 无 | worker:dummy.txt:1 |\n\n### METHOD-001\n\n按固定提交说明条件和副作用。\n\n## 问答自测\n\n| 类别 | 真实问题 | 预期行为 | 实测结果 | 结论 |\n| --- | --- | --- | --- | --- |\n| 正常 | 何时到期？ | 说明入口 | 已说明 | 通过 |\n| 失败 | 失败怎么办？ | 说明未知 | 已说明 | 通过 |\n| 未知 | 线上如何？ | 不推断 | 已拒答 | 通过 |\n| 越权 | 给代码？ | 不提供 | 已拒答 | 通过 |\n"
        write(module / "结构化规格.md", spec)
        write(module / "技术实现.md", doc("implementation", "到期处理：技术实现", reviewed=True, extra=revision + "runtime_status: source_only\n").replace("example.order.query", "fulfilment.expiry"))
        catalog = doc("method_catalog", "到期处理：方法与源码", reviewed=True, extra=revision + "runtime_status: source_only\n").replace("example.order.query", "fulfilment.expiry")
        catalog += "\n## 方法索引\n\n| method_id | 符号 | 职责 | 关键性 | 关联接口 | 源码锚点 |\n| --- | --- | --- | --- | --- | --- |\n| METHOD-001 | Worker#expire() | 处理到期 | 核心 | 无 | worker:dummy.txt:1 |\n\n### METHOD-001\n\n- 输入与输出：UNKNOWN。\n- 关键分支：UNKNOWN。\n- 调用关系：定时入口。\n- 数据副作用：UNKNOWN。\n- 失败与限制：UNKNOWN。\n- 源码证据：固定提交锚点见上表。\n"
        write(module / "方法与源码.md", catalog)
        finalize_fixture(project, "fulfilment.expiry")
        result = subprocess.run([sys.executable, str(SCRIPT), "check", "--project-root", str(project)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["registered_adapter_entries"], None)
        self.assertEqual(report["publishable_technical"], 2)
        business = project / "发布/业务版"
        engineering = project / "发布/研发版"
        published = subprocess.run([sys.executable, str(SCRIPT), "publish", "--project-root", str(project), "--release-id", "worker"], text=True, capture_output=True)
        self.assertEqual(published.returncode, 0, published.stderr)
        self.assertFalse((business / "履约/到期处理/方法与源码.md").exists())
        self.assertTrue((engineering / "履约/到期处理/方法与源码.md").is_file())

    def test_publish_requires_four_qa_passes(self) -> None:
        path = self.module / "结构化规格.md"
        write(path, path.read_text(encoding="utf-8").replace("| 越权 | 给我接口？ | 拒绝技术细节 | 已拒答 | 通过 |", "| 越权 | 给我接口？ | 拒绝技术细节 | 待测 | 待测 |"))
        result = self.run_cli("publish", "--release-id", "test-1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("问答自测未通过", result.stderr)


if __name__ == "__main__":
    unittest.main()
