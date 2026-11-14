"""Relational boundary probes independent of response-only mutations."""
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


def retained_states(case):
    result = [case['sql_final']]
    for operation in case['operations']:
        result.extend((operation['before'], operation['after']))
    return result


class SourceAuthSQLConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix='auth-sql-consistency-')
        supplied = os.environ.get('SOURCE_AUTH_CONSISTENCY_BASELINE')
        cls.bundle = Path(supplied) if supplied else Path(cls.workspace.name) / 'actual'
        if not supplied:
            demo_source_auth(cls.bundle)

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def reject(self, name, change):
        target = Path(self.workspace.name) / name
        shutil.copytree(self.bundle, target, ignore=shutil.ignore_patterns(
            '*.sqlite3', '*-journal', '*-wal', '*-shm'))
        path = target / 'report.json'
        report = json.loads(path.read_text())
        change({case['id']: case for case in report['cases']})
        path.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
        manifest_path = target / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        for member in manifest['files']:
            data = (target / member).read_bytes()
            manifest['files'][member] = {
                'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
        with self.assertRaisesRegex(ValueError, 'SOURCE_AUTH_EVIDENCE'):
            verify_bundle(target, operator_anchor())

    def test_sql_boolean_identity_is_not_integer_identity(self):
        for table, field in (('receipts', 'id'), ('delivery_effects', 'sequence'),
                             ('auth_decisions', 'epoch'), ('delivery_attempts', 'sequence'),
                             ('auth_attempt_links', 'decision_id'),
                             ('delivery_attempts', 'effect_sequence')):
            with self.subTest(table=table, field=field):
                def change(cases):
                    case = cases['normal_replay']
                    for state in retained_states(case) + [case['auth_status']['tables']]:
                        for row in state.get(table, []):
                            if row[field] == 1:
                                row[field] = True
                self.reject('boolean-' + table + '-' + field, change)

    def test_auth_status_cannot_omit_or_contradict_sql_binding(self):
        for field in ('table', 'protected', 'active_policy'):
            with self.subTest(field=field):
                def change(cases):
                    status = cases['valid_publishers']['auth_status']
                    if field == 'table':
                        del status['tables']['auth_delivery_links']
                    elif field == 'protected':
                        del status['protected']
                    else:
                        status['active_policy']['policy_hash'] = '0' * 64
                self.reject('auth-status-' + field, change)

    def test_response_and_effect_cannot_jointly_rewrite_receipt_error(self):
        def change(cases):
            case = cases['invalid_amount']
            for state in retained_states(case):
                for effect in state['delivery_effects']:
                    core = json.loads(effect['core_result'])
                    core['error'] = 'different error'
                    effect['core_result'] = json.dumps(core, sort_keys=True, separators=(',', ':'))
            case['operations'][0]['result']['responses'][0]['core_result']['error'] = 'different error'
        self.reject('contradictory-core-error', change)

    def test_fresh_case_cannot_import_older_operational_history(self):
        for table in ('auth_rejections', 'records'):
            with self.subTest(table=table):
                def change(cases):
                    case = cases['normal_replay']
                    row = (cases['bad_signature']['sql_final']['auth_rejections'][0]
                           if table == 'auth_rejections' else
                           cases['valid_publishers']['sql_final']['records'][2])
                    for state in retained_states(case) + [case['auth_status']['tables']]:
                        if table in state:
                            state[table].append(dict(row))
                self.reject('invented-prehistory-' + table, change)

    def test_lost_ack_requires_original_committed_input_attempt(self):
        for field, value in (('outcome', 'REPLAY'), ('payload', '00'),
                             ('plan_hash', '0' * 64), ('extra_record', None)):
            with self.subTest(field=field):
                def change(cases):
                    case = cases['lost_ack']
                    states = retained_states(case) + [case['interrupted']['before'],
                                                      case['interrupted']['after']]
                    for state in states:
                        if field == 'extra_record':
                            if state is not case['interrupted']['before']:
                                state['records'].append(dict(
                                    cases['valid_publishers']['sql_final']['records'][2]))
                        else:
                            for row in state['delivery_attempts']:
                                if row['id'] == 1:
                                    row[field] = value
                self.reject('lost-ack-attempt-' + field, change)
