"""Failure-mode tests for the local 0.6 execution journal."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "validation" / "knowledge.py"
sys.path.insert(0, str(ROOT))
from validation import run_state
import test_knowledge as fixture
import test_governance as governance_fixture


class RunStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project"
        self.module = self.project / "知识源" / "样本" / "模块"
        self.module.mkdir(parents=True)

    def test_governance_hard_exit_restores_before_images(self):
        first, second = self.module / "模块概览.md", self.module / "发布清单.md"
        first.write_text("old\n", encoding="utf-8")
        code = """
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from validation import run_state
from validation.governance import atomic_write
project, module = Path(sys.argv[2]), Path(sys.argv[3])
with run_state.project_lock(project):
    with run_state.GovernanceTransaction(project, module, 'approve'):
        atomic_write(module / '模块概览.md', 'new\\n')
        os._exit(71)
        atomic_write(module / '发布清单.md', 'approved\\n')
"""
        result = subprocess.run([sys.executable, "-c", code, str(ROOT), str(self.project), str(self.module)])
        self.assertEqual(result.returncode, 71)
        self.assertEqual(first.read_text(encoding="utf-8"), "new\n")
        self.assertFalse(second.exists())
        blocked = subprocess.run([sys.executable, str(SCRIPT), "recover", "--project-root", str(self.project)], capture_output=True, text=True)
        self.assertEqual(blocked.returncode, 0, blocked.stderr)
        self.assertEqual(json.loads(blocked.stdout)["recovered"][0]["result"], "rolled_back")
        self.assertEqual(first.read_text(encoding="utf-8"), "old\n")
        self.assertFalse(second.exists())
        self.assertFalse(run_state.pending_transactions(self.project))

    def test_external_change_blocks_recovery(self):
        target = self.module / "模块概览.md"
        target.write_text("before", encoding="utf-8")
        transaction = run_state.GovernanceTransaction(self.project, self.module, "prepare")
        transaction.__enter__()
        transaction.before_write(target, b"planned")
        run_state._active_transaction.reset(transaction.token)
        target.write_text("external", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "外部变更"):
            run_state.recover_pending(self.project)
        self.assertEqual(target.read_text(encoding="utf-8"), "external")

    def test_project_lock_rejects_second_writer(self):
        code = """
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from validation.run_state import project_lock
with project_lock(Path(sys.argv[2])):
    print('locked', flush=True)
    time.sleep(20)
"""
        child = subprocess.Popen([sys.executable, "-c", code, str(ROOT), str(self.project)], stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: child.poll() is None and (child.kill(), child.wait()))
        self.assertEqual(child.stdout.readline().strip(), "locked")
        with self.assertRaisesRegex(ValueError, "另一修改任务"):
            with run_state.project_lock(self.project):
                pass
        child.kill()
        child.wait()
        child.stdout.close()
        with run_state.project_lock(self.project):
            pass

    def test_empty_governance_journal_after_early_exit_is_discarded(self):
        early = self.project / ".code2kb/transactions/governance-early"
        early.mkdir(parents=True)
        self.assertEqual(run_state.recover_pending(self.project)[0]["result"], "discarded_empty")


class PublishRecoveryTests(unittest.TestCase):
    setUp = fixture.KnowledgeTests.setUp
    run_cli = fixture.KnowledgeTests.run_cli

    def publish_v1(self):
        result = self.run_cli("publish", "--release-id", "v1")
        self.assertEqual(result.returncode, 0, result.stderr)
        subprocess.run(["git", "-C", str(self.project), "add", "发布"], check=True)
        subprocess.run(["git", "-C", str(self.project), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "publish v1"], check=True)

    def crash_publish(self, point):
        code = """
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from validation import knowledge as core
point = sys.argv[3]
project_dir = Path(sys.argv[2]).resolve()
real_replace = os.replace
def replace(source, target):
    real_replace(source, target)
    source, target = Path(source), Path(target)
    if point == 'old_moved' and target.name == '原发布':
        os._exit(72)
    if point == 'new_installed' and target == project_dir / '发布' and source.name == '发布':
        os._exit(73)
if point == 'post_audit':
    def finish(self):
        os._exit(74)
    core.run_state.PublishTransaction.finish = finish
else:
    os.replace = replace
