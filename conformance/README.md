# 一致性夹具

此目录给不同语言的 Code2KB 实现提供相同输入、预期结果和规范编号覆盖表。

## 内容

- `cases.json`：夹具清单及有效/无效预期；
- `valid/`、`invalid/`：不依赖维护者机器路径的输入；
- `coverage.json`：61 条规范要求到可执行测试、夹具或示例的显式映射；
- `expected/report.json`：官方参考实现的确定性报告；
- `compatibility-statement.template.json`：第三方兼容声明模板。

## 运行

```bash
python3 -B scripts/check_conformance.py --check-expected
```

脚本会严格读取 JSON，检查每条规范要求恰好存在一项覆盖声明、验证引用目标，并执行夹具。报告不含时间戳或本机路径，可跨环境比较。

通过这些夹具只证明声明范围内的结构兼容，不证明自然语言结论、业务政策、线上部署或现实身份。
