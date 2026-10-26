# 全项目源码升级预览

`preview-upgrade --all-modules` 比较项目配置中的旧固定提交与显式传入的新固定提交；只读 Git 对象，不读取工作树作为正式证据，也不更新配置、事实、审核账本或发布指针。

```sh
code2kb preview-upgrade --project-root /知识项目 \
  --all-modules --repository-id backend --new-commit <完整提交号>
```

若维护者已独立核对某个变化路径与知识范围无关，可重复传入 `--exclude-path '相对路径=审核理由'`。已有模块或证据关联的路径不能这样排除。排除理由只记录在本次预览中，不写回知识项目，也不表示工具自动证实了排除的正确性。

输出 `schema_version: 0.2`，与原来的 `--module-id` 结果分开。`changed_files` 列出新增、修改、删除和类型变化及两端 Git blob，并逐路径给出覆盖状态。`changed_evidence` 与 `changed_node_evidence` 比较关系边及扩展节点的原证据在新提交同一路径、同行段的摘要；原文出现在新行段时只给 `relocation_line_candidates`，不会自动保持 `verified`。完全相同 blob 的删除与新增仅给 `relocation_candidates`。这些都是重定位提示，不是新的证据快照。

`must_review_facts` 从变化的关系证据或扩展节点证据出发，沿已复核的入口、接口、方法、事实链定位事实及规格所列正文；`affected_topics` 继续沿已复核事实到主题的边追踪，包括跨模块消费者。扩展节点的观察列在 `changed_node_evidence`；遇到候选或未解关系时停止事实传播，将该边列入 `needs_evidence` 并纳入模块复核。仅当现有关系发布与当前源映射一致时才给 `published_unit_ids`。`possible_modules` 包含变化路径所关联及可追踪的消费者模块，即使旧片段本身未变。`unattributed_paths` 触发全项目复核建议。新增文件的 Adapter L1/L2 发现列在 `adapter.added_file_candidates`，扫描失败或超过单次 32 文件上限列在 `adapter.unresolved`；候选不等于调用、权限或业务关系已核实。

`fallback` 只有 `none_observed`、`module_review`、`full_project_review` 三种建议。`none_observed` 仅表示当前映射没有观察到需要排队的变化，仍受 `coverage`、显式排除和外部服务边界限制。图谱未关联的路径不会因 `must_review_facts` 为空而放行。

该预览只回答“下一步核查哪里”。维护者确认后，仍须修订规格和正文，再执行既有 `impact`、`confirm-claims`、`prepare`、批准、发布与审计。旧命令 `preview-upgrade --module-id ...` 的返回结构与含义保持不变。

## 1.0 只读复核候选计划

全项目模式可显式附加 `--plan`；不附加时仍返回上述 0.2 预览。计划使用独立的 `schema_version: 1.0`，记录旧、新源码提交、知识项目 Git 提交、配置、知识源、关系映射、发布清单及当前发布指针的摘要，并逐路径给出归属和回退原因。`baseline_migration` 另列全局配置与大纲、各模块固定提交文件、关系证据、待重审正文和发布清单的候选修改范围；即使模块不需重新解释业务语义，也可能出现在这张迁移表中。相同输入产生相同 `plan_sha256`。

工作区有未提交改动、新增/删除/类型变化路径、变化路径未归属、显式排除、Adapter 无法解析、关系未证实或变化缺少已验证证据时，计划给出 `full_project_review`。满足当前归属条件时也仅给 `selected_modules` 候选；`execution_gate` 明确要求先解决全局固定提交和证据迁移，并重新走审核。`--plan` 不创建任务、不修改知识项目，也不授权旧批准复用。公开双模块案例已验证只读选择与手工迁移可行；受控迁移和任务衔接仍待实现。
