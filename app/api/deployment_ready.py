"""Non-sensitive CD readiness on the existing public webhook URL (GET only).

POST is still handled by the signed LINE webhook. This GET returns no body,
identities, metadata, or backup contents. It verifies the caller's expected run
and commit instead of returning success from a healthy but outdated container.
"""
from functools import lru_cache
import hmac
import os
import threading

from fastapi import APIRouter, Query, Response

from app.services import deploy_backup

router = APIRouter()
_verify_lock = threading.Lock()


@lru_cache(maxsize=1)
def _verified(run_id: str, commit: str) -> bool:
    # Full checksum/integrity verification once per process, never on every
    # unauthenticated probe. Failed verification is cached until restart too.
    try:
        deploy_backup.verify_snapshot(
            deploy_backup.BACKUP_ROOT / 'snapshots' / run_id, run_id, commit)
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
            ready = _verified(run_id, commit)
    return Response(status_code=204 if ready else 503, headers={
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        'X-Robots-Tag': 'noindex, nofollow',
    })
