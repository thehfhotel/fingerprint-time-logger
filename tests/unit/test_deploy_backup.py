"""Real SQLite backups + Alembic ordering, without production access."""
from contextlib import contextmanager, closing
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('tested_deploy_backup', ROOT / 'app/services/deploy_backup.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)
COMMIT = 'a' * 40
RUN = '12345-1'


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.source = self.path / 'attendance.db'
        self.dest = self.path / 'backups'
        with closing(sqlite3.connect(self.source)) as db:
            db.executescript('''
                CREATE TABLE employees(id INTEGER PRIMARY KEY, name TEXT);
                CREATE TABLE attendance_records(id INTEGER PRIMARY KEY, note TEXT);
                CREATE TABLE alembic_version(version_num TEXT PRIMARY KEY);
                INSERT INTO alembic_version VALUES ('base01');
                INSERT INTO employees VALUES (1, 'Private test name');
                INSERT INTO attendance_records VALUES (1, 'Private attendance');
            ''')
        self.env = patch.dict(os.environ, {'ENV': 'production',
                             'HF_DEPLOY_RUN': RUN, 'HF_DEPLOY_COMMIT': COMMIT})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.output = io.StringIO()
        self.redirect = patch('sys.stdout', self.output)
        self.redirect.start()
        self.addCleanup(self.redirect.stop)

    def gate(self, **kwargs):
        return backup.snapshot_gate(self.source, self.dest, RUN, COMMIT, **kwargs)

    def snapshot(self):
        return self.dest / 'snapshots' / RUN

    def test_backup_complete_private_and_readable(self):
        with self.gate() as receipt:
            self.assertEqual(receipt['schema_before'], ['base01'])
        folder = self.snapshot()
        with closing(sqlite3.connect(folder / 'attendance.db')) as db:
            self.assertEqual(db.execute('SELECT name FROM employees').fetchone()[0], 'Private test name')
        self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.dest.stat().st_mode & 0o777, 0o700)
        for file in ['attendance.db', 'manifest.json']:
            self.assertEqual((folder / file).stat().st_mode & 0o777, 0o600)
        self.assertNotIn('Private', self.output.getvalue())
        self.assertIn('"verified": true', self.output.getvalue())

    def test_retry_preserves_original_snapshot(self):
        with self.gate():
            pass
        original = (self.snapshot() / 'attendance.db').read_bytes()
        with closing(sqlite3.connect(self.source)) as db:
            db.execute("UPDATE employees SET name='after migration'")
            db.commit()
        with self.gate():
            pass
        self.assertEqual((self.snapshot() / 'attendance.db').read_bytes(), original)
        self.assertEqual(len(list((self.dest / 'snapshots').iterdir())), 1)

    def test_new_workflow_attempt_gets_new_snapshot(self):
        with self.gate():
            pass
        with backup.snapshot_gate(self.source, self.dest, '12345-2', COMMIT):
            pass
        self.assertEqual(len(list((self.dest / 'snapshots').iterdir())), 2)

    def test_different_commit_cannot_reuse_snapshot(self):
        with self.gate():
            pass
        with self.assertRaises(backup.BackupError):
            with backup.snapshot_gate(self.source, self.dest, RUN, 'b' * 40):
                self.fail('must not migrate')

    def test_missing_source_never_creates_empty_database(self):
        self.source.unlink()
        with self.assertRaises(FileNotFoundError):
            with self.gate():
                self.fail('must not migrate')
        self.assertFalse(self.source.exists())

    def test_empty_source_blocks(self):
        self.source.write_bytes(b'')
        with self.assertRaises(backup.BackupError):
            with self.gate():
                self.fail('must not migrate')

    def test_corrupt_database_blocks(self):
        self.source.write_bytes(b'not a sqlite database' * 100)
        with self.assertRaises(sqlite3.DatabaseError):
            with self.gate():
                self.fail('must not migrate')
        self.assertFalse(self.snapshot().exists())

    def test_wrong_database_blocks(self):
        with closing(sqlite3.connect(self.source)) as db:
            db.execute('DROP TABLE employees')
            db.commit()
        with self.assertRaises(backup.BackupError):
            with self.gate():
                self.fail('must not migrate')

    def test_missing_migration_version_blocks(self):
        with closing(sqlite3.connect(self.source)) as db:
            db.execute('DROP TABLE alembic_version')
            db.commit()
        with self.assertRaises(backup.BackupError):
            with self.gate():
                self.fail('must not migrate')

    def test_space_failure_blocks(self):
        with patch.object(backup.shutil, 'disk_usage', return_value=SimpleNamespace(free=1)):
            with self.assertRaises(backup.BackupError):
                with self.gate():
                    self.fail('must not migrate')
        self.assertFalse(self.snapshot().exists())

    def test_copy_failure_never_publishes_snapshot(self):
        with patch.object(backup, '_copy_database', side_effect=OSError('test write failure')):
            with self.assertRaises(OSError):
                with self.gate():
                    self.fail('must not migrate')
        self.assertEqual(list((self.dest / 'snapshots').iterdir()), [])

    def test_copy_deadline_blocks(self):
        with self.assertRaises(backup.BackupError):
            with self.gate(copy_timeout=-1):
                self.fail('must not migrate')
        self.assertFalse(self.snapshot().exists())

    def test_checksum_tampering_blocks_reuse(self):
        with self.gate():
            pass
        with (self.snapshot() / 'attendance.db').open('ab') as file:
            file.write(b'tamper')
        with self.assertRaises(backup.BackupError):
            with self.gate():
                self.fail('must not migrate')

    def test_manifest_tampering_blocks_reuse(self):
        with self.gate():
            pass
        file = self.snapshot() / 'manifest.json'
        data = json.loads(file.read_text())
        data['schema_before'] = ['wrong']
        file.write_text(json.dumps(data))
        with self.assertRaises(backup.BackupError):
            with self.gate():
                self.fail('must not migrate')

    def test_source_symlink_blocks(self):
        real = self.source.with_suffix('.real')
        self.source.rename(real)
        self.source.symlink_to(real)
        with self.assertRaises(backup.BackupError):
            with self.gate():
                self.fail('must not migrate')

    def test_root_symlink_blocks(self):
        real = self.path / 'other'
        real.mkdir()
        self.dest.symlink_to(real, target_is_directory=True)
        with self.assertRaises(backup.BackupError):
            with self.gate():
                self.fail('must not migrate')

    def test_snapshot_symlink_blocks(self):
        with self.gate():
            pass
        real = self.dest / 'moved'
        self.snapshot().rename(real)
        self.snapshot().symlink_to(real, target_is_directory=True)
        with self.assertRaises(backup.BackupError):
            with self.gate():
                self.fail('must not migrate')

    def test_lock_kept_through_migration_body(self):
        with self.gate():
            with self.assertRaises(backup.BackupError):
                with self.gate(lock_timeout=0):
                    self.fail('must not interleave migrations')
        with self.gate(lock_timeout=0):
            pass

    def test_migration_exception_preserves_backup_and_unlocks(self):
        with self.assertRaisesRegex(RuntimeError, 'migration failed'):
            with self.gate():
                raise RuntimeError('migration failed')
        self.assertTrue(self.snapshot().is_dir())
        with self.gate(lock_timeout=0):
            pass

    def test_native_backup_captures_live_wal(self):
        with closing(sqlite3.connect(self.source)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA wal_autocheckpoint=0')
            db.execute("INSERT INTO employees VALUES (2, 'WAL data')")
            db.commit()
            self.assertGreater(Path(str(self.source) + '-wal').stat().st_size, 0)
            with self.gate():
                pass
            with closing(sqlite3.connect(self.snapshot() / 'attendance.db')) as restored:
                self.assertEqual(restored.execute('SELECT COUNT(*) FROM employees').fetchone()[0], 2)
                self.assertEqual(restored.execute('PRAGMA journal_mode').fetchone()[0], 'delete')

    def test_file_only_production_mount_rejects_wal(self):
        with closing(sqlite3.connect(self.source)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            with self.assertRaises(backup.BackupError):
                with self.gate(delete_journal=True):
                    self.fail('cannot assume old container WAL is on the host')

    def test_invalid_run_id_blocks(self):
        for value in ['', '../escape', '123;true', '12345', '-1-1', '1-0']:
            with self.subTest(value=value), self.assertRaises(backup.BackupError):
                with backup.snapshot_gate(self.source, self.dest, value, COMMIT):
                    self.fail('must not migrate')

    def test_invalid_commit_blocks(self):
        for value in ['', 'latest', 'a' * 7, 'a' * 40 + '\n']:
            with self.subTest(value=value), self.assertRaises(backup.BackupError):
                with backup.snapshot_gate(self.source, self.dest, RUN, value):
                    self.fail('must not migrate')

    def test_production_requires_mount(self):
        with patch.object(backup, 'DATABASE_PATH', self.source), \
             patch.object(backup, '_is_persistent_mount', return_value=False):
            with self.assertRaises(backup.BackupError):
                with backup.before_migrations(str(self.source)):
                    self.fail('must not migrate')

    def test_production_rejects_wrong_database(self):
        with patch.object(backup, '_is_persistent_mount', return_value=True):
            with self.assertRaises(backup.BackupError):
                with backup.before_migrations(str(self.source)):
                    self.fail('must not migrate')

    def test_production_requires_ci_metadata(self):
        with patch.object(backup, 'DATABASE_PATH', self.source), \
             patch.object(backup, 'BACKUP_ROOT', self.dest), \
             patch.object(backup, '_is_persistent_mount', return_value=True), \
             patch.dict(os.environ, {'HF_DEPLOY_RUN': ''}):
            with self.assertRaises(backup.BackupError):
                with backup.before_migrations(str(self.source)):
                    self.fail('must not migrate')

    def test_unknown_environment_is_not_a_bypass(self):
        for value in ['', 'prod', 'PRODUCTION', 'unknown']:
            with self.subTest(value=value), patch.dict(os.environ, {'ENV': value}):
                with self.assertRaises(backup.BackupError):
                    with backup.before_migrations(str(self.source)):
                        self.fail('must not migrate')

    def test_explicit_test_environment_does_not_touch_host(self):
        with patch.dict(os.environ, {'ENV': 'test'}):
            with backup.before_migrations(str(self.source)) as result:
                self.assertIsNone(result)
        self.assertFalse(self.dest.exists())

    def test_persistent_mount_parser(self):
        with patch.object(Path, 'read_text', return_value='9 4 8:1 /foo /backups rw - ext4 /dev/sda rw\n'):
            self.assertTrue(backup._is_persistent_mount(Path('/backups')))
            self.assertFalse(backup._is_persistent_mount(Path('/not-mounted')))

    def _alembic(self):
        """Real Alembic runs the actual repo env.py; only app metadata is isolated."""
        import sqlalchemy as sa
        from alembic.config import Config
        script = self.path / 'migrations'
        script.mkdir()
        (script / 'versions').mkdir()
        shutil.copy(ROOT / 'database/migrations/env.py', script / 'env.py')
        (script / 'versions/base.py').write_text(
            "revision='base01'\ndown_revision=None\ndef upgrade(): pass\ndef downgrade(): pass\n")
        (script / 'versions/next.py').write_text(
            "from alembic import op\nimport sqlalchemy as sa\nrevision='next02'\ndown_revision='base01'\n"
            "def upgrade():\n op.create_table('migration_probe',sa.Column('id',sa.Integer,primary_key=True))\n"
            "def downgrade():\n op.drop_table('migration_probe')\n")
        config = Config()
        config.set_main_option('script_location', str(script))
        config.set_main_option('sqlalchemy.url', 'sqlite:///' + str(self.source))
        models = ModuleType('app.models.models')
        models.Base = SimpleNamespace(metadata=sa.MetaData())
        model_package = ModuleType('app.models')
        model_package.staff_leave = ModuleType('app.models.staff_leave')
        overrides = {
            'app.models.models': models, 'app.models': model_package,
            'app.models.staff_leave': model_package.staff_leave,
            'app.services.deploy_backup': backup,
        }
        return config, overrides

    def test_actual_alembic_hook_backs_up_before_schema_change(self):
        from alembic import command
        config, overrides = self._alembic()
        with patch.dict(sys.modules, overrides), \
             patch.object(backup, 'DATABASE_PATH', self.source), \
             patch.object(backup, 'BACKUP_ROOT', self.dest), \
             patch.object(backup, '_is_persistent_mount', return_value=True):
            command.upgrade(config, 'head')
        with closing(sqlite3.connect(self.source)) as live:
            self.assertEqual(live.execute('SELECT version_num FROM alembic_version').fetchone()[0], 'next02')
        with closing(sqlite3.connect(self.snapshot() / 'attendance.db')) as old:
            self.assertEqual(old.execute('SELECT version_num FROM alembic_version').fetchone()[0], 'base01')
            self.assertIsNone(old.execute("SELECT name FROM sqlite_master WHERE name='migration_probe'").fetchone())

    def test_actual_alembic_hook_failure_prevents_schema_change(self):
        from alembic import command
        config, overrides = self._alembic()
        @contextmanager
        def fail(_):
            raise backup.BackupError('simulated backup failure')
            yield  # pragma: no cover
        with patch.dict(sys.modules, overrides), patch.object(backup, 'before_migrations', fail):
            with self.assertRaises(backup.BackupError):
                command.upgrade(config, 'head')
        with closing(sqlite3.connect(self.source)) as live:
            self.assertEqual(live.execute('SELECT version_num FROM alembic_version').fetchone()[0], 'base01')
            self.assertIsNone(live.execute("SELECT name FROM sqlite_master WHERE name='migration_probe'").fetchone())

    def _ready_client(self):
        import importlib
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        readiness = importlib.import_module('app.api.deployment_ready')
        readiness._verified.cache_clear()
        self.addCleanup(readiness._verified.cache_clear)
        root_patch = patch.object(readiness.deploy_backup, 'BACKUP_ROOT', self.dest)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        app = FastAPI()
        app.include_router(readiness.router, prefix='/api/public/staff-oa')
        return TestClient(app), readiness

    def test_readiness_requires_exact_release_and_verified_snapshot(self):
        client, _ = self._ready_client()
        with self.gate():
            pass
        params = {'run_id': RUN, 'commit': COMMIT}
        result = client.get('/api/public/staff-oa/webhook', params=params)
        self.assertEqual(result.status_code, 204)
        self.assertEqual(result.content, b'')
        self.assertEqual(result.headers['cache-control'], 'no-store')
        for changed in [{'run_id': '12345-2', 'commit': COMMIT},
                        {'run_id': RUN, 'commit': 'b'*40}]:
            self.assertEqual(client.get('/api/public/staff-oa/webhook', params=changed).status_code, 503)

    def test_readiness_missing_snapshot_cannot_claim_success(self):
        client, _ = self._ready_client()
        response = client.get('/api/public/staff-oa/webhook', params={'run_id': RUN, 'commit': COMMIT})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content, b'')

    def test_readiness_rejects_corrupt_snapshot(self):
        with self.gate():
            pass
        (self.snapshot() / 'attendance.db').write_bytes(b'corrupt')
        client, _ = self._ready_client()
        self.assertEqual(client.get('/api/public/staff-oa/webhook',
                                   params={'run_id': RUN, 'commit': COMMIT}).status_code, 503)

    def test_readiness_does_not_handle_post_or_untrusted_paths(self):
        client, readiness = self._ready_client()
        self.assertEqual(client.post('/api/public/staff-oa/webhook').status_code, 405)
        with patch.object(readiness, '_verified') as verify:
            self.assertEqual(client.get('/api/public/staff-oa/webhook',
                                       params={'run_id': '../escape', 'commit': COMMIT}).status_code, 422)
            self.assertEqual(client.get('/api/public/staff-oa/webhook',
                                       params={'run_id': '99999-1', 'commit': COMMIT}).status_code, 503)
            verify.assert_not_called()

    def test_cd_contract(self):
        workflow = (ROOT / '.github/workflows/build.yml').read_text()
        compose = (ROOT / 'docker-compose.yml').read_text()
        self.assertIn('HF_DEPLOY_RUN=${{ github.run_id }}-${{ github.run_attempt }}', workflow)
        self.assertIn('HF_DEPLOY_COMMIT=${{ github.sha }}', workflow)
        self.assertIn('needs: [test]', workflow)
        self.assertNotIn('FINGERPRINT_BACKUP_READY', workflow)
        self.assertNotIn('install_host.py', workflow)
        self.assertIn('/home/deploy/backups/fingerprint-time-logger:/backups', compose)
        self.assertIn('HF_DEPLOY_RUN=${HF_DEPLOY_RUN:-}', compose)
        self.assertIn('HF_DEPLOY_COMMIT=${HF_DEPLOY_COMMIT:-}', compose)
        self.assertNotIn('/var/run/docker.sock', compose)
        self.assertIn('needs: [deploy]', workflow)
        self.assertIn('[ \"$status\" = 204 ]', workflow)
        self.assertNotIn('curl -L', workflow)
        source = (ROOT / 'app/api/staff_oa.py').read_text()
        self.assertIn('router.include_router(deployment_ready_router)', source)
        self.assertIn('@router.post(\"/webhook\")', source)


if __name__ == '__main__':
    unittest.main()
