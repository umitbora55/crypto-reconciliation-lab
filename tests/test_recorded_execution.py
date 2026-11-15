"""Recorded observation, retry and raw-storage bindings with independent oracles."""
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from crypto_reconciliation_lab import Store, reconcile
from crypto_reconciliation_lab.execution import (
    ExecutionError, reconcile_recorded, read_execution, export_execution,
)
from crypto_reconciliation_lab.execution.demo import build_fixture, PLATFORM, CONFIG
from crypto_reconciliation_lab.model import digest


def altered(db, table, action, sql, args=()):
    """Controlled corrupt fixture only; preserve required immutable guard DDL."""
    trigger = 'immutable_' + table + '_' + action
    ddl = db.execute('SELECT sql FROM sqlite_master WHERE name=?', (trigger,)).fetchone()[0]
    db.execute('DROP TRIGGER ' + trigger)
    try:
        db.execute(sql, args)
    finally:
        db.execute(ddl)


class RecordedExecutionCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self, name='fixture', **kwargs):
        return build_fixture(self.root/name, **kwargs)

    def recorded(self, fixture, request_id='request-1', **kwargs):
        with closing(Store(fixture['database'])) as store:
            return reconcile_recorded(store, fixture['balance_at'], fixture['knowledge_at'], request_id, **kwargs)

    def counts(self, path):
        with closing(sqlite3.connect(path)) as db:
            return {name: db.execute('SELECT COUNT(*) FROM '+name).fetchone()[0]
                    for name in ('runs', 'findings', 'evidence', 'execution_contexts', 'recorded_executions')}

    def assert_error(self, code, operation):
        with self.assertRaises(ExecutionError) as raised:
            operation()
        self.assertEqual(raised.exception.reason_code, code, str(raised.exception))


