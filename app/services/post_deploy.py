"""Release-scoped post-deploy completion marker.

The production deploy is not considered complete until repository-owned
post-deploy work (currently Staff LINE OA rich-menu reconciliation) finishes
for the exact GitHub Actions run and commit being served.

The marker lives on the same host-persistent /backups mount as the verified
pre-migration snapshot.  It contains no secrets, employee data, LINE ids, or
API responses: only release metadata and the names of completed tasks.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Iterable

from app.services import deploy_backup

MARKER_ROOT = deploy_backup.BACKUP_ROOT / "post-deploy"
FORMAT = "hf-post-deploy-v1"
TASK_STAFF_OA_RICH_MENU = "staff_oa_rich_menu_sync"


class PostDeployError(RuntimeError):
    """Safe post-deploy diagnostic; never include secrets or business data."""


def _validate_release(run_id: str, commit: str) -> None:
    if not deploy_backup.RUN_RE.fullmatch(run_id or ""):
        raise PostDeployError("Invalid deployment run id")
    if not deploy_backup.COMMIT_RE.fullmatch(commit or ""):
        raise PostDeployError("Invalid deployment commit")


def marker_path(run_id: str, root: Path = MARKER_ROOT) -> Path:
    if not deploy_backup.RUN_RE.fullmatch(run_id or ""):
        raise PostDeployError("Invalid deployment run id")
    return root / f"{run_id}.json"


def _require_regular(path: Path) -> None:
    if path.is_symlink() or not path.exists() or not stat.S_ISREG(path.stat().st_mode):
        raise PostDeployError("Post-deploy marker must be a regular file")


def write_marker(
    run_id: str,
    commit: str,
    tasks: Iterable[str],
    root: Path = MARKER_ROOT,
) -> Path:
    """Atomically publish completion for one exact release."""
    _validate_release(run_id, commit)
    task_list = sorted({str(task).strip() for task in tasks if str(task).strip()})
    if not task_list:
        raise PostDeployError("At least one completed post-deploy task is required")

    if root.is_symlink():
        raise PostDeployError("Post-deploy marker directory cannot be a symlink")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not root.is_dir():
        raise PostDeployError("Post-deploy marker root is not a directory")
    root.chmod(0o700)

    payload = {
        "format": FORMAT,
        "run_id": run_id,
        "target_commit": commit,
        "status": "ok",
        "tasks": task_list,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    target = marker_path(run_id, root)
    fd, temp_name = tempfile.mkstemp(prefix=f".{run_id}.", suffix=".tmp", dir=root)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=True, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        temp.chmod(0o600)
        os.replace(temp, target)
        target.chmod(0o600)
        directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp.exists():
            temp.unlink()
    return target


def verify_marker(
    run_id: str,
    commit: str,
    required_tasks: Iterable[str] = (TASK_STAFF_OA_RICH_MENU,),
    root: Path = MARKER_ROOT,
) -> dict:
    """Verify that required post-deploy work completed for this release."""
    _validate_release(run_id, commit)
    path = marker_path(run_id, root)
    _require_regular(path)
    if path.stat().st_size > 8192:
        raise PostDeployError("Invalid post-deploy marker size")
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise PostDeployError("Invalid post-deploy marker") from exc

    if (
        info.get("format"),
        info.get("run_id"),
        info.get("target_commit"),
        info.get("status"),
    ) != (FORMAT, run_id, commit, "ok"):
        raise PostDeployError("Post-deploy marker does not match this deployment")

    tasks = info.get("tasks")
    if not isinstance(tasks, list) or not all(isinstance(task, str) for task in tasks):
        raise PostDeployError("Invalid post-deploy task list")
    missing = set(required_tasks) - set(tasks)
    if missing:
        raise PostDeployError("Required post-deploy task is incomplete")
    return info
