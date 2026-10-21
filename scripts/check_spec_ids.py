#!/usr/bin/env python3
"""Check that normative Code2KB requirement IDs are unique."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PATTERN = re.compile(r"\*\*(C2KB-[A-Z]+-[0-9]{3})\*\*")


def main() -> int:
    found: list[tuple[str, str]] = []
    for path in sorted((ROOT / "spec").glob("*.md")):
        for match in PATTERN.finditer(path.read_text(encoding="utf-8")):
            found.append((match.group(1), path.relative_to(ROOT).as_posix()))
    counts = Counter(item[0] for item in found)
    duplicates = sorted(key for key, count in counts.items() if count > 1)
    if not found:
        print("规范编号检查失败：没有发现 C2KB 约束编号")
        return 1
    if duplicates:
        print("规范编号检查失败：存在重复编号")
        for key in duplicates:
            print(f"- {key}")
        return 1
    print(f"规范编号检查通过：{len(found)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
