# 贡献指南

感谢你改进 Code2KB Spec。

## 开始之前

1. 先搜索已有 Issue，确认问题尚未讨论；
2. 对较大的格式、发布协议或目录变更，先创建 Issue 说明目标、兼容性和迁移方案；
3. 不要提交真实业务数据、私有源码、凭据、本机绝对路径或可识别个人的信息。

## 本地验证

```bash
python3 -B -m unittest discover -s validation/tests -q
python3 -B scripts/check_spec_ids.py
python3 -B scripts/check_conformance.py --check-expected
python3 scripts/check_markdown_links.py
python3 scripts/check_public_content.py
git diff --check
```

如果你的修改来自非公开工程，请把组织名、仓库名、模块 ID 等专属词逐行写入根目录的 `.code2kb-public-denylist` 后再运行公开内容检查。该文件不会进入 Git；CI 也可通过逗号分隔的 `CODE2KB_PUBLIC_DENYLIST` 传入相同词表。

修改规则或模板时，请同时更新 `conformance/coverage.json`，并补充能区分有效与无效行为的测试或夹具。仅重复实现细节、不能发现回归的测试没有必要增加。

## Pull Request

- 一次 Pull Request 解决一个清晰问题；
- 说明修改原因、用户可见变化、兼容性和验证结果；
- 如改变知识文件协议，必须更新兼容说明、模板、规范编号覆盖和一致性夹具；
- 如改变命令或公开路径，必须同步 README 与使用指南；
- Commit message 使用简洁中文，格式建议为“动作 + 对象 + 结果”。

项目维护者会根据证据边界、业务与研发隔离、向后兼容和测试质量进行审阅。
