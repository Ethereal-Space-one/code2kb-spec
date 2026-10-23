---
audience: business
document_type: retrieval_unit
fact_ids:
module_id: starlette.authentication.http
question_variants: 网页接口权限不足会怎样
release_id: starlette-61123a5
retrieval_schema_version: 0.1
source_documents: starlette/docs/authentication.md | starlette/starlette/authentication.py
source_headings: Permissions | requires
topic: HTTP 权限不足
traceability_level: document
unit_id: ru.business.starlette.authentication.http.permission
---

# HTTP 权限不足

## 结论与边界

HTTP 接口使用 `requires` 检查所需权限范围。权限不足时默认返回 403；接口可显式配置返回 404，以隐藏地址布局，也可配置重定向。404 是可选配置，不能说成默认结果。

## 出处

- starlette/docs/authentication.md · Permissions
- starlette/starlette/authentication.py · requires
