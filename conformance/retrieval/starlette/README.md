# 独立公开检索样本：Starlette

本样本只用于检验 Code2KB Spec 的离线证据定位与拒答决策。它不是 Starlette 官方知识库，也不验证生成回答或线上服务。五个检索单元由公开文档与代码重新撰写；未复制上游代码、文档正文或任何私有项目内容。

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
| 缺少支持答案 | 账号锁定时长应拒答 | — |
| 相邻状态码与未知边界 | — | 认证后端错误可定制 401，非统一 403 |

题目按具体问答场景分组，允许共享来源和相邻主题；不能把这种分组称作严格的主题隔离。保留集在候选冻结前不用于排名调参。六道题覆盖不同误答路径；没有用改写问法凑题数。详见[逐题审核记录](审核记录.md)。

## 当前阶段

开发集的 `lexical-v1` 基线为 2/3。两道有答案题命中正确单元；账号锁定题虽命中认证相关文本，但内置基线仍作出 `answer` 决策，故失败。这个失败展示了“相关文本”与“有可支持答案”的差别，不应通过降低金标准消除。六题已由用户指定的独立 AI 完成内容复核；保留集尚未执行，且拒答失败仍在，因此本样本尚不能作为 0.4.0 的通过证明。