class RecordedExecutionTests(RecordedExecutionCase):
    def test_literal_clean_finances_and_unsigned_observation_are_distinct_claims(self):
        fixture = self.fixture()
        result = self.recorded(fixture)
        self.assertEqual((result['status'], result['replayed']), ('RECORDED', False))
        ledgers = result['financial_result']['ledgers']
        self.assertEqual(ledgers['ASSET_A']['investor_balances'], {'I1': '7', 'I2': '4'})
        self.assertEqual(ledgers['ASSET_A']['liability'], '11')
        self.assertEqual(ledgers['ASSET_A']['custody_rollforward'], {'platform': '2', 'external': '9'})
        self.assertEqual(ledgers['ASSET_B']['investor_balances'], {'I1': '0.3', 'I2': '0.2'})
        self.assertEqual(ledgers['ASSET_B']['liability'], '0.5')
        self.assertEqual(ledgers['ASSET_B']['custody_rollforward'], {'platform': '0.05', 'external': '0.45'})
        self.assertEqual(len(result['financial_result']['findings']), 6)
        self.assertEqual({(f['data_state'], f['reconciliation_state']) for f in result['financial_result']['findings']}, {('COMPLETE', 'MATCHED')})
        self.assertEqual(result['context']['claims'], {
            'context_state': 'RECORDED', 'admission_mode': 'LEGACY',
            'legacy_signature_status': 'UNSIGNED', 'source_signature_verification': 'NOT_PERFORMED',
            'run_actor_authorization': 'NOT_DEFINED'})
        self.assertEqual(result['context']['counts']['receipts'], 30)
        self.assertEqual(result['context']['acceptance_epochs'], [])
        self.assertIsNone(result['context']['observed_policy_head'])
        self.assertNotIn('context', result['financial_result'])

    def test_duplicate_physical_rows_are_retained_without_changing_financial_run(self):
        fixture = self.fixture()
        first = self.recorded(fixture)
        row = fixture['records_by_source'][PLATFORM][0]
        with closing(Store(fixture['database'])) as store:
            self.assertEqual(store.ingest(row['record'], row['received_at'])['status'], 'DUPLICATE')
        second = self.recorded(fixture, 'request-2')
        self.assertEqual(first['run_id'], second['run_id'])
        self.assertEqual(first['financial_result'], second['financial_result'])
        self.assertNotEqual(first['execution_id'], second['execution_id'])
        self.assertNotEqual(first['context_hash'], second['context_hash'])
        self.assertEqual((first['context']['counts']['receipts'], second['context']['counts']['receipts']), (30, 31))
        candidates = [r for r in second['context']['tables']['receipts'] if r['receipt_hash'] == digest(row)]
        self.assertEqual([r['id'] for r in candidates], [1, 31])
        entry = second['context']['selected_evidence'][candidates[0]['record_id']]
        self.assertEqual(entry['receipt_ids'], [1, 31])
        self.assertEqual(read_execution(fixture['database'], first['execution_id'])['context'], first['context'])

    def test_retry_lookup_precedes_capture_and_financial_recomputation_after_new_input(self):
        fixture = self.fixture()
        first = self.recorded(fixture)
        row = fixture['records_by_source'][PLATFORM][0]
        with closing(Store(fixture['database'])) as store:
            store.ingest(row['record'], row['received_at'])
            with patch('crypto_reconciliation_lab.execution.capture.capture_inputs', side_effect=AssertionError('must not recapture')), \
                 patch('crypto_reconciliation_lab.engine.reconcile', side_effect=AssertionError('must not recompute')):
                retry = reconcile_recorded(store, fixture['balance_at'], fixture['knowledge_at'], 'request-1')
        self.assertEqual(retry, {**first, 'replayed': True})
        self.assertEqual(self.counts(fixture['database'])['recorded_executions'], 1)

    def test_request_conflicts_cover_every_stable_parameter_without_rewriting_original(self):
        fixture = self.fixture()
        first = self.recorded(fixture)
        with closing(Store(fixture['database'])) as store:
            for changes in ({'balance_at': '2026-11-12T23:59:58Z'},
                            {'knowledge_at': '2026-11-13T02:00:00Z'},
                            {'configuration_digest': 'a'*64}, {'rule_version': 'another-rule'},
                            {'profile': 'another-profile'}):
                with self.subTest(changes=changes):
                    arguments = {'balance_at': fixture['balance_at'], 'knowledge_at': fixture['knowledge_at'], **changes}
                    self.assert_error('EXECUTION_REQUEST_CONFLICT', lambda: reconcile_recorded(store, request_id='request-1', **arguments))
                    self.assertFalse(store.db.in_transaction)
        self.assertEqual(read_execution(fixture['database'], first['execution_id'])['context'], first['context'])
        self.assertEqual(self.counts(fixture['database'])['recorded_executions'], 1)

    def test_timezone_equivalence_and_database_move_preserve_request_identity(self):
        fixture = self.fixture()
        first = self.recorded(fixture)
        moved = self.root/'moved.sqlite'
        shutil.move(fixture['database'], moved)
        with closing(Store(moved)) as store:
            retry = reconcile_recorded(store, '2026-11-13T02:59:59+03:00', '2026-11-13T04:00:00+03:00', 'request-1')
        self.assertEqual(retry, {**first, 'replayed': True})

    def test_ordinary_run_has_no_recorded_creation_cut_and_multiple_executions_are_explicit(self):
        fixture = self.fixture()
        with closing(Store(fixture['database'])) as store:
            original = reconcile(store, fixture['balance_at'], fixture['knowledge_at'])
        missing = read_execution(fixture['database'], run_id=original['run_id'])
        self.assertEqual(missing['status'], 'NOT_RECORDED')
        self.assertEqual(missing['run_creation_authorization_cut'], 'NOT_RECORDED')
        first = self.recorded(fixture)
        second = self.recorded(fixture, 'request-2')
        self.assertEqual(first['run_id'], original['run_id'])
        selected = read_execution(fixture['database'], run_id=original['run_id'])
        self.assertEqual(selected['status'], 'MULTIPLE_EXECUTIONS')
        self.assertEqual(selected['execution_ids'], sorted([first['execution_id'], second['execution_id']]))
        self.assertNotIn('context', selected)
        self.assertEqual(self.counts(fixture['database'])['runs'], 1)

    def test_caller_transaction_remains_open_and_unmodified_on_rejection(self):
        fixture = self.fixture()
        with closing(Store(fixture['database'])) as store:
            store.db.execute('CREATE TABLE caller_notes(value TEXT)')
            store.db.execute('BEGIN')
            store.db.execute("INSERT INTO caller_notes VALUES ('pending')")
            self.assert_error('EXECUTION_TRANSACTION', lambda: reconcile_recorded(store, fixture['balance_at'], fixture['knowledge_at'], 'request-1'))
            self.assertTrue(store.db.in_transaction)
            self.assertEqual(store.db.execute('SELECT value FROM caller_notes').fetchone()[0], 'pending')
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 0)
            store.db.execute('ROLLBACK')
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM caller_notes').fetchone()[0], 0)

    def test_configuration_is_read_inside_owned_transaction_not_from_cached_store(self):
        fixture = self.fixture()
        with closing(Store(fixture['database'])) as store:
            store.config = {'untrusted_cached_value': True}
            result = reconcile_recorded(store, fixture['balance_at'], fixture['knowledge_at'], 'request-1')
        self.assertEqual(result['context']['configuration'], CONFIG)
        self.assertEqual(result['request']['configuration_digest'], digest(CONFIG))

    def test_future_receipt_excluded_null_invalid_included_and_old_context_not_enriched(self):
        fixture = self.fixture()
        row = fixture['records_by_source'][PLATFORM][0]
        with closing(Store(fixture['database'])) as store:
            store.ingest(row['record'], '2026-11-14T00:00:00Z')
            invalid = copy.deepcopy(row['record']); invalid['amount'] = 'NaN'
            self.assertEqual(store.ingest(invalid, 'not-a-time')['status'], 'INVALID')
        first = self.recorded(fixture)
        receipts = first['context']['tables']['receipts']
        self.assertEqual([r['id'] for r in receipts], list(range(1,31)) + [32])
        bad = receipts[-1]
        self.assertIsNone(bad['received_at'])
        self.assertIsNone(bad['record_id'])
        self.assertEqual(bad['status'], 'INVALID')
        self.assertIn('NaN', bad['raw'])
        with closing(Store(fixture['database'])) as store:
            store.ingest(row['record'], row['received_at'])
        self.assertEqual(read_execution(fixture['database'], first['execution_id'])['context'], first['context'])
        second = self.recorded(fixture, 'request-2')
        self.assertEqual(second['context']['counts']['receipts'], 32)

    def test_superseded_valid_report_is_in_context_even_when_not_selected(self):
        fixture = self.fixture()
        original = next(row for row in fixture['records_by_source'][PLATFORM] if row['record']['kind'] == 'report')
        replacement = copy.deepcopy(original['record']); replacement['version'] = 2
        with closing(Store(fixture['database'])) as store:
            response = store.ingest(replacement, fixture['knowledge_at'])
            old_id = next(r[0] for r in store.db.execute('SELECT id,payload FROM records') if json.loads(r[1])['kind'] == 'report' and json.loads(r[1]).get('scope') == 'I1' and json.loads(r[1])['asset'] == 'ASSET_A' and json.loads(r[1])['version'] == 1)
        result = self.recorded(fixture)
        records = {r['id'] for r in result['context']['tables']['records']}
        self.assertIn(old_id, records)
        self.assertIn(response['record_id'], records)
        self.assertEqual(result['context']['counts']['receipts'], 31)
        finding = next(f for f in result['financial_result']['findings'] if f['asset'] == 'ASSET_A' and f['scope'] == 'I1')
        self.assertEqual(finding['reconciliation_state'], 'MATCHED')

    def test_raw_saved_run_serialization_is_bound_without_canonical_rewriting(self):
        fixture = self.fixture()
        with closing(Store(fixture['database'])) as store:
            ordinary = reconcile(store, fixture['balance_at'], fixture['knowledge_at'])
            saved = store.db.execute('SELECT payload FROM runs WHERE id=?', (ordinary['run_id'],)).fetchone()[0]
            pretty = json.dumps(json.loads(saved), indent=2, ensure_ascii=True) + '\n'
            altered(store.db, 'runs', 'UPDATE', 'UPDATE runs SET payload=? WHERE id=?', (pretty, ordinary['run_id']))
        result = self.recorded(fixture)
        self.assertEqual(result['run_id'], ordinary['run_id'])
        self.assertEqual(result['run_payload_sha256'], hashlib.sha256(pretty.encode()).hexdigest())
        export = self.root/'export'
        export_execution(fixture['database'], result['execution_id'], export)
        self.assertEqual((export/'run.json').read_bytes(), pretty.encode())
        with closing(sqlite3.connect(fixture['database'])) as db:
            self.assertEqual(db.execute('SELECT payload FROM runs').fetchone()[0], pretty)

    def test_missing_financial_mirror_is_rejected_without_repair_or_new_context(self):
        for table, key in (('findings', 'ordinal'), ('evidence', 'evidence_id')):
            with self.subTest(table=table):
                fixture = self.fixture(table)
                with closing(Store(fixture['database'])) as store:
                    reconcile(store, fixture['balance_at'], fixture['knowledge_at'])
                    altered(store.db, table, 'DELETE', 'DELETE FROM '+table+' WHERE '+key+'=(SELECT '+key+' FROM '+table+' LIMIT 1)')
                before = self.counts(fixture['database'])
                self.assert_error('EXECUTION_INTEGRITY', lambda: self.recorded(fixture))
                self.assertEqual(self.counts(fixture['database']), before)

    def test_correction_receipts_and_exact_mirrors_are_required_without_repair(self):
        from crypto_reconciliation_lab.correction_demo import correction_fixtures, T3
        from crypto_reconciliation_lab.demo import BALANCE_AT
        for missing in (None, 'correction_groups', 'correction_effects'):
            with self.subTest(missing=missing):
                config, rows, _ = correction_fixtures('deposit_amount_correction')
                path = self.root/(str(missing)+'.sqlite')
                with closing(Store(path, config)) as store:
                    for row in rows:
                        store.ingest(row['record'], row['received_at'])
                    original = reconcile(store, BALANCE_AT, T3)
                    if missing:
                        if missing == 'correction_groups':
                            altered(store.db, 'correction_effects', 'DELETE', 'DELETE FROM correction_effects')
                        altered(store.db, missing, 'DELETE', 'DELETE FROM '+missing)
                        before = self.counts(path)
                        self.assert_error('EXECUTION_INTEGRITY', lambda: reconcile_recorded(store, BALANCE_AT, T3, 'corrected'))
                        self.assertEqual(self.counts(path), before)
                    else:
                        result = reconcile_recorded(store, BALANCE_AT, T3, 'corrected')
                        self.assertEqual(result['run_id'], original['run_id'])
                        ledger = result['financial_result']['ledgers']['ASSET_A']
                        self.assertEqual(ledger['investor_balances'], {'I1': '8', 'I2': '4'})
                        self.assertEqual(ledger['liability'], '12')
                        self.assertEqual(ledger['custody_rollforward'], {'platform': '2', 'external': '10'})
                        corrections = [r for r in result['context']['tables']['records'] if r['kind'] == 'correction']
                        self.assertEqual(len(corrections), 1)
                        correction_id = corrections[0]['id']
                        self.assertTrue(any(r['record_id'] == correction_id for r in result['context']['tables']['receipts']))
                        target_id = next(r[0] for r in store.db.execute("SELECT id,payload FROM records WHERE kind='event'") if json.loads(r[1])['ref'] == 'A2')
                        expected_ids = sorted([correction_id, target_id])
                        physical = sorted(r[0] for r in store.db.execute('SELECT id FROM receipts WHERE record_id IN (?,?)', expected_ids))
                        groups = [entry for entry in result['financial_result']['evidence'].items() if 'derived_correction_group' in entry[1]]
                        self.assertEqual(len(groups), 1)
                        self.assertEqual(result['context']['selected_evidence'][groups[0][0]], {
                            'record_ids': expected_ids, 'receipt_ids': physical})

    def test_semantic_missing_selected_receipt_rejected_even_with_coherent_hash_bindings(self):
        fixture = self.fixture()
        first = self.recorded(fixture)
        context = copy.deepcopy(first['context'])
        removed = context['tables']['receipts'].pop(0)
        context['tables']['records'] = [r for r in context['tables']['records'] if r['id'] != removed['record_id']]
        context['counts']['receipts'] -= 1
        context['counts']['records'] -= 1
        # A fixture owner reseals every local byte binding. Rejection must be
        # required financial-evidence coverage, not an accidental stale hash.
        def encoded(value):
            return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()
        raw = encoded(context)
        context_hash = hashlib.sha256(raw).hexdigest()
        binding = {'format': 'recorded-execution-v1', **{key: first[key] for key in (
            'request_id', 'request_fingerprint', 'run_id', 'run_payload_sha256') if key in first}}
        binding['request_fingerprint'] = context['request_fingerprint']
        binding['context_hash'] = context_hash
        execution_id = hashlib.sha256(encoded(binding)).hexdigest()
        with closing(sqlite3.connect(fixture['database'], isolation_level=None)) as db:
            altered(db, 'execution_contexts', 'UPDATE', 'UPDATE execution_contexts SET context_hash=?,payload=?', (context_hash, raw))
            altered(db, 'recorded_executions', 'UPDATE', 'UPDATE recorded_executions SET execution_id=?,context_hash=?', (execution_id, context_hash))
        with self.assertRaises(ExecutionError) as raised:
            read_execution(fixture['database'], execution_id)
        self.assertEqual(raised.exception.reason_code, 'EXECUTION_INTEGRITY')
        self.assertIn('selected record absent', str(raised.exception))

    def test_actual_oversized_sql_value_is_rejected_before_financial_persistence(self):
        fixture = self.fixture()
        raw = {'kind': 'unsupported', 'padding': 'x' * (4 * 1024 * 1024)}
        with closing(Store(fixture['database'])) as store:
            self.assertEqual(store.ingest(raw, fixture['knowledge_at'])['status'], 'INVALID')
            maximum = store.db.execute('SELECT MAX(length(CAST(raw AS BLOB))) FROM receipts').fetchone()[0]
            self.assertGreater(maximum, 4 * 1024 * 1024)
        before = self.counts(fixture['database'])
        self.assert_error('EXECUTION_LIMIT', lambda: self.recorded(fixture))
        self.assertEqual(self.counts(fixture['database']), before)

    def test_oversized_semantically_valid_mirror_is_rejected_before_parity_loading(self):
        for table in ('findings', 'evidence'):
            for recorded in (False, True):
                fixture = self.fixture(table + ('-recorded' if recorded else '-ordinary'))
                if recorded:
                    first = self.recorded(fixture)
                with closing(Store(fixture['database'])) as store:
                    if not recorded:
                        reconcile(store, fixture['balance_at'], fixture['knowledge_at'])
                    rowid, raw = store.db.execute('SELECT rowid,payload FROM '+table+' LIMIT 1').fetchone()
                    padded = ' ' * (4 * 1024 * 1024 + 1) + raw
                    self.assertEqual(json.loads(padded), json.loads(raw))
                    altered(store.db, table, 'UPDATE', 'UPDATE '+table+' SET payload=? WHERE rowid=?', (padded, rowid))
                before = self.counts(fixture['database'])
                operations = [('new-reuse', lambda: self.recorded(fixture))] if not recorded else [
                    ('show', lambda: read_execution(fixture['database'], first['execution_id'])),
                    ('retry', lambda: self.recorded(fixture))]
                for operation_name, operation in operations:
                    with self.subTest(table=table, operation=operation_name):
                        self.assert_error('EXECUTION_LIMIT', operation)
                        self.assertEqual(self.counts(fixture['database']), before)

    def test_corrupt_context_bytes_and_request_binding_fail_show_and_retry(self):
        for table in ('execution_contexts', 'recorded_executions'):
            with self.subTest(table=table):
                fixture = self.fixture(table)
                first = self.recorded(fixture)
                with closing(sqlite3.connect(fixture['database'], isolation_level=None)) as db:
                    field, value = ('payload', b'{}') if table == 'execution_contexts' else ('request_fingerprint', 'a'*64)
                    altered(db, table, 'UPDATE', 'UPDATE '+table+' SET '+field+'=?', (value,))
                before = fixture['database'].read_bytes()
                self.assert_error('EXECUTION_INTEGRITY', lambda: read_execution(fixture['database'], first['execution_id']))
                self.assert_error('EXECUTION_INTEGRITY', lambda: self.recorded(fixture))
                self.assertEqual(fixture['database'].read_bytes(), before)

    def test_orphan_context_prevents_new_execution_and_successful_retry(self):
        fixture = self.fixture()
        first = self.recorded(fixture)
        with closing(Store(fixture['database'])) as store:
            store.db.execute('INSERT INTO execution_contexts VALUES (?,?,?)', ('f'*64, 'recorded-execution-v1', b'{}'))
        before = self.counts(fixture['database'])
        for request in ('request-1', 'request-2'):
            self.assert_error('EXECUTION_INTEGRITY', lambda: self.recorded(fixture, request))
        self.assert_error('EXECUTION_INTEGRITY', lambda: read_execution(fixture['database'], first['execution_id']))
        self.assertEqual(self.counts(fixture['database']), before)

    def test_capture_resource_limit_aborts_whole_execution_without_partial_success(self):
        for limit, value in (('MAX_RECEIPTS', 29), ('MAX_ROWS', 10), ('MAX_VALUE_BYTES', 10), ('MAX_CONTEXT_BYTES', 32)):
            with self.subTest(limit=limit):
                fixture = self.fixture(limit)
                before = self.counts(fixture['database'])
                with patch('crypto_reconciliation_lab.execution.capture.'+limit, value):
                    self.assert_error('EXECUTION_LIMIT', lambda: self.recorded(fixture))
                self.assertEqual(self.counts(fixture['database']), before)

    def test_complete_empty_inventory_is_recorded_with_incomplete_financial_result(self):
        path = self.root/'empty.sqlite'
        with closing(Store(path, CONFIG)) as store:
            result = reconcile_recorded(store, '2026-11-12T23:59:59Z', '2026-11-13T01:00:00Z', 'empty-request')
        self.assertEqual(result['status'], 'RECORDED')
        self.assertTrue(result['context']['scope']['complete'])
        self.assertEqual(set(result['context']['counts'].values()), {0})
        self.assertEqual(result['context']['selected_evidence'], {})
        self.assertEqual({f['reconciliation_state'] for f in result['financial_result']['findings']}, {'NOT_EVALUATED'})
        self.assertEqual({f['data_state'] for f in result['financial_result']['findings']}, {'INCOMPLETE'})

    def test_reader_and_export_never_capture_reconcile_migrate_or_enrich(self):
        fixture = self.fixture()
        first = self.recorded(fixture)
        before = fixture['database'].read_bytes()
        with patch('crypto_reconciliation_lab.execution.capture.capture_inputs', side_effect=AssertionError('capture forbidden')), \
             patch('crypto_reconciliation_lab.engine.reconcile', side_effect=AssertionError('recompute forbidden')), \
             patch('crypto_reconciliation_lab.store.Store', side_effect=AssertionError('Store forbidden')), \
             patch('crypto_reconciliation_lab.migrations.migrate_connection', side_effect=AssertionError('migration forbidden')):
            self.assertEqual(read_execution(fixture['database'], first['execution_id']), first)
            output = self.root/'export'
            exported = export_execution(fixture['database'], first['execution_id'], output)
        self.assertEqual(exported['status'], 'EXPORTED')
        with closing(sqlite3.connect(fixture['database'])) as db:
            raw = db.execute('SELECT payload FROM execution_contexts').fetchone()[0]
        self.assertEqual((output/'context.json').read_bytes(), raw)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), first['context_hash'])
        self.assertEqual(fixture['database'].read_bytes(), before)

    def test_input_types_and_timeout_bounds_reject_before_writes(self):
        fixture = self.fixture()
        with closing(Store(fixture['database'])) as store:
            for request in ('', 'spaces are forbidden', '../path', 'ğ', 'a'*129, True):
                with self.subTest(request=request):
                    self.assert_error('EXECUTION_INPUT', lambda: reconcile_recorded(store, fixture['balance_at'], fixture['knowledge_at'], request))
            for timeout in (True, -1, 5001, 1.5):
                with self.subTest(timeout=timeout):
                    self.assert_error('EXECUTION_INPUT', lambda: reconcile_recorded(store, fixture['balance_at'], fixture['knowledge_at'], 'request-1', busy_timeout_ms=timeout))
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 0)

    def test_timeout_and_durability_settings_are_restored_on_success_and_failure(self):
        fixture = self.fixture()
        with closing(Store(fixture['database'], busy_timeout_ms=1234)) as store:
            names = ('busy_timeout', 'journal_mode', 'synchronous', 'foreign_keys')
            before = {name: store.db.execute('PRAGMA '+name).fetchone()[0] for name in names}
            reconcile_recorded(store, fixture['balance_at'], fixture['knowledge_at'], 'request-1', busy_timeout_ms=0)
            self.assert_error('EXECUTION_REQUEST_CONFLICT', lambda: reconcile_recorded(store, fixture['balance_at'], fixture['knowledge_at'], 'request-1', rule_version='different', busy_timeout_ms=17))
            after = {name: store.db.execute('PRAGMA '+name).fetchone()[0] for name in names}
            self.assertEqual(after, before)

    def test_physical_receipt_ids_beyond_javascript_precision_remain_exact_in_python_export(self):
        fixture = self.fixture()
        large = 2**53 + 1
        maximum = 2**63 - 1
        with closing(Store(fixture['database'])) as store:
            altered(store.db, 'receipts', 'UPDATE', 'UPDATE receipts SET id=? WHERE id=1', (large,))
            altered(store.db, 'receipts', 'UPDATE', 'UPDATE receipts SET id=? WHERE id=2', (maximum,))
        result = self.recorded(fixture)
        ids = [r['id'] for r in result['context']['tables']['receipts']]
        self.assertIn(large, ids)
        self.assertIn(maximum, ids)
        self.assertNotIn(2**53, ids)
        self.assertTrue(all(type(value) is int for value in ids))
        output = self.root/'export'
        export_execution(fixture['database'], result['execution_id'], output)
        self.assertIn(large, [r['id'] for r in json.loads((output/'context.json').read_bytes())['tables']['receipts']])
        self.assertIn(maximum, [r['id'] for r in json.loads((output/'context.json').read_bytes())['tables']['receipts']])


