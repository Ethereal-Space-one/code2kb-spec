# 检索扩展契约

这是 Code2KB Spec 工程的可选扩展，不改变 `c2kb-file/1` 或兼容读取的旧 `0.8.3` 文件协议。基础 `registry_schema_version: 2.0` 仍只含业务版和研发版，基础 `当前版本.json` 字段不变。

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

每个单元是一个 UTF-8 Markdown 文件，围绕一个主题保留原文结论、条件和未知，不重新解释源码。生成来源限已审核的发布正文。`unit_id` 由受众、模块、首个来源文件名和标题摘要确定，正文修改会改变文件 SHA，不会随意改变 ID。完全相同正文在同模块同受众合并并保留所有出处；同模块的泛标题（如“说明”）跨文件聚合，避免相同标题生成相互缺限定的候选。其他相似标题只提示候选，不自动合并。聚合可能改变生成单元的身份或大小，应在新 release 中重建并复核。

生成器识别“适用条件／已确认的适用条件／回答边界／尚不能确定的结果”这些跨节限定标题时，会保守保留完整来源正文为一个单元。其他标题仍需维护者核对条件和答案是否在同一节；生成器不能自动判断所有限定的语义归属。单元超过既有大小上限则构建失败。各单元继承来源文件首节之前的正文前言，嵌套问答还继承其父节前言；泛标题带可读模块名。原文内部锚点会指回基础发布正文。`source_headings` 保留参与聚合的来源节标题，关系主题仍可按原标题找到对应单元。

单元 front matter 必须且只能含 `document_type: retrieval_unit`、`retrieval_schema_version: 0.1`、`unit_id`、`module_id`、`audience`、`topic`、`question_variants`、`source_documents`、`source_headings`、`fact_ids`、`traceability_level`、`release_id`。`audience` 为 `business|engineering`；没有可核事实 ID 时 `fact_ids` 留空、`traceability_level: document`。正文末尾必须有 `## 出处`。一个单元不能超过 256 KiB；不接受符号链接或路径穿越。

检索清单保存两视图逐文件摘要、单元目录、确切重复与相似候选、路由索引摘要、评测报告及其问题集和外部结果摘要。它绑定基础 `release_id`、registry 路径与 SHA-256。`当前检索版本.json` 同时绑定基础 registry 摘要和检索清单摘要。基础发布变化后必须重新构建检索版；不能直接改发布物修复答案。

若当前基础发布已经冻结关系扩展，不能再用 `retrieval-build` 追加检索，因为这会使原关系清单的检索绑定失效。请在新的 release 中使用 `publish --with-retrieval --retrieval-suite ...` 一次生成并冻结两种扩展。未启用关系扩展的基础发布仍可单独构建检索扩展。

默认业务消费者只能读取 `检索版/业务`；研发消费者可合并业务和研发单元。`检索索引` 只负责定位，不是结论来源。基础发布目录仍由 `audit-release` 审计；检索扩展用 `retrieval-audit` 单独审计。

`retrieval-query` 是只读消费入口。它先审计基础发布与当前检索发布，再按指定受众检索，返回单元原文与已审计的正文出处路径。它不会读取旧版本或绕过当前检索就绪指针；输出 `answerability: not_assessed`，不代表可答性或生成回答已验证。

`code2kb retrieval-coverage --project-root /项目 --release-id example-v1` 在基础发布与检索扩展审计后，输出未转成检索单元的发布文件及原因，以及因跨节限定而保守保留整篇、需要人工复核的来源。根级或模块级术语表当前只留在基础发布及其人读索引中；若消费者只导入检索版，应查看报告并按原文位置补充检索来源。报告从冻结清单只读生成，不改变严格清单字段，也不宣称全部业务内容已经转为单元。

## 外部索引导入

外部 FTS 或向量消费者应只读取经审计且评测就绪的当前检索版本，按受众建立独立语料。单元键使用 `(release_id, audience, unit_id)`；一次更新先在独立新快照写入并校验该受众的**全部**新单元，成功后原子切换当前快照，随后按保留策略回收旧快照。标题改变、主题删除或受众迁移后的旧键不进入新快照；经审计的新版本若删除该受众的全部单元，须切换到空快照以停止检索旧内容。导入失败时继续使用旧快照。不能先清空正在服务的索引再写入新单元。参考实现的 `validation.retrieval_snapshot` 只做内存模拟，不连接生产数据库或机器人。

`full` 是默认正文 profile。`compact` 使用相同文件类型，通过在项目根增加 `Code2KB工程配置.json` 选择：

```json
{"schema_version":"0.1","content_profile":"compact"}
```

该工程配置不是 `知识库配置.json` 的新字段。compact 仍要求概览、规则、问答；可以把范围和流程合入这些文件，不能省略四类问答自测和事实证据。方法目录省略时，技术实现必须能定位规格中的每个方法 ID。`retrieval-compare` 只能机械比较主题和未知边界是否出现，不能代替语义复核。

公开样本可用 `python3 -B -m unittest discover -s validation/tests -p test_petclinic_public_source.py -q` 重跑。它先从许可明确的 PetClinic 固定源码生成并发布知识与关系扩展，再建立一个明确标注为受控改动的第二源码提交，通过实际全项目预览命令核对冻结的关系、文档与检索单元映射。两个临时源码提交使用固定时间；同语料、同问题下的 lexical-v1 与实际 SQLite FTS5 trigram、`top_k=1` 原始排名和 FTS 语料摘要见 [公开样本 FTS 记录](../conformance/public-source/petclinic/fts5-run.json)。这个小样本只证明已生成证据可被有限召回，不代表线上问答或通用中文检索质量。
