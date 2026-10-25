# Code2KB Spec 使用指南

> 已发布工程基线 `0.6.0`；0.7 候选中新项目默认 `c2kb-file/1`，旧项目继续支持 `0.8.3`。AI 的执行入口是 [`skills/extract-app-knowledge/SKILL.md`](../skills/extract-app-knowledge/SKILL.md)。

## 工作方式

Code2KB 从一个或多个固定 Git 提交中建立独立的知识项目。先盘点全范围入口，再逐模块提取事实、正文和证据，最后经人工或策略审核生成业务版与研发版。

| 阶段 | 主要产物 | 完成条件 |
| --- | --- | --- |
| 范围盘点 | `知识库配置.json`、`功能大纲.md` | 入口、模块、受众、范围和缺口逐项登记 |
| 模块取证 | `结构化规格.md`、研发材料 | 事实、接口、方法、锚点和未知边界完整 |
| 知识写作 | 业务正文、研发正文、可选业务意图 | 四类问答；业务与技术内容隔离 |
| 影响复核 | impact 队列、结论复核 | 受影响文件逐项清零 |
| 候选审核 | `发布清单.md`、人工或策略审核记录 | 候选摘要和审核依据一致 |
| 发布审计 | 双版、版本清单、当前指针 | `audit-release` 通过并提交 Git |

## 安装

直接运行源码：

```bash
python3 -B validation/knowledge.py --help
```

或安装命令：

```bash
python3 -m pip install -e .
code2kb --help
code2kb --version
```

两种入口调用同一参考实现。

## 新建知识项目

1. 为知识库建立独立 Git 项目。
2. 复制 [`templates/知识库配置.example.json`](../templates/知识库配置.example.json)。
3. 为每个源码仓库填写绝对路径或完整 `${UPPER_CASE_ENV}` 引用，并填写固定提交 SHA。
4. 让 AI 读取 Skill，先建立完整功能大纲。

```text
请完整读取 <code2kb-spec-root>/skills/extract-app-knowledge/SKILL.md，
按“当前任务”只加载所需参考文件和模板。
知识项目为 /path/to/knowledge-project，
本次任务是建立全范围功能大纲。
```

## 项目结构

```text
知识项目/
├── 知识库配置.json
├── 知识源/功能大纲.md
├── 知识源/<业务域>/<模块>/
│   ├── 模块概览.md、功能与范围.md、业务流程.md
│   ├── 规则与限制.md、常见问答.md、业务意图.md       # 按证据创建
│   ├── 技术实现.md、接口与调用.md、方法与源码.md     # 按证据创建
│   └── 结构化规格.md、待确认事项.md、发布清单.md
├── 运行证据/                                           # 可选
├── 自动审核策略/、自动审核记录/                        # 策略审核时使用
└── 发布/
```

不创建空正文。业务证据只保存脱敏摘录和原始材料摘要，不复制敏感原文。

## 常用命令

```bash
code2kb check --project-root /项目
code2kb impact --project-root /项目 --module-id example.module
code2kb confirm-claims --project-root /项目 --module-id example.module
code2kb prepare --project-root /项目 --module-id example.module \
  --business-topics '用户操作、处理结果' \
  --business-unknowns '运行环境表现' \
  --business-keywords '订单、查询' \
  --engineering-topics '调用链与处理方法' \
  --engineering-unknowns '部署差异' \
  --engineering-keywords '订单、查询、实现'
```

人工明确授权后记录审核：

```bash
code2kb approve --project-root /项目 --module-id example.module \
  --reviewed-by '实际审核人' --reviewed-at 2026-10-20 \
  --approval-note '审核人确认的发布范围原文'
```

启用预授权策略时，先把策略和审核记录提交到项目 Git，再执行：

```bash
code2kb policy-review --project-root /项目 --module-id example.module \
  --evidence-file 自动审核记录/run-id/example.module.json \
  --executed-by ci-bot
```

发布和审计：

```bash
code2kb publish --project-root /项目 --release-id example-v1
code2kb audit-release --project-root /项目
```

准确参数和回退方式见[发布与维护](../skills/extract-app-knowledge/references/发布与维护.md)。

## 可选检索扩展

基础双版发布后，可按[检索扩展契约](retrieval-contract.md)构建单主题单元，并按[离线评测手顺](retrieval-evaluation.md)运行问题集。评测通过后才有 `发布/当前检索版本.json`；失败不改变基础版本指针。下次基础发布可显式使用 `publish --with-retrieval --retrieval-suite` 把检索门禁纳入同一临时快照。

检索扩展通过审计后，可从**当前检索版本**只读查询候选证据：

```bash
code2kb retrieval-query --project-root /项目 --query "订单查询失败时会怎样" --audience business --top-k 3
```

返回 JSON 含 `release_id`、检索清单摘要、命中单元原文、单元路径及双版正文出处。`business` 只读取业务单元；`engineering` 可读取业务与研发单元。输出的 `answerability: not_assessed` 表示尚未判断证据能否回答问题；无命中也不自动构成最终拒答。此命令不修改发布物，也不生成机器人回复。未通过检索门禁或审计失败的发布物不可查询。

`compact` 项目在根目录放独立 `Code2KB工程配置.json`，保留现有知识规范文件类型；它不能靠省略必要条件或未知来缩短正文。

## 重要边界

可选的持久运行账本、批次任务、恢复命令及 Claude Code 薄适配见[0.6 本地接续执行器](0.6.0-runner.md)。旧知识项目无需启用账本。

- `check` 验证结构和固定锚点，不证明自然语言正确。
- `confirm-claims` 记录已经完成的语义复核，不执行语义判断。
- `policy-review` 验证策略和记录，不调用审核模型。
- 缺少运行证据时，研发正文保持 `source_only`。
- 未闭环业务意图只能留在内部规格和待确认事项。
- 业务用户只检索业务版；研发用户才检索研发版。
