---
name: extract-app-knowledge
description: Extract an evidence-checked feature outline and incremental Chinese Markdown business and engineering QA knowledge from one or more Git repositories. Use for building or updating a source-backed knowledge base, not ordinary feature coding.
---

# 提取源码知识库

从技能目录沿 `../../` 定位 Code2KB Spec 根目录；下文的 `templates/`、`adapters/` 和 `validation/` 均相对于该根目录。先读项目 `知识库配置.json` 和根目录 `VERSION`；本版要求 `standard_version: 0.8.3`。工程版本、知识规范版本与项目 `release_id` 彼此独立，不能从其中一个推定另两个。新项目按配置模板登记约定范围、`coverage_terms`、一个或多个源码仓库及固定提交。已有项目还要读 `知识源/功能大纲.md` 与项目 Git 状态。若项目有接手入口或进度记录，先核对其中指向的权威文件。源码只读配置指定的固定提交，锚点使用 `仓库ID:仓库相对路径:行号`，不得以工作区内容代替。面向人的 `docs/usage.md` 和 [任务提示示例](references/任务提示示例.md) 不作为默认输入。

配置中的仓库 path 可使用绝对路径，或使用完整的大写环境变量引用以适配本地、CI 和代理工作目录。环境变量只决定运行位置，固定 commit 仍须直接写入配置；不得让模型展开 shell 表达式或改用当前工作树代替固定提交。

项目可选启用策略化自动审核。策略必须由 `知识库配置.json` 固定指向并预先提交；`policy-review` 只校验并记录已有审核结果，不调用模型、不冒充人工批准。策略记录必须绑定 `prepare` 生成的候选摘要和模块固定源码提交；命中人工门禁时保持 draft。

0.8.3 可选记录业务意图。需要回答“为什么”时，先读[业务意图与材料证据](references/业务意图与材料证据.md)：只有业务材料或明确人工确认、当前模块行为事实与业务正文形成完整链路的意图才能进入机器人知识库。推断和未知只留在规格与待确认事项。原始业务材料留在原系统，项目只保存脱敏摘录、来源定位与原始内容摘要。

## 按当前任务读取

| 当前任务 | 必读参考与资产 | 完成边界 |
| --- | --- | --- |
| 新建项目、全范围盘点 | [文件与元数据](references/文件与元数据.md)、[范围与大纲](references/范围与大纲.md)、`templates/知识库配置.example.json`、`templates/功能大纲.md`；取证时只读适用的 `adapters/` 文件 | 主会话对账约定范围的入口、模块、受众及缺口，`inventory_status: complete` 且 `check` 通过后才开始模块文件。试点不能替代完整大纲 |
| 单模块取证或规格修订 | [文件与元数据](references/文件与元数据.md)、[模块取证与规格](references/模块取证与规格.md)、[高影响语义闭环](references/高影响语义闭环.md)、需要业务意图时读[业务意图与材料证据](references/业务意图与材料证据.md)、`templates/结构化规格.md`；取证时只读适用的 `adapters/` 文件 | 每轮只深入当前模块，保留稳定 fact/API/METHOD/INT ID、接口匹配、核心方法分支、证据与未知；未确认意图不得进入机器人知识库 |
| 业务与研发正文、自测 | [文件与元数据](references/文件与元数据.md)、[知识写作与复核](references/知识写作与复核.md)、[高影响语义闭环](references/高影响语义闭环.md)、当前要生成的 `templates/` 文件 | 业务版只用业务语言；问答与规则小节离开相邻段落仍能理解结论、必要条件和边界。研发版复用业务结论并补接口、方法和源码。四类问答与三类语义一致性自测后按实际计数报告 |
| 结论影响、证据、审核、Git、发布或回退 | [知识写作与复核](references/知识写作与复核.md)、[发布与维护](references/发布与维护.md) | `impact` 后逐文件语义复核，再 `confirm-claims`；`prepare` 时按有正文依据的主题填写并区分业务/研发检索关键词。人的既有批准用 `approve`；预授权策略审核用独立 `policy-review`，不得混写身份。发布覆盖固定双版路径，覆盖前旧快照须已提交到 Git；发布后 `audit-release` 并提交整个 `发布/` |
| 跨会话或长任务接手 | [长任务续跑](references/长任务续跑.md) | 从项目配置、大纲、进度、缺口、审核记录和 Git 重建状态，不凭聊天总结认定已批准或已发布 |
| 用户允许且任务适合并行取证 | [子Agent取证](references/子Agent取证.md) | 主会话负责范围归类、共享文件写入和最终判断；代理仅回报限定的只读证据 |

有界面时以页面按钮和交互为主要业务线索；无界面时追 API、消息、定时或命令入口。消息、回调和定时入口须继续追到会改变回答的字段级副作用。界面隐藏不等于后端鉴权，成功提示不等于业务状态已变化，动态配置键不等于运行取值；键名有源码证据时必须保留，不能因值未知而省略。静态事实、推断、业务确认、运行观测和未知分开；缺部署配对或运行证据时研发文件保持 `runtime_status: source_only`。未找到调用方不等于废弃。

从 Code2KB Spec 根目录用 `python3 -B validation/knowledge.py check --project-root /项目` 校验。0.8.3 发布清单分开记录业务与研发检索字段，发布前检查纯文字文件引用、事实编号定义、双版导航与自动生成的覆盖数字。`check` 只核机械结构和锚点，不认证语义、现实身份或线上运行；`confirm-claims` 只记录已完成的语义复核。人工模式集中确认可审模块包；策略模式只按已经提交的预授权策略执行。仅按用户授权发布，不自行连接机器人或修改源码仓库；若项目代理设置与上述责任或用户最新指示冲突，先说明冲突。
