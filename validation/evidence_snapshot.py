"""Rebuild a precise source excerpt from a configured, fixed Git commit."""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath
import re
import subprocess


ANCHOR = re.compile(r"([a-z][a-z0-9_-]*):(.+):([1-9][0-9]*)(?:-([1-9][0-9]*))?\Z")
OID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
FIELDS = {"repository_id", "commit", "path", "line_start", "line_end", "snippet_sha256", "blob_oid"}


class EvidenceError(ValueError):
    pass


def safe_path(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and path.as_posix() == value and all(
        part not in {"", ".", ".."} for part in path.parts
    ) and "\\" not in value and ":" not in value


def git(repo: str, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", repo, *args], capture_output=True, check=False)
    if result.returncode:
        raise EvidenceError("固定提交中的源码对象无法读取")
    return result.stdout


def parse_anchor(anchor: str) -> tuple[str, str, int, int]:
    match = ANCHOR.fullmatch(anchor)
    if not match:
        raise EvidenceError("源码锚点格式无效")
    role, path, first, last = match.groups()
    if not safe_path(path):
        raise EvidenceError("源码锚点路径不安全")
    start = int(first)
    end = int(last or first)
    if end < start:
        raise EvidenceError("源码锚点行段倒序")
    return role, path, start, end


def snapshot(anchor: str, repositories: dict) -> dict:
    role, path, start, end = parse_anchor(anchor)
    settings = repositories.get(role)
    if not isinstance(settings, dict) or not settings.get("path") or not settings.get("commit"):
        raise EvidenceError("源码锚点仓库未配置")
    repo = settings["path"]
    commit = git(repo, "rev-parse", "--verify", f"{settings['commit']}^{{commit}}").decode("ascii").strip()
    listing = git(repo, "ls-tree", "-z", commit, "--", path)
    rows = [row for row in listing.split(b"\0") if row]
    if len(rows) != 1:
        raise EvidenceError("固定提交中找不到唯一源码文件")
    try:
        descriptor, listed_path = rows[0].split(b"\t", 1)
        mode, kind, oid = descriptor.decode("ascii").split(" ")
        actual_path = listed_path.decode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise EvidenceError("Git 源码对象信息无效") from exc
    if actual_path != path or mode not in {"100644", "100755"} or kind != "blob" or not OID.fullmatch(oid):
        raise EvidenceError("源码路径指向非普通文本文件")
    raw = git(repo, "cat-file", "blob", oid)
    if b"\0" in raw:
        raise EvidenceError("源码对象不是文本文件")
    try:
        raw.decode("utf-8")
    except UnicodeError as exc:
        raise EvidenceError("源码对象不是 UTF-8 文本") from exc
    lines = raw.splitlines(keepends=True)
    if end > len(lines):
        raise EvidenceError("源码锚点行号越界")
    return {
        "repository_id": role,
        "commit": commit,
        "path": path,
        "line_start": start,
        "line_end": end,
        "snippet_sha256": hashlib.sha256(b"".join(lines[start - 1:end])).hexdigest(),
        "blob_oid": oid,
    }


def verify(record: dict, repositories: dict) -> None:
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise EvidenceError("证据快照字段无效")
    if (not isinstance(record["commit"], str) or not OID.fullmatch(record["commit"])
        or not isinstance(record["repository_id"], str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", record["repository_id"])
        or not isinstance(record["blob_oid"], str) or not OID.fullmatch(record["blob_oid"])
        or not isinstance(record["snippet_sha256"], str) or not SHA256.fullmatch(record["snippet_sha256"])
        or type(record["line_start"]) is not int or type(record["line_end"]) is not int
        or record["line_start"] < 1 or record["line_end"] < record["line_start"]
        or not isinstance(record["path"], str) or not safe_path(record["path"])):
        raise EvidenceError("证据快照身份无效")
    anchor = f"{record['repository_id']}:{record['path']}:{record['line_start']}-{record['line_end']}"
    current = snapshot(anchor, repositories)
    if current != record:
        raise EvidenceError("证据快照与当前固定提交不一致；先预览影响并重新取证")
