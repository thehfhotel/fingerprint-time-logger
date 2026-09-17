"""Non-sensitive CD readiness on the existing public webhook URL (GET only).

POST is still handled by the signed LINE webhook. This GET returns no body,
identities, metadata, or backup contents. It verifies the caller's expected run
and commit instead of returning success from a healthy but outdated container.

When HF_POST_DEPLOY_REQUIRED=true (production CI/CD), readiness also requires a
release-scoped post-deploy marker proving repository-owned operational tasks
such as Staff LINE OA rich-menu reconciliation completed for this exact run.
"""
from functools import lru_cache
import hmac
import os
import threading

from fastapi import APIRouter, Query, Response

from app.services import deploy_backup, post_deploy

router = APIRouter()
_verify_lock = threading.Lock()


@lru_cache(maxsize=1)
def _verified(run_id: str, commit: str) -> bool:
    """Cache immutable snapshot verification, never mutable post-deploy state."""
    # Full checksum/integrity verification once per process, never on every
    # unauthenticated probe. Failed snapshot verification is cached until
    # restart too. Post-deploy markers are intentionally NOT cached: the app is
    # already serving while the one-shot Compose service performs the sync, so
    # the first probes normally see 503 and later probes must be able to become
    # 204 without restarting the app.
    try:
        deploy_backup.verify_snapshot(
            deploy_backup.BACKUP_ROOT / 'snapshots' / run_id, run_id, commit)
        return True
    except Exception:
        return False


def _post_deploy_required() -> bool:
    return os.getenv('HF_POST_DEPLOY_REQUIRED', '').strip().lower() in {
        '1', 'true', 'yes', 'on',
    }


def _post_deploy_verified(run_id: str, commit: str) -> bool:
    if not _post_deploy_required():
        return True
    try:
        post_deploy.verify_marker(run_id, commit)
        return True
    except Exception:
        return False


@router.get('/webhook', include_in_schema=False)
def deployment_ready(
    run_id: str = Query(..., min_length=3, max_length=27, pattern=r'^[1-9][0-9]{0,19}-[1-9][0-9]{0,5}$'),
    commit: str = Query(..., min_length=40, max_length=40, pattern=r'^[0-9a-f]{40}$'),
):
    expected_run = os.getenv('HF_DEPLOY_RUN', '')
    expected_commit = os.getenv('HF_DEPLOY_COMMIT', '')
    ready = False
    if (hmac.compare_digest(run_id, expected_run)
            and hmac.compare_digest(commit, expected_commit)):
        with _verify_lock:
            backup_ready = _verified(run_id, commit)
        ready = backup_ready and _post_deploy_verified(run_id, commit)
    return Response(status_code=204 if ready else 503, headers={
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        'X-Robots-Tag': 'noindex, nofollow',
    })
