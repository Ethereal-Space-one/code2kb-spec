"""Recoverable local task contracts for Code2KB knowledge projects.

The ledger coordinates work; project documents, Git and release audits remain
authoritative. No task completion is an approval grant.
"""

from __future__ import annotations

from datetime import datetime, timezone
import contextlib
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys

try:
    from . import run_state
except ImportError:
    import run_state


SCHEMA = "0.1"
RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,119}\Z")
STATES = {"pending", "running", "waiting_review", "blocked", "failed", "completed", "cancelled"}
EXTERNAL = {"writer", "business_intent", "reviewer", "checkpoint", "approval", "commit_inputs", "publish"}
AUTOMATED = {"inventory", "confirm_claims", "prepare", "audit"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(project: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True)
    if result.returncode:
        raise ValueError("运行账本需要独立且有提交的知识项目 Git 仓库")
    return result.stdout.strip()


def _verify_sources(project: Path) -> None:
    project = project.resolve()
    try:
        from . import knowledge as cli
    except ImportError:
        import knowledge as cli
    try:
        _, config = cli.read_config(project)
        cli.verify_repos(config)
    except cli.KnowledgeError as exc:
        raise ValueError(str(exc)) from exc


def _paths(project: Path) -> dict[str, str]:
    """Digest tracked and non-ignored untracked files without reading Git internals."""
    result = subprocess.run(["git", "-C", str(project), "ls-files", "--cached", "--others", "--exclude-standard", "-z"], capture_output=True)
    if result.returncode:
        raise ValueError("无法盘点知识项目文件")
    values = {}
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        local = raw.decode("utf-8")
        if local.startswith(".code2kb/"):
            continue
        path = project / local
        if path.is_symlink() or not path.resolve().is_relative_to(project.resolve()):
            raise ValueError(f"任务文件不能是符号链接：{local}")
        if path.is_file():
            values[local] = _digest(path.read_bytes())
    return values


def _task(task_id: str, kind: str, module_id: str | None, allowed: list[str], dependencies: list[str]) -> dict:
    return {"task_id": task_id, "kind": kind, "module_id": module_id,
            "depends_on": dependencies, "allowed_write_set": allowed,
            "status": "pending", "attempt": 0, "started_at": None, "completed_at": None,
            "actor": None, "note_digest": None, "git_head_before": None, "git_head_after": None,
            "before_files": None, "changed_files": [], "result_sha256": None, "blocked_reason": None}


def _run_file(project: Path, run_id: str) -> Path:
    if not RUN_ID.fullmatch(run_id):
        raise ValueError("run_id 须为 3–120 位安全标识")
    root = run_state.state_root(project) / "runs"
    if root.is_symlink():
        raise ValueError("运行账本目录不能是符号链接")
    root.mkdir(exist_ok=True)
    return root / run_id / "run.json"


def _module_location(project: Path, domain: str, name: str) -> Path:
    if any(not part or part in {".", ".."} or "/" in part or "\\" in part or "\x00" in part for part in (domain, name)):
        raise ValueError("功能大纲中的业务域或模块目录不安全")
    source = project / "知识源"
    location = source / domain / name
    if source.is_symlink() or (source / domain).is_symlink() or location.is_symlink() or not location.resolve().is_relative_to(source.resolve()):
        raise ValueError("功能大纲模块目录不能穿越知识源")
    return location


def create(project: Path, run_id: str, modules: dict[str, tuple[str, str, str]], selected: list[str],
           release_id: str, batch_size: int = 5, include_business_intent: bool = False,
           retrieval_suite: Path | None = None, entries: list[tuple[str, str, str, str, str, str]] | None = None) -> dict:
    if not 1 <= batch_size <= 20:
        raise ValueError("批次大小须在 1–20 之间")
    if not selected or len(selected) != len(set(selected)) or set(selected) - set(modules):
        raise ValueError("运行模块须在功能大纲中逐项列名且不能重复")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", release_id):
        raise ValueError("运行发布 ID 无效")
    if retrieval_suite is not None and not retrieval_suite.is_file():
        raise ValueError("检索评测套件文件不存在")
    path = _run_file(project, run_id)
    if path.parent.exists():
        raise ValueError("run_id 已存在，不得覆盖运行账本")
    head = _git(project, "rev-parse", "HEAD")
    if Path(_git(project, "rev-parse", "--show-toplevel")).resolve() != project.resolve():
        raise ValueError("运行账本需要独立的知识项目 Git 仓库")
    tasks = []

    def append(task_id, kind, module_id=None, allowed=None, deps=None):
        tasks.append(_task(task_id, kind, module_id, allowed or [], deps or []))

    append("inventory", "inventory")
    batch_gate = "inventory"
    batch_prepared = []
    for index, module_id in enumerate(selected, 1):
        domain, name, _ = modules[module_id]
        _module_location(project, domain, name)
        root = f"知识源/{domain}/{name}/"
        append(f"{module_id}:writer", "writer", module_id, [root, "知识源/功能大纲.md", f"运行证据/{domain}/{name}/"], [batch_gate])
        review_dependency = f"{module_id}:writer"
        if include_business_intent:
            review_dependency = f"{module_id}:business-intent"
            append(review_dependency, "business_intent", module_id, [root, f"运行证据/{domain}/{name}/"], [f"{module_id}:writer"])
        append(f"{module_id}:reviewer", "reviewer", module_id, deps=[review_dependency])
        append(f"{module_id}:confirm", "confirm_claims", module_id, [root], [f"{module_id}:reviewer"])
        append(f"{module_id}:prepare", "prepare", module_id, [root], [f"{module_id}:confirm"])
        batch_prepared.append(f"{module_id}:prepare")
        if index % batch_size == 0 or index == len(selected):
            batch_gate = f"batch-{(index - 1) // batch_size + 1}:checkpoint"
            append(batch_gate, "checkpoint", deps=batch_prepared)
            batch_prepared = []
    approvals = []
    for module_id in selected:
        domain, name, _ = modules[module_id]
        _module_location(project, domain, name)
        approval_id = f"{module_id}:approval"
        append(approval_id, "approval", module_id, [f"知识源/{domain}/{name}/"], [f"{module_id}:prepare", batch_gate])
        approvals.append(approval_id)
    append("commit-inputs", "commit_inputs", deps=approvals)
    append("publish", "publish", allowed=["发布/"], deps=["commit-inputs"])
    append("audit", "audit", deps=["publish"])
    record = {"schema_version": SCHEMA, "run_id": run_id, "release_id": release_id,
              "created_at": _now(), "project": str(project.resolve()), "initial_git_head": head,
              "status": "active", "config_sha256": _digest((project / "知识库配置.json").read_bytes()),
              "outline_sha256": _digest((project / "知识源" / "功能大纲.md").read_bytes()),
              "spec_baselines": {},
              "include_business_intent": include_business_intent,
              "retrieval_suite": str(retrieval_suite.resolve()) if retrieval_suite else None,
              "retrieval_suite_sha256": _digest(retrieval_suite.read_bytes()) if retrieval_suite else None,
              "inventory_summary": {"entries": len(entries),
                                    "unclassified": sum(entry[3] == "未归类" for entry in entries),
                                    "pending_review": sum(entry[5] == "待核查" for entry in entries)} if entries is not None else None,
              "modules": {module_id: list(modules[module_id]) for module_id in selected},
              "batch_size": batch_size, "tasks": tasks}
    path.parent.mkdir(mode=0o700)
    run_state._save_json(path, record)
    return summary(record)


def load(project: Path, run_id: str) -> dict:
    path = _run_file(project, run_id)
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict) or record.get("schema_version") != SCHEMA or record.get("run_id") != run_id or record.get("project") != str(project.resolve()) or record.get("status") not in {"active", "cancelled"} or not isinstance(record.get("tasks"), list) or not isinstance(record.get("modules"), dict) or not isinstance(record.get("spec_baselines"), dict) or not all(isinstance(record.get(key), str) and re.fullmatch(r"[0-9a-f]{64}", record[key]) for key in ("config_sha256", "outline_sha256")):
        raise ValueError("运行账本结构或所属项目无效")
    if any(not isinstance(module_id, str) or not isinstance(parts, list) or len(parts) != 3 or not all(isinstance(part, str) for part in parts) for module_id, parts in record["modules"].items()):
        raise ValueError("运行账本模块结构无效")
    if any(module_id not in record["modules"] or not isinstance(baseline, str) or not re.fullmatch(r"[0-9a-f]{64}", baseline) for module_id, baseline in record["spec_baselines"].items()):
        raise ValueError("运行账本规格基线无效")
    for domain, name, _ in record["modules"].values():
        _module_location(project, domain, name)
    required_task = {"task_id", "kind", "module_id", "depends_on", "allowed_write_set", "status", "attempt", "before_files", "blocked_reason"}
    if any(not isinstance(task, dict) or not required_task <= set(task) for task in record["tasks"]):
        raise ValueError("运行账本任务结构无效")
    ids = [task.get("task_id") for task in record["tasks"]]
    if any(not isinstance(value, str) for value in ids) or len(ids) != len(set(ids)) or any(task.get("status") not in STATES or task.get("kind") not in EXTERNAL | AUTOMATED or not isinstance(task.get("depends_on"), list) or not all(isinstance(value, str) for value in task["depends_on"]) or not isinstance(task.get("allowed_write_set"), list) or not all(isinstance(value, str) for value in task["allowed_write_set"]) or not set(task["depends_on"]) <= set(ids) for task in record["tasks"]):
        raise ValueError("运行账本任务 ID 或状态无效")
    return record


