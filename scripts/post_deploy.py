#!/usr/bin/env python3
"""Repository-owned production post-deploy tasks.

Runs automatically as a one-shot Compose service for CI/CD production releases.
Nothing here is a host-side manual command: it ships in the immutable app image,
uses the same production database mount and runtime secrets as the app, and
publishes a release-scoped completion marker only after every task succeeds.

Local/dev compose stays unchanged: unless HF_POST_DEPLOY_REQUIRED is explicitly
truthy this process exits successfully without touching LINE or the database.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import deploy_backup, post_deploy  # noqa: E402
import staff_oa_sync  # noqa: E402

DEFAULT_READY_URL = "http://app:5000/fingerprintlogs/health"
DEFAULT_READY_TIMEOUT_SECONDS = 240
_TRUTHY = {"1", "true", "yes", "on"}


def _required() -> bool:
    return os.getenv("HF_POST_DEPLOY_REQUIRED", "").strip().lower() in _TRUTHY


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise post_deploy.PostDeployError(f"Required release metadata {name} is empty")
    return value


def _wait_for_app(url: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_status = "unreachable"
    while time.monotonic() < deadline:
        try:
            response = requests.get(url, timeout=5)
            last_status = str(response.status_code)
            if response.status_code // 100 == 2:
                return
        except requests.RequestException:
            last_status = "unreachable"
        time.sleep(2)
    raise post_deploy.PostDeployError(
        f"Application did not become ready before post-deploy deadline (last status {last_status})"
    )


def main() -> int:
    if not _required():
        print("Post-deploy disabled; no production operations requested.")
        return 0
    if os.getenv("ENV", "").strip().lower() != "production":
        print("REFUSING post-deploy: ENV must be production", file=sys.stderr)
        return 2

    try:
        run_id = _required_env("HF_DEPLOY_RUN")
        commit = _required_env("HF_DEPLOY_COMMIT")
        post_deploy._validate_release(run_id, commit)

        ready_url = os.getenv("HF_POST_DEPLOY_READY_URL", DEFAULT_READY_URL).strip()
        timeout_seconds = int(
            os.getenv("HF_POST_DEPLOY_READY_TIMEOUT_SECONDS", str(DEFAULT_READY_TIMEOUT_SECONDS))
        )
        if timeout_seconds < 1 or timeout_seconds > 900:
            raise post_deploy.PostDeployError("Invalid post-deploy readiness timeout")

        # `depends_on` guarantees only that the app container has started, not
        # that its `alembic upgrade head` has completed. Wait for the app's
        # existing health route first; once it answers 2xx, migrations and the
        # pre-migration backup gate have completed and uvicorn is serving.
        _wait_for_app(ready_url, timeout_seconds)

        # Now verify the exact release snapshot before touching LINE. This is
        # also what the public readiness endpoint verifies after post-deploy.
        deploy_backup.verify_snapshot(
            deploy_backup.BACKUP_ROOT / "snapshots" / run_id,
            run_id,
            commit,
        )

        print("Post-deploy: reconciling Staff LINE OA rich menus")
        result = staff_oa_sync.sync(apply=True)
        if result != 0:
            raise post_deploy.PostDeployError("Staff LINE OA rich-menu sync failed")

        marker = post_deploy.write_marker(
            run_id,
            commit,
            [post_deploy.TASK_STAFF_OA_RICH_MENU],
        )
        # Safe diagnostic: path/run metadata only, never LINE ids or secrets.
        print(f"Post-deploy complete: {marker.name}")
        return 0
    except Exception as exc:  # noqa: BLE001 - job must fail closed
        print(f"POST-DEPLOY FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
