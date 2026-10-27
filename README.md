# Code2KB Spec

**简体中文** | [English](README.en.md)

Code2KB Spec 从固定源码提交提取有证据的业务行为与代码逻辑，建立可追溯、可审核、可发布、适合检索的知识库，并提供开放规范、Python 参考实现、AI Agent Skill、模板和技术栈适配器。代码不能单独证明业务政策原因或线上运行结果；未知边界须随知识保留。

> 当前工程版本：`1.0.0`。知识文件协议的兼容标识见[版本管理](docs/versioning.md)，不与任何使用本工具的知识库项目同步编号。

## 三层结构

| 层次 | 内容 | 入口 |
| --- | --- | --- |
| Code2KB Spec | 文件、证据、审核和发布规范 | [SPEC.md](SPEC.md) |
| Reference Implementation | Python 校验、审核、发布和审计工具 | [参考实现](docs/reference-implementation.md) |
| Agent Toolkit | Skill、提示词、模板和适配器 | [AI Skill](skills/extract-app-knowledge/SKILL.md) |

## 它解决什么问题

直接让 AI 阅读大型代码仓库，容易遗漏范围、把推断写成事实、混淆业务和技术内容，也难以跨会话复核。Code2KB 将过程拆成可检查步骤：

1. 盘点页面、按钮、接口、消息、定时和命令入口；
2. 固定源码提交，记录事实、方法、接口和证据锚点；
3. 追踪高影响字段、动态配置和跨文档语义；
4. 只把证据闭环的业务意图写入机器人知识；
5. 通过人工批准或预授权策略审核候选包；
6. 生成隔离的业务版与研发版，并审计完整快照。

## 快速开始

```bash
git clone https://github.com/Ethereal-Space-one/code2kb-spec.git
cd code2kb-spec
python3 -B -m unittest discover -s validation/tests -q
python3 -B scripts/check_spec_ids.py
python3 -B scripts/check_conformance.py --check-expected
python3 -B scripts/check_retrieval_scale.py
```

可以安装本地命令：

```bash
python3 -m pip install -e .
code2kb --help
code2kb --version
```

复制配置模板：

```bash
cp templates/知识库配置.example.json /path/to/knowledge-project/知识库配置.json
```

把仓库路径和固定提交替换为真实值，然后让 AI 读取：

```text
请完整读取 <code2kb-spec-root>/skills/extract-app-knowledge/SKILL.md，
按其中“当前任务”的路由读取所需参考文件和模板。
我的知识库项目是 /path/to/knowledge-project，
本次任务是建立全范围功能大纲。
```

检查知识项目：

```bash
code2kb check --project-root /path/to/knowledge-project
# 或：python3 -B validation/knowledge.py check --project-root /path/to/knowledge-project
```

完整命令和发布流程见[使用指南](docs/usage.md)。

## 0.4.0 新能力

- 从已审核双版生成按主题切分、受众隔离的 Markdown 检索单元；
- 独立检索清单、轻量路由索引、基础版本摘要绑定和篡改审计；
- 对已审计的当前检索发布物执行只读查询，返回候选证据及双版正文出处；
- 无外部依赖的离线检索评测，支持导入外部检索结果；
- 可选 `compact` 正文模式与 full/compact 主题覆盖对照；
- Agent Skill 按核心契约、当前任务和可选扩展加载。

检索扩展的[产物契约](docs/retrieval-contract.md)与[评测手顺](docs/retrieval-evaluation.md)独立维护。默认发布行为保持双版；只有显式启用检索扩展时才产生检索就绪指针。

## 0.5.0 新能力

可选的[关系与证据扩展](docs/relation-contract.md)提供固定提交片段重建、事实与检索主题的审核映射、覆盖报告及首批 TypeScript/Java 候选发现。它不会把候选调用自动写成业务事实；旧项目默认行为保持不变。[实施计划](docs/0.5.0-implementation-plan.md)和[独立公开证据核对](docs/0.5.0-public-evidence-check.md)记录范围与验证边界。

## 0.6.0 新增能力

可选的[本地接续执行器](docs/0.6.0-runner.md)提供任务账本、项目锁、崩溃恢复、批次检查点和 Claude Code／Codex 薄适配。账本不代替正式批准；旧知识项目无需启用它，也无需为此重新发布。文件格式兼容关系见[版本管理](docs/versioning.md)，范围与发布门槛见[实施计划](docs/0.6.0-implementation-plan.md)。

[实施与验证记录](docs/0.6.0-implementation-report.md)列出通过的检查及已知边界。

## 0.7.0 新增能力

新知识项目默认使用独立文件协议标识 `c2kb-file/1`；旧 `0.8.3` 项目继续按原规则检查、发布与审计，迁移须显式预演和执行。多语言 Adapter 提供固定源码候选、能力声明与保守的关系线索；候选仍需人工核对后才能写为知识事实。独立的 [Spring PetClinic 公开样本](docs/0.7.0-public-sample-review.md)走通了人工锚点映射、双版发布和检索单元；它不证明自动跨仓库配对或线上运行结果。详见[实施与复核记录](docs/0.7.0-implementation-report.md)。

## 0.8.0 新增能力

可选检索扩展保守保留跨节条件和未知、合并同模块的泛标题，并提供术语表遗漏与整篇保留诊断。新增只读的[全项目源码升级预览](docs/source-upgrade-preview.md)：比较旧、新固定提交，标出证据变化、事实与主题、可定位的检索单元以及无法归属的路径。公开 PetClinic 样本用两个受控提交和实际 SQLite FTS5 跑通改变答案后的定位与召回；结果只证明小样本证据可召回，不代表最终模型回答或线上行为已验证。[检索导入边界](docs/retrieval-contract.md)保持独立快照切换，默认双版发布和知识文件协议不变。

## 1.0.0 新增能力

`preview-upgrade --all-modules --plan` 为源码升级生成绑定输入摘要的[只读复核计划](docs/1.0.0-public-contract.md)：区分需要重新解释业务语义的模块、全局基线触及和需刷新审核的包。计划过期或覆盖不明时拒绝或回退全项目；它不自动改写知识、迁移证据、创建任务、批准或发布。公开五模块案例显示语义复核候选为 1/5，但基线与审核工作仍为 5/5，因此不宣称自动增量执行有净收益。业务版新发布会拒绝明确的源码仓库链接；旧发布可按原规则继续审计。

## 能力边界

本项目能检查结构、固定锚点、摘要、发布隔离和治理记录。它不能自动证明：

- AI 对源码的自然语言理解一定正确；
- 入口盘点已经覆盖全部业务；
- 固定提交与线上部署一致；
- 业务政策和授权边界已经正式确认；
- 自动审核的外部报告内容真实；
- 静态源码推断等同于运行结果。

项目不包含具体公司的业务知识、机器人部署、向量数据库或线上凭据。

## 仓库结构

```text
├── SPEC.md、spec/                  # 规范性内容
├── validation/                    # 官方 Python 参考实现
├── conformance/                   # 跨实现夹具、覆盖表与预期报告
├── skills/、templates/、adapters/ # Agent 工具、模板和适配器
├── examples/                      # 可运行示例
├── scripts/                       # 仓库质量检查
└── docs/                          # 教程和实现说明
```

版本规则见[版本管理](docs/versioning.md)，升级关系见[兼容性说明](docs/compatibility.md)，本版实施边界见[1.0.0 实施规划](docs/1.0.0-implementation-plan.md)，后续方向见 [ROADMAP](ROADMAP.md)。

## 参与贡献

提交修改前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。

## 许可证

本项目采用 [Apache License 2.0](LICENSE)。
