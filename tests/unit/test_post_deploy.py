"""Post-deploy release marker and CI/CD contract tests."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deployment_ready
from app.services import post_deploy

RUN = "12345-1"
COMMIT = "a" * 40


def test_marker_round_trip_is_release_scoped_and_private(tmp_path):
    root = tmp_path / "post-deploy"
    path = post_deploy.write_marker(
        RUN, COMMIT, [post_deploy.TASK_STAFF_OA_RICH_MENU], root=root
    )
    assert path == root / f"{RUN}.json"
    assert path.stat().st_mode & 0o777 == 0o600
    assert root.stat().st_mode & 0o777 == 0o700
    info = post_deploy.verify_marker(RUN, COMMIT, root=root)
    assert info["status"] == "ok"
    assert info["tasks"] == [post_deploy.TASK_STAFF_OA_RICH_MENU]


def test_marker_cannot_be_reused_for_another_commit(tmp_path):
    root = tmp_path / "post-deploy"
    post_deploy.write_marker(
        RUN, COMMIT, [post_deploy.TASK_STAFF_OA_RICH_MENU], root=root
    )
    with pytest.raises(post_deploy.PostDeployError):
        post_deploy.verify_marker(RUN, "b" * 40, root=root)


def test_tampered_or_incomplete_marker_fails_closed(tmp_path):
    root = tmp_path / "post-deploy"
    path = post_deploy.write_marker(
        RUN, COMMIT, [post_deploy.TASK_STAFF_OA_RICH_MENU], root=root
    )
    data = json.loads(path.read_text())
    data["tasks"] = []
    path.write_text(json.dumps(data))
    with pytest.raises(post_deploy.PostDeployError):
        post_deploy.verify_marker(RUN, COMMIT, root=root)


def test_invalid_release_metadata_cannot_escape_marker_root(tmp_path):
    for run_id in ("", "../escape", "12345", "1-0"):
        with pytest.raises(post_deploy.PostDeployError):
            post_deploy.marker_path(run_id, tmp_path)
    with pytest.raises(post_deploy.PostDeployError):
        post_deploy.write_marker(
            RUN, "latest", [post_deploy.TASK_STAFF_OA_RICH_MENU], root=tmp_path
        )


def _readiness_client():
    app = FastAPI()
    app.include_router(deployment_ready.router, prefix="/api/public/staff-oa")
    return TestClient(app)


def test_production_readiness_waits_for_post_deploy_marker(monkeypatch):
    deployment_ready._verified.cache_clear()
    monkeypatch.setenv("HF_DEPLOY_RUN", RUN)
    monkeypatch.setenv("HF_DEPLOY_COMMIT", COMMIT)
    monkeypatch.setenv("HF_POST_DEPLOY_REQUIRED", "true")
    client = _readiness_client()

    with patch.object(deployment_ready, "_verified", return_value=True), \
         patch.object(deployment_ready.post_deploy, "verify_marker", side_effect=post_deploy.PostDeployError("missing")):
        assert client.get(
            "/api/public/staff-oa/webhook", params={"run_id": RUN, "commit": COMMIT}
        ).status_code == 503

    with patch.object(deployment_ready, "_verified", return_value=True), \
         patch.object(deployment_ready.post_deploy, "verify_marker", return_value={"status": "ok"}):
        assert client.get(
            "/api/public/staff-oa/webhook", params={"run_id": RUN, "commit": COMMIT}
        ).status_code == 204


def test_post_deploy_requirement_is_off_for_local_and_legacy_tests(monkeypatch):
    monkeypatch.delenv("HF_POST_DEPLOY_REQUIRED", raising=False)
    assert deployment_ready._post_deploy_required() is False


def test_repo_contract_has_no_manual_rich_menu_deploy_step():
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/build.yml").read_text()
    compose = (root / "docker-compose.yml").read_text()

    assert "needs: [provenance, quality, test]" in workflow
    assert "Require merged PR provenance" in workflow
    assert "/commits/${GITHUB_SHA}/pulls" in workflow
    assert "HF_POST_DEPLOY_REQUIRED=true" in workflow
    assert "Verify release + backup + post-deploy" in workflow
    assert "post-deploy:" in compose
    assert 'command: ["python", "scripts/post_deploy.py"]' in compose
    assert "HF_POST_DEPLOY_REQUIRED=${HF_POST_DEPLOY_REQUIRED:-false}" in compose
    assert "STAFF_OA_CHANNEL_ACCESS_TOKEN=${STAFF_OA_CHANNEL_ACCESS_TOKEN}" in compose
    assert "/home/deploy/backups/fingerprint-time-logger:/backups" in compose
    assert "/var/run/docker.sock" not in compose
