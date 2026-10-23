---
name: extract-app-knowledge
description: Extract evidence-checked business and engineering knowledge from pinned source revisions, then validate and publish a searchable knowledge base.
---

# 源码知识库任务入口

先读 [核心契约](contracts/core.md)，再只读当前任务对应的一份契约。具体字段、文件名和 CLI 参数由 Code2KB Spec 模板、规范和 `code2kb --help` 给出，不在提示词中复制整份 Schema。

| 当前任务 | 任务契约 |
| --- | --- |
| 配置范围、盘点入口 | [范围盘点](contracts/inventory.md) |
| 固定提交取证、写规格 | [模块取证](contracts/extract.md) |
| 写业务与研发正文 | [知识写作](contracts/author.md) |
| 自测、影响复核、检索评测 | [质量评测](contracts/evaluate.md) |
| 审核、发布、审计、回退 | [发布维护](contracts/release.md) |

只有任务或项目配置涉及相应能力时才读 `extensions/`：业务意图、运行证据、策略审核、语义质量、迁移。原 `references/` 在 0.4.0 继续保留，供需要完整操作细节的旧调用方使用。

默认先核对项目 `知识库配置.json`、`VERSION`、功能大纲、固定 Git 提交与当前任务的审核状态。长任务恢复时从项目文件和 Git 重建状态，不凭聊天摘要推断批准或发布。用户授权优先于此技能中的流程建议。
