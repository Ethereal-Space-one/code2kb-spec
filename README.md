# Code2KB Spec

**简体中文** | [English](README.en.md)

Code2KB Spec 帮助团队从**固定 Git 提交**中提取业务行为与代码逻辑，建立有源码依据、可审核、可发布、便于检索的知识库。它提供 AI Agent Skill、文件规范、模板和 Python 参考工具；AI 负责理解与写作，工具负责检查结构、证据和发布状态。

> 当前工程版本：`1.0.0`。新知识项目使用 `c2kb-file/1` 文件协议；旧 `0.8.3` 项目仍可检查和审计。[版本说明](docs/versioning.md)

## 能做什么

- **盘点范围**：登记页面、按钮、接口、消息、定时任务等入口及未覆盖项。
- **建立知识**：把固定提交中的事实、调用与未知边界写成业务版和研发版，保留证据锚点。
- **审核发布**：检查影响、复核结论，按授权发布双版知识及版本清单，并审计快照。
- **按需扩展**：生成检索单元；源码升级时输出[只读复核计划](docs/1.0.0-public-contract.md)，不自动改写或批准知识。

适合维护多仓库应用知识、需要追溯答案来源的团队。它是**知识库生产工具**，不附带业务知识、机器人或在线检索服务。

## 先跑通示例

需要 Git 和 Python 3.9+。克隆仓库后运行内置示例，无需先配置自己的代码：

```bash
git clone https://github.com/Ethereal-Space-one/code2kb-spec.git
cd code2kb-spec
python3 -B examples/create_demo.py
```

脚本会在临时目录创建一个小型源码仓库和知识项目，执行 `check`，并打印知识项目路径。示例只演示文件结构与检查，不会自动生成完整业务知识。

## 接入自己的代码

1. **建立独立知识项目**。复制配置模板，删去不用的示例仓库，为每个源码仓库填写本机绝对路径和固定提交 SHA：

   ```bash
   python3 -m pip install -e .
   mkdir -p /path/to/knowledge-project
   cp templates/知识库配置.example.json /path/to/knowledge-project/知识库配置.json
   git -C /path/to/source-repo rev-parse HEAD
   ```

2. **先盘点，再逐模块取证**。让 AI 编码助手读取 [Skill](skills/extract-app-knowledge/SKILL.md)，从范围盘点开始；核对配置中的固定提交，生成 `知识源/功能大纲.md`，再按模块写规格、业务正文和研发正文。可直接给助手：

   ```text
   请读取 <code2kb-spec-root>/skills/extract-app-knowledge/SKILL.md。
   知识项目是 /path/to/knowledge-project。先核对配置中的固定源码提交，
   盘点全范围入口并生成知识源/功能大纲.md；未知项明确登记，不推断线上运行结果。
   ```

3. **检查与发布**。每个模块依次处理影响复核、结论复核、候选准备和授权审核；全部通过后发布并审计：

   ```bash
   code2kb check --project-root /path/to/knowledge-project
   code2kb publish --project-root /path/to/knowledge-project --release-id my-kb-v1
   code2kb audit-release --project-root /path/to/knowledge-project
   ```

   `publish` 需要已审核的模块包，不能在刚复制模板后直接运行。具体审核命令与参数见[使用指南](docs/usage.md)；工具不会替你判断业务政策或给予发布授权。

## 从哪里继续

| 需求 | 文档 |
| --- | --- |
| 完整操作与命令 | [使用指南](docs/usage.md) |
| 文件、证据和发布规则 | [规范](SPEC.md) |
| 可选检索单元与评测 | [检索契约](docs/retrieval-contract.md) · [评测手顺](docs/retrieval-evaluation.md) |
| 版本变化与兼容性 | [变更记录](CHANGELOG.md) · [兼容说明](docs/compatibility.md) |

**边界**：源码不能单独证明线上部署、运行效果或业务政策；缺少运行证据时保留 `source_only` 与待确认项。检索命中只是候选证据，不等于最终回答已核实。

欢迎阅读 [贡献指南](CONTRIBUTING.md)；本项目采用 [Apache License 2.0](LICENSE)。
