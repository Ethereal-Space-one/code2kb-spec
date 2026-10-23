---
audience: business
document_type: retrieval_unit
fact_ids:
module_id: starlette.exceptions.background
question_variants: 后台任务失败还能修改已发送的响应吗
release_id: starlette-61123a5
retrieval_schema_version: 0.1
source_documents: starlette/docs/exceptions.md
source_headings: Errors and handled exceptions
topic: 响应发出后的后台任务错误
traceability_level: document
unit_id: ru.business.starlette.exceptions.background.response
---

# 响应发出后的后台任务错误

## 结论与边界

后台任务在响应已经发出后抛错，错误处理器仍会处理该异常，但它新生成的响应会被丢弃，无法替换用户已收到的响应。如果错误发生在响应发出之前，情况不同。

## 出处

- starlette/docs/exceptions.md · Errors and handled exceptions
