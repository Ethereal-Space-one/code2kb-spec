from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import test_knowledge as fixture


core = fixture.core


class ProtocolMigrationTests(unittest.TestCase):
    setUp = fixture.KnowledgeTests.setUp
    run_cli = fixture.KnowledgeTests.run_cli
    enable_business_intent = fixture.KnowledgeTests.enable_business_intent

    def legacy_config(self) -> None:
        path = self.project / "知识库配置.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        config["standard_version"] = core.LEGACY_STANDARD_VERSION
        fixture.write(path, json.dumps(config, ensure_ascii=False))

    def commit(self, message: str) -> None:
        subprocess.run(["git", "-C", str(self.project), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.project), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-q", "-m", message], check=True)

    def test_preview_writes_nothing_and_requires_matching_plan(self) -> None:
        self.legacy_config()
        for path in self.source.rglob("*.md"):
            path.unlink()
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        self.commit("legacy source")
        state_exists_before = (self.project / ".code2kb").exists()
        before = {path.relative_to(self.project).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in self.project.rglob("*") if path.is_file() and ".git" not in path.parts}
        preview = self.run_cli("migrate-protocol", "--to", core.STANDARD_VERSION, "--dry-run")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        plan = json.loads(preview.stdout)["plan_sha256"]
        after_preview = {path.relative_to(self.project).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in self.project.rglob("*") if path.is_file() and ".git" not in path.parts}
        self.assertEqual(before, after_preview)
        self.assertEqual((self.project / ".code2kb").exists(), state_exists_before)
        invalid = self.run_cli("migrate-protocol", "--to", core.STANDARD_VERSION, "--apply", "--plan-sha256", "0" * 64)
        self.assertNotEqual(invalid.returncode, 0)
        self.assertEqual(json.loads((self.project / "知识库配置.json").read_text())["standard_version"], core.LEGACY_STANDARD_VERSION)
        applied = self.run_cli("migrate-protocol", "--to", core.STANDARD_VERSION, "--apply", "--plan-sha256", plan)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(json.loads((self.project / "知识库配置.json").read_text())["standard_version"], core.STANDARD_VERSION)

    def test_stale_preview_and_pending_transaction_block_migration(self) -> None:
        self.legacy_config()
        for path in self.source.rglob("*.md"):
            path.unlink()
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        self.commit("legacy source")
        preview = self.run_cli("migrate-protocol", "--to", core.STANDARD_VERSION, "--dry-run")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        plan = json.loads(preview.stdout)["plan_sha256"]
        changed = self.project / "知识源/迁移后新增.md"
        fixture.write(changed, "# 新增证据\n")
        self.commit("new evidence")
        stale = self.run_cli("migrate-protocol", "--to", core.STANDARD_VERSION, "--apply", "--plan-sha256", plan)
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn("预演已过期", stale.stderr)
        self.assertEqual(json.loads((self.project / "知识库配置.json").read_text())["standard_version"], core.LEGACY_STANDARD_VERSION)
        pending = self.project / ".code2kb/transactions/pending"
        pending.mkdir(parents=True)
        blocked = self.run_cli("migrate-protocol", "--to", core.STANDARD_VERSION, "--dry-run")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("未完成事务", blocked.stderr)
        self.assertEqual(json.loads((self.project / "知识库配置.json").read_text())["standard_version"], core.LEGACY_STANDARD_VERSION)

    def test_active_run_blocks_migration_without_writing(self) -> None:
        self.legacy_config()
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        self.commit("legacy source")
        run = self.project / ".code2kb/runs/example/run.json"
        fixture.write(run, json.dumps({"status": "active", "tasks": [{"status": "pending"}]}))
        before = (self.project / "知识库配置.json").read_bytes()
        result = self.run_cli("migrate-protocol", "--to", core.STANDARD_VERSION, "--dry-run")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("尚未完成", result.stderr)
        self.assertEqual(before, (self.project / "知识库配置.json").read_bytes())
        fixture.write(run, json.dumps({"status": "active", "tasks": []}))
        empty = self.run_cli("migrate-protocol", "--to", core.STANDARD_VERSION, "--dry-run")
        self.assertNotEqual(empty.returncode, 0)
        self.assertIn("尚未完成", empty.stderr)

    def test_legacy_business_intent_gate_stays_enabled(self) -> None:
        self.enable_business_intent()
        self.legacy_config()
        fixture.finalize_fixture(self.project, "example.order.query")
        self.assertEqual(self.run_cli("check").returncode, 0)
        manifest = self.module / "发布清单.md"
        fixture.write(manifest, manifest.read_text(encoding="utf-8").replace("intent_included: true\n", ""))
        invalid = self.run_cli("check")
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn("intent_included", invalid.stderr)

    def test_repository_url_guard_applies_to_both_source_protocols(self) -> None:
        overview = self.module / "模块概览.md"
        fixture.write(overview, overview.read_text(encoding="utf-8") +
                      "\n[参考](https://github.com/example/repo/blob/abc1234/README.md#L3)\n")
        for standard_version in (core.STANDARD_VERSION, core.LEGACY_STANDARD_VERSION):
            with self.subTest(standard_version=standard_version):
                config_path = self.project / "知识库配置.json"
                config = json.loads(config_path.read_text(encoding="utf-8"))
                config["standard_version"] = standard_version
                fixture.write(config_path, json.dumps(config, ensure_ascii=False))
                result = self.run_cli("check")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("业务文件含源码仓库链接", result.stderr)

    def test_legacy_release_then_migrate_then_new_release(self) -> None:
        self.legacy_config()
        fixture.finalize_fixture(self.project, "example.order.query")
        self.assertEqual(self.run_cli("check").returncode, 0)
        first = self.run_cli("publish", "--release-id", "legacy-v1")
        self.assertEqual(first.returncode, 0, first.stderr)
        old_release = self.project / "发布"
        old_files = {path.relative_to(old_release).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in old_release.rglob("*") if path.is_file()}
        self.assertEqual(self.run_cli("audit-release").returncode, 0)
        self.commit("legacy release")
        refresh = self.run_cli("prepare", "--module-id", "example.order.query", "--refresh",
                               "--business-topics", "用户操作", "--business-unknowns", "运行表现", "--business-keywords", "操作",
                               "--engineering-topics", "接口路径和处理方法", "--engineering-unknowns", "部署配对", "--engineering-keywords", "调用链",
                               "--files", "模块概览.md,功能与范围.md")
        self.assertEqual(refresh.returncode, 0, refresh.stderr)
        self.commit("refresh candidates")
        preview = self.run_cli("migrate-protocol", "--to", core.STANDARD_VERSION, "--dry-run")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        report = json.loads(preview.stdout)
        self.assertEqual(report["draft_packages_to_refresh"], ["知识源/订单/订单查询/发布清单.md"])
        plan = report["plan_sha256"]
        migrated = self.run_cli("migrate-protocol", "--to", core.STANDARD_VERSION, "--apply", "--plan-sha256", plan)
        self.assertEqual(migrated.returncode, 0, migrated.stderr)
        self.assertEqual(self.run_cli("audit-release").returncode, 0)
        self.assertEqual(old_files, {path.relative_to(old_release).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                                     for path in old_release.rglob("*") if path.is_file()})
        approved = self.run_cli("approve", "--module-id", "example.order.query", "--reviewed-by", "example-reviewer",
                                "--reviewed-at", "2026-10-25", "--approval-note", "测试授权，仅用于公开夹具")
        self.assertEqual(approved.returncode, 0, approved.stderr)
        self.commit("new protocol inputs")
        second = self.run_cli("publish", "--release-id", "public-v2")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.run_cli("audit-release").returncode, 0)
        pointer = json.loads((old_release / "当前版本.json").read_text())
        self.assertEqual(pointer["standard_version"], core.STANDARD_VERSION)


