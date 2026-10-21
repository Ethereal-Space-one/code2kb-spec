# 一致性说明

兼容声明按角色区分：Producer、Validator、Reviewer 和 Publisher。第三方实现应列出其覆盖的 `C2KB-*` 规范编号，并说明未实现能力。

本仓库当前通过以下方式维护一致性：

- 单元测试覆盖有效与无效项目、两种审核模式和发布审计；
- `scripts/check_spec_ids.py` 检查规范编号唯一性；
- `scripts/check_markdown_links.py` 检查本地链接；
- `scripts/check_public_content.py` 阻断机器专属路径和常见凭据，并支持维护者提供不入库的私有拒绝词；
- `examples/create_demo.py` 创建最小项目并运行参考实现。

后续版本将逐步增加独立 `conformance/` 数据夹具，使其他语言实现可以复用相同输入与预期结果。

组织或项目专属标识不应硬编码进公开扫描器。维护者可以把每行一个的私有词写入仓库根目录的 `.code2kb-public-denylist`，或通过逗号分隔的 `CODE2KB_PUBLIC_DENYLIST` 环境变量传入；本地文件已被 `.gitignore` 排除。
