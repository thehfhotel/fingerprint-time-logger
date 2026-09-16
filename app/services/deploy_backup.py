"""Host-persistent database backup gate for production Alembic operations.

Ships in the normal application image. No SSH installer, Docker socket, host
command execution, or new credentials. The deployment run identifies the FIRST
pre-migration snapshot; container retries must never replace it with a partially
migrated database. Existing snapshots are reverified before reuse.
"""
from __future__ import annotations

from contextlib import contextmanager, closing
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
import time

BACKUP_ROOT = Path('/backups')
DATABASE_PATH = Path('/app/database/attendance.db')
RUN_RE = re.compile(r'[1-9][0-9]{0,19}-[1-9][0-9]{0,5}\Z')
COMMIT_RE = re.compile(r'[0-9a-f]{40}\Z')
REQUIRED_TABLES = {'employees', 'attendance_records'}
RESERVE_BYTES = 64 * 1024 * 1024
FORMAT = 'hf-pre-migration-backup-v1'


class BackupError(RuntimeError):
    """Safe diagnostic: never includes a database row or environment values."""


def _regular(path: Path) -> None:
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise BackupError('Expected a regular file; symlinks are not allowed')


def _directory(path: Path) -> None:
    if path.is_symlink():
        raise BackupError('Backup directory cannot be a symlink')
    path.mkdir(mode=0o700, parents=False, exist_ok=True)
    if not path.is_dir():
        raise BackupError('Expected a backup directory')
    path.chmod(0o700)


def _fsync(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _digest(path: Path) -> str:
    _regular(path)
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def _inspect_database(path: Path, *, delete_journal: bool = False) -> list[str]:
    _regular(path)
    deadline = time.monotonic() + 90
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        if delete_journal and db.execute('PRAGMA journal_mode').fetchone()[0] != 'delete':
            # The current compose persists ONE .db file, not WAL/SHM from an
            # old container. Never call a WAL snapshot complete on that mount.
            raise BackupError('Production file-only database mount requires DELETE journal mode')
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise BackupError('SQLite integrity check failed')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not REQUIRED_TABLES <= tables:
            raise BackupError('Required attendance tables are missing')
        if 'alembic_version' not in tables:
            raise BackupError('Migration version table is missing')
        return sorted(r[0] for r in db.execute('SELECT version_num FROM alembic_version'))


def _copy_database(source: Path, target: Path, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    def progress(_status, _remaining, _total):
        if time.monotonic() > deadline:
            raise BackupError('SQLite backup deadline exceeded')
    with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as src:
        with closing(sqlite3.connect(target)) as dest:
            src.backup(dest, pages=256, progress=progress, sleep=0.05)
            # Make the snapshot self-contained, regardless of the source mode.
            dest.execute('PRAGMA journal_mode=DELETE')
    target.chmod(0o600)
    _fsync(target)


def verify_snapshot(folder: Path, run_id: str, commit: str) -> dict:
    if folder.is_symlink() or not folder.is_dir():
        raise BackupError('Snapshot must be a real directory')
    manifest = folder / 'manifest.json'
    _regular(manifest)
    if manifest.stat().st_size > 16384:
        raise BackupError('Invalid manifest size')
    info = json.loads(manifest.read_text())
    if (info.get('format'), info.get('run_id'), info.get('target_commit')) != (FORMAT, run_id, commit):
        raise BackupError('Snapshot does not match this deployment')
    database = folder / 'attendance.db'
    _regular(database)
    if database.stat().st_size != info.get('database_bytes') or _digest(database) != info.get('sha256'):
        raise BackupError('Snapshot checksum verification failed')
    if _inspect_database(database) != info.get('schema_before'):
        raise BackupError('Snapshot migration version verification failed')
    if info.get('integrity_check') != 'ok':
        raise BackupError('Snapshot is not verified')
    return info


@contextmanager
def snapshot_gate(source: Path, root: Path, run_id: str, commit: str, *,
                  lock_timeout: float = 30, copy_timeout: float = 90,
                  delete_journal: bool = False):
    """Hold the migration lock through backup AND the caller's migration.

    All exceptions propagate: the caller must NOT migrate or start the server
    on failure. No auto-restore, no deletion/overwrite of completed snapshots.
    """
    if not RUN_RE.fullmatch(run_id) or not COMMIT_RE.fullmatch(commit):
        raise BackupError('CI deployment run/commit metadata is missing or invalid')
    _regular(source)
    if source.stat().st_size == 0:
        raise BackupError('Refusing to back up an empty production database')
    _directory(root)
    snapshots = root / 'snapshots'
    _directory(snapshots)
    old_umask = os.umask(0o077)
    try:
        fd = os.open(root / '.migration.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    finally:
        os.umask(old_umask)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise BackupError('Invalid migration lock file')
        deadline = time.monotonic() + lock_timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise BackupError('Another backup or migration holds the lock')
                time.sleep(0.05)
        folder = snapshots / run_id
        if folder.exists() or folder.is_symlink():
            info = verify_snapshot(folder, run_id, commit)
        else:
            # The original mount is file-only. Fail closed on unexpected WAL.
            _inspect_database(source, delete_journal=delete_journal)
            if shutil.disk_usage(root).free < source.stat().st_size * 2 + RESERVE_BYTES:
                raise BackupError('Insufficient free space for a verified backup')
            staging = Path(tempfile.mkdtemp(prefix='.incomplete-', dir=snapshots))
            try:
                database = staging / 'attendance.db'
                _copy_database(source, database, copy_timeout)
                schema = _inspect_database(database)
                info = {
                    'format': FORMAT, 'run_id': run_id, 'target_commit': commit,
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'database_bytes': database.stat().st_size,
                    'sha256': _digest(database), 'schema_before': schema,
                    'integrity_check': 'ok',
                    'scope': 'database only; commit identifies incoming release, not previous image',
                }
                manifest = staging / 'manifest.json'
                with manifest.open('x') as file:
                    os.chmod(manifest, 0o600)
                    json.dump(info, file, sort_keys=True, indent=2)
                    file.write('\n')
                    file.flush()
                    os.fsync(file.fileno())
                verify_snapshot(staging, run_id, commit)
                _fsync(staging)
                staging.rename(folder)
                _fsync(snapshots)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
        print('[backup] ' + json.dumps({
            'verified': True, 'run_id': run_id,
            'database_bytes': info['database_bytes'], 'sha256': info['sha256'],
            'integrity_check': 'ok',
        }), flush=True)
        yield info
    finally:
        os.close(fd)


def _is_persistent_mount(path: Path) -> bool:
    # ismount() alone does not reliably detect same-filesystem bind mounts.
    return any(line.split()[4] == str(path)
               for line in Path('/proc/self/mountinfo').read_text().splitlines())


@contextmanager
def before_migrations(database_path: str):
    """Production boundary used by env.py before it opens a writable connection."""
    environment = os.getenv('ENV', 'production').strip().lower()
    if environment in {'test', 'testing', 'development', 'dev'}:
        yield None
        return
    # Unrecognized/empty ENV is NOT a bypass.
    if Path(database_path).resolve() != DATABASE_PATH or not _is_persistent_mount(BACKUP_ROOT):
        raise BackupError('Expected production database and persistent /backups bind mount')
    with snapshot_gate(DATABASE_PATH, BACKUP_ROOT,
                       os.getenv('HF_DEPLOY_RUN', ''), os.getenv('HF_DEPLOY_COMMIT', ''),
                       delete_journal=True) as receipt:
        yield receipt
