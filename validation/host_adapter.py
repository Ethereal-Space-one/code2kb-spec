"""Stateless Host rendering of the shared 0.6 task contract."""

from __future__ import annotations


INSTRUCTIONS = {
    "inventory": "运行确定性入口盘点检查；未归类和待核查入口保持原状态。",
    "writer": "仅从固定源码提交和允许的业务材料写当前模块知识；保留条件、失败与未知边界。",
    "business_intent": "仅依据可定位且脱敏的业务材料确认意图；证据不足则保持内部未知。",
    "reviewer": "逐条核对会改变问答的结论和证据，指出需改写处；本任务只读，不授予发布批准。",
    "confirm_claims": "语义复核确实完成后才记录结论摘要；工具本身不判断自然语言正确。",
    "prepare": "根据当前正文准备候选，刷新会撤销旧审核戳；不要在已有有效批准后重跑。",
    "checkpoint": "核对本批完成模块、入口覆盖、未归类项、缺口与下一批；不改变审批状态。",
    "approval": "等待用户明确列名批准，或项目已有预授权策略及有效审核记录；只核验既有批准。",
    "commit_inputs": "只提交核对过的发布输入；不得 git add .、夹带无关文件或推送远端。",
    "publish": "必须先取得本次发布授权；使用既有 publish 命令，核对 release-id 与检索扩展选项。",
    "audit": "只读审计当前基础发布及已启用的检索/关系扩展。",
}


HOSTS = frozenset({"claude-code", "codex"})


def render(run: dict, task: dict | None, host: str) -> dict:
    if host not in HOSTS:
        raise ValueError(f"不支持的 Host：{host}")
    if task is None:
        return {"adapter_schema_version": "0.1", "host": host, "run_id": run["run_id"], "task": None}
    kind = task["kind"]
    if kind not in INSTRUCTIONS:
        raise ValueError(f"Host 不支持的任务类型：{kind}")
    result = {
        "adapter_schema_version": "0.1", "host": host, "run_id": run["run_id"],
        "task": {key: task[key] for key in ("task_id", "kind", "module_id", "depends_on", "allowed_write_set", "status", "attempt")},
        "instruction": INSTRUCTIONS[kind],
        "start": f"code2kb run-begin --project-root <知识项目> --run-id {run['run_id']} --task-id {task['task_id']}",
        "finish": f"code2kb run-complete --project-root <知识项目> --run-id {run['run_id']} --task-id {task['task_id']} --actor <执行者> --note <已核对的简短说明>",
        "automated": kind in {"inventory", "confirm_claims", "prepare", "audit"},
        "authorization_boundary": kind in {"approval", "publish"},
    }
    if kind == "publish":
        result["release_id"] = run["release_id"]
        result["retrieval_suite"] = run.get("retrieval_suite")
        result["publish_requires_explicit_authorization"] = True
    return result
