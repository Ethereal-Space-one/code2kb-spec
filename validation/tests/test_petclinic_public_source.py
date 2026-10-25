"""Offline public mixed-language source → reviewed knowledge → retrieval test."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import unittest

import test_knowledge as fixture
from validation.adapters.platform import scan


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

        revisions = {}
        for role in ("frontend", "backend"):
            repo = self.root / f"petclinic-{role}"
            shutil.copytree(PUBLIC / role, repo)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=Public Fixture", "-c", "user.email=public@example.invalid", "commit", "-q", "-m", "preserve public source files"], check=True)
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
            f"| FACT-001 | 按姓氏查询主人；无结果时后端返回未找到 | CODE_VERIFIED | {front_anchor}, {api_anchor}, {java_anchor} | 模块概览.md、功能与范围.md |",
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
        self.assertIn(f"{front_anchor}, {api_anchor}, {java_anchor} | 模块概览.md、功能与范围.md", spec)
        fixture.write(spec_path, spec)

        for name, addition in {
            "模块概览.md": "用户可查看主人列表；传入姓氏时按姓氏筛选。无结果时查询返回未找到；线上页面表现未运行验证。",
            "功能与范围.md": "本样本覆盖主人列表及姓氏筛选；服务端无结果时返回未找到。实际权限、代理和部署配对尚未验证。",
            "技术实现.md": f"手工核对 `{front_anchor}` 构造请求地址，`{api_anchor}` 定义接口，`{java_anchor}` 进入方法；不把 Adapter 文件候选当作已验证调用边。",
            "接口与调用.md": f"手工核对接口三处出处：`{front_anchor}`、`{api_anchor}`、`{java_anchor}`。OpenAPI 与运行部署配对未验证。",
            "方法与源码.md": f"`{java_anchor}` 的 listOwners 在姓氏非空时按姓氏查询，否则查全部；空结果返回 NOT_FOUND。",
        }.items():
            path = self.module / name
            fixture.write(path, path.read_text(encoding="utf-8") + "\n" + addition + "\n")

        fixture.finalize_fixture(self.project, "example.owner.search")
        self.assertEqual(self.run_cli("check").returncode, 0)
        published = self.run_cli("publish", "--release-id", "petclinic-public-v1")
        self.assertEqual(published.returncode, 0, published.stderr)
        self.assertEqual(self.run_cli("audit-release").returncode, 0)
        built = self.run_cli("retrieval-build", "--release-id", "petclinic-public-v1")
        self.assertEqual(built.returncode, 0, built.stderr)
        release = self.project / "发布"
        business = (release / "业务版/公开样本/主人查询/模块概览.md").read_text(encoding="utf-8")
        engineering = (release / "研发版/公开样本/主人查询/方法与源码.md").read_text(encoding="utf-8")
        self.assertIn("传入姓氏时按姓氏筛选", business)
        self.assertIn("线上页面表现未运行验证", business)
        self.assertIn(java_anchor, engineering)
        units = list((release / "检索版/业务").rglob("*.md"))
        self.assertTrue(any("按姓氏筛选" in item.read_text(encoding="utf-8") for item in units))


if __name__ == "__main__":
    unittest.main()