sys.argv = ['knowledge.py', 'publish', '--project-root', sys.argv[2], '--release-id', 'v2']
core.main()
"""
        return subprocess.run([sys.executable, "-c", code, str(ROOT), str(self.project), point], capture_output=True, text=True)

    def assert_recovery(self, point, exit_code, expected):
        self.publish_v1()
        crashed = self.crash_publish(point)
        self.assertEqual(crashed.returncode, exit_code, crashed.stderr)
        recovered = self.run_cli("recover")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual(json.loads((self.project / "发布/当前版本.json").read_text(encoding="utf-8"))["release_id"], expected)
        self.assertEqual(self.run_cli("audit-release").returncode, 0)
        self.assertFalse(run_state.pending_transactions(self.project))

    def test_hard_exit_after_old_directory_moves(self):
        self.assert_recovery("old_moved", 72, "v1")

    def test_hard_exit_after_new_directory_installs(self):
        self.assert_recovery("new_installed", 73, "v2")

    def test_hard_exit_after_audit_before_journal_close(self):
        self.assert_recovery("post_audit", 74, "v2")

    def test_tampered_new_registry_restores_previous_release(self):
        self.publish_v1()
        self.assertEqual(self.crash_publish("new_installed").returncode, 73)
        (self.project / "发布/版本清单/v2.json").write_text("{}", encoding="utf-8")
        recovered = self.run_cli("recover")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual(json.loads((self.project / "发布/当前版本.json").read_text(encoding="utf-8"))["release_id"], "v1")
        self.assertEqual(self.run_cli("audit-release").returncode, 0)


class GovernanceCommandCrashTests(unittest.TestCase):
    """Terminate actual multi-file CLI commands after their first write."""

    def setUp(self):
        self.example = fixture.KnowledgeTests("test_publish_isolated_views_and_no_overwrite")
        self.example.setUp()
        self.addCleanup(self.example.doCleanups)

    PREPARE_OPTIONS = (
        "--refresh", "--business-topics", "用户操作", "--business-unknowns", "运行表现",
        "--business-keywords", "操作", "--engineering-topics", "接口路径和处理方法",
        "--engineering-unknowns", "部署配对", "--engineering-keywords", "调用链",
    )

    def crash_command(self, example, action, *options):
        before = {path.relative_to(example.module): path.read_bytes() for path in example.module.rglob("*.md")}
        code = """
import os, sys
sys.path.insert(0, sys.argv[1])
from validation import knowledge as core
from validation import governance
original = governance.atomic_write
def interrupted(path, value):
    original(path, value)
    os._exit(75)
governance.atomic_write = interrupted
sys.argv = ['knowledge.py', *sys.argv[3:]]
core.main()
"""
        command = [action, "--project-root", str(example.project), "--module-id", "example.order.query", *options]
        crashed = subprocess.run([sys.executable, "-c", code, str(ROOT), str(example.project), *command], capture_output=True, text=True)
        self.assertEqual(crashed.returncode, 75, crashed.stderr)
        self.assertTrue(run_state.pending_transactions(example.project))
        blocked = example.run_cli("check")
        self.assertNotIn("另一修改任务", blocked.stderr)  # read-only inspection remains possible
        recovered = example.run_cli("recover")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual(json.loads(recovered.stdout)["recovered"][0]["result"], "rolled_back")
        after = {path.relative_to(example.module): path.read_bytes() for path in example.module.rglob("*.md")}
        self.assertEqual(after, before)
        self.assertFalse(run_state.pending_transactions(example.project))

    def test_prepare_hard_exit_rolls_back_all_files(self):
        self.crash_command(self.example, "prepare", *self.PREPARE_OPTIONS)

    def test_approve_hard_exit_rolls_back_all_files(self):
        prepared = self.example.run_cli("prepare", "--module-id", "example.order.query", *self.PREPARE_OPTIONS)
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        self.crash_command(self.example, "approve", "--reviewed-by", "fixture-reviewer", "--reviewed-at", "2026-10-25", "--approval-note", "测试明确授权")

    def test_policy_review_hard_exit_rolls_back_all_files(self):
        example = governance_fixture.GovernanceTests("test_policy_review_can_publish_and_records_provenance")
        example.setUp()
        self.addCleanup(example.doCleanups)
        example.enable_policy()
        subject = example.prepare_policy_candidate()
        record = example.policy_record(subject)
        self.crash_command(example, "policy-review", "--evidence-file", record.relative_to(example.project).as_posix(), "--executed-by", "ci-bot")


if __name__ == "__main__":
    unittest.main()
