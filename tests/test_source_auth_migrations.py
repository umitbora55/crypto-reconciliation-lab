"""Independent historical-layout migration and public unsigned admission guards."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from crypto_reconciliation_lab import Store
from crypto_reconciliation_lab.demo import fixtures
from crypto_reconciliation_lab.migrations import (application_snapshot, assert_preserved,
    migrate_connection, migrate_database, validate_current)
from crypto_reconciliation_lab.source_auth.schema import AUTH_TABLES
from test_admission_migrations import schema3_history, old_rows
from source_auth_legacy_fixtures import install_historical_schema4


class SourceAuthMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config, self.rows, _ = fixtures()

    def historical(self, name='history.db'):
        path = self.root / name
        db, data = schema3_history(path)
        install_historical_schema4(db)
        return path, db, data

    def test_schema4_open_read_is_byte_and_logically_unchanged(self):
        path, db, _ = self.historical()
        with closing(db):
            before = application_snapshot(db)
        original = path.read_bytes()
        with closing(Store(path)) as store:
            self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 4)
            self.assertEqual(application_snapshot(store.db), before)
            self.assertFalse(store.db.execute("SELECT 1 FROM sqlite_master WHERE name='auth_configuration'").fetchone())
        self.assertEqual(path.read_bytes(), original)

    def test_populated_schema4_explicit_backup_restore_and_preservation(self):
        path, db, _ = self.historical()
        with closing(db):
            before = application_snapshot(db)
            rows = old_rows(db)
        result = migrate_database(path, self.root / 'backups')
        self.assertEqual(result['status'], 'MIGRATED')
        with closing(Store(path)) as store:
            self.assertTrue(validate_current(store.db))
            self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 5)
            assert_preserved(store.db, before)
            for name, expected in rows.items():
                query = f'SELECT * FROM "{name}"' + (' WHERE version<=4' if name == 'schema_migrations' else '') + ' ORDER BY rowid'
                self.assertEqual([tuple(r) for r in store.db.execute(query)], expected)
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM auth_configuration').fetchone()[0], 0)
            self.assertFalse(store.db.execute('PRAGMA foreign_key_check').fetchall())
        backups = list((self.root / 'backups').glob('*.schema4.sqlite3'))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as restored:
            self.assertEqual(application_snapshot(restored), before)
        self.assertEqual(migrate_database(path, self.root / 'unused')['status'], 'ALREADY_CURRENT')

    def test_every_schema5_fault_rolls_back_entire_upgrade(self):
        for point in ('migration_before_auth', 'migration_after_auth_tables', 'migration_after_schema5', 'migration_before_commit'):
            with self.subTest(point=point):
                _, db, _ = self.historical(point + '.db')
                with closing(db):
                    before = application_snapshot(db)
                    def fail(actual):
                        if actual == point:
                            raise RuntimeError(point)
                    with self.assertRaisesRegex(RuntimeError, point):
                        migrate_connection(db, fail)
                    self.assertEqual(application_snapshot(db), before)

    def test_new_database_chain_and_no_implicit_protection(self):
        with closing(Store(self.root / 'new.db', self.config)) as store:
            self.assertEqual([r[0] for r in store.db.execute('SELECT version FROM schema_migrations ORDER BY version')], [2, 3, 4, 5])
            for table in AUTH_TABLES:
                self.assertEqual(store.db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0], 0)
            self.assertEqual(store.ingest(self.rows[0]['record'], self.rows[0]['received_at'])['status'], 'ACCEPTED')

    def protected_marker(self):
        # Public guards depend only on the immutable mode marker. Full policy and
        # signature flows are covered separately with real cryptography.
        store = Store(self.root / 'protected.db', self.config)
        self.addCleanup(store.close)
        store.db.execute('INSERT INTO auth_configuration VALUES (1,?,?,?)', ('test', 'a'*64, 'b'*64))
        return store

    def test_store_unsigned_guard_is_before_first_financial_receipt(self):
        store = self.protected_marker()
        before = application_snapshot(store.db)
        with self.assertRaisesRegex(ValueError, 'SOURCE_AUTH_REQUIRED'):
            store.ingest(self.rows[0]['record'], self.rows[0]['received_at'])
        self.assertEqual(application_snapshot(store.db), before)

    def test_module_and_store_delivery_paths_cannot_bypass_guard(self):
        from crypto_reconciliation_lab.admission.runtime import ingest_delivery
        store = self.protected_marker()
        data = json.dumps(self.rows[0]).encode() + b'\n'
        plan = {'format':'admission-plan-v1','input_sha256':hashlib.sha256(data).hexdigest(),
                'input_bytes':len(data),'planned_lines':1,'framing':'utf8-lf-jsonl-v1'}
        before = application_snapshot(store.db)
        for call in (lambda: store.ingest_delivery('unused', 1, data, plan),
                     lambda: ingest_delivery(store, 'unused', 1, data, plan)):
            with self.assertRaisesRegex(ValueError, 'SOURCE_AUTH_REQUIRED'):
                call()
            self.assertEqual(application_snapshot(store.db), before)

    def test_guard_requires_write_transaction_and_marker_cannot_be_removed(self):
        from crypto_reconciliation_lab.source_auth.schema import reject_unsigned
        store = self.protected_marker()
        with self.assertRaisesRegex(ValueError, 'owned transaction'):
            reject_unsigned(store.db)
        for sql in ('DELETE FROM auth_configuration', "UPDATE auth_configuration SET receiver='other'"):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'append-only'):
                store.db.execute(sql)

    def test_missing_schema5_guard_is_rejected_without_repair(self):
        path = self.root / 'broken.db'
        with closing(Store(path, self.config)) as store:
            store.db.execute('DROP TRIGGER immutable_auth_configuration_DELETE')
        with self.assertRaisesRegex(ValueError, 'SCHEMA_INVALID'):
            Store(path)
