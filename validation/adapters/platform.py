"""Opt-in candidate schema for fixed-commit, mixed-language inventories.

This adapter reports evidence locations and conservative candidates. It never
promotes a lexical match or a route-name match to a verified relationship.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
from pathlib import PurePosixPath

from .ts_java import MAX_FILES, scan as legacy_scan, git as fixed_git
from .uniapp_pages import read_uniapp_pages
from .sdk import validate_result


ADAPTER_VERSION = "0.1"
SCHEMA_VERSION = "0.2"
MANIFESTS = {
    "builtin-mixed": {"name": "builtin-mixed", "version": ADAPTER_VERSION,
                      "capabilities": ["L1:text-file-inventory", "L2:uniapp-pages-json", "candidate:ts-java-lexical"]},
    "universal-l1": {"name": "universal-l1", "version": ADAPTER_VERSION,
                     "capabilities": ["L1:text-file-inventory"]},
}
MAX_BYTES = 1024 * 1024
LANGUAGES = {
    ".ts": "typescript", ".tsx": "typescript", ".js": "javascript", ".jsx": "javascript",
    ".vue": "vue", ".java": "java", ".php": "php", ".py": "python", ".go": "go",
    ".rs": "rust", ".rb": "ruby", ".kt": "kotlin", ".swift": "swift", ".cs": "csharp",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp",
    ".sh": "shell", ".bash": "shell", ".sql": "sql", ".html": "html", ".css": "css",
    ".yaml": "yaml", ".yml": "yaml", ".json": "json", ".toml": "toml",
}
EXCLUDED_DIRS = {"node_modules", "vendor", "dist", "build", "target", ".git", ".next"}


def identity(*parts: object) -> str:
    text = "\0".join(str(part) for part in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def _files(repo: str, commit: str, scope: str | None) -> tuple[list[tuple[str, int]], Counter]:
    entries = [entry for entry in fixed_git(repo, "ls-tree", "-r", "-l", "-z", commit).split(b"\0") if entry]
    selected: list[tuple[str, int]] = []
    skipped = Counter()
    in_scope = 0
    for entry in entries:
        try:
            descriptor, encoded = entry.split(b"\t", 1)
            mode, kind, _, size = descriptor.decode("ascii").split()
            path = encoded.decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise ValueError("固定提交目录包含无效记录") from exc
        if scope and path != scope and not path.startswith(scope.rstrip("/") + "/"):
            continue
        in_scope += 1
        if in_scope > MAX_FILES:
            raise ValueError("所选范围文件数量超过 Adapter 扫描上限")
        if mode not in {"100644", "100755"} or kind != "blob":
            skipped["non_regular"] += 1
            continue
        if EXCLUDED_DIRS.intersection(PurePosixPath(path).parts):
            skipped["generated_or_dependency"] += 1
            continue
        if size == "-" or int(size) == 0 or int(size) > MAX_BYTES:
            skipped["empty_or_large"] += 1
            continue
        selected.append((path, int(size)))
    return selected, skipped


def scan(repository_id: str, repository: dict, *, scope: str | None = None, uniapp_manifest: str | None = None,
         adapter_name: str = "builtin-mixed") -> dict:
    if adapter_name not in MANIFESTS:
        raise ValueError(f"未知内置 Adapter：{adapter_name}")
    if adapter_name == "universal-l1" and uniapp_manifest:
        raise ValueError("universal-l1 不解析 UniApp 页面清单")
    if scope is not None and (not scope or scope.startswith("/") or "\\" in scope or any(part in {"", ".", ".."} for part in scope.split("/"))):
        raise ValueError("扫描范围必须是安全的仓库相对路径")
    repo, revision = repository["path"], repository["commit"]
    commit = fixed_git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}").decode("ascii").strip()
    selected, skipped = _files(repo, commit, scope)
    candidates = []
    accepted = set()
    for path, _ in selected:
        raw = fixed_git(repo, "show", f"{commit}:{path}")
        if b"\0" in raw:
            skipped["binary"] += 1
            continue
        try:
            raw.decode("utf-8")
        except UnicodeError:
            skipped["non_utf8"] += 1
            continue
        accepted.add(path)
        candidates.append({
            "candidate_id": identity(repository_id, path, "file"),
            "repository_id": repository_id, "source_path": path, "line": 1,
            "kind": "source_file", "language": LANGUAGES.get(PurePosixPath(path).suffix.lower(), "unknown"),
            "expression": path, "status": "candidate", "capability": "L1",
            "rule_id": "text-file-inventory", "rule_version": ADAPTER_VERSION,
            "anchor": f"{repository_id}:{path}:1", "unresolved_reason": None,
        })
    old = legacy_scan(repository_id, repository, uniapp_manifest=uniapp_manifest, scope=scope) if adapter_name == "builtin-mixed" else {"candidates": []}
    occurrences = Counter()
    for item in old["candidates"]:
        path = item["source_path"]
        if path not in accepted or scope and path != scope and not path.startswith(scope.rstrip("/") + "/"):
            continue
        key = (path, item["kind"], item["expression"])
        occurrences[key] += 1
        route = item["kind"] == "uniapp_route"
        candidates.append({
            "candidate_id": identity(repository_id, *key, occurrences[key]),
            **item,
            "language": "vue" if route else LANGUAGES.get(PurePosixPath(path).suffix.lower(), "unknown"),
            "capability": "L2" if route else "L1",
            "rule_id": "uniapp-pages-json" if route else "lexical-route-or-method",
            "rule_version": ADAPTER_VERSION,
            "unresolved_reason": "dynamic_or_ambiguous_expression" if item["status"] == "unresolved" else None,
        })
    # Equal path literals across the two languages are discovery hints only.
    frontend = [item for item in candidates if item["kind"] == "typescript_path" and item["status"] == "candidate"]
    backend = defaultdict(list)
    for item in candidates:
        if item["kind"] == "java_route" and item["status"] == "candidate":
            backend[item["expression"]].append(item)
    edges = []
    for left in frontend:
        for right in backend[left["expression"]]:
            edges.append({"edge_id": identity(left["candidate_id"], right["candidate_id"]),
                          "from_candidate_id": left["candidate_id"], "to_candidate_id": right["candidate_id"],
                          "status": "candidate", "basis": "equal_literal_path_only",
                          "evidence": [left["anchor"], right["anchor"]], "unresolved_reason": None})
    candidates.sort(key=lambda item: (item["source_path"], item["line"], item["kind"], item["expression"]))
    edges.sort(key=lambda item: item["edge_id"])
    return validate_result({
        "schema_version": SCHEMA_VERSION,
        "adapter": MANIFESTS[adapter_name],
        "snapshot": {"repository_id": repository_id, "commit": commit, "scope": scope},
        "coverage": {"text_files": len(accepted), "skipped": dict(sorted(skipped.items()))},
        "candidates": candidates, "edges": edges,
        "unresolved": sum(item["status"] == "unresolved" for item in candidates),
    })


class BuiltinMixedAdapter:
    name = "builtin-mixed"
    version = ADAPTER_VERSION

    def inventory_entries(self, repository: dict, manifest_path: str) -> set[str]:
        return read_uniapp_pages(repository, manifest_path)

    def scan(self, repository_id: str, repository: dict, *, scope: str | None = None,
             uniapp_manifest: str | None = None) -> dict:
        return scan(repository_id, repository, scope=scope, uniapp_manifest=uniapp_manifest, adapter_name=self.name)


class UniversalL1Adapter(BuiltinMixedAdapter):
    name = "universal-l1"
