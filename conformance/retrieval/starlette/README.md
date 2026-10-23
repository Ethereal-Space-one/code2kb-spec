# 独立公开检索样本：Starlette

本样本只用于检验 Code2KB Spec 的离线证据定位与未知边界保留。它不是 Starlette 官方知识库，也不验证生成回答或线上服务。五个检索单元由公开文档与代码重新撰写；未复制上游代码、文档正文或任何私有项目内容。

- 上游：<https://github.com/Kludex/starlette>
- 固定提交：`61123a5c76ebb9d5786758008945c4fbbb380bf6`（2026-10-22）
- 上游许可证：BSD-3-Clause，见该提交的 [LICENSE.md](https://github.com/Kludex/starlette/blob/61123a5c76ebb9d5786758008945c4fbbb380bf6/LICENSE.md)。上游版权归其原权利人；本样本不暗示上游认可本项目。
- 证据文件：[认证文档](https://github.com/Kludex/starlette/blob/61123a5c76ebb9d5786758008945c4fbbb380bf6/docs/authentication.md)、[异常文档](https://github.com/Kludex/starlette/blob/61123a5c76ebb9d5786758008945c4fbbb380bf6/docs/exceptions.md)、[权限实现](https://github.com/Kludex/starlette/blob/61123a5c76ebb9d5786758008945c4fbbb380bf6/starlette/authentication.py)。固定提交下对应 Git blob 为 `6789fd1554b4c47ed0675979ae1e02e5bb61dbd0`、`5e3d50088609857cdcbfd411eba471eaf95e19ee`、`317ef01939642969cf9d84c24baf7913589972bb`。
- 单元身份：`release_id: starlette-61123a5`；`corpus.json` 列出所有单元文件的 SHA-256，评测时还需使用 `views` 规范 JSON 的摘要。该单元身份是测试夹具身份，不是上游正式 release。

## 覆盖与分组

| 失效机制 | 开发集 | 保留集 |
| --- | --- | --- |
| HTTP 与 WebSocket 权限差异 | HTTP 默认 403 | WebSocket 不支持自定义 404 |
| 错误发生时机 | debug 覆盖 500 处理器 | 响应已发出后的后台任务错误 |
| 答案未知但有边界证据 | 召回认证错误单元中的锁定时长未知边界 | — |
| 相邻状态码与未知边界 | — | 认证后端错误可定制 401，非统一 403 |

题目按具体问答场景分组，允许共享来源和相邻主题；不能把这种分组称作严格的主题隔离。保留集在检索目标纠正后只运行一次，未用于排名调参。六道题覆盖不同误召回路径；没有用改写问法凑题数。详见[逐题审核记录](审核记录.md)。

## 当前阶段

开发集的 `lexical-v1` 证据检索基线为 [3/3](development-baseline.json)：两道具体行为题命中正确单元；账号锁定题命中认证错误单元及其“没有给出锁定多久的规则”边界。[保留集](holdout-baseline.json)首次运行也是 3/3，六题共覆盖五个检索单元。这个小样本只证明固定题目的离线证据定位，不能推断生产查询的总体质量。账号锁定题的具体时长仍无答案，召回边界不代表模型能正确拒绝编造。六题已由用户指定的独立 AI 完成内容复核。
