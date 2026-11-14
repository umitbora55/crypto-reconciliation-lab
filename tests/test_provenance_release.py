"""Bounded release checks cannot substitute counts or labels for provenance evidence."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location('provenance_release_' + name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify = load('verify_release')
build = load('build_release')


def demo_record():
    """Literal small contract; does not call the demo, engine or production validator."""
    groups = [
        ('clean_two_publishers', [('clean', 0, [])]),
        ('signed_custody_difference', [('signed_mismatch', 0, [])]),
        ('historical_correction_quarantine', [('history_original', 0, []), ('history_corrected', 0, []), ('history_quarantine', 0, [])]),
        ('rotation_and_revocation', [('rotation', 0, [])]),
        ('exact_replay', [('replay', 0, [])]),
        ('multiple_physical_candidates', [('ambiguous', 3, ['MULTIPLE_RECEIPT_CANDIDATES'])]),
        ('missing_full_snapshot', [('missing_snapshot', 3, ['MISSING_SIGNED_SNAPSHOT']), ('prefix_only', 3, ['MISSING_SIGNED_SNAPSHOT'])]),
        ('legacy_and_protected', [('legacy', 3, ['UNSIGNED_LEGACY']), ('broken_protected_link', 2, ['PROTECTED_LINK']), ('protected_downgrade', 2, ['PROFILE_MISMATCH'])]),
        ('external_expectations', [('wrong_run', 2, ['RUN_IDENTITY']), ('wrong_capture', 2, ['CAPTURE_BINDING']), ('wrong_policy', 2, ['POLICY_BINDING']), ('hidden_policy_head', 2, ['POLICY_BINDING'])]),
        ('semantic_relations', [('removed_receipt', 2, ['EVIDENCE_SCOPE']), ('changed_receipt', 2, ['RECEIPT_BINDING']),
                                ('removed_quarantine', 2, ['EVIDENCE_SCOPE']), ('removed_correction', 2, ['EVIDENCE_SCOPE']),
                                ('changed_effect', 2, ['DELIVERY_RELATION']), ('changed_endorsement', 2, ['ENDORSEMENT_BINDING']),
                                ('broken_link_and_missing_snapshot', 2, ['PROTECTED_LINK'])]),
    ]
    cases = []
    for group, entries in groups:
        for name, code, reasons in entries:
            cases.append({'id': name, 'group_id': group, 'passed': True,
                          'actual': {'exit_code': code, 'status': {0: 'VERIFIED_FOR_CAPTURE', 3: 'PARTIAL', 2: 'FAILED'}[code],
                                     'reasons': reasons}, 'financial': {'findings': []}})
    for case in cases[:2]:
        for asset, comparison, scope, amount in (
                ('TOKEN_X', 'A', 'Aster', '7'), ('TOKEN_X', 'A', 'Birch', '4'),
                ('TOKEN_X', 'B', 'customer_liability', '11'), ('TOKEN_Y', 'A', 'Aster', '0.3'),
                ('TOKEN_Y', 'A', 'Birch', '0.2'), ('TOKEN_Y', 'B', 'customer_liability', '0.5')):
            mismatch = case['id'] == 'signed_mismatch' and asset == 'TOKEN_X' and comparison == 'B'
            case['financial']['findings'].append({'asset': asset, 'comparison': comparison, 'scope': scope,
                'expected': amount, 'reported': '10' if mismatch else amount, 'difference': '1' if mismatch else '0',
                'data_state': 'COMPLETE', 'reconciliation_state': 'MISMATCH' if mismatch else 'MATCHED'})
    return {'format': 'provenance-demo-v1', 'status': 'PASS',
            'run_creation_authorization_cut': 'NOT_RECORDED', 'financial_recomputation': 'NOT_PERFORMED',
            'scenario_groups': [{'id': group, 'case_ids': [entry[0] for entry in entries], 'passed': True}
                                for group, entries in groups], 'cases': cases}


class ProvenanceReleaseTests(unittest.TestCase):
    def test_complete_literal_demo_inventory_is_accepted(self):
        result = verify.validate_provenance_demo(demo_record())
        self.assertEqual(result['scenario_count'], 10)
        self.assertEqual(result['case_count'], 24)
        self.assertEqual(len(set(result['case_ids'])), 24)

    def test_missing_duplicate_or_substituted_case_is_rejected(self):
        for mutation in ('missing', 'duplicate', 'substitute'):
            report = demo_record()
            if mutation == 'missing':
                report['cases'].pop()
            elif mutation == 'duplicate':
                report['cases'][-1] = deepcopy(report['cases'][0])
            else:
                report['cases'][-1]['id'] = 'unreviewed_case'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                verify.validate_provenance_demo(report)

    def test_group_inventory_cannot_omit_reassign_or_duplicate_cases(self):
        for mutation in ('missing', 'reassigned', 'duplicate'):
            report = demo_record()
            if mutation == 'missing':
                report['scenario_groups'].pop()
            elif mutation == 'reassigned':
                report['cases'][0]['group_id'] = 'semantic_relations'
            else:
                report['scenario_groups'][-1] = deepcopy(report['scenario_groups'][0])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                verify.validate_provenance_demo(report)

    def test_demo_expected_labels_cannot_override_actual_semantic_failure(self):
        report = demo_record()
        case = next(row for row in report['cases'] if row['id'] == 'broken_protected_link')
        case['actual'] = case['expected'] = {'exit_code': 0, 'status': 'VERIFIED_FOR_CAPTURE', 'reasons': []}
        with self.assertRaisesRegex(ValueError, 'semantic result differs'):
            verify.validate_provenance_demo(report)

    def test_dependency_error_is_not_a_semantic_negative(self):
        report = demo_record()
        case = next(row for row in report['cases'] if row['id'] == 'changed_effect')
        case['actual']['reasons'] = ['AUTH_DEPENDENCY']
        with self.assertRaisesRegex(ValueError, 'semantic result differs'):
            verify.validate_provenance_demo(report)

    def test_false_exit_code_is_not_integer_zero(self):
        report = demo_record()
        report['cases'][0]['actual']['exit_code'] = False
        with self.assertRaisesRegex(ValueError, 'semantic result differs'):
            verify.validate_provenance_demo(report)

    def test_signed_source_cannot_erase_financial_difference_or_history_limit(self):
        for mutation in ('financial', 'authorization_cut', 'recomputed'):
            report = demo_record()
            if mutation == 'financial':
                next(row for row in report['cases'][1]['financial']['findings']
                     if row['asset'] == 'TOKEN_X' and row['comparison'] == 'B')['difference'] = '0'
            elif mutation == 'authorization_cut':
                report['run_creation_authorization_cut'] = 'VERIFIED'
            else:
                report['financial_recomputation'] = 'PERFORMED'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                verify.validate_provenance_demo(report)

    def test_all_core_commands_must_explicitly_refuse_without_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            gate = verify.Verification(Path(temporary) / 'gate', 'core')
            def absent(name, argv, **kwargs):
                self.assertEqual(kwargs['expected'], 2)
                self.assertIn('-I', argv)
                (gate.output / 'logs' / (name + '.stderr.txt')).write_text('AUTH_DEPENDENCY')
                return json.dumps({'status': 'FAILED', 'exit_code': 2, 'reasons': [{'code': 'AUTH_DEPENDENCY'}]})
            with patch.object(gate, 'run', side_effect=absent) as run:
                verify.core_provenance_denied(gate, 'never-executed')
            self.assertEqual(run.call_count, 3)
            self.assertEqual(set(gate.record['core_provenance_refusal']['operations']), {'demo', 'export', 'verify'})
            self.assertFalse((gate.output / 'core-provenance-must-not-exist').exists())

    def test_core_refusal_after_creating_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            gate = verify.Verification(Path(temporary) / 'gate', 'core')
            def misleading(name, *args, **kwargs):
                (gate.output / 'core-provenance-must-not-exist').mkdir()
                (gate.output / 'logs' / (name + '.stderr.txt')).write_text('AUTH_DEPENDENCY')
                return ''
            with patch.object(gate, 'run', side_effect=misleading):
                with self.assertRaisesRegex(ValueError, 'before creating output'):
                    verify.core_provenance_denied(gate, 'never-executed')

    def test_actual_case_command_requires_exact_paths_exit_and_log_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / 'cases' / 'clean' / 'commands' / 'verify'
            folder.mkdir(parents=True)
            result = {'status': 'VERIFIED_FOR_CAPTURE', 'exit_code': 0, 'reasons': []}
            (folder / 'stdout.txt').write_text(json.dumps(result))
            (folder / 'stderr.txt').write_text('')
            record = {'argv': ['never-executed', '-B', '-I', '-m', 'crypto_reconciliation_lab', 'verify-provenance',
                       '--bundle', str(root / 'cases/clean/bundle'), '--expectations', str(root / 'cases/clean/expectations.json')],
                      'cwd': str(root), 'exit_code': 0,
                      'stdout': 'cases/clean/commands/verify/stdout.txt', 'stderr': 'cases/clean/commands/verify/stderr.txt',
                      'stdout_sha256': hashlib.sha256((folder / 'stdout.txt').read_bytes()).hexdigest(),
                      'stderr_sha256': hashlib.sha256(b'').hexdigest()}
            (folder / 'command.json').write_text(json.dumps(record))
            self.assertEqual(verify.provenance_command_record(root, 'clean', 'never-executed', ['-I'], root, result)['exit_code'], 0)
            for mutation in ('argv', 'cwd', 'exit', 'hash', 'substituted_stdout'):
                changed = deepcopy(record)
                if mutation == 'argv':
                    changed['argv'][-1] = str(root / 'other-expectations.json')
                elif mutation == 'cwd':
                    changed['cwd'] = str(root / 'other-origin')
                elif mutation == 'exit':
                    changed['exit_code'] = False
                elif mutation == 'hash':
                    changed['stdout_sha256'] = '0' * 64
                else:
                    (folder / 'stdout.txt').write_text('{}')
                    changed['stdout_sha256'] = hashlib.sha256(b'{}').hexdigest()
                (folder / 'command.json').write_text(json.dumps(changed))
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    verify.provenance_command_record(root, 'clean', 'never-executed', ['-I'], root, result)

    def test_accepted_575_scope_and_packaged_assets_remain_separately_bound(self):
        scope = verify.TEST_SCOPE
        path = ROOT / scope.ACCEPTED_PATH
        self.assertEqual(scope.ACCEPTED_PATH, 'contracts/release-test-scope-0.8.2.json')
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         '2191421a231dff4b560e3c0c6b3469a4f097fe277009a56f1e48ed4a7d7aa592')
        self.assertEqual(len(set(json.loads(path.read_bytes())['current']['test_ids'])), 575)
        self.assertLessEqual({'contracts/release-test-scope-0.8.2.json', 'contracts/release-test-scope-0.9.0.json'}, build.REQUIRED)
        package_data = tomllib.loads((ROOT / 'pyproject.toml').read_text())['tool']['setuptools']['package-data']
        self.assertEqual(package_data['crypto_reconciliation_lab.provenance'], ['assets/*.html', 'assets/*.css', 'assets/*.js'])
