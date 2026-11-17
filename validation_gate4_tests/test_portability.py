"""Portability evidence cannot convert missing or substituted checks into PASS."""
import copy
import unittest

from validation_lab.gate4_portability import compare_results


def complete_pair():
    # This is only a validator unit fixture, never a product execution witness.
    shared = {key: {'literal_fixture': key} for key in (
        'source_snapshot', 'five_files', 'financial_result', 'links', 'execution_id', 'run_id')}
    result = []
    for method in ('BASELINE', 'CANDIDATE_WAL_FULL'):
        checks = {name: {'status': 'PASS', 'result': {}} for name in (
            'auth_export_backup', 'legacy_review', 'offline_replay', 'migration_restore')}
        checks['auth_export_backup']['result'] = copy.deepcopy(shared)
        checks['legacy_review']['result'] = {'compatible': method == 'BASELINE'}
        result.append({'method': method, 'checks': checks})
    return result


class PortabilityVerifierTests(unittest.TestCase):
    def test_complete_equal_pair_still_does_not_accept_incompatible_candidate(self):
        result = compare_results(complete_pair())
        self.assertEqual(result['candidate_acceptance'], 'CANDIDATE_NOT_ACCEPTED')
        self.assertEqual(result['decision_under_existing_invariants'], 'NO_CHANGE')

    def test_empty_duplicate_or_missing_checks_cannot_pass(self):
        pair = complete_pair()
        for altered in ([], [pair[0], pair[0]], [dict(method='BASELINE', checks={}), pair[1]]):
            with self.subTest(altered=altered), self.assertRaises(ValueError):
                compare_results(altered)

    def test_same_count_substituted_logical_evidence_cannot_pass(self):
        pair = complete_pair()
        pair[1]['checks']['auth_export_backup']['result']['source_snapshot']['literal_fixture'] = 'substituted'
        with self.assertRaisesRegex(ValueError, 'logical/export evidence differs'):
            compare_results(pair)

    def test_falsely_compatible_review_result_cannot_erase_known_failure(self):
        pair = complete_pair()
        pair[1]['checks']['legacy_review']['result']['compatible'] = True
        with self.assertRaisesRegex(AssertionError, 'incompatibility lost'):
            compare_results(pair)