class FrozenLegacyReleaseTests(unittest.TestCase):
    def test_v060_generated_release_remains_auditable(self) -> None:
        frozen = Path(__file__).resolve().parents[2] / "conformance/legacy-release"
        registry = json.loads((frozen / "发布/版本清单/legacy-v1.json").read_text(encoding="utf-8"))
        self.assertEqual(registry["generated_by"]["version"], "0.6.0")
        self.assertEqual(registry["standard_version"], core.LEGACY_STANDARD_VERSION)
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "frozen"
            shutil.copytree(frozen, project)
            audited = subprocess.run([sys.executable, str(fixture.SCRIPT), "audit-release", "--project-root", str(project)], text=True, capture_output=True)
            self.assertEqual(audited.returncode, 0, audited.stderr)
            target = project / "发布/业务版/订单/订单查询/模块概览.md"
            target.write_text(target.read_text(encoding="utf-8") + "\n额外修改\n", encoding="utf-8")
            broken = subprocess.run([sys.executable, str(fixture.SCRIPT), "audit-release", "--project-root", str(project)], text=True, capture_output=True)
            self.assertNotEqual(broken.returncode, 0)
            self.assertIn("发布目录内容已被修改", broken.stderr)

    def test_unknown_registry_protocol_is_rejected(self) -> None:
        frozen = Path(__file__).resolve().parents[2] / "conformance/legacy-release"
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "frozen"
            shutil.copytree(frozen, project)
            registry = project / "发布/版本清单/legacy-v1.json"
            content = json.loads(registry.read_text(encoding="utf-8"))
            content["standard_version"] = "unknown/9"
            registry.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run([sys.executable, str(fixture.SCRIPT), "audit-release", "--project-root", str(project)], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("版本清单结构或身份无效", result.stderr)


if __name__ == "__main__":
    unittest.main()
