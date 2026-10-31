from __future__ import annotations

import contextlib
from datetime import date, datetime, timedelta, timezone
import io
import json
from pathlib import Path
import shutil
import subprocess
from unittest import mock
import unittest

import test_knowledge as fixture

core, doc, finalize_fixture, write = fixture.core, fixture.doc, fixture.finalize_fixture, fixture.write


class GovernanceTests(unittest.TestCase):
    setUp = fixture.KnowledgeTests.setUp
    run_cli = fixture.KnowledgeTests.run_cli

    def publish(self, release_id="v1"):
        return self.run_cli("publish", "--release-id", release_id)

    def commit_release(self, message="记录当前知识库发布"):
        subprocess.run(["git", "-C", str(self.project), "add", "发布"], check=True)
        subprocess.run(["git", "-C", str(self.project), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-q", "-m", message], check=True)

    def commit_project(self, message="记录策略审核输入"):
        subprocess.run(["git", "-C", str(self.project), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.project), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-q", "-m", message], check=True)

    def enable_policy(self, **overrides):
        config_path = self.project / "知识库配置.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["policy_review"] = {"enabled": True, "policy_file": "自动审核策略/test-policy.json"}
        write(config_path, json.dumps(config, ensure_ascii=False))
        policy = {
            "schema_version": "1.0",
            "policy_id": "test-policy-v1",
            "policy_version": "1.0.0",
            "policy_owner": "example-owner",
            "authorized_at": "2020-01-01",
            "authorization_note": "测试预授权策略",
            "expires_at": "2099-12-31",
            "allowed_module_ids": ["*"],
            "allowed_risk_levels": ["low", "medium"],
            "required_checks": sorted({
                "knowledge_check", "impact_clear", "qa_four_categories", "source_traceability",
                "cross_module_consistency", "sensitive_scan",
            }),
            "manual_gate_categories": ["security_boundary", "business_policy", "financial_policy", "runtime_conflict", "source_gap"],
        }
        policy.update(overrides)
        path = self.project / "自动审核策略/test-policy.json"
        write(path, json.dumps(policy, ensure_ascii=False, indent=2))
        self.commit_project("登记自动审核策略")
        return path

    def prepare_policy_candidate(self):
        result = self.run_cli(
            "prepare", "--module-id", "example.order.query",
            "--business-topics", "用户操作", "--business-unknowns", "运行表现", "--business-keywords", "操作",
            "--engineering-topics", "接口路径和处理方法", "--engineering-unknowns", "部署配对", "--engineering-keywords", "调用链",
            "--refresh",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["review_subject_digest"]

    def policy_record(self, subject, **overrides):
        record = {
            "schema_version": "1.1",
            "run_id": "weekly-test-001",
            "module_id": "example.order.query",
            "policy_id": "test-policy-v1",
            "policy_version": "1.0.0",
            "review_subject_digest": subject,
            "risk_level": "medium",
            "source_revisions": {role: self.repos[role]["commit"] for role in sorted(self.repos)},
            "checks": [
                {"check_id": check, "status": "passed", "report_sha256": core.digest(check)}
                for check in sorted({"knowledge_check", "impact_clear", "qa_four_categories", "source_traceability", "cross_module_consistency", "sensitive_scan"})
            ],
            "findings": [],
            "external_reports": [],
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "executed_by": "ci-bot",
        }
        record.update(overrides)
        path = self.project / "自动审核记录/weekly-test-001/example.order.query.json"
        write(path, json.dumps(record, ensure_ascii=False, indent=2))
        return path

    def complete_policy_review(self, **record_overrides):
        self.enable_policy()
        subject = self.prepare_policy_candidate()
        path = self.policy_record(subject, **record_overrides)
        result = self.run_cli(
            "policy-review", "--module-id", "example.order.query",
            "--evidence-file", path.relative_to(self.project).as_posix(), "--executed-by", "ci-bot",
        )
        return result, path

    def test_policy_review_can_publish_and_records_provenance(self):
        result, record = self.complete_policy_review()
        self.assertEqual(result.returncode, 0, result.stderr)
        meta = core.parse_frontmatter(self.module / "模块概览.md")[0]
        self.assertEqual(meta["review_status"], "policy_reviewed")
        self.assertEqual(meta["executed_by"], "ci-bot")
        self.assertNotIn("reviewed_by", meta)
        self.assertEqual(self.run_cli("check").returncode, 0)
        self.commit_project()
        published = self.publish()
        self.assertEqual(published.returncode, 0, published.stderr)
        registry = json.loads((self.project / "发布/版本清单/v1.json").read_text(encoding="utf-8"))
        self.assertEqual(registry["review_summary"], {"human": 0, "policy_auto": 1})
        self.assertEqual(registry["module_reviews"]["example.order.query"]["executed_by"], "ci-bot")
        self.assertEqual(self.run_cli("audit-release").returncode, 0)
        published_text = "\n".join(path.read_text(encoding="utf-8") for path in (self.project / "发布").rglob("*") if path.is_file())
        self.assertNotIn(record.read_text(encoding="utf-8"), published_text)
        self.assertNotIn("测试预授权策略", published_text)

    def test_human_and_policy_reviewed_modules_can_share_one_release(self):
        second = self.source / "销售" / "订单"
        shutil.copytree(self.module, second)
        for path in second.rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            text = text.replace("example.order.query", "app.sales.order")
            text = text.replace("ENT-001", "ENT-003")
            write(path, text)
        finalize_fixture(self.project, "app.sales.order")

        result, _ = self.complete_policy_review()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.commit_project()
        published = self.publish()
        self.assertEqual(published.returncode, 0, published.stderr)
        registry = json.loads((self.project / "发布/版本清单/v1.json").read_text(encoding="utf-8"))
        self.assertEqual(registry["review_summary"], {"human": 1, "policy_auto": 1})
        self.assertEqual(registry["module_reviews"]["app.sales.order"]["mode"], "human")
        self.assertEqual(registry["module_reviews"]["example.order.query"]["mode"], "policy_auto")
        self.assertEqual(self.run_cli("audit-release").returncode, 0)

    def test_policy_review_requires_enabled_committed_policy(self):
        subject = self.prepare_policy_candidate()
        path = self.policy_record(subject)
        result = self.run_cli("policy-review", "--module-id", "example.order.query", "--evidence-file", path.relative_to(self.project).as_posix(), "--executed-by", "ci-bot")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("没有启用", result.stderr)

        config = json.loads((self.project / "知识库配置.json").read_text(encoding="utf-8"))
        config["policy_review"] = {"enabled": True, "policy_file": "自动审核策略/test-policy.json"}
        write(self.project / "知识库配置.json", json.dumps(config, ensure_ascii=False))
        write(self.project / "自动审核策略/test-policy.json", "{}")
        result = self.run_cli("policy-review", "--module-id", "example.order.query", "--evidence-file", path.relative_to(self.project).as_posix(), "--executed-by", "ci-bot")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("知识库配置未提交", result.stderr)

    def test_policy_review_rejects_candidate_source_check_and_risk_mismatches(self):
        self.enable_policy()
        subject = self.prepare_policy_candidate()
        cases = [
            ({"review_subject_digest": "0" * 64}, "候选内容摘要"),
            ({"source_revisions": {"frontend": self.repos["frontend"]["commit"]}}, "源码提交"),
            ({"risk_level": "high"}, "风险等级"),
            ({"checks": []}, "缺少 checks"),
        ]
        for index, (updates, expected) in enumerate(cases):
            path = self.policy_record(subject, run_id=f"weekly-test-{index + 10}", **updates)
            result = self.run_cli("policy-review", "--module-id", "example.order.query", "--evidence-file", path.relative_to(self.project).as_posix(), "--executed-by", "ci-bot")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(expected, result.stderr)

    def test_policy_review_rejects_manual_gate_and_impersonation(self):
        self.enable_policy()
        subject = self.prepare_policy_candidate()
        finding = [{"finding_id": "finding-001", "category": "business_policy", "severity": "medium", "status": "accepted_boundary", "summary": "业务政策需要确认"}]
        path = self.policy_record(subject, findings=finding)
        result = self.run_cli("policy-review", "--module-id", "example.order.query", "--evidence-file", path.relative_to(self.project).as_posix(), "--executed-by", "ci-bot")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("转人工", result.stderr)
        path = self.policy_record(subject, executed_by="example-owner")
        result = self.run_cli("policy-review", "--module-id", "example.order.query", "--evidence-file", path.relative_to(self.project).as_posix(), "--executed-by", "example-owner")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("不得冒充", result.stderr)

    def test_policy_or_record_change_invalidates_policy_review(self):
        result, record = self.complete_policy_review()
        self.assertEqual(result.returncode, 0, result.stderr)
        write(record, record.read_text(encoding="utf-8").replace('"risk_level": "medium"', '"risk_level": "low"'))
        checked = self.run_cli("check")
        self.assertNotEqual(checked.returncode, 0)
        self.assertIn("审核记录已变化", checked.stderr)

    def test_policy_review_publish_requires_committed_record_and_stamps(self):
        result, _ = self.complete_policy_review()
        self.assertEqual(result.returncode, 0, result.stderr)
        published = self.publish()
        self.assertNotEqual(published.returncode, 0)
        self.assertIn("发布输入未提交", published.stderr)

    def test_policy_review_rejects_mixed_module_status(self):
        result, _ = self.complete_policy_review()
        self.assertEqual(result.returncode, 0, result.stderr)
        path = self.module / "模块概览.md"
        original = path.read_text(encoding="utf-8")
        write(path, original.replace("review_status: policy_reviewed", "review_status: reviewed").replace("review_mode: policy_auto\n", "").replace("review_policy: test-policy-v1\n", "").replace("policy_version: 1.0.0\n", "").replace("policy_owner: example-owner\n", "").replace("executed_by: ci-bot\n", "").replace("review_evidence:", "reviewed_by: tester\nreview_evidence:", 1))
        checked = self.run_cli("check")
        self.assertNotEqual(checked.returncode, 0)

    def test_policy_review_rejects_future_and_timezone_free_records(self):
        self.enable_policy()
        subject = self.prepare_policy_candidate()
        for completed in ((datetime.now(timezone.utc) + timedelta(days=1)).isoformat(), datetime.now().replace(microsecond=0).isoformat()):
            path = self.policy_record(subject, completed_at=completed)
            result = self.run_cli("policy-review", "--module-id", "example.order.query", "--evidence-file", path.relative_to(self.project).as_posix(), "--executed-by", "ci-bot")
            self.assertNotEqual(result.returncode, 0)
            self.assertRegex(result.stderr, "时间|时区")

    def test_policy_review_rejects_expired_or_incomplete_policy(self):
        self.enable_policy(expires_at="2020-01-02")
        subject = self.prepare_policy_candidate()
        path = self.policy_record(subject)
        result = self.run_cli("policy-review", "--module-id", "example.order.query", "--evidence-file", path.relative_to(self.project).as_posix(), "--executed-by", "ci-bot")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("已过期", result.stderr)

    def test_policy_review_requires_external_report_when_policy_requests_it(self):
        required = sorted({"knowledge_check", "impact_clear", "qa_four_categories", "source_traceability", "cross_module_consistency", "sensitive_scan", "external.security_scan"})
        self.enable_policy(required_checks=required)
        subject = self.prepare_policy_candidate()
        checks = [{"check_id": check, "status": "passed", "report_sha256": core.digest(check)} for check in required]
        path = self.policy_record(subject, schema_version="1.0", checks=checks)
        result = self.run_cli("policy-review", "--module-id", "example.order.query", "--evidence-file", path.relative_to(self.project).as_posix(), "--executed-by", "ci-bot")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("1.1 记录", result.stderr)
        report_path = self.project / "自动审核报告/security-scan.json"
        report_body = '{"result":"passed"}\n'
        write(report_path, report_body)
        report_sha = core.digest(report_body)
        next(item for item in checks if item["check_id"] == "external.security_scan")["report_sha256"] = report_sha
        report = [{"name": "external.security_scan", "result": "passed", "sha256": report_sha, "path": "自动审核报告/security-scan.json"}]
        path = self.policy_record(subject, schema_version="1.1", checks=checks, external_reports=report)
        self.commit_project("记录外部审核报告")
        result = self.run_cli("policy-review", "--module-id", "example.order.query", "--evidence-file", path.relative_to(self.project).as_posix(), "--executed-by", "ci-bot")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.commit_project("记录策略审核结果")
        write(report_path, '{"result":"failed"}\n')
        self.assertIn("Git HEAD 不一致", self.run_cli("check").stderr)
        self.assertNotEqual(self.run_cli("publish", "--release-id", "external-report").returncode, 0)
        write(report_path, report_body)
        self.assertEqual(self.run_cli("publish", "--release-id", "external-report").returncode, 0)

    def test_policy_review_rejects_uncommitted_or_changed_external_report(self):
        required = sorted({"knowledge_check", "impact_clear", "qa_four_categories", "source_traceability", "cross_module_consistency", "sensitive_scan", "external.security_scan"})
        self.enable_policy(required_checks=required)
        subject = self.prepare_policy_candidate()
        report_path = self.project / "自动审核报告/security-scan.json"
        body = '{"result":"passed"}\n'
        write(report_path, body)
        sha = core.digest(body)
        checks = [{"check_id": check, "status": "passed", "report_sha256": sha if check == "external.security_scan" else core.digest(check)} for check in required]
        report = [{"name": "external.security_scan", "result": "passed", "sha256": sha, "path": "自动审核报告/security-scan.json"}]
        record = self.policy_record(subject, schema_version="1.1", checks=checks, external_reports=report)
        command = ("policy-review", "--module-id", "example.order.query", "--evidence-file", record.relative_to(self.project).as_posix(), "--executed-by", "ci-bot")
        result = self.run_cli(*command)
        self.assertIn("未提交", result.stderr)
        self.commit_project("记录外部审核报告")
        write(report_path, '{"result":"failed"}\n')
        result = self.run_cli(*command)
        self.assertIn("Git HEAD 不一致", result.stderr)
        write(report_path, body)
        report[0]["sha256"] = core.digest("wrong")
        self.policy_record(subject, schema_version="1.1", checks=checks, external_reports=report)
        result = self.run_cli(*command)
        self.assertIn("内容摘要不匹配", result.stderr)

    def test_new_policy_review_rejects_legacy_optional_external_report(self):
        self.enable_policy()
        subject = self.prepare_policy_candidate()
        report = [{"name": "external.optional_scan", "result": "passed", "sha256": core.digest("unlocated")}]
        path = self.policy_record(subject, schema_version="1.0", external_reports=report)
        result = self.run_cli("policy-review", "--module-id", "example.order.query", "--evidence-file", path.relative_to(self.project).as_posix(), "--executed-by", "ci-bot")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("1.1 记录", result.stderr)
        checks = json.loads(path.read_text(encoding="utf-8"))["checks"]
        checks.append({"check_id": "external.optional_scan", "status": "passed", "report_sha256": core.digest("unlocated")})
        self.policy_record(subject, schema_version="1.1", checks=checks, external_reports=[])
        result = self.run_cli("policy-review", "--module-id", "example.order.query", "--evidence-file", path.relative_to(self.project).as_posix(), "--executed-by", "ci-bot")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("逐项对应", result.stderr)

    def test_historical_record_1_0_remains_readable(self):
        from governance import Governance

        required = sorted({"knowledge_check", "impact_clear", "qa_four_categories", "source_traceability", "cross_module_consistency", "sensitive_scan", "external.security_scan"})
        self.enable_policy(required_checks=required)
        subject = self.prepare_policy_candidate()
        checks = [{"check_id": check, "status": "passed", "report_sha256": core.digest(check)} for check in required]
        report = [{"name": "external.security_scan", "result": "passed", "sha256": core.digest("external.security_scan")}]
        path = self.policy_record(subject, schema_version="1.0", checks=checks, external_reports=report)
        project = self.project.resolve()
        source, config = core.read_config(project)
        docs, outline = core.read_documents(source)
        governance = Governance(project, source, config, docs, outline, core)
        policy, _, _, authorized, expires = governance.read_policy()
        record, _, _ = governance.read_review_record(path.relative_to(self.project).as_posix())
        manifest = next(item for item in docs if item.doc_type == "release_manifest")
        self.assertTrue(governance.validate_review_record("example.order.query", manifest, policy, record, "ci-bot", authorized, expires))

    def test_policy_review_rejects_wrong_types_and_external_digest_mismatch(self):
        self.enable_policy()
        subject = self.prepare_policy_candidate()
        path = self.policy_record(subject, risk_level=[])
        result = self.run_cli("policy-review", "--module-id", "example.order.query", "--evidence-file", path.relative_to(self.project).as_posix(), "--executed-by", "ci-bot")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("风险等级", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

        required = sorted({"knowledge_check", "impact_clear", "qa_four_categories", "source_traceability", "cross_module_consistency", "sensitive_scan", "external.security_scan"})
        self.enable_policy(required_checks=required)
        subject = self.prepare_policy_candidate()
        checks = [{"check_id": check, "status": "passed", "report_sha256": core.digest(check)} for check in required]
        report_body = '{"result":"passed"}\n'
        write(self.project / "自动审核报告/security-scan.json", report_body)
        self.commit_project("记录外部审核报告")
        report = [{"name": "external.security_scan", "result": "passed", "sha256": core.digest(report_body), "path": "自动审核报告/security-scan.json"}]
        path = self.policy_record(subject, schema_version="1.1", checks=checks, external_reports=report)
        result = self.run_cli("policy-review", "--module-id", "example.order.query", "--evidence-file", path.relative_to(self.project).as_posix(), "--executed-by", "ci-bot")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("摘要与报告摘要不一致", result.stderr)

    def test_policy_change_invalidates_policy_review(self):
        result, _ = self.complete_policy_review()
        self.assertEqual(result.returncode, 0, result.stderr)
        policy = self.project / "自动审核策略/test-policy.json"
        write(policy, policy.read_text(encoding="utf-8").replace('"allowed_risk_levels": [', '"allowed_risk_levels": ["high", '))
        checked = self.run_cli("check")
        self.assertNotEqual(checked.returncode, 0)
        self.assertIn("Git HEAD 不一致", checked.stderr)

    def test_policy_review_rejects_sensitive_review_record(self):
        self.enable_policy()
        subject = self.prepare_policy_candidate()
        finding = [{"finding_id": "finding-001", "category": "quality_note", "severity": "low", "status": "resolved", "summary": "AKIA1234567890ABCDEF"}]
        path = self.policy_record(subject, findings=finding)
        result = self.run_cli("policy-review", "--module-id", "example.order.query", "--evidence-file", path.relative_to(self.project).as_posix(), "--executed-by", "ci-bot")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("敏感信息规则", result.stderr)

    def test_policy_review_rejects_duplicate_json_fields(self):
        self.enable_policy()
        subject = self.prepare_policy_candidate()
        path = self.policy_record(subject)
        text = path.read_text(encoding="utf-8")
        write(path, text.replace('"schema_version": "1.1",', '"schema_version": "1.1",\n  "schema_version": "1.1",', 1))
        result = self.run_cli("policy-review", "--module-id", "example.order.query", "--evidence-file", path.relative_to(self.project).as_posix(), "--executed-by", "ci-bot")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("重复字段", result.stderr)

    def test_review_metadata_alone_cannot_publish(self):
        (self.module / "发布清单.md").unlink()
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("明确批准的发布清单", result.stderr)

    def test_changed_body_invalidates_approval(self):
        path = self.module / "功能与范围.md"
        write(path, path.read_text(encoding="utf-8") + "\n新的业务条件。\n")
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("发布清单已过期", result.stderr)

    def test_changed_index_topics_invalidates_approval(self):
        path = self.module / "发布清单.md"
        write(path, path.read_text(encoding="utf-8").replace("business_unknowns: 运行表现", "business_unknowns: 无"))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("主题、边界或批准记录已变化", result.stderr)

    def test_legacy_manifest_fields_are_rejected(self):
        path = self.module / "发布清单.md"
        write(path, path.read_text(encoding="utf-8").replace("business_topics: 用户操作", "answerable_topics: 用户操作\nbusiness_topics: 用户操作"))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("当前知识规范不支持的旧字段", result.stderr)

    def test_changed_fact_reports_affected_file(self):
        spec = self.module / "结构化规格.md"
        write(spec, spec.read_text(encoding="utf-8").replace("用户可提交查询", "仅有资格的用户可提交查询"))
        result = self.run_cli("impact")
        self.assertEqual(result.returncode, 0, result.stderr)
        impacts = json.loads(result.stdout)["pending_impacts"]
        self.assertEqual([(row["fact_id"], row["file"]) for row in impacts], [("FACT-001", "功能与范围.md")])

    def test_removed_fact_requires_review_of_deleted_relationship(self):
        spec = self.module / "结构化规格.md"
        write(spec, spec.read_text(encoding="utf-8").replace("| FACT-001 | 用户可提交查询 | CODE_VERIFIED | frontend:dummy.txt:1 | 功能与范围.md |\n", ""))
        result = self.run_cli("impact")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("删除影响", result.stdout)

    def test_document_commit_must_contain_exact_inputs(self):
        outline = self.source / "功能大纲.md"
        write(outline, outline.read_text(encoding="utf-8") + "\n补充盘点备注。\n")
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("发布输入未提交", result.stderr)
        self.assertFalse((self.project / "发布/当前版本.json").exists())

    def test_unrelated_untracked_notes_do_not_block_release(self):
        write(self.project / "个人便笺.txt", "未纳入本次发布输入\n")
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_publish_preserves_all_eight_documents_and_routes(self):
        for name, kind in (("业务流程.md", "flow"), ("规则与限制.md", "rules"), ("常见问答.md", "faq")):
            write(self.module / name, doc(kind, f"订单查询：{name[:-3]}", reviewed=True) + "\n## 特定条件\n\n仅在满足条件时使用。\n")
        finalize_fixture(self.project, "example.order.query")
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual((report["publishable_business"], report["publishable_technical"]), (5, 3))
        business, engineering = self.project / "发布/业务版", self.project / "发布/研发版"
        for name, kind in core.TYPES.items():
            if kind in core.INTERNAL:
                self.assertFalse((business / "订单/订单查询" / name).exists())
                self.assertFalse((engineering / "订单/订单查询" / name).exists())
            elif kind in core.BUSINESS | core.ENGINEERING:
                if not (self.module / name).is_file():
                    continue
                original = (self.module / name).read_bytes()
                self.assertEqual((engineering / "订单/订单查询" / name).read_bytes(), original)
                if kind in core.BUSINESS:
                    self.assertEqual((business / "订单/订单查询" / name).read_bytes(), original)
                else:
                    self.assertFalse((business / "订单/订单查询" / name).exists())
        self.assertIn("特定条件", (business / "检索索引.md").read_text(encoding="utf-8"))
        self.assertNotIn("METHOD-001", (business / "检索索引.md").read_text(encoding="utf-8"))
        self.assertIn("METHOD-001", (engineering / "检索索引.md").read_text(encoding="utf-8"))
        self.assertTrue(json.loads((self.project / "发布/当前版本.json").read_text(encoding="utf-8"))["document_commit"])

    def test_published_file_mutation_is_detected(self):
        self.assertEqual(self.publish().returncode, 0)
        path = self.project / "发布/业务版/订单/订单查询/模块概览.md"
        write(path, path.read_text(encoding="utf-8") + "\n被篡改的结论\n")
        result = self.run_cli("audit-release")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("内容已被修改", result.stderr)

    def test_extra_file_in_business_view_is_detected(self):
        self.assertEqual(self.publish().returncode, 0)
        write(self.project / "发布/业务版/调试信息.md", "# 不应索引的调试信息\n")
        result = self.run_cli("audit-release")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("增加", result.stderr)

    def test_artifact_only_repository_can_audit_without_config_or_knowledge_source(self):
        self.assertEqual(self.publish("artifact-v1").returncode, 0)
        artifact = self.root / "artifact-only"
        shutil.copytree(self.project / "发布", artifact / "发布")
        result = subprocess.run(
            [fixture.sys.executable, str(fixture.SCRIPT), "audit-release", "--project-root", str(artifact)],
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["release_id"], "artifact-v1")

    def test_future_generator_cannot_omit_review_provenance(self):
        self.assertEqual(self.publish("future-v1").returncode, 0)
        registry_path = self.project / "发布/版本清单/future-v1.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["generated_by"]["version"] = "0.8.4"
        registry.pop("registry_schema_version", None)
        registry.pop("review_summary", None)
        registry.pop("module_reviews", None)
        write(registry_path, json.dumps(registry, ensure_ascii=False, indent=2) + "\n")
        pointer_path = self.project / "发布/当前版本.json"
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer["generated_by"]["version"] = "0.8.4"
        pointer["registry_sha256"] = core.digest(registry_path.read_bytes())
        write(pointer_path, json.dumps(pointer, ensure_ascii=False, indent=2) + "\n")
        result = self.run_cli("audit-release")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("版本清单字段不完整", result.stderr)

    def test_audit_rejects_duplicate_pointer_fields(self):
        self.assertEqual(self.publish("duplicate-v1").returncode, 0)
        pointer_path = self.project / "发布/当前版本.json"
        text = pointer_path.read_text(encoding="utf-8")
        write(pointer_path, text.replace('"release_id": "duplicate-v1",', '"release_id": "duplicate-v1",\n  "release_id": "duplicate-v1",', 1))
        result = self.run_cli("audit-release")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("重复字段", result.stderr)

    def test_policy_auto_review_can_publish_complete_business_intent(self):
        fixture.KnowledgeTests.enable_business_intent(self)
        finalize_fixture(self.project, "example.order.query")
        self.enable_policy()
        subject = self.prepare_policy_candidate()
        record = self.policy_record(subject)
        reviewed = self.run_cli(
            "policy-review", "--module-id", "example.order.query",
            "--evidence-file", record.relative_to(self.project).as_posix(), "--executed-by", "ci-bot",
        )
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
        self.commit_project("记录带业务意图的自动审核输入")
        published = self.publish("intent-policy-v1")
        self.assertEqual(published.returncode, 0, published.stderr)
        self.assertTrue((self.project / "发布/业务版/订单/订单查询/业务意图.md").is_file())
        registry = json.loads((self.project / "发布/版本清单/intent-policy-v1.json").read_text(encoding="utf-8"))
        self.assertEqual(registry["review_summary"], {"human": 0, "policy_auto": 1})

    def test_second_release_overwrites_snapshot_and_keeps_first_in_git(self):
        self.assertEqual(self.publish("v1").returncode, 0)
        self.commit_release("发布 v1")
        self.assertEqual(self.publish("v2").returncode, 0)
        pointer = json.loads((self.project / "发布/当前版本.json").read_text(encoding="utf-8"))
        self.assertEqual(pointer["release_id"], "v2")
        self.assertEqual(pointer["standard_version"], core.STANDARD_VERSION)
        self.assertEqual(pointer["history_backend"], "git")
        self.assertEqual(pointer["generated_by"]["name"], "Code2KB Spec")
        self.assertTrue(pointer["generated_by"]["version"])
        self.assertTrue((self.project / "发布/研发版/目录.md").is_file())
        self.assertFalse((self.project / "发布/版本清单/v1.json").exists())
        old = subprocess.run(["git", "-C", str(self.project), "show", "HEAD:发布/当前版本.json"], text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(old.stdout)["release_id"], "v1")
        self.assertEqual(self.run_cli("audit-release").returncode, 0)

    def test_second_release_requires_current_snapshot_committed(self):
        self.assertEqual(self.publish("v1").returncode, 0)
        result = self.publish("v2")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("完整提交到 Git", result.stderr)
        self.assertEqual(json.loads((self.project / "发布/当前版本.json").read_text(encoding="utf-8"))["release_id"], "v1")

    def test_release_id_cannot_be_reused_from_git_history(self):
        self.assertEqual(self.publish("v1").returncode, 0)
        self.commit_release("发布 v1")
        self.assertEqual(self.publish("v2").returncode, 0)
        result = self.publish("v1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("历史版本使用", result.stderr)

    def test_first_release_declares_git_history(self):
        self.assertEqual(self.publish("v1").returncode, 0)
        pointer = json.loads((self.project / "发布/当前版本.json").read_text(encoding="utf-8"))
        self.assertEqual(pointer["history_backend"], "git")
        self.assertEqual(pointer["standard_version"], core.STANDARD_VERSION)
        self.assertEqual(pointer["release_id"], "v1")
        self.assertEqual(pointer["generated_by"], {"name": "Code2KB Spec", "version": core.IMPLEMENTATION_VERSION})
        self.assertNotEqual(pointer["generated_by"]["version"], pointer["standard_version"])
        self.assertEqual(pointer["business_path"], "发布/业务版")
        self.assertEqual(pointer["engineering_path"], "发布/研发版")
        self.assertNotIn("previous_release_id", pointer)
        release_info = (self.project / "发布/业务版/发布信息.md").read_text(encoding="utf-8")
        self.assertIn("内容版本：v1", release_info)
        self.assertIn(f"知识规范：{core.STANDARD_VERSION}", release_info)
        self.assertIn(f"生成工具：Code2KB Spec {core.IMPLEMENTATION_VERSION}", release_info)

    def test_audit_rejects_invalid_history_backend(self):
        self.assertEqual(self.publish("v1").returncode, 0)
        path = self.project / "发布/当前版本.json"
        pointer = json.loads(path.read_text(encoding="utf-8"))
        pointer["history_backend"] = "directory-switch"
        write(path, json.dumps(pointer, ensure_ascii=False))
        result = self.run_cli("audit-release")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("历史管理方式无效", result.stderr)

    def test_boundary_counts_cannot_be_overridden_in_notes(self):
        path = self.project / "知识库配置.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        config["boundary_notes"] = {"business": "本目录覆盖 9 个模块"}
        write(path, json.dumps(config, ensure_ascii=False))
        subprocess.run(["git", "-C", str(self.project), "add", "知识库配置.json"], check=True)
        subprocess.run(["git", "-C", str(self.project), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "test boundary"], check=True)
        result = self.publish("v1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("不得手写覆盖数量", result.stderr)

    def test_business_index_rejects_process_vocabulary(self):
        from governance import scan_business_terms
        leaked = "需限定或仍未知：写入方法带事务注解且经同类自身代理调用，事务是否实际生效未运行验证（业务正文不承诺整体撤销）；累计回访数为无行锁读改写（推断并发可能少计）"
        with self.assertRaises(ValueError) as context:
            scan_business_terms(core, leaked, "检索索引.md")
        self.assertIn("业务版生成内容含禁用表述", str(context.exception))
        for sample in ("（见待确认事项）", "全字段详情端点未见区域校验", "（已列入集中审核）", "（F-18/F-18b）", "实现旁注释称数仓异步", "依赖共享子模块"):
            with self.assertRaises(ValueError, msg=sample):
                scan_business_terms(core, sample, "检索索引.md")
        scan_business_terms(core, "数据是否存在缓存或延迟；上传失败只在日志里记录", "检索索引.md")

    def test_business_generated_navigation_rejects_repository_url(self):
        from governance import scan_business_terms
        with self.assertRaisesRegex(ValueError, "源码仓库链接"):
            scan_business_terms(core, "[参考](https://github.com/example/repo/blob/abc1234/README.md#L3)", "目录.md")
        with self.assertRaisesRegex(ValueError, "源码仓库链接"):
            scan_business_terms(core, "[参考](https://github.com/example&#47;repo)", "目录.md")
        scan_business_terms(core, "[帮助](https://example.invalid/help/orders)", "目录.md")
        with self.assertRaisesRegex(ValueError, "禁用表述"):
            scan_business_terms(core, "METHOD-001", "旧目录.md", source_urls=False)

    def test_frozen_08_source_url_fixture_remains_auditable(self):
        frozen = Path(__file__).resolve().parents[2] / "conformance/legacy-url-release"
        result = subprocess.run(
            [fixture.sys.executable, str(fixture.SCRIPT), "audit-release", "--project-root", str(frozen)],
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["generated_by"]["version"], "0.8.0")

    def test_audit_source_url_rule_follows_generator_version(self):
        # Start from a genuine frozen 0.8 release. A new 1.0 publish must not
        # be relabeled as 0.8 merely to test the historical audit rule.
        frozen = Path(__file__).resolve().parents[2] / "conformance/legacy-url-release"
        candidate = self.root / "legacy-url-audit-copy"
        shutil.copytree(frozen, candidate)
        release = candidate / "发布"
        legacy_audit = subprocess.run(
            [fixture.sys.executable, str(fixture.SCRIPT), "audit-release", "--project-root", str(candidate)],
            text=True, capture_output=True)
        self.assertEqual(legacy_audit.returncode, 0, legacy_audit.stderr)

        registry_path = release / "版本清单/v08-source-url.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        pointer_path = release / "当前版本.json"
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        registry["generated_by"]["version"] = "1.0.0"
        pointer["generated_by"]["version"] = "1.0.0"
        write(registry_path, json.dumps(registry, ensure_ascii=False, indent=2) + "\n")
        pointer["registry_sha256"] = core.digest(registry_path.read_bytes())
        write(pointer_path, json.dumps(pointer, ensure_ascii=False, indent=2) + "\n")
        current_audit = subprocess.run(
            [fixture.sys.executable, str(fixture.SCRIPT), "audit-release", "--project-root", str(candidate)],
            text=True, capture_output=True)
        self.assertNotEqual(current_audit.returncode, 0)
        self.assertIn("源码仓库链接", current_audit.stderr)

    def test_prepare_refuses_process_vocabulary_in_topics(self):
        result = self.run_cli("prepare", "--module-id", "example.order.query", "--business-topics", "用户操作", "--business-unknowns", "写入方法带事务注解且经同类自身代理调用", "--business-keywords", "操作", "--refresh")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("业务语言", result.stderr)

    def test_current_pointer_tampering_is_detected(self):
        self.assertEqual(self.publish().returncode, 0)
        path = self.project / "发布/当前版本.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["registry_sha256"] = "0" * 64
        write(path, json.dumps(value))
        result = self.run_cli("audit-release")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("当前版本指针", result.stderr)

    def test_incomplete_pointer_reports_a_validation_error(self):
        self.assertEqual(self.publish().returncode, 0)
        write(self.project / "发布/当前版本.json", "{}")
        result = self.run_cli("audit-release")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("指针字段不完整", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_release_cannot_use_reserved_pointer_path_as_a_directory(self):
        result = self.run_cli("publish", "--business-out", str(self.project / "发布/当前版本.json"), "--engineering-out", str(self.project / "发布/new-engineering"), "--release-id", "v1")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.project / "发布/当前版本.json").exists())

    def test_failed_second_view_does_not_change_current_pointer(self):
        self.assertEqual(self.publish().returncode, 0)
        pointer = self.project / "发布/当前版本.json"
        prior = pointer.read_bytes()
        real_make = core.make_release
        calls = []

        def fail_second(*args):
            calls.append(args)
            if len(calls) == 2:
                raise OSError("simulated second view failure")
            return real_make(*args)

        self.commit_release("发布 v1")
        argv = ["knowledge.py", "publish", "--project-root", str(self.project), "--release-id", "v2"]
        with mock.patch("sys.argv", argv), mock.patch.object(core, "make_release", side_effect=fail_second), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(core.main(), 1)
        self.assertEqual(pointer.read_bytes(), prior)
        self.assertEqual(json.loads(pointer.read_text(encoding="utf-8"))["release_id"], "v1")
        self.assertFalse((self.project / "发布/版本清单/v2.json").exists())

    def test_failed_post_install_audit_restores_previous_snapshot(self):
        self.assertEqual(self.publish("v1").returncode, 0)
        pointer = self.project / "发布/当前版本.json"
        prior = pointer.read_bytes()
        self.commit_release("发布 v1")
        real_audit = core.Governance.audit_release
        calls = []

        def fail_new_snapshot(instance, release_id):
            calls.append(release_id)
            if len(calls) == 2:
                raise ValueError("simulated post-install audit failure")
            return real_audit(instance, release_id)

        argv = ["knowledge.py", "publish", "--project-root", str(self.project), "--release-id", "v2"]
        with mock.patch("sys.argv", argv), mock.patch.object(core.Governance, "audit_release", new=fail_new_snapshot), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(core.main(), 1)
        self.assertEqual(pointer.read_bytes(), prior)
        self.assertEqual(json.loads(pointer.read_text(encoding="utf-8"))["release_id"], "v1")
        self.assertTrue((self.project / "发布/版本清单/v1.json").is_file())

    def evidence(self, *, kind="runtime", expired=False):
        observed, expiry = ("2020-01-01", "2020-02-01") if expired else ("2026-01-01", "2099-01-01")
        revisions = f"backend={self.repos['backend']['commit']}, frontend={self.repos['frontend']['commit']}"
        path = self.project / "运行证据/订单/订单查询/测试观测.md"
        write(path, f"---\ndocument_type: runtime_evidence\nevidence_id: EVID-001\nmodule_id: example.order.query\nevidence_type: {kind}\nenvironment: 测试\nobserved_at: {observed}\nvalid_until: {expiry}\nfact_ids: FACT-001\nsource_revisions: {revisions}\n---\n\n# 测试观测\n\n## 来源与方法\n\n测试日志。\n\n## 观察或确认结果\n\n固定条件下可查询。\n\n## 适用范围与不能证明的事项\n\n仅该平台，不认证其他环境。\n\n## 脱敏说明\n\n无个人资料。\n")
        spec = self.module / "结构化规格.md"
        write(spec, spec.read_text(encoding="utf-8").replace("| CODE_VERIFIED | frontend:dummy.txt:1 |", "| RUN_VERIFIED | EVID-001 |"))
        return path

    def test_runtime_claim_requires_registered_evidence(self):
        spec = self.module / "结构化规格.md"
        write(spec, spec.read_text(encoding="utf-8").replace("| CODE_VERIFIED | frontend:dummy.txt:1 |", "| RUN_VERIFIED | EVID-MISSING |"))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("证据未登记", result.stderr)

    def test_business_confirmation_cannot_be_used_as_runtime_observation(self):
        evidence = fixture.KnowledgeTests.enable_business_intent(self)
        write(evidence, evidence.read_text(encoding="utf-8").replace("fact_ids: 无", "fact_ids: FACT-001"))
        spec = self.module / "结构化规格.md"
        write(spec, spec.read_text(encoding="utf-8").replace("| CODE_VERIFIED | frontend:dummy.txt:1 |", "| RUN_VERIFIED | EVID-BIZ-001 |"))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("证据类型不支持", result.stderr)

    def test_expired_evidence_blocks_publish(self):
        self.evidence(expired=True)
        finalize_fixture(self.project, "example.order.query")
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("证据已失效", result.stderr)

    def test_expired_unpublished_module_does_not_block_current_release(self):
        module = self.source / "销售/订单"
        revision = f"source_revisions: backend={self.repos['backend']['commit']}\n"
        for name, kind in (("模块概览.md", "overview"), ("功能与范围.md", "scope")):
            write(module / name, doc(kind, "订单草稿").replace("example.order.query", "app.sales.order"))
        spec = (self.module / "结构化规格.md").read_text(encoding="utf-8")
        spec = spec.replace("example.order.query", "app.sales.order").replace("reviewed_by: example-reviewer\n", "").replace("reviewed_at: 2026-10-12\n", "")
        from governance import replace_section, FACT_HEADER, MATCH_HEADER
        spec = replace_section(spec, "## 入口与调用链", "## 入口与调用链\n\n" + FACT_HEADER + "\n| --- | --- | --- | --- | --- |\n| FACT-OTHER | 仅旧环境的观测 | RUN_VERIFIED | EVID-OTHER | 功能与范围.md |\n")
        spec = replace_section(spec, "## 入口与接口", "## 入口与接口\n\n| entry_id | api_id | 调用条件 | 证据 |\n| --- | --- | --- | --- |\n")
        spec = replace_section(spec, "## 接口契约", "## 接口契约\n\n| api_id | 接口标识 | 调用方 | 服务入口 | 主处理方法 | 证据 |\n| --- | --- | --- | --- | --- | --- |\n")
        spec = replace_section(spec, "## 方法职责", "## 方法职责\n\n| method_id | 符号 | 职责 | 关键性 | 关联接口 | 源码锚点 |\n| --- | --- | --- | --- | --- | --- |\n")
        spec = replace_section(spec, "## 调用匹配", "## 调用匹配\n\n" + MATCH_HEADER + "\n| --- | --- | --- | --- | --- | --- |\n")
        spec = spec.split("## 大纲覆盖核对\n", 1)[0]
        write(module / "结构化规格.md", spec)
        evidence = f"---\ndocument_type: runtime_evidence\nevidence_id: EVID-OTHER\nmodule_id: app.sales.order\nevidence_type: runtime\nenvironment: 旧测试\nobserved_at: 2020-01-01\nvalid_until: 2020-02-01\nfact_ids: FACT-OTHER\n{revision}---\n\n# 订单旧测试\n\n## 来源与方法\n\n测试。\n\n## 观察或确认结果\n\n测试结果。\n\n## 适用范围与不能证明的事项\n\n只限旧测试。\n\n## 脱敏说明\n\n无个人信息。\n"
        write(self.project / "运行证据/销售/订单/旧测试.md", evidence)
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("EVID-OTHER", json.loads(result.stdout)["expired_runtime_evidence"])
        self.assertFalse((self.project / "发布/业务版/销售").exists())

    def test_evidence_change_invalidates_module_approval(self):
        path = self.evidence()
        finalize_fixture(self.project, "example.order.query")
        write(path, path.read_text(encoding="utf-8") + "\n新的观察结果。\n")
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("运行依据已变化", result.stderr)

    def test_static_matching_does_not_prove_deployment(self):
        for name in ("结构化规格.md", "接口与调用.md"):
            path = self.module / name
            write(path, path.read_text(encoding="utf-8").replace("| 未验证 | 静态匹配 |", "| EVID-DEPLOY | 静态匹配 |"))
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("证据未登记", result.stderr)

    def test_secret_pattern_stops_release_before_activation(self):
        path = self.module / "技术实现.md"
        marker = "-----BEGIN " + "PRIVATE KEY-----"
        write(path, path.read_text(encoding="utf-8") + f"\n{marker}\n")
        finalize_fixture(self.project, "example.order.query")
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("敏感信息规则", result.stderr)
        self.assertFalse((self.project / "发布/当前版本.json").exists())

    def test_valid_runtime_evidence_can_be_published_in_limited_scope(self):
        self.evidence()
        implementation = self.module / "技术实现.md"
        write(implementation, implementation.read_text(encoding="utf-8").replace("runtime_status: source_only", "runtime_status: runtime_verified\nruntime_evidence: EVID-001") + "\n## 运行范围\n\n仅验证 FACT-001，其他情况仍未知。\n")
        finalize_fixture(self.project, "example.order.query")
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["runtime_evidence"], 1)
        self.assertFalse((self.project / "发布/业务版/运行证据").exists())

    def test_business_only_package_retains_technical_sources_as_drafts(self):
        result = self.run_cli("prepare", "--module-id", "example.order.query", "--business-topics", "用户操作", "--business-unknowns", "运行结果", "--business-keywords", "操作", "--files", "模块概览.md,功能与范围.md", "--refresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_cli("approve", "--module-id", "example.order.query", "--reviewed-by", "example-reviewer", "--reviewed-at", "2026-10-12", "--approval-note", "测试夹具仅批准业务正文")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_cli("check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["publishable_technical"], 0)
        self.assertTrue((self.module / "接口与调用.md").is_file())
        self.assertEqual(core.parse_frontmatter(self.module / "接口与调用.md")[0]["review_status"], "draft")

    def test_preparation_can_handle_affected_file_returned_to_draft(self):
        overview = self.module / "模块概览.md"
        write(overview, overview.read_text(encoding="utf-8").replace("review_status: reviewed", "review_status: draft") + "\n[新增流程](业务流程.md)\n")
        result = self.run_cli("confirm-claims", "--module-id", "example.order.query")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_cli("prepare", "--module-id", "example.order.query", "--business-topics", "用户操作", "--business-unknowns", "运行结果", "--business-keywords", "操作", "--refresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["candidate_files"], 6)

    def test_crlf_business_content_is_copied_without_loss(self):
        path = self.module / "功能与范围.md"
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        finalize_fixture(self.project, "example.order.query")
        source = path.read_bytes()
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.project / "发布/业务版/订单/订单查询/功能与范围.md").read_bytes(), source)


if __name__ == "__main__":
    unittest.main()
