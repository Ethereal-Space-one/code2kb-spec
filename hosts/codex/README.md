# Codex Host 适配

Codex 与 Claude Code 使用同一份 0.6 运行账本及任务契约。此适配只渲染当前任务，不创建独立状态机，不替用户批准，也不保存授权。

```bash
code2kb host-next --host codex --project-root /path/to/knowledge-project --run-id run-2026-01 --output json
```

响应中的 `task` 与 `run-next` 相同。执行前核对 `allowed_write_set`、`conflicts` 和 `authorization_boundary`。确定性任务可按 `task_id` 运行 `run-execute`；需要人工判断的任务先完成实际核对，再调用 `run-begin` / `run-complete`。`run-complete` 的说明不是批准凭据。批准须有项目中的有效审核记录，发布仍须取得本次明确授权。

若出现冲突，先按[本地接续执行器说明](../../docs/0.6.0-runner.md)运行 `recover` 和 `run-resume`，再重新读取任务。此适配不自动配置 Codex 工具权限或目录隔离；任务完成时的文件范围检查也不能阻止项目外副作用。
