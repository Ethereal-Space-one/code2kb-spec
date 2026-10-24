#!/usr/bin/env python3
"""Reject machine-specific paths, private identifiers, and common secrets."""

from __future__ import annotations

from pathlib import Path
import os
import re


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".md", ".py", ".json", ".yml", ".yaml", ".toml", ".txt", "",
    ".java", ".ts", ".tsx", ".vue", ".js", ".jsx",
}
LOCAL_DENYLIST = ROOT / ".code2kb-public-denylist"
SKIP_DIRS = {".git", ".venv", "venv", "build", "dist", "__pycache__", ".pytest_cache", ".mypy_cache"}
FORBIDDEN = {
    "macOS 用户绝对路径": re.compile(r"/Users/[^/\s]+/"),
    "Linux 用户绝对路径": re.compile(r"/home/[^/\s]+/"),
    "Windows 用户绝对路径": re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+"),
    "旧公开名称": re.compile(r"source[- ]knowledge[- ]kit", re.IGNORECASE),
    "私钥": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "常见凭据赋值": re.compile(
        r"(?i)(?:api[_-]?key|access[_-]?key|secret|password|passwd|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]"
    ),
}


def private_patterns() -> dict[str, re.Pattern[str]]:
    """Load repository-specific literal deny terms without committing them."""
    values: list[str] = []
    raw = os.environ.get("CODE2KB_PUBLIC_DENYLIST", "")
    values.extend(item.strip() for item in raw.split(",") if item.strip())
    if LOCAL_DENYLIST.is_file():
        values.extend(
            line.strip()
            for line in LOCAL_DENYLIST.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    return {
        f"私有拒绝词 {index}": re.compile(re.escape(value), re.IGNORECASE)
        for index, value in enumerate(dict.fromkeys(values), start=1)
    }


def main() -> int:
    failures: list[str] = []
    patterns = {**FORBIDDEN, **private_patterns()}
    for path in sorted(ROOT.rglob("*")):
        if (
            not path.is_file()
            or path == LOCAL_DENYLIST
            or any(part in SKIP_DIRS or part.endswith(".egg-info") for part in path.parts)
            or path.suffix not in TEXT_SUFFIXES
        ):
            continue
        if path == Path(__file__).resolve():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in patterns.items():
                if pattern.search(line):
                    failures.append(f"{path.relative_to(ROOT)}:{line_number}: {label}")
    if failures:
        print("公开内容检查失败：")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("公开内容检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
