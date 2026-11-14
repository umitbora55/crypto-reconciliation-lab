"""Authority boundaries, epoch transitions and immutable receipt linkage."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from crypto_reconciliation_lab.store import Store
from crypto_reconciliation_lab.source_auth.crypto import AuthError, canonical, parse_envelope, sign_statement, strict_json
from crypto_reconciliation_lab.source_auth.fixtures import (CONFIG, RECEIVER, TEST_KEYS, policy,
    small_records, snapshot, signed, financial_records)
from crypto_reconciliation_lab.source_auth.runtime import enable_protection, activate_policy, auth_status, ingest_signed
from crypto_reconciliation_lab.source_auth.scope import capabilities, snapshot_bytes


class SourceAuthRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'auth.sqlite'
        self.store = Store(self.path, CONFIG)
        self.addCleanup(self.store.close)
        self.initial = enable_protection(self.store, RECEIVER, policy())
        self.data = snapshot(small_records())
        self.envelope = signed(self.data)

    def count(self, table):
        return self.store.db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]

    def assert_no_effect(self):
        for table in ('records','receipts','admission_streams','delivery_effects','delivery_attempts','auth_streams','auth_decisions','auth_endorsements'):
            self.assertEqual(self.count(table), 0, table)

    def rotate(self):
        active = auth_status(self.store)['active_policy']
        return activate_policy(self.store, policy(True), active['epoch'], active['policy_hash'])

    def raw_signed(self, records, **changes):
        data = snapshot(records)
        value = strict_json(parse_envelope(self.envelope)[0])
        value.update(plan=snapshot_bytes(data).plan)
        value.update(changes)
        return data, sign_statement(value, bytes.fromhex(TEST_KEYS['P1-old'][0]), 'P1-old')

    def test_accept_replay_and_restart_preserve_receipt_and_original_links(self):
        first = ingest_signed(self.store, self.data, self.envelope)
        again = ingest_signed(self.store, self.data, self.envelope)
        self.assertEqual(first['status'], 'COMPLETE')
        self.assertEqual([r['outcome'] for r in again['responses']], ['REPLAY','REPLAY'])
        self.assertEqual([r['core_receipt_row_id'] for r in first['responses']], [1,2])
        self.assertEqual([r['core_receipt_row_id'] for r in again['responses']], [1,2])
        self.assertEqual(self.count('receipts'), 2)
        self.assertEqual([r[0] for r in self.store.db.execute('SELECT decision_id FROM auth_delivery_links ORDER BY sequence')], [1,2])
        reopened = Store(self.path)
        try:
            self.assertEqual(auth_status(reopened), auth_status(self.store))
        finally:
            reopened.close()

    def test_revoked_exact_prefix_replays_but_unseen_suffix_is_denied(self):
        first = ingest_signed(self.store, self.data, self.envelope, max_lines=1)
        self.assertEqual(first['status'], 'INCOMPLETE')
        self.rotate()
        replay = ingest_signed(self.store, self.data, self.envelope)
        self.assertEqual(replay['status'], 'DENIED')
        self.assertEqual(len(replay['responses']), 1)
        authorization = replay['responses'][0]['authorization']
        self.assertEqual(authorization['decision'], 'HISTORICAL_REPLAY')
        self.assertEqual(authorization['key_status'], 'revoked')
        self.assertFalse(authorization['currently_authorized'])
        self.assertEqual(authorization['original_decision_id'], 1)
        self.assertEqual(replay['responses'][0]['core_receipt_row_id'], 1)
        self.assertEqual(self.count('receipts'), 1)
        self.assertEqual(self.count('auth_delivery_links'), 1)

    def test_new_same_source_key_resumes_suffix_preserving_old_epoch(self):
        ingest_signed(self.store, self.data, self.envelope, max_lines=1)
        self.rotate()
        resumed = ingest_signed(self.store, self.data, signed(self.data, key_id='P1-new'))
        self.assertEqual(resumed['status'], 'COMPLETE')
        self.assertEqual([r['outcome'] for r in resumed['responses']], ['REPLAY','COMMITTED'])
        rows = self.store.db.execute('SELECT d.epoch,e.key_id,l.core_receipt_id FROM auth_delivery_links l JOIN auth_decisions d ON d.id=l.decision_id JOIN auth_endorsements e ON e.id=d.endorsement_id ORDER BY l.sequence').fetchall()
        self.assertEqual([tuple(row) for row in rows], [(1,'P1-old',1),(2,'P1-new',2)])

    def test_revoked_different_statement_cannot_borrow_existing_sequence(self):
        ingest_signed(self.store, self.data, self.envelope)
        self.rotate()
        data = self.data.replace(b'"6"', b'"5"')
        denied = ingest_signed(self.store, data, signed(data))
        self.assertEqual(denied['status'], 'DENIED')
        self.assertEqual(denied['responses'], [])
        self.assertEqual(self.count('receipts'), 2)
        self.assertFalse(self.store.feed_status('platform-demo:sample')['blocked'])

    def test_every_transaction_rechecks_epoch_after_preflight_and_between_lines(self):
        def before(point):
            if point == 'auth_after_preflight':
                self.rotate()
        result = ingest_signed(self.store, self.data, self.envelope, fault=before)
        self.assertEqual(result['status'], 'DENIED')
        self.assert_no_effect()
        fresh = Store(Path(self.temp.name)/'second.sqlite', CONFIG)
        try:
            initial = enable_protection(fresh, RECEIVER, policy())
            count = 0
            def after(point):
                nonlocal count
                if point == 'auth_after_commit':
                    count += 1
                    if count == 1:
                        activate_policy(fresh, policy(True), initial['epoch'], initial['policy_hash'])
            result = ingest_signed(fresh, self.data, self.envelope, fault=after)
            self.assertEqual(result['status'], 'DENIED')
            self.assertEqual(fresh.db.execute('SELECT COUNT(*) FROM receipts').fetchone()[0], 1)
        finally:
            fresh.close()

    def test_whole_scope_is_reauthorized_for_every_new_effect(self):
        records = [financial_records()['P1'][0], financial_records()['P1'][4]]
        data = snapshot(records)
        envelope = signed(data)
        def remove_b(point):
            if point == 'auth_after_preflight':
                candidate = policy()
                candidate['sources'][0]['capabilities'] = [c for c in candidate['sources'][0]['capabilities'] if c['asset'] != 'ASSET_B']
                activate_policy(self.store, candidate, self.initial['epoch'], self.initial['policy_hash'])
        result = ingest_signed(self.store, data, envelope, max_lines=1, fault=remove_b)
        self.assertEqual(result['status'], 'DENIED')
        self.assert_no_effect()

    def test_invalid_last_line_authority_rejects_before_first_core_write(self):
        records = small_records()
        records[-1]['record']['stream'] = 'external_custody'
        data, envelope = self.raw_signed(records)
        self.assertEqual(ingest_signed(self.store, data, envelope)['status'], 'DENIED')
        self.assert_no_effect()

    def test_clear_scope_invalid_amount_uses_core_quarantine(self):
        records = small_records()
        records[0]['record']['amount'] = 'NaN'
        data = snapshot(records)
        result = ingest_signed(self.store, data, signed(data))
        self.assertEqual(result['status'], 'COMPLETE')
        self.assertEqual(result['responses'][0]['disposition'], 'INVALID')
        self.assertEqual(self.count('receipts'), 2)
        self.assertEqual(self.count('records'), 1)
        self.assertEqual(self.count('auth_delivery_links'), 2)

    def test_unsigned_public_paths_fail_before_first_stream_and_legacy_survives(self):
        record = small_records()[0]
        with self.assertRaisesRegex(ValueError, 'SOURCE_AUTH_REQUIRED'):
            self.store.ingest(record['record'], record['received_at'])
        with self.assertRaisesRegex(ValueError, 'SOURCE_AUTH_REQUIRED'):
            self.store.ingest_delivery('platform-demo:first', 1, self.data.splitlines(keepends=True)[0], snapshot_bytes(self.data).plan)
        path = Path(self.temp.name)/'feed.jsonl'
        path.write_bytes(self.data)
        from crypto_reconciliation_lab.admission.feed import ingest_feed
        with self.assertRaisesRegex(ValueError, 'SOURCE_AUTH_REQUIRED'):
            ingest_feed(self.store, path, 'platform-demo:first')
        self.assert_no_effect()
        legacy = Store(Path(self.temp.name)/'legacy.sqlite', CONFIG)
        try:
            self.assertEqual(legacy.ingest(record['record'], record['received_at'])['status'], 'ACCEPTED')
            with self.assertRaisesRegex(AuthError, 'empty database'):
                enable_protection(legacy, RECEIVER, policy())
        finally:
            legacy.close()

    def test_unknown_embedded_wrong_and_corrupt_keys_do_not_reserve_stream(self):
        original = json.loads(self.envelope)
        variants = []
        unknown = copy.deepcopy(original)
        unknown['signatures'][0]['keyid'] = 'attacker'
        unknown['public_key'] = TEST_KEYS['P1-old'][1]
        variants.append(unknown)
        wrong = copy.deepcopy(original)
        wrong['signatures'][0]['keyid'] = 'P1-new'
        variants.append(wrong)
        corrupt = copy.deepcopy(original)
        corrupt['signatures'][0]['sig'] = ('B' if corrupt['signatures'][0]['sig'][0] == 'A' else 'A') + corrupt['signatures'][0]['sig'][1:]
        variants.append(corrupt)
        for envelope in variants:
            self.assertEqual(ingest_signed(self.store, self.data, canonical(envelope))['status'], 'DENIED')
            self.assert_no_effect()
        self.assertEqual(ingest_signed(self.store, self.data, self.envelope)['status'], 'COMPLETE')

    def test_namespace_receiver_and_configuration_rejection_do_not_poison_live_stream(self):
        ingest_signed(self.store, self.data, self.envelope, max_lines=1)
        for changes in ({'receiver':'different'}, {'configuration_digest':'0'*64}, {'stream_id':'custodian-demo:sample'}):
            self.assertEqual(ingest_signed(self.store, self.data, signed(self.data, **changes))['status'], 'DENIED')
        self.assertFalse(self.store.feed_status('platform-demo:sample')['blocked'])
        self.assertEqual(ingest_signed(self.store, self.data, self.envelope)['status'], 'COMPLETE')
        self.assertEqual(self.count('receipts'), 2)

    def test_authorized_plan_conflict_stays_blocked_even_for_revoked_exact_replay(self):
        ingest_signed(self.store, self.data, self.envelope)
        changed = self.data.replace(b'"6"', b'"5"')
        conflict = ingest_signed(self.store, changed, signed(changed))
        self.assertEqual(conflict['status'], 'BLOCKED')
        self.assertEqual(conflict['responses'][0]['outcome'], 'PLAN_CONFLICT')
        self.rotate()
        replay = ingest_signed(self.store, self.data, self.envelope)
        self.assertEqual(replay['status'], 'BLOCKED')
        self.assertEqual(replay['responses'][0]['outcome'], 'BLOCKED')
        self.assertFalse(replay['responses'][0]['ack'])
        self.assertEqual(self.count('receipts'), 2)

    def test_policy_stale_update_alias_reactivation_and_namespace_changes_rejected(self):
        self.rotate()
        with self.assertRaisesRegex(AuthError, 'AUTH_POLICY_STALE'):
            activate_policy(self.store, policy(), self.initial['epoch'], self.initial['policy_hash'])
        active = auth_status(self.store)['active_policy']
        variants = [policy()]
        alias = policy(True)
        alias['keys'].append({**alias['keys'][0], 'key_id':'alias', 'status':'active'})
        variants.append(alias)
        namespace = policy(True)
        namespace['sources'][0]['namespace'] = 'changed:'
        variants.append(namespace)
        rebound = policy(True)
        rebound['keys'][0]['source'] = 'C1'
        variants.append(rebound)
        for candidate in variants:
            with self.assertRaises(AuthError):
                activate_policy(self.store, candidate, active['epoch'], active['policy_hash'])
        self.assertEqual(self.count('auth_policy_activations'), 2)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.db.execute("UPDATE auth_keys SET source='C1'")

    def test_exception_before_commit_rolls_back_auth_receipt_stream_and_links(self):
        def fail(point):
            if point == 'auth_before_commit':
                raise RuntimeError('controlled rollback, not a process-kill claim')
        with self.assertRaises(RuntimeError):
            ingest_signed(self.store, self.data, self.envelope, fault=fail)
        self.assert_no_effect()
        self.assertEqual(self.count('auth_attempt_links'), 0)
        self.assertEqual(ingest_signed(self.store, self.data, self.envelope)['status'], 'COMPLETE')

    def test_busy_reports_retryable_without_false_durable_rejection(self):
        other = sqlite3.connect(self.path, isolation_level=None)
        try:
            other.execute('BEGIN IMMEDIATE')
            result = ingest_signed(self.store, self.data, self.envelope, busy_timeout_ms=0)
            self.assertEqual(result['status'], 'RETRYABLE_BUSY')
            self.assertFalse(result['rejection']['durable'])
            result = ingest_signed(self.store, b'bad', b'bad', busy_timeout_ms=0)
            self.assertEqual(result['status'], 'DENIED')
            self.assertFalse(result['rejection']['durable'])
        finally:
            other.execute('ROLLBACK')
            other.close()
        self.assert_no_effect()
        self.assertEqual(self.count('auth_rejections'), 0)

    def test_all_six_kind_scopes_and_correction_target_binding(self):
        common = {'source':'P1','platform':'P1','asset':'ASSET_A'}
        rows = [dict(common,kind='opening',scope='external'), dict(common,kind='event'),
                dict(common,kind='report',stream='investor'), dict(common,kind='manifest',stream='event'),
                dict(common,kind='correction_manifest'), dict(common,kind='correction',
                    target={'kind':'event','source':'P1','platform':'P1','business_day':'2026-11-10','ref':'A1'})]
        extracted = capabilities(snapshot_bytes(snapshot([{'record':r,'received_at':'bad'} for r in rows])), CONFIG)
        self.assertEqual({c['kind'] for c in extracted}, {'opening','event','report','manifest','correction','correction_manifest'})
        self.assertTrue(all(c['source']=='P1' for c in extracted))
        for target in ({**rows[-1]['target'],'source':'C1'}, {**rows[-1]['target'],'asset':'ASSET_A'}):
            bad = copy.deepcopy(rows[-1])
            bad['target'] = target
            with self.assertRaises(AuthError):
                capabilities(snapshot_bytes(snapshot([{'record':bad,'received_at':'bad'}])), CONFIG)

    def test_same_count_scope_substitution_and_cartesian_grant_are_denied(self):
        value = strict_json(parse_envelope(self.envelope)[0])
        value['capabilities'][0]['asset'] = 'ASSET_B'
        envelope = sign_statement(value, bytes.fromhex(TEST_KEYS['P1-old'][0]), 'P1-old')
        self.assertEqual(ingest_signed(self.store, self.data, envelope)['status'], 'DENIED')
        candidate = policy()
        candidate['sources'][0]['capabilities'] = [
            {'source':'P1','platform':'P1','asset':'ASSET_A','kind':'event','channel':'none'},
            {'source':'P1','platform':'P1','asset':'ASSET_B','kind':'opening','channel':'none'}]
        activate_policy(self.store, candidate, self.initial['epoch'], self.initial['policy_hash'])
        self.assertEqual(ingest_signed(self.store, self.data, self.envelope)['status'], 'DENIED')
        self.assert_no_effect()
