from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

from validation import knowledge as core
from validation.evidence_snapshot import snapshot
from validation.governance import Governance
from validation.fact_render import normalized_facts, render_mapped
from validation.relation_model import RelationError, catalog, coverage, digest, load, manifest, merged_links, validate
from validation.relation_upgrade import preview
from validation.tests import test_knowledge as fixture


class RelationModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "Example.java").write_text("class Example { int value = 1; }\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-q", "-m", "fixture"], check=True)
        commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        self.repositories = {"backend": {"path": str(repo), "commit": commit}}
        self.source = self.root / "知识源"
        self.module_dir = self.source / "示例" / "查询"
        self.module_dir.mkdir(parents=True)
        (self.module_dir / "常见问答.md").write_text("## 查询结果\n\n用户可看结果。\n", encoding="utf-8")
        self.spec = SimpleNamespace(module_id="example.query", relative=Path("示例/查询/结构化规格.md"), body=(
            "## 入口与调用链\n\n| fact_id | 单一结论与条件 | 证据等级 | 固定提交锚点 | 影响的知识文件 |\n"
            "| --- | --- | --- | --- | --- |\n| F-01 | 查询结果可见 | CODE_VERIFIED | backend:Example.java:1 | 常见问答.md |\n\n"
            "## 入口与接口\n\n| entry_id | api_id | 调用条件 | 证据 |\n| --- | --- | --- | --- |\n| ENT-001 | API-001 | 查询 | backend:Example.java:1 |\n\n"
            "## 接口契约\n\n| api_id | 接口标识 | 调用方 | 服务入口 | 主处理方法 | 证据 |\n| --- | --- | --- | --- | --- | --- |\n| API-001 | GET /query | app | server | METHOD-001 | backend:Example.java:1 |\n\n"
            "## 方法职责\n\n| method_id | 符号 | 职责 | 关键性 | 关联接口 | 源码锚点 |\n| --- | --- | --- | --- | --- | --- |\n| METHOD-001 | Example#query | 查询 | 核心 | API-001 | backend:Example.java:1 |\n\n"
            "## 调用匹配\n\n| api_id | 匹配状态 | 调用方证据 | 服务方证据 | 部署配对 | 差异或边界 |\n| --- | --- | --- | --- | --- | --- |\n| API-001 | 疑似匹配 | backend:Example.java:1 | backend:Example.java:1 | 未验证 | 仅静态候选 |\n"
        ))
        self.outline = SimpleNamespace(entries=[("ENT-001", "按钮", "查询", "example.query", "backend:Example.java:1", "已归类")])
        self.record = snapshot("backend:Example.java:1", self.repositories)
        self.data = {
            "schema_version": "0.1", "module_id": "example.query", "nodes": [], "identity_history": [],
            "topics": [{"topic_id": "topic.query.result", "audience": "business", "source_document": "常见问答.md", "source_heading": "查询结果"}],
            "links": [
                {"from_type": "method", "from_id": "METHOD-001", "to_type": "fact", "to_id": "F-01", "status": "verified", "evidence": [self.record], "reviewed_by": "Fixture reviewer", "reviewed_at": "2026-10-24"},
                {"from_type": "fact", "from_id": "F-01", "to_type": "topic", "to_id": "topic.query.result", "status": "verified", "evidence": [self.record], "reviewed_by": "Fixture reviewer", "reviewed_at": "2026-10-24"},
            ],
        }

    def test_candidate_old_link_and_verified_explicit_mapping(self) -> None:
        known, derived, states = catalog(core, self.spec, self.outline)
        self.assertEqual(derived[("entry", "ENT-001", "interface", "API-001")]["status"], "candidate")
        validate(self.data, known=known, module_dir=self.module_dir, repositories=self.repositories)
        links = merged_links(self.data, derived, states)
        self.assertEqual(len(links), 4)
        gaps = coverage(self.spec.module_id, known, self.data["topics"], links)
        self.assertEqual(gaps["entry_without_verified_interface"], ["ENT-001"])
        self.assertEqual(gaps["topic_without_verified_fact"], [])
        raw = (json.dumps(self.data, ensure_ascii=False) + "\n").encode()
        path = self.module_dir / "关系映射.json"
        path.write_bytes(raw)
        self.assertEqual(load(self.source, self.spec)[1], raw)
        result = manifest(self.data, raw, release_id="example-v1", registry_sha256="a" * 64, retrieval_sha256=None, links=links)
        self.assertEqual(result["source_mapping_sha256"], digest(raw))

    def test_suspected_call_cannot_be_promoted(self) -> None:
        _, derived, states = catalog(core, self.spec, self.outline)
        promoted = {"from_type": "entry", "from_id": "ENT-001", "to_type": "interface", "to_id": "API-001", "status": "verified", "evidence": [self.record], "reviewed_by": "Fixture reviewer", "reviewed_at": "2026-10-24"}
        self.data["links"].append(promoted)
        with self.assertRaisesRegex(RelationError, "疑似匹配"):
            merged_links(self.data, derived, states)

    def test_tampered_evidence_and_dangling_topic_fail(self) -> None:
        known, _, _ = catalog(core, self.spec, self.outline)
        self.data["links"][0]["evidence"][0] = {**self.record, "snippet_sha256": "0" * 64}
        with self.assertRaisesRegex(RelationError, "无法从固定提交重建"):
            validate(self.data, known=known, module_dir=self.module_dir, repositories=self.repositories)
        self.data["links"][0]["evidence"][0] = self.record
        self.data["links"][1]["to_id"] = "topic.missing"
        with self.assertRaisesRegex(RelationError, "未知身份"):
            validate(self.data, known=known, module_dir=self.module_dir, repositories=self.repositories)

    def test_malformed_evidence_identity_fails_cleanly(self) -> None:
        known, _, _ = catalog(core, self.spec, self.outline)
        self.data["links"][0]["evidence"][0] = {**self.record, "repository_id": []}
        with self.assertRaisesRegex(RelationError, "关系证据无法"):
            validate(self.data, known=known, module_dir=self.module_dir, repositories=self.repositories)

    def test_one_fact_renders_consistent_audience_sections(self) -> None:
        self.spec.body += ("\n## 规范化事实\n\n| fact_id | 适用条件 | 结论 | 例外与失败 | 未知边界 |\n"
                           "| --- | --- | --- | --- | --- |\n"
                           "| F-01 | 登录后 | 查询结果可见 | 请求失败会提示 | 线上延迟未验证 |\n")
        self.assertEqual(normalized_facts(self.spec, core)["F-01"]["condition"], "登录后")
        rendered = render_mapped(self.spec, self.data, core)[0]
        self.assertIn("登录后", rendered["business"])
        self.assertIn("线上延迟未验证", rendered["business"])
        self.assertEqual(rendered["business"], rendered["retrieval"].split("\n## 出处", 1)[0].rstrip() + "\n")
        self.assertNotIn("F-01", rendered["business"])
        self.assertIn("F-01", rendered["engineering"])

    def test_upgrade_previews_fact_and_topic_before_config_change(self) -> None:
        repo = Path(self.repositories["backend"]["path"])
        (repo / "Example.java").write_text("class Example { int value = 2; }\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-q", "-m", "next source"], check=True)
        newer = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        result = preview(self.data, self.repositories, "backend", newer)
        self.assertEqual(result["affected_fact_ids"], ["F-01"])
        self.assertEqual(result["affected_topic_ids"], ["topic.query.result"])
        self.assertTrue(all(item["outcome"] == "changed_excerpt" for item in result["changed_evidence"]))
        self.assertNotEqual(self.repositories["backend"]["commit"], newer)

    def test_topic_identity_survives_display_heading_change(self) -> None:
        known, _, _ = catalog(core, self.spec, self.outline)
        old_id = self.data["topics"][0]["topic_id"]
        (self.module_dir / "常见问答.md").write_text("## 查询结果说明\n\n用户可看结果。\n", encoding="utf-8")
        self.data["topics"][0]["source_heading"] = "查询结果说明"
        validate(self.data, known=known, module_dir=self.module_dir, repositories=self.repositories)
        self.assertEqual(self.data["topics"][0]["topic_id"], old_id)
        self.data["identity_history"] = [{"old_id": old_id, "new_ids": [old_id], "reason": "错误沿用"}]
        with self.assertRaisesRegex(RelationError, "身份历史"):
            validate(self.data, known=known, module_dir=self.module_dir, repositories=self.repositories)

    def test_same_fact_id_in_another_module_needs_qualified_reference(self) -> None:
        known, _, _ = catalog(core, self.spec, self.outline)
        known["fact"].add("other.module#F-01")
        self.data["links"][1]["from_id"] = "other.module#F-01"
        validate(self.data, known=known, module_dir=self.module_dir, repositories=self.repositories)
        self.data["links"][1]["from_id"] = "missing.module#F-01"
        with self.assertRaisesRegex(RelationError, "未知身份"):
            validate(self.data, known=known, module_dir=self.module_dir, repositories=self.repositories)
        self.data["links"][1]["from_type"] = "method"
        self.data["links"][1]["from_id"] = "other.module#F-01"
        self.data["links"][1]["to_type"] = "fact"
        self.data["links"][1]["to_id"] = "F-01"
        with self.assertRaisesRegex(RelationError, "跨模块身份"):
            validate(self.data, known=known, module_dir=self.module_dir, repositories=self.repositories)

    def test_foreign_fact_change_invalidates_only_registered_consumer(self) -> None:
        header = ("## 入口与调用链\n\n| fact_id | 单一结论与条件 | 证据等级 | 固定提交锚点 | 影响的知识文件 |\n"
                  "| --- | --- | --- | --- | --- |\n")

        def spec(module_id, name, body):
            relative = Path("示例") / name / "结构化规格.md"
            original = (f"---\nmodule_id: {module_id}\ndocument_type: spec\nreview_status: draft\n"
                        "applicability: current\n---\n\n# 示例规格\n\n" + body)
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(original, encoding="utf-8")
            return core.Document(relative, module_id, "示例", name, "spec", {"source_revisions": "backend=fixed"}, body, original)

        provider = spec("example.provider", "供方", header + "| F-01 | 原结论 | CODE_VERIFIED | backend:Example.java:1 | 常见问答.md |\n")
        consumer = spec("example.consumer", "消费方", header)
        unrelated = spec("example.unrelated", "无关方", header)
        relation = {"sha256": "a" * 64, "data": {"links": [
            {"from_type": "fact", "from_id": "example.provider#F-01", "to_type": "topic", "to_id": "topic.query.result"}
        ]}}

        def governance(docs):
            instance = Governance(self.root, self.source, {}, docs, None, core)
            instance.relations = {"example.consumer": relation}
            return instance

        initial = governance([provider, consumer, unrelated])
        self.assertTrue(any(row["fact_id"] == "RELATION" for row in initial.impacts("example.consumer")))
        initial.confirm_claims("example.consumer")
        approved_text = (self.source / consumer.relative).read_text(encoding="utf-8")
        consumer = core.replace(consumer, original=approved_text, body=core.parse_frontmatter(self.source / consumer.relative)[1])
        stable = governance([provider, consumer, unrelated])
        self.assertEqual(stable.impacts("example.consumer"), [])
        changed = core.replace(provider, body=provider.body.replace("原结论", "新结论"))
        changed_governance = governance([changed, consumer, unrelated])
        self.assertTrue(any(row["fact_id"] == "RELATION" for row in changed_governance.impacts("example.consumer")))
        self.assertEqual(changed_governance.impacts("example.unrelated"), [])
        deleted = core.replace(provider, body=header)
        deleted_governance = governance([deleted, consumer, unrelated])
        self.assertTrue(any(row["fact_id"] == "RELATION" for row in deleted_governance.impacts("example.consumer")))
        self.assertEqual(deleted_governance.impacts("example.unrelated"), [])

    def test_cross_module_fact_renders_from_owning_spec(self) -> None:
        self.spec.body += ("\n## 规范化事实\n\n| fact_id | 适用条件 | 结论 | 例外与失败 | 未知边界 |\n"
                           "| --- | --- | --- | --- | --- |\n"
                           "| F-01 | 登录后 | 查询结果可见 | 请求失败会提示 | 线上延迟未验证 |\n")
        external = SimpleNamespace(module_id="other.module", body=self.spec.body)
        self.data["links"][1]["from_id"] = "other.module#F-01"
        rendered = render_mapped(self.spec, self.data, core, {"other.module": external})[0]
        self.assertEqual(rendered["fact_ids"], ["other.module#F-01"])
        self.assertIn("线上延迟未验证", rendered["business"])
        self.assertNotIn("other.module#F-01", rendered["business"])
        self.assertIn("other.module#F-01", rendered["engineering"])


class RelationGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.example = fixture.KnowledgeTests("test_publish_isolated_views_and_no_overwrite")
        self.example.setUp()
        self.addCleanup(self.example.doCleanups)
        self.module = self.example.module
        self.record = snapshot("backend:dummy.txt:1", self.example.repos)
        self.mapping = {
            "schema_version": "0.1", "module_id": "example.order.query", "nodes": [], "identity_history": [],
            "topics": [{"topic_id": "topic.order.visible", "audience": "business", "source_document": "功能与范围.md", "source_heading": "说明"}],
            "links": [{"from_type": "fact", "from_id": "FACT-001", "to_type": "topic", "to_id": "topic.order.visible", "status": "verified", "evidence": [self.record], "reviewed_by": "Fixture reviewer", "reviewed_at": "2026-10-24"}],
        }

    def save(self) -> None:
        (self.module / "关系映射.json").write_text(json.dumps(self.mapping, ensure_ascii=False) + "\n", encoding="utf-8")

    def approve_mapping(self) -> None:
        self.save()
        impact = self.example.run_cli("impact", "--module-id", "example.order.query")
        self.assertEqual(impact.returncode, 0, impact.stderr)
        self.assertTrue(any(item["fact_id"] == "RELATION" for item in json.loads(impact.stdout)["pending_impacts"]))
        confirmed = self.example.run_cli("confirm-claims", "--module-id", "example.order.query")
        self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
        impact = self.example.run_cli("impact", "--module-id", "example.order.query")
        self.assertEqual(json.loads(impact.stdout)["pending_impacts"], [])
        prepared = self.example.run_cli("prepare", "--module-id", "example.order.query", "--business-topics", "用户操作", "--business-unknowns", "运行表现", "--business-keywords", "操作", "--engineering-topics", "接口路径和处理方法", "--engineering-unknowns", "部署配对", "--engineering-keywords", "调用链", "--refresh")
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        approved = self.example.run_cli("approve", "--module-id", "example.order.query", "--reviewed-by", "Fixture reviewer", "--reviewed-at", "2026-10-24", "--approval-note", "仅用于公开夹具")
        self.assertEqual(approved.returncode, 0, approved.stderr)
        subprocess.run(["git", "-C", str(self.example.project), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.example.project), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-q", "-m", "review relation"], check=True)

    def test_mapping_change_invalidates_review_and_candidate(self) -> None:
        self.approve_mapping()
        published = self.example.run_cli("publish", "--release-id", "relation-fixture")
        self.assertEqual(published.returncode, 0, published.stderr)
        audited = self.example.run_cli("audit-release", "--release-id", "relation-fixture")
        self.assertEqual(audited.returncode, 0, audited.stderr)
        self.assertEqual(json.loads(audited.stdout)["relations"]["modules"], 1)
        self.mapping["links"][0]["reviewed_by"] = "Second fixture reviewer"
        self.save()
        self.assertEqual(self.example.run_cli("audit-release", "--release-id", "relation-fixture").returncode, 0)
        impact = self.example.run_cli("impact", "--module-id", "example.order.query")
        self.assertTrue(any(item["fact_id"] == "RELATION" for item in json.loads(impact.stdout)["pending_impacts"]))
        checked = self.example.run_cli("check")
        self.assertNotEqual(checked.returncode, 0)
        self.assertIn("关系依据已变化", checked.stderr)
        frozen = self.example.project / "发布" / "关系输入" / "relation-fixture" / "example.order.query.json"
        frozen.write_bytes(frozen.read_bytes() + b" ")
        self.assertNotEqual(self.example.run_cli("audit-release", "--release-id", "relation-fixture").returncode, 0)

    def test_relation_binds_retrieval_manifest_and_units(self) -> None:
        self.approve_mapping()
        suite_path = self.example.project / "suite.json"
        suite_path.write_text(json.dumps({
            "schema_version": "0.1", "suite_id": "relation-fixture", "audience": "business",
            "cases": [{"case_id": "visible-answer", "query": "用户能看到什么操作说明", "expected_module_ids": ["example.order.query"], "expected_unit_ids": [], "required_phrases": ["这是用户能看到的操作说明"], "required_unknown_phrases": [], "forbidden_phrases": ["METHOD-001"], "top_k": 3}],
        }, ensure_ascii=False), encoding="utf-8")
        published = self.example.run_cli("publish", "--release-id", "relation-with-retrieval", "--with-retrieval", "--retrieval-suite", str(suite_path))
        self.assertEqual(published.returncode, 0, published.stderr)
        manifest = json.loads((self.example.project / "发布/关系清单/relation-with-retrieval.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["retrieval_manifest_sha256"])
        topic = manifest["modules"]["example.order.query"]["topics"][0]
        self.assertTrue(topic["unit_ids"])
        self.assertEqual(self.example.run_cli("audit-release", "--release-id", "relation-with-retrieval").returncode, 0)

    def test_missing_pointer_and_malformed_frozen_mapping_fail_audit(self) -> None:
        self.approve_mapping()
        release_id = "relation-corruption"
        published = self.example.run_cli("publish", "--release-id", release_id)
        self.assertEqual(published.returncode, 0, published.stderr)
        release = self.example.project / "发布"
        pointer_path = release / "当前关系版本.json"
        pointer = pointer_path.read_bytes()
        pointer_path.unlink()
        missing = self.example.run_cli("audit-release", "--release-id", release_id)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("关系", missing.stderr)
        pointer_path.write_bytes(pointer)
        frozen = release / "关系输入" / release_id / "example.order.query.json"
        malformed = json.loads(frozen.read_text(encoding="utf-8"))
        malformed["topics"] = [None]
        frozen.write_text(json.dumps(malformed, ensure_ascii=False), encoding="utf-8")
        manifest_path = release / "关系清单" / f"{release_id}.json"
        relation_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        relation_manifest["mapping_files"][f"发布/关系输入/{release_id}/example.order.query.json"] = digest(frozen.read_bytes())
        relation_manifest["modules"]["example.order.query"]["source_mapping_sha256"] = digest(frozen.read_bytes())
        manifest_path.write_text(json.dumps(relation_manifest, ensure_ascii=False), encoding="utf-8")
        relation_pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        relation_pointer["manifest_sha256"] = digest(manifest_path.read_bytes())
        pointer_path.write_text(json.dumps(relation_pointer, ensure_ascii=False), encoding="utf-8")
        corrupted = self.example.run_cli("relation-audit", "--release-id", release_id)
        self.assertNotEqual(corrupted.returncode, 0)
        self.assertIn("关系", corrupted.stderr)
        self.assertNotIn("Traceback", corrupted.stderr)

    def test_historical_relation_release_remains_auditable_after_new_release(self) -> None:
        self.approve_mapping()
        published = self.example.run_cli("publish", "--release-id", "relation-old")
        self.assertEqual(published.returncode, 0, published.stderr)
        subprocess.run(["git", "-C", str(self.example.project), "add", "发布"], check=True)
        subprocess.run(["git", "-C", str(self.example.project), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-q", "-m", "archive first release"], check=True)
        old_commit = subprocess.check_output(["git", "-C", str(self.example.project), "rev-parse", "HEAD"], text=True).strip()
        published = self.example.run_cli("publish", "--release-id", "relation-new")
        self.assertEqual(published.returncode, 0, published.stderr)
        archived = self.example.project.parent / "historical"
        subprocess.run(["git", "-C", str(self.example.project), "worktree", "add", "-q", "--detach", str(archived), old_commit], check=True)
        historical = subprocess.run([sys.executable, str(fixture.SCRIPT), "audit-release", "--project-root", str(archived), "--release-id", "relation-old"], text=True, capture_output=True)
        self.assertEqual(historical.returncode, 0, historical.stderr)
        self.assertEqual(json.loads(historical.stdout)["relations"]["release_id"], "relation-old")
        current = self.example.run_cli("relation-audit", "--release-id", "relation-new")
        self.assertEqual(current.returncode, 0, current.stderr)
        self.assertEqual(json.loads(current.stdout)["release_id"], "relation-new")


if __name__ == "__main__":
    unittest.main()
