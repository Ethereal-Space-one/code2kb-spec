"""Task-ledger checks that distinguish approval, resume and file boundaries."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from unittest.mock import patch

import test_knowledge as fixture
from validation import workflow
from validation import knowledge


class WorkflowTests(fixture.unittest.TestCase):
    setUp = fixture.KnowledgeTests.setUp
    run_cli = fixture.KnowledgeTests.run_cli

    def create_run(self, run_id="sample-001"):
        result = self.run_cli("run-create", "--run-id", run_id, "--module-id", "example.order.query", "--release-id", "release-001")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def begin(self, task_id):
        result = self.run_cli("run-begin", "--run-id", "sample-001", "--task-id", task_id)
        self.assertEqual(result.returncode, 0, result.stderr)

    def complete(self, task_id, actor="agent", note="已核对项目文件"):
        return self.run_cli("run-complete", "--run-id", "sample-001", "--task-id", task_id, "--actor", actor, "--note", note)

    def test_inventory_and_write_set_block(self):
        created = self.create_run()
        self.assertEqual(created["next_task"]["kind"], "inventory")
        self.begin("inventory")
        self.assertEqual(self.complete("inventory").returncode, 0)
        self.begin("example.order.query:writer")
        unexpected = self.project / "unrelated.md"
        unexpected.write_text("unrelated", encoding="utf-8")
        blocked = self.complete("example.order.query:writer")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("允许范围", blocked.stderr)
        self.assertEqual(unexpected.read_text(encoding="utf-8"), "unrelated")
        status = json.loads(self.run_cli("run-status", "--run-id", "sample-001").stdout)
        self.assertEqual(status["next_task"]["status"], "blocked")
        unexpected.unlink()
        resumed = self.run_cli("run-resume", "--run-id", "sample-001")
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(json.loads(resumed.stdout)["next_task"]["status"], "waiting_review")

    def test_executor_advances_deterministic_inventory(self):
        self.create_run()
        executed = self.run_cli("run-execute", "--run-id", "sample-001", "--task-id", "inventory", "--output", "json")
        self.assertEqual(executed.returncode, 0, executed.stderr)
        envelope = json.loads(executed.stdout)
        self.assertEqual(envelope["status"], "completed")
        self.assertEqual(envelope["result"]["next_task"]["kind"], "writer")

    def test_claude_host_uses_same_task_contract(self):
        self.create_run()
        native = json.loads(self.run_cli("run-next", "--run-id", "sample-001").stdout)["next_task"]
        rendered = self.run_cli("host-next", "--run-id", "sample-001", "--host", "claude-code")
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        host = json.loads(rendered.stdout)
        self.assertEqual(host["task"], native)
        self.assertFalse(host["authorization_boundary"])

    def test_business_intent_task_is_optional(self):
        self.create_run()
        ordinary = workflow.load(self.project, "sample-001")
        self.assertFalse(any(task["kind"] == "business_intent" for task in ordinary["tasks"]))
        created = self.run_cli("run-create", "--run-id", "sample-002", "--module-id", "example.order.query",
                              "--release-id", "release-002", "--business-intent")
        self.assertEqual(created.returncode, 0, created.stderr)
        special = workflow.load(self.project, "sample-002")
        self.assertTrue(any(task["kind"] == "business_intent" for task in special["tasks"]))

    def test_module_directory_cannot_escape_knowledge_source(self):
        with self.assertRaisesRegex(ValueError, "模块目录不安全"):
            workflow.create(self.project, "unsafe-001", {"example.escape": ("..", "outside", "待提取")},
                            ["example.escape"], "release-safe")

    def test_all_modules_reports_unresolved_entries(self):
        result = self.run_cli("run-create", "--run-id", "all-001", "--all-modules", "--batch-size", "1", "--release-id", "release-all")
        self.assertEqual(result.returncode, 0, result.stderr)
        created = json.loads(result.stdout)
        self.assertEqual(created["inventory_summary"]["entries"], 3)
        run = workflow.load(self.project, "all-001")
        self.assertEqual(len(run["modules"]), 2)
        checkpoints = [task for task in run["tasks"] if task["kind"] == "checkpoint"]
        self.assertEqual(len(checkpoints), 2)
        second_writer = [task for task in run["tasks"] if task["kind"] == "writer"][1]
        self.assertEqual(second_writer["depends_on"], [checkpoints[0]["task_id"]])

    def test_runner_holds_project_lock_during_deterministic_command(self):
        self.create_run()
        original = knowledge._main
        attempts = []

        def competing_command():
            second = self.run_cli("confirm-claims", "--module-id", "example.order.query")
            attempts.append(second)
            return original()

        with patch.object(knowledge, "_main", side_effect=competing_command):
            result = workflow.execute(self.project, "sample-001", "inventory")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(attempts), 1)
        self.assertNotEqual(attempts[0].returncode, 0)
        self.assertIn("另一修改任务", attempts[0].stderr)

    def test_json_response_reports_recovery_and_argument_errors(self):
        invalid = self.run_cli("run-create", "--run-id", "bad-001", "--release-id", "release-001", "--output", "json")
        self.assertNotEqual(invalid.returncode, 0)
        self.assertEqual(json.loads(invalid.stdout)["error_code"], "E_ARGUMENT")
        self.create_run()
        journal = self.project / ".code2kb/transactions/governance-test"
        (journal / "before").mkdir(parents=True)
        blocked = self.run_cli("run-begin", "--run-id", "sample-001", "--task-id", "inventory", "--output", "json")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertEqual(json.loads(blocked.stdout)["error_code"], "E_RECOVERY_REQUIRED")

    def test_source_fact_change_reopens_prepared_module(self):
        self.create_run()
        record = workflow.load(self.project, "sample-001")
        for task in record["tasks"]:
            if task["kind"] in {"inventory", "writer", "reviewer", "confirm_claims", "prepare"}:
                task["status"] = "completed"
        spec = self.module / "结构化规格.md"
        record["spec_baselines"]["example.order.query"] = workflow._digest(spec.read_bytes())
        workflow._save(self.project, record)
        spec.write_text(spec.read_text(encoding="utf-8").replace("查询订单", "查询订单结果", 1), encoding="utf-8")
        resumed = self.run_cli("run-resume", "--run-id", "sample-001")
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        value = json.loads(resumed.stdout)
        self.assertIn("example.order.query:prepare", value["invalidated_tasks"])
        self.assertEqual(value["next_task"]["kind"], "writer")

    def test_outline_change_before_task_blocks_old_inventory(self):
        self.create_run()
        outline = self.project / "知识源/功能大纲.md"
        outline.write_text(outline.read_text(encoding="utf-8") + "\n外部增加的范围说明。\n", encoding="utf-8")
        blocked = self.run_cli("run-begin", "--run-id", "sample-001", "--task-id", "inventory")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("功能大纲与运行基线不同", blocked.stderr)
        next_task = json.loads(self.run_cli("run-next", "--run-id", "sample-001").stdout)
        self.assertIsNone(next_task["next_task"])
        self.assertIn("outline_changed", next_task["conflicts"])
        host = json.loads(self.run_cli("host-next", "--run-id", "sample-001", "--host", "claude-code").stdout)
        self.assertIsNone(host["task"])

    def test_writer_can_commit_reviewed_outline_change_to_run_baseline(self):
        self.create_run()
        self.begin("inventory")
        self.assertEqual(self.complete("inventory").returncode, 0)
        self.begin("example.order.query:writer")
        outline = self.project / "知识源/功能大纲.md"
        outline.write_text(outline.read_text(encoding="utf-8") + "\n范围说明已核对。\n", encoding="utf-8")
        self.assertEqual(self.complete("example.order.query:writer").returncode, 0)
        reviewer = self.run_cli("run-begin", "--run-id", "sample-001", "--task-id", "example.order.query:reviewer")
        self.assertEqual(reviewer.returncode, 0, reviewer.stderr)

    def test_unrelated_git_commit_does_not_satisfy_publish_checkpoint(self):
        self.create_run()
        record = workflow.load(self.project, "sample-001")
        for task in record["tasks"]:
            if task["kind"] not in {"commit_inputs", "publish", "audit"}:
                task["status"] = "completed"
        workflow._save(self.project, record)
        extra = self.project / "unrelated.md"
        extra.write_text("unrelated", encoding="utf-8")
        self.begin("commit-inputs")
        subprocess.run(["git", "-C", str(self.project), "add", "unrelated.md"], check=True)
        subprocess.run(["git", "-C", str(self.project), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "unrelated"], check=True)
        result = self.complete("commit-inputs")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("无关文件", result.stderr)
        resumed = self.run_cli("run-resume", "--run-id", "sample-001")
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(json.loads(resumed.stdout)["next_task"]["status"], "blocked")

    def test_approval_after_prepare_resumes_without_refresh(self):
        self.create_run()
        for task_id in ("inventory", "example.order.query:writer", "example.order.query:reviewer"):
            self.begin(task_id)
            self.assertEqual(self.complete(task_id).returncode, 0)
        self.begin("example.order.query:confirm")
        confirmed = self.run_cli("confirm-claims", "--module-id", "example.order.query")
        self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
        completed_confirm = self.complete("example.order.query:confirm")
        self.assertEqual(completed_confirm.returncode, 0, completed_confirm.stderr)
        self.begin("example.order.query:prepare")
        prepared = self.run_cli(
            "prepare", "--module-id", "example.order.query", "--business-topics", "用户操作",
            "--business-unknowns", "运行表现", "--business-keywords", "操作",
            "--engineering-topics", "接口路径和处理方法", "--engineering-unknowns", "部署配对",
            "--engineering-keywords", "调用链", "--refresh",
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        self.assertEqual(self.complete("example.order.query:prepare").returncode, 0)
        self.begin("batch-1:checkpoint")
        self.assertEqual(self.complete("batch-1:checkpoint").returncode, 0)
        self.begin("example.order.query:approval")
        approved = self.run_cli("approve", "--module-id", "example.order.query", "--reviewed-by", "reviewer",
                                "--reviewed-at", "2026-10-24", "--approval-note", "明确批准此公开测试包")
        self.assertEqual(approved.returncode, 0, approved.stderr)
        resumed = self.run_cli("run-resume", "--run-id", "sample-001")
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        state = json.loads(resumed.stdout)
        self.assertEqual(state["next_task"]["kind"], "commit_inputs")
        self.assertIn("review_status: reviewed", (self.module / "发布清单.md").read_text(encoding="utf-8"))
        self.begin("commit-inputs")
        subprocess.run(["git", "-C", str(self.project), "add", "知识源"], check=True)
        subprocess.run(["git", "-C", str(self.project), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "approved inputs"], check=True)
        committed = self.complete("commit-inputs")
        self.assertEqual(committed.returncode, 0, committed.stderr)
        self.begin("publish")
        published = self.run_cli("publish", "--release-id", "release-001")
        self.assertEqual(published.returncode, 0, published.stderr)
        self.assertFalse(any(".code2kb" in path.parts for path in (self.project / "发布").rglob("*")))
        resumed_publish = self.run_cli("run-resume", "--run-id", "sample-001")
        self.assertEqual(resumed_publish.returncode, 0, resumed_publish.stderr)
        self.assertEqual(json.loads(resumed_publish.stdout)["next_task"]["kind"], "audit")
        audited = self.run_cli("run-execute", "--run-id", "sample-001", "--task-id", "audit")
        self.assertEqual(audited.returncode, 0, audited.stderr)
        self.assertEqual(json.loads(self.run_cli("run-status", "--run-id", "sample-001").stdout)["run_status"], "completed")


if __name__ == "__main__":
    fixture.unittest.main()
