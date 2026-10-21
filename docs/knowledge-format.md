# 知识文件格式

Code2KB Spec 工程 `0.2.0` 实现知识规范 `0.8.3`。规范性要求见 [`SPEC.md`](../SPEC.md)，本文件只提供快速说明。

## 配置

`知识库配置.json` 至少包含：

- `standard_version: 0.8.3`；
- `knowledge_source_root`；
- 一个或多个源码仓库路径和固定 Git 提交；
- `coverage_terms`；
- 可选 `policy_review`、`semantic_quality`、敏感模式和受众边界。

路径可为绝对目录或完整 `${UPPER_CASE_ENV}`，提交必须直接填写固定 SHA。

## 文件类型

业务正文包括模块概览、功能范围、业务流程、规则限制、常见问答，以及证据闭环时的业务意图。研发正文增加技术实现、接口与调用、方法与源码。结构化规格、待确认事项、发布清单和证据属于治理材料，不进入检索目录。

## 证据与意图

事实等级为 `CODE_VERIFIED`、`RUN_VERIFIED`、`BUSINESS_CONFIRMED`、`INFERRED` 和 `UNKNOWN`。业务意图另使用 `DOCUMENTED` 表示文档材料直接证明的业务原因。

业务意图进入发布物前必须闭环：

```text
业务证据 → INT 意图主张 → 行为事实 → 业务意图正文
```

推断和未知意图不得进入机器人知识库。

## 模板

完整字段和章节见 [`templates/`](../templates/)；对应的规范要求见 [`spec/`](../spec/)。