def _save(project: Path, record: dict) -> None:
    run_state._save_json(_run_file(project, record["run_id"]), record)


def _spec_path(project: Path, record: dict, module_id: str) -> Path:
    domain, name, _ = record["modules"][module_id]
    return _module_location(project, domain, name) / "结构化规格.md"


def _refresh_dependencies(project: Path, record: dict) -> list[str]:
    if record.get("status") == "cancelled" or all(task["status"] == "completed" for task in record["tasks"]):
        return []
    changed_providers = {
        module_id for module_id, baseline in record["spec_baselines"].items()
        if not _spec_path(project, record, module_id).is_file()
        or _digest(_spec_path(project, record, module_id).read_bytes()) != baseline
    }
    if not changed_providers:
        return []
    result = subprocess.run([sys.executable, str(Path(__file__).with_name("knowledge.py")), "impact", "--project-root", str(project)], capture_output=True, text=True)
    if result.returncode:
        impacted = set(record["modules"])
        record["dependency_warning"] = "影响分析未通过，关系或规格可能失效；全部模块保守重开，须修正后才能确认候选"
    else:
        impacted = {item["module_id"] for item in json.loads(result.stdout)["pending_impacts"]} & set(record["modules"])
        record.pop("dependency_warning", None)
    if any(not (project / "知识源" / record["modules"][module][0] / record["modules"][module][1] / "关系映射.json").is_file() for module in record["modules"]):
        impacted |= set(record["modules"])
    impacted |= changed_providers
    reset = []
    for task in record["tasks"]:
        if task["module_id"] in impacted and task["status"] == "completed":
            task.update(status="pending", started_at=None, completed_at=None, actor=None, note_digest=None,
                        git_head_before=None, git_head_after=None, before_files=None, changed_files=[], result_sha256=None, blocked_reason=None)
            reset.append(task["task_id"])
        if task["kind"] in {"checkpoint", "commit_inputs", "publish", "audit"} and task["status"] == "completed":
            task.update(status="pending", started_at=None, completed_at=None, actor=None, note_digest=None,
                        git_head_before=None, git_head_after=None, before_files=None, changed_files=[], result_sha256=None, blocked_reason=None)
            reset.append(task["task_id"])
    for module_id in impacted:
        record["spec_baselines"].pop(module_id, None)
    if reset:
        _save(project, record)
    return reset


