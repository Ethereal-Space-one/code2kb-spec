# 离线检索评测

0.4.0 自带 `lexical-v1`：对中文字符和相邻双字、英文数字 token 做确定性匹配，按模块、主题、问法、正文固定权重排序，分数相同按 `unit_id` 排序。它是无外部服务的回归基线，不代表生产 RAG 的实际效果。

## 问题集

问题集 JSON 字段严格为 `schema_version: 0.1`、`suite_id`、`audience`、`cases`。每个 case 必须有唯一 `case_id`、`query`、`expected_module_ids`、`expected_unit_ids`、`required_phrases`、`required_unknown_phrases`、`forbidden_phrases`、`top_k`。至少填写预期模块或单元；建议把失败、未知和越权问法纳入问题集。[公开示例](../conformance/retrieval/suites/minimal-business.json)只含许可明确的通用订单案例。

`schema_version: 0.2` 在每个 case 增加 `expected_decision: answer|abstain`。`abstain` 表示语料无法支持该问题的答案，预期模块、单元和必要短语必须为空。它不是“命中一个写有未知的单元”；评测必须检查检索器提交的独立决策。旧 0.1 问题集继续可用，按有答案题处理。[独立公开候选样本](../conformance/retrieval/starlette/README.md)包含真实的不可回答题和人工审核记录。

```bash
code2kb retrieval-build --project-root /项目 --release-id example-v1 --profile full
code2kb retrieval-evaluate --project-root /项目 --release-id example-v1 --suite /路径/questions.json
code2kb retrieval-audit --project-root /项目 --release-id example-v1
```

`retrieval-build` 后的状态是 `unevaluated`，没有当前检索指针。评测结果包含模块与单元 recall@k、MRR、必要事实与未知短语覆盖、禁止断言命中、受众泄漏、重复命中、出处与版本一致性。任一用例不达预期，门禁失败且无就绪指针。JSON 与人读 Markdown 报告、原始问题集和外部结果副本写入发布目录，审计核摘要。

0.2 报告还记录预期决策、实际决策及不可回答题的正确数。recall@k 与 MRR 只对有答案题计算，避免空金标准把指标虚抬。内置 `lexical-v1` 仅在无命中时决定 `abstain`，有相关命中时会决定 `answer`；它没有语义支持度判断能力。相关但不足以回答的命中因此会使不可回答题失败，这属于基线限制，不能把失败题删掉来放行。

外部检索器只提交结果 JSON，不交给工具凭据或执行权限。字段严格为 `schema_version`、`suite_id`、`retriever_id`、`corpus_sha256`、`cases`。`cases` 是 `case_id` 到有序 `{unit_id, score}` 数组的映射。语料摘要取检索清单 `views` 的规范 JSON SHA-256；评测器拒绝未知、重复 ID 和错误语料摘要。执行：

0.2 外部结果保持相同顶层字段，但每个 case 改为 `{"hits": [{"unit_id": "...", "score": 1.0}], "decision": "answer|abstain"}`。评测器允许拒答时同时返回相关证据，但必须明确提交 `abstain`；不能从空命中或“未知”短语推测其决策。`required_phrases`、`required_unknown_phrases`、`forbidden_phrases` 只扫描检索文本，不评判生成回答。0.2 测到的是检索证据与**检索器声明的可答性决策**，不是机器人回复是否真的拒答。

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
