from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import test_knowledge as fixtures

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import knowledge as core
from retrieval_evaluate import evaluate_data, load_suite
from retrieval_build import build_in_release, coverage_report, index_sections, metadata_candidates
from retrieval_model import RetrievalError, digest, json_bytes, read_unit
from retrieval_profile import compare


def suite(*, required=None, unknown=None, forbidden=None):
    return {
        "schema_version": "0.1", "suite_id": "public-test", "audience": "business",
        "cases": [{
            "case_id": "order-explanation", "query": "用户能看到什么操作说明",
            "expected_module_ids": ["example.order.query"], "expected_unit_ids": [],
            "required_phrases": required if required is not None else ["这是用户能看到的操作说明"],
            "required_unknown_phrases": unknown or [], "forbidden_phrases": forbidden or ["METHOD-001"],
            "top_k": 3,
        }],
    }


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.KnowledgeTests("test_publish_isolated_views_and_no_overwrite")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.project = self.fixture.project
        self.suite_path = self.project / "test-suite.json"
        fixtures.write(self.suite_path, json.dumps(suite(), ensure_ascii=False))

    def publish(self):
        result = self.fixture.run_cli("publish", "--release-id", "retrieval-test")
        self.assertEqual(result.returncode, 0, result.stderr)

    def build(self):
        result = self.fixture.run_cli("retrieval-build", "--release-id", "retrieval-test")
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.project / "发布"

    def test_business_unit_build_rejects_source_repository_url(self):
        self.publish()
        release = self.project / "发布"
        local = "订单/订单查询/模块概览.md"
        overview = release / "业务版" / local
        fixtures.write(overview, overview.read_text(encoding="utf-8") + "\n[参考](https://github.com/example/repo/blob/abc1234/README.md#L3)\n")
        registry_path = release / "版本清单/retrieval-test.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["views"]["business"]["files"][local] = core.digest(overview.read_bytes())
        fixtures.write(registry_path, json.dumps(registry, ensure_ascii=False, indent=2) + "\n")
        pointer_path = release / "当前版本.json"
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer["registry_sha256"] = core.digest(registry_path.read_bytes())
        fixtures.write(pointer_path, json.dumps(pointer, ensure_ascii=False, indent=2) + "\n")
        result = self.fixture.run_cli("retrieval-build", "--release-id", "retrieval-test")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("源码仓库链接", result.stderr)
        self.assertFalse((release / "检索版").exists())

    def test_build_is_deterministic_and_requires_evaluation(self):
        self.publish()
        self.assertFalse((self.project / "发布/检索版").exists())
        release = self.build()
        manifest_path = release / "检索清单/retrieval-test.json"
        first = manifest_path.read_bytes()
        self.assertFalse((release / "当前检索版本.json").exists())
        self.assertNotEqual(self.fixture.run_cli("retrieval-audit", "--release-id", "retrieval-test").returncode, 0)
        import shutil
        shutil.rmtree(release / "检索版")
        shutil.rmtree(release / "检索索引")
        shutil.rmtree(release / "检索清单")
        self.build()
        self.assertEqual(first, manifest_path.read_bytes())

    def test_evaluate_and_audit_tampering(self):
        self.publish()
        release = self.build()
        result = self.fixture.run_cli("retrieval-evaluate", "--release-id", "retrieval-test", "--suite", str(self.suite_path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fixture.run_cli("retrieval-audit", "--release-id", "retrieval-test").returncode, 0)
        markdown = release / "检索评测/retrieval-test.md"
        original_markdown = markdown.read_bytes()
        markdown.write_bytes(original_markdown + b" ")
        self.assertIn("Markdown 报告", self.fixture.run_cli("retrieval-audit", "--release-id", "retrieval-test").stderr)
        markdown.write_bytes(original_markdown)
        manifest = json.loads((release / "检索清单/retrieval-test.json").read_text())
        first = manifest["units"][0]["path"]
        path = self.project / first
        path.write_text(path.read_text() + "\n篡改\n", encoding="utf-8")
        self.assertIn("被增删改", self.fixture.run_cli("retrieval-audit", "--release-id", "retrieval-test").stderr)

    def test_query_reads_only_audited_current_evidence(self):
        self.publish()
        release = self.build()
        query_args = ("retrieval-query", "--query", "订单查询失败时会怎样")
        self.assertNotEqual(self.fixture.run_cli(*query_args).returncode, 0)
        self.assertEqual(self.fixture.run_cli("retrieval-evaluate", "--release-id", "retrieval-test", "--suite", str(self.suite_path)).returncode, 0)
        result = self.fixture.run_cli(*query_args)
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertEqual(response["release_id"], "retrieval-test")
        self.assertEqual(response["answerability"], "not_assessed")
        self.assertEqual(response["audience"], "business")
        self.assertTrue(response["hits"])
        for hit in response["hits"]:
            self.assertEqual(hit["audience"], "business")
            self.assertTrue((self.project / hit["unit_path"]).is_file())
            self.assertTrue(all((self.project / path).is_file() for path in hit["source_paths"]))
            self.assertTrue(all(path.startswith("发布/业务版/") for path in hit["source_paths"]))
        engineering = self.fixture.run_cli("retrieval-query", "--query", "METHOD-001", "--audience", "engineering")
        self.assertEqual(engineering.returncode, 0, engineering.stderr)
        self.assertTrue(any(hit["audience"] == "engineering" for hit in json.loads(engineering.stdout)["hits"]))
        self.assertNotEqual(self.fixture.run_cli(*query_args, "--top-k", "21").returncode, 0)
        unit_path = self.project / response["hits"][0]["unit_path"]
        unit_path.write_text(unit_path.read_text(encoding="utf-8") + "\n改动\n", encoding="utf-8")
        self.assertNotEqual(self.fixture.run_cli(*query_args).returncode, 0)

    def test_audit_rejects_changed_base_or_report(self):
        self.publish()
        release = self.build()
        self.assertEqual(self.fixture.run_cli("retrieval-evaluate", "--release-id", "retrieval-test", "--suite", str(self.suite_path)).returncode, 0)
        report = release / "检索评测/retrieval-test.json"
        original = report.read_bytes()
        report.write_bytes(original + b" ")
        self.assertIn("评测报告", self.fixture.run_cli("retrieval-audit", "--release-id", "retrieval-test").stderr)
        report.write_bytes(original)
        registry = release / "版本清单/retrieval-test.json"
        registry.write_bytes(registry.read_bytes() + b" ")
        self.assertNotEqual(self.fixture.run_cli("retrieval-audit", "--release-id", "retrieval-test").returncode, 0)

    def test_failed_gate_has_no_ready_pointer(self):
        self.publish()
        release = self.build()
        fixtures.write(self.suite_path, json.dumps(suite(required=["不存在的必要条件"]), ensure_ascii=False))
        result = self.fixture.run_cli("retrieval-evaluate", "--release-id", "retrieval-test", "--suite", str(self.suite_path))
        self.assertEqual(result.returncode, 1)
        self.assertFalse((release / "当前检索版本.json").exists())
        self.assertNotEqual(self.fixture.run_cli("retrieval-audit", "--release-id", "retrieval-test").returncode, 0)

    def test_external_audience_leakage_and_wrong_corpus(self):
        self.publish()
        release = self.build()
        manifest = json.loads((release / "检索清单/retrieval-test.json").read_text())
        business = next(item["unit_id"] for item in manifest["units"] if item["audience"] == "business")
        engineering = next(item["unit_id"] for item in manifest["units"] if item["audience"] == "engineering")
        external = {
            "schema_version": "0.1", "suite_id": "public-test", "retriever_id": "outside-test",
            "corpus_sha256": digest(json_bytes(manifest["views"])),
            "cases": {"order-explanation": [{"unit_id": engineering, "score": 9.0}, {"unit_id": business, "score": 8.0}]},
        }
        path = self.project / "results.json"
        fixtures.write(path, json.dumps(external, ensure_ascii=False))
        result = self.fixture.run_cli("retrieval-evaluate", "--release-id", "retrieval-test", "--suite", str(self.suite_path), "--results", str(path))
        self.assertEqual(result.returncode, 1)
        self.assertIn(engineering, json.loads(result.stdout)["cases"][0]["audience_leakage"])
        external["corpus_sha256"] = "0" * 64
        fixtures.write(path, json.dumps(external, ensure_ascii=False))
        result = self.fixture.run_cli("retrieval-evaluate", "--release-id", "retrieval-test", "--suite", str(self.suite_path), "--results", str(path))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("语料摘要", result.stderr)

    def test_publish_extension_is_optional_and_failure_rolls_back(self):
        fixtures.write(self.suite_path, json.dumps(suite(required=["永远不会出现的短语"]), ensure_ascii=False))
        failed = self.fixture.run_cli("publish", "--release-id", "retrieval-test", "--with-retrieval", "--retrieval-suite", str(self.suite_path))
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse((self.project / "发布").exists())
        fixtures.write(self.suite_path, json.dumps(suite(), ensure_ascii=False))
        result = self.fixture.run_cli("publish", "--release-id", "retrieval-test", "--with-retrieval", "--retrieval-suite", str(self.suite_path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fixture.run_cli("audit-release", "--release-id", "retrieval-test").returncode, 0)
        self.assertEqual(self.fixture.run_cli("retrieval-audit", "--release-id", "retrieval-test").returncode, 0)

    def test_failed_second_release_keeps_previous_retrieval_pointer(self):
        first = self.fixture.run_cli("publish", "--release-id", "retrieval-v1", "--with-retrieval", "--retrieval-suite", str(self.suite_path))
        self.assertEqual(first.returncode, 0, first.stderr)
        pointer = (self.project / "发布/当前检索版本.json").read_bytes()
        manifest = (self.project / "发布/检索清单/retrieval-v1.json").read_bytes()
        subprocess.run(["git", "-C", str(self.project), "add", "发布"], check=True)
        subprocess.run(["git", "-C", str(self.project), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "retrieval v1"], check=True)
        fixtures.write(self.suite_path, json.dumps(suite(required=["从未出现的测试词"]), ensure_ascii=False))
        failed = self.fixture.run_cli("publish", "--release-id", "retrieval-v2", "--with-retrieval", "--retrieval-suite", str(self.suite_path))
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual((self.project / "发布/当前检索版本.json").read_bytes(), pointer)
        self.assertEqual((self.project / "发布/检索清单/retrieval-v1.json").read_bytes(), manifest)
        self.assertEqual(self.fixture.run_cli("retrieval-audit", "--release-id", "retrieval-v1").returncode, 0)

    def test_compact_project_uses_existing_document_types(self):
        fixtures.write(self.project / "Code2KB工程配置.json", json.dumps({"schema_version": "0.1", "content_profile": "compact"}))
        (self.fixture.module / "功能与范围.md").unlink()
        fixtures.write(self.fixture.module / "规则与限制.md", fixtures.doc("rules", "订单查询：规则与限制", reviewed=True))
        fixtures.write(self.fixture.module / "常见问答.md", fixtures.doc("faq", "订单查询：常见问答", reviewed=True))
        implementation = self.fixture.module / "技术实现.md"
        fixtures.write(implementation, implementation.read_text() + "\n## 方法定位\n\nMETHOD-001 处理查询。\n")
        source, config = core.read_config(self.project.resolve())
        docs, outline = core.read_documents(source)
        core.validate_project(docs, outline, config, core.registered_adapter_entries(config))
        self.assertEqual(config["_content_profile"], "compact")

    def test_public_fixture_checks_unknown_and_audience(self):
        root = Path(__file__).resolve().parents[2] / "conformance/retrieval"
        check = load_suite(root / "suites/minimal-business.json")
        units = {}
        corpus_data = json.loads((root / "corpus.json").read_text(encoding="utf-8"))
        for path in sorted((root / "units").glob("*.md")):
            meta, body = read_unit(path)
            self.assertEqual(corpus_data["views"][meta["audience"]]["files"][path.name], digest(path.read_bytes()))
            units[meta["unit_id"]] = {"meta": meta, "body": body}
        self.assertEqual(len(units), sum(len(view["files"]) for view in corpus_data["views"].values()))
        corpus = digest(json_bytes(corpus_data["views"]))
        report = evaluate_data(check, units, None, corpus)
        self.assertEqual(report["gate_status"], "passed")
        self.assertEqual(report["summary"]["audience_leakage"], 0)
        external = json.loads((root / "external-results/minimal-business.json").read_text(encoding="utf-8"))
        self.assertEqual(evaluate_data(check, units, external, corpus)["gate_status"], "passed")
        check["cases"][0]["required_unknown_phrases"] = ["线上已确认"]
        report = evaluate_data(check, units, None, corpus)
        self.assertEqual(report["gate_status"], "failed")

    def test_independent_public_sample_development_baseline(self):
        root = Path(__file__).resolve().parents[2] / "conformance/retrieval/starlette"
        corpus = json.loads((root / "corpus.json").read_text(encoding="utf-8"))
        self.assertEqual(corpus["source_commit"], "61123a5c76ebb9d5786758008945c4fbbb380bf6")
        units = {}
        for path in sorted((root / "units").glob("*.md")):
            meta, body = read_unit(path)
            self.assertEqual(corpus["views"]["business"]["files"][path.name], digest(path.read_bytes()))
            self.assertEqual(meta["release_id"], "starlette-61123a5")
            units[meta["unit_id"]] = {"meta": meta, "body": body}
        self.assertEqual(len(units), 5)
        check = load_suite(root / "suites/development.json")
        report = evaluate_data(check, units, None, digest(json_bytes(corpus["views"])))
        self.assertEqual(report["summary"]["passed"], 3)
        boundary = next(row for row in report["cases"] if row["case_id"] == "unknown-account-lock")
        self.assertTrue(boundary["passed"])
        self.assertIn("ru.business.starlette.authentication.errors.response", boundary["hits"])
        self.assertFalse(boundary["missing_unknown_phrases"])

    def test_bad_suite_and_unit_metadata_are_rejected(self):
        invalid = suite()
        invalid["cases"].append(invalid["cases"][0])
        fixtures.write(self.suite_path, json.dumps(invalid, ensure_ascii=False))
        with self.assertRaises(RetrievalError):
            load_suite(self.suite_path)
        root = Path(__file__).resolve().parents[2] / "conformance/retrieval/units/business-order.md"
        text = root.read_text(encoding="utf-8").replace("audience: business", "audience: business\naudience: engineering")
        path = self.project / "bad-unit.md"
        fixtures.write(path, text)
        with self.assertRaises(RetrievalError):
            read_unit(path)
        fixtures.write(path, root.read_text(encoding="utf-8").replace("source_documents: 订单/订单查询/常见问答.md", "source_documents: ../secret.md"))
        with self.assertRaises(RetrievalError):
            read_unit(path)
        fixtures.write(path, root.read_text(encoding="utf-8").replace("source_documents: 订单/订单查询/常见问答.md", "source_documents: ."))
        with self.assertRaises(RetrievalError):
            read_unit(path)

    def test_compact_comparison_detects_missing_topic_or_unknown(self):
        root = Path(__file__).resolve().parents[2] / "conformance/retrieval/units/business-order.md"
        meta, body = read_unit(root)
        full = {meta["unit_id"]: {"meta": meta, "body": body}}
        self.assertFalse(compare(full, {})["passed"])
        compact = {meta["unit_id"]: {"meta": meta, "body": body.replace("线上是否有延迟仍不能确定。", "")}}
        self.assertEqual(len(compare(full, compact)["missing_unknown_boundaries"]), 1)
        self.assertTrue(compare(full, full)["passed"])

    def test_auto_metadata_stays_bound_to_source_text(self):
        source, _ = core.read_config(self.project.resolve())
        docs, _ = core.read_documents(source)
        selected = [doc for doc in docs if doc.module_id == "example.order.query"]
        result = metadata_candidates(selected)
        self.assertIn("订单查询", result["business_topics"])
        self.assertEqual(result["business_unknowns"], "")

    def test_generated_units_keep_conditions_unknown_and_readable_topic(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release = root / "发布"
            business = release / "业务版/订单/订单查询"
            business.mkdir(parents=True)
            flow = business / "业务流程.md"
            flow.write_text(
                "---\nmodule_id: example.order.query\n---\n\n"
                "# 订单查询：业务流程\n\n## 适用条件\n\n仅限已登录用户。\n\n"
                "## 主流程\n\n[见条件](#适用条件) 返回当前用户的订单。\n\n"
                "## 回答边界\n\n跨租户结果未验证。\n", encoding="utf-8")
            overview = business / "模块概览.md"
            overview.write_text(
                "---\nmodule_id: example.order.query\n---\n\n"
                "# 订单查询：模块概览\n\n## 说明\n\n用户可查看订单。\n\n## 重复回答\n\n用户可查看订单。\n", encoding="utf-8")
            registry = {
                "release_id": "index-context", "views": {
                    "business": {"path": "发布/业务版", "files": {
                        "订单/订单查询/业务流程.md": digest(flow.read_bytes()),
                        "订单/订单查询/模块概览.md": digest(overview.read_bytes()),
                    }},
                    "engineering": {"path": "发布/研发版", "files": {}},
                },
                "created_at": "2026-10-25T00:00:00Z",
            }
            manifest = release / "版本清单/index-context.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_bytes(json_bytes(registry))
            (release / "研发版").mkdir()
            (release / "当前版本.json").write_bytes(json_bytes({
                "release_id": "index-context", "registry_path": "发布/版本清单/index-context.json",
                "registry_sha256": digest(manifest.read_bytes()),
            }))
            built = build_in_release(release, "index-context", "full", {"name": "test", "version": "0.8"})
            units = {}
            for entry in built["units"]:
                meta, body = read_unit(root / entry["path"])
                units[meta["topic"]] = (meta, body)
            flow_meta, flow_body = units["订单查询：业务流程"]
            self.assertIn("仅限已登录用户", flow_body)
            self.assertIn("返回当前用户的订单", flow_body)
            self.assertIn("跨租户结果未验证", flow_body)
            self.assertIn("适用条件", flow_meta["source_headings"])
            self.assertIn("回答边界", flow_meta["source_headings"])
            self.assertIn("业务版/订单/订单查询/业务流程.md#适用条件", flow_body)
            self.assertIn("订单查询 · 说明", units)
            self.assertIn("重复回答", units["订单查询 · 说明"][0]["source_headings"])
            self.assertIn("模块：订单查询", units["订单查询 · 说明"][1])
            report = coverage_report(registry, built, release)
            self.assertEqual(report["conservative_groups"], [{
                "audience": "business", "source_path": "发布/业务版/订单/订单查询/业务流程.md",
                "shared_headings": ["回答边界", "适用条件"],
                "reason": "whole_source_kept_to_preserve_answer_boundaries", "review_required": True,
            }])

    def test_nested_question_keeps_parent_condition(self):
        sections = index_sections(
            "# 订单查询\n\n## 查询结果\n\n仅限已登录用户。\n\n"
            "### 问：能看到什么？\n\n返回当前用户订单。\n", "常见问答.md")
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0][2], ["查询结果", "问：能看到什么？"])
        self.assertIn("仅限已登录用户", sections[0][1])
        self.assertIn("返回当前用户订单", sections[0][1])

    def test_document_preamble_is_preserved_in_each_answer(self):
        sections = index_sections(
            "# 订单查询\n\n仅限已登录用户；跨租户未验证。\n\n"
            "## 查询\n\n返回当前用户订单。\n\n"
            "## 失败\n\n### 问：无结果时怎么办？\n\n显示空列表。\n", "常见问答.md")
        self.assertEqual(len(sections), 2)
        for _, content, _ in sections:
            self.assertIn("仅限已登录用户；跨租户未验证", content)

    def test_coverage_reports_glossary_without_claiming_indexed(self):
        registry = {"release_id": "sample", "views": {
            "business": {"files": {"术语表.md": "x", "目录.md": "x", "订单/模块概览.md": "x"}},
            "engineering": {"files": {}},
        }}
        retrieval = {"release_id": "sample", "units": [{
            "audience": "business", "source_documents": ["订单/模块概览.md"],
        }]}
        report = coverage_report(registry, retrieval)
        self.assertFalse(report["coverage_is_complete"])
        self.assertEqual(report["omissions"], [
            {"audience": "business", "source_path": "发布/业务版/术语表.md", "reason": "glossary_not_in_retrieval_extension"},
            {"audience": "business", "source_path": "发布/业务版/目录.md", "reason": "navigation_only"},
        ])
        self.publish()
        self.build()
        output = self.fixture.run_cli("retrieval-coverage", "--release-id", "retrieval-test")
        self.assertEqual(output.returncode, 0, output.stderr)
        self.assertEqual(json.loads(output.stdout)["release_id"], "retrieval-test")


if __name__ == "__main__":
    unittest.main()