def _next(record: dict) -> dict | None:
    if record.get("status") == "cancelled":
        return None
    completed = {task["task_id"] for task in record["tasks"] if task["status"] == "completed"}
    for task in record["tasks"]:
        if task["status"] != "completed" and task["status"] != "cancelled":
            if set(task["depends_on"]) <= completed:
                return task
    return None


def summary(record: dict) -> dict:
    current = _next(record)
    run_status = ("cancelled" if record.get("status") == "cancelled" else
                  "completed" if all(task["status"] == "completed" for task in record["tasks"]) else
                  current["status"] if current is not None and current["status"] in {"blocked", "failed", "waiting_review"} else "active")
    return {"run_id": record["run_id"], "release_id": record["release_id"],
            "inventory_summary": record.get("inventory_summary"),
            "dependency_warning": record.get("dependency_warning"),
            "total_tasks": len(record["tasks"]),
            "completed_tasks": sum(task["status"] == "completed" for task in record["tasks"]),
            "next_task": contract(current) if current else None,
            "run_status": run_status}


def inspect(project: Path, record: dict) -> dict:
    """Read-only status; never offer a task from stale inputs or a pending journal."""
    result = summary(record)
    if result["run_status"] in {"cancelled", "completed"}:
        return result
    conflicts = []
    if _digest((project / "知识库配置.json").read_bytes()) != record["config_sha256"]:
        conflicts.append("config_changed")
    if _digest((project / "知识源" / "功能大纲.md").read_bytes()) != record["outline_sha256"]:
        current = _next(record)
        if current is None or current["kind"] != "writer" or current["status"] not in {"running", "waiting_review"}:
            conflicts.append("outline_changed")
    if any(not _spec_path(project, record, module).is_file() or _digest(_spec_path(project, record, module).read_bytes()) != baseline for module, baseline in record["spec_baselines"].items()):
        conflicts.append("prepared_spec_changed")
    if run_state.pending_transactions(project):
        conflicts.append("pending_transaction")
    if conflicts:
        result.update(run_status="blocked", next_task=None, conflicts=conflicts,
                      next_step="先执行 recover 和 run-resume，复核项目文件后再取下一任务")
    return result


