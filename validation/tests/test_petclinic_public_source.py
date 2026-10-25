"""Offline public mixed-language source → reviewed knowledge → retrieval test."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

import test_knowledge as fixture
from validation.adapters.platform import scan
from validation.external_fts5 import probe
from validation.evidence_snapshot import snapshot
from validation.retrieval_evaluate import lexical, load_units


PUBLIC = Path(__file__).resolve().parents[2] / "conformance/public-source/petclinic"
OWNER_JAVA = "src/main/java/org/springframework/samples/petclinic/rest/controller/v1/OwnerRestControllerV1.java"
OWNER_TS = "src/app/owners/owner.service.ts"
OPENAPI = "src/main/resources/openapi.yml"
EXPECTED = {
    f"frontend/{OWNER_TS}": "acf97110c1bbd2bdfae43915bef702464bb5a56e4b0e9e5d5a2a3a75cb93fe49",
    "frontend/src/environments/environment.ts": "f607900559602acd8d56f1458cb61372b2b7d6dc22945d58f2bc267cc56a0573",
    f"backend/{OPENAPI}": "a1a8ee2f853ebd8af89cd5a958158ac16550b5627da1cf59dca9736e95a597f4",
    f"backend/{OWNER_JAVA}": "19291723b9b2f6545595f098116cbf3fd5ee5676aa55ae20f8079b51b5b2d883",
}


class PetclinicPublicSourceTests(unittest.TestCase):
    setUp = fixture.KnowledgeTests.setUp
    run_cli = fixture.KnowledgeTests.run_cli

    def test_manual_bridge_from_independent_source_to_retrieval(self) -> None:
        for relative, digest in EXPECTED.items():
            self.assertEqual(hashlib.sha256((PUBLIC / relative).read_bytes()).hexdigest(), digest)

        fixed_git_environment = {**os.environ, "GIT_AUTHOR_DATE": "2026-10-25T00:00:00+00:00",
                                 "GIT_COMMITTER_DATE": "2026-10-25T00:00:00+00:00"}
        revisions = {}
        for role in ("frontend", "backend"):
            repo = self.root / f"petclinic-{role}"
            shutil.copytree(PUBLIC / role, repo)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=Public Fixture", "-c", "user.email=public@example.invalid", "commit", "-q", "-m", "preserve public source files"], check=True, env=fixed_git_environment)
            revisions[role] = {"path": str(repo), "commit": subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()}

        config_path = self.project / "知识库配置.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["repositories"] = revisions
        config.pop("inventory_adapter")
        config["coverage_terms"] = ["前端调用", "后端入口"]
        fixture.write(config_path, json.dumps(config, ensure_ascii=False))

        frontend_candidates = scan("frontend", revisions["frontend"])["candidates"]
        backend_candidates = scan("backend", revisions["backend"])["candidates"]
        self.assertTrue(any(item["source_path"] == OWNER_TS and item["kind"] == "source_file" for item in frontend_candidates))
        self.assertTrue(any(item["source_path"] == OPENAPI and item["kind"] == "source_file" for item in backend_candidates))
        self.assertTrue(any(item["source_path"] == OWNER_JAVA and item["kind"] == "java_method" and item["expression"] == "listOwners" for item in backend_candidates))
        self.assertFalse(any(item["kind"] == "typescript_path" and item["expression"] == "/api/owners" for item in frontend_candidates))

        front_anchor = f"frontend:{OWNER_TS}:36"
        java_anchor = f"backend:{OWNER_JAVA}:78"
        api_anchor = f"backend:{OPENAPI}:65"
        for path in self.source.rglob("*.md"):
            body = path.read_text(encoding="utf-8")
            for role in ("frontend", "backend"):
                body = body.replace(self.repos[role]["commit"], revisions[role]["commit"])
            body = body.replace("example.order.query", "example.owner.search")
            body = body.replace("订单查询", "主人查询")
            body = body.replace("订单", "主人")
            body = body.replace("POST /orders/query", "GET /owners")
            body = body.replace("OrderHandler#query()", "OwnerRestControllerV1#listOwners()")
            body = body.replace("example request", "OwnerService")
            body = body.replace("frontend:dummy.txt:1", front_anchor)
            body = body.replace("backend:dummy.txt:1", java_anchor)
            fixture.write(path, body)
        outline = self.source / "功能大纲.md"
        body = outline.read_text(encoding="utf-8")
        body = "\n".join(line for line in body.split("\n") if not any(marker in line for marker in ("app.sales.order", "ENT-002", "ENT-003")))
        body = body.replace("| 主人 | 主人查询 | 详情查询按钮 |", "| 公开样本 | 主人查询 | 主人查询请求 |")
        body = body.replace("| 按钮 | 详情查询 |", "| 其他 | 查询主人 |")
        body = body.replace("页面与导航、按钮、非按钮动作、前端调用和后端入口均已逐项查看；动态配置仍待核查。", "只核对主人查询一条前端调用及后端入口；其余功能不在样本范围。")
        fixture.write(outline, body)

        old_module = self.module
        self.module = self.source / "公开样本/主人查询"
        self.module.parent.mkdir(parents=True, exist_ok=True)
        old_module.rename(self.module)
        old_module.parent.rmdir()
        spec_path = self.module / "结构化规格.md"
        spec = spec_path.read_text(encoding="utf-8")
        spec = spec.replace("用户可提交查询", "按姓氏查询主人；无结果时后端返回未找到")
        spec = spec.replace(
            f"| FACT-001 | 按姓氏查询主人；无结果时后端返回未找到 | CODE_VERIFIED | {front_anchor} | 功能与范围.md |",
            f"| FACT-001 | 按姓氏查询主人；无结果时后端返回未找到 | CODE_VERIFIED | {front_anchor}, {api_anchor}, {java_anchor} | 模块概览.md、功能与范围.md、方法与源码.md |",
        )
        spec = spec.replace("POST /orders/query", "GET /owners")
        spec = spec.replace("example request", "OwnerService")
        spec = spec.replace("OrderHandler#query()", "OwnerRestControllerV1#listOwners()")
        spec = spec.replace("handler | METHOD-001", "OwnerRestControllerV1#listOwners | METHOD-001")
        spec = spec.replace("点击详情查询", "调用 getOwners 或 searchOwners")
        spec = spec.replace("查询订单", "查询主人")
        spec = spec.replace("订单标识", "主人列表")
        spec = spec.replace("如何查询？", "怎样按姓氏查找主人？")
        spec = spec.replace("查询失败？", "没有匹配结果时怎样？")
        spec = spec.replace("线上一定可用？", "线上一定按此返回吗？")
        spec = spec.replace("给我接口？", "能提供线上账号凭据吗？")
        self.assertIn(f"{front_anchor}, {api_anchor}, {java_anchor} | 模块概览.md、功能与范围.md、方法与源码.md", spec)
        fixture.write(spec_path, spec)

        for name, addition in {
            "模块概览.md": "具有主人管理权限的用户可查看主人列表；传入姓氏时按姓氏筛选，空白姓氏进入按姓氏查询分支。无结果时查询返回未找到；线上页面表现未运行验证。\n\n## 样本范围外的操作\n\n本样本没有取证新增主人、修改主人或删除主人的业务结果。\n\n## 部署状态\n\n线上代理、权限配置和实际可用性没有运行验证。",
            "功能与范围.md": "本样本覆盖主人列表及姓氏筛选；服务端无结果时返回未找到。实际权限、代理和部署配对尚未验证。",
            "技术实现.md": f"手工核对 `{front_anchor}` 构造请求地址，`{api_anchor}` 定义接口，`{java_anchor}` 进入方法；不把 Adapter 文件候选当作已验证调用边。",
            "接口与调用.md": f"手工核对接口三处出处：`{front_anchor}`、`{api_anchor}`、`{java_anchor}`。OpenAPI 与运行部署配对未验证。",
            "方法与源码.md": f"`{java_anchor}` 的 listOwners 在姓氏非 null 时按姓氏查询，否则查全部；空结果返回 NOT_FOUND。",
        }.items():
            path = self.module / name
            fixture.write(path, path.read_text(encoding="utf-8") + "\n" + addition + "\n")

        record = snapshot(f"backend:{OWNER_JAVA}:74-87", revisions)
        relation = {
            "schema_version": "0.1", "module_id": "example.owner.search", "nodes": [], "identity_history": [],
            "topics": [{"topic_id": "topic.owner.search", "audience": "business",
                        "source_document": "模块概览.md", "source_heading": "说明"}],
            "links": [
                {"from_type": "method", "from_id": "METHOD-001", "to_type": "fact", "to_id": "FACT-001",
                 "status": "verified", "evidence": [record], "reviewed_by": "Public fixture reviewer", "reviewed_at": "2026-10-25"},
                {"from_type": "fact", "from_id": "FACT-001", "to_type": "topic", "to_id": "topic.owner.search",
                 "status": "verified", "evidence": [record], "reviewed_by": "Public fixture reviewer", "reviewed_at": "2026-10-25"},
            ],
        }
        relation_path = self.module / "关系映射.json"
        fixture.write(relation_path, json.dumps(relation, ensure_ascii=False))
        suite_path = self.root / "public-retrieval-suite.json"
        suite = {"schema_version": "0.1", "suite_id": "petclinic-public", "audience": "business", "cases": [{
            "case_id": "owner-query", "query": "姓氏筛选", "expected_module_ids": ["example.owner.search"],
            "expected_unit_ids": [], "required_phrases": ["主人管理权限", "按姓氏筛选", "无结果"],
            "required_unknown_phrases": ["未运行验证"], "forbidden_phrases": ["METHOD-001", OWNER_JAVA], "top_k": 1,
        }]}
        fixture.write(suite_path, json.dumps(suite, ensure_ascii=False))
        fixture.finalize_fixture(self.project, "example.owner.search")
        self.assertEqual(self.run_cli("check").returncode, 0)
        published = self.run_cli("publish", "--release-id", "petclinic-public-v1", "--with-retrieval", "--retrieval-suite", str(suite_path))
        self.assertEqual(published.returncode, 0, published.stderr)
        self.assertEqual(self.run_cli("audit-release").returncode, 0)
        release = self.project / "发布"
        business = (release / "业务版/公开样本/主人查询/模块概览.md").read_text(encoding="utf-8")
        engineering = (release / "研发版/公开样本/主人查询/方法与源码.md").read_text(encoding="utf-8")
        self.assertIn("传入姓氏时按姓氏筛选", business)
        self.assertIn("线上页面表现未运行验证", business)
        self.assertIn(java_anchor, engineering)
        units = list((release / "检索版/业务").rglob("*.md"))
        self.assertTrue(any("按姓氏筛选" in item.read_text(encoding="utf-8") for item in units))
        queries = ["姓氏筛选", "空白姓氏", "zzunrelatedzz"]
        fts = probe(self.project, "petclinic-public-v1", "business", queries, top_k=1)
        self.assertEqual(fts["engine"], "SQLite FTS5")
        self.assertEqual(fts["unit_count"], 3)
        self.assertTrue(fts["queries"][0]["ranking"])
        from validation.retrieval_model import read_unit
        manifest = json.loads((release / "检索清单/petclinic-public-v1.json").read_text(encoding="utf-8"))
        by_id = {item["unit_id"]: item for item in manifest["units"]}
        ranked = [read_unit(self.project / by_id[item["unit_id"]]["path"])[1]
                  for item in fts["queries"][0]["ranking"]]
        self.assertTrue(all(term in ranked[0] for term in ("主人管理权限", "按姓氏筛选", "无结果", "未运行验证")))
        self.assertEqual(len(by_id[fts["queries"][0]["ranking"][0]["unit_id"]]["source_documents"]), 2)

        # The second commit is a controlled public-sample change, not an
        # upstream PetClinic revision. A blank surname now takes the all-owner branch.
        backend_repo = Path(revisions["backend"]["path"])
        java_file = backend_repo / OWNER_JAVA
        old_java = java_file.read_text(encoding="utf-8")
        self.assertIn("if (lastName != null) {", old_java)
        java_file.write_text(old_java.replace("if (lastName != null) {",
                                              "if (lastName != null && !lastName.isBlank()) {", 1), encoding="utf-8")
        subprocess.run(["git", "-C", str(backend_repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(backend_repo), "-c", "user.name=Public Fixture", "-c", "user.email=public@example.invalid", "commit", "-q", "-m", "controlled blank-surname branch change"], check=True, env=fixed_git_environment)
        next_commit = subprocess.check_output(["git", "-C", str(backend_repo), "rev-parse", "HEAD"], text=True).strip()
        source_unit = fts["queries"][0]["ranking"][0]["unit_id"]
        before_files = {path.relative_to(self.project).as_posix(): path.read_bytes()
                        for path in self.project.rglob("*") if path.is_file() and ".git" not in path.relative_to(self.project).parts}
        before_status = subprocess.check_output(["git", "-C", str(self.project), "status", "--porcelain"])
        previewed = self.run_cli("preview-upgrade", "--all-modules", "--repository-id", "backend", "--new-commit", next_commit)
        self.assertEqual(previewed.returncode, 0, previewed.stderr)
        preview = json.loads(previewed.stdout)
        self.assertEqual(preview["must_review_facts"], [{"fact_id": "example.owner.search#FACT-001",
                                                      "documents": sorted(["模块概览.md", "功能与范围.md", "方法与源码.md"])}])
        self.assertEqual(preview["published_unit_ids"], [source_unit])
        self.assertEqual(preview["unattributed_paths"], [])
        self.assertEqual(preview["fallback"], "module_review")
        self.assertEqual(before_files, {path.relative_to(self.project).as_posix(): path.read_bytes()
                                      for path in self.project.rglob("*") if path.is_file() and ".git" not in path.relative_to(self.project).parts})
        self.assertEqual(before_status, subprocess.check_output(["git", "-C", str(self.project), "status", "--porcelain"]))
        first_lexical = {query: lexical(query, [unit for unit in load_units(release, manifest).values()
                                              if unit["meta"]["audience"] == "business"], 1) for query in queries}
        self.assertEqual(first_lexical["姓氏筛选"], [source_unit])
        self.assertEqual(first_lexical["zzunrelatedzz"], [])
        self.assertEqual(fts["queries"][2]["ranking"], [])
        self.assertEqual(self.run_cli("retrieval-audit", "--release-id", "petclinic-public-v1").returncode, 0)
        old_commit = revisions["backend"]["commit"]
        config["repositories"]["backend"]["commit"] = next_commit
        fixture.write(config_path, json.dumps(config, ensure_ascii=False))
        for path in self.source.rglob("*.md"):
            fixture.write(path, path.read_text(encoding="utf-8").replace(old_commit, next_commit))
        overview_path = self.module / "模块概览.md"
        fixture.write(overview_path, overview_path.read_text(encoding="utf-8").replace(
            "空白姓氏进入按姓氏查询分支", "空白姓氏进入查询全部主人的分支"))
        spec_path = self.module / "结构化规格.md"
        fixture.write(spec_path, spec_path.read_text(encoding="utf-8").replace(
            "按姓氏查询主人；无结果时后端返回未找到", "非空白姓氏按姓氏查询；空白姓氏查询全部主人；无结果时后端返回未找到"))
        methods_path = self.module / "方法与源码.md"
        fixture.write(methods_path, methods_path.read_text(encoding="utf-8").replace(
            "在姓氏非 null 时按姓氏查询，否则查全部", "在姓氏非 null 且非空白时按姓氏查询，否则查全部"))
        for link in relation["links"]:
            link["evidence"] = [snapshot(f"backend:{OWNER_JAVA}:74-87", config["repositories"])]
        fixture.write(relation_path, json.dumps(relation, ensure_ascii=False))
        suite["cases"][0]["required_phrases"].append("空白姓氏进入查询全部主人的分支")
        suite["cases"][0]["forbidden_phrases"].append("空白姓氏进入按姓氏查询分支")
        fixture.write(suite_path, json.dumps(suite, ensure_ascii=False))
        fixture.finalize_fixture(self.project, "example.owner.search")
        self.assertEqual(self.run_cli("check").returncode, 0)
        second = self.run_cli("publish", "--release-id", "petclinic-public-v2", "--with-retrieval", "--retrieval-suite", str(suite_path))
        self.assertEqual(second.returncode, 0, second.stderr)
        second_manifest = json.loads((release / "检索清单/petclinic-public-v2.json").read_text(encoding="utf-8"))
        second_overview = [self.project / item["path"] for item in second_manifest["units"]
                           if item["audience"] == "business" and "模块概览.md" in item["source_documents"][0]]
        self.assertTrue(second_overview)
        updated = "\n".join(path.read_text(encoding="utf-8") for path in second_overview)
        self.assertIn("空白姓氏进入查询全部主人的分支", updated)
        self.assertNotIn("空白姓氏进入按姓氏查询分支", updated)
        next_fts = probe(self.project, "petclinic-public-v2", "business", queries, top_k=1)
        self.assertTrue(next_fts["queries"][0]["ranking"])
        updated_unit = next(item for item in second_manifest["units"]
                            if item["unit_id"] == next_fts["queries"][0]["ranking"][0]["unit_id"])
        updated_hit = (self.project / updated_unit["path"]).read_text(encoding="utf-8")
        self.assertIn("空白姓氏进入查询全部主人的分支", updated_hit)
        self.assertNotIn("空白姓氏进入按姓氏查询分支", updated_hit)
        second_lexical = {query: lexical(query, [unit for unit in load_units(release, second_manifest).values()
                                               if unit["meta"]["audience"] == "business"], 1) for query in queries}
        self.assertEqual(second_lexical["空白姓氏"], [updated_unit["unit_id"]])
        self.assertEqual(second_lexical["zzunrelatedzz"], [])
        self.assertEqual(next_fts["queries"][2]["ranking"], [])
        self.assertEqual(self.run_cli("audit-release").returncode, 0)
        self.assertEqual(self.run_cli("retrieval-audit", "--release-id", "petclinic-public-v2").returncode, 0)
        if destination := os.environ.get("CODE2KB_RECORD_PUBLIC_FTS"):
            Path(destination).write_text(json.dumps({
                "source": "spring-petclinic-rest public fixture plus controlled second commit",
                "upstream_file_sha256": EXPECTED[f"backend/{OWNER_JAVA}"],
                "second_change": "blank surname enters all-owner branch",
                "fixed_source_commits": {"frontend": revisions["frontend"]["commit"], "backend_first": old_commit, "backend_second": next_commit},
                "lexical_baseline": {"retriever_id": "lexical-v1", "top_k": 1,
                                     "fields": {"module_id": 6, "topic": 5, "question_variants": 4, "body": 1},
                                     "tokenizer": "casefolded ASCII words and Chinese characters/bigrams",
                                     "first": first_lexical, "second": second_lexical},
                "first": fts, "second": next_fts,
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
