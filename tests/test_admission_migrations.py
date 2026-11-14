"""Additive admission schema and historical read/export preservation."""
import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from crypto_reconciliation_lab import Store
from crypto_reconciliation_lab.demo import fixtures
from crypto_reconciliation_lab.migrations import (
    application_snapshot, backup_database, migrate_connection, migrate_database,
    validate_current,
)
from crypto_reconciliation_lab.review.adapter import Selection, SourceSelection, read_selected_sources

ROOT = Path(__file__).resolve().parents[1]
OBSERVED = '2026-11-13T12:00:00.000000Z'


def schema3_history(path):
    """Independent historical layout: frozen schema 2 plus literal stage-3 DDL."""
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
    db.execute('CREATE INDEX receipts_hash_lookup ON receipts(receipt_hash)')
    db.execute('INSERT INTO schema_migrations VALUES (?,?)',
               (3, 'Add nonunique receipts_hash_lookup(receipt_hash); preserve all financial data'))
    db.execute('PRAGMA user_version=3')
    db.execute('PRAGMA foreign_keys=ON')
    return db, data


def old_rows(db):
    """Direct, independent row readback, not a migration preservation helper."""
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {name: [tuple(row) for row in db.execute(f'SELECT * FROM "{name}" ORDER BY rowid')]
            for name in tables}


class AdmissionMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config, self.rows, _ = fixtures()

    def fresh(self):
        store = Store(self.root / 'current.sqlite3', self.config)
        self.addCleanup(store.close)
        return store

    def bind(self, db, name='stream', payload=b'{}\n', lines=3):
        db.execute('INSERT INTO admission_streams VALUES (?,?,?,?,?,?,?)',
                   (name, hashlib.sha256(payload * lines).hexdigest(), len(payload) * lines,
                    lines, 'utf8-lf-jsonl-v1', 'a' * 64, OBSERVED))

    def effect(self, store, *, stream='stream', sequence=1, payload=b'{}\n', bad_hash=False):
        row = self.rows[0]
        result = store.ingest(row['record'], row['received_at'])
        receipt = store.db.execute('SELECT id FROM receipts ORDER BY id DESC LIMIT 1').fetchone()[0]
        values = (stream, sequence, payload, hashlib.sha256(payload).hexdigest(), receipt,
                  '0' * 64 if bad_hash else result['receipt_id'], json.dumps(result),
                  result['status'], None, OBSERVED)
        store.db.execute('INSERT INTO delivery_effects VALUES (?,?,?,?,?,?,?,?,?,?)', values)
        return receipt

    def attempt(self, db, *, outcome='COMMITTED', sequence=1, payload=b'{}\n', effect_sequence=1):
        db.execute('''INSERT INTO delivery_attempts
            (stream_id,sequence,payload,payload_sha256,plan_hash,outcome,effect_stream_id,effect_sequence,observed_at,reason)
            VALUES (?,?,?,?,?,?,?,?,?,?)''',
            ('stream', sequence, payload, hashlib.sha256(payload).hexdigest(), 'a' * 64,
             outcome, 'stream' if effect_sequence is not None else None, effect_sequence, OBSERVED, None))

    def test_schema3_open_reads_history_without_migration_or_byte_changes(self):
        path = self.root / 'historical.sqlite3'
        db, fixture = schema3_history(path)
        expected_runs = dict(db.execute('SELECT id,payload FROM runs'))
        expected_rows = old_rows(db)
        db.close()
        original = path.read_bytes()
        store = Store(path)
        try:
            self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 3)
            self.assertEqual(old_rows(store.db), expected_rows)
            for run_id in fixture['run_ids']:
                self.assertEqual(store.read_run(run_id), {'run_id': run_id, **json.loads(expected_runs[run_id])})
            with self.assertRaisesRegex(ValueError, 'MIGRATION_REQUIRED'):
                store.save_run(json.loads(next(iter(expected_runs.values()))))
        finally:
            store.close()
        self.assertEqual(path.read_bytes(), original)

    def test_schema3_migration_preserves_every_original_row_object_and_history(self):
        db, fixture = schema3_history(self.root / 'historical.sqlite3')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE unrelated_extension (id INTEGER PRIMARY KEY, value BLOB)')
        db.execute('INSERT INTO unrelated_extension VALUES (1,?)', (b'\x00\xff',))
        db.execute("CREATE TRIGGER retain_extension BEFORE DELETE ON unrelated_extension BEGIN SELECT RAISE(ABORT,'retain'); END")
        before = old_rows(db)
        objects = set(db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master'))
        self.assertTrue(before['correction_groups'])
        self.assertTrue(before['correction_effects'])
        self.assertTrue(migrate_connection(db))
        validate_current(db)
        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 5)
        self.assertLessEqual(objects, set(db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master')))
        after = old_rows(db)
        for name, rows in before.items():
            actual = [row for row in after[name] if row[0] <= 3] if name == 'schema_migrations' else after[name]
            self.assertEqual(actual, rows, name)
        self.assertEqual(db.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall(), [(2,), (3,), (4,), (5,)])
        self.assertEqual(set(fixture['run_ids']), {row[0] for row in after['runs']})
        self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        snapshot = application_snapshot(db)
        self.assertFalse(migrate_connection(db))
        self.assertEqual(application_snapshot(db), snapshot)

    def test_each_schema4_boundary_failure_rolls_back_all_ddl_metadata_and_rows(self):
        for point in ('migration_before_admission', 'migration_after_admission_tables',
                      'migration_after_schema4', 'migration_before_commit'):
            with self.subTest(point=point):
                db, _ = schema3_history(self.root / (point + '.sqlite3'))
                self.addCleanup(db.close)
                before = application_snapshot(db)
                rows = old_rows(db)
                def fail(current):
                    if current == point:
                        raise RuntimeError('controlled stage4 boundary')
                with self.assertRaisesRegex(RuntimeError, 'controlled stage4 boundary'):
                    migrate_connection(db, fail)
                self.assertEqual(application_snapshot(db), before)
                self.assertEqual(old_rows(db), rows)

    def test_explicit_schema3_backup_rehearsal_restore_and_retry_preserve_history(self):
        path = self.root / 'historical.sqlite3'
        db, _ = schema3_history(path)
        before = application_snapshot(db)
        db.close()
        def fail(point):
            if point == 'migration_after_schema4':
                raise RuntimeError('source failed before commit')
        with self.assertRaisesRegex(RuntimeError, 'source failed'):
            migrate_database(path, self.root / 'backups', fail)
        with closing(sqlite3.connect(path)) as check:
            self.assertEqual(application_snapshot(check), before)
        saved = next((self.root / 'backups').glob('*.schema3.sqlite3'))
        backup_bytes = saved.read_bytes()
        report = migrate_database(path, self.root / 'backups')
        self.assertEqual(report['from_version'], 3)
        self.assertEqual(report['schema_version'], 5)
        self.assertEqual(report['before_digest'], report['after_digest'])
        for field in ('all_old_columns_equal', 'all_old_tables_equal', 'all_old_objects_equal',
                      'copy_rollback_verified', 'copy_restore_verified', 'idempotency_verified'):
            self.assertTrue(report[field], field)
        self.assertEqual(saved.read_bytes(), backup_bytes)
        restored = self.root / 'separate-restored.sqlite3'
        backup_database(saved, restored)
        with closing(sqlite3.connect(restored)) as check:
            self.assertEqual(application_snapshot(check), before)
        self.assertEqual(migrate_database(path, self.root / 'backups')['status'], 'ALREADY_CURRENT')

    def test_schema4_saved_historical_run_exports_without_recompute_or_source_writes(self):
        path = self.root / 'historical.sqlite3'
        db, fixture = schema3_history(path)
        expected = dict(db.execute('SELECT id,payload FROM runs'))
        from source_auth_legacy_fixtures import install_historical_schema4
        install_historical_schema4(db)
        db.close()
        before = path.read_bytes()
        selected = Selection((SourceSelection('history', path, tuple(fixture['run_ids']), 'History', {}),))
        result = read_selected_sources(selected)
        self.assertEqual({run.run_id for run in result.runs}, set(fixture['run_ids']))
        for run in result.runs:
            self.assertEqual(run.schema_version, 4)
            self.assertEqual(run.payload_text, expected[run.run_id])
            self.assertNotIn('delivery_attempts', run.payload)
        self.assertTrue(all(source['unchanged'] for source in result.sources))
        self.assertEqual(path.read_bytes(), before)

    def test_delivery_tables_are_append_only_and_receipt_links_are_exact(self):
        store = self.fresh()
        self.bind(store.db)
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'receipt identity/status'):
            self.effect(store, bad_hash=True)
        receipt = self.effect(store)
        self.attempt(store.db)
        self.assertEqual(store.db.execute('SELECT core_receipt_id FROM delivery_effects').fetchone()[0], receipt)
        for table in ('admission_streams', 'delivery_effects', 'delivery_attempts'):
            with self.subTest(table=table):
                for operation in (f'DELETE FROM {table}', f'UPDATE {table} SET stream_id=stream_id'):
                    with self.assertRaisesRegex(sqlite3.IntegrityError, 'append-only'):
                        store.db.execute(operation)
        self.bind(store.db, name='other')
        effect = tuple(store.db.execute('SELECT * FROM delivery_effects').fetchone())
        with self.assertRaises(sqlite3.IntegrityError):
            store.db.execute('INSERT INTO delivery_effects VALUES (?,?,?,?,?,?,?,?,?,?)', ('other', *effect[1:]))
        self.assertEqual(store.db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_effect_guards_reject_gaps_blocked_streams_and_plan_overrun(self):
        store = self.fresh()
        self.bind(store.db, lines=1)
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'strict next'):
            self.effect(store, sequence=2)
        self.effect(store)
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'immutable plan'):
            self.effect(store, sequence=2)
        self.attempt(store.db, outcome='TRANSPORT_CONFLICT', payload=b'{ }\n')
        self.bind(store.db, name='blocked', lines=3)
        store.db.execute('''INSERT INTO delivery_attempts
            (stream_id,sequence,payload,payload_sha256,plan_hash,outcome,observed_at,reason)
            VALUES (?,?,?,?,?,?,?,?)''',
            ('blocked', 1, b'{}\n', hashlib.sha256(b'{}\n').hexdigest(), 'b' * 64, 'PLAN_CONFLICT', OBSERVED, 'different plan'))
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'blocked'):
            self.effect(store, stream='blocked')
        self.assertEqual(store.db.execute('SELECT stream_id,sequence FROM delivery_effects').fetchall()[0][:], ('stream', 1))

    def test_attempt_guards_preserve_replay_identity_and_allow_unbound_gap_audit(self):
        store = self.fresh()
        self.attempt(store.db, outcome='GAP', sequence=2, effect_sequence=None)
        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM admission_streams').fetchone()[0], 0)
        self.bind(store.db)
        self.effect(store)
        self.attempt(store.db, outcome='REPLAY')
        with self.assertRaises(sqlite3.IntegrityError):
            self.attempt(store.db, outcome='REPLAY', payload=b'{ }\n')
        with self.assertRaises(sqlite3.IntegrityError):
            self.attempt(store.db, outcome='REPLAY', sequence=2)
        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM delivery_attempts').fetchone()[0], 2)
        self.assertEqual(store.db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_frame_rejection_is_only_disposition_without_core_receipt(self):
        store = self.fresh()
        payload = b'{\n'
        self.bind(store.db, payload=payload, lines=1)
        values = ('stream', 1, payload, hashlib.sha256(payload).hexdigest(), None, None, None,
                  'INVALID', 'bad frame', OBSERVED)
        with self.assertRaises(sqlite3.IntegrityError):
            store.db.execute('INSERT INTO delivery_effects VALUES (?,?,?,?,?,?,?,?,?,?)', values)
        store.db.execute('INSERT INTO delivery_effects VALUES (?,?,?,?,?,?,?,?,?,?)',
                         (*values[:7], 'REJECTED_FRAME', *values[8:]))
        self.attempt(store.db, payload=payload)
        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM receipts').fetchone()[0], 0)

    def test_corrupt_admission_guard_is_rejected_without_implicit_repair(self):
        path = self.root / 'corrupt.sqlite3'
        store = Store(path, self.config)
        store.db.execute('DROP TRIGGER delivery_effects_strict_next')
        before = application_snapshot(store.db)
        store.close()
        with self.assertRaisesRegex(ValueError, 'SCHEMA_INVALID: admission schema object differs'):
            Store(path)
        with closing(sqlite3.connect(path)) as check:
            self.assertEqual(application_snapshot(check), before)


if __name__ == '__main__':
    unittest.main()
