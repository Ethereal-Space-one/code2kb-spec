#!/usr/bin/env python3
"""Check release-facing version claims against the repository's actual contracts."""

from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def match(pattern: str, value: str, label: str, failures: list[str]) -> str:
    found = re.search(pattern, value, re.MULTILINE)
    if found is None:
        failures.append(f"无法定位 {label}")
        return ""
    return found.group(1)


def main() -> int:
    failures: list[str] = []
    version = read("VERSION").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        failures.append("VERSION 必须是发布用的 X.Y.Z 工程版本")
    package_version = match(r'^version = "([^"]+)"$', read("pyproject.toml"), "包版本", failures)
    protocol = match(r'^DEFAULT_VERSION = "([^"]+)"$', read("validation/protocol.py"), "新项目文件协议标识", failures)
    legacy_protocol = match(r'^LEGACY_VERSION = "([^"]+)"$', read("validation/protocol.py"), "历史文件协议标识", failures)

    if package_version != version:
        failures.append(f"VERSION {version} 与 pyproject.toml {package_version} 不一致")
    if f"当前工程版本：`{version}`" not in read("README.md"):
        failures.append("中文 README 的当前工程版本不一致")
    if f"Current project version: `{version}`" not in read("README.en.md"):
        failures.append("英文 README 的当前工程版本不一致")
    if f"## [{version}]" not in read("CHANGELOG.md"):
        failures.append("CHANGELOG 缺少当前工程版本")
    if f"## 已发布：{version}" not in read("ROADMAP.md"):
        failures.append("路线图未将当前工程版本标为已发布")

    versioning = read("docs/versioning.md")
    engineering_row = match(r"^\| 工程发行版本 \| ([^|]+) \|", versioning, "工程版本表行", failures)
    protocol_row = match(r"^\| 文件协议兼容标识 \| ([^|]+) \|", versioning, "协议版本表行", failures)
    if engineering_row.strip() != f"`{version}`":
        failures.append("版本管理的当前工程版本不一致或仍标为候选")
    if protocol_row.strip() != f"`{protocol}`":
        failures.append("版本管理的文件协议标识与校验器不一致")

    series = ".".join(version.split(".")[:2]) + ".x"
    compatibility = read("docs/compatibility.md")
    current_row = match(
        rf"^\| `{re.escape(series)}` \| ([^|]+) \| ([^|]+) \|$",
        compatibility,
        "当前工程的兼容矩阵表行",
        failures,
    )
    if f"`{legacy_protocol}`" not in current_row:
        failures.append("已发布工程的历史文件协议标识不一致")
    if re.search(rf"^\| `{re.escape(series)}` \|[^\n]*候选", compatibility, re.MULTILINE):
        failures.append("已发布工程在兼容矩阵中仍标为候选")

    template = json.loads(read("templates/知识库配置.example.json"))
    report = json.loads(read("conformance/expected/report.json"))
    if template.get("standard_version") != protocol:
        failures.append("新项目配置模板的协议标识与校验器不一致")
    if report.get("spec_version") != protocol:
        failures.append("一致性报告的协议标识与新项目默认值不一致")
    if report.get("implementation_version") != version:
        failures.append("一致性报告的工程版本与 VERSION 不一致")
    if f"新知识项目的 `standard_version` 必须为 `{protocol}`" not in read("spec/00-规范说明.md"):
        failures.append("基础规范的协议标识与校验器不一致")

    if failures:
        print("发布版本边界检查失败：")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"工作树版本边界检查通过：工程基线 {version}；新项目文件协议 {protocol}；历史兼容 {legacy_protocol}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
