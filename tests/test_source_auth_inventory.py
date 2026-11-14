"""S10-F2: closed persistent key and stream inventories in retained SQL.

Expected acceptance is literal. Mutations touch report evidence only; no verifier,
admission, financial or signing helper derives the expected inventory or hashes.
The optional baseline is the preserved independent-review bundle, not an oracle.
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


def states(case):
    yield case['sql_final']
    for operation in case['operations']:
        yield operation['before']
        yield operation['after']
    if 'interrupted' in case:
        yield case['interrupted']['before']
        yield case['interrupted']['after']


def sync_status(case):
    for name, rows in case['sql_final'].items():
        if name.startswith('auth_'):
            case['auth_status']['tables'][name] = copy.deepcopy(rows)


def orphan(state, template, wrong_fields=()):
    stream = copy.deepcopy(template['admission_streams'][0])
    owner = copy.deepcopy(template['auth_streams'][0])
    stream['stream_id'] = owner['stream_id'] = 'platform-demo:orphan'
    values = {'source': 'C1', 'receiver': 'NON-ANCHOR:receiver',
              'configuration_digest': '0' * 64, 'plan_hash': 'f' * 64}
    for field in wrong_fields:
        owner[field] = values[field]
    state['admission_streams'].append(stream)
    state['auth_streams'].append(owner)


def select_cut(cases, cut):
    case = cases['lost_ack'] if cut.startswith('interrupted_') else cases['normal_replay']
    if cut == 'before':
        state = case['operations'][0]['before']
    elif cut == 'after':
        state = case['operations'][0]['after']
    elif cut == 'final':
        state = case['sql_final']
    elif cut == 'auth_status':
        state = case['auth_status']['tables']
    else:
        state = case['interrupted'][cut.removeprefix('interrupted_')]
    return case, state


def mutate_report(report, name):
    cases = {case['id']: case for case in report['cases']}
    case = cases['normal_replay']
    if name in ('missing_referenced_key', 'missing_unused_key', 'missing_all_keys'):
        key = {'missing_referenced_key': 'P1-old', 'missing_unused_key': 'P1-new',
               'missing_all_keys': None}[name]
        for state in states(case):
            state['auth_keys'] = [row for row in state['auth_keys']
                                  if key is not None and row['key_id'] != key]
        sync_status(case)
    elif name == 'orphan_stream' or name.startswith('orphan_authority:'):
        fields = () if name == 'orphan_stream' else name.split(':')[1].split(',')
        for state in states(case):
            if state['admission_streams']:
                orphan(state, state, fields)
        sync_status(case)
    elif name.startswith('missing_key_cut:'):
        case, state = select_cut(cases, name.split(':')[1])
        state['auth_keys'] = [row for row in state['auth_keys'] if row['key_id'] != 'P1-old']
        if state is case['sql_final']:
            sync_status(case)
    elif name.startswith('orphan_cut:'):
        case, state = select_cut(cases, name.split(':')[1])
        if name.endswith(':auth_status'):
            owner = copy.deepcopy(case['sql_final']['auth_streams'][0])
            owner['stream_id'] = 'platform-demo:orphan'
            state['auth_streams'].append(owner)
        else:
            orphan(state, case['sql_final'])
            if state is case['sql_final']:
                sync_status(case)
    elif name.startswith('first_epoch:'):
        case = cases['new_key_resume']
        key = name.split(':')[1]
        for state in states(case):
            for row in state['auth_keys']:
                if row['key_id'] == key:
                    row['first_epoch'] = 2
        sync_status(case)
    elif name.startswith('persistent_key_field:'):
        field = name.split(':')[1]
        for state in states(case):
            row = next(row for row in state['auth_keys'] if row['key_id'] == 'P1-old')
            row[field] = {'source': 'C1', 'public_key': '0' * 64,
                          'fingerprint': 'f' * 64}[field]
        sync_status(case)
    elif name.startswith('missing_stream_table:'):
        table = name.split(':')[1]
        for state in states(case):
            state[table] = []
        sync_status(case)
    elif name == 'positive_sql_order':
        for case in report['cases']:
            if 'sql_final' not in case:
                continue
            for state in states(case):
                for rows in state.values():
                    if isinstance(rows, list):
                        rows.reverse()
            sync_status(case)
    elif name == 'positive_extra_information':
        report['extra:operator_note'] = 'This is explanatory information, not authority.'
    else:
        raise ValueError('unknown evidence mutation: ' + name)


MINIMAL_CASES = ('missing_referenced_key', 'orphan_stream')
CUTS = ('before', 'after', 'final', 'interrupted_before', 'interrupted_after', 'auth_status')
NEGATIVE_CASES = MINIMAL_CASES + (
    'missing_unused_key', 'missing_all_keys',
    'orphan_authority:source,receiver,configuration_digest,plan_hash',
    *('orphan_authority:' + field for field in ('source', 'receiver', 'configuration_digest', 'plan_hash')),
    *('missing_key_cut:' + cut for cut in CUTS),
    *('orphan_cut:' + cut for cut in CUTS),
    'first_epoch:P1-old', 'first_epoch:P1-new',
    *('persistent_key_field:' + field for field in ('source', 'public_key', 'fingerprint')),
    'missing_stream_table:admission_streams', 'missing_stream_table:auth_streams',
)


def mutate_bundle(baseline, target, name):
    """Reproducible evidence-only mutation and independent byte-manifest rebuild."""
    baseline, target = Path(baseline), Path(target)
    shutil.copytree(baseline, target, ignore=shutil.ignore_patterns(
        '*.db', '*.sqlite3', '*-journal', '*-wal', '*-shm'))
    report_path = target / 'report.json'
    report = json.loads(report_path.read_text())
    mutate_report(report, name)
    report_path.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    members = {}
    for path in sorted(target.rglob('*')):
        if path.is_file() and path.name != 'manifest.json':
            data = path.read_bytes()
            members[path.relative_to(target).as_posix()] = {
                'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    (target / 'manifest.json').write_text(json.dumps(
        {'format': 'source-auth-file-manifest-v1', 'files': members},
        sort_keys=True, indent=2) + '\n')
    return target


class SourceAuthInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix='auth-inventory-')
        supplied = os.environ.get('SOURCE_AUTH_INVENTORY_BASELINE')
        cls.bundle = Path(supplied) if supplied else Path(cls.workspace.name) / 'actual'
        if not supplied:
            demo_source_auth(cls.bundle)

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def rejects(self, names):
        for name in names:
            with self.subTest(mutation=name):
                with tempfile.TemporaryDirectory(prefix='auth-inventory-negative-') as temp:
                    target = mutate_bundle(self.bundle, Path(temp) / 'bundle', name)
                    with self.assertRaisesRegex(ValueError, 'SOURCE_AUTH_EVIDENCE:'):
                        verify_bundle(target, operator_anchor())

    def test_preserved_real_positive_bundle(self):
        self.assertEqual(verify_bundle(self.bundle, operator_anchor())['status'], 'PASSED')

    def test_w1_missing_referenced_persistent_key(self):
        self.rejects(['missing_referenced_key'])

    def test_w2_unexplained_stream_owner_pair(self):
        self.rejects(['orphan_stream'])

    def test_activated_policy_requires_unused_and_all_persistent_keys(self):
        self.rejects(['missing_unused_key', 'missing_all_keys'])

    def test_orphan_owner_authority_fields_cannot_escape_effect_linkage(self):
        self.rejects([name for name in NEGATIVE_CASES if name.startswith('orphan_authority:')])

    def test_key_inventory_covers_every_retained_cut_and_status(self):
        self.rejects(['missing_key_cut:' + cut for cut in CUTS])

    def test_stream_inventory_covers_every_retained_cut_and_status(self):
        self.rejects(['orphan_cut:' + cut for cut in CUTS])

    def test_key_first_epoch_survives_rotation_and_resume(self):
        self.rejects(['first_epoch:P1-old', 'first_epoch:P1-new'])

    def test_persistent_key_identity_matches_activated_policy(self):
        self.rejects([name for name in NEGATIVE_CASES if name.startswith('persistent_key_field:')])

    def test_stream_and_owner_tables_cannot_drop_effect_owners(self):
        self.rejects(['missing_stream_table:admission_streams', 'missing_stream_table:auth_streams'])

    def test_semantic_sql_permutation_and_extra_information_remain_valid(self):
        for name in ('positive_sql_order', 'positive_extra_information'):
            with self.subTest(mutation=name):
                with tempfile.TemporaryDirectory(prefix='auth-inventory-positive-') as temp:
                    target = mutate_bundle(self.bundle, Path(temp) / 'bundle', name)
                    self.assertEqual(verify_bundle(target, operator_anchor())['status'], 'PASSED')
