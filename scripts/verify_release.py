#!/usr/bin/env python3
"""Portable release verification: sdist source, installed wheel, and core-only paths."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import PurePosixPath
import re
import stat
from pathlib import Path
import subprocess
import sys
import time
import tomllib
import traceback
import zipfile

OPTIONAL = ('sklearn', 'numpy', 'scipy')


def release_helper(name):
    # File-based loading remains valid under -I and importlib-based old tests.
    path = Path(__file__).resolve().with_name(name + '.py')
    spec = importlib.util.spec_from_file_location('release_gate_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TEST_SCOPE = release_helper('release_test_scope')
FINANCIAL_SCOPE = release_helper('release_financial_scope')
ADMISSION_SCOPE = release_helper('release_admission_scope')


def digest(path):
    data = Path(path).read_bytes()
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def clean_environment():
    environment = dict(os.environ)
    for name in ('PYTHONPATH', 'PYTHONHOME'):
        environment.pop(name, None)
    environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1')
    return environment


PROBE = r'''
import hashlib, importlib.metadata as metadata, importlib.util, json, pathlib, platform, sqlite3, sys
import crypto_reconciliation_lab as package
from crypto_reconciliation_lab.engine import RULE_VERSION
from crypto_reconciliation_lab.migrations import SCHEMA_VERSION
from crypto_reconciliation_lab.review import BUNDLE_FORMAT
from crypto_reconciliation_lab.triage import EXPERIMENT_FORMAT, FEATURE_FORMAT
from crypto_reconciliation_lab.triage.contracts import CONTRACT_SHA256
root = pathlib.Path(package.__file__).resolve().parent
files = {p.relative_to(root).as_posix(): {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
         for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
print(json.dumps(dict(python=sys.version, executable=sys.executable, isolated=bool(sys.flags.isolated),
    cwd=str(pathlib.Path.cwd()), sys_path=sys.path, platform=platform.platform(), sqlite=sqlite3.sqlite_version,
    origin=package.__file__, package_version=package.__version__, distribution_version=metadata.version('crypto-reconciliation-lab'),
    rule=RULE_VERSION, schema=SCHEMA_VERSION, review_format=BUNDLE_FORMAT, experiment_format=EXPERIMENT_FORMAT,
    feature_format=FEATURE_FORMAT, contract_sha256=CONTRACT_SHA256, package_files=files,
    auth_imported=[name for name in ('cryptography','cffi','_cffi_backend') if name in sys.modules],
    auth_available={name:importlib.util.find_spec(name) is not None for name in ('cryptography','cffi','pycparser')},
    optional_imported=[name for name in ('sklearn','numpy','scipy') if name in sys.modules],
    optional_available={name:importlib.util.find_spec(name) is not None for name in ('sklearn','numpy','scipy')},
    dependencies={d.metadata['Name']: {'version':d.version,'requires_python':d.metadata.get('Requires-Python')}
                  for d in metadata.distributions()}), sort_keys=True))
'''

TEST_RUNNER = r'''
import importlib.util, json, os, pathlib, sys, unittest
import crypto_reconciliation_lab as package
report = pathlib.Path(sys.argv[2])
if len(sys.argv) > 3:
    os.environ['CRYPTO_EXECUTION_TEST_EVIDENCE'] = sys.argv[3]
if len(sys.argv) > 4:
    os.environ['CRYPTO_STAGE12_1_TEST_EVIDENCE'] = sys.argv[4]
if len(sys.argv) > 5:
    os.environ['CRYPTO_EXECUTION_REPLAY_TEST_EVIDENCE'] = sys.argv[5]
source = pathlib.Path(sys.argv[1]).resolve().parent
row = dict(discovered=0, executed=0, discovered_ids=[], executed_ids=[], skips=0, failures=0,
    errors=0, unexpected_successes=0, expected_failures=0, status='ERROR',
    origin=package.__file__, version=package.__version__, isolated=bool(sys.flags.isolated), cwd=str(pathlib.Path.cwd()))
try:
    spec = importlib.util.spec_from_file_location('runner_release_test_scope', source / 'scripts/release_test_scope.py')
    scope_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scope_module)
    scope = scope_module.load_test_scope(source)
    row['file_scope'] = scope_module.validate_test_files(source, scope)
    row['scope_identity'] = scope_module.identity()
    row['expected_ids'] = list(scope['current']['test_ids'])
    suite = unittest.defaultTestLoader.discover(sys.argv[1], pattern='test*.py')
    def identities(tests):
        for test in tests:
            if isinstance(test, unittest.TestSuite):
                yield from identities(test)
            else:
                yield test.id()
    # unittest removes suite members during execution: freeze discovery now.
    row['discovered_ids'] = list(identities(suite))
    row['discovered'] = len(row['discovered_ids'])
    scope_module.validate_discovered_ids(row['discovered_ids'], scope)
    class RecordedResult(unittest.TextTestResult):
        def startTest(self, test):
            row['executed_ids'].append(test.id())
            super().startTest(test)
    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(suite)
    row.update(executed=result.testsRun, skips=len(result.skipped), failures=len(result.failures),
        errors=len(result.errors), unexpected_successes=len(result.unexpectedSuccesses),
        expected_failures=len(result.expectedFailures), status='PASS' if result.wasSuccessful() else 'ERROR')
    row['identity_validation'] = scope_module.validate_test_result(row, scope)
except Exception as error:
    row.update(status='ERROR', scope_error='TEST_SCOPE: ' + str(error).removeprefix('TEST_SCOPE: '))
report.write_text(json.dumps(row,indent=2,sort_keys=True)+'\n',encoding='utf-8')
raise SystemExit(0 if row['status']=='PASS' else 1)
'''


class Verification:
    def __init__(self, output, profile):
        self.output = Path(output).absolute()
        # Refuse collisions before creating or changing any files.
        self.output.mkdir(parents=True, exist_ok=False)
        (self.output / 'logs').mkdir()
        self.external = self.output / 'external-cwd'
        self.external.mkdir()
        self.record = {'format': 'release-verification-v1', 'status': 'RUNNING', 'profile': profile,
                       'commands': [], 'main_generation_training_final_evaluation': False,
                       'environment_policy': 'PYTHONPATH and PYTHONHOME removed; isolated installed commands; no editable install',
                       'invocation': [sys.executable, *sys.argv], 'invocation_cwd': str(Path.cwd())}
        self.persist()

    def persist(self):
        save(self.output / 'verification.json', self.record)

    def run(self, name, argv, cwd=None, expected=0):
        command = list(map(str, argv))
        stdout = self.output / 'logs' / (name + '.stdout.txt')
        stderr = self.output / 'logs' / (name + '.stderr.txt')
        row = {'name': name, 'argv': command, 'cwd': str(cwd or self.external), 'expected_exit': expected,
               'stdout': str(stdout.relative_to(self.output)), 'stderr': str(stderr.relative_to(self.output)), 'status': 'RUNNING'}
        self.record['commands'].append(row)
        self.persist()
        started = time.monotonic()
        with stdout.open('w', encoding='utf-8') as out, stderr.open('w', encoding='utf-8') as err:
            completed = subprocess.run(command, cwd=cwd or self.external, env=clean_environment(), stdout=out, stderr=err)
        row.update(exit_code=completed.returncode, seconds=time.monotonic()-started,
                   status='PASS' if completed.returncode == expected else 'ERROR',
                   stdout_hash=digest(stdout), stderr_hash=digest(stderr))
        self.persist()
        require(completed.returncode == expected, f'{name}: expected exit {expected}, received {completed.returncode}; see {stderr}')
        print(f'{name}: PASS (exit {completed.returncode})', flush=True)
        return stdout.read_text(encoding='utf-8')

    def probe(self, name, python, source, installed, expected_version):
        flags = ['-I'] if installed else []
        result = json.loads(self.run(name, [python, '-B', *flags, '-c', PROBE], None if installed else source))
        require(result['package_version'] == result['distribution_version'] == expected_version, 'package/distribution version mismatch')
        package_metadata = result['dependencies'].get('crypto-reconciliation-lab', {})
        require(package_metadata.get('requires_python') == '>=3.12', 'installed Requires-Python metadata mismatch')
        origin = Path(result['origin']).resolve()
        if installed:
            require(result['isolated'] and ('site-packages' in origin.parts or 'dist-packages' in origin.parts), 'installed import must come from site-packages with -I')
            require(not origin.is_relative_to(source), 'installed import leaked from source')
        else:
            require(origin == source / 'crypto_reconciliation_lab/__init__.py', 'source import origin mismatch')
        expected = {p.relative_to(source / 'crypto_reconciliation_lab').as_posix(): digest(p)
                    for p in (source / 'crypto_reconciliation_lab').rglob('*')
                    if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
        require(result['package_files'] == expected, 'installed/source package module or asset bytes differ')
        require(result['rule'] == 'stage2-v2' and result['schema'] == 6, 'financial rule/schema changed')
        require(result['review_format'] == 'review-bundle-v1' and result['experiment_format'] == 'triage-experiment-v1'
                and result['feature_format'] == 'triage-features-v1', 'saved review/triage v1 format changed')
        require(result['contract_sha256'] == 'd532627546c49a582397fcb700ad723269fafe45ac25af7f162eded5f85d7428',
                'frozen Stage 5 experiment contract changed')
        require(not result['optional_imported'], 'package import eagerly loaded optional AI dependencies')
        require(not result['auth_imported'], 'package import eagerly loaded optional auth dependencies')
        self.record[name] = result
        self.persist()
        return result

    def tests(self, name, python, source, installed):
        flags = ['-I'] if installed else []
        target = self.output / (name + '.json')
        evidence = self.output / ('process-evidence-installed' if installed else 'process-evidence-source')
        maintenance = self.output / (('installed' if installed else 'source') + '-execution-maintenance')
        replay = self.output / ('process-evidence-replay-installed' if installed else 'process-evidence-replay-source')
        self.run(name, [python, '-B', *flags, '-c', TEST_RUNNER, source / 'tests', target, evidence, maintenance, replay], None if installed else source)
        result = json.loads(target.read_text(encoding='utf-8'))
        validate_tests(result, TEST_SCOPE.load_test_scope(source))
        self.record[name] = result
        covered = sorted(item for item in result['executed_ids'] if item.startswith('test_stage12_1_'))
        require(covered, 'execution maintenance regression identities are missing')
        self.record[('installed' if installed else 'source') + '_execution_maintenance'] = {
            'status': 'PASS', 'coverage': 'WITHIN_FULL_SUITE', 'executed_ids': covered,
            'evidence': {p.relative_to(maintenance).as_posix(): digest(p)
                         for p in sorted(maintenance.rglob('*')) if p.is_file()}}
        self.record[name + '_execution_processes'] = validate_execution_process_evidence(
            evidence, package_origin=result['origin'], isolated=installed)
        self.record[name + '_execution_replay_timeout'] = release_helper('release_execution_replay').validate_timeout(
            replay, executable=python, isolated=installed)
        self.persist()
        return result


def validate_tests(result, scope=None):
    # Preserve the original failed/skip/count boundary before new ID requirements.
    require(all(type(result.get(field, 0)) is int and result.get(field, 0) == 0
                for field in ('skips', 'failures', 'errors', 'unexpected_successes', 'expected_failures')),
            'TEST_SCOPE: tests skipped or unsuccessful')
    require(result.get('status') == 'PASS' and type(result.get('discovered')) is int
            and type(result.get('executed')) is int and result['discovered'] > 0
            and result['executed'] == result['discovered'], 'TEST_SCOPE: incomplete test discovery/execution')
    if scope is None:
        scope = TEST_SCOPE.load_test_scope(Path(__file__).resolve().parents[1])
    return TEST_SCOPE.validate_test_result(result, scope)


def preflight(source):
    # Both profiles bind the same immutable scopes before external operations.
    scope = TEST_SCOPE.validate_test_files(source)
    ADMISSION_SCOPE.load_scope(source)
    reference = FINANCIAL_SCOPE.load_financial_reference(source / 'docs/stage6/financial-reference.json')
    return scope, reference


def compare_reports(directory, reference):
    directory = Path(directory)
    require(type(reference) is dict and type(reference.get('files')) is dict and reference['files'],
            'FINANCIAL_REFERENCE: comparison requires a nonempty file inventory')
    checked = {}
    for name, expected in reference['files'].items():
        actual = digest(directory / name)
        require(actual == expected, f'financial report changed: {directory / name}')
        checked[name] = actual
    return {'status': 'PASS', 'count': len(checked), 'files': checked, 'full_bytes_and_run_ids_equal': True}


def validate_core_probe(probe):
    require(not probe['optional_imported'] and not any(probe['optional_available'].values()), 'core environment contains or imported optional AI dependency')
    installed = {name.lower().replace('_', '-') for name in probe['dependencies']}
    require(not installed.intersection({'scikit-learn', 'numpy', 'scipy'}), 'core installation contains an optional dependency distribution')


def validate_auth_absent(probe):
    require(not probe.get('auth_imported') and probe.get('auth_available') ==
            {'cryptography': False, 'cffi': False, 'pycparser': False},
            'core environment contains or imported optional auth dependency')
    installed = {name.lower().replace('_', '-') for name in probe['dependencies']}
    require(not installed.intersection({'cryptography', 'cffi', 'pycparser'}),
            'core installation contains an auth dependency distribution')


def validate_auth_pins(probe, source):
    require(probe.get('auth_available') == {'cryptography': True, 'cffi': True, 'pycparser': True},
            'auth installation missing its optional dependencies')
    for line in (Path(source) / 'requirements-auth.txt').read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            name, expected = line.split('==', 1)
            require(probe['dependencies'].get(name, {}).get('version') == expected,
                    'auth pin mismatch: ' + name)


def core_auth_denied(gate, python):
    """The actual isolated command must fail before creating any demo effects."""
    target = gate.output / 'core-auth-must-not-exist'
    gate.run('core-auth-unavailable', [python, '-B', '-I', '-m', 'crypto_reconciliation_lab',
             'demo-source-auth', '--output', target, '--seed', '19'], expected=2)
    error = (gate.output / 'logs/core-auth-unavailable.stderr.txt').read_text(encoding='utf-8')
    require('AUTH_DEPENDENCY' in error and not target.exists(),
            'core auth command did not fail explicitly before creating output')
    gate.record['core_auth_refusal'] = {'status': 'PASS', 'exit_code': 2,
                                      'output_absent': True, 'reason': 'AUTH_DEPENDENCY'}
    gate.persist()


def core_provenance_denied(gate, python):
    """Every new command reports the missing auth extra before output effects."""
    target = gate.output / 'core-provenance-must-not-exist'
    commands = {
        'demo': ['demo-provenance', '--output', target],
        'export': ['export-provenance', '--db', gate.external / 'absent.sqlite',
                   '--run-id', '0' * 64, '--materials', gate.external / 'absent-materials', '--output', target],
        'verify': ['verify-provenance', '--bundle', gate.external / 'absent-bundle',
                   '--expectations', gate.external / 'absent-expectations.json'],
    }
    observed = {}
    for operation, arguments in commands.items():
        name = 'core-provenance-' + operation + '-unavailable'
        stdout = gate.run(name, [python, '-B', '-I', '-m', 'crypto_reconciliation_lab', *arguments], expected=2)
        stderr = (gate.output / 'logs' / (name + '.stderr.txt')).read_text(encoding='utf-8')
        require('AUTH_DEPENDENCY' in stdout + stderr and not target.exists(),
                'core provenance command did not fail explicitly before creating output')
        if operation == 'verify':
            result = json.loads(stdout)
            require(result['status'] == 'FAILED' and result['exit_code'] == 2
                    and [reason['code'] for reason in result['reasons']] == ['AUTH_DEPENDENCY'],
                    'core provenance verifier did not report the missing dependency')
        observed[operation] = {'status': 'PASS', 'exit_code': 2, 'reason': 'AUTH_DEPENDENCY', 'output_absent': True}
    gate.record['core_provenance_refusal'] = {'status': 'PASS', 'operations': observed}
    gate.persist()


def source_auth(gate, python, source, mode):
    """Run the new independent auth gate, keeping historical recovery v2 intact."""
    target = gate.output / (mode + '-source-auth')
    flags = ['-I'] if mode == 'installed' else []
    cwd = None if mode == 'installed' else source
    gate.run(mode + '-source-auth', [python, '-B', *flags, '-m', 'crypto_reconciliation_lab',
             'demo-source-auth', '--output', target, '--seed', '19'], cwd)
    report = json.loads((target / 'report.json').read_text(encoding='utf-8'))
    verified = json.loads(gate.run(mode + '-verify-source-auth',
                         [python, '-B', *flags, '-m', 'crypto_reconciliation_lab',
                          'verify-source-auth', '--bundle', target, '--anchor', 'demo-test-only'], cwd))
    require(verified['status'] == 'PASSED', 'independent source-auth verification failed')
    origin = Path(report['environment']['import_origin']).resolve()
    expected_origin = Path(gate.record[mode + '_import']['origin']).resolve()
    require(origin == expected_origin, 'source-auth imported a different source/package')
    gate.record[mode + '_source_auth'] = {'status': 'PASS', 'path': str(target),
        'report_identity': digest(target / 'report.json'), 'report': report,
        'verification': verified, 'operator_anchor': 'demo-test-only; independently pinned public fixture'}
    gate.persist()


PROVENANCE_GROUPS = {
    'clean_two_publishers': ['clean'],
    'signed_custody_difference': ['signed_mismatch'],
    'historical_correction_quarantine': ['history_original', 'history_corrected', 'history_quarantine'],
    'rotation_and_revocation': ['rotation'],
    'exact_replay': ['replay'],
    'multiple_physical_candidates': ['ambiguous'],
    'missing_full_snapshot': ['missing_snapshot', 'prefix_only'],
    'legacy_and_protected': ['legacy', 'broken_protected_link', 'protected_downgrade'],
    'external_expectations': ['wrong_run', 'wrong_capture', 'wrong_policy', 'hidden_policy_head'],
    'semantic_relations': ['removed_receipt', 'changed_receipt', 'removed_quarantine', 'removed_correction',
                           'changed_effect', 'changed_endorsement', 'broken_link_and_missing_snapshot'],
}
# Release-owned literals. Neither the demo's expected labels nor an exporter
# inventory defines what this independent gate is required to observe.
PROVENANCE_RESULTS = {
    **{name: (0, 'VERIFIED_FOR_CAPTURE', []) for name in
       ('clean', 'signed_mismatch', 'history_original', 'history_corrected', 'history_quarantine', 'rotation', 'replay')},
    'ambiguous': (3, 'PARTIAL', ['MULTIPLE_RECEIPT_CANDIDATES']),
    'missing_snapshot': (3, 'PARTIAL', ['MISSING_SIGNED_SNAPSHOT']),
    'prefix_only': (3, 'PARTIAL', ['MISSING_SIGNED_SNAPSHOT']),
    'legacy': (3, 'PARTIAL', ['UNSIGNED_LEGACY']),
    **{name: (2, 'FAILED', [code]) for name, code in {
        'broken_protected_link': 'PROTECTED_LINK', 'protected_downgrade': 'PROFILE_MISMATCH',
        'wrong_run': 'RUN_IDENTITY', 'wrong_capture': 'CAPTURE_BINDING', 'wrong_policy': 'POLICY_BINDING',
        'hidden_policy_head': 'POLICY_BINDING', 'removed_receipt': 'EVIDENCE_SCOPE',
        'changed_receipt': 'RECEIPT_BINDING', 'removed_quarantine': 'EVIDENCE_SCOPE',
        'removed_correction': 'EVIDENCE_SCOPE', 'changed_effect': 'DELIVERY_RELATION',
        'changed_endorsement': 'ENDORSEMENT_BINDING', 'broken_link_and_missing_snapshot': 'PROTECTED_LINK',
    }.items()},
}


def validate_provenance_demo(report):
    require(type(report) is dict and report.get('format') == 'provenance-demo-v1'
            and report.get('status') == 'PASS', 'provenance demo did not complete')
    require(report.get('run_creation_authorization_cut') == 'NOT_RECORDED'
            and report.get('financial_recomputation') == 'NOT_PERFORMED', 'provenance limits disappeared')
    groups, rows = report.get('scenario_groups'), report.get('cases')
    require(type(groups) is list and len(groups) == len(PROVENANCE_GROUPS)
            and all(type(row) is dict and type(row.get('id')) is str for row in groups),
            'provenance scenario group inventory differs')
    actual_groups = {row['id']: row.get('case_ids') for row in groups}
    require(len(actual_groups) == len(groups) and actual_groups == PROVENANCE_GROUPS
            and all(row.get('passed') is True for row in groups), 'provenance scenario group coverage differs')
    require(type(rows) is list and len(rows) == len(PROVENANCE_RESULTS)
            and all(type(row) is dict and type(row.get('id')) is str for row in rows),
            'provenance case inventory differs')
    cases = {row['id']: row for row in rows}
    require(len(cases) == len(rows) and set(cases) == set(PROVENANCE_RESULTS), 'provenance case identities differ')
    for group_id, case_ids in PROVENANCE_GROUPS.items():
        for name in case_ids:
            row = cases[name]
            actual = row.get('actual', {})
            wanted_exit, wanted_status, wanted_reasons = PROVENANCE_RESULTS[name]
            require(row.get('group_id') == group_id and row.get('passed') is True
                    and type(actual.get('exit_code')) is int
                    and (actual['exit_code'], actual.get('status'), actual.get('reasons'))
                    == (wanted_exit, wanted_status, wanted_reasons),
                    'provenance semantic result differs: ' + name)
    for name in ('clean', 'signed_mismatch'):
        findings = cases[name].get('financial', {}).get('findings')
        require(type(findings) is list and len(findings) == 6, 'provenance financial finding coverage differs')
        actual = {(row['asset'], row['comparison'], row['scope']):
                  (row['expected'], row['reported'], row['difference'], row['data_state'], row['reconciliation_state'])
                  for row in findings}
        wanted = {('TOKEN_X', 'A', 'Aster'): ('7', '7', '0', 'COMPLETE', 'MATCHED'),
                  ('TOKEN_X', 'A', 'Birch'): ('4', '4', '0', 'COMPLETE', 'MATCHED'),
                  ('TOKEN_X', 'B', 'customer_liability'): ('11', '11', '0', 'COMPLETE', 'MATCHED'),
                  ('TOKEN_Y', 'A', 'Aster'): ('0.3', '0.3', '0', 'COMPLETE', 'MATCHED'),
                  ('TOKEN_Y', 'A', 'Birch'): ('0.2', '0.2', '0', 'COMPLETE', 'MATCHED'),
                  ('TOKEN_Y', 'B', 'customer_liability'): ('0.5', '0.5', '0', 'COMPLETE', 'MATCHED')}
        if name == 'signed_mismatch':
            wanted[('TOKEN_X', 'B', 'customer_liability')] = ('11', '10', '1', 'COMPLETE', 'MISMATCH')
        require(actual == wanted, 'provenance literal financial result differs: ' + name)
    return {'status': 'PASS', 'scenario_count': 10, 'case_count': 24, 'case_ids': sorted(cases),
            'expected_results_source': 'release-owned literals; demo expected labels are not an oracle'}


def provenance_command_record(target, name, python, flags, cwd, verification):
    folder = Path(target) / 'cases' / name / 'commands' / 'verify'
    command = json.loads((folder / 'command.json').read_text(encoding='utf-8'))
    argv = list(map(str, [python, '-B', *flags, '-m', 'crypto_reconciliation_lab', 'verify-provenance',
        '--bundle', Path(target) / 'cases' / name / 'bundle',
        '--expectations', Path(target) / 'cases' / name / 'expectations.json']))
    require(command.get('argv') == argv and Path(command['cwd']).resolve() == Path(cwd).resolve()
            and type(command.get('exit_code')) is int and command['exit_code'] == verification['exit_code'],
            'provenance actual CLI identity or exit differs: ' + name)
    for kind in ('stdout', 'stderr'):
        relative = 'cases/' + name + '/commands/verify/' + kind + '.txt'
        require(command.get(kind) == relative and command.get(kind + '_sha256') == digest(folder / (kind + '.txt'))['sha256'],
                'provenance command log identity differs: ' + name)
    require(json.loads((folder / 'stdout.txt').read_text(encoding='utf-8')) == verification,
            'provenance command stdout differs from saved verification: ' + name)
    return {'command': digest(folder / 'command.json'), 'stdout': digest(folder / 'stdout.txt'),
            'stderr': digest(folder / 'stderr.txt'), 'exit_code': command['exit_code']}


def provenance(gate, python, source, mode):
    target = gate.output / (mode + '-provenance')
    flags = ['-I'] if mode == 'installed' else []
    cwd = None if mode == 'installed' else source
    gate.run(mode + '-provenance', [python, '-B', *flags, '-m', 'crypto_reconciliation_lab',
             'demo-provenance', '--output', target], cwd)
    report = json.loads((target / 'summary.json').read_text(encoding='utf-8'))
    coverage = validate_provenance_demo(report)
    origin = Path(report['environment']['import_origin']).resolve()
    require(origin == Path(gate.record[mode + '_import']['origin']).resolve(),
            'provenance demo imported a different source/package')
    records = {}
    for row in report['cases']:
        path = target / 'cases' / row['id'] / 'verification.json'
        actual = json.loads(path.read_text(encoding='utf-8'))
        expected_exit, expected_status, expected_reasons = PROVENANCE_RESULTS[row['id']]
        require(type(actual.get('exit_code')) is int
                and (actual['exit_code'], actual.get('status'), sorted({reason['code'] for reason in actual['reasons']}))
                == (expected_exit, expected_status, expected_reasons),
                'provenance saved verification differs: ' + row['id'])
        require(actual.get('run_creation_authorization_cut') == 'NOT_RECORDED'
                and actual.get('financial_recomputation') == 'NOT_PERFORMED', 'provenance saved limits disappeared')
        observed_command = provenance_command_record(target, row['id'], python, flags,
                                                     gate.external if mode == 'installed' else source, actual)
        records[row['id']] = {'path': str(path), **digest(path), 'actual_cli': observed_command}
    controls = {}
    for name in ('clean', 'broken_protected_link'):
        code, status, reasons = PROVENANCE_RESULTS[name]
        verified = json.loads(gate.run(mode + '-verify-provenance-' + name,
            [python, '-B', *flags, '-m', 'crypto_reconciliation_lab', 'verify-provenance',
             '--bundle', target / 'cases' / name / 'bundle',
             '--expectations', target / 'cases' / name / 'expectations.json'], cwd, expected=code))
        require(type(verified.get('exit_code')) is int and verified['exit_code'] == code and verified['status'] == status
                and sorted({reason['code'] for reason in verified['reasons']}) == reasons,
                'independent provenance CLI control differs: ' + name)
        path = target / (name + '.release-verification.json')
        save(path, verified)
        controls[name] = {'path': str(path), **digest(path), 'result': verified}
    gate.record[mode + '_provenance'] = {'status': 'PASS', 'path': str(target), 'coverage': coverage,
        'summary_identity': digest(target / 'summary.json'), 'verification_records': records, 'independent_cli_controls': controls,
        'operator_anchor': 'TEST-ONLY controlled fixture observation outside each bundle',
        'run_creation_authorization_cut': 'NOT_RECORDED', 'financial_recomputation': 'NOT_PERFORMED'}
    gate.persist()


MAINTENANCE_RESULTS = {
    'rotation': (0, 'VERIFIED_FOR_CAPTURE', []),
    'later_replay_promoted': (2, 'FAILED', ['DELIVERY_CAUSALITY']),
    'large_ids': (0, 'VERIFIED_FOR_CAPTURE', []),
    'tampered_transport': (2, 'FAILED', ['PRESENTATION_INTEGRITY']),
}


def validate_provenance_maintenance(setup, results):
    require(setup.get('format') == 'release-provenance-maintenance-v1'
            and setup.get('package_version') == '0.11.1', 'maintenance setup identity differs')
    require(setup.get('f1_preservation') == {'external_changed_fields': ['capture_digest'],
            'raw_run_equal': True, 'signed_materials_equal': True}, 'maintenance F1 preservation differs')
    require(setup.get('f2_authoritative_capture_unchanged') is True, 'maintenance F2 raw capture changed')
    paths = setup.get('f2_identity_paths')
    require(type(paths) is list and len(paths) == 4
            and {row.get('receipt_id') for row in paths} == {
                '9007199254740991', '9007199254740992', '9007199254740993', '9223372036854775807'}
            and all(type(row.get('effect_count')) is int and row['effect_count'] == 1 for row in paths),
            'maintenance exact SQL identity coverage differs')
    require(set(setup.get('fixtures', {})) == set(results) == set(MAINTENANCE_RESULTS),
            'maintenance CLI control inventory differs')
    for name, (code, status, reasons) in MAINTENANCE_RESULTS.items():
        result = results[name]
        require(type(result.get('exit_code')) is int and result['exit_code'] == code
                and result.get('status') == status
                and sorted({row['code'] for row in result.get('reasons', [])}) == reasons,
                'maintenance semantic CLI result differs: ' + name)
        require(result.get('run_creation_authorization_cut') == 'NOT_RECORDED'
                and result.get('financial_recomputation') == 'NOT_PERFORMED', 'maintenance limits disappeared')
    return {'status': 'PASS', 'case_count': 4, 'case_ids': sorted(MAINTENANCE_RESULTS)}


def provenance_maintenance(gate, python, source, mode):
    target = gate.output / (mode + '-provenance-maintenance')
    flags = ['-I'] if mode == 'installed' else []
    cwd = None if mode == 'installed' else source
    helper = source / 'scripts/release_provenance_maintenance.py'
    # -c leaves source mode's cwd importable; installed mode is isolated and only
    # the explicit test-helper directory is added after the package import.
    launcher = 'import runpy,sys; p=sys.argv.pop(1); runpy.run_path(p,run_name="__main__")'
    setup = json.loads(gate.run(mode + '-provenance-maintenance-setup',
        [python, '-B', *flags, '-c', launcher, helper, '--tests', source / 'tests', '--output', target], cwd))
    require(Path(setup['environment']['origin']).resolve() == Path(gate.record[mode + '_import']['origin']).resolve(),
            'maintenance setup imported a different source/package')
    require(setup['environment']['isolated'] is (mode == 'installed'), 'maintenance import isolation differs')
    results, controls = {}, {}
    for name, (code, _, _) in MAINTENANCE_RESULTS.items():
        results[name] = json.loads(gate.run(mode + '-maintenance-verify-' + name,
            [python, '-B', *flags, '-m', 'crypto_reconciliation_lab', 'verify-provenance',
             '--bundle', target / name / 'bundle', '--expectations', target / name / 'expectations.json'], cwd, expected=code))
        path = target / name / 'verification.json'
        save(path, results[name])
        controls[name] = {'path': str(path), **digest(path), 'result': results[name]}
    coverage = validate_provenance_maintenance(setup, results)
    summary = {'status': 'PASS', 'coverage': coverage, 'setup': setup,
               'setup_identity': digest(target / 'setup.json'), 'cli_controls': controls}
    save(target / 'summary.json', summary)
    gate.record[mode + '_provenance_maintenance'] = summary
    gate.persist()


# Stage 12 release-owned scope: never infer required coverage from demo labels.
EXECUTION_CASES = {
    'legacy_unrecorded': (0, 'NOT_RECORDED', None, 'show-execution'),
    'legacy_recorded': (0, 'RECORDED', None, 'reconcile-recorded'),
    'legacy_retry': (0, 'RECORDED', None, 'reconcile-recorded'),
    'legacy_conflict': (2, 'ERROR', 'EXECUTION_REQUEST_CONFLICT', 'reconcile-recorded'),
    'legacy_new_request': (0, 'RECORDED', None, 'reconcile-recorded'),
    'legacy_multiple': (0, 'MULTIPLE_EXECUTIONS', None, 'show-execution'),
    'legacy_show': (0, 'RECORDED', None, 'show-execution'),
    'legacy_export': (0, 'EXPORTED', None, 'export-execution'),
    'legacy_export_existing': (2, 'ERROR', 'EXECUTION_OUTPUT', 'export-execution'),
    'protected_recorded': (0, 'RECORDED', None, 'reconcile-recorded'),
    'protected_retry_after_change': (0, 'RECORDED', None, 'reconcile-recorded'),
    'protected_new_request': (0, 'RECORDED', None, 'reconcile-recorded'),
    'protected_original_readback': (0, 'RECORDED', None, 'show-execution'),
    'protected_multiple': (0, 'MULTIPLE_EXECUTIONS', None, 'show-execution'),
    'protected_export': (0, 'EXPORTED', None, 'export-execution'),
    'signed_mismatch': (1, 'RECORDED', None, 'reconcile-recorded'),
    'signed_mismatch_show': (0, 'RECORDED', None, 'show-execution'),
}
EXECUTION_KILLS = {
    'test_sigkill_after_financial_persistence_rolls_back_fresh_and_existing_variants': 'execution_after_financial',
    'test_sigkill_after_context_before_commit_rolls_back_fresh_and_existing_variants': 'execution_after_context',
    'test_sigkill_after_commit_before_cli_ack_retries_durable_original': 'execution_after_commit',
}
EXECUTION_RACES = {
    'test_separate_process_admission_before_cut_is_wholly_present': ('admission', 'before'),
    'test_separate_process_admission_after_cut_cannot_mix_with_first_context': ('admission', 'after'),
    'test_separate_process_policy_before_cut_is_wholly_present': ('policy', 'before'),
    'test_separate_process_policy_after_cut_cannot_mix_with_first_context': ('policy', 'after'),
}
EXECUTION_SAME_REQUEST = 'test_same_request_in_two_processes_has_one_durable_execution'


def execution_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def execution_member(root, name):
    relative = Path(name)
    target = root / relative
    require(not relative.is_absolute() and '..' not in relative.parts and target.is_file()
            and not target.is_symlink() and target.resolve().is_relative_to(root.resolve()),
            'EXECUTION_EVIDENCE: missing or unsafe member ' + str(name))
    return target


def execution_financial(result, mismatch=False):
    financial = result['financial_result']
    literal = [('ASSET_A', 'A', 'I1', '7'), ('ASSET_A', 'A', 'I2', '4'),
               ('ASSET_A', 'B', 'customer_liability', '11'), ('ASSET_B', 'A', 'I1', '0.3'),
               ('ASSET_B', 'A', 'I2', '0.2'), ('ASSET_B', 'B', 'customer_liability', '0.5')]
    fields = ('asset', 'comparison', 'scope', 'expected', 'reported', 'difference', 'data_state', 'reconciliation_state')
    expected = [(asset, comparison, scope, amount, '10' if mismatch and asset == 'ASSET_A' and comparison == 'B' else amount,
                 '1' if mismatch and asset == 'ASSET_A' and comparison == 'B' else '0', 'COMPLETE',
                 'MISMATCH' if mismatch and asset == 'ASSET_A' and comparison == 'B' else 'MATCHED')
                for asset, comparison, scope, amount in literal]
    require([tuple(row[key] for key in fields) for row in financial['findings']] == expected,
            'EXECUTION_FINANCIAL: six literal findings differ')
    require(financial['rule_version'] == 'stage2-v2', 'EXECUTION_FINANCIAL: rule changed')
    for asset, balances, liability, custody in (
            ('ASSET_A', {'I1': '7', 'I2': '4'}, '11', {'platform': '2', 'external': '9'}),
            ('ASSET_B', {'I1': '0.3', 'I2': '0.2'}, '0.5', {'platform': '0.05', 'external': '0.45'})):
        ledger = financial['ledgers'][asset]
        require((ledger['investor_balances'], ledger['liability'], ledger['custody_rollforward']) ==
                (balances, liability, custody), 'EXECUTION_FINANCIAL: literal ledger differs')


def execution_context(result, protected, receipts=30, epoch=None):
    context = result['context']
    require(result['status'] == 'RECORDED' and context['schema_version'] == 6
            and context['scope']['complete'] is True, 'EXECUTION_CONTEXT: incomplete recorded context')
    require(context['claims'] == {'context_state': 'RECORDED', 'admission_mode': 'PROTECTED' if protected else 'LEGACY',
            'legacy_signature_status': 'NOT_APPLICABLE' if protected else 'UNSIGNED',
            'source_signature_verification': 'NOT_PERFORMED', 'run_actor_authorization': 'NOT_DEFINED'},
            'EXECUTION_CONTEXT: claims changed')
    tables = context['tables']
    require(context['counts'] == {table: len(rows) for table, rows in tables.items()}
            and len(tables['receipts']) == receipts and len(tables['records']) == 30,
            'EXECUTION_CONTEXT: physical/normalized inventory differs')
    require((context['observed_policy_head']['epoch'] if context['observed_policy_head'] else None) == epoch
            and context['acceptance_epochs'] == ([1] if protected else []), 'EXECUTION_CONTEXT: policy cut differs')
    require(len(context['selected_evidence']) == 60, 'EXECUTION_CONTEXT: selected evidence coverage differs')
    if protected:
        require(len(tables['delivery_effects']) == len(tables['auth_decisions']) == receipts,
                'EXECUTION_CONTEXT: admission inventory differs')
    else:
        require(all(not rows for table, rows in tables.items() if table.startswith('auth_')),
                'EXECUTION_CONTEXT: legacy unexpectedly claims authentication')


def validate_execution_demo(path, *, profile, package_origin):
    root = Path(path)
    summary = execution_json(root / 'summary.json')
    require(profile in ('legacy', 'protected') and summary.get('format') == 'execution-context-demo-v1'
            and summary.get('profile') == profile and summary.get('status') == 'PASS'
            and summary.get('schema_version') == 6 and summary.get('rule_version') == 'stage2-v2',
            'EXECUTION_DEMO: header or profile mismatch')
    require(summary.get('frozen_experiment') == summary.get('process_crash_race_experiments') == 'NOT_RUN',
            'EXECUTION_DEMO: scope boundary changed')
    environment = summary['environment']
    require(Path(environment['import_origin']).resolve() == Path(package_origin).resolve(),
            'EXECUTION_DEMO: import origin differs')
    required = list(EXECUTION_CASES)[:9] if profile == 'legacy' else list(EXECUTION_CASES)
    require(summary['case_inventory'] == required and [case['id'] for case in summary['cases']] == required,
            'EXECUTION_DEMO: missing, duplicate or unexpected cases')
    results, identities = {}, {}
    for case in summary['cases']:
        name = case['id']
        code, status, reason, operation = EXECUTION_CASES[name]
        require(case['command'] == 'commands/' + name + '/command.json'
                and case['result'] == 'commands/' + name + '/result.json', 'EXECUTION_DEMO: command binding differs')
        command_path = execution_member(root, case['command'])
        result_path = execution_member(root, case['result'])
        command, result = execution_json(command_path), execution_json(result_path)
        for channel in ('stdout', 'stderr'):
            log = execution_member(root, 'commands/' + name + '/' + channel + '.txt')
            require(digest(log) == command[channel], 'EXECUTION_DEMO: missing or changed CLI log')
        actual = {'exit_code': code, 'status': status, 'reason_code': reason}
        require(command['exit_code'] == code and result.get('status') == status and result.get('reason_code') == reason
                and case['actual'] == actual, 'EXECUTION_DEMO: actual exit/status/reason differs')
        require(execution_json(command_path.parent / 'stdout.txt') == result,
                'EXECUTION_DEMO: result differs from actual CLI stdout')
        argv = command['argv']
        flags = ['-B', '-I'] if environment['isolated'] else ['-B']
        require(argv[:len(flags) + 4] == [environment['executable'], *flags, '-m', 'crypto_reconciliation_lab', operation]
                and bool(command['cwd']) and bool(command['started_at']) and bool(command['finished_at']),
                'EXECUTION_DEMO: command/interpreter identity differs')
        if 'financial_result' in result:
            execution_financial(result, name.startswith('signed_mismatch'))
        if status == 'RECORDED':
            protected = not name.startswith('legacy_')
            receipts = 31 if name == 'protected_new_request' else 30
            execution_context(result, protected, receipts, (2 if receipts == 31 else 1) if protected else None)
        results[name] = result
        identities[name] = {'command': digest(command_path), 'result': digest(result_path),
                            'stdout': command['stdout'], 'stderr': command['stderr'], 'exit_code': code}
    old, first, retry, second = (results[name] for name in ('legacy_unrecorded', 'legacy_recorded', 'legacy_retry', 'legacy_new_request'))
    require(old['execution_ids'] == [] and old.get('run_creation_authorization_cut') == 'NOT_RECORDED'
            and first['run_id'] == old['run_id'], 'EXECUTION_DEMO: historical run was enriched')
    for prefix, original, replay, newer, readback in [('legacy', first, retry, second, results['legacy_show'])] + (
            [('protected', results['protected_recorded'], results['protected_retry_after_change'],
              results['protected_new_request'], results['protected_original_readback'])] if profile == 'protected' else []):
        require(original['replayed'] is False and replay['replayed'] is True and newer['replayed'] is False
                and original['execution_id'] == replay['execution_id'] == readback['execution_id']
                and original['context'] == replay['context'] == readback['context']
                and original['run_id'] == newer['run_id'] and original['execution_id'] != newer['execution_id']
                and original['context_hash'] != newer['context_hash'], 'EXECUTION_DEMO: retry/new-request identity differs')
        multiple = results[prefix + '_multiple']
        require(multiple['execution_ids'] == sorted([original['execution_id'], newer['execution_id']])
                and 'execution_id' not in multiple, 'EXECUTION_DEMO: run-only lookup selected an arbitrary execution')
        export = results[prefix + '_export']
        relative = 'exports/legacy' if prefix == 'legacy' else 'exports/protected-original'
        require(set(export['files']) == {'context.json', 'run.json', 'execution.json', 'summary.json', 'summary.md'},
                'EXECUTION_DEMO: export inventory differs')
        for member, identity in export['files'].items():
            require(digest(execution_member(root, relative + '/' + member)) == identity, 'EXECUTION_DEMO: export bytes differ')
        require(export['files']['context.json']['sha256'] == original['context_hash']
                and export['files']['run.json']['sha256'] == original['run_payload_sha256']
                and execution_json(root / relative / 'context.json') == original['context'], 'EXECUTION_DEMO: raw export binding differs')
    if profile == 'protected':
        context = results['protected_new_request']['context']
        groups = {}
        for row in context['tables']['receipts']:
            groups.setdefault(row['receipt_hash'], []).append(row['id'])
        duplicates = [(key, ids) for key, ids in groups.items() if len(ids) > 1]
        require(len(duplicates) == 1 and len(set(duplicates[0][1])) == 2
                and context['selected_evidence'][duplicates[0][0]]['receipt_ids'] == sorted(duplicates[0][1]),
                'EXECUTION_DEMO: physical candidates were lost or collapsed')
    return {'status': 'PASS', 'profile': profile, 'case_count': len(required), 'case_ids': required,
            'summary': digest(root / 'summary.json'), 'cases': identities, 'import_origin': str(package_origin),
            'literal_financial_findings': 6, 'process_experiments': 'NOT_RUN'}


def execution_recorded_path(value, cwd):
    """Compare recorded POSIX paths lexically; never inspect the remote host."""
    import posixpath
    require(isinstance(value, str) and bool(value) and '\x00' not in value
            and isinstance(cwd, str) and cwd.startswith('/') and '\x00' not in cwd,
            'EXECUTION_PROCESS: request binding requires a path and absolute recorded cwd')
    # POSIX double-leading-slash semantics are implementation-defined.
    require(not value.startswith('//') and not cwd.startswith('//'),
            'EXECUTION_PROCESS: request binding has an ambiguous recorded path')
    return posixpath.normpath(value if value.startswith('/') else posixpath.join(cwd, value))


def execution_recorded_cut(value):
    from datetime import datetime, timezone
    require(isinstance(value, str), 'EXECUTION_PROCESS: request binding requires a timestamp')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(parsed.utcoffset() is not None, 'EXECUTION_PROCESS: request binding timestamp lacks a timezone')
        return parsed.astimezone(timezone.utc).isoformat(timespec='microseconds')
    except (ValueError, OverflowError) as exc:
        raise ValueError('EXECUTION_PROCESS: request binding timestamp is invalid') from exc


def execution_process_request(row, request, action):
    """Extract only recorded source/operation semantics, not a runtime identity."""
    require(isinstance(request, dict) and request.get('action') == action,
            'EXECUTION_PROCESS: request binding action differs from the experiment role')
    cwd = row.get('cwd')
    bound = {'action': action, 'db': execution_recorded_path(request.get('db'), cwd)}
    if action == 'recorded':
        identifier = request.get('request_id')
        timeout = request.get('busy_timeout_ms', 250)
        require(isinstance(identifier, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', identifier)
                and type(timeout) is int and 0 <= timeout <= 5000,
                'EXECUTION_PROCESS: request binding identifier or timeout is invalid')
        bound.update(request_id=identifier, busy_timeout_ms=timeout,
                     balance_at=execution_recorded_cut(request.get('balance_at')),
                     knowledge_at=execution_recorded_cut(request.get('knowledge_at')))
    elif action == 'admission':
        bound.update(snapshot=execution_recorded_path(request.get('snapshot'), cwd),
                     envelope=execution_recorded_path(request.get('envelope'), cwd))
    else:
        require(action == 'policy' and isinstance(request.get('policy'), dict)
                and type(request.get('expected_epoch')) is int and request['expected_epoch'] >= 0
                and isinstance(request.get('expected_hash'), str)
                and re.fullmatch(r'[0-9a-f]{64}', request['expected_hash']),
                'EXECUTION_PROCESS: request binding policy parameters are invalid')
        bound.update(policy=request['policy'], expected_epoch=request['expected_epoch'],
                     expected_hash=request['expected_hash'])
    return bound


def validate_execution_process_evidence(root, *, package_origin, isolated):
    root = Path(root)
    required = [*EXECUTION_KILLS, *EXECUTION_RACES, EXECUTION_SAME_REQUEST]
    require(root.is_dir(), 'EXECUTION_PROCESS: retained evidence missing')
    directories = {}
    for name in required:
        matches = [path for path in root.glob(name + '-*') if path.is_dir()]
        require(len(matches) == 1, 'EXECUTION_PROCESS: missing or repeated test evidence ' + name)
        directories[name] = matches[0]
    require(set(root.iterdir()) == set(directories.values()), 'EXECUTION_PROCESS: unexpected test evidence')
    identities, process_count = {}, 0
    def load(directory, relative):
        path = execution_member(root, (directory / relative).relative_to(root).as_posix())
        identities[path.relative_to(root).as_posix()] = digest(path)
        return execution_json(path)
    def process(directory, name, expected_exit=0, action='recorded'):
        nonlocal process_count
        row = load(directory, name + '-process.json')
        request = load(directory, name + '-request.json')
        bound = execution_process_request(row, request, action)
        require(row['exit_code'] == expected_exit and row['joined'] is True and row['forced_timeout_cleanup'] is False
                and type(row['pid']) is int and row['pid'] > 0 and bool(row['started_at']) and bool(row['cwd']),
                'EXECUTION_PROCESS: child did not finish as required')
        argv = row['argv']
        require(('-I' in argv) is isolated and '--request' in argv and
                Path(argv[argv.index('--request') + 1]).name == name + '-request.json', 'EXECUTION_PROCESS: invocation binding differs')
        messages = row['messages']
        require(messages and messages[0]['type'] == 'READY' and all(message['pid'] == row['pid'] for message in messages),
                'EXECUTION_PROCESS: READY/PID binding differs')
        ready = messages[0]
        for observed in messages:
            if observed['type'] == 'BARRIER':
                require(request.get('barrier') == observed['point'],
                        'EXECUTION_PROCESS: request binding barrier differs')
            if observed['type'] == 'SQL_BEGIN_ATTEMPT':
                require(request.get('observe_begin') is True,
                        'EXECUTION_PROCESS: request binding did not request BEGIN observation')
        require(ready['origin'] == str(package_origin) and ready['isolated'] is isolated and ready['interpreter'] == argv[0]
                and bool(ready['sqlite']) and set(ready['settings']) == {'journal_mode', 'synchronous', 'busy_timeout'},
                'EXECUTION_PROCESS: interpreter/settings observation missing')
        for channel, key in [('stdout-tail', 'stdout_tail'), ('stderr', 'stderr')]:
            path = execution_member(root, (directory / (name + '-' + channel + '.txt')).relative_to(root).as_posix())
            require(path.read_text(encoding='utf-8') == row[key], 'EXECUTION_PROCESS: actual child log differs')
            identities[path.relative_to(root).as_posix()] = digest(path)
        process_count += 1
        return row, bound
    def message(row, kind):
        found = [entry for entry in row['messages'] if entry['type'] == kind]
        require(len(found) == 1, 'EXECUTION_PROCESS: missing/duplicate ' + kind)
        return found[0]
    def result(row, request):
        msg = message(row, 'RESULT')
        value = msg['result']
        if request['action'] == 'policy':
            require(value.get('epoch') == request['expected_epoch'] + 1 and value.get('payload') == request['policy'],
                    'EXECUTION_PROCESS: request binding differs from the committed policy result')
        if value.get('status') == 'RECORDED':
            ack = msg['ack']
            require(ack['exit_code'] == 0 and ack['argv'][0] == 'reconcile-recorded' and json.loads(ack['stdout']) == value,
                    'EXECUTION_PROCESS: first real CLI ACK differs')
            argv = ack['argv']
            flags = {'--db', '--balance-at', '--knowledge-at', '--request-id', '--busy-timeout-ms'}
            require(len(argv) == 11 and set(argv[1::2]) == flags and all(isinstance(v, str) for v in argv),
                    'EXECUTION_PROCESS: ACK binding options are missing, repeated or unexpected')
            options = dict(zip(argv[1::2], argv[2::2]))
            require(options['--busy-timeout-ms'].isdigit(), 'EXECUTION_PROCESS: ACK binding timeout is invalid')
            acknowledged = execution_process_request(row, {'action': 'recorded',
                'db': options['--db'], 'balance_at': options['--balance-at'], 'knowledge_at': options['--knowledge-at'],
                'request_id': options['--request-id'], 'busy_timeout_ms': int(options['--busy-timeout-ms'])}, 'recorded')
            require(acknowledged == request, 'EXECUTION_PROCESS: ACK binding differs from the recorded request')
            require(value.get('request_id') == request['request_id'] == value['context'].get('request_id')
                    and value.get('request') == value['context'].get('request')
                    and all(execution_recorded_cut(value['request'].get(key)) == request[key]
                            and execution_recorded_cut(value['financial_result'].get(key)) == request[key]
                            for key in ('balance_at', 'knowledge_at')),
                    'EXECUTION_PROCESS: request binding differs from the recorded result')
            execution_financial(value)
        return value
    before_base = {'runs': 0, 'findings': 0, 'evidence': 0, 'correction_groups': 0, 'correction_effects': 0,
                   'execution_contexts': 0, 'recorded_executions': 0}
    durable = dict(before_base, runs=1, findings=6, evidence=60, execution_contexts=1, recorded_executions=1)
    kills = []
    for name, point in EXECUTION_KILLS.items():
        for variant in ('fresh', 'existing'):
            directory = directories[name] / variant
            interrupted, request = process(directory, 'interrupted', -9)
            retry, retry_request = process(directory, 'retry')
            barrier = message(interrupted, 'BARRIER')
            committed = point == 'execution_after_commit'
            require(barrier['point'] == point and barrier['in_transaction'] is (not committed)
                    and interrupted['signal'] == 'SIGKILL' and interrupted['sender_result'] == 'UNKNOWN'
                    and not any(row['type'] in ('RESULT', 'ERROR') for row in interrupted['messages']),
                    'EXECUTION_PROCESS: actual SIGKILL barrier/unknown ACK differs')
            observed = load(directory, 'durability.json')
            before = dict(before_base, **({'runs': 1, 'findings': 6, 'evidence': 60} if variant == 'existing' else {}))
            barrier_counts = dict(durable, **({'execution_contexts': 0, 'recorded_executions': 0}
                                            if point == 'execution_after_financial' else {}))
            require(message(interrupted, 'READY')['counts'] == before and barrier['counts'] == barrier_counts
                    and observed['point'] == point and observed['existing_run'] is (variant == 'existing')
                    and observed['before_counts'] == before and observed['after_kill_counts'] == (durable if committed else before)
                    and observed['after_retry_counts'] == durable, 'EXECUTION_PROCESS: durable rollback/commit counts differ')
            require(request == retry_request, 'EXECUTION_PROCESS: request binding differs across interrupted/retry children')
            retried = result(retry, retry_request)
            require(retried['replayed'] is committed and observed['retry_replayed'] is committed
                    and observed['retry_execution_id'] == retried['execution_id']
                    and request['request_id'] == retry_request['request_id'] == retried['request_id'],
                    'EXECUTION_PROCESS: retry did not return the durable request')
            kills.append({'test': name, 'variant': variant, 'point': point, 'exit_code': -9,
                          'sender_result': 'UNKNOWN', 'retry_replayed': committed})
    races = []
    for name, (action, timing) in EXECUTION_RACES.items():
        directory = directories[name]
        if timing == 'before':
            writer, writer_request = process(directory, 'writer-before-cut', action=action)
            reader, reader_request = process(directory, 'execution')
            require(writer_request['db'] == reader_request['db'], 'EXECUTION_PROCESS: request binding differs across before-cut children')
            written, execution = result(writer, writer_request), result(reader, reader_request)
            require((written.get('status') == 'COMPLETE') if action == 'admission' else written.get('epoch') == 2,
                    'EXECUTION_PROCESS: before-cut writer did not commit')
            execution_context(execution, True, 31 if action == 'admission' else 30, 1 if action == 'admission' else 2)
        else:
            holder, holder_request = process(directory, 'execution-holder')
            contender, contender_request = process(directory, 'writer-contender', 0 if action == 'admission' else 2, action=action)
            after, after_request = process(directory, 'writer-after-cut', action=action)
            later, later_request = process(directory, 'later-execution')
            require(len({r['db'] for r in (holder_request, contender_request, after_request, later_request)}) == 1
                    and contender_request == after_request
                    and holder_request['request_id'] != later_request['request_id']
                    and all(holder_request[key] == later_request[key] for key in ('balance_at', 'knowledge_at')),
                    'EXECUTION_PROCESS: request binding differs across after-cut children')
            barrier = message(holder, 'BARRIER')
            require(holder['pid'] != contender['pid'] and barrier['point'] == 'execution_after_begin' and barrier['in_transaction'] is True
                    and message(contender, 'SQL_BEGIN_ATTEMPT')['statement'] == 'BEGIN IMMEDIATE',
                    'EXECUTION_PROCESS: after-cut competing writer was not observed at the locked boundary')
            if action == 'admission':
                busy = result(contender, contender_request)
                require(busy['status'] == 'RETRYABLE_BUSY' and busy['rejection']['durable'] is False
                        and busy['responses'] == [], 'EXECUTION_PROCESS: busy admission claimed a commit')
            else:
                require(message(contender, 'ERROR')['reason_code'] == 'SQLITE_BUSY',
                        'EXECUTION_PROCESS: busy policy writer did not report contention')
            first, second, written = result(holder, holder_request), result(later, later_request), result(after, after_request)
            execution_context(first, True, 30, 1)
            execution_context(second, True, 31 if action == 'admission' else 30, 1 if action == 'admission' else 2)
            require((written.get('status') == 'COMPLETE') if action == 'admission' else written.get('epoch') == 2,
                    'EXECUTION_PROCESS: writer after release did not commit')
            observed = load(directory, 'cut-observation.json')
            require(observed['action'] == action and observed['busy_is_not_commit'] is True
                    and observed['first_execution_id'] == first['execution_id']
                    and observed['second_execution_id'] == second['execution_id']
                    and first['execution_id'] != second['execution_id'] and first['run_id'] == second['run_id']
                    and observed['first_counts'] == first['context']['counts']
                    and observed['second_counts'] == second['context']['counts'], 'EXECUTION_PROCESS: cut observation differs')
        races.append({'test': name, 'action': action, 'timing': timing, 'status': 'PASS'})
    directory = directories[EXECUTION_SAME_REQUEST]
    first, first_request = process(directory, 'first-process')
    second, second_request = process(directory, 'second-process', 2)
    retry, retry_request = process(directory, 'second-process-retry')
    require(first_request == second_request == retry_request,
            'EXECUTION_PROCESS: request binding differs across same-request children')
    first_result, retry_result = result(first, first_request), result(retry, retry_request)
    require(first['pid'] != second['pid'] and message(first, 'BARRIER')['in_transaction'] is True
            and message(second, 'ERROR')['reason_code'] == 'EXECUTION_BUSY'
            and first_request['request_id'] == second_request['request_id'] == retry_request['request_id']
            and first_result['execution_id'] == retry_result['execution_id']
            and first_result['context'] == retry_result['context'] and retry_result['replayed'] is True
            and message(retry, 'RESULT')['counts'] == durable, 'EXECUTION_PROCESS: same request created a second execution')
    return {'status': 'PASS', 'test_names': required, 'test_count': 8, 'process_count': process_count,
            'kill_variants': kills, 'race_cases': races, 'same_request': {'status': 'PASS', 'durable_executions': 1},
            'files': identities, 'import_origin': str(package_origin), 'isolated': isolated}


def execution_demo(gate, python, source, mode, profile):
    target = gate.output / (mode + '-execution')
    flags = ['-I'] if mode == 'installed' else []
    gate.run(mode + '-execution', [python, '-B', *flags, '-m', 'crypto_reconciliation_lab',
             'demo-execution-context', '--profile', profile, '--output', target], None if mode == 'installed' else source)
    check = validate_execution_demo(target, profile=profile, package_origin=gate.record[mode + '_import']['origin'])
    gate.record[mode + '_execution'] = {'status': 'PASS', 'path': str(target), 'validation': check,
                                      'summary': execution_json(target / 'summary.json')}
    gate.persist()


def core_execution_denied(gate, python):
    target = gate.output / 'core-protected-execution-must-not-exist'
    result = json.loads(gate.run('core-protected-execution-unavailable', [python, '-B', '-I', '-m',
                        'crypto_reconciliation_lab', 'demo-execution-context', '--profile', 'protected', '--output', target], expected=2))
    require(result.get('status') == 'ERROR' and result.get('reason_code') == 'AUTH_DEPENDENCY' and not target.exists(),
            'EXECUTION_DEMO: core protected invocation did not refuse before side effects')
    gate.record['core_execution_refusal'] = {'status': 'PASS', 'exit_code': 2, 'reason_code': 'AUTH_DEPENDENCY', 'output_absent': True}
    gate.persist()


def wheel_manifest(wheel, version='0.11.1'):
    with zipfile.ZipFile(wheel) as archive:
        members = archive.infolist()
        require(len(members) <= 1000 and sum(item.file_size for item in members) <= 32 * 1024**2, 'wheel member/size limit exceeded')
        seen, result = set(), {}
        for item in members:
            name = item.filename
            parts = PurePosixPath(name).parts
            require(name and '\\' not in name and '\x00' not in name and not re.match(r'^[A-Za-z]:', name)
                    and not PurePosixPath(name).is_absolute() and all(part not in ('', '.', '..') for part in name.split('/')),
                    'unsafe wheel member')
            require(name not in seen, 'wheel has duplicate members')
            seen.add(name)
            mode = stat.S_IFMT(item.external_attr >> 16)
            require(not item.is_dir() and mode in (0, stat.S_IFREG), 'wheel has a link, directory or special member')
            require(name.startswith(('crypto_reconciliation_lab/', f'crypto_reconciliation_lab-{version}.dist-info/')),
                    'wheel contains an unrelated installation path')
            require(not any(part in ('__pycache__', '.git', '.DS_Store', 'node_modules') or part.startswith('.env') for part in parts)
                    and not name.endswith(('.db', '.sqlite', '.sqlite3', '.pyc', '.pem', '.key', '.zip', '.whl', '-wal', '-shm', '-journal')),
                    'wheel contains excluded artifact')
            if name.startswith('crypto_reconciliation_lab/'):
                require(PurePosixPath(name).suffix in ('.py', '.html', '.css', '.js')
                        or name in ('crypto_reconciliation_lab/admission/recovery_scope_v2.json',
                                    'crypto_reconciliation_lab/source_auth/experiment_scope_v1.json',
                                    'crypto_reconciliation_lab/replay/demo_catalog_v1.json',
                                    'crypto_reconciliation_lab/replay/fixtures/protected-context.json',
                                    'crypto_reconciliation_lab/replay/fixtures/protected-run.json'),
                        'wheel contains unexpected package data')
            data = archive.read(item)
            require(len(data) == item.file_size, 'wheel member size mismatch')
            result[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        return result


def reproduce(gate, python, source, mode, reference, core):
    target = gate.output / (mode + '-reproduction')
    gate.run(mode + '-reproduction', [python, '-B', '-I', source / 'scripts/reproduce_review.py',
             '--mode', mode, '--python', python, '--output', target])
    result = json.loads((target / 'reproduction.json').read_text(encoding='utf-8'))
    require(result['status'] == 'PASSED', 'small review reproduction failed')
    audits = list((target / 'logs').glob('*-imports.json'))
    require(audits, 'reproduction has no actual CLI import audits')
    for path in audits:
        audit = json.loads(path.read_text(encoding='utf-8'))
        require(not audit['imported_optional'], 'review/rank CLI imported optional AI dependencies')
        if core:
            require(not any(audit['available_optional'].values()), 'core child can import optional AI dependencies')
    reports = {stage: FINANCIAL_SCOPE.compare_required_reports(target / 'review/sources' / stage, reference, stage)
               for stage in ('stage1', 'stage2')}
    gate.record[mode + '_reproduction'] = {'status': 'PASS', 'path': str(target), 'result': result,
                                        'financial_reports': reports, 'actual_cli_import_audits': len(audits)}
    gate.persist()


def accept_recovery_evidence(source, target):
    """The same pinned semantic gate for executed and separately supplied reports.

    This validates completeness/consistency, not authenticity or re-execution.
    """
    source, target = Path(source).resolve(), Path(target).resolve()
    summary, schedule = target / 'delivery-summary.json', target / 'schedule.json'
    for path in (summary, schedule):
        require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 16 * 1024 * 1024,
                'ADMISSION_SCOPE: bounded regular recovery evidence required')
    before = {'summary': digest(summary), 'schedule': digest(schedule)}
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, 'ADMISSION_SCOPE: duplicate evidence JSON key')
            value[key] = item
        return value
    def read_json(path):
        return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError('ADMISSION_SCOPE: nonfinite evidence JSON')))
    result, plan = read_json(summary), read_json(schedule)
    scope = ADMISSION_SCOPE.load_scope(source)
    ADMISSION_SCOPE.validate_schedule(plan, scope)
    validation = ADMISSION_SCOPE.validate_report(result, scope,
                                               schedule_sha256=before['schedule']['sha256'])
    expected_plans = {row['id']: row for row in plan['scenarios']}
    require(all(row['expected'] == expected_plans[row['id']] for row in result['scenarios']),
            'ADMISSION_SCOPE: executed case plans differ from saved schedule')
    require(before == {'summary': digest(summary), 'schedule': digest(schedule)},
            'ADMISSION_SCOPE: evidence changed during validation')
    return {'status': 'PASS', 'path': str(target), 'scope': validation,
            **before, 'result': result}


def recovery(gate, python, source, mode):
    """Exercise the finite process-crash plan in the actual source/wheel context."""
    target = gate.output / (mode + '-recovery')
    flags = ['-I'] if mode == 'installed' else []
    gate.run(mode + '-recovery', [python, '-B', *flags, '-m', 'crypto_reconciliation_lab',
             'demo-recovery', '--output', target, '--seed', '19'],
             None if mode == 'installed' else source)
    evidence = accept_recovery_evidence(source, target)
    result = evidence['result']
    origin = Path(result['environment']['import_origin']).resolve()
    package_root = Path(gate.record[mode + '_import']['origin']).resolve().parent
    require(origin.is_relative_to(package_root), 'recovery imported a different source/package')
    gate.record[mode + '_recovery'] = evidence
    gate.persist()


def execution_maintenance(gate, python, source, profile):
    """Small profiles run only the fixed repair controls; full suites already do."""
    target = gate.output / 'installed-execution-maintenance'
    gate.run('installed-execution-maintenance', [python, '-B', '-I',
             source / 'scripts/release_execution_maintenance.py', '--tests', source / 'tests',
             '--profile', profile, '--output', target])
    result = json.loads((target / 'summary.json').read_bytes())
    checked = release_helper('release_execution_maintenance').validate_result(
        result, profile, gate.record['installed_import']['origin'])
    require(result['version'] == gate.record['expected_version'], 'maintenance package version differs')
    actual = {p.relative_to(target).as_posix(): digest(p) for p in sorted(target.rglob('*'))
              if p.is_file() and p.name != 'summary.json'}
    require(actual and actual == result['evidence_files'], 'maintenance command evidence differs')
    gate.record['installed_execution_maintenance'] = {**checked, 'coverage': 'FIXED_SUBSET',
        'summary': digest(target / 'summary.json'), 'result': result}
    gate.persist()


def execution_replay(gate, python, source, mode):
    target = gate.output / (mode + '-execution-replay')
    flags = ['-I'] if mode == 'installed' else []
    cwd = gate.external if mode == 'installed' else source
    gate.run(mode + '-execution-replay', [python, '-B', *flags, '-m', 'crypto_reconciliation_lab',
             'demo-execution-replay', '--output', target], cwd)
    checked = release_helper('release_execution_replay').validate_demo(target,
        package_origin=gate.record[mode + '_import']['origin'], executable=python,
        isolated=mode == 'installed', cwd=cwd)
    gate.record[mode + '_execution_replay'] = {**checked, 'path': str(target)}
    gate.persist()


def replay_maintenance(gate, python, source):
    target = gate.output / 'installed-replay-maintenance'
    gate.run('installed-replay-maintenance', [python, '-I', '-B',
             source / 'scripts/release_replay_maintenance.py', '--tests', source / 'tests', '--output', target])
    result = json.loads((target / 'summary.json').read_bytes())
    require(result['status'] == 'PASS' and result['case_count'] == 8
            and result['package_version'] == gate.record['expected_version']
            and result['origin'] == gate.record['installed_import']['origin'], 'replay maintenance identity differs')
    gate.record['installed_replay_maintenance'] = {'status': 'PASS', 'summary': digest(target / 'summary.json'),
                                                  'result': result}
    gate.persist()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('full', 'core', 'auth-only'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--wheel', type=Path)
    parser.add_argument('--check-recovery', type=Path, help='validate existing recovery evidence through the release gate only; no build, install or application execution')
    parser.add_argument('--financial', action='store_true', help='run the 69-case/162-evaluation financial matrix exactly once; full only')
    args = parser.parse_args(argv)
    if args.check_recovery and (args.source or args.wheel or args.financial):
        parser.error('--check-recovery cannot be combined with source/wheel/financial execution')
    if bool(args.source) != bool(args.wheel):
        parser.error('--source and --wheel must be supplied together')
    if args.financial and args.profile != 'full':
        parser.error('--financial is available only with --profile full')
    gate = None
    try:
        if args.source:
            require(not args.output.resolve().is_relative_to(args.source.resolve()), 'verification output must be outside extracted source')
        gate = Verification(args.output, args.profile)
        require(sys.version_info >= (3, 12), 'Python 3.12 or newer is required')
        preflight_root = args.source.resolve() if args.source else Path(__file__).resolve().parents[1]
        file_scope, reference = preflight(preflight_root)
        gate.record['preflight'] = {'status': 'PASS', 'source': str(preflight_root),
                                    'test_scope': file_scope, 'financial_reference': FINANCIAL_SCOPE.reference_identity(),
                                    'admission_scope': ADMISSION_SCOPE.identity()}
        gate.persist()
        if args.check_recovery:
            gate.record['recovery_evidence_check'] = accept_recovery_evidence(preflight_root, args.check_recovery)
            gate.record.update(status='PASS', exit_code=0, execution_scope='RECOVERY_EVIDENCE_ONLY',
                               source_tests={'status': 'NOT_RUN'}, installed_tests={'status': 'NOT_RUN'},
                               financial_matrix={'status': 'NOT_RUN'},
                               note='Existing report completeness and internal consistency only; no application executed and no authenticity claim.')
            gate.persist()
            (gate.output / 'verification.md').write_text(
                '# Recovery evidence verification\n\nStatus: PASS. Existing report only; no build, installation, suite or matrix executed.\n',
                encoding='utf-8')
            print(json.dumps({'status': 'PASS', 'mode': 'RECOVERY_EVIDENCE_ONLY', 'report': str(gate.output / 'verification.json')}))
            return 0
        if args.source:
            source = args.source.resolve()
            wheel = args.wheel.resolve()
            gate.record['build'] = {'status': 'SUPPLIED', 'source_root': str(source), 'wheel': str(wheel),
                                    'note': 'Caller supplies extracted-sdist source and its built wheel; standalone verifier proves package byte equality.'}
        else:
            builder = Path(__file__).resolve().with_name('build_release.py')
            build_output = gate.output / 'build'
            gate.run('build', [sys.executable, '-B', '-I', builder, '--output', build_output])
            build = json.loads((build_output / 'release.json').read_text(encoding='utf-8'))
            require(build['status'] == 'PASS', 'sdist-to-wheel build failed')
            source, wheel = Path(build['source_root']).resolve(), Path(build['wheel']).resolve()
            gate.record['build'] = build
        require(source.is_dir() and wheel.is_file(), 'source tree or wheel missing')
        require(not gate.output.is_relative_to(source), 'verification output must be outside extracted source')
        metadata = tomllib.loads((source / 'pyproject.toml').read_text(encoding='utf-8'))['project']
        version = metadata['version']
        require(metadata['requires-python'] == '>=3.12', 'Requires-Python must reflect the supported dependency floor')
        gate.record.update(source=str(source), wheel={'path': str(wheel), **digest(wheel)}, wheel_members=wheel_manifest(wheel, version),
                           expected_version=version, requires_python=metadata['requires-python'])
        file_scope, reference = preflight(source)
        gate.record['source_scope'] = file_scope
        gate.record['financial_reference'] = FINANCIAL_SCOPE.reference_identity()
        environment = gate.output / 'environment'
        gate.run('create-environment', [sys.executable, '-B', '-I', '-m', 'venv', environment])
        python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        # Keep the venv executable path: resolving its symlink would discard the environment.
        install = [python, '-B', '-I', '-m', 'pip', 'install', '--disable-pip-version-check', '--no-cache-dir']
        if args.profile == 'full':
            constraints = source / 'docs/stage5/ai_constraints.txt'
            gate.run('install-wheel-ai-auth', [*install, '-c', constraints, '-c', source / 'requirements-auth.txt', str(wheel) + '[ai,auth]'])
        elif args.profile == 'auth-only':
            gate.run('install-wheel-auth', [*install, '-c', source / 'requirements-auth.txt', str(wheel) + '[auth]'])
        else:
            gate.run('install-wheel-core', [*install, '--no-deps', str(wheel)])
        installed = gate.probe('installed_import', python, source, True, version)
        if args.profile == 'core':
            validate_core_probe(installed)
            validate_auth_absent(installed)
            core_auth_denied(gate, python)
            core_provenance_denied(gate, python)
            core_execution_denied(gate, python)
        elif args.profile == 'auth-only':
            validate_core_probe(installed)
            validate_auth_pins(installed, source)
        else:
            validate_auth_pins(installed, source)
            for line in constraints.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                name, expected = line.split('==', 1)
                require(installed['dependencies'].get(name, {}).get('version') == expected, f'AI pin mismatch: {name}')
            gate.probe('source_import', python, source, False, version)
            source_tests = gate.tests('source_tests', python, source, False)
            installed_tests = gate.tests('installed_tests', python, source, True)
            require(source_tests['executed'] == installed_tests['executed'], 'source and installed test count differ')
            reproduce(gate, python, source, 'source', reference, False)
            recovery(gate, python, source, 'source')
            source_auth(gate, python, source, 'source')
            provenance(gate, python, source, 'source')
            provenance_maintenance(gate, python, source, 'source')
            execution_demo(gate, python, source, 'source', 'protected')
            execution_replay(gate, python, source, 'source')
        reproduce(gate, python, source, 'installed', reference, args.profile != 'full')
        recovery(gate, python, source, 'installed')
        execution_demo(gate, python, source, 'installed', 'legacy' if args.profile == 'core' else 'protected')
        execution_replay(gate, python, source, 'installed')
        replay_maintenance(gate, python, source)
        if args.profile != 'core':
            source_auth(gate, python, source, 'installed')
            provenance(gate, python, source, 'installed')
            provenance_maintenance(gate, python, source, 'installed')
        else:
            gate.record['installed_source_auth'] = {'status': 'NOT_RUN', 'reason': 'core has no auth dependency; refusal checked separately'}
            gate.record['installed_provenance'] = {'status': 'NOT_RUN', 'reason': 'core has no auth dependency; all new command refusals checked separately'}
            gate.record['installed_provenance_maintenance'] = {'status': 'NOT_RUN', 'reason': 'core has no auth dependency; provenance refusals checked before output'}
        if args.profile != 'full':
            execution_maintenance(gate, python, source, args.profile)
            gate.record['source_execution_maintenance'] = {'status': 'NOT_RUN', 'reason': 'source repair tests belong to full profile'}
            gate.record['source_execution'] = {'status': 'NOT_RUN', 'reason': 'source demonstration belongs to full profile'}
            gate.record['source_execution_replay'] = {'status': 'NOT_RUN', 'reason': 'source replay demonstration belongs to full profile'}
            gate.record['source_tests_execution_replay_timeout'] = gate.record['installed_tests_execution_replay_timeout'] = {
                'status': 'NOT_RUN', 'reason': 'real timeout experiment runs within the full suite only'}
            gate.record['source_tests_execution_processes'] = gate.record['installed_tests_execution_processes'] = {
                'status': 'NOT_RUN', 'reason': 'process experiments run within the full suite only'}
            gate.record['source_tests'] = gate.record['installed_tests'] = {'status': 'NOT_RUN', 'reason': 'full suite requires both optional extras'}
            gate.record['source_provenance'] = {'status': 'NOT_RUN', 'reason': 'source feature check belongs to the full profile; installed auth-only check remains separate'}
            gate.record['source_provenance_maintenance'] = {'status': 'NOT_RUN', 'reason': 'source maintenance checks belong to the full profile'}
        if args.financial:
            inputs, outputs = gate.output / 'financial-input', gate.output / 'financial-matrix'
            generated = json.loads(gate.run('financial-generate', [python, '-B', '-I', '-m', 'crypto_reconciliation_lab', 'lab-generate', '--output', inputs,
                     '--seed', '11', '--seed', '29', '--seed', '47', '--events', '100', '--investors', '6']))
            require(type(generated.get('cases')) is int and generated['cases'] == 69, 'financial matrix case count failed')
            result = json.loads(gate.run('financial-verify', [python, '-B', '-I', '-m', 'crypto_reconciliation_lab',
                                'lab-verify', '--input', inputs, '--output', outputs]))
            FINANCIAL_SCOPE.validate_matrix_result(result)
            reports = FINANCIAL_SCOPE.compare_required_reports(outputs, reference, 'matrix')
            gate.record['financial_matrix'] = {'status': 'PASS', 'cases': 69, 'evaluations': 162,
                                               'counters': result['counters'], 'reports': reports}
        else:
            gate.record['financial_matrix'] = {'status': 'NOT_RUN', 'reason': '--financial not requested; small demos still verified'}
        gate.record.update(status='PASS', exit_code=0)
        gate.persist()
        tests = gate.record.get('installed_tests', {})
        (gate.output / 'verification.md').write_text(
            f"# Release verification\n\nStatus: PASS. Profile: {args.profile}. Version: {version}.\n\n"
            f"Installed origin: `{installed['origin']}`. Python: `{installed['python']}`.\n\n"
            f"Full-suite tests: {tests.get('executed', 'NOT_RUN (non-full profile)')}; skips: {tests.get('skips', 'not applicable')}. "
            f"Financial matrix: {gate.record['financial_matrix']['status']}.\n\n"
            f"Admission recovery: {gate.record['installed_recovery']['scope']['executed_count']} fixed scenarios, observed crash barriers and negative controls PASS.\n\n"
            f"Source authentication: {gate.record['installed_source_auth']['status']}. Profile-specific dependency absence/pins are in the import probe.\n\n"
            f"Saved-run provenance: {gate.record['installed_provenance']['status']}. Run-creation authorization remains NOT_RECORDED; financial recomputation NOT_PERFORMED.\n\n"
            f"Recorded execution: {gate.record['installed_execution']['validation']['case_count']} fixed CLI cases PASS. Process evidence: {gate.record['installed_tests_execution_processes']['status']}.\n\n"
            f"Offline execution replay: {gate.record['installed_execution_replay']['case_count']} fixed CLI cases PASS; same-engine comparison only.\n\n"
            "All commands, actual exits, import origins, dependency versions, byte proofs and logs are in verification.json. "
            "No main triage generation, training, or final holdout evaluation was invoked by this gate.\n", encoding='utf-8')
        print(json.dumps({'status': 'PASS', 'profile': args.profile, 'report': str(gate.output / 'verification.json')}))
        return 0
    except Exception as error:
        if gate is not None:
            gate.record.update(status='ERROR', exit_code=1, error=str(error), traceback=traceback.format_exc())
            gate.persist()
            (gate.output / 'verification.md').write_text(f'# Release verification\n\nStatus: ERROR.\n\n{error}\n', encoding='utf-8')
        print(f'verify_release: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
