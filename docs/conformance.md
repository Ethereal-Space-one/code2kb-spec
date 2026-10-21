# 一致性说明

兼容声明按 Producer、Validator、Reviewer 和 Publisher 四种角色区分。第三方实现应列出其覆盖的 `C2KB-*` 规范编号、未实现能力、使用的夹具提交和报告摘要。

## 官方参考实现

本仓库通过以下门禁维护一致性：

- 单元测试覆盖有效与无效项目、两种审核模式和发布审计；
- [`conformance/`](../conformance/README.md) 提供跨实现输入、预期结果、61 条要求覆盖表和兼容声明模板；
- `scripts/check_spec_ids.py` 检查规范编号唯一性；
- `scripts/check_conformance.py --check-expected` 执行夹具并对比确定性报告；
- `scripts/check_markdown_links.py` 检查本地链接；
- `scripts/check_public_content.py` 阻断机器专属路径和常见凭据；
- `examples/create_demo.py` 创建最小项目并运行参考实现。

## 第三方兼容声明

1. 固定 Code2KB Spec 版本与一致性夹具的 Git 提交；
2. 运行全部夹具，保存机器可读报告并计算 SHA-256；
3. 从 [`compatibility-statement.template.json`](../conformance/compatibility-statement.template.json) 创建声明；
4. 逐项列出角色、已覆盖编号、未覆盖编号和限制；
5. 实现或夹具升级后重新生成声明，禁止沿用旧报告。

“通过部分夹具”只能声明对应编号和角色兼容，不得表述为完整实现。夹具不判断自然语言事实是否正确，也不证明线上部署、业务政策或审核人身份。

## 私有公开扫描词

组织或项目专属标识不应硬编码进公开扫描器。维护者可以把每行一个的私有词写入仓库根目录的 `.code2kb-public-denylist`，或通过逗号分隔的 `CODE2KB_PUBLIC_DENYLIST` 环境变量传入；本地文件已被 `.gitignore` 排除。
