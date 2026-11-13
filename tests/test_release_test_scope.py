"""S6-F1: an independent roster must survive file loss and misleading counts."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = 'contracts/release-tests-baseline-0.6.0.json'
CONTRACT_PATH = 'contracts/release-test-scope-0.6.1.json'
BASELINE = json.loads((ROOT / BASELINE_PATH).read_text())
SPEC = importlib.util.spec_from_file_location('scope_release_verifier', ROOT / 'scripts/verify_release.py')
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)
OMITTED = ('test_reproduce_review.py', 'test_release_packaging.py', 'test_release_verification.py')


def declared_ids():
    # Only this RED/GREEN test harness has an old-baseline fallback. Production
    # verification must require its pinned current contract without any fallback.
    current = ROOT / CONTRACT_PATH
    return json.loads(current.read_text())['current']['test_ids'] if current.exists() else BASELINE['test_ids']


def successful_result():
    identities = list(declared_ids())
    current = ROOT / CONTRACT_PATH
    identity = ({'path':CONTRACT_PATH, 'bytes':current.stat().st_size,
                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.6.1'}
                if current.exists() else {})
    return dict(status='PASS', discovered=len(identities), executed=len(identities),
                discovered_ids=identities, executed_ids=list(identities), scope_identity=identity,
                skips=0, failures=0, errors=0, unexpected_successes=0, expected_failures=0)


def bounded_source(destination, *, omit=()):
    """Own a bounded copy; never recurse through workspace outputs or environments."""
    destination.mkdir()
    for folder, suffixes in (('crypto_reconciliation_lab',{'.py','.html','.css','.js'}),
                              ('scripts',{'.py'}), ('contracts',{'.json'})):
        for source in (ROOT / folder).rglob('*'):
            if source.is_file() and source.suffix in suffixes and '__pycache__' not in source.parts:
                target = destination / source.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source,target)
    current = ROOT / CONTRACT_PATH
    files = json.loads(current.read_text())['current']['files'] if current.exists() else BASELINE['files']
    for name in files:
        if Path(name).name in omit:
            continue
        target = destination / name; target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/name,target)
    for name in ('pyproject.toml','fixtures/stage1_history.json','fixtures/stage3_3_schema2_history.json',
                 'docs/stage2/baseline-schema.json','docs/stage5/experiment_contract.md',
                 'docs/stage5/ai_constraints.txt','docs/stage6/financial-reference.json'):
        target=destination/name; target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(ROOT/name,target)
    return destination


class ReleaseTestScopeTests(unittest.TestCase):
    def test_actual_runner_rejects_all_three_omitted_stage6_modules(self):
        with tempfile.TemporaryDirectory(prefix='scope-real-runner-') as temporary:
            root = Path(temporary)
            source = bounded_source(root/'source', omit=OMITTED)
            report = root/'runner.json'
            argv = [sys.executable,'-B','-c',verify.TEST_RUNNER,str(source/'tests'),str(report)]
            environment=dict(os.environ); environment.pop('PYTHONPATH',None); environment.pop('PYTHONHOME',None)
            started=time.perf_counter()
            result=subprocess.run(argv,cwd=source,env=environment,text=True,capture_output=True)
            row=json.loads(report.read_text())
            record={'argv':argv,'cwd':str(source),'exit_code':result.returncode,
                    'seconds':time.perf_counter()-started,'result':row,
                    'omitted_modules':list(OMITTED),'expected_original_count':355,
                    'runner_sha256':hashlib.sha256(verify.TEST_RUNNER.encode()).hexdigest()}
            audit=os.environ.get('CRYPTO_RELEASE_SCOPE_AUDIT')
            if audit:
                folder=Path(audit);folder.mkdir(parents=True,exist_ok=True)
                (folder/'omitted-modules-command.json').write_text(json.dumps(record,indent=2)+'\n')
                (folder/'omitted-modules.stdout.txt').write_text(result.stdout)
                (folder/'omitted-modules.stderr.txt').write_text(result.stderr)
            self.assertNotEqual(result.returncode,0,record)
            self.assertEqual(row['status'],'ERROR')
            self.assertIn('TEST_SCOPE:',row.get('scope_error',''))
            self.assertEqual(row['executed'],0,'the invalid roster must stop before any test executes')

    def test_missing_one_old_identity_is_rejected_even_above_old_threshold(self):
        row=successful_result()
        removed=BASELINE['test_ids'][0]
        row['discovered_ids'].remove(removed);row['executed_ids'].remove(removed)
        row['discovered']-=1;row['executed']-=1
        with self.assertRaises(ValueError):verify.validate_tests(row)

    def test_same_count_substituted_identity_is_rejected(self):
        row=successful_result()
        row['discovered_ids'][-1]=row['executed_ids'][-1]='test_unreviewed.Unreviewed.test_replacement'
        with self.assertRaises(ValueError):verify.validate_tests(row)

    def test_same_count_duplicate_identity_is_rejected(self):
        row=successful_result()
        row['discovered_ids'][-1]=row['executed_ids'][-1]=row['discovered_ids'][0]
        with self.assertRaises(ValueError):verify.validate_tests(row)

    def test_discovered_and_actually_executed_identities_must_agree(self):
        row=successful_result()
        row['executed_ids'][-1]='test_unreviewed.Unreviewed.test_replacement'
        with self.assertRaises(ValueError):verify.validate_tests(row)

    def test_counts_without_actual_identity_evidence_are_not_a_full_suite(self):
        row=successful_result();row.pop('discovered_ids');row.pop('executed_ids')
        with self.assertRaises(ValueError):verify.validate_tests(row)

    def test_import_error_holder_cannot_be_an_expected_test_identity(self):
        row=successful_result()
        row['discovered_ids'][-1]=row['executed_ids'][-1]='unittest.loader._FailedTest.missing_module'
        with self.assertRaises(ValueError):verify.validate_tests(row)

    def test_complete_declared_unique_identity_evidence_is_accepted(self):
        verify.validate_tests(successful_result())

    def test_official_full_supplied_source_stops_before_environment_creation(self):
        with tempfile.TemporaryDirectory(prefix='scope-official-preflight-') as temporary:
            root=Path(temporary);source=bounded_source(root/'source',omit=OMITTED)
            wheel=root/'placeholder.whl'
            with zipfile.ZipFile(wheel,'w') as archive:
                archive.writestr('crypto_reconciliation_lab/__init__.py',b'# never installed\n')
            with patch.object(verify.Verification,'run',side_effect=AssertionError('EXPENSIVE_SETUP_REACHED')) as expensive:
                result=verify.main(['--profile','full','--source',str(source),'--wheel',str(wheel),'--output',str(root/'gate')])
            record=json.loads((root/'gate/verification.json').read_text())
            self.assertNotEqual(result,0)
            self.assertEqual(record['status'],'ERROR')
            self.assertEqual(expensive.call_count,0,'invalid source scope must fail before install/test/reproduction')
            self.assertIn('TEST_SCOPE:',record['error'])
            self.assertFalse((root/'gate/environment').exists())
            self.assertFalse((root/'gate/source-reproduction').exists())
            self.assertFalse((root/'gate/installed-reproduction').exists())
