#!/usr/bin/env python3
"""Validate local Markdown links in the public repository."""

from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def main() -> int:
    failures: list[str] = []
    for path in sorted(ROOT.rglob("*.md")):
        if ".git" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for raw in LINK.findall(text):
            target = raw.strip().strip("<>").split("#", 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = (path.parent / unquote(target)).resolve()
            if not resolved.is_relative_to(ROOT) or not resolved.exists():
                failures.append(f"{path.relative_to(ROOT)} -> {raw}")
    if failures:
        print("发现失效或越界的 Markdown 链接：")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Markdown 本地链接检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
