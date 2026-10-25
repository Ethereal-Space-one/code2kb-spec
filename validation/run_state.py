"""Local execution locks and recoverable multi-file governance writes.

The state directory is deliberately outside the knowledge source and release
trees. It is an execution journal, not a source of approval or content truth.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import uuid


SCHEMA = "0.1"
_active_transaction: ContextVar["GovernanceTransaction | None"] = ContextVar("code2kb_transaction", default=None)
_held_project_lock: ContextVar[Path | None] = ContextVar("code2kb_project_lock", default=None)


class ProjectLockConflict(ValueError):
    code = "E_CONFLICT"


class RecoveryRequired(ValueError):
    code = "E_RECOVERY_REQUIRED"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _save_json(path: Path, value: dict) -> None:
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(prefix=f".{path.name}-", dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def state_root(project: Path) -> Path:
    root = project / ".code2kb"
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise ValueError("执行状态目录不能是符号链接或普通文件")
    root.mkdir(mode=0o700, exist_ok=True)
    return root


@contextmanager
def project_lock(project: Path):
    """Serialize supported writers on one local Unix host.

    A persistent lock file avoids inode replacement races. flock releases the
    lock automatically if the process dies, while transaction journals remain.
    """
    resolved = project.resolve()
    if _held_project_lock.get() == resolved:
        yield
        return
    root = state_root(project)
    path = root / "project.lock"
    if path.is_symlink():
        raise ValueError("项目锁不能是符号链接")
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ProjectLockConflict("知识项目正由另一修改任务使用；稍后重试") from exc
        token = _held_project_lock.set(resolved)
        try:
            yield
        finally:
            _held_project_lock.reset(token)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _journal_root(project: Path) -> Path:
    root = state_root(project) / "transactions"
    if root.is_symlink():
        raise ValueError("事务目录不能是符号链接")
    root.mkdir(mode=0o700, exist_ok=True)
    return root


def pending_transactions(project: Path) -> list[Path]:
    entries = list(_journal_root(project).iterdir())
    if any(path.is_symlink() for path in entries):
        raise ValueError("事务目录包含符号链接，拒绝恢复")
    return sorted(path for path in entries if path.is_dir())


def require_recovered(project: Path) -> None:
    pending = pending_transactions(project)
    if pending:
        raise RecoveryRequired("存在未完成的文件事务；先执行 recover --project-root 再继续修改")


class GovernanceTransaction:
    """Journal the before image and intended digest before each file write."""

    def __init__(self, project: Path, module_dir: Path, action: str):
        self.project = project
        self.module_dir = module_dir
        self.action = action
        self.path: Path | None = None
        self.record: dict = {}
        self.token = None

    def __enter__(self):
        require_recovered(self.project)
        root = _journal_root(self.project)
        self.path = root / f"governance-{uuid.uuid4().hex}"
        self.path.mkdir(mode=0o700)
        (self.path / "before").mkdir(mode=0o700)
        self.record = {"schema_version": SCHEMA, "kind": "governance", "action": self.action,
                       "module_dir": self.module_dir.relative_to(self.project).as_posix(),
                       "owner_pid": os.getpid(), "owner_host": socket.gethostname(), "files": {}}
        _save_json(self.path / "journal.json", self.record)
        self.token = _active_transaction.set(self)
        return self

    def before_write(self, path: Path, data: bytes) -> None:
        assert self.path is not None
        try:
            local = path.relative_to(self.project).as_posix()
            path.relative_to(self.module_dir)
        except ValueError as exc:
            raise ValueError("治理事务写入超出当前模块") from exc
        if path.is_symlink():
            raise ValueError("治理事务不能写入符号链接")
        files = self.record["files"]
        if local not in files:
            existed = path.is_file()
            before = path.read_bytes() if existed else b""
            backup = self.path / "before" / f"{len(files):04d}.bin"
            with backup.open("xb") as stream:
                stream.write(before)
                stream.flush()
                os.fsync(stream.fileno())
            files[local] = {"existed": existed, "before_sha256": _digest(before),
                            "before_file": backup.name, "after_sha256": _digest(data)}
        else:
            files[local]["after_sha256"] = _digest(data)
        _save_json(self.path / "journal.json", self.record)

    def __exit__(self, exc_type, exc, traceback):
        assert self.path is not None and self.token is not None
        _active_transaction.reset(self.token)
        if exc_type is not None:
            recover_governance(self.project, self.path)
        else:
            shutil.rmtree(self.path)
        return False


def record_governance_write(path: Path, data: bytes) -> None:
    transaction = _active_transaction.get()
    if transaction is not None:
        transaction.before_write(path, data)


def recover_governance(project: Path, journal_dir: Path) -> dict:
    journal_path = journal_dir / "journal.json"
    if journal_path.is_symlink():
        raise ValueError("治理事务记录不能是符号链接")
    record = json.loads(journal_path.read_text(encoding="utf-8"))
    if set(record) != {"schema_version", "kind", "action", "module_dir", "owner_pid", "owner_host", "files"} or record["schema_version"] != SCHEMA or record["kind"] != "governance" or not isinstance(record["files"], dict):
        raise ValueError("治理事务记录无效，拒绝自动恢复")
    paths = []
    module = project / record["module_dir"]
    if module.is_symlink() or not module.resolve().is_relative_to(project.resolve()):
        raise ValueError("治理事务模块路径无效，拒绝自动恢复")
    for local, item in record["files"].items():
        path = project / local
        if not isinstance(item, dict) or set(item) != {"existed", "before_sha256", "before_file", "after_sha256"} or path.is_symlink() or not path.resolve().is_relative_to(module.resolve()) or not item["before_file"].endswith(".bin") or Path(item["before_file"]).name != item["before_file"]:
            raise ValueError("治理事务文件路径或记录无效，拒绝自动恢复")
        backup_path = journal_dir / "before" / item["before_file"]
        if backup_path.is_symlink() or (journal_dir / "before").is_symlink():
            raise ValueError("治理事务备份不能是符号链接")
        before = backup_path.read_bytes()
        if _digest(before) != item["before_sha256"]:
            raise ValueError("治理事务原始文件摘要不匹配，拒绝自动恢复")
        actual = path.read_bytes() if path.is_file() else None
        allowed = {before if item["existed"] else None}
        if actual is not None and _digest(actual) == item["after_sha256"]:
            allowed.add(actual)
        if actual not in allowed:
            raise ValueError(f"治理事务期间文件出现外部变更，拒绝覆盖：{local}")
        paths.append((path, item["existed"], before))
    for path, existed, before in reversed(paths):
        temp = path.with_name(path.name + ".tmp")
        if temp.is_file() and not temp.is_symlink():
            temp.unlink()
        if existed:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}-", delete=False) as stream:
                replacement = Path(stream.name)
                stream.write(before)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(replacement, path)
        elif path.exists():
            path.unlink()
    shutil.rmtree(journal_dir)
    return {"kind": "governance", "action": record["action"], "result": "rolled_back", "files": len(paths)}


def recover_pending(project: Path, audit=None) -> list[dict]:
    results = []
    for path in pending_transactions(project):
        if path.name.startswith("publish-") and not (path / "journal.json").exists() and not list(path.iterdir()):
            shutil.rmtree(path)
            results.append({"kind": "publish", "result": "discarded_empty_journal"})
            continue
        if path.name.startswith("governance-"):
            children = sorted(path.rglob("*"))
            if not (path / "journal.json").exists() and (not children or children == [path / "before"]):
                shutil.rmtree(path)
                results.append({"kind": "governance", "result": "discarded_empty"})
                continue
            results.append(recover_governance(project, path))
        elif path.name.startswith("publish-") and audit is not None:
            results.append(recover_publish(project, path, audit))
        else:
            raise ValueError(f"未知或未完成的事务，需要人工检查：{path.name}")
    return results


class PublishTransaction:
    """Journal a directory replacement across process death."""

    def __init__(self, project: Path, staging: Path, release_id: str):
        self.project = project
        self.staging = staging
        self.path = _journal_root(project) / f"publish-{uuid.uuid4().hex}"
        pointer = project / "发布" / "当前版本.json"
        stage_release = staging / "发布"
        critical = ["当前版本.json", f"版本清单/{release_id}.json"]
        for pointer_name, manifest_dir in (("当前检索版本.json", "检索清单"), ("当前关系版本.json", "关系清单")):
            if (stage_release / pointer_name).is_file():
                critical.extend([pointer_name, f"{manifest_dir}/{release_id}.json"])
        expected = {}
        for local in critical:
            path = stage_release / local
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"发布暂存的关键文件无效：{local}")
            expected[local] = _digest(path.read_bytes())
        self.record = {
            "schema_version": SCHEMA, "kind": "publish", "release_id": release_id,
            "staging": staging.relative_to(project).as_posix(),
            "old_pointer_sha256": _digest(pointer.read_bytes()) if pointer.is_file() else None,
            "expected_files": expected,
        }
        self.path.mkdir(mode=0o700)
        _save_json(self.path / "journal.json", self.record)

    def finish(self) -> None:
        shutil.rmtree(self.path)


def _publish_paths(project: Path, record: dict) -> tuple[Path, Path, Path]:
    if set(record) != {"schema_version", "kind", "release_id", "staging", "old_pointer_sha256", "expected_files"} or record["schema_version"] != SCHEMA or record["kind"] != "publish" or not isinstance(record["expected_files"], dict):
        raise ValueError("发布事务记录无效")
    local = record["staging"]
    if not isinstance(local, str) or not local.startswith(".发布待替换-") or Path(local).name != local:
        raise ValueError("发布事务暂存路径无效")
    staging = project / local
    if staging.is_symlink() or (staging / "发布").is_symlink() or (staging / "原发布").is_symlink() or (project / "发布").is_symlink() or not staging.resolve().is_relative_to(project.resolve()):
        raise ValueError("发布事务暂存目录不安全")
    return project / "发布", staging / "发布", staging / "原发布"


def recover_publish(project: Path, journal_dir: Path, audit) -> dict:
    if (journal_dir / "journal.json").is_symlink():
        raise ValueError("发布事务记录不能是符号链接")
    record = json.loads((journal_dir / "journal.json").read_text(encoding="utf-8"))
    current, staged, backup = _publish_paths(project, record)
    pointer = current / "当前版本.json"
    old_digest = record["old_pointer_sha256"]
    current_bytes = pointer.read_bytes() if pointer.is_file() else None
    old_current = current_bytes is not None and old_digest is not None and _digest(current_bytes) == old_digest
    new_current = False
    if current_bytes is not None:
        try:
            new_current = json.loads(current_bytes).get("release_id") == record["release_id"]
        except (ValueError, TypeError, AttributeError):
            pass
    if new_current:
        try:
            for local, expected_sha in record["expected_files"].items():
                candidate = current / local
                if not isinstance(expected_sha, str) or len(expected_sha) != 64 or ".." in Path(local).parts or Path(local).is_absolute() or candidate.is_symlink() or not candidate.is_file() or _digest(candidate.read_bytes()) != expected_sha:
                    raise ValueError(f"新发布关键文件与事务记录不一致：{local}")
            audit(record["release_id"])
        except Exception:
            if not backup.is_dir():
                raise ValueError("新发布审计失败且无旧版备份，保留现场供人工处理")
            if staged.exists():
                raise ValueError("新发布审计失败且暂存路径冲突，保留现场供人工处理")
            os.replace(current, staged)
            os.replace(backup, current)
            audit(None)
            result = "restored_previous"
        else:
            result = "completed_new_release"
    elif old_current:
        if backup.exists():
            raise ValueError("旧版仍在当前目录但备份也存在，拒绝猜测发布状态")
        audit(None)
        result = "kept_previous"
    elif not current.exists() and backup.is_dir():
        old_pointer = backup / "当前版本.json"
        if old_digest is None or not old_pointer.is_file() or _digest(old_pointer.read_bytes()) != old_digest:
            raise ValueError("旧版备份指针不匹配，拒绝恢复")
        os.replace(backup, current)
        audit(None)
        result = "restored_previous"
    elif not current.exists() and old_digest is None:
        result = "kept_unpublished"
    else:
        raise ValueError("发布目录与事务记录冲突，保留现场供人工处理")
    shutil.rmtree(staged.parent, ignore_errors=True)
    shutil.rmtree(journal_dir)
    return {"kind": "publish", "release_id": record["release_id"], "result": result}