class RecordedProtectedExecutionTests(RecordedExecutionCase):
    def test_protected_signed_financial_mismatch_does_not_become_authorization_failure(self):
        fixture = self.fixture(protected=True, mismatch=True)
        result = self.recorded(fixture)
        findings = result['financial_result']['findings']
        bad = [f for f in findings if f['reconciliation_state'] == 'MISMATCH']
        self.assertEqual(len(bad), 1)
        self.assertEqual((bad[0]['asset'], bad[0]['scope'], bad[0]['data_state'], bad[0]['difference']), ('ASSET_A', 'customer_liability', 'COMPLETE', '1'))
        self.assertEqual(result['context']['claims']['admission_mode'], 'PROTECTED')
        self.assertEqual(result['context']['claims']['source_signature_verification'], 'NOT_PERFORMED')
        self.assertEqual(result['context']['claims']['run_actor_authorization'], 'NOT_DEFINED')
        self.assertEqual(result['context']['acceptance_epochs'], [1])

    def test_policy_advance_changes_new_observation_but_never_old_acceptance_or_retry(self):
        from crypto_reconciliation_lab.source_auth.runtime import activate_policy
        fixture = self.fixture(protected=True)
        first = self.recorded(fixture)
        with closing(Store(fixture['database'])) as store:
            head = first['context']['observed_policy_head']
            activate_policy(store, fixture['rotated_policy'], expected_epoch=head['epoch'], expected_hash=head['policy_hash'])
            with patch('crypto_reconciliation_lab.execution.capture.capture_inputs', side_effect=AssertionError('retry capture forbidden')):
                retry = reconcile_recorded(store, fixture['balance_at'], fixture['knowledge_at'], 'request-1')
        self.assertEqual(retry, {**first, 'replayed': True})
        second = self.recorded(fixture, 'request-2')
        self.assertEqual(second['run_id'], first['run_id'])
        self.assertEqual(second['context']['observed_policy_head']['epoch'], 2)
        self.assertEqual(second['context']['acceptance_epochs'], [1])
        self.assertEqual(first['context']['observed_policy_head']['epoch'], 1)
        self.assertEqual(read_execution(fixture['database'], first['execution_id'])['context'], first['context'])
