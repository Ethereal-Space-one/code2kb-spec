# 离线检索评测

0.4.0 自带 `lexical-v1`：对中文字符和相邻双字、英文数字 token 做确定性匹配，按模块、主题、问法、正文固定权重排序，分数相同按 `unit_id` 排序。它是无外部服务的回归基线，不代表生产 RAG 的实际效果。

## 问题集

问题集 JSON 字段严格为 `schema_version: 0.1`、`suite_id`、`audience`、`cases`。每个 case 必须有唯一 `case_id`、`query`、`expected_module_ids`、`expected_unit_ids`、`required_phrases`、`required_unknown_phrases`、`forbidden_phrases`、`top_k`。至少填写预期模块或单元；建议把失败、未知和越权问法纳入问题集。[公开示例](../conformance/retrieval/suites/minimal-business.json)只含许可明确的通用订单案例。[独立公开候选样本](../conformance/retrieval/starlette/README.md)包含答案未知但相关单元明确写有知识边界的题。

```bash
code2kb retrieval-build --project-root /项目 --release-id example-v1 --profile full
code2kb retrieval-evaluate --project-root /项目 --release-id example-v1 --suite /路径/questions.json
code2kb retrieval-audit --project-root /项目 --release-id example-v1
```

`retrieval-build` 后的状态是 `unevaluated`，没有当前检索指针。评测结果包含模块与单元 recall@k、MRR、必要事实与未知短语覆盖、禁止断言命中、受众泄漏、重复命中、出处与版本一致性。任一用例不达预期，门禁失败且无就绪指针。JSON 与人读 Markdown 报告、原始问题集和外部结果副本写入发布目录，审计核摘要。

本评测只检查 **FTS 找到了哪些证据**。如果问题要求的具体数字在固定语料中未知，可以要求召回写明未知边界的相关单元；这只证明模型有机会看到该边界，不证明模型会正确拒绝编造数字。最终答复的证据支持度和表达质量须在下游模型问答中另测。`lexical-v1` 不判断可答性，`retrieval-query` 明确返回 `answerability: not_assessed`。

外部检索器只提交结果 JSON，不交给工具凭据或执行权限。字段严格为 `schema_version`、`suite_id`、`retriever_id`、`corpus_sha256`、`cases`。`cases` 是 `case_id` 到有序 `{unit_id, score}` 数组的映射。语料摘要取检索清单 `views` 的规范 JSON SHA-256；评测器拒绝未知、重复 ID 和错误语料摘要。执行：

`required_phrases`、`required_unknown_phrases`、`forbidden_phrases` 只扫描检索文本，不评判生成回答。外部结果同样只提交有序命中单元，不提交回答或拒答决策。

```bash
code2kb retrieval-evaluate --project-root /项目 --release-id example-v1 \
  --suite /路径/questions.json --results /路径/external-results.json
```

可在基础发布时显式加入门禁：

```bash
code2kb publish --project-root /项目 --release-id example-v2 \
  --with-retrieval --retrieval-suite /路径/questions.json
```

该命令先在临时快照生成双版、检索单元并完成评测。检索失败时旧 `发布/` 保持不变。默认 `publish` 沿用基础双版发布行为。

比较 full 与 compact 两个独立项目的检索主题：

```bash
code2kb retrieval-compare --project-root /完整项目 --compact-project-root /精简项目
```

比较器报告缺失主题和原本含未知表述、精简版却不再含未知表述的主题。主题相同仍可能存在事实语义差异，需人工复核。
