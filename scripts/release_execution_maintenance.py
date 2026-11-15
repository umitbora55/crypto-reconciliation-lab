"""Run finite Stage12.1 installed controls, never the full suite or experiment."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import unittest

CORE_CASES = (
    'test_stage12_1_export_alias.Stage121ExportAliasTests.test_dotdot_aliases_refuse_dangling_final_symlink_before_any_publication',
    'test_stage12_1_export_alias.Stage121ExportAliasTests.test_dotdot_alias_preserves_existing_final_symlink_and_target_bytes',
    'test_stage12_1_export.Stage121ExportTests.test_ordinary_export_preserves_raw_bytes_namespace_and_next_write',
    'test_stage12_1_export.Stage121ExportTests.test_sidecar_dotdot_routes_publish_safely_without_creating_reserved_names',
    'test_stage12_1_export.Stage121ExportTests.test_canonical_database_sidecar_and_descendant_targets_are_rejected',
    'test_stage12_1_export.Stage121ExportTests.test_existing_directory_file_and_dangling_symlink_are_never_replaced',
    'test_stage12_1_export.Stage121ExportTests.test_dotdot_alias_of_existing_target_does_not_create_skipped_directory',
    'test_stage12_1_input.Stage121TimestampTests.test_lower_utc_overflow_balance_at_is_controlled_input_error',
    'test_stage12_1_input.Stage121TimestampTests.test_lower_utc_overflow_knowledge_at_is_controlled_input_error',
    'test_stage12_1_input.Stage121TimestampTests.test_upper_utc_overflow_balance_at_is_controlled_input_error',
    'test_stage12_1_input.Stage121TimestampTests.test_upper_utc_overflow_knowledge_at_is_controlled_input_error',
    'test_stage12_1_input.Stage121TimestampTests.test_invalid_syntax_remains_structured_input_error',
    'test_stage12_1_input.Stage121TimestampTests.test_near_utc_bounds_are_valid_with_appropriate_opening',
    'test_stage12_1_input.Stage121TimestampTests.test_valid_matched_and_financial_mismatch_keep_distinct_exit_codes',
)
AUTH_CASES = (
    'test_stage12_1_epochs.OriginalAcceptanceEpochTests.test_five_actual_admission_steps_have_literal_original_epoch_sets',
    'test_stage12_1_epochs.OriginalAcceptanceEpochTests.test_wrong_0100_cli_show_export_retry_are_integrity_errors_without_effects',
    'test_stage12_1_epochs.OriginalAcceptanceEpochTests.test_correct_0100_context_keeps_raw_id_hash_bytes_read_export_and_retry',
)


def cases(profile):
    if profile == 'core':
        return CORE_CASES
    if profile == 'auth-only' and AUTH_CASES:
        return AUTH_CASES
    raise ValueError('EXECUTION_MAINTENANCE: unsupported or incomplete profile')


def identities(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from identities(test)
        else:
            yield test.id()


def validate_result(row, profile, origin):
    expected = list(cases(profile))
    valid = (row.get('format') == 'execution-maintenance-tests-v1'
             and row.get('profile') == profile and row.get('status') == 'PASS'
             and row.get('origin') == origin and row.get('isolated') is True
             and row.get('expected_ids') == expected
             and row.get('discovered_ids') == expected and row.get('executed_ids') == expected
             and row.get('executed') == len(expected)
             and all(type(row.get(name)) is int and row[name] == 0 for name in
                     ('skips', 'failures', 'errors', 'expected_failures', 'unexpected_successes')))
    if not valid:
        raise ValueError('EXECUTION_MAINTENANCE: incomplete or inconsistent fixed subset')
    return {'status': 'PASS', 'profile': profile, 'expected_ids': expected,
            'executed_ids': row['executed_ids'], 'origin': origin, 'isolated': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tests', type=Path, required=True)
    parser.add_argument('--profile', choices=('core', 'auth-only'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Resolve package before making only the pinned test-helper directory importable.
    import crypto_reconciliation_lab as package
    args.output.mkdir(parents=True, exist_ok=False)
    output = args.output.resolve()
    os.environ['CRYPTO_STAGE12_1_TEST_EVIDENCE'] = str(output / 'cases')
    tests = args.tests.resolve()
    sys.path.insert(0, str(tests))
    expected = list(cases(args.profile))
    suite = unittest.defaultTestLoader.loadTestsFromNames(expected)
    row = {'format': 'execution-maintenance-tests-v1', 'profile': args.profile,
           'status': 'RUNNING', 'expected_ids': expected, 'discovered_ids': list(identities(suite)),
           'executed_ids': [], 'origin': package.__file__, 'version': package.__version__,
           'isolated': bool(sys.flags.isolated), 'executable': sys.executable,
           'cwd': str(Path.cwd()), 'tests': str(tests), 'argv': [sys.executable, *sys.argv]}
    if row['discovered_ids'] != expected:
        row.update(status='ERROR', error='Fixed subset discovery differs')
        (output / 'summary.json').write_text(json.dumps(row, indent=2) + '\n')
        return 1
    class RecordedResult(unittest.TextTestResult):
        def startTest(self, test):
            row['executed_ids'].append(test.id())
            super().startTest(test)
    started = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(suite)
    row.update(executed=result.testsRun, skips=len(result.skipped), failures=len(result.failures),
               errors=len(result.errors), expected_failures=len(result.expectedFailures),
               unexpected_successes=len(result.unexpectedSuccesses), seconds=time.monotonic()-started,
               status='PASS' if result.wasSuccessful() else 'ERROR')
    row['evidence_files'] = {p.relative_to(output).as_posix(): {
        'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in sorted(output.rglob('*')) if p.is_file()}
    (output / 'summary.json').write_text(json.dumps(row, indent=2, sort_keys=True) + '\n')
    validate_result(row, args.profile, package.__file__)
    print(json.dumps({'status': 'PASS', 'profile': args.profile, 'executed': result.testsRun,
                      'report': str(output / 'summary.json')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
