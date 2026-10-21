# 验证说明

在仓库根目录运行：

```bash
python3 -B -m unittest discover -s validation/tests -q
python3 -B scripts/check_spec_ids.py
python3 -B scripts/check_markdown_links.py
python3 -B scripts/check_public_content.py
git diff --check
```

测试覆盖项目结构、固定锚点、环境变量路径、四类问答、语义门禁、业务意图证据链、人工审核、策略审核、双版隔离、发布回滚、严格 JSON 和纯产物审计。

这些检查不能证明自然语言结论、范围穷尽、生产部署、业务政策、外部审核报告或现实身份。使用者仍须审查项目边界和证据质量。
