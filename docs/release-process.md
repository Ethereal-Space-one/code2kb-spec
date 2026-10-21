# 公开版本发布流程

本文描述 Code2KB Spec 自身的 GitHub 发布流程。

## 发布前

1. 更新 `VERSION`、`pyproject.toml`、README 和 `CHANGELOG.md`；
2. 核对 `SPEC.md` 的规范版本和实现版本；
3. 运行单元测试、规范编号、一致性夹具、链接、公开内容和空白检查；
4. 创建全新虚拟环境，安装项目并验证 `code2kb --help`；
5. 创建最小示例并运行 `check`；
6. 在 Python 3.9–3.13 的 CI 全部通过后，通过 Pull Request 合并到受保护的 `main`；禁止直接推送发布提交。

发布前的最小回归命令为：

```bash
python3 -B -m unittest discover -s validation/tests -q
python3 -B scripts/check_spec_ids.py
python3 -B scripts/check_conformance.py --check-expected
python3 -B scripts/check_markdown_links.py
python3 -B scripts/check_public_content.py
python3 -B examples/create_demo.py
python3 -m compileall -q validation scripts examples
git diff --check
```

## 发布

从 `main` 创建不可移动的 `vX.Y.Z` 标签和同版本 GitHub Release。Release Notes 应列出规范版本、兼容性、用户可见变化和已知限制。标签对应 CI 通过后，在全新目录重复快速开始。

已发布标签禁止移动或覆盖。问题修复使用新版本；凭据泄露时先撤销或轮换凭据，再按 GitHub 敏感数据流程处理历史。
