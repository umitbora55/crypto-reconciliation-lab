"""Reject misleading orchestration success and unsafe evidence destinations."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('validation_runner', ROOT/'scripts/validation/run_validation.py')
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class RunnerTests(unittest.TestCase):
    def test_offline_cannot_enable_fetch_or_package_network(self):
        for option in ('--fetch-public', '--with-release'):
            with tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp)/'absent'
                result = subprocess.run([sys.executable, str(SPEC.origin), '--output', str(output), '--no-network', option], capture_output=True)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(output.exists())

    def test_existing_evidence_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp)/'original'
            marker.write_text('unchanged')
            result = subprocess.run([sys.executable, str(SPEC.origin), '--output', tmp], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(marker.read_text(), 'unchanged')

    def test_zero_exit_cannot_override_partial_benchmark(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            (output/'benchmark').mkdir()
            (output/'benchmark/summary.json').write_text(json.dumps({'status': 'PARTIAL'}))
            result = RUNNER.run_stage(output, 'benchmark', [sys.executable, '-c', 'pass'], 5, {})
            self.assertEqual(result['exit_code'], 0)
            self.assertEqual(result['status'], 'PARTIAL')

    def test_empty_test_command_is_not_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = RUNNER.run_stage(Path(tmp), 'research-tests', [sys.executable, '-c', 'pass'], 5, {})
            self.assertEqual(result['status'], 'FAILED_EMPTY_TEST_RUN')

    def test_partial_benchmark_with_distinct_exit_is_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            (output/'benchmark').mkdir()
            (output/'benchmark/summary.json').write_text(json.dumps({'status': 'PARTIAL'}))
            result = RUNNER.run_stage(output, 'benchmark', [sys.executable, '-c', 'raise SystemExit(3)'], 5, {})
            self.assertEqual(result['exit_code'], 3)
            self.assertEqual(result['status'], 'PARTIAL')

    def test_forged_complete_benchmark_with_empty_case_inventory_is_rejected(self):
        result = {'status':'COMPLETE', 'cases':[], 'executed_trials':0, 'passed_trials':0}
        self.assertFalse(RUNNER.accepted_summary(Path('/tmp'), 'benchmark', result, ['--profiles','100']))

    def test_timeout_preserves_failure_and_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = RUNNER.run_stage(Path(tmp), 'timeout-witness', [sys.executable, '-c', 'import time; time.sleep(10)'], 0.05, {})
            self.assertEqual(result['status'], 'TIMEOUT')
            self.assertEqual(result['exit_code'], -9)
            self.assertTrue((Path(tmp)/'commands/timeout-witness/command.json').is_file())
