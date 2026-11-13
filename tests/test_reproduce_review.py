"""Narrow failure-propagation checks for the portable release orchestration."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/reproduce_review.py'
SPEC = importlib.util.spec_from_file_location('reproduce_review_script', SCRIPT)
reproduction = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reproduction)


class ReproductionFailureTests(unittest.TestCase):
    def test_nonzero_child_exit_is_recorded_and_propagated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            recorder = reproduction.Recorder(root, sys.executable, 'installed', root)
            completed = subprocess.CompletedProcess([], 7, stdout='partial result', stderr='actual child failure')
            with patch.object(reproduction.subprocess, 'run', return_value=completed):
                with self.assertRaisesRegex(reproduction.ReproductionError, 'expected exit 0, got 7'):
                    recorder.command('failed-child', ['review-demo'])
            self.assertEqual(recorder.records[0]['exit_code'], 7)
            self.assertEqual(recorder.records[0]['status'], 'FAILED')
            self.assertEqual((root/'logs/failed-child.stderr.txt').read_text(), 'actual child failure')

    def test_zero_exit_without_required_child_audit_is_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            recorder = reproduction.Recorder(root, sys.executable, 'installed', root)
            completed = subprocess.CompletedProcess([], 0, stdout='{"status":"COMPLETE"}', stderr='')
            with patch.object(reproduction.subprocess, 'run', return_value=completed):
                with self.assertRaisesRegex(reproduction.ReproductionError, 'missing child import audit'):
                    recorder.command('incomplete-child', ['review-demo'])
            self.assertEqual(recorder.records[0]['exit_code'], 0)
            self.assertEqual(recorder.records[0]['status'], 'FAILED')

    def test_installed_origin_rejects_checkout_and_accepts_local_venv_site_packages(self):
        import tomllib
        with (SCRIPT.parents[1]/'pyproject.toml').open('rb') as stream:
            version = tomllib.load(stream)['project']['version']
        site = SCRIPT.parents[1]/'.venv/lib/python/site-packages'
        for accepted, origin in ((False, SCRIPT.parents[1]/'crypto_reconciliation_lab/__init__.py'),
                                 (True, site/'crypto_reconciliation_lab/__init__.py')):
            with self.subTest(accepted=accepted), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                recorder = reproduction.Recorder(root, sys.executable, 'installed', root)
                def child(argv, **kwargs):
                    Path(argv[5]).write_text(json.dumps({'package_origin':str(origin),
                        'package_version':version, 'site_packages':[str(site)], 'imported_optional':[]}))
                    return subprocess.CompletedProcess(argv, 0, stdout='', stderr='')
                with patch.object(reproduction.subprocess, 'run', side_effect=child):
                    if accepted:
                        self.assertEqual(recorder.command('origin-check', ['--help']).returncode, 0)
                        self.assertEqual(recorder.records[0]['status'], 'PASSED')
                    else:
                        with self.assertRaisesRegex(reproduction.ReproductionError, 'site-packages wheel'):
                            recorder.command('origin-check', ['--help'])
                        self.assertEqual(recorder.records[0]['status'], 'FAILED')

    def test_missing_or_duplicate_demo_coverage_never_counts_as_success(self):
        counts = [('clean',1), ('late_event',2), ('custody_difference',1), ('corrected_report',2),
                  ('deposit_amount_correction',4), ('void_deposit',4), ('void_internal_transfer',3),
                  ('correction_before_target',3), ('duplicate_and_conflicting_corrections',4)]
        rows = [{'scenario':name, 'phase':str(i), 'verified':True} for name,count in counts for i in range(count)]
        self.assertEqual(len(rows),24)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'showcase.json'
            for invalid in (rows[:-1], [*deepcopy(rows[:-1]),deepcopy(rows[0])]):
                path.write_text(json.dumps({'status':'COMPLETE','runs':invalid}))
                with self.subTest(count=len(invalid)), self.assertRaises(reproduction.ReproductionError):
                    reproduction.validate_showcase(path)

    def test_negative_exit_cannot_hide_a_published_queue(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'rank-invalid'; output.mkdir()
            (output/'queue.json').write_text('{}')
            with self.assertRaisesRegex(reproduction.ReproductionError, 'published'):
                reproduction.validate_negative(output, '', 'TRIAGE_PROVENANCE: future source')

    def test_existing_output_and_source_paths_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            existing = root/'existing'; existing.mkdir(); (existing/'sentinel').write_text('preserve')
            with self.assertRaisesRegex(reproduction.ReproductionError, 'OUTPUT_EXISTS'):
                reproduction.new_output(existing, root, root/'examples')
            self.assertEqual((existing/'sentinel').read_text(), 'preserve')
            with self.assertRaisesRegex(reproduction.ReproductionError, 'OUTPUT_SOURCE_CONFLICT'):
                reproduction.new_output(root/'docs/new-output', root, root/'examples')
            self.assertFalse((root/'docs').exists())
