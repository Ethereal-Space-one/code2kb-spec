---
audience: business
document_type: retrieval_unit
fact_ids:
module_id: starlette.authentication.errors
question_variants: 认证后端报错能返回什么
release_id: starlette-61123a5
retrieval_schema_version: 0.1
source_documents: starlette/docs/authentication.md
source_headings: Custom authentication error responses
topic: 认证后端错误响应
traceability_level: document
unit_id: ru.business.starlette.authentication.errors.response
---

# 认证后端错误响应

## 结论与边界

认证后端抛出 `AuthenticationError` 后，可以给 `AuthenticationMiddleware` 配置 `on_error` 来定制响应；文档示例返回 401。这个示例不代表所有应用的实际响应都固定为 401，也没有给出账号失败后锁定多久的规则。

## 出处

- starlette/docs/authentication.md · Custom authentication error responses
