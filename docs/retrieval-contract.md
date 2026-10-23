# 0.4.0 检索扩展契约

这是 Code2KB Spec 工程的实验扩展，不改变知识规范 `0.8.3`。基础 `registry_schema_version: 2.0` 仍只含业务版和研发版，基础 `当前版本.json` 字段不变。

## 目录与身份

```text
发布/
├── 业务版/、研发版/、版本清单/、当前版本.json
├── 检索版/业务/、检索版/研发/
├── 检索索引/<release_id>.json
├── 检索清单/<release_id>.json
├── 检索评测/<release_id>.json
├── 检索评测/<release_id>.md
├── 检索评测/套件/<release_id>.json
├── 检索评测/外部结果/<release_id>.json  # 仅外部评测
└── 当前检索版本.json                    # 仅门禁通过
```

每个单元是一个 UTF-8 Markdown 文件，围绕一个主题保留原文结论、条件和未知，不重新解释源码。生成来源限已审核的发布正文。`unit_id` 由受众、模块、来源文件名和标题摘要确定，正文修改会改变文件 SHA，不会随意改变 ID。完全相同正文在同模块同受众合并并保留所有出处；相似标题只提示候选，不自动合并。

单元 front matter 必须且只能含 `document_type: retrieval_unit`、`retrieval_schema_version: 0.1`、`unit_id`、`module_id`、`audience`、`topic`、`question_variants`、`source_documents`、`source_headings`、`fact_ids`、`traceability_level`、`release_id`。`audience` 为 `business|engineering`；没有可核事实 ID 时 `fact_ids` 留空、`traceability_level: document`。正文末尾必须有 `## 出处`。一个单元不能超过 256 KiB；不接受符号链接或路径穿越。

检索清单保存两视图逐文件摘要、单元目录、确切重复与相似候选、路由索引摘要、评测报告及其问题集和外部结果摘要。它绑定基础 `release_id`、registry 路径与 SHA-256。`当前检索版本.json` 同时绑定基础 registry 摘要和检索清单摘要。基础发布变化后必须重新构建检索版；不能直接改发布物修复答案。

默认业务消费者只能读取 `检索版/业务`；研发消费者可合并业务和研发单元。`检索索引` 只负责定位，不是结论来源。基础发布目录仍由 `audit-release` 审计；检索扩展用 `retrieval-audit` 单独审计。

`full` 是默认正文 profile。`compact` 使用相同文件类型，通过在项目根增加 `Code2KB工程配置.json` 选择：

```json
{"schema_version":"0.1","content_profile":"compact"}
```

该工程配置不是 `知识库配置.json` 的新字段。compact 仍要求概览、规则、问答；可以把范围和流程合入这些文件，不能省略四类问答自测和事实证据。方法目录省略时，技术实现必须能定位规格中的每个方法 ID。`retrieval-compare` 只能机械比较主题和未知边界是否出现，不能代替语义复核。
