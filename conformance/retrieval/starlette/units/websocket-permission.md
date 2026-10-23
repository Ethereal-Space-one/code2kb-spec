---
audience: business
document_type: retrieval_unit
fact_ids:
module_id: starlette.authentication.websocket
question_variants: WebSocket 权限不足能改为 404 吗
release_id: starlette-61123a5
retrieval_schema_version: 0.1
source_documents: starlette/docs/authentication.md | starlette/starlette/authentication.py
source_headings: Permissions | requires
topic: WebSocket 权限不足
traceability_level: document
unit_id: ru.business.starlette.authentication.websocket.permission
---

# WebSocket 权限不足

## 结论与边界

WebSocket 使用 `requires` 检查权限范围时，权限不足会关闭连接；文档说明 `status_code` 参数对 WebSocket 不生效，权限不足始终使用 403，不能套用 HTTP 接口可配置 404 的规则。

## 出处

- starlette/docs/authentication.md · Permissions
- starlette/starlette/authentication.py · requires.websocket_wrapper
