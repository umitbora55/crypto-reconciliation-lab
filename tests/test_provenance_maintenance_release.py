"""Independent finite release controls for the two Stage 11.1 repairs."""
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('maintenance_release_gate', ROOT/'scripts/verify_release.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def literal_controls():
    setup = {'format': 'release-provenance-maintenance-v1', 'package_version': '0.10.0',
             'f1_preservation': {'external_changed_fields': ['capture_digest'], 'raw_run_equal': True,
                                 'signed_materials_equal': True},
             'f2_authoritative_capture_unchanged': True,
             'f2_identity_paths': [{'receipt_id': value, 'effect_count': 1} for value in
                                  ('9007199254740991', '9007199254740992', '9007199254740993', '9223372036854775807')],
             'fixtures': {name: {} for name in ('rotation', 'later_replay_promoted', 'large_ids', 'tampered_transport')}}
    results = {}
    for name, code, status, reasons in (
            ('rotation', 0, 'VERIFIED_FOR_CAPTURE', []),
            ('later_replay_promoted', 2, 'FAILED', ['DELIVERY_CAUSALITY']),
            ('large_ids', 0, 'VERIFIED_FOR_CAPTURE', []),
            ('tampered_transport', 2, 'FAILED', ['PRESENTATION_INTEGRITY'])):
        results[name] = {'exit_code': code, 'status': status, 'reasons': [{'code': reason} for reason in reasons],
                         'run_creation_authorization_cut': 'NOT_RECORDED', 'financial_recomputation': 'NOT_PERFORMED'}
    return setup, results


class ProvenanceMaintenanceReleaseTests(unittest.TestCase):
    def test_literal_four_control_scope_is_accepted(self):
        setup, results = literal_controls()
        self.assertEqual(gate.validate_provenance_maintenance(setup, results), {
            'status': 'PASS', 'case_count': 4,
            'case_ids': ['large_ids', 'later_replay_promoted', 'rotation', 'tampered_transport']})

    def test_missing_or_substituted_cli_control_is_rejected(self):
        for substitute in (False, True):
            setup, results = literal_controls()
            value = results.pop('later_replay_promoted')
            if substitute:
                results['unreviewed_case'] = value
            with self.subTest(substitute=substitute), self.assertRaisesRegex(ValueError, 'inventory differs'):
                gate.validate_provenance_maintenance(setup, results)

    def test_f1_asset_or_dependency_rejection_cannot_replace_causality(self):
        for reason in ('PRESENTATION_INTEGRITY', 'AUTH_DEPENDENCY'):
            setup, results = literal_controls()
            results['later_replay_promoted']['reasons'] = [{'code': reason}]
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, 'semantic CLI result differs'):
                gate.validate_provenance_maintenance(setup, results)

    def test_float_boolean_or_rounded_identity_is_not_valid_coverage(self):
        for mutation in ('boolean_exit', 'float_count', 'rounded_id'):
            setup, results = literal_controls()
            if mutation == 'boolean_exit':
                results['rotation']['exit_code'] = False
            elif mutation == 'float_count':
                setup['f2_identity_paths'][0]['effect_count'] = 1.0
            else:
                setup['f2_identity_paths'][2]['receipt_id'] = '9007199254740992'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                gate.validate_provenance_maintenance(setup, results)

    def test_altered_authority_raw_bytes_or_limits_are_rejected(self):
        for mutation in ('authority', 'run', 'materials', 'capture', 'limits'):
            setup, results = literal_controls()
            if mutation == 'authority':
                setup['f1_preservation']['external_changed_fields'].append('policy_head')
            elif mutation == 'run':
                setup['f1_preservation']['raw_run_equal'] = False
            elif mutation == 'materials':
                setup['f1_preservation']['signed_materials_equal'] = False
            elif mutation == 'capture':
                setup['f2_authoritative_capture_unchanged'] = False
            else:
                results['rotation']['run_creation_authorization_cut'] = 'VERIFIED'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                gate.validate_provenance_maintenance(setup, results)

    def test_reviewed_641_scope_remains_a_separate_immutable_ancestor(self):
        scope = gate.TEST_SCOPE
        self.assertEqual(scope.PROVENANCE_PATH, 'contracts/release-test-scope-0.9.0.json')
        data = (ROOT/scope.PROVENANCE_PATH).read_bytes()
        self.assertEqual(len(data), 111648)
        self.assertEqual(hashlib.sha256(data).hexdigest(), '111f1975957662efe1f73083be03a608f37b055fcf9b61da51c129da40e5a4f5')
        self.assertEqual(len(set(json.loads(data)['current']['test_ids'])), 641)
        self.assertEqual(scope.ACCEPTED_PATH, 'contracts/release-test-scope-0.8.2.json')


if __name__ == '__main__':
    unittest.main()
