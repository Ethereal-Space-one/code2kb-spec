# 官方参考实现

`validation/` 是 Code2KB Spec 0.8.3 的官方 Python 参考实现。它使用标准库，覆盖项目检查、影响队列、候选准备、人工批准、策略审核、发布和纯产物审计。

工程 0.4.0 另外提供可选检索扩展：`retrieval-build`、`retrieval-evaluate`、`retrieval-audit`、`retrieval-query`、`retrieval-compare`，以及显式 `publish --with-retrieval`。检索数据契约独立于 0.8.3 基础 registry；默认命令行为不变。

工程 0.6.0 新增可选[本地接续执行器](0.6.0-runner.md)：项目锁、运行账本、治理与发布恢复、分批任务及 Claude Code 薄适配。执行记录不能代替批准或发布审计。

安装开发版本后可使用：

```bash
python3 -m pip install -e .
code2kb check --project-root /path/to/knowledge-project
```

源码运行方式继续可用：

```bash
python3 -B validation/knowledge.py check --project-root /path/to/knowledge-project
```

参考实现只验证可确定的结构、摘要和门禁。通过检查不代表代码解释、业务政策、线上部署或现实身份已经被证明。
