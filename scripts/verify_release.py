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
    optional_imported=[name for name in ('sklearn','numpy','scipy') if name in sys.modules],
    optional_available={name:importlib.util.find_spec(name) is not None for name in ('sklearn','numpy','scipy')},
    dependencies={d.metadata['Name']: {'version':d.version,'requires_python':d.metadata.get('Requires-Python')}
                  for d in metadata.distributions()}), sort_keys=True))
'''

TEST_RUNNER = r'''
import importlib.util, json, pathlib, sys, unittest
import crypto_reconciliation_lab as package
report = pathlib.Path(sys.argv[2])
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
        require(result['rule'] == 'stage2-v2' and result['schema'] == 4, 'financial rule/schema changed')
        require(result['review_format'] == 'review-bundle-v1' and result['experiment_format'] == 'triage-experiment-v1'
                and result['feature_format'] == 'triage-features-v1', 'saved review/triage v1 format changed')
        require(result['contract_sha256'] == 'd532627546c49a582397fcb700ad723269fafe45ac25af7f162eded5f85d7428',
                'frozen Stage 5 experiment contract changed')
        require(not result['optional_imported'], 'package import eagerly loaded optional AI dependencies')
        self.record[name] = result
        self.persist()
        return result

    def tests(self, name, python, source, installed):
        flags = ['-I'] if installed else []
        target = self.output / (name + '.json')
        self.run(name, [python, '-B', *flags, '-c', TEST_RUNNER, source / 'tests', target], None if installed else source)
        result = json.loads(target.read_text(encoding='utf-8'))
        validate_tests(result, TEST_SCOPE.load_test_scope(source))
        self.record[name] = result
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


def wheel_manifest(wheel, version='0.7.0'):
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
                require(PurePosixPath(name).suffix in ('.py', '.html', '.css', '.js'), 'wheel contains unexpected package data')
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


def recovery(gate, python, source, mode):
    """Exercise the finite process-crash plan in the actual source/wheel context."""
    target = gate.output / (mode + '-recovery')
    flags = ['-I'] if mode == 'installed' else []
    gate.run(mode + '-recovery', [python, '-B', *flags, '-m', 'crypto_reconciliation_lab',
             'demo-recovery', '--output', target, '--seed', '19'],
             None if mode == 'installed' else source)
    summary = target / 'delivery-summary.json'
    schedule = target / 'schedule.json'
    result = json.loads(summary.read_text(encoding='utf-8'))
    validation = ADMISSION_SCOPE.validate_report(result, ADMISSION_SCOPE.load_scope(source),
                                               schedule_sha256=digest(schedule)['sha256'])
    origin = Path(result['environment']['import_origin']).resolve()
    package_root = Path(gate.record[mode + '_import']['origin']).resolve().parent
    require(origin.is_relative_to(package_root), 'recovery imported a different source/package')
    gate.record[mode + '_recovery'] = {'status': 'PASS', 'path': str(target), 'scope': validation,
                                     'summary': digest(summary), 'schedule': digest(schedule), 'result': result}
    gate.persist()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('full', 'core'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--wheel', type=Path)
    parser.add_argument('--financial', action='store_true', help='run the 69-case/162-evaluation financial matrix exactly once; full only')
    args = parser.parse_args(argv)
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
            gate.run('install-wheel-ai', [*install, '-c', constraints, str(wheel) + '[ai]'])
        else:
            gate.run('install-wheel-core', [*install, '--no-deps', str(wheel)])
        installed = gate.probe('installed_import', python, source, True, version)
        if args.profile == 'core':
            validate_core_probe(installed)
        else:
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
        reproduce(gate, python, source, 'installed', reference, args.profile == 'core')
        recovery(gate, python, source, 'installed')
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
            f"Full-suite tests: {tests.get('executed', 'NOT_RUN (core profile)')}; skips: {tests.get('skips', 'not applicable')}. "
            f"Financial matrix: {gate.record['financial_matrix']['status']}.\n\n"
            f"Admission recovery: {gate.record['installed_recovery']['scope']['executed_count']} fixed scenarios, observed crash barriers and negative controls PASS.\n\n"
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
