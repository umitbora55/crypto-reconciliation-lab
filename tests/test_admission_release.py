"""Negative coverage checks for the release gate, not fabricated crash evidence."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('admission_release_scope', ROOT / 'scripts/release_admission_scope.py')
scope_gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scope_gate)


def report_fixture(scope):
    """Synthetic complete verifier input; never evidence of an executed process."""
    import json
    value = json.loads((ROOT / 'tests/fixtures/admission-semantic-report-v2.json').read_text())
    if not value['fixture_notice'].startswith('SYNTHETIC VERIFIER INPUT.'):
        raise ValueError('fixture provenance missing')
    return value


class AdmissionReleaseTests(unittest.TestCase):
    def setUp(self):
        self.scope = scope_gate.load_scope(ROOT)
        self.report = report_fixture(self.scope)

    def validate(self, report):
        return scope_gate.validate_report(report, self.scope, schedule_sha256='a' * 64)

    def test_complete_declared_verifier_input_is_accepted(self):
        self.assertEqual(self.validate(self.report)['executed_count'], 21)

    def test_empty_partial_duplicate_or_substituted_scenario_ids_are_rejected(self):
        for field in ('planned_scenario_ids', 'executed_scenario_ids'):
            for value in ([], self.scope['scenario_ids'][:-1],
                          self.scope['scenario_ids'][:-1] + [self.scope['scenario_ids'][0]],
                          self.scope['scenario_ids'][:-1] + ['unreviewed_substitute']):
                with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, 'ADMISSION_SCOPE'):
                    self.validate(self.report | {field: value})

    def test_claimed_pass_without_observed_sigkill_or_barrier_is_rejected(self):
        for field, value in (('barrier_reached', False), ('exit_code', 0), ('sender_result', 'ACK')):
            report = deepcopy(self.report)
            row = next(r for r in report['scenarios'] if r['id'] == 'lost_ack')
            row['processes'][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'observed SIGKILL'):
                self.validate(report)

    def test_writer_claim_requires_two_distinct_joined_successful_processes(self):
        for fields in ({'pid': 101}, {'joined': False}, {'exit_code': 1}):
            report = deepcopy(self.report)
            row = next(r for r in report['scenarios'] if r['id'] == 'writers_same_stream')
            row['processes'][1].update(fields)
            with self.subTest(fields=fields), self.assertRaisesRegex(ValueError, 'independent writer'):
                self.validate(report)

    def test_failed_or_missing_readback_checks_and_changed_schedule_are_rejected(self):
        for changes in ({'checks': []}, {'checks': [{'passed': False}]}, {'status': 'INCOMPLETE'}):
            report = deepcopy(self.report); report['scenarios'][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.validate(report)
        with self.assertRaisesRegex(ValueError, 'schedule'):
            self.validate(self.report | {'schedule_sha256': 'b' * 64})

    def test_broken_models_must_actually_fail_the_negative_control(self):
        report = deepcopy(self.report)
        report['negative_control']['models'][0]['observed_status'] = 'PASS'
        with self.assertRaisesRegex(ValueError, 'broken transport models'):
            self.validate(report)

    def test_candidate_cannot_replace_fixed_required_scope_with_partial_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); target = root / scope_gate.CONTRACT_PATH
            target.parent.mkdir(); shutil.copyfile(ROOT / scope_gate.CONTRACT_PATH, target)
            target.write_text('{"scenario_ids": []}\n')
            with self.assertRaisesRegex(ValueError, 'identity differs'):
                scope_gate.load_scope(root)
