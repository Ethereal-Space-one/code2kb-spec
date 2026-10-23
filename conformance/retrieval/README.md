# 检索扩展示例夹具

`units/` 是公开、通用的订单与账号查询示例，不涉及实际公司项目。`suites/minimal-business.json` 演示正常、失败、未知和越权问法，以及跨模块同名主题。`corpus.json` 固定两类单元的文件摘要；`external-results/minimal-business.json` 演示离线导入格式，语料摘要取 `corpus.json` 中 `views` 的规范 JSON SHA-256，不对应任何实际项目。

完整端到端测试见 `validation/tests/test_retrieval.py`。这些夹具验证格式和评测行为，不证明模型问答质量。
