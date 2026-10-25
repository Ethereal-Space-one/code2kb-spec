# 公开版本发布流程

本文描述 Code2KB Spec 自身的 GitHub 发布流程。

## 发布前

1. 更新 `VERSION`、`pyproject.toml`、README、`CHANGELOG.md`、路线图和兼容性说明；
2. 分别核对工程发行版本、文件协议兼容标识和使用方项目 `release_id`，只修改本次实际变化的层次；对外摘要按[发布说明模板](release-notes-template.md)核对。协议未变化时，摘要说明现有项目是否需要迁移即可，不把旧协议编号当作本次新能力；
3. 运行版本边界、单元测试、规范编号、一致性夹具、链接、公开内容和空白检查；
4. 创建全新虚拟环境，安装项目并验证 `code2kb --help`；
5. 创建最小示例并运行 `check`；
6. 在 Python 3.9–3.13 的 CI 全部通过后，通过 Pull Request 合并到受保护的 `main`；禁止直接推送发布提交。

发布前的最小回归命令为：

```bash
python3 -B -m unittest discover -s validation/tests -q
python3 -B scripts/check_spec_ids.py
python3 -B scripts/check_conformance.py --check-expected
python3 -B scripts/check_release_surface.py
python3 -B scripts/check_retrieval_scale.py
python3 -B scripts/check_markdown_links.py
python3 -B scripts/check_public_content.py
python3 -B examples/create_demo.py
python3 -m compileall -q validation scripts examples
git diff --check
```

## 发布

从 `main` 创建不可移动的 `vX.Y.Z` 标签和同版本 GitHub Release。Release Notes 应说明本次实际改变的层次、兼容性、用户可见变化和已知限制；文件协议未改变时不必在发布摘要重复旧编号，技术兼容矩阵仍保留准确编号。发布说明先进入 Pull Request 接受内容复核，再将同一正文写入 GitHub Release。标签对应 CI 通过后，在全新目录重复快速开始。

发布后复核 GitHub Release 正文、README、路线图和兼容矩阵，清除“候选”等过期状态；这一步检查的是公开表述，不替代协议兼容测试。若协议编号变化，必须同时提供旧格式读取、显式迁移、旧发布物审计以及新旧格式夹具，不能只批量替换版本字符串。

已发布标签禁止移动或覆盖。问题修复使用新版本；凭据泄露时先撤销或轮换凭据，再按 GitHub 敏感数据流程处理历史。
