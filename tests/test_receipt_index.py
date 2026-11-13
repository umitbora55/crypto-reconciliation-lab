"""Physical-index and migration invariants; expected history is a frozen 0.3.2 fixture."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from crypto_reconciliation_lab import Store, reconcile
from crypto_reconciliation_lab.demo import BALANCE_AT, KNOWLEDGE_AT, fixtures
from crypto_reconciliation_lab.migrations import (
    INDEX_NAME, INDEX_SQL, application_snapshot, assert_preserved, backup_database,
    index_inventory, migrate_connection, migrate_database, query_plans, validate_current,
)

ROOT = Path(__file__).resolve().parents[1]


def schema2_fixture(path):
    data = json.loads((ROOT / 'fixtures/stage3_3_schema2_history.json').read_text())
    db = sqlite3.connect(path, isolation_level=None)
    for kind in ('table', 'index'):
        for obj in data['objects']:
            if obj['type'] == kind and obj['sql']:
                db.execute(obj['sql'])
    for table, content in data['tables'].items():
        placeholders = ','.join('?' for _ in content['columns'])
        db.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', content['rows'])
    for obj in data['objects']:
        if obj['type'] == 'trigger':
            db.execute(obj['sql'])
    db.execute('PRAGMA user_version=2')
    db.execute('PRAGMA foreign_keys=ON')
    return db, data


class ReceiptIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.config, self.rows, _ = fixtures()

    def old(self, filename='old.sqlite3'):
        db, data = schema2_fixture(self.path / filename)
        self.addCleanup(db.close)
        return db, data

    def fresh(self):
        store = Store(self.path / 'new.sqlite3', self.config)
        self.addCleanup(store.close)
        return store

    def test_fresh_index_is_exactly_one_nonunique_binary_ascending_column(self):
        store = self.fresh()
        validate_current(store.db)
        self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 3)
        listed = {r[1]: r for r in store.db.execute('PRAGMA index_list(receipts)')}
        self.assertEqual(set(listed), {'receipts_time', INDEX_NAME})
        self.assertEqual(tuple(listed[INDEX_NAME][2:]), (0, 'c', 0))
        keys = [tuple(r) for r in store.db.execute(f'PRAGMA index_xinfo({INDEX_NAME})') if r[5]]
        self.assertEqual([(r[2], r[3], r[4]) for r in keys], [('receipt_hash', 0, 'BINARY')])

    def test_schema2_all_tables_objects_and_correction_rows_are_preserved(self):
        db, fixture = self.old()
        db.execute('CREATE TABLE extension (id INTEGER PRIMARY KEY, value BLOB, note TEXT COLLATE NOCASE)')
        db.executemany('INSERT INTO extension VALUES (?,?,?)', [(1, b'\x00\xff', 'a'), (2, None, 'A')])
        db.execute('CREATE INDEX extension_note ON extension(note)')
        db.execute("CREATE TRIGGER extension_no_delete BEFORE DELETE ON extension BEGIN SELECT RAISE(ABORT,'retain'); END")
        before = application_snapshot(db)
        self.assertGreater(before['tables']['correction_groups']['rows'], 0)
        self.assertGreater(before['tables']['correction_effects']['rows'], 0)
        old_meta = list(db.execute('SELECT * FROM schema_migrations'))
        old_runs = list(db.execute('SELECT id,payload FROM runs ORDER BY id'))
        self.assertTrue(migrate_connection(db))
        assert_preserved(db, before)
        self.assertEqual(list(db.execute('SELECT * FROM schema_migrations WHERE version=2')), old_meta)
        self.assertEqual(list(db.execute('SELECT id,payload FROM runs ORDER BY id')), old_runs)
        self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        after = application_snapshot(db)
        self.assertFalse(migrate_connection(db))
        self.assertEqual(application_snapshot(db), after)
        self.assertEqual(set(fixture['run_ids']), {r[0] for r in old_runs})

    def test_schema0_transition_keeps_literal_old_metadata_and_rolls_back_atomically(self):
        schema = json.loads((ROOT / 'docs/stage2/baseline-schema.json').read_text())
        # The frozen baseline file has the literal Stage 1 definitions, independently of new DDL.
        self.assertIsInstance(schema, list)
        db = sqlite3.connect(self.path / 'zero.sqlite3', isolation_level=None)
        self.addCleanup(db.close)
        for kind in ('table', 'index', 'trigger'):
            for typ, name, sql in schema:
                if typ == kind and sql:
                    db.execute(sql)
        before = application_snapshot(db)
        for point in ('migration_after_group_table', 'migration_after_schema2',
                      'migration_before_index', 'migration_after_index', 'migration_before_commit'):
            def fail(current, target=point):
                if current == target:
                    raise RuntimeError('controlled migration failure')
            with self.assertRaisesRegex(RuntimeError, 'controlled'):
                migrate_connection(db, fail)
            self.assertEqual(application_snapshot(db), before, point)
        self.assertTrue(migrate_connection(db))
        self.assertEqual(db.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall(), [(2,), (3,)])
        self.assertEqual(db.execute('SELECT description FROM schema_migrations WHERE version=2').fetchone()[0],
                         'Add immutable correction groups/effects; retain all Stage 1 columns')
        assert_preserved(db, before)

    def test_schema2_failures_before_and_after_index_restore_everything(self):
        for point in ('migration_before_index', 'migration_after_index', 'migration_before_commit'):
            with self.subTest(point=point):
                db, _ = self.old(point + '.sqlite3')
                before = application_snapshot(db)
                def fail(current):
                    if current == point:
                        raise RuntimeError('controlled migration failure')
                with self.assertRaisesRegex(RuntimeError, 'controlled'):
                    migrate_connection(db, fail)
                self.assertEqual(application_snapshot(db), before)

    def test_wrong_same_name_definitions_are_rejected_without_dropping(self):
        definitions = [
            'CREATE UNIQUE INDEX receipts_hash_lookup ON receipts(receipt_hash)',
            'CREATE INDEX receipts_hash_lookup ON receipts(receipt_hash) WHERE status="ACCEPTED"',
            'CREATE INDEX receipts_hash_lookup ON receipts(raw)',
            'CREATE INDEX receipts_hash_lookup ON receipts(receipt_hash,raw)',
            'CREATE INDEX receipts_hash_lookup ON records(id)',
            'CREATE INDEX receipts_hash_lookup ON receipts(receipt_hash COLLATE NOCASE)',
            'CREATE INDEX receipts_hash_lookup ON receipts(receipt_hash DESC)',
            'CREATE INDEX receipts_hash_lookup ON receipts(lower(receipt_hash))',
            'CREATE TABLE receipts_hash_lookup (receipt_hash TEXT)',
        ]
        for i, statement in enumerate(definitions):
            with self.subTest(statement=statement):
                db, _ = self.old(f'wrong-{i}.sqlite3')
                db.execute(statement)
                before = application_snapshot(db)
                with self.assertRaises((ValueError, sqlite3.DatabaseError)):
                    migrate_connection(db)
                self.assertEqual(application_snapshot(db), before)

    def test_existing_valid_index_is_accepted_and_metadata_is_added(self):
        db, _ = self.old()
        db.execute(INDEX_SQL)
        before = application_snapshot(db)
        self.assertTrue(migrate_connection(db))
        assert_preserved(db, before)
        validate_current(db)
        self.assertEqual(len([r for r in db.execute('PRAGMA index_list(receipts)') if r[1] == INDEX_NAME]), 1)

    def test_corrupt_current_or_future_schema_is_rejected_without_implicit_repair(self):
        cases = ('missing_index', 'wrong_index', 'missing_metadata', 'future')
        for case in cases:
            with self.subTest(case=case):
                path = self.path / (case + '.sqlite3')
                store = Store(path, self.config)
                if case == 'future':
                    store.db.execute('PRAGMA user_version=4')
                else:
                    store.db.execute('DROP INDEX receipts_hash_lookup')
                    if case == 'wrong_index':
                        store.db.execute('CREATE INDEX receipts_hash_lookup ON receipts(raw)')
                    elif case == 'missing_metadata':
                        store.db.execute('CREATE INDEX receipts_hash_lookup ON receipts(receipt_hash)')
                        store.db.execute('DROP TRIGGER immutable_schema_migrations_DELETE')
                        store.db.execute('DELETE FROM schema_migrations WHERE version=3')
                before = application_snapshot(store.db)
                store.close()
                with self.assertRaises(ValueError):
                    Store(path)
                with sqlite3.connect(path) as check:
                    self.assertEqual(application_snapshot(check), before)

    def test_schema2_open_and_read_are_ddl_free_and_save_requires_migration(self):
        db, fixture = self.old()
        before = application_snapshot(db)
        store = Store(self.path / 'old.sqlite3')
        self.addCleanup(store.close)
        for run_id in fixture['run_ids']:
            result = store.read_run(run_id)
            self.assertEqual(result['run_id'], run_id)
            with self.assertRaisesRegex(ValueError, 'MIGRATION_REQUIRED'):
                store.save_run({k: v for k, v in result.items() if k != 'run_id'})
        self.assertEqual(application_snapshot(db), before)

    def test_incomplete_existing_database_is_not_initialized(self):
        path = self.path / 'incomplete.sqlite3'
        db = sqlite3.connect(path, isolation_level=None)
        self.addCleanup(db.close)
        db.execute('CREATE TABLE configuration (id INTEGER PRIMARY KEY, payload TEXT)')
        before = application_snapshot(db)
        with self.assertRaisesRegex(ValueError, 'SCHEMA_INVALID'):
            Store(path, self.config)
        self.assertEqual(application_snapshot(db), before)

    def test_empty_versioned_database_is_rejected_before_any_ddl(self):
        for version in (2, 3, 99):
            with self.subTest(version=version):
                path = self.path / f'empty-schema-{version}.sqlite3'
                db = sqlite3.connect(path, isolation_level=None)
                self.addCleanup(db.close)
                db.execute(f'PRAGMA user_version={version}')
                before = application_snapshot(db)
                with self.assertRaisesRegex(ValueError, 'SCHEMA_INVALID'):
                    Store(path, self.config)
                self.assertEqual(application_snapshot(db), before)

    def test_failed_fresh_open_without_config_keeps_creation_recoverable(self):
        path = self.path / 'missing-config.sqlite3'
        with self.assertRaisesRegex(ValueError, 'new database requires configuration'):
            Store(path)
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute('SELECT name FROM sqlite_master').fetchall(), [])
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 0)
        store = Store(path, self.config)
        self.addCleanup(store.close)
        validate_current(store.db)

    def test_existing_view_only_database_is_not_treated_as_empty(self):
        path = self.path / 'view-only.sqlite3'
        db = sqlite3.connect(path, isolation_level=None)
        self.addCleanup(db.close)
        db.execute('CREATE VIEW configuration AS SELECT 1 AS id, NULL AS payload')
        before = application_snapshot(db)
        with self.assertRaisesRegex(ValueError, 'SCHEMA_INVALID'):
            Store(path, self.config)
        self.assertEqual(application_snapshot(db), before)

    def test_duplicate_raw_variant_conflict_and_invalid_lookup_evidence(self):
        store = self.fresh()
        for row in self.rows:
            store.ingest(row['record'], row['received_at'])
        event = next(r for r in self.rows if r['record']['kind'] == 'event')
        first = store.ingest(event['record'], event['received_at'])
        again = store.ingest(event['record'], event['received_at'])
        self.assertEqual(first['receipt_id'], again['receipt_id'])
        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM receipts WHERE receipt_hash=?',
                                         (first['receipt_id'],)).fetchone()[0], 3)
        original = store.db.execute('SELECT raw FROM receipts WHERE receipt_hash=? LIMIT 1',
                                    (first['receipt_id'],)).fetchone()[0]
        self.assertEqual(json.loads(original)['record'], event['record'])
        later = store.ingest(event['record'], '2026-11-12T06:00:00Z')
        self.assertNotEqual(later['receipt_id'], first['receipt_id'])
        self.assertEqual(later['record_id'], first['record_id'])
        variant = copy.deepcopy(event['record'])
        variant['amount'] += '0' if '.' in variant['amount'] else '.0'
        normalized = store.ingest(variant, event['received_at'])
        self.assertEqual(normalized['record_id'], first['record_id'])
        self.assertNotEqual(normalized['receipt_id'], first['receipt_id'])
        conflict = copy.deepcopy(event['record'])
        conflict['amount'] = '999'
        conflicting = store.ingest(conflict, event['received_at'])
        self.assertEqual(conflicting['status'], 'CONFLICT')
        invalid = store.ingest({'kind': 'event', 'amount': 'NaN'}, event['received_at'])
        self.assertEqual(invalid['status'], 'INVALID')
        for response in (first, later, normalized, conflicting, invalid):
            row = store.db.execute('SELECT raw FROM receipts WHERE receipt_hash=? LIMIT 1',
                                   (response['receipt_id'],)).fetchone()
            self.assertIsNotNone(row)
        records, receipts, invalid_rows = store.known(KNOWLEDGE_AT)
        self.assertIn(invalid['receipt_id'], {row['id'] for row in invalid_rows})
        self.assertNotIn(later['receipt_id'], {h for hashes in receipts.values() for h in hashes})
        self.assertIsNone(store.db.execute('SELECT raw FROM receipts WHERE receipt_hash=? LIMIT 1', ('missing',)).fetchone())

    def test_schema2_duplicate_receipts_and_limit_one_raw_are_unchanged(self):
        db, _ = self.old()
        store = Store(self.path / 'old.sqlite3')
        event = next(r for r in self.rows if r['record']['kind'] == 'event')
        received = [store.ingest(event['record'], event['received_at']) for _ in range(2)]
        receipt_hash = received[0]['receipt_id']
        self.assertEqual(received[1]['receipt_id'], receipt_hash)
        rows_before = [tuple(r) for r in db.execute('SELECT id,raw FROM receipts WHERE receipt_hash=? ORDER BY id', (receipt_hash,))]
        first_before = db.execute('SELECT raw FROM receipts WHERE receipt_hash=? LIMIT 1', (receipt_hash,)).fetchone()[0]
        self.assertEqual(len(rows_before), 3)
        self.assertEqual({r[1] for r in rows_before}, {first_before})
        store.close()
        migrate_connection(db)
        self.assertEqual([tuple(r) for r in db.execute('SELECT id,raw FROM receipts WHERE receipt_hash=? ORDER BY id', (receipt_hash,))], rows_before)
        self.assertEqual(db.execute('SELECT raw FROM receipts WHERE receipt_hash=? LIMIT 1', (receipt_hash,)).fetchone()[0], first_before)

    def test_actual_unforced_query_plans_use_hash_search_after_migration(self):
        db, _ = self.old()
        hashes = [r[0] for r in db.execute('SELECT receipt_hash FROM receipts ORDER BY id')]
        cases = {'early': hashes[0], 'late': hashes[-1], 'missing': 'not-present'}
        for plan in query_plans(db, cases).values():
            self.assertTrue(any('SCAN receipts' in r[3] for r in plan))
        migrate_connection(db)
        for plan in query_plans(db, cases).values():
            self.assertTrue(any('SEARCH receipts USING INDEX receipts_hash_lookup (receipt_hash=?)' in r[3] for r in plan))

    def test_explicit_backup_restore_and_full_database_verification(self):
        db, _ = self.old()
        before = application_snapshot(db)
        db.close()
        report = migrate_database(self.path / 'old.sqlite3', self.path / 'backups')
        self.assertEqual(report['status'], 'MIGRATED')
        self.assertEqual(report['before_digest'], report['after_digest'])
        for key in ('all_old_columns_equal', 'all_old_tables_equal', 'all_old_objects_equal',
                    'copy_rollback_verified', 'copy_restore_verified'):
            self.assertTrue(report[key], key)
        with sqlite3.connect(report['backup']) as backup:
            self.assertEqual(application_snapshot(backup), before)
        restored = self.path / 'restored.sqlite3'
        backup_database(report['backup'], restored)
        with sqlite3.connect(restored) as copy_db:
            self.assertEqual(application_snapshot(copy_db), before)
        with self.assertRaisesRegex(ValueError, 'never overwrite'):
            backup_database(report['backup'], restored)
        self.assertEqual(migrate_database(self.path / 'old.sqlite3', self.path / 'backups')['status'], 'ALREADY_CURRENT')

    def test_existing_backup_with_wrong_starting_version_is_never_overwritten(self):
        db, _ = self.old()
        before = application_snapshot(db)
        def fail(point):
            if point == 'migration_before_commit':
                raise RuntimeError('controlled source failure')
        with self.assertRaisesRegex(RuntimeError, 'controlled source failure'):
            migrate_database(self.path / 'old.sqlite3', self.path / 'backups', fail)
        backup_path = next((self.path / 'backups').glob('*.sqlite3'))
        with sqlite3.connect(backup_path) as backup:
            backup.execute('PRAGMA user_version=77')
            mismatched_backup = application_snapshot(backup)
        with self.assertRaisesRegex(ValueError, 'existing backup does not match'):
            migrate_database(self.path / 'old.sqlite3', self.path / 'backups')
        self.assertEqual(application_snapshot(db), before)
        with sqlite3.connect(backup_path) as backup:
            self.assertEqual(application_snapshot(backup), mismatched_backup)

    def test_migration_rejects_nested_transaction(self):
        db, _ = self.old()
        before = application_snapshot(db)
        db.execute('BEGIN')
        with self.assertRaisesRegex(ValueError, 'transaction'):
            migrate_connection(db)
        db.rollback()
        self.assertEqual(application_snapshot(db), before)


if __name__ == '__main__':
    unittest.main()
