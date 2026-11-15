"""Additive schema 6 and honest, complete historical-schema compatibility."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from crypto_reconciliation_lab import Store, reconcile
from crypto_reconciliation_lab.demo import fixtures, BALANCE_AT, KNOWLEDGE_AT
from crypto_reconciliation_lab.migrations import (
    application_snapshot, assert_preserved, migrate_connection, migrate_database,
    transaction, validate_current, validate_runtime, validate_schema,
)
from crypto_reconciliation_lab.provenance.common import ProvenanceError
from crypto_reconciliation_lab.provenance.exporter import export_provenance
from crypto_reconciliation_lab.review.adapter import read_selected_sources
from review_fixtures import create_selection


class RecordedExecutionMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='execution-migration-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config, self.rows, _ = fixtures()

    def populated(self, name='legacy.sqlite', version=5):
        path = self.root / name
        with closing(Store(path, self.config, target_schema=version)) as store:
            for row in self.rows:
                store.ingest(row['record'], row['received_at'])
            result = reconcile(store, BALANCE_AT, KNOWLEDGE_AT)
        return path, result

    def test_default_six_and_explicit_five_are_real_distinct_physical_layouts(self):
        for version in (5, 6):
            with self.subTest(version=version), closing(Store(
                    self.root / f'{version}.db', self.config,
                    **({'target_schema': 5} if version == 5 else {}))) as store:
                self.assertTrue(validate_schema(store.db, version))
                self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], version)
                self.assertEqual([r[0] for r in store.db.execute('SELECT version FROM schema_migrations ORDER BY version')],
                                 [2, 3, 4, 5] if version == 5 else [2, 3, 4, 5, 6])
                names = {r[0] for r in store.db.execute('SELECT name FROM sqlite_master')}
                self.assertEqual('execution_contexts' in names, version == 6)
                self.assertEqual('recorded_executions' in names, version == 6)
                self.assertEqual('recorded_executions_run' in names, version == 6)

    def test_schema_five_open_is_read_only_and_ordinary_calculation_stays_supported(self):
        path, expected = self.populated()
        before = path.read_bytes()
        with closing(Store(path)) as store:
            self.assertTrue(validate_runtime(store.db))
            self.assertEqual(store.read_run(expected['run_id']), expected)
            with self.assertRaisesRegex(ValueError, 'MIGRATION_REQUIRED'):
                validate_current(store.db)
        self.assertEqual(path.read_bytes(), before)
        with closing(Store(path)) as store:
            self.assertEqual(reconcile(store, BALANCE_AT, KNOWLEDGE_AT), expected)
            self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 5)

    def test_populated_five_migrates_with_backup_full_preservation_restore_and_idempotency(self):
        path, expected = self.populated()
        with closing(sqlite3.connect(path)) as db:
            before = application_snapshot(db)
        result = migrate_database(path, self.root / 'backups')
        self.assertEqual((result['status'], result['from_version'], result['schema_version']), ('MIGRATED', 5, 6))
        for key in ('all_old_columns_equal', 'all_old_tables_equal', 'all_old_objects_equal',
                    'copy_rollback_verified', 'copy_restore_verified', 'idempotency_verified'):
            self.assertTrue(result[key], key)
        with closing(Store(path)) as store:
            assert_preserved(store.db, before)
            self.assertEqual(store.read_run(expected['run_id']), expected)
            self.assertEqual(store.db.execute('SELECT count(*) FROM execution_contexts').fetchone()[0], 0)
            self.assertEqual(store.db.execute('SELECT count(*) FROM recorded_executions').fetchone()[0], 0)
        with closing(sqlite3.connect(result['backup'])) as backup:
            self.assertEqual(application_snapshot(backup), before)
        self.assertEqual(migrate_database(path, self.root / 'unused')['status'], 'ALREADY_CURRENT')

    def test_every_schema_six_fault_rolls_back_all_new_objects_and_metadata(self):
        for point in ('migration_before_execution', 'migration_after_execution_tables',
                      'migration_after_schema6', 'migration_before_commit'):
            with self.subTest(point=point):
                path, _ = self.populated(point + '.db')
                with closing(sqlite3.connect(path, isolation_level=None)) as db:
                    before = application_snapshot(db)
                    def fail(actual):
                        if actual == point:
                            raise RuntimeError(point)
                    with self.assertRaisesRegex(RuntimeError, point):
                        migrate_connection(db, fail)
                    self.assertFalse(db.in_transaction)
                    self.assertEqual(application_snapshot(db), before)

    def test_initializer_and_migration_never_downgrade_or_accept_future_versions(self):
        for index, target in enumerate((5.0, 6.0, True, 4, 7)):
            destination = self.root / f'invalid-target-{index}.db'
            with self.subTest(initializer_target=target), self.assertRaises(ValueError):
                Store(destination, self.config, target_schema=target)
            self.assertFalse(destination.exists())
        path, _ = self.populated(version=6)
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            Store(path, target_schema=5)
        self.assertEqual(path.read_bytes(), before)
        with closing(sqlite3.connect(path, isolation_level=None)) as db:
            for target in (5, 7, True):
                with self.subTest(target=target), self.assertRaises(ValueError):
                    migrate_connection(db, target_version=target)
            db.execute('PRAGMA user_version=7')
            changed = application_snapshot(db)
            with self.assertRaisesRegex(ValueError, 'MIGRATION_REQUIRED'):
                validate_runtime(db)
            with self.assertRaisesRegex(ValueError, 'unsupported schema'):
                validate_schema(db, 7)
            self.assertEqual(application_snapshot(db), changed)

    def test_explicit_historical_validation_rejects_each_missing_guard_layer(self):
        for name in ('immutable_runs_UPDATE', 'immutable_correction_effects_DELETE',
                     'delivery_effects_strict_next', 'immutable_auth_keys_UPDATE'):
            with self.subTest(name=name):
                path, _ = self.populated(name + '.db')
                with closing(sqlite3.connect(path, isolation_level=None)) as db:
                    db.execute('DROP TRIGGER ' + name)
                    before = application_snapshot(db)
                    with self.assertRaisesRegex(ValueError, 'SCHEMA_INVALID'):
                        validate_schema(db, 5)
                    self.assertEqual(application_snapshot(db), before)

    def test_historical_validation_rejects_altered_financial_and_correction_table_definitions(self):
        for name in ('findings', 'correction_effects'):
            with self.subTest(name=name):
                path, _ = self.populated(name + '.db')
                with closing(sqlite3.connect(path, isolation_level=None)) as db:
                    # A caller-created extension column cannot be mistaken for the
                    # complete historical table definition.
                    db.execute('ALTER TABLE ' + name + ' ADD COLUMN unexpected TEXT')
                    before = application_snapshot(db)
                    with self.assertRaisesRegex(ValueError, 'SCHEMA_INVALID'):
                        validate_schema(db, 5)
                    self.assertEqual(application_snapshot(db), before)

    def test_five_rejects_hidden_future_objects_without_rejecting_unrelated_extensions(self):
        path, _ = self.populated()
        with closing(sqlite3.connect(path, isolation_level=None)) as db:
            db.execute('CREATE TABLE unrelated_extension (value BLOB)')
            db.execute("INSERT INTO unrelated_extension VALUES (X'00ff')")
            self.assertTrue(validate_schema(db, 5))
            db.execute('CREATE TABLE execution_contexts (value TEXT)')
            before = application_snapshot(db)
            with self.assertRaisesRegex(ValueError, 'future execution objects'):
                validate_schema(db, 5)
            self.assertEqual(application_snapshot(db), before)

    def test_new_tables_enforce_append_only_foreign_keys_types_and_local_uniqueness(self):
        path, run = self.populated(version=6)
        with closing(Store(path)) as store:
            db = store.db
            db.execute('INSERT INTO execution_contexts VALUES (?,?,?)', ('a'*64, 'recorded-execution-v1', b'{}'))
            row = ('b'*64, 'request-1', 'c'*64, b'{}', run['run_id'], 'd'*64, 'a'*64)
            db.execute('INSERT INTO recorded_executions VALUES (?,?,?,?,?,?,?)', row)
            for table in ('execution_contexts', 'recorded_executions'):
                for sql in ('DELETE FROM ' + table, 'UPDATE ' + table + ' SET ' +
                            ('context_hash=context_hash' if table == 'execution_contexts' else 'request_id=request_id')):
                    with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, 'append-only'):
                        db.execute(sql)
            db.execute('INSERT INTO execution_contexts VALUES (?,?,?)', ('e'*64, 'recorded-execution-v1', b'{}'))
            for candidate in (
                    ('f'*64, *row[1:6], 'e'*64),
                    ('f'*64, 'request-2', *row[2:]),
                    ('f'*64, 'request-2', *row[2:6], 'f'*64),
                    ('f'*64, 'bad request', *row[2:6], 'e'*64),
                    ('f'*64, 'request-2', row[2], '{}', *row[4:6], 'e'*64)):
                with self.subTest(candidate=candidate[:2]), self.assertRaises(sqlite3.IntegrityError):
                    db.execute('INSERT INTO recorded_executions VALUES (?,?,?,?,?,?,?)', candidate)
            for payload in ('{}', b'', b'x' * (16 * 1024 * 1024 + 1)):
                with self.subTest(length=len(payload)), self.assertRaises(sqlite3.IntegrityError):
                    db.execute('INSERT INTO execution_contexts VALUES (?,?,?)', ('f'*64, 'recorded-execution-v1', payload))
            self.assertEqual(db.execute('SELECT count(*) FROM recorded_executions').fetchone()[0], 1)
            self.assertEqual(list(db.execute('PRAGMA foreign_key_check')), [])

    def test_migration_and_transaction_reject_caller_owned_transaction_unchanged(self):
        path, _ = self.populated()
        with closing(sqlite3.connect(path, isolation_level=None)) as db:
            db.execute('BEGIN')
            before = application_snapshot(db)
            with self.assertRaisesRegex(ValueError, 'nested transaction'):
                migrate_connection(db)
            with self.assertRaisesRegex(ValueError, 'nested transaction'):
                with transaction(db):
                    self.fail('must not enter nested body')
            self.assertTrue(db.in_transaction)
            self.assertEqual(application_snapshot(db), before)
            db.execute('ROLLBACK')

    def test_provenance_v1_accepts_real_five_and_rejects_six_without_source_changes(self):
        materials = self.root / 'materials'; materials.mkdir()
        for version in (5, 6):
            path, run = self.populated(f'provenance-{version}.db', version)
            before = path.read_bytes()
            output = self.root / f'bundle-{version}'
            if version == 5:
                self.assertEqual(export_provenance(path, run['run_id'], materials, output)['status'], 'CREATED')
                self.assertEqual(json.loads((output / 'capture.json').read_bytes())['schema_version'], 5)
            else:
                with self.assertRaises(ProvenanceError) as raised:
                    export_provenance(path, run['run_id'], materials, output)
                self.assertEqual(raised.exception.code, 'PROVENANCE_SCHEMA')
                self.assertFalse(output.exists())
            self.assertEqual(path.read_bytes(), before)

    def test_financial_review_explicitly_reads_six_without_mutation_or_recalculation(self):
        path, run = self.populated(version=6)
        selection = create_selection(self.root / 'selection', [('six', path, [run['run_id']])])
        before = path.read_bytes()
        report = read_selected_sources(selection)
        self.assertEqual(report.runs[0].run_id, run['run_id'])
        self.assertEqual(report.runs[0].schema_version, 6)
        self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