def contract(task: dict | None) -> dict | None:
    if task is None:
        return None
    return {key: task[key] for key in ("task_id", "kind", "module_id", "depends_on", "allowed_write_set", "status", "attempt")}


def begin(project: Path, run_id: str, task_id: str) -> dict:
    record = load(project, run_id)
    if _digest((project / "知识库配置.json").read_bytes()) != record["config_sha256"]:
        raise ValueError("知识库配置与运行基线不同；须复核固定提交并创建新运行")
    current_task = _next(record)
    writer_retry = current_task is not None and current_task["kind"] == "writer" and current_task["status"] == "waiting_review" and current_task["attempt"] > 0
    if _digest((project / "知识源" / "功能大纲.md").read_bytes()) != record["outline_sha256"] and not writer_retry:
        raise ValueError("功能大纲与运行基线不同；须复核范围后创建新运行")
    _verify_sources(project)
    _refresh_dependencies(project, record)
    record = load(project, run_id)
    task = _next(record)
    if task is None or task["task_id"] != task_id or task["status"] not in {"pending", "failed", "waiting_review"}:
        raise ValueError("任务不是当前可开始的步骤")
    run_state.require_recovered(project)
    task.update(status="running", attempt=task["attempt"] + 1, started_at=_now(),
                git_head_before=_git(project, "rev-parse", "HEAD"), before_files=_paths(project), blocked_reason=None)
    _save(project, record)
    return contract(task)


def _changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))


def _allowed(path: str, patterns: list[str]) -> bool:
    return any(path.startswith(pattern) if pattern.endswith("/") else path == pattern for pattern in patterns)


