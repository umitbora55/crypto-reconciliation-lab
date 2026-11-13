import copy
import json
import random
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from crypto_reconciliation_lab import Store, reconcile
from crypto_reconciliation_lab.correction_demo import (T1, T2, T3, correction, correction_manifest,
    correction_fixtures, financial_projection, run_correction_demos)
from crypto_reconciliation_lab.demo import BALANCE_AT, KNOWLEDGE_AT, fixtures
from crypto_reconciliation_lab.migrations import backup_database, migrate_connection, migrate_database


class CorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config, self.base, _ = fixtures()
        self.stores = []
        self.addCleanup(lambda: [store.close() for store in self.stores])

    def store(self, rows=None):
        store = Store(Path(self.temp.name) / f'{len(self.stores)}.sqlite3', self.config)
        self.stores.append(store)
        for row in self.base if rows is None else rows:
            store.ingest(row['record'], row['received_at'])
        return store

    def add(self, store, raw=None, manifest=True, time=T1):
        raw = correction() if raw is None else raw
        response = store.ingest(raw, time)
        if manifest:
            store.ingest(correction_manifest(raw['batch_id']), time)
        return response

    def run_at(self, store, time=T1, **kwargs):
        return reconcile(store, BALANCE_AT, time, **kwargs)

    def finding(self, result, scope='customer_liability', asset='ASSET_A'):
        return next(f for f in result['findings'] if f['asset'] == asset and f['scope'] == scope)

    def assert_quantities(self, result, i1, i2, liability, external):
        ledger = result['ledgers']['ASSET_A']
        self.assertEqual(ledger['investor_balances'], {'I1': i1, 'I2': i2})
        self.assertEqual(ledger['liability'], liability)
        self.assertEqual(ledger['custody_rollforward'], {'platform': '2', 'external': external})
        self.assertEqual(result['ledgers']['ASSET_B']['investor_balances'], {'I1': '0.3', 'I2': '0.2'})
        self.assertEqual(result['ledgers']['ASSET_B']['liability'], '0.5')
        self.assertEqual(result['ledgers']['ASSET_B']['custody_rollforward'], {'platform': '0.05', 'external': '0.45'})
        self.assertTrue(all(f['reconciliation_state'] == 'MATCHED' for f in result['findings'] if f['asset'] == 'ASSET_B'))

    def codes(self, result):
        return {i['code'] for i in self.finding(result)['issues']}

    def test_deposit_replacement_reports_are_independent(self):
        config, rows, phases = correction_fixtures('deposit_amount_correction')
        store = self.store(rows)
        original = self.run_at(store, KNOWLEDGE_AT)
        corrected = self.run_at(store)
        self.assert_quantities(corrected, '8', '4', '12', '10')
        self.assertEqual(self.finding(corrected, 'I1')['difference'], '1')
        self.assertEqual(self.finding(corrected)['difference'], '1')
        investor_updated = self.run_at(store, T2)
        self.assertEqual(self.finding(investor_updated, 'I1')['reconciliation_state'], 'MATCHED')
        self.assertEqual(self.finding(investor_updated)['difference'], '1')
        self.assertEqual(self.finding(self.run_at(store, T3))['reconciliation_state'], 'MATCHED')
        self.assert_quantities(original, '7', '4', '11', '9')
        self.assertEqual(self.run_at(store, KNOWLEDGE_AT), original)

    def test_deposit_void_and_old_reports(self):
        store = self.store()
        self.add(store, correction(mode='VOID'))
        result = self.run_at(store)
        self.assert_quantities(result, '5', '4', '9', '7')
        self.assertEqual(self.finding(result, 'I1')['difference'], '-2')
        self.assertEqual(self.finding(result)['difference'], '-2')

    def test_transfer_void_preserves_liability_but_catches_distribution(self):
        store = self.store()
        self.add(store, correction('A1', 'VOID'))
        result = self.run_at(store)
        self.assert_quantities(result, '8', '3', '11', '9')
        self.assertEqual(self.finding(result, 'I1')['difference'], '1')
        self.assertEqual(self.finding(result, 'I2')['difference'], '-1')
        self.assertEqual(self.finding(result)['reconciliation_state'], 'MATCHED')

    def test_withdrawal_void_signs(self):
        store = self.store()
        self.add(store, correction('A3', 'VOID'))
        result = self.run_at(store)
        self.assert_quantities(result, '7', '5', '12', '10')
        self.assertEqual(self.finding(result)['difference'], '1')
        group = result['ledgers']['ASSET_A']['correction_groups'][0]
        self.assertEqual(group['effects'][0]['investor_deltas'], {'I2': '1'})
        self.assertEqual(group['effects'][0]['custody_delta'], '1')

    def test_withdrawal_replace_signs(self):
        store = self.store()
        self.add(store, correction('A3', 'REPLACE', '2'))
        result = self.run_at(store)
        self.assert_quantities(result, '7', '3', '10', '8')
        self.assertEqual(self.finding(result)['difference'], '-1')
        group = result['ledgers']['ASSET_A']['correction_groups'][0]
        self.assertEqual([e['custody_delta'] for e in group['effects']], ['1', '-2'])
        self.assertEqual(group['net_effect']['custody_delta'], '-2')

    def test_transfer_amount_replacement(self):
        store = self.store()
        self.add(store, correction('A1', 'REPLACE', '2'))
        result = self.run_at(store)
        self.assert_quantities(result, '6', '5', '11', '9')
        self.assertEqual(self.finding(result)['difference'], '0')

    def test_retry_receipts_first_known_time_and_rerun(self):
        store = self.store()
        self.add(store)
        first = self.run_at(store)
        self.assertEqual(store.ingest(correction(), T2)['status'], 'DUPLICATE')
        second = self.run_at(store, T2)
        self.assertEqual(first['ledgers']['ASSET_A']['correction_groups'], second['ledgers']['ASSET_A']['correction_groups'])
        self.assertEqual(second['ledgers']['ASSET_A']['correction_groups'][0]['first_known_at'], '2026-11-11T03:00:00.000000Z')
        self.assert_quantities(second, '8', '4', '12', '10')
        self.assertEqual(store.ingest(correction(), T2)['status'], 'DUPLICATE')
        self.assertEqual(self.run_at(store, T2), second)
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM receipts WHERE record_id=(SELECT id FROM records WHERE kind='correction')").fetchone()[0], 3)
        self.assertEqual(self.run_at(store), first)

    def test_same_id_changed_content_conflicts_without_winner(self):
        store = self.store()
        self.add(store)
        before = self.run_at(store)
        self.assertEqual(store.ingest(correction(replacement='4'), T2)['status'], 'CONFLICT')
        after = self.run_at(store, T2)
        self.assertIn('CORRECTION_ID_CONFLICT', self.codes(after))
        self.assertEqual(self.finding(after)['data_state'], 'CONFLICT')
        self.assertEqual(after['ledgers']['ASSET_A']['correction_groups'], [])
        self.assertEqual(self.run_at(store), before)
        self.assertEqual(store.read_run(before['run_id']), before)

    def test_two_corrections_same_target_conflict_in_every_arrival_order(self):
        _, rows, _ = correction_fixtures('duplicate_and_conflicting_corrections')
        shuffled = copy.deepcopy(rows)
        random.Random(42).shuffle(shuffled)
        first = self.run_at(self.store(rows), T3)
        second = self.run_at(self.store(shuffled), T3)
        self.assertEqual(first, second)
        self.assertIn('MULTIPLE_TARGET_CORRECTIONS', self.codes(first))
        self.assertEqual(self.finding(first)['reconciliation_state'], 'NOT_EVALUATED')
        self.assert_quantities(first, '7', '4', '11', '9')

    def test_arrival_order_independent_for_valid_group(self):
        _, rows, _ = correction_fixtures('deposit_amount_correction')
        self.assertEqual(self.run_at(self.store(rows), T3), self.run_at(self.store(list(reversed(rows))), T3))

    def test_missing_target_is_pending_then_resolves(self):
        target = next(r for r in self.base if r['record'].get('ref') == 'A2')
        store = self.store([r for r in self.base if r != target])
        self.add(store)
        pending = self.run_at(store)
        self.assertIn('TARGET_PENDING', self.codes(pending))
        self.assertEqual(self.finding(pending)['data_state'], 'INCOMPLETE')
        self.assertEqual(pending['ledgers']['ASSET_A']['correction_deliveries'][0]['observed_unique_valid_count'], 0)
        store.ingest(target['record'], T2)
        resolved = self.run_at(store, T2)
        self.assert_quantities(resolved, '8', '4', '12', '10')
        self.assertEqual(self.finding(resolved)['difference'], '1')
        self.assertEqual(self.run_at(store), pending)

    def test_invalid_target_is_not_reported_as_missing(self):
        for row in self.base:
            if row['record'].get('ref') == 'A2':
                row['record']['amount'] = 'NaN'
        store = self.store()
        self.add(store)
        result = self.run_at(store)
        self.assertIn('INVALID_TARGET', self.codes(result))
        self.assertNotIn('TARGET_PENDING', self.codes(result))
        self.assertEqual(result['ledgers']['ASSET_A']['correction_groups'], [])

    def test_conflicting_target_is_not_corrected(self):
        store = self.store()
        event = next(r['record'] for r in self.base if r['record'].get('ref') == 'A2')
        store.ingest({**event, 'amount': '4'}, T1)
        self.add(store)
        result = self.run_at(store)
        self.assertIn('TARGET_EVENT_CONFLICT', self.codes(result))
        self.assertEqual(result['ledgers']['ASSET_A']['correction_groups'], [])

    def test_invalid_replacement_never_removes_original(self):
        for quantity in ('0', '-1', 'NaN', 'Infinity', '', None, 0.1, '3.000000001'):
            with self.subTest(quantity=quantity):
                store = self.store()
                response = self.add(store, correction(replacement=quantity))
                self.assertEqual(response['reason_code'], 'INVALID_REPLACEMENT_AMOUNT')
                result = self.run_at(store)
                self.assert_quantities(result, '7', '4', '11', '9')
                self.assertEqual(self.finding(result)['reconciliation_state'], 'NOT_EVALUATED')
                self.assertEqual(result['ledgers']['ASSET_A']['correction_deliveries'][0]['observed_unique_valid_count'], 0)

    def test_unsupported_forms_have_reason_codes(self):
        cases = [({**correction(mode='VOID'), 'replacement_amount': None}, 'VOID_WITH_REPLACEMENT_AMOUNT'),
                 ({**correction(), 'partial_amount': '1'}, 'UNSUPPORTED_PARTIAL_REVERSAL'),
                 ({**correction(), 'reverse_amount': '2'}, 'UNSUPPORTED_PARTIAL_REVERSAL'),
                 ({**correction(), 'mode': 'PARTIAL'}, 'UNSUPPORTED_CORRECTION_MODE'),
                 ({**correction(), 'to_investor': 'I2'}, 'UNSUPPORTED_CORRECTION_FIELDS'),
                 ({**correction(), 'target': {'kind': 'opening'}}, 'UNSUPPORTED_OPENING_REVISION'),
                 ({**correction(), 'target': {'kind': 'correction', 'correction_id': 'COR1'}}, 'SELF_REFERENCE'),
                 ({**correction(), 'target': {'kind': 'correction', 'correction_id': 'COR2'}}, 'UNSUPPORTED_CORRECTION_CHAIN')]
        for raw, code in cases:
            with self.subTest(code=code):
                store = self.store()
                self.assertEqual(self.add(store, raw)['reason_code'], code)
                result = self.run_at(store)
                self.assertIn(code, self.codes(result))
                self.assert_quantities(result, '7', '4', '11', '9')

    def test_cycle_is_rejected_without_recursion(self):
        store = self.store()
        for cid, target in [('COR1', 'COR2'), ('COR2', 'COR1')]:
            raw = correction(correction_id=cid)
            raw['target'] = {'kind': 'correction', 'correction_id': target}
            self.assertEqual(store.ingest(raw, T1)['reason_code'], 'UNSUPPORTED_CORRECTION_CHAIN')
        self.assertIn('UNSUPPORTED_CORRECTION_CHAIN', self.codes(self.run_at(store)))

    def test_platform_asset_and_time_mismatches(self):
        raw = correction()
        raw['target']['platform'] = 'P2'
        store = self.store()
        self.assertEqual(self.add(store, raw)['reason_code'], 'TARGET_PLATFORM_MISMATCH')
        raw = correction()
        raw['target']['ref'] = 'B1'
        store = self.store()
        self.add(store, raw)
        result = self.run_at(store)
        self.assertIn('TARGET_ASSET_MISMATCH', self.codes(result))
        self.assert_quantities(result, '7', '4', '11', '9')
        raw = correction()
        raw['target_occurred_at'] = '2026-11-10T02:30:00Z'
        store = self.store()
        self.add(store, raw)
        self.assertIn('TARGET_TIME_MISMATCH', self.codes(self.run_at(store)))

    def test_opening_horizon_is_explicitly_unsupported(self):
        store = self.store()
        raw = correction()
        raw['target_occurred_at'] = '2026-11-09T23:00:00Z'
        raw['target']['business_day'] = '2026-11-09'
        self.assertEqual(self.add(store, raw)['reason_code'], 'UNSUPPORTED_OPENING_HORIZON')
        result = self.run_at(store)
        self.assertIn('UNSUPPORTED_OPENING_HORIZON', self.codes(result))
        self.assert_quantities(result, '7', '4', '11', '9')

    def test_no_effect_before_target_economic_time(self):
        store = self.store()
        self.add(store)
        result = reconcile(store, '2026-11-10T01:30:00Z', T1)
        self.assertEqual(result['ledgers']['ASSET_A']['investor_balances'], {'I1': '5', 'I2': '5'})
        self.assertEqual(result['ledgers']['ASSET_A']['correction_groups'], [])

    def test_missing_manifest_does_not_apply_group(self):
        store = self.store()
        self.add(store, manifest=False)
        before = self.run_at(store)
        self.assertIn('CORRECTION_MANIFEST_ABSENT', self.codes(before))
        self.assert_quantities(before, '7', '4', '11', '9')
        store.ingest(correction_manifest(), T2)
        self.assert_quantities(self.run_at(store, T2), '8', '4', '12', '10')
        self.assertEqual(self.run_at(store), before)

    def test_unannounced_legacy_data_has_no_missing_channel(self):
        result = self.run_at(self.store())
        self.assertEqual(result['ledgers']['ASSET_A']['correction_deliveries'], [])
        self.assertEqual(self.finding(result)['reconciliation_state'], 'MATCHED')

    def test_manifest_only_announces_missing_correction(self):
        store = self.store()
        store.ingest(correction_manifest(), T1)
        result = self.run_at(store)
        self.assertIn('CORRECTION_MANIFEST_COUNT', self.codes(result))
        self.assertEqual(self.finding(result)['data_state'], 'INCOMPLETE')
        self.assert_quantities(result, '7', '4', '11', '9')

    def test_cancelled_event_and_derived_effects_are_not_source_counts(self):
        for mode in ('VOID', 'REPLACE'):
            with self.subTest(mode=mode):
                store = self.store()
                self.add(store, correction(mode=mode))
                store.ingest(correction(mode=mode), T1)
                result = self.run_at(store)
                ledger = result['ledgers']['ASSET_A']
                self.assertEqual(len(ledger['event_ids']), 3)
                self.assertEqual(ledger['correction_deliveries'][0]['observed_unique_valid_count'], 1)
                self.assertEqual(len(ledger['correction_groups'][0]['effects']), 1 if mode == 'VOID' else 2)
                self.assertEqual(store.db.execute("SELECT COUNT(*) FROM records WHERE kind='event'").fetchone()[0], 4)

    def test_duplicate_does_not_cover_correction_count_shortfall(self):
        store = self.store()
        self.add(store, manifest=False)
        store.ingest(correction(), T1)
        store.ingest(correction_manifest(count=2), T1)
        result = self.run_at(store)
        delivery = result['ledgers']['ASSET_A']['correction_deliveries'][0]
        self.assertEqual(delivery['observed_unique_valid_count'], 1)
        self.assertFalse(delivery['complete'])
        self.assert_quantities(result, '7', '4', '11', '9')

    def test_manifest_conflict_coverage_and_revision_rejection(self):
        store = self.store()
        self.add(store)
        store.ingest(correction_manifest(count=2), T1)
        self.assertIn('CORRECTION_MANIFEST_CONFLICT', self.codes(self.run_at(store)))
        store = self.store()
        self.add(store, manifest=False)
        store.ingest({**correction_manifest(), 'coverage_from': '2026-11-10T02:30:00Z'}, T1)
        self.assertIn('TARGET_OUTSIDE_CORRECTION_COVERAGE', self.codes(self.run_at(store)))
        self.assertEqual(store.ingest({**correction_manifest(), 'version': 2}, T1)['reason_code'], 'UNSUPPORTED_MANIFEST_REVISION')

    def test_incomplete_original_delivery_prevents_correction_application(self):
        rows = [r for r in self.base if not (r['record']['kind'] == 'manifest' and r['record'].get('stream') == 'event' and r['record']['asset'] == 'ASSET_A')]
        store = self.store(rows)
        self.add(store)
        result = self.run_at(store)
        self.assert_quantities(result, '7', '4', '11', '9')
        self.assertEqual(result['ledgers']['ASSET_A']['correction_groups'], [])
        self.assertEqual(self.finding(result)['data_state'], 'INCOMPLETE')

    def test_fractional_correction_and_zero_tolerance(self):
        store = self.store()
        self.add(store, correction(replacement='2.00000001'))
        result = self.run_at(store)
        self.assert_quantities(result, '7.00000001', '4', '11.00000001', '9.00000001')
        self.assertEqual(self.finding(result)['difference'], '0.00000001')
        self.assertEqual(self.finding(result)['reconciliation_state'], 'MISMATCH')

    def test_atomic_net_avoids_half_group_negative(self):
        # Original internal transfer gives I2 +1 at that economic point. A naive
        # reverse-before-original ordering would make its zero opening negative.
        for row in self.base:
            if row['record']['kind'] == 'opening' and row['record']['asset'] == 'ASSET_A' and row['record']['scope'] == 'I2':
                row['record']['amount'] = '0'
        store = self.store()
        self.add(store, correction('A1', 'REPLACE', '2'))
        result = self.run_at(store)
        self.assertEqual(result['ledgers']['ASSET_A']['investor_balances'], {'I1': '6', 'I2': '1'})
        self.assertEqual(result['ledgers']['ASSET_A']['data_state'], 'COMPLETE')
        self.assertNotIn('NEGATIVE_ECONOMIC_BALANCE', self.codes(result))

    def test_negative_corrected_ledger_is_invalid_in_economic_order(self):
        store = self.store()
        self.add(store, correction('A3', 'REPLACE', '6'))
        result = self.run_at(store)
        self.assertIn('NEGATIVE_ECONOMIC_BALANCE', self.codes(result))
        self.assertEqual(self.finding(result)['data_state'], 'CONFLICT')
        self.assertEqual(self.finding(result)['reconciliation_state'], 'NOT_EVALUATED')

    def test_derived_and_saved_groups_fail_atomically_but_audit_survives(self):
        for point in ('derive_after_reversal', 'save_after_run', 'save_after_reversal', 'save_before_commit'):
            with self.subTest(point=point):
                store = self.store()
                before = self.run_at(store, KNOWLEDGE_AT)
                self.add(store)
                counts = {table: store.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in ('records', 'receipts', 'runs', 'findings', 'evidence', 'correction_groups', 'correction_effects')}
                def fail(at):
                    if at == point:
                        raise RuntimeError('controlled group failure')
                with self.assertRaisesRegex(RuntimeError, 'controlled'):
                    self.run_at(store, fault=fail)
                self.assertFalse(store.db.in_transaction)
                for table, count in counts.items():
                    self.assertEqual(store.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], count)
                self.assertEqual(store.read_run(before['run_id']), before)
                result = self.run_at(store)
                self.assert_quantities(result, '8', '4', '12', '10')
                self.assertEqual(store.db.execute('SELECT COUNT(*) FROM correction_groups').fetchone()[0], 1)
                self.assertEqual(store.db.execute('SELECT COUNT(*) FROM correction_effects').fetchone()[0], 2)

    def test_ingestion_failure_does_not_leave_record_without_receipt(self):
        store = self.store()
        count = store.db.execute('SELECT COUNT(*) FROM records').fetchone()[0]
        def fail(point):
            if point == 'ingest_before_receipt':
                raise RuntimeError('controlled intake failure')
        with self.assertRaises(RuntimeError):
            store.ingest(correction(), T1, fault=fail)
        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM records').fetchone()[0], count)
        self.assertEqual(self.add(store)['status'], 'ACCEPTED')

    def test_group_evidence_survives_restart_and_is_immutable(self):
        store = self.store()
        self.add(store)
        result = self.run_at(store)
        group = result['ledgers']['ASSET_A']['correction_groups'][0]
        self.assertIn(group['id'], result['evidence'])
        self.assertIn(group['target_record_id'], result['evidence'])
        self.assertIn(group['correction_record_id'], result['evidence'])
        with self.assertRaises(sqlite3.IntegrityError):
            store.db.execute('DELETE FROM correction_effects')
        path = store.db.execute('PRAGMA database_list').fetchone()[2]
        store.close()
        self.stores.remove(store)
        reopened = Store(path)
        self.stores.append(reopened)
        self.assertEqual(reopened.read_run(result['run_id']), result)
        self.assertEqual(self.run_at(reopened), result)

    def test_five_demos_have_literal_oracles_and_are_repeatable(self):
        path = Path(self.temp.name) / 'demos'
        summary = run_correction_demos(path)
        self.assertEqual(len(summary), 18)
        self.assertTrue(all(r['verified'] for r in summary))
        self.assertEqual({r['scenario'] for r in summary}, {'deposit_amount_correction', 'void_deposit', 'void_internal_transfer', 'correction_before_target', 'duplicate_and_conflicting_corrections'})
        before = (path / 'summary.json').read_bytes()
        run_correction_demos(path)
        self.assertEqual((path / 'summary.json').read_bytes(), before)

    def test_cli_correction_demo(self):
        result = subprocess.run([sys.executable, '-m', 'crypto_reconciliation_lab', 'demo-corrections', '--output', str(Path(self.temp.name) / 'cli')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('conflicting_corrections: PASS', result.stdout)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(__file__).resolve().parents[1]
        self.fixture = json.loads((root / 'fixtures/stage1_history.json').read_text())
        self.schema = json.loads((root / 'docs/stage2/baseline-schema.json').read_text())
        self.path = Path(self.temp.name) / 'legacy.sqlite3'
        db = sqlite3.connect(self.path, isolation_level=None)
        for typ in ('table', 'index'):
            for kind, name, sql in self.schema:
                if kind == typ:
                    db.execute(sql)
        for table, value in self.fixture.items():
            placeholders = ','.join('?' for _ in value['columns'])
            db.executemany(f'INSERT INTO {table} VALUES ({placeholders})', value['rows'])
        for kind, name, sql in self.schema:
            if kind == 'trigger':
                db.execute(sql)
        db.close()

    def assert_legacy(self, db):
        for table, value in self.fixture.items():
            self.assertEqual([r[1] for r in db.execute(f'PRAGMA table_info({table})')], value['columns'])
            actual = sorted([list(r) for r in db.execute(f'SELECT * FROM {table}')], key=lambda row: json.dumps(row, sort_keys=True))
            self.assertEqual(actual, value['rows'], table)

    def test_migration_preserves_all_columns_ids_and_old_runs(self):
        result = migrate_database(self.path, Path(self.temp.name) / 'backup')
        self.assertTrue(result['all_old_columns_equal'])
        self.assertTrue(result['copy_rollback_verified'])
        self.assertTrue(result['copy_restore_verified'])
        self.assertEqual(result['before_digest'], result['after_digest'])
        db = sqlite3.connect(self.path)
        self.assert_legacy(db)
        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 4)
        self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
        db.close()
        store = Store(self.path)
        try:
            for run_id, balance, knowledge, payload in self.fixture['runs']['rows']:
                self.assertEqual(store.read_run(run_id), {'run_id': run_id, **json.loads(payload)})
        finally:
            store.close()
        again = migrate_database(self.path, Path(self.temp.name) / 'backup')
        self.assertEqual(again['status'], 'ALREADY_CURRENT')

    def test_controlled_migration_failures_rollback_schema_and_data(self):
        for point in ('migration_after_group_table', 'migration_before_commit'):
            with self.subTest(point=point):
                db = sqlite3.connect(self.path, isolation_level=None)
                def fail(at):
                    if at == point:
                        raise RuntimeError('controlled migration failure')
                with self.assertRaises(RuntimeError):
                    migrate_connection(db, fail)
                self.assertFalse(db.in_transaction)
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 0)
                self.assertEqual([list(r) for r in db.execute('SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name')], self.schema)
                self.assert_legacy(db)
                db.close()

    def test_failure_on_real_phase_keeps_verified_backup_and_original(self):
        def fail(at):
            if at == 'migration_before_commit':
                raise RuntimeError('controlled real-phase failure')
        with self.assertRaises(RuntimeError):
            migrate_database(self.path, Path(self.temp.name) / 'backups', fail)
        db = sqlite3.connect(self.path)
        self.assert_legacy(db)
        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 0)
        db.close()
        self.assertEqual(len(list((Path(self.temp.name) / 'backups').glob('*.sqlite3'))), 1)
        self.assertEqual(migrate_database(self.path, Path(self.temp.name) / 'backups')['status'], 'MIGRATED')

    def test_backup_restore_to_new_destination(self):
        backup = Path(self.temp.name) / 'old.sqlite3'
        backup_database(self.path, backup)
        db = sqlite3.connect(self.path, isolation_level=None)
        migrate_connection(db)
        db.close()
        restored = Path(self.temp.name) / 'restored.sqlite3'
        backup_database(backup, restored)
        db = sqlite3.connect(restored)
        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 0)
        self.assert_legacy(db)
        db.close()
        with self.assertRaisesRegex(ValueError, 'must be new'):
            backup_database(self.path, backup)

    def test_old_history_read_without_silent_migration(self):
        store = Store(self.path)
        try:
            self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 0)
            self.assert_legacy(store.db)
            run_id = self.fixture['runs']['rows'][0][0]
            self.assertEqual(store.read_run(run_id)['rule_version'], 'stage1-v1')
            with self.assertRaisesRegex(ValueError, 'MIGRATION_REQUIRED'):
                reconcile(store, BALANCE_AT, KNOWLEDGE_AT)
            self.assert_legacy(store.db)
        finally:
            store.close()

    def test_cli_migration(self):
        result = subprocess.run([sys.executable, '-m', 'crypto_reconciliation_lab', 'migrate', '--db', str(self.path), '--backup-dir', str(Path(self.temp.name) / 'cli-backup')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'MIGRATED')
