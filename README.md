# Code2KB Spec

**简体中文** · [English](README.en.md)

![Code2KB Spec：从固定源码提交到可审核的知识库](assets/readme/overview.svg)

从固定源码提交建立**有证据、可审核、可发布**的业务与研发知识库。

Code2KB Spec 提供知识文件规范、AI Agent Skill、模板和 Python 参考工具。AI 编码助手负责阅读源码与编写知识；参考工具负责检查文件、证据和发布状态。它适合需要追溯知识来源、维护多仓库应用知识的团队。

## 工作流程与产物

`固定 Git 提交 → 入口盘点 → 模块取证与写作 → 审核 → 双版发布`

| 产物 | 内容 |
| --- | --- |
| 知识源 | 功能大纲、模块规格、业务与研发正文、待确认事项 |
| 发布版本 | 分离的业务版与研发版、版本清单和当前版本指针 |
| 可选检索扩展 | 按主题组织的检索单元及独立审计信息 |

源码升级时，1.0.0 还可生成[只读复核计划](docs/1.0.0-public-contract.md)，帮助定位需重新解释的知识；它不会自动改写知识或批准发布。

<details>
<summary>查看源码取证与双版知识示意（3 张）</summary>

图中的代码、文件名和事实编号仅用于说明结构。

![固定源码提交后盘点入口，适配器只输出待复核候选](assets/readme/source-adapters.svg)

![从固定源码锚点记录可核对的结构化事实](assets/readme/evidence.svg)

![同一业务知识分别进入业务版与研发版](assets/readme/two-views.svg)

</details>

<details>
<summary>查看可选检索与源码升级复核示意（2 张）</summary>

检索扩展只处理已审核的发布知识；升级计划只读，不自动迁移或批准。

![从已审计的发布版生成按主题组织的可选检索单元](assets/readme/retrieval.svg)

![比较固定源码提交并生成只读升级复核计划](assets/readme/upgrade-review.svg)

</details>

## 快速体验

需要 **Git** 和 **Python 3.9+**。内置示例无需准备自己的源码：

```bash
git clone https://github.com/Ethereal-Space-one/code2kb-spec.git
cd code2kb-spec
python3 -B examples/create_demo.py
```

命令会在临时目录创建小型源码仓库和知识项目，运行 `check`，并打印项目路径。示例用于体验文件结构与检查流程，不会自动生成完整知识库。

## 创建自己的知识项目

### 1. 安装并固定源码版本

知识项目应与源码仓库分开存放。从模板创建配置：

```bash
python3 -m pip install -e .
mkdir -p /path/to/knowledge-project
git init /path/to/knowledge-project
cp templates/知识库配置.example.json /path/to/knowledge-project/知识库配置.json
git -C /path/to/source-repo rev-parse HEAD
```

编辑 `知识库配置.json`：删去不用的示例仓库，将每个 `repositories` 条目的 `path` 改为本机源码仓库绝对路径，`commit` 改为对应的固定提交 SHA。

### 2. 盘点入口并编写知识

让 AI 编码助手读取 [Skill](skills/extract-app-knowledge/SKILL.md)。先核对配置与固定提交，建立 `知识源/功能大纲.md`；再按模块取证、写业务与研发正文。例如：

```text
请读取 <code2kb-spec-root>/skills/extract-app-knowledge/SKILL.md。
知识项目是 /path/to/knowledge-project。先核对配置中的固定源码提交，
盘点全范围入口并生成知识源/功能大纲.md；明确登记未知项，
不要把源码推断写成线上运行结果。
```

### 3. 检查、审核与发布

知识源写入后，可随时运行结构检查：

```bash
code2kb check --project-root /path/to/knowledge-project
```

按模块完成影响复核、结论复核、候选准备及授权审核后，再发布并审计：

```bash
code2kb publish --project-root /path/to/knowledge-project --release-id my-kb-v1
code2kb audit-release --project-root /path/to/knowledge-project
```

`check` 通过不等于知识已可发布。`impact`、`confirm-claims`、`prepare` 和审核命令的参数见[使用指南](docs/usage.md)。

## 文档与支持

- [使用指南](docs/usage.md)：完整操作手顺与命令
- [规范](SPEC.md)：文件、证据、审核与发布要求
- [检索扩展](docs/retrieval-contract.md)：可选检索单元与外部索引边界
- [版本与兼容性](docs/versioning.md)：工程版本、知识文件协议和项目发布版本
- [问题反馈](https://github.com/Ethereal-Space-one/code2kb-spec/issues) · [贡献指南](CONTRIBUTING.md) · [变更记录](CHANGELOG.md)

## 使用边界

源码不能单独证明线上运行、业务政策或授权结果；缺少运行证据时须保留未知项。项目不包含业务知识、机器人部署或在线检索服务。

当前工程版本：`1.0.0`。新项目默认文件协议为 `c2kb-file/1`；旧 `0.8.3` 项目仍受支持。本项目采用 [Apache License 2.0](LICENSE)。
