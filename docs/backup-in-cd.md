# Automatic database backup inside CD

This replaces the earlier downloadable host-installer proposal. Do not upload
that ZIP, run install_host.py, change authorized_keys, add a new SSH secret, or
set FINGERPRINT_BACKUP_READY for this implementation.

## Deployment path

The existing `Build & Publish` workflow remains the only production entry point:

1. Run the repository tests, including the named backup/failure-path test step.
2. Build/push the application image with the existing SHA-pinned estate workflow.
3. The existing forced-command deploy ships Compose and environment metadata.
4. Inside the deployed image, Alembic's `env.py` verifies a host-persistent
   snapshot BEFORE opening the writable migration connection.
5. Run migrations under the same advisory lock. The existing Docker CMD uses
   `alembic ... upgrade head && uvicorn ...`; failure never starts the server.
6. A final workflow job checks the exact expected workflow run/attempt and
   commit on the running application AND verifies that its snapshot is valid.
   An old healthy container, a login redirect, and a bare HTTP 200 cannot pass.

No manual bootstrap on evergreen is required: Compose creates the backup bind
source as part of the normal deployment. The helper lives in the application
image. No Docker socket, privileged helper container, arbitrary SSH command, or
new host execution permission is used.

This is **before migration and application startup**, not before every host-side
change. The existing host shim may already have replaced `.env`/Compose or
stopped the old container. This change does not promise zero downtime or keep
the old application serving when a backup fails. A failed backup blocks schema
changes/new server startup; the final workflow check prevents a false green
when the host shim itself does not report that startup failure.

## What is saved

On evergreen:

`/home/deploy/backups/fingerprint-time-logger/snapshots/<run_id>-<attempt>/`

- `attendance.db`: the whole SQLite database, not a CSV/table subset.
- `manifest.json`: creation time, database size, SHA-256, original Alembic
  revision(s), incoming commit and workflow identity, integrity-check result.

The mount appears at `/backups` in the container. The gate verifies that it is
actually mounted, rather than silently writing an ephemeral container copy.
Directories are 0700 and files 0600. No backup contents, employee rows or secret
values are uploaded to GitHub. The log receipt contains identifiers/checksums
only. Snapshots remain on the host across image replacement.

**Scope is database recovery, not a complete machine/application backup.**
There is no previous `.env` archive or `docker save` export in this version.
The manifest's commit identifies the INCOMING release, not the outgoing image.
Those are intentionally not misrepresented as captured: the existing deploy
contract can replace configuration before this hook runs. Existing Git/GHCR and
secret management remain the sources for application/configuration recovery.
An older database restore is not an automatic application rollback.

## Failure and retry behavior

SQLite's native backup API creates the snapshot. It is reopened and checked
with `PRAGMA integrity_check`, required attendance tables, migration revisions,
size and SHA-256. A private staging directory is synced and renamed to the final
snapshot only after verification. Incomplete snapshots cannot pass readiness.
Missing/empty/wrong/corrupt source databases, missing CI metadata, a missing
persistent mount, low disk space, lock contention, copy timeouts, invalid
manifests and bad checksums all fail closed. Unknown/empty ENV is not a bypass;
only explicit test/development environments skip the production hook.

An advisory lock covers both snapshot creation and the actual migration. The
first successful snapshot for a workflow run/attempt is immutable. Container
restart within that deployment re-verifies/reuses it, instead of replacing it
with partially migrated state. Re-running the complete workflow gets a new
attempt identifier and a new snapshot. To repeat a failed readiness job, use
**Re-run all jobs**, not just that job: the expected attempt must match the
metadata delivered by the deployment.

Completed backups are not deleted automatically. Low space stops deployment
rather than deleting recovery data. There is no automatic database restore on
failure: it could erase writes accepted since the snapshot. Recovery remains
an explicit, separately reviewed action. Host-only copies do not protect against
loss of evergreen's disk or the whole host.

The existing production Compose persists only the `.db` file. Accordingly the
production gate requires SQLite DELETE journal mode; it refuses WAL rather than
assuming another container's WAL/SHM files were persisted. The core copy routine
is tested with a live WAL database in one filesystem, but that is not a claim
that the current file-only production mount supports WAL across containers.

## Readiness check

GET on the existing public `/api/public/staff-oa/webhook` URL returns an empty
204 only when `run_id` and `commit` match the application's environment and the
snapshot verifies. Otherwise it returns 503 (invalid inputs are 422). Responses
are no-store. Snapshot verification is cached once per process and guarded by a
lock; wrong-version probes do not trigger database reads. This check discloses
no metadata or backup contents. The signature-protected LINE POST handler is
unchanged. The workflow does not follow redirects and accepts only 204.

The first production run still has to prove the public edge forwards GET on
that URL and the host uses this image's migrator/Compose mount. Neither has been
claimed live-verified from unit tests. Any failure appears as a failed final
verification job rather than a successful deployment claim.

## Tests

`pytest tests/unit/test_deploy_backup.py -v`

36 local tests passed, plus 14 unittest subtests, using real SQLite and real
Alembic against temporary data. Application metadata is isolated in the Alembic
ordering tests; production is never contacted. Includes snapshot completeness,
permissions, redacted logs, immutable retries, checksum failures, disk/timeout
errors, symlinks, migration locking, live WAL copying versus production WAL
refusal, production environment/mount checks, real schema-change ordering and
failure blocking, version-specific HTTP readiness and the workflow contract.

Local runtime was Python 3.13.5 / SQLAlchemy 2.0.50 / Alembic 1.18.4 /
FastAPI 0.128.2. Python parsing, YAML parsing, shell syntax and the Compose bind
contract also passed. Full repository CI uses its pinned Python dependencies;
its result must be checked separately. No production backup or deployment was
executed while preparing this change.