def _verify(project: Path, record: dict, task: dict) -> None:
    kind, module = task["kind"], task["module_id"]
    if kind in {"inventory", "prepare"}:
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("knowledge.py")), "check", "--project-root", str(project)], capture_output=True)
        if result.returncode:
            raise ValueError("知识项目 check 未通过，任务不能标为完成")
    if kind in {"writer", "business_intent", "reviewer", "confirm_claims", "prepare"}:
        domain, name, _ = record["modules"][module]
        if not (project / "知识源" / domain / name / "结构化规格.md").is_file():
            raise ValueError("模块结构化规格尚未建立")
    if kind == "confirm_claims":
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("knowledge.py")), "impact", "--project-root", str(project), "--module-id", module], capture_output=True, text=True)
        if result.returncode or json.loads(result.stdout)["pending_impacts"]:
            raise ValueError("模块仍有未复核的结论影响")
    if kind == "prepare":
        domain, name, _ = record["modules"][module]
        manifest = project / "知识源" / domain / name / "发布清单.md"
        if not manifest.is_file() or "review_status: draft" not in manifest.read_text(encoding="utf-8"):
            raise ValueError("模块尚无 draft 发布清单")
    if kind == "approval":
        domain, name, _ = record["modules"][module]
        manifest = project / "知识源" / domain / name / "发布清单.md"
        if not manifest.is_file() or not any(f"review_status: {status}" in manifest.read_text(encoding="utf-8") for status in ("reviewed", "policy_reviewed")):
            raise ValueError("模块没有已获授权的发布清单")
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("knowledge.py")), "check", "--project-root", str(project)], capture_output=True)
        if result.returncode:
            raise ValueError("批准后知识项目校验失败")
    if kind == "commit_inputs":
        current_head = _git(project, "rev-parse", "HEAD")
        if current_head == task["git_head_before"]:
            raise ValueError("发布输入尚未形成新的 Git 提交")
        diff = subprocess.run(["git", "-C", str(project), "diff", "--name-only", "-z", task["git_head_before"], current_head], capture_output=True)
        if diff.returncode:
            raise ValueError("无法核对发布输入提交的文件范围")
        committed_paths = [part.decode("utf-8") for part in diff.stdout.split(b"\0") if part]
        allowed = ["知识源/功能大纲.md", "知识源/术语表.md", "运行证据/", "自动审核记录/", "自动审核策略/", "发布/"]
        for domain, name, _ in record["modules"].values():
            allowed.append(f"知识源/{domain}/{name}/")
        outside = [path for path in committed_paths if not _allowed(path, allowed)]
        if not committed_paths or outside:
            raise ValueError(f"发布输入提交包含无关文件或没有变更：{outside[:5]}")
        status = _git(project, "status", "--porcelain", "--untracked-files=all")
        if any(line[3:] and not line[3:].startswith(".code2kb/") for line in status.splitlines()):
            raise ValueError("知识项目仍有未提交的文件变化")
    if kind in {"publish", "audit"}:
        pointer = project / "发布" / "当前版本.json"
        if not pointer.is_file() or json.loads(pointer.read_text(encoding="utf-8")).get("release_id") != record["release_id"]:
            raise ValueError("当前发布版本与运行账本不一致")
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("knowledge.py")), "audit-release", "--project-root", str(project)], capture_output=True)
        if result.returncode:
            raise ValueError("当前发布审计未通过")
        if record["retrieval_suite"]:
            suite = Path(record["retrieval_suite"])
            if not suite.is_file() or _digest(suite.read_bytes()) != record["retrieval_suite_sha256"]:
                raise ValueError("检索评测套件与运行基线不一致")
            retrieval = subprocess.run([sys.executable, str(Path(__file__).with_name("knowledge.py")), "retrieval-audit", "--project-root", str(project), "--release-id", record["release_id"]], capture_output=True)
            if retrieval.returncode:
                raise ValueError("检索扩展审计未通过")
        relation_pointer = project / "发布" / "当前关系版本.json"
        if relation_pointer.is_file() and json.loads(relation_pointer.read_text(encoding="utf-8")).get("release_id") == record["release_id"]:
            relation = subprocess.run([sys.executable, str(Path(__file__).with_name("knowledge.py")), "relation-audit", "--project-root", str(project), "--release-id", record["release_id"]], capture_output=True)
            if relation.returncode:
                raise ValueError("关系扩展审计未通过")


def complete(project: Path, run_id: str, task_id: str, actor: str, note: str) -> dict:
    record = load(project, run_id)
    task = _next(record)
    if task is None or task["task_id"] != task_id or task["status"] != "running":
        raise ValueError("任务未处于运行中")
    if task["kind"] in {"writer", "business_intent", "reviewer", "checkpoint", "approval", "publish"} and (not actor.strip() or not note.strip()):
        raise ValueError("此任务须记录执行者与实际检查说明；账本记录不构成批准")
    current = _paths(project)
    changed = _changed(task["before_files"], current)
    outside = [path for path in changed if not _allowed(path, task["allowed_write_set"])]
    if outside:
        task["status"] = "blocked"
        task["blocked_reason"] = "write_set"
        _save(project, record)
        raise ValueError(f"任务写入超出允许范围：{outside[:5]}")
    _verify(project, record, task)
    task.update(status="completed", completed_at=_now(), actor=actor or "code2kb-cli",
                note_digest=_digest(note.encode("utf-8")) if note else None,
                git_head_after=_git(project, "rev-parse", "HEAD"), changed_files=changed,
                result_sha256=_digest(json.dumps({path: current.get(path) for path in changed}, sort_keys=True).encode("utf-8")))
    task["before_files"] = None
    if task["kind"] == "prepare":
        record["spec_baselines"][task["module_id"]] = _digest(_spec_path(project, record, task["module_id"]).read_bytes())
    if task["kind"] == "writer":
        record["outline_sha256"] = _digest((project / "知识源" / "功能大纲.md").read_bytes())
    _save(project, record)
    return summary(record)


