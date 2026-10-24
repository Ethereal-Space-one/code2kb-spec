# Claude Code Host 适配

此适配层只把 0.6 运行账本的当前任务渲染为 Claude Code 可用的指令和命令。它不创建独立状态机，不执行批准，也不保存用户授权。真实状态来自知识项目文件、Git 和 `.code2kb/runs/`。

```bash
code2kb host-next --host claude-code --project-root /path/to/knowledge-project --run-id run-2026-01 --output json
```

响应中的 `task` 与 `run-next` 相同，另外给出 `instruction`、`start`、`finish`、`automated` 和 `authorization_boundary`。Claude Code 应先遵守任务的 `allowed_write_set`，再按命令执行。确定性任务优先用 `run-execute`；审核和发布仍需使用者已有明确授权及旧命令提供的正式凭据。若 `host-next` 与项目现状冲突，先运行 `recover` / `run-resume`，不得凭聊天摘要推进。
