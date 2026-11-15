"""Independent expectations and semantic mutations for the new general reader.

Expected statuses, codes and financial quantities below are literal. The fixture
operator creates small synthetic inputs; it is never imported by the verifier.
Every semantic mutation refreshes member hashes and the inert offline view. A
controlled capture repin is explicit and preserves the original run/policy pins.
"""
import base64
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from crypto_reconciliation_lab.provenance.demo import build_fixture
from crypto_reconciliation_lab.provenance.exporter import export_provenance
from crypto_reconciliation_lab.provenance.verifier import verify_bundle


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def fingerprint(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def load(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    Path(path).write_bytes(encoded(value))


def refresh(bundle, expectations, *, repin=False):
    """Test-only resealing; this is not an operator trust generator."""
    run, capture, report = [load(bundle/name) for name in ('run.json', 'capture.json', 'report.json')]
    if repin:
        expected = load(expectations)
        original = copy.deepcopy(expected)
        expected['capture_digest'] = hashlib.sha256(encoded(capture)).hexdigest()
        report['capture_digest'] = expected['capture_digest']
        write(expectations, expected)
        write(bundle/'report.json', report)
        assert all(expected[k] == original[k] for k in ('run_id', 'run_payload_sha256', 'configuration_digest', 'policies', 'policy_head'))
    material = {p.relative_to(bundle).as_posix(): fingerprint(p.read_bytes())
                for p in sorted((bundle/'materials').rglob('*')) if p.is_file()}
    # Fixture-only 0.9.1 display serialization; raw capture and every semantic
    # assertion stay unchanged. Do not import the production view builder.
    shown = copy.deepcopy(capture)
    fields = {'receipts': ('id',), 'delivery_effects': ('sequence', 'core_receipt_id'),
              'delivery_attempts': ('id', 'sequence', 'effect_sequence'), 'auth_configuration': ('id',),
              'auth_policy_activations': ('epoch', 'previous_epoch'), 'auth_keys': ('first_epoch',),
              'auth_decisions': ('id', 'epoch', 'sequence'),
              'auth_delivery_links': ('sequence', 'decision_id', 'core_receipt_id'),
              'auth_attempt_links': ('attempt_id', 'decision_id')}
    for table, columns in fields.items():
        for row in shown['tables'][table]:
            for column in columns:
                if type(row[column]) is int:
                    row[column] = str(row[column])
    value = {'run': run, 'capture': shown, 'report': report, 'materials': material}
    (bundle/'data.js').write_bytes(b'window.PROVENANCE_DATA = JSON.parse(' + encoded(encoded(value).decode('ascii')) + b');\n')
    manifest = load(bundle/'manifest.json')
    manifest['files'] = {p.relative_to(bundle).as_posix(): fingerprint(p.read_bytes())
                         for p in sorted(bundle.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
    write(bundle/'manifest.json', manifest)


class ProvenanceVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.fixture = build_fixture(cls.root/'clean-fixture')
        cls.template = cls.root/'template'
        export_provenance(cls.fixture['database'], cls.fixture['run_id'], cls.fixture['material_dir'], cls.template)
        positive = verify_bundle(cls.template, cls.fixture['expectations'])
        if positive['status'] != 'VERIFIED_FOR_CAPTURE' or positive['exit_code'] != 0:
            raise AssertionError('positive family must pass before negative tests: ' + repr(positive['reasons']))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.case = self.root/self._testMethodName
        self.case.mkdir()
        self.bundle = self.case/'bundle'
        shutil.copytree(self.template, self.bundle)
        self.expectations = self.case/'outside-expectations.json'
        shutil.copyfile(self.fixture['expectations'], self.expectations)

    def check_failure(self, code):
        result = verify_bundle(self.bundle, self.expectations)
        self.assertEqual(result['exit_code'], 2, result)
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['reasons'][0]['code'], code, result['reasons'])
        self.assertEqual(result['run_creation_authorization_cut'], 'NOT_RECORDED')
        return result

    def mutate(self, function):
        capture = load(self.bundle/'capture.json')
        function(capture['tables'])
        write(self.bundle/'capture.json', capture)
        refresh(self.bundle, self.expectations, repin=True)

    def independent_case(self, scenario):
        root = self.case/scenario
        fixture = build_fixture(root/'fixture', scenario=scenario)
        bundle = root/'bundle'
        export_provenance(fixture['database'], fixture['run_id'], fixture['material_dir'], bundle)
        return fixture, bundle, verify_bundle(bundle, fixture['expectations'])

    def test_complete_two_publisher_capture_preserves_literal_finance_and_limits(self):
        result = verify_bundle(self.bundle, self.expectations)
        self.assertEqual((result['status'], result['exit_code']), ('VERIFIED_FOR_CAPTURE', 0))
        self.assertEqual(result['run_creation_authorization_cut'], 'NOT_RECORDED')
        self.assertEqual(result['financial_recomputation'], 'NOT_PERFORMED')
        self.assertEqual({row['source'] for row in result['candidates']}, {'LARK_EXCHANGE', 'ORBIT_VAULT'})
        x = next(row for row in result['financial'] if row['comparison'] == 'B' and row['asset'] == 'TOKEN_X')
        self.assertEqual((x['expected'], x['reported'], x['difference']), ('11', '11', '0'))
        self.assertTrue(all(row['source_line'].endswith('\n') for row in result['candidates']))

    def test_signed_custody_mismatch_remains_a_financial_mismatch(self):
        _, _, result = self.independent_case('custody_difference')
        self.assertEqual(result['exit_code'], 0, result['reasons'])
        x = next(row for row in result['financial'] if row['comparison'] == 'B' and row['asset'] == 'TOKEN_X')
        self.assertEqual((x['reconciliation_state'], x['expected'], x['reported'], x['difference']), ('MISMATCH', '11', '10', '1'))

    def test_four_epochs_preserve_original_acceptance_and_show_current_revocation(self):
        _, _, result = self.independent_case('rotation')
        self.assertEqual(result['exit_code'], 0, result['reasons'])
        platform = [row for row in result['candidates'] if row['source'] == 'LARK_EXCHANGE']
        self.assertTrue(platform)
        self.assertEqual({row['original_policy_epoch'] for row in platform}, {1})
        self.assertEqual({row['capture_policy_epoch'] for row in platform}, {4})
        self.assertEqual({row['current_key_status'] for row in platform}, {'revoked'})
        self.assertTrue(all(row['replay_attempt_ids'] for row in platform))

    def test_replay_and_post_run_multiple_physical_candidates_have_distinct_meanings(self):
        _, _, replay = self.independent_case('replay')
        self.assertEqual(replay['exit_code'], 0, replay['reasons'])
        self.assertEqual(replay['physical_receipt_binding'], 'UNIQUE_CANDIDATE')
        self.assertTrue(all(row['replay_attempt_ids'] for row in replay['candidates']))
        fixture, _, multiple = self.independent_case('ambiguous')
        self.assertEqual(multiple['exit_code'], 3, multiple['reasons'])
        self.assertEqual(multiple['physical_receipt_binding'], 'MULTIPLE_CANDIDATES')
        self.assertIn('MULTIPLE_RECEIPT_CANDIDATES', [row['code'] for row in multiple['reasons']])
        self.assertTrue(any(len(row['physical_row_ids']) == 2 for row in multiple['receipt_candidates']))
        self.assertTrue(all(row['run_creation_authorization_cut'] == 'NOT_RECORDED' for row in multiple['candidates']))
        self.assertEqual(load(fixture['proof'])['run_creation_authorization_cut'], 'NOT_RECORDED')

    def test_history_correction_and_signed_invalid_quarantine_keep_saved_run_bytes(self):
        fixture, _, result = self.independent_case('quarantine')
        self.assertEqual(result['exit_code'], 0, result['reasons'])
        self.assertTrue(any(row['reconciliation_state'] == 'NOT_EVALUATED' for row in result['financial']))
        self.assertEqual(set(fixture['runs']), {'original', 'corrected', 'quarantine'})
        for phase in ('original', 'corrected'):
            bundle = self.case/('historical-' + phase)
            export_provenance(fixture['database'], fixture['runs'][phase], fixture['material_dir'], bundle)
            self.assertEqual(hashlib.sha256((bundle/'run.json').read_bytes()).hexdigest(), load(fixture['proof'])['saved_payload_sha256'][phase])
            verified = verify_bundle(bundle, fixture['expectations_by_phase'][phase])
            self.assertEqual(verified['exit_code'], 0, verified['reasons'])
            x = next(row for row in verified['financial'] if row['comparison'] == 'B' and row['asset'] == 'TOKEN_X')
            self.assertEqual(x['expected'], '11' if phase == 'original' else '12')

    def test_missing_full_file_and_prefix_only_are_partial_without_invented_suffix(self):
        for scenario in ('missing_snapshot', 'prefix_only'):
            with self.subTest(scenario=scenario):
                _, _, result = self.independent_case(scenario)
                self.assertEqual(result['exit_code'], 3, result['reasons'])
                self.assertEqual(result['source_admission'], 'MISSING_MATERIAL')
                self.assertIn('MISSING_SIGNED_SNAPSHOT', [r['code'] for r in result['reasons']])

    def test_genuine_legacy_is_partial_and_protected_deletion_is_not_a_downgrade(self):
        _, _, result = self.independent_case('legacy')
        self.assertEqual(result['exit_code'], 3, result['reasons'])
        self.assertEqual(result['source_admission'], 'UNSIGNED_LEGACY')
        self.mutate(lambda t: t['auth_configuration'].clear())
        self.check_failure('PROFILE_MISMATCH')

    def test_wrong_external_run_payload_capture_and_policy_pins_are_rejected(self):
        original = load(self.expectations)
        for field, code in (('run_id', 'RUN_IDENTITY'), ('run_payload_sha256', 'RUN_IDENTITY'),
                            ('capture_digest', 'CAPTURE_BINDING'), ('configuration_digest', 'CONFIGURATION_BINDING')):
            with self.subTest(field=field):
                value = copy.deepcopy(original);value[field] = '0'*64
                write(self.expectations, value)
                self.check_failure(code)
        value = copy.deepcopy(original)
        value['policies'][0]['policy_hash'] = value['policy_head']['policy_hash'] = '0'*64
        write(self.expectations, value)
        self.check_failure('POLICY_BINDING')

    def test_external_expectations_must_not_be_a_bundle_member_or_symlink_into_it(self):
        inside = self.bundle/'expectations.json'
        shutil.copyfile(self.expectations, inside)
        self.assertEqual(verify_bundle(self.bundle, inside)['reasons'][0]['code'], 'EXPECTATIONS_PATH')
        self.expectations.unlink();self.expectations.symlink_to(inside)
        self.check_failure('EXPECTATIONS_PATH')

    def test_required_record_and_receipt_scope_is_independent_of_report_lists(self):
        self.mutate(lambda t: t['receipts'].pop())
        self.check_failure('EVIDENCE_SCOPE')
        shutil.rmtree(self.bundle);shutil.copytree(self.template, self.bundle)
        shutil.copyfile(self.fixture['expectations'], self.expectations)
        self.mutate(lambda t: t['records'].clear())
        self.check_failure('EVIDENCE_SCOPE')

    def test_report_cannot_claim_empty_scope_or_another_finding_ordinal(self):
        report = load(self.bundle/'report.json');report['receipt_hashes'] = []
        write(self.bundle/'report.json', report);refresh(self.bundle, self.expectations)
        self.check_failure('REPORT_SCOPE')
        report = load(self.template/'report.json');report['findings'][0]['id'] = 'another-run:0'
        write(self.bundle/'report.json', report);refresh(self.bundle, self.expectations)
        self.check_failure('REPORT_SCOPE')

    def test_broken_original_protected_link_remains_failure_with_missing_snapshot(self):
        self.mutate(lambda t: t['auth_delivery_links'].pop())
        snapshot = next((self.bundle/'materials/snapshots').glob('*.jsonl'));snapshot.unlink()
        refresh(self.bundle, self.expectations)
        self.check_failure('PROTECTED_LINK')

    def test_effect_core_result_and_line_mutations_reach_relationship_checks(self):
        def change(t):
            effect = t['delivery_effects'][0]
            core = json.loads(effect['core_result']);core['record_id'] = 'f'*64
            effect['core_result'] = encoded(core).decode()
        self.mutate(change)
        self.check_failure('DELIVERY_RELATION')

    def test_committed_attempt_and_original_current_decision_cannot_be_replaced_by_replay(self):
        self.mutate(lambda t: t['delivery_attempts'][0].update(outcome='REPLAY'))
        self.check_failure('DELIVERY_RELATION')

    def test_missing_persistent_key_or_unexplained_owner_is_inconsistent(self):
        self.mutate(lambda t: t['auth_keys'].pop())
        self.check_failure('POLICY_BINDING')

    def test_semantic_quarantine_and_correction_record_corruption_are_rejected(self):
        fixture, bundle, _ = self.independent_case('quarantine')
        self.bundle, self.expectations = bundle, fixture['expectations']
        self.mutate(lambda t: next(row for row in t['receipts'] if row['status']=='INVALID').update(error='different diagnostic'))
        self.check_failure('RECEIPT_BINDING')
        fixture, bundle, _ = self.independent_case('correction')
        self.bundle, self.expectations = bundle, fixture['expectations']
        def corrupt(t):
            row = next(row for row in t['records'] if row['kind']=='correction')
            value = json.loads(row['payload']);value['replacement_amount'] = '999'
            row['payload'] = encoded(value).decode()
        self.mutate(corrupt)
        self.check_failure('EVIDENCE_SCOPE')

    def test_capture_head_cannot_hide_later_revocation_even_when_observation_is_repinned(self):
        fixture, bundle, _ = self.independent_case('rotation')
        self.bundle, self.expectations = bundle, fixture['expectations']
        self.mutate(lambda t: t['auth_policy_activations'].pop())
        self.check_failure('POLICY_BINDING')

    def test_invalid_signature_outranks_missing_full_snapshot(self):
        capture = load(self.bundle/'capture.json')
        row = capture['tables']['auth_endorsements'][0]
        envelope = json.loads(bytes.fromhex(row['envelope']))
        signature = bytearray(base64.b64decode(envelope['signatures'][0]['sig']));signature[0] ^= 1
        envelope['signatures'][0]['sig'] = base64.b64encode(signature).decode()
        raw = encoded(envelope);row['envelope'] = raw.hex()
        (self.bundle/'materials/envelopes'/(row['id']+'.json')).write_bytes(raw)
        (self.bundle/'materials/snapshots'/(row['snapshot_hash']+'.jsonl')).unlink()
        write(self.bundle/'capture.json', capture);refresh(self.bundle, self.expectations, repin=True)
        self.check_failure('AUTH_SIGNATURE')

    def test_known_line_capability_mismatch_outranks_missing_full_snapshot(self):
        # A valid TEST-ONLY signature deliberately omits an observed opening's
        # capability. Missing full bytes cannot conceal that available mismatch.
        from crypto_reconciliation_lab.source_auth.crypto import sign_statement
        capture = load(self.bundle/'capture.json')
        tables = capture['tables']
        row = next(r for r in tables['auth_endorsements'] if r['key_id'] == 'lark-original')
        previous_id = row['id']
        statement = json.loads(bytes.fromhex(row['payload']))
        original_count = len(statement['capabilities'])
        statement['capabilities'] = [c for c in statement['capabilities']
                                     if not (c['asset'] == 'TOKEN_X' and c['kind'] == 'opening')]
        self.assertLess(len(statement['capabilities']), original_count)
        self.assertTrue(statement['capabilities'])
        envelope = sign_statement(statement, b'1'*32, 'lark-original')
        parsed = json.loads(envelope)
        payload = base64.b64decode(parsed['payload'])
        signature = base64.b64decode(parsed['signatures'][0]['sig'])
        replacement_id = hashlib.sha256(encoded({
            'payload_sha256': hashlib.sha256(payload).hexdigest(), 'signature': signature.hex(),
            'fingerprint': row['fingerprint'], 'key_id': row['key_id']})).hexdigest()
        row.update(id=replacement_id, payload=payload.hex(), envelope=envelope.hex(),
                   statement_hash=hashlib.sha256(payload).hexdigest())
        tables['auth_endorsements'].sort(key=lambda r: r['id'])
        for decision in tables['auth_decisions']:
            if decision['endorsement_id'] == previous_id:
                decision['endorsement_id'] = replacement_id
        (self.bundle/'materials/envelopes'/(previous_id+'.json')).unlink()
        (self.bundle/'materials/envelopes'/(replacement_id+'.json')).write_bytes(envelope)
        (self.bundle/'materials/snapshots'/(row['snapshot_hash']+'.jsonl')).unlink()
        write(self.bundle/'capture.json', capture)
        refresh(self.bundle, self.expectations, repin=True)
        self.check_failure('SIGNED_SCOPE')

    def test_full_snapshot_prefix_is_inconsistent_when_present_as_the_full_file(self):
        path = next((self.bundle/'materials/snapshots').glob('*.jsonl'))
        path.write_bytes(path.read_bytes().splitlines(keepends=True)[0])
        refresh(self.bundle, self.expectations)
        self.check_failure('AUTH_SNAPSHOT')

    def test_missing_snapshot_cannot_hide_impossible_byte_count_or_conflicting_lines(self):
        from crypto_reconciliation_lab.source_auth.crypto import sign_statement
        for variant in ('impossible_byte_count', 'conflicting_observed_line'):
            with self.subTest(variant=variant):
                shutil.rmtree(self.bundle);shutil.copytree(self.template, self.bundle)
                shutil.copyfile(self.fixture['expectations'], self.expectations)
                capture = load(self.bundle/'capture.json');t = capture['tables']
                row = next(r for r in t['auth_endorsements'] if r['key_id']=='lark-original')
                statement = json.loads(bytes.fromhex(row['payload']))
                sid = statement['stream_id']
                if variant == 'impossible_byte_count':
                    statement['plan']['input_bytes'] = 1
                    envelope = sign_statement(statement, b'1'*32, 'lark-original')
                    parsed = json.loads(envelope);payload = base64.b64decode(parsed['payload'])
                    signature = base64.b64decode(parsed['signatures'][0]['sig'])
                    replacement_id = hashlib.sha256(encoded({
                        'payload_sha256': hashlib.sha256(payload).hexdigest(), 'signature': signature.hex(),
                        'fingerprint': row['fingerprint'], 'key_id': row['key_id']})).hexdigest()
                    previous_id = row['id'];plan_hash = hashlib.sha256(encoded(statement['plan'])).hexdigest()
                    row.update(id=replacement_id, payload=payload.hex(), envelope=envelope.hex(),
                               statement_hash=hashlib.sha256(payload).hexdigest(), plan_hash=plan_hash)
                    t['auth_endorsements'].sort(key=lambda r:r['id'])
                    for decision in t['auth_decisions']:
                        if decision['endorsement_id'] == previous_id:
                            decision['endorsement_id'] = replacement_id
                    next(r for r in t['admission_streams'] if r['stream_id']==sid).update(input_bytes=1, plan_hash=plan_hash)
                    next(r for r in t['auth_streams'] if r['stream_id']==sid)['plan_hash'] = plan_hash
                    for attempt in t['delivery_attempts']:
                        if attempt['stream_id']==sid:attempt['plan_hash'] = plan_hash
                    (self.bundle/'materials/envelopes'/(previous_id+'.json')).unlink()
                    (self.bundle/'materials/envelopes'/(replacement_id+'.json')).write_bytes(envelope)
                else:
                    attempt = copy.deepcopy(next(r for r in t['delivery_attempts'] if r['stream_id']==sid))
                    original_id = attempt['id'];attempt['id'] = max(r['id'] for r in t['delivery_attempts'])+1
                    line = json.loads(bytes.fromhex(attempt['payload']));line['record']['amount'] = '999'
                    raw = encoded(line)+b'\n'
                    attempt.update(payload=raw.hex(), payload_sha256=hashlib.sha256(raw).hexdigest(),
                                   outcome='TRANSPORT_CONFLICT', reason='different payload at the same sequence')
                    t['delivery_attempts'].append(attempt)
                    did = next(r['decision_id'] for r in t['auth_attempt_links'] if r['attempt_id']==original_id)
                    decision = copy.deepcopy(next(r for r in t['auth_decisions'] if r['id']==did))
                    decision['id'] = max(r['id'] for r in t['auth_decisions'])+1
                    t['auth_decisions'].append(decision)
                    t['auth_attempt_links'].append({'attempt_id':attempt['id'],'decision_id':decision['id']})
                (self.bundle/'materials/snapshots'/(row['snapshot_hash']+'.jsonl')).unlink()
                write(self.bundle/'capture.json',capture);refresh(self.bundle,self.expectations,repin=True)
                self.check_failure('SIGNED_SCOPE')

    def test_sql_boolean_and_duplicate_id_are_not_valid_integer_identities(self):
        self.mutate(lambda t: t['receipts'][0].update(id=True))
        self.check_failure('CAPTURE_STRUCTURE')
        shutil.rmtree(self.bundle);shutil.copytree(self.template, self.bundle)
        shutil.copyfile(self.fixture['expectations'], self.expectations)
        self.mutate(lambda t: t['receipts'].append(copy.deepcopy(t['receipts'][0])))
        self.check_failure('CAPTURE_STRUCTURE')

    def test_member_hash_failures_are_separate_from_semantic_failures(self):
        path = self.bundle/'run.json';path.write_bytes(path.read_bytes()+b' ')
        self.check_failure('MEMBER_HASH')

    def test_rehashed_unsafe_ui_and_extra_path_members_are_rejected(self):
        (self.bundle/'app.js').write_text('window.PROVENANCE_XSS=1;')
        refresh(self.bundle, self.expectations)
        self.check_failure('PRESENTATION_INTEGRITY')
        (self.bundle/'unexpected').mkdir()
        self.check_failure('BUNDLE_PATH')

    def test_duplicate_json_keys_and_nonfinite_values_are_controlled_failures(self):
        original = self.expectations.read_bytes()
        self.expectations.write_bytes(b'{"format":0,"format":1}')
        self.check_failure('PROVENANCE_JSON')
        self.expectations.write_bytes(original.replace(b'"profile":"protected"', b'"profile":NaN'))
        self.check_failure('PROVENANCE_JSON')

    def test_verifier_is_offline_read_only_and_does_not_call_builders_or_runtime(self):
        before = {p.relative_to(self.bundle).as_posix(): fingerprint(p.read_bytes())
                  for p in self.bundle.rglob('*') if p.is_file()}
        with patch('sqlite3.connect', side_effect=AssertionError('no DB needed')), \
             patch('crypto_reconciliation_lab.provenance.exporter.export_provenance', side_effect=AssertionError('no exporter')), \
             patch('crypto_reconciliation_lab.source_auth.runtime.ingest_signed', side_effect=AssertionError('no admission')), \
             patch('crypto_reconciliation_lab.engine.reconcile', side_effect=AssertionError('no financial evaluation')):
            result = verify_bundle(self.bundle, self.expectations)
        self.assertEqual(result['exit_code'], 0, result['reasons'])
        after = {p.relative_to(self.bundle).as_posix(): fingerprint(p.read_bytes())
                 for p in self.bundle.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_valid_empty_financial_run_is_explicitly_unsupported_provenance(self):
        from crypto_reconciliation_lab.store import Store
        from crypto_reconciliation_lab.engine import reconcile
        from crypto_reconciliation_lab.source_auth.policy import enable_protection
        from crypto_reconciliation_lab.provenance.demo import CONFIG, RECEIVER, BALANCE, KNOWLEDGE, policy, _fixture_observation
        database = self.case/'empty.sqlite'
        store = Store(database, CONFIG, target_schema=5)
        first = policy(1)
        enable_protection(store, RECEIVER, first, observed_at='2026-11-14T09:00:00Z')
        run = reconcile(store, BALANCE, KNOWLEDGE)
        store.close()
        self.assertEqual(run['evidence'], {})
        self.assertTrue(all(f['reconciliation_state'] == 'NOT_EVALUATED' for f in run['findings']))
        expected, _ = _fixture_observation(database, run['run_id'], [{'epoch': 1, 'policy_hash': hashlib.sha256(encoded(first)).hexdigest()}], legacy=False)
        expectations = self.case/'empty-expectations.json';write(expectations, expected)
        materials = self.case/'empty-materials';materials.mkdir()
        bundle = self.case/'empty-bundle'
        exported = export_provenance(database, run['run_id'], materials, bundle)
        self.assertEqual(exported['status'], 'CREATED')
        result = verify_bundle(bundle, expectations)
        self.assertEqual((result['status'], result['exit_code'], result['reasons'][0]['code']), ('FAILED', 2, 'NO_LISTED_EVIDENCE'))
        self.assertEqual(result['financial_recomputation'], 'NOT_PERFORMED')


if __name__ == '__main__':
    unittest.main()
