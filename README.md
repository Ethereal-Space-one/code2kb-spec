# Code2KB Spec

**简体中文** | [English](README.en.md)

Code2KB Spec 是一套把固定源码提交转换为可追溯、可审核、可发布知识库的开放规范，并提供 Python 参考实现、AI Agent Skill、模板和技术栈适配器。

> 工程版本：`0.2.0`；知识规范版本：`0.8.3`。两者独立演进。

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

## 0.2.0 新能力

- 安全的 `${UPPER_CASE_ENV}` 源码路径；
- 人工审核与策略化自动审核分离；
- 高影响字段、配置键和正文一致性门禁；
- 业务证据、行为事实和业务意图闭环；
- 严格 JSON、审核溯源和纯发布物审计；
- 可安装的 `code2kb` 命令。

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
├── skills/、templates/、adapters/ # Agent 工具、模板和适配器
├── examples/                      # 可运行示例
├── scripts/                       # 仓库质量检查
└── docs/                          # 教程和实现说明
```

版本规则见[版本管理](docs/versioning.md)，本版验证结果见[0.2.0 开源审计](docs/open-source-audit.md)，后续方向见 [ROADMAP](ROADMAP.md)。

## 参与贡献

提交修改前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。

## 许可证

本项目采用 [Apache License 2.0](LICENSE)。
