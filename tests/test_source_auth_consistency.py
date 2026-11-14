"""S10-F1: independently rehashed evidence must retain its relational meaning.

The optional fixture path is only for replaying the preserved independent 0.8.0
bundle. Ordinary source/installed suites create the unchanged real demo. No
expected result is calculated by the verifier, runtime, or financial engine.
The public mutation catalogue also drives actual installed-CLI rejection checks.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from crypto_reconciliation_lab.source_auth.demo import demo_source_auth
from crypto_reconciliation_lab.source_auth.fixtures import operator_anchor
from crypto_reconciliation_lab.source_auth.verifier import verify_bundle


def first_response(cases):
    return cases['valid_publishers']['operations'][0]['result']['responses'][0]


def worker_result(cases):
    return next(row['result'] for row in cases['policy_race']['process']['observations']
                if row['type'] == 'RESULT')


def sync_auth_status(case):
    for name in case['auth_status']['tables']:
        case['auth_status']['tables'][name] = copy.deepcopy(case['sql_final'][name])


def duplicate_rows(cases, tables, changed=False):
    case = cases['normal_replay']
    for state in [case['sql_final']] + [op['after'] for op in case['operations']]:
        for table in tables:
            row = copy.deepcopy(state[table][0])
            if changed:
                # Keep the actual composite primary key while contradicting data.
                field = 'reason' if table == 'delivery_effects' else 'core_receipt_id'
                row[field] = 'invented explanation' if field == 'reason' else 2
            state[table].append(row)
    sync_auth_status(case)


def mutate_report(report, name):
    """Change evidence only, preserving original snapshots/signatures/anchor."""
    cases = {case['id']: case for case in report['cases']}
    response = first_response(cases)
    operations = cases['valid_publishers']['operations']
    if name == 'R1_missing_response_authorization':
        for op in operations:
            for item in op['result']['responses']:
                del item['authorization']
    elif name == 'R2_substituted_response_receipt':
        response['core_receipt_row_id'] = 2
    elif name == 'R3_substituted_response_identity':
        response.update(stream_id='custodian-demo:unrelated', sequence=999,
                        outcome='REPLAY', ack=False)
    elif name == 'R4_missing_positive_responses':
        for op in operations:
            op['result']['responses'] = []
    elif name == 'R5_contradictory_worker_result':
        value = worker_result(cases)
        value.clear()
        value.update(format='source-auth-admission-v1', status='COMPLETE',
                     responses=[{'outcome': 'COMMITTED', 'core_receipt_row_id': 1}])
    elif name == 'R6_duplicate_effect_rows':
        duplicate_rows(cases, ('delivery_effects', 'auth_delivery_links'))
    elif name.startswith('response_field:'):
        key = name.split(':')[1]
        values = {'stream_id': 'custodian-demo:unrelated', 'sequence': 999,
                  'outcome': 'REPLAY', 'ack': False, 'durable': False,
                  'blocked': True, 'committed_prefix': 26, 'attempt_id': 2,
                  'disposition': 'QUARANTINED', 'reason': 'invented explanation'}
        response[key] = values[key]
    elif name.startswith('response_type:'):
        key = name.split(':')[1]
        response[key] = {'sequence': True, 'attempt_id': True, 'ack': 1,
                         'durable': 1, 'blocked': 0, 'committed_prefix': True,
                         'core_receipt_row_id': True}[key]
    elif name.startswith('authorization_field:'):
        key = name.split(':')[1]
        response['authorization'][key] = {
            'decision_id': 2, 'original_decision_id': 2, 'epoch': 2,
            'policy_hash': '0' * 64, 'key_id': 'C1-key', 'key_status': 'revoked',
            'currently_authorized': False, 'decision': 'HISTORICAL_REPLAY',
            'endorsement_id': '0' * 64}[key]
    elif name.startswith('authorization_type:'):
        key = name.split(':')[1]
        response['authorization'][key] = {
            'decision_id': True, 'original_decision_id': True, 'epoch': True,
            'currently_authorized': 1}[key]
    elif name.startswith('core_result:'):
        key = name.split(':')[1]
        other = operations[0]['result']['responses'][1]['core_result']
        response['core_result'][key] = {
            'receipt_id': other['receipt_id'], 'record_id': other['record_id'],
            'status': 'QUARANTINED', 'error': 'invented error',
            'reason_code': 'INVENTED'}[key]
    elif name.startswith('authorization_shape:'):
        shape = name.split(':')[1]
        response['authorization'] = {'empty': {}, 'null': None, 'list': []}[shape]
    elif name.startswith('responses_shape:'):
        shape = name.split(':')[1]
        if shape == 'missing':
            del operations[0]['result']['responses']
        else:
            operations[0]['result']['responses'] = {'null': None, 'dict': {}}[shape]
    elif name == 'same_count_other_stream_response':
        operations[0]['result']['responses'][0] = copy.deepcopy(
            operations[1]['result']['responses'][0])
    elif name == 'same_count_duplicate_response':
        operations[0]['result']['responses'][0] = copy.deepcopy(
            operations[0]['result']['responses'][1])
    elif name == 'reordered_responses':
        operations[0]['result']['responses'][:2] = list(reversed(
            operations[0]['result']['responses'][:2]))
    elif name.startswith('missing_required_response:'):
        del response[name.split(':')[1]]
    elif name.startswith('missing_required_authorization:'):
        del response['authorization'][name.split(':')[1]]
    elif name.startswith('duplicate:'):
        _, table, variant = name.split(':')
        duplicate_rows(cases, (table,), changed=(variant == 'different'))
    elif name.startswith('duplicate_primary_key:'):
        table = name.split(':')[1]
        case = cases['normal_replay']
        case['sql_final'][table].append(copy.deepcopy(case['sql_final'][table][0]))
        sync_auth_status(case)
    elif name == 'changed_intermediate_effect':
        cases['normal_replay']['operations'][1]['before']['delivery_effects'][0]['reason'] = 'changed then hidden'
    elif name == 'changed_intermediate_attempt':
        cases['normal_replay']['operations'][1]['after']['delivery_attempts'][0]['reason'] = 'changed then hidden'
    elif name == 'changed_intermediate_decision':
        cases['normal_replay']['operations'][1]['before']['auth_decisions'][0]['observed_at'] = '2026-11-12T00:00:00.000000Z'
    elif name == 'missing_intermediate_effect':
        cases['normal_replay']['operations'][1]['before']['delivery_effects'].pop()
    elif name == 'current_decision_substituted_for_original':
        item = cases['normal_replay']['operations'][1]['result']['responses'][0]
        item['authorization']['original_decision_id'] = item['authorization']['decision_id']
    elif name == 'historical_replay_relabelled_current':
        item = cases['revoked_replay']['operations'][1]['result']['responses'][0]
        item['authorization']['currently_authorized'] = True
    elif name == 'blocked_response_relabelled_ack':
        cases['authorized_plan_conflict']['operations'][2]['result']['responses'][0]['ack'] = True
    elif name == 'partial_response_removed':
        cases['new_key_resume']['operations'][0]['result']['responses'] = []
    elif name == 'replay_response_removed':
        cases['normal_replay']['operations'][1]['result']['responses'] = []
    elif name == 'blocked_response_removed':
        cases['authorized_plan_conflict']['operations'][2]['result']['responses'] = []
    elif name.startswith('worker_or_operation:'):
        _, side, field = name.split(':')
        value = worker_result(cases) if side == 'worker' else cases['policy_race']['operations'][0]['result']
        if field == 'status':
            value['status'] = 'COMPLETE'
        elif field == 'response':
            value['responses'] = [copy.deepcopy(response)]
        elif field == 'receipt':
            item = copy.deepcopy(response)
            item['core_receipt_row_id'] = 2
            value['responses'] = [item]
        elif field == 'authorization':
            item = copy.deepcopy(response)
            item['authorization']['decision_id'] = 2
            value['responses'] = [item]
        elif field == 'audit':
            value['rejection']['audit_id'] = 999
        else:
            raise AssertionError(name)
    elif name == 'sql_inventory_order':
        for case in cases.values():
            states = [case['sql_final']] if 'sql_final' in case else []
            for op in case.get('operations', []):
                states.extend((op['before'], op['after']))
            if 'interrupted' in case:
                states.extend((case['interrupted']['before'], case['interrupted']['after']))
            for state in states:
                for rows in state.values():
                    if isinstance(rows, list):
                        rows.reverse()
            if 'auth_status' in case:
                sync_auth_status(case)
    elif name == 'extra_information':
        report['extra:explanation'] = 'Non-authoritative operator note.'
    else:
        raise AssertionError('unknown test mutation: ' + name)


R_CASES = (
    'R1_missing_response_authorization', 'R2_substituted_response_receipt',
    'R3_substituted_response_identity', 'R4_missing_positive_responses',
    'R5_contradictory_worker_result', 'R6_duplicate_effect_rows',
)
RESPONSE_FIELDS = ('stream_id', 'sequence', 'outcome', 'ack', 'durable', 'blocked',
                   'committed_prefix', 'attempt_id', 'disposition', 'reason')
AUTH_FIELDS = ('decision_id', 'original_decision_id', 'epoch', 'policy_hash',
               'key_id', 'key_status', 'currently_authorized', 'decision', 'endorsement_id')
RESPONSE_REQUIRED = ('format', 'stream_id', 'sequence', 'outcome', 'ack', 'durable',
                     'blocked', 'committed_prefix', 'attempt_id', 'core_receipt_row_id',
                     'core_result', 'disposition', 'reason', 'authorization')
NEIGHBORS = (
    *(f'response_field:{key}' for key in RESPONSE_FIELDS),
    *(f'response_type:{key}' for key in ('sequence', 'attempt_id', 'ack', 'durable',
                                       'blocked', 'committed_prefix', 'core_receipt_row_id')),
    *(f'authorization_field:{key}' for key in AUTH_FIELDS),
    *(f'authorization_type:{key}' for key in ('decision_id', 'original_decision_id',
                                            'epoch', 'currently_authorized')),
    *(f'core_result:{key}' for key in ('receipt_id', 'record_id', 'status', 'error', 'reason_code')),
    *(f'authorization_shape:{shape}' for shape in ('empty', 'null', 'list')),
    *(f'responses_shape:{shape}' for shape in ('missing', 'null', 'dict')),
    'same_count_other_stream_response', 'same_count_duplicate_response', 'reordered_responses',
    *(f'missing_required_response:{key}' for key in RESPONSE_REQUIRED),
    *(f'missing_required_authorization:{key}' for key in AUTH_FIELDS),
    *(f'duplicate:{table}:{variant}' for table in ('delivery_effects', 'auth_delivery_links')
      for variant in ('same', 'different')),
    *(f'duplicate_primary_key:{table}' for table in ('auth_configuration', 'auth_policy_snapshots',
        'auth_policy_activations', 'auth_keys', 'auth_streams', 'auth_endorsements',
        'auth_decisions', 'auth_attempt_links', 'admission_streams', 'delivery_attempts',
        'receipts', 'records')),
    'changed_intermediate_effect', 'changed_intermediate_attempt', 'changed_intermediate_decision',
    'missing_intermediate_effect', 'current_decision_substituted_for_original',
    'historical_replay_relabelled_current', 'blocked_response_relabelled_ack',
    'partial_response_removed', 'replay_response_removed', 'blocked_response_removed',
    *(f'worker_or_operation:{side}:{field}' for side in ('worker', 'operation')
      for field in ('status', 'response', 'receipt', 'authorization', 'audit')),
)
NEGATIVE_CASES = R_CASES + NEIGHBORS


def mutate_bundle(baseline, target, mutation):
    """Keep every byte inventory entry coherent without calling verifier.rehash."""
    shutil.copytree(baseline, target, ignore=shutil.ignore_patterns(
        '*.sqlite3', '*-journal', '*-wal', '*-shm'))
    path = target / 'report.json'
    report = json.loads(path.read_text())
    mutate_report(report, mutation)
    path.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    manifest_path = target / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    for name in manifest['files']:
        data = (target / name).read_bytes()
        manifest['files'][name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    return target


class SourceAuthConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix='auth-consistency-')
        supplied = os.environ.get('SOURCE_AUTH_CONSISTENCY_BASELINE')
        cls.bundle = Path(supplied) if supplied else Path(cls.workspace.name) / 'actual'
        if not supplied:
            demo_source_auth(cls.bundle)

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def rejects(self, names):
        for name in names:
            with self.subTest(mutation=name):
                with tempfile.TemporaryDirectory(prefix='auth-consistency-negative-') as tmp:
                    target = mutate_bundle(self.bundle, Path(tmp) / 'bundle', name)
                    with self.assertRaisesRegex(ValueError, 'SOURCE_AUTH_EVIDENCE:'):
                        verify_bundle(target, operator_anchor())

    def test_preserved_real_positive_bundle(self):
        self.assertEqual(verify_bundle(self.bundle, operator_anchor())['status'], 'PASSED')

    def test_r1_missing_response_authorization(self):
        self.rejects([R_CASES[0]])

    def test_r2_unrelated_existing_receipt(self):
        self.rejects([R_CASES[1]])

    def test_r3_response_identity_outcome_ack(self):
        self.rejects([R_CASES[2]])

    def test_r4_empty_successful_response_inventory(self):
        self.rejects([R_CASES[3]])

    def test_r5_worker_result_contradicts_operation(self):
        self.rejects([R_CASES[4]])

    def test_r6_duplicate_composite_sql_rows(self):
        self.rejects([R_CASES[5]])

    def test_each_response_field_and_type(self):
        self.rejects([n for n in NEIGHBORS if n.startswith(('response_field:', 'response_type:'))])

    def test_each_authorization_field_and_type(self):
        self.rejects([n for n in NEIGHBORS if n.startswith(('authorization_field:', 'authorization_type:'))])

    def test_each_core_result_field(self):
        self.rejects([n for n in NEIGHBORS if n.startswith('core_result:')])

    def test_required_inventory_shapes_and_same_count_substitution(self):
        self.rejects([n for n in NEIGHBORS if n.startswith(('authorization_shape:', 'responses_shape:', 'same_count_')) or n == 'reordered_responses'])

    def test_missing_required_fields(self):
        self.rejects([n for n in NEIGHBORS if n.startswith('missing_required_')])

    def test_composite_duplicates_same_and_different_payload(self):
        self.rejects([n for n in NEIGHBORS if n.startswith('duplicate:')])

    def test_other_sql_primary_key_duplicates(self):
        self.rejects([n for n in NEIGHBORS if n.startswith('duplicate_primary_key:')])

    def test_intermediate_sql_history_cannot_change_or_disappear(self):
        self.rejects([n for n in NEIGHBORS if n.startswith(('changed_intermediate_', 'missing_intermediate_'))])

    def test_replay_current_and_original_decisions_remain_distinct(self):
        self.rejects(['current_decision_substituted_for_original', 'historical_replay_relabelled_current'])

    def test_partial_replay_and_blocked_response_coverage(self):
        self.rejects(['partial_response_removed', 'replay_response_removed',
                      'blocked_response_removed', 'blocked_response_relabelled_ack'])

    def test_worker_and_operation_single_side_disagreements(self):
        self.rejects([n for n in NEIGHBORS if n.startswith('worker_or_operation:')])

    def test_nonsemantic_sql_list_order_and_extra_information_remain_valid(self):
        for name in ('sql_inventory_order', 'extra_information'):
            with self.subTest(mutation=name):
                with tempfile.TemporaryDirectory(prefix='auth-consistency-positive-') as tmp:
                    target = mutate_bundle(self.bundle, Path(tmp) / 'bundle', name)
                    self.assertEqual(verify_bundle(target, operator_anchor())['status'], 'PASSED')