def execute(project: Path, run_id: str, task_id: str) -> dict:
    record = load(project, run_id)
    task = _next(record)
    if task is None or task["task_id"] != task_id or task["kind"] not in AUTOMATED:
        raise ValueError("只有当前确定性任务可由执行器运行")
    with run_state.project_lock(project):
        begin(project, run_id, task_id)
        kind = task["kind"]
        arguments = ["knowledge.py", {"inventory": "check", "confirm_claims": "confirm-claims",
                                      "prepare": "prepare", "audit": "audit-release"}[kind]]
        if kind in {"confirm_claims", "prepare"}:
            arguments += ["--module-id", task["module_id"]]
        if kind == "prepare":
            arguments += ["--auto-retrieval-metadata", "--refresh"]
        arguments += ["--project-root", str(project)]
        try:
            from . import knowledge as cli
        except ImportError:
            import knowledge as cli
        output, diagnostic = io.StringIO(), io.StringIO()
        prior_argv = sys.argv
        try:
            sys.argv = arguments
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(diagnostic):
                try:
                    return_code = cli._main()
                except SystemExit as exc:
                    return_code = exc.code if isinstance(exc.code, int) else 1
        finally:
            sys.argv = prior_argv
        if return_code:
            record = load(project, run_id)
            current = _next(record)
            if current is None or current["task_id"] != task_id:
                raise ValueError("执行失败时运行账本已变化，拒绝覆盖")
            pending = run_state.pending_transactions(project)
            current["status"] = "blocked" if pending else "failed"
            current["blocked_reason"] = "transaction" if pending else None
            current["result_sha256"] = _digest(output.getvalue().encode("utf-8"))
            _save(project, record)
            return {"run_id": run_id, "task_id": task_id, "status": "failed",
                    "error_code": "E_TASK_COMMAND_FAILED", "diagnostics": diagnostic.getvalue().splitlines()}
        completed = complete(project, run_id, task_id, "code2kb-cli", "")
    return {"run_id": run_id, "task_id": task_id, "status": "completed", "next_task": completed["next_task"]}


def resume(project: Path, run_id: str) -> dict:
    record = load(project, run_id)
    if _digest((project / "知识库配置.json").read_bytes()) != record["config_sha256"]:
        result = summary(record)
        result["recovery_note"] = "知识库配置或固定提交已变化，停止自动续跑并复核"
        return result
    current_task = _next(record)
    writer_in_progress = current_task is not None and current_task["kind"] == "writer" and current_task["status"] in {"running", "waiting_review"} and current_task["attempt"] > 0
    if _digest((project / "知识源" / "功能大纲.md").read_bytes()) != record["outline_sha256"] and not writer_in_progress:
        result = summary(record)
        result["recovery_note"] = "功能大纲与运行基线不同，停止自动续跑并复核范围"
        return result
    try:
        _verify_sources(project)
    except (OSError, ValueError) as exc:
        result = summary(record)
        result["recovery_note"] = f"固定源码提交当前无法读取，停止自动续跑：{exc}"
        return result
    reset = _refresh_dependencies(project, record)
    record = load(project, run_id)
    task = _next(record)
    if task is None:
        return summary(record)
    if task["status"] == "blocked" and task.get("blocked_reason") in {"write_set", "transaction"}:
        changed = _changed(task["before_files"], _paths(project))
        outside = [path for path in changed if not _allowed(path, task["allowed_write_set"])]
        if not outside and not run_state.pending_transactions(project):
            task["status"] = "waiting_review"
            task["blocked_reason"] = None
            _save(project, record)
    if task["status"] == "running":
        # An interrupted writer/reviewer needs an explicit review; a finished
        # deterministic operation may be recognized from the authoritative files.
        if task["kind"] in {"inventory", "confirm_claims", "prepare", "approval", "commit_inputs", "publish", "audit"}:
            try:
                return complete(project, run_id, task["task_id"], "code2kb-recovery", "从项目文件与 Git 重新验证")
            except ValueError:
                record = load(project, run_id)
                task = _next(record)
                if task is not None and task["kind"] == "commit_inputs" and task["status"] == "running":
                    task["status"] = "blocked"
                    task["blocked_reason"] = "git_checkpoint"
                    _save(project, record)
        if task is not None and task["status"] == "running":
            changed = _changed(task["before_files"], _paths(project))
            outside = [path for path in changed if not _allowed(path, task["allowed_write_set"])]
            task["status"] = "blocked" if outside else "waiting_review"
            task["blocked_reason"] = "write_set" if outside else None
            _save(project, record)
    result = summary(record)
    if reset:
        result["invalidated_tasks"] = reset
    result["recovery_note"] = "从当前项目文件、Git 与发布审计核对；等待必要复核或外部授权"
    return result


def cancel(project: Path, run_id: str) -> dict:
    record = load(project, run_id)
    record["status"] = "cancelled"
    task = _next(record)
    if task is not None and task["status"] != "completed":
        task["status"] = "cancelled"
    _save(project, record)
    return summary(record)
