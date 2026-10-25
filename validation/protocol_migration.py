"""Explicit, single-file migration of a knowledge project's working config.

Preview is read-only, including for projects with no execution state directory.
Existing release artifacts and run ledgers are never rewritten.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

try:
    from . import protocol, run_state
except ImportError:
    import protocol
    import run_state


VERSION_FIELD = re.compile(rb'("standard_version"\s*:\s*)"0\.8\.3"')


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(project: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True)
    if result.returncode:
        raise ValueError("协议迁移需要有提交的独立知识项目 Git 仓库")
    return result.stdout.strip()


def _release_digest(project: Path) -> str:
    release = project / "发布"
    if release.is_symlink():
        raise ValueError("发布目录不能是符号链接")
    values = []
    if release.exists():
        for path in sorted(release.rglob("*")):
            if path.is_symlink():
                raise ValueError("发布目录含符号链接")
            if path.is_file():
                values.append((path.relative_to(release).as_posix(), _hash(path.read_bytes())))
    return _hash(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _execution_state(project: Path) -> None:
    state = project / ".code2kb"
    if state.is_symlink() or (state.exists() and not state.is_dir()):
        raise ValueError("执行状态目录无效")
    for name in ("transactions", "runs"):
        folder = state / name
        if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
            raise ValueError("执行状态子目录无效")
    transactions = state / "transactions"
    if transactions.is_dir() and any(transactions.iterdir()):
        raise ValueError("存在未完成事务；先恢复后再迁移协议")
    runs = state / "runs"
    if runs.is_dir():
        for path in sorted(runs.iterdir()):
            if path.is_symlink() or not path.is_dir():
                raise ValueError("运行账本目录无效")
            ledger = path / "run.json"
            if ledger.is_symlink() or not ledger.is_file():
                raise ValueError("运行账本文件缺失或无效")
            try:
                record = json.loads(ledger.read_text(encoding="utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError("运行账本无法解析") from exc
            if not isinstance(record, dict) or record.get("status") not in {"active", "cancelled"} or not isinstance(record.get("tasks"), list):
                raise ValueError("运行账本结构无效")
            if record["status"] == "active" and not all(isinstance(task, dict) and task.get("status") == "completed" for task in record["tasks"]):
                raise ValueError(f"运行 {path.name} 尚未完成；先完成或取消，再创建新运行")


def preview(project: Path) -> dict:
    project = project.resolve(strict=True)
    config_path = project / "知识库配置.json"
    if config_path.is_symlink() or not config_path.is_file():
        raise ValueError("知识库配置必须是普通文件")
    if Path(_git(project, "rev-parse", "--show-toplevel")).resolve() != project:
        raise ValueError("协议迁移需要独立的知识项目 Git 仓库")
    changes = _git(project, "status", "--porcelain", "--untracked-files=all").splitlines()
    if any(not line.startswith("?? .code2kb/") for line in changes):
        raise ValueError("知识项目工作区不干净；先审阅并提交或清理改动")
    _execution_state(project)
    before = config_path.read_bytes()

    def no_duplicates(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError(f"知识库配置包含重复字段：{key}")
            value[key] = item
        return value

    try:
        config = json.loads(before.decode("utf-8"), object_pairs_hook=no_duplicates)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("知识库配置不是有效 UTF-8 JSON") from exc
    if not isinstance(config, dict) or config.get("standard_version") != protocol.LEGACY_VERSION:
        raise ValueError(f"仅支持从 {protocol.LEGACY_VERSION} 显式迁移")
    # Published or already approved files remain untouched. Their review
    # snapshot is tied to the old project context and must be prepared anew.
    source_name = config.get("knowledge_source_root")
    if not isinstance(source_name, str) or not source_name or Path(source_name).is_absolute() or ".." in Path(source_name).parts:
        raise ValueError("知识源目录无效")
    source = project / source_name
    if source.is_symlink() or not source.is_dir() or not source.resolve().is_relative_to(project):
        raise ValueError("知识源目录无效")
    draft_packages = []
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError("知识源包含符号链接")
        if not path.is_file() or path.suffix != ".md":
            continue
        body = path.read_text(encoding="utf-8")
        if re.search(r"(?m)^review_status:\s*(reviewed|policy_reviewed)\s*$", body):
            raise ValueError("存在已批准发布包；先完成旧版发布或将包重新准备为 draft")
        if path.name == "发布清单.md" and re.search(r"(?m)^review_status:\s*draft\s*$", body):
            draft_packages.append(path.relative_to(project).as_posix())
    after, count = VERSION_FIELD.subn(rb'\g<1>"' + protocol.DEFAULT_VERSION.encode("ascii") + b'"', before)
    if count != 1:
        raise ValueError("配置中的旧协议编号无法无损替换；请检查 standard_version 写法")
    baseline = {
        "from": protocol.LEGACY_VERSION, "to": protocol.DEFAULT_VERSION,
        "git_head": _git(project, "rev-parse", "HEAD"),
        "before_sha256": _hash(before), "after_sha256": _hash(after),
        "release_sha256": _release_digest(project),
    }
    plan_sha256 = _hash(json.dumps(baseline, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return {"plan_sha256": plan_sha256, "files": [{"path": "知识库配置.json", "before_sha256": baseline["before_sha256"], "after_sha256": baseline["after_sha256"]}],
            "from": baseline["from"], "to": baseline["to"], "release_sha256": baseline["release_sha256"],
            "draft_packages_to_refresh": sorted(draft_packages), "after": after}


def apply(project: Path, expected_plan_sha256: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_plan_sha256):
        raise ValueError("--plan-sha256 必须是预演返回的 SHA-256")
    with run_state.project_lock(project):
        run_state.require_recovered(project)
        current = preview(project)
        if current["plan_sha256"] != expected_plan_sha256:
            raise ValueError("迁移预演已过期；重新预演并核对差异")
        target = project / "知识库配置.json"
        if target.is_symlink() or _hash(target.read_bytes()) != current["files"][0]["before_sha256"]:
            raise ValueError("迁移预演已过期；配置在核对后发生变化")
        with tempfile.NamedTemporaryFile(prefix=".protocol-migration-", dir=project, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(current["after"])
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
    return {key: value for key, value in current.items() if key != "after"}
