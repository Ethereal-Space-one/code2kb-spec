#!/usr/bin/env python3
"""Exercise the 0.6 runner against a real, redistributable source commit.

The source is this open-source repository's committed CLI. The knowledge
content is a tiny fixture that describes its public `check` command. This
checks process-to-process recovery and traceability, not model answer quality.
"""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from create_demo import build, write


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "validation" / "knowledge.py"
MODULE_ID = "example.cli.check"


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def run(project: Path, action: str, *args: str) -> dict:
    result = subprocess.run([sys.executable, "-B", str(CLI), action, "--project-root", str(project), *args],
                            capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(f"{action} failed: {result.stderr or result.stdout}")
    return json.loads(result.stdout)


def prepare_project(root: Path) -> Path:
    project = build(root)
    commit = git(ROOT, "rev-parse", "HEAD")
    source = git(ROOT, "show", f"{commit}:validation/knowledge.py").splitlines()
    line = next(index for index, value in enumerate(source, 1) if '"check", "publish"' in value)
    anchor = f"source:validation/knowledge.py:{line}"
    config_path = project / "知识库配置.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["repositories"] = {"source": {"path": str(ROOT), "commit": commit}}
    config["coverage_terms"] = ["命令入口"]
    write(config_path, json.dumps(config, ensure_ascii=False, indent=2) + "\n")

    outline_path = project / "知识源/功能大纲.md"
    outline = outline_path.read_text(encoding="utf-8")
    outline = re.sub(r"source_revisions: source=[0-9a-f]{40}", f"source_revisions: source={commit}", outline)
    outline = outline.replace("example.order.query", MODULE_ID).replace("| 订单 | 订单查询 | 查询入口 |", "| 工具 | 项目检查 | check 命令 |")
    outline = outline.replace("| 后端入口 | 查询订单 |", "| 命令入口 | 检查知识项目 |")
    outline = outline.replace("source:src/order.py:1", anchor)
    outline = outline.replace("本示例只约定一个后端入口，已核对源码文件中的全部示例函数。", "本示例只约定一个命令入口；其他命令不在样本范围。")
    write(outline_path, outline)

    old_module = project / "知识源/订单/订单查询"
    module = project / "知识源/工具/项目检查"
    module.parent.mkdir(parents=True)
    old_module.rename(module)
    (project / "知识源/订单").rmdir()
    spec_path = module / "结构化规格.md"
    spec = spec_path.read_text(encoding="utf-8")
    spec = re.sub(r"source_revisions: source=[0-9a-f]{40}", f"source_revisions: source={commit}", spec)
    spec = spec.replace("example.order.query", MODULE_ID).replace("source:src/order.py:1", anchor)
    spec = spec.replace("订单查询", "知识项目检查").replace("查询函数按输入返回订单标识", "固定版本提供 check 子命令")
    spec = spec.replace("查询函数返回什么", "有哪些项目检查入口").replace("查询失败如何表现", "检查未通过会怎样")
    spec = spec.replace("本示例没有其他约定入口", "本样本没有列入其他命令")
    spec = spec.replace("实际调用方、权限和线上行为未知。", "运行环境的具体结果不由固定提交保证。")
    spec = spec.replace("| 待测 | 待测 |", "| 静态演练 | 通过 |")
    write(spec_path, spec)

    front = f"module_id: {MODULE_ID}\nreview_status: draft\napplicability: current\n"
    overview = (f"---\n{front}document_type: overview\n---\n\n# 项目检查\n\n"
                "用户可运行 check 命令检查知识项目。检查结果只反映当前输入与本工具的校验规则。\n")
    scope = (f"---\n{front}document_type: scope\n---\n\n# 功能与范围\n\n"
             "固定版本提供 check 命令；本样本只覆盖命令入口是否存在。检查通过不证明实际业务结论正确。\n")
    technical = (f"---\n{front}document_type: implementation\nsource_revisions: source={commit}\n"
                 "runtime_status: source_only\n---\n\n# 技术实现\n\n"
                 f"命令注册位置由固定提交锚点 `{anchor}` 定位；不推断其他命令的运行效果。\n")
    write(module / "模块概览.md", overview)
    write(module / "功能与范围.md", scope)
    write(module / "技术实现.md", technical)
    write(project / ".gitignore", ".code2kb/\n")
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "add", "知识库配置.json", "知识源", ".gitignore"], check=True)
    subprocess.run(["git", "-C", str(project), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "commit", "-q", "-m", "建立公开样本"], check=True)
    return project


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="code2kb-runner-public-") as temporary:
        project = prepare_project(Path(temporary) / "sample")
        run_id, release_id = "public-source-001", "public-source-v1"
        created = run(project, "run-create", "--run-id", run_id, "--module-id", MODULE_ID, "--release-id", release_id)
        assert created["next_task"]["kind"] == "inventory"
        run(project, "run-execute", "--run-id", run_id, "--task-id", "inventory")
        for task in ("writer", "reviewer"):
            task_id = f"{MODULE_ID}:{task}"
            run(project, "run-begin", "--run-id", run_id, "--task-id", task_id)
            run(project, "run-complete", "--run-id", run_id, "--task-id", task_id,
                "--actor", "public-fixture", "--note", "已对照开源固定提交和样本边界")
        run(project, "run-execute", "--run-id", run_id, "--task-id", f"{MODULE_ID}:confirm")
        run(project, "run-begin", "--run-id", run_id, "--task-id", f"{MODULE_ID}:prepare")
        run(project, "prepare", "--module-id", MODULE_ID, "--business-topics", "项目检查",
            "--business-unknowns", "业务结论正确性", "--business-keywords", "项目检查",
            "--engineering-topics", "命令注册", "--engineering-unknowns", "运行环境",
            "--engineering-keywords", "命令注册")
        run(project, "run-complete", "--run-id", run_id, "--task-id", f"{MODULE_ID}:prepare",
            "--actor", "public-fixture", "--note", "候选摘要已核对")
        run(project, "run-begin", "--run-id", run_id, "--task-id", "batch-1:checkpoint")
        run(project, "run-complete", "--run-id", run_id, "--task-id", "batch-1:checkpoint",
            "--actor", "public-fixture", "--note", "一模块样本范围和未知项已核对")
        run(project, "run-begin", "--run-id", run_id, "--task-id", f"{MODULE_ID}:approval")
        run(project, "approve", "--module-id", MODULE_ID, "--reviewed-by", "public-fixture",
            "--reviewed-at", date.today().isoformat(), "--approval-note", "仅批准本临时公开夹具的本地发布")
        resumed = run(project, "run-resume", "--run-id", run_id)
        assert resumed["next_task"]["kind"] == "commit_inputs"
        run(project, "run-begin", "--run-id", run_id, "--task-id", "commit-inputs")
        subprocess.run(["git", "-C", str(project), "add", "知识源"], check=True)
        subprocess.run(["git", "-C", str(project), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                        "commit", "-q", "-m", "记录样本审核输入"], check=True)
        run(project, "run-complete", "--run-id", run_id, "--task-id", "commit-inputs", "--actor", "public-fixture",
            "--note", "只提交本次知识源文件")
        run(project, "run-begin", "--run-id", run_id, "--task-id", "publish")
        run(project, "publish", "--release-id", release_id)
        run(project, "run-resume", "--run-id", run_id)
        run(project, "run-execute", "--run-id", run_id, "--task-id", "audit")
        state = run(project, "run-status", "--run-id", run_id)
        assert state["run_status"] == "completed"
        print(json.dumps({"source": "Code2KB Spec committed open-source repository", "release_id": release_id,
                          "tasks": state["completed_tasks"], "status": "passed",
                          "boundary": "process recovery and source traceability only; not model answer quality"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
