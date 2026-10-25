"""One public mixed-language route, reviewed knowledge and retrieval source."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest

import test_knowledge as fixture


class MixedLanguageKnowledgeFlowTests(unittest.TestCase):
    setUp = fixture.KnowledgeTests.setUp
    run_cli = fixture.KnowledgeTests.run_cli

    def test_candidate_is_not_fact_until_reviewed_knowledge_is_published(self) -> None:
        repo = Path(self.repos["frontend"]["path"])
        fixture.write(repo / "api.ts", "const request = { url: '/orders/status' };\n")
        fixture.write(repo / "Order.java", "class Order {\n@GetMapping(\"/orders/status\") public String status(boolean paid) { return paid ? \"ready\" : \"unavailable\"; }\n}\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-q", "-m", "public mixed source"], check=True)
        old_revision = self.repos["frontend"]["commit"]
        new_revision = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        config_path = self.project / "知识库配置.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["repositories"]["frontend"]["commit"] = new_revision
        fixture.write(config_path, json.dumps(config, ensure_ascii=False))
        for path in self.source.rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            text = text.replace(old_revision, new_revision)
            text = text.replace("frontend:dummy.txt:1", "frontend:api.ts:1")
            text = text.replace("backend:dummy.txt:1", "frontend:Order.java:2")
            if path.name == "结构化规格.md":
                text = text.replace("用户可提交查询 | CODE_VERIFIED | frontend:api.ts:1", "已支付订单返回 ready，未支付订单返回 unavailable | CODE_VERIFIED | frontend:Order.java:2")
            if path.name in {"模块概览.md", "功能与范围.md"}:
                text += "\n已付款的订单显示可用，未付款的订单显示不可用；线上结果和实际权限未验证。\n"
            fixture.write(path, text)
        candidate = self.run_cli("analyze-candidates", "--repository-id", "frontend", "--candidate-schema", "0.2")
        self.assertEqual(candidate.returncode, 0, candidate.stderr)
        report = json.loads(candidate.stdout)
        self.assertEqual(len(report["edges"]), 1)
        self.assertEqual(report["edges"][0]["status"], "candidate")
        fixture.finalize_fixture(self.project, "example.order.query")
        checked = self.run_cli("check")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        published = self.run_cli("publish", "--release-id", "mixed-v1")
        self.assertEqual(published.returncode, 0, published.stderr)
        self.assertEqual(self.run_cli("audit-release").returncode, 0)
        business = (self.project / "发布/业务版/订单/订单查询/模块概览.md").read_text(encoding="utf-8")
        engineering = (self.project / "发布/研发版/订单/订单查询/方法与源码.md").read_text(encoding="utf-8")
        self.assertIn("已付款的订单显示可用", business)
        self.assertIn("线上结果和实际权限未验证", business)
        self.assertIn("Order.java:2", engineering)
        built = self.run_cli("retrieval-build", "--release-id", "mixed-v1")
        self.assertEqual(built.returncode, 0, built.stderr)
        units = list((self.project / "发布/检索版/业务").rglob("*.md"))
        self.assertTrue(units)
        self.assertTrue(any("已付款的订单显示可用" in path.read_text(encoding="utf-8") for path in units))


if __name__ == "__main__":
    unittest.main()
