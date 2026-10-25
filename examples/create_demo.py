#!/usr/bin/env python3
"""Create and validate a small source-backed knowledge project."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def build(output: Path) -> Path:
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"输出目录必须为空：{output}")
    output.mkdir(parents=True, exist_ok=True)

    source_repo = output / "example-source"
    source_repo.mkdir()
    run("git", "init", "-q", cwd=source_repo)
    write(source_repo / "src/order.py", "def query_order(order_id):\n    return {'order_id': order_id}\n")
    run("git", "add", ".", cwd=source_repo)
    run(
        "git", "-c", "user.name=Example", "-c", "user.email=example@example.com",
        "commit", "-q", "-m", "添加订单查询示例", cwd=source_repo,
    )
    commit = run("git", "rev-parse", "HEAD", cwd=source_repo)

    project = output / "knowledge-project"
    revision = f"source={commit}"
    config = {
        "standard_version": "c2kb-file/1",
        "knowledge_source_root": "知识源",
        "coverage_terms": ["后端入口"],
        "sensitive_patterns": [],
        "boundary_notes": {
            "business": "动态配置和业务政策的实际取值需另行确认。",
            "engineering": "缺部署配对或运行依据时保持 source_only。",
        },
        "repositories": {"source": {"path": str(source_repo.resolve()), "commit": commit}},
    }
    write(project / "知识库配置.json", json.dumps(config, ensure_ascii=False, indent=2) + "\n")

    outline = f"""---
document_type: outline
review_status: draft
applicability: current
source_revisions: {revision}
inventory_status: complete
---

# 示例功能大纲

## 模块清单

| module_id | 业务域 | 子模块 | 发现入口 | 状态 |
| --- | --- | --- | --- | --- |
| example.order.query | 订单 | 订单查询 | 查询入口 | 知识草稿 |

## 入口证据索引

| entry_id | 类型 | 入口或动作 | module_id | 证据 | 状态 |
| --- | --- | --- | --- | --- | --- |
| ENT-001 | 后端入口 | 查询订单 | example.order.query | source:src/order.py:1 | 已归类 |

## 入口受众

| entry_id | 受众 | 范围 |
| --- | --- | --- |
| ENT-001 | 用户操作 | 范围内 |

## 盘点覆盖说明

本示例只约定一个后端入口，已核对源码文件中的全部示例函数。
"""
    write(project / "知识源/功能大纲.md", outline)

    spec = f"""---
module_id: example.order.query
document_type: spec
review_status: draft
applicability: current
source_revisions: {revision}
---

# 订单查询：结构化规格

## 取证基线

固定读取示例源码仓库提交 `{commit}`；没有运行或部署证据。

## 入口与调用链

| fact_id | 单一结论与条件 | 证据等级 | 固定提交锚点 | 影响的知识文件 |
| --- | --- | --- | --- | --- |
| FACT-001 | 查询函数按输入返回订单标识 | CODE_VERIFIED | source:src/order.py:1 | 模块概览.md |

## 入口与接口

| entry_id | api_id | 调用条件 | 证据 |
| --- | --- | --- | --- |

## 接口契约

| api_id | 接口标识 | 调用方 | 服务入口 | 主处理方法 | 证据 |
| --- | --- | --- | --- | --- | --- |

## 调用匹配

| api_id | 匹配状态 | 调用方证据 | 服务方证据 | 部署配对 | 差异或边界 |
| --- | --- | --- | --- | --- | --- |

## 方法职责

| method_id | 符号 | 职责 | 关键性 | 关联接口 | 源码锚点 |
| --- | --- | --- | --- | --- | --- |

## 冲突和未知

实际调用方、权限和线上行为未知。

## 大纲覆盖核对

已复核 ENT-001；本示例没有其他约定入口。

## 问答自测

| 类别 | 真实问题 | 预期行为 | 实测结果 | 结论 |
| --- | --- | --- | --- | --- |
| 正常 | 查询函数返回什么 | 只回答固定源码行为 | 待测 | 待测 |
| 失败 | 查询失败如何表现 | 明确当前未知 | 待测 | 待测 |
| 未知 | 线上是否已部署 | 明确没有运行证据 | 待测 | 待测 |
| 越权 | 提供线上凭据 | 拒绝提供 | 待测 | 待测 |

## 结论复核

| fact_id | 知识文件 | 结论摘要 | 文件摘要 | 复核结果 |
| --- | --- | --- | --- | --- |
"""
    write(project / "知识源/订单/订单查询/结构化规格.md", spec)
    return project


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, help="用于创建示例的空目录；省略时使用临时目录")
    args = parser.parse_args()
    output = args.output or Path(tempfile.mkdtemp(prefix="code2kb-spec-demo-"))
    try:
        project = build(output.resolve())
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(f"创建示例失败：{exc}", file=sys.stderr)
        return 1
    result = subprocess.run(
        [sys.executable, "-B", str(ROOT / "validation/knowledge.py"), "check", "--project-root", str(project)],
        text=True,
    )
    if result.returncode:
        return result.returncode
    print(f"示例已创建并通过检查：{project}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
