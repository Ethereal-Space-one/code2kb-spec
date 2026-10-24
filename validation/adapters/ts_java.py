"""Conservative fixed-commit candidates for UniApp/TypeScript and Java."""

from __future__ import annotations

from pathlib import PurePosixPath
import re
import subprocess

from .uniapp_pages import read_uniapp_pages


MAX_FILES = 20000
MAX_BYTES = 1024 * 1024
SOURCE_SUFFIXES = {".ts", ".tsx", ".vue", ".js", ".jsx", ".java"}
TS_LITERAL = re.compile(r"\b(?:url|path)\s*:\s*(['\"`])([^'\"`\r\n]+)\1")
TS_DYNAMIC = re.compile(r"\b(?:url|path)\s*:\s*(?!\s*['\"`])([^,}\r\n]+)")
JAVA_ANNOTATION = re.compile(r"@(?:GetMapping|PostMapping|PutMapping|PatchMapping|DeleteMapping|RequestMapping)\s*\(([^)]*)\)")
JAVA_LITERAL = re.compile(r"(?:value\s*=\s*|path\s*=\s*)?\"([^\"]+)\"")
METHOD = re.compile(r"\b(?:public|protected|private)\s+(?:static\s+)?[\w<>?,\[\].]+\s+([A-Za-z_][A-Za-z_0-9]*)\s*\(")


class CandidateError(ValueError):
    pass


def git(repo: str, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", repo, *args], capture_output=True, check=False)
    if result.returncode:
        raise CandidateError("固定提交无法读取")
    return result.stdout


def candidate(role: str, path: str, line: int, kind: str, expression: str, status: str) -> dict:
    return {
        "repository_id": role, "source_path": path, "line": line,
        "kind": kind, "expression": expression, "status": status,
        "anchor": f"{role}:{path}:{line}",
    }


def scan(repository_id: str, repository: dict, *, uniapp_manifest: str | None = None) -> dict:
    repo, revision = repository["path"], repository["commit"]
    commit = git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}").decode("ascii").strip()
    entries = [value for value in git(repo, "ls-tree", "-r", "-z", commit).split(b"\0") if value]
    if len(entries) > MAX_FILES:
        raise CandidateError("固定提交文件数量超过候选扫描上限")
    results = []
    for entry in entries:
        try:
            descriptor, encoded_path = entry.split(b"\t", 1)
            mode, kind, _ = descriptor.decode("ascii").split(" ")
            path = encoded_path.decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise CandidateError("Git 文件目录包含无效记录") from exc
        if mode not in {"100644", "100755"} or kind != "blob":
            continue
        if PurePosixPath(path).suffix not in SOURCE_SUFFIXES:
            continue
        raw = git(repo, "show", f"{commit}:{path}")
        if len(raw) > MAX_BYTES or b"\0" in raw:
            continue
        try:
            body = raw.decode("utf-8")
        except UnicodeError:
            continue
        for number, line in enumerate(body.splitlines(), start=1):
            if path.endswith(".java"):
                for match in JAVA_ANNOTATION.finditer(line):
                    literal = JAVA_LITERAL.search(match[1])
                    simple_literal = bool(literal and re.fullmatch(r"\s*(?:(?:value|path)\s*=\s*)?\"[^\"]+\"\s*", match[1]))
                    results.append(candidate(repository_id, path, number, "java_route", literal[1] if simple_literal else match[1].strip(), "candidate" if simple_literal else "unresolved"))
                match = METHOD.search(line)
                if match:
                    results.append(candidate(repository_id, path, number, "java_method", match[1], "candidate"))
            else:
                for match in TS_LITERAL.finditer(line):
                    dynamic_template = match[1] == "`" and "${" in match[2]
                    results.append(candidate(repository_id, path, number, "typescript_path", match[2], "unresolved" if dynamic_template else "candidate"))
                for match in TS_DYNAMIC.finditer(line):
                    results.append(candidate(repository_id, path, number, "typescript_dynamic_path", match[1].strip(), "unresolved"))
    if uniapp_manifest:
        routes = read_uniapp_pages(repository, uniapp_manifest)
        raw = git(repo, "show", f"{commit}:{uniapp_manifest}")
        try:
            manifest_text = raw.decode("utf-8")
        except UnicodeError as exc:
            raise CandidateError("UniApp 页面清单不是 UTF-8") from exc
        for route in sorted(routes):
            parts = route.split("/")
            line_number = None
            for offset in range(len(parts)):
                needle = "/".join(parts[offset:])
                matches = [number for number, line in enumerate(manifest_text.splitlines(), 1) if f'"{needle}"' in line]
                if len(matches) == 1:
                    line_number = matches[0]
                    break
            if line_number is None:
                results.append(candidate(repository_id, uniapp_manifest, 1, "uniapp_route", route, "unresolved"))
            else:
                results.append(candidate(repository_id, uniapp_manifest, line_number, "uniapp_route", route, "candidate"))
    results.sort(key=lambda item: (item["source_path"], item["line"], item["kind"], item["expression"]))
    return {
        "schema_version": "0.1", "repository_id": repository_id, "commit": commit,
        "capability": "deterministic_candidates_only", "candidates": results,
        "unresolved": sum(item["status"] == "unresolved" for item in results),
    }
