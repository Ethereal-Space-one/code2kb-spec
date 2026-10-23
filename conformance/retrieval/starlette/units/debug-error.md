---
audience: business
document_type: retrieval_unit
fact_ids:
module_id: starlette.exceptions.debug
question_variants: 开启调试后服务器错误还显示自定义页面吗
release_id: starlette-61123a5
retrieval_schema_version: 0.1
source_documents: starlette/docs/exceptions.md
source_headings: Custom exception handlers
topic: 调试模式下服务器错误
traceability_level: document
unit_id: ru.business.starlette.exceptions.debug.response
---

# 调试模式下服务器错误

## 结论与边界

启用 `debug` 且发生服务器错误时，Starlette 返回 traceback 响应，而不是使用已安装的 500 错误处理器。这里说的是调试模式下的错误响应，不是所有 HTTP 异常都改为 traceback。

## 出处

- starlette/docs/exceptions.md · debug and 500 handler
