from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

import test_knowledge as fixtures

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import knowledge as core
from retrieval_evaluate import evaluate_data, load_suite
from retrieval_build import metadata_candidates
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


if __name__ == "__main__":
    unittest.main()
