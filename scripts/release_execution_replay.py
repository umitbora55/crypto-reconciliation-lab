"""Release-owned, fixed seven-case replay coverage; never a financial calculator."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

CATALOG = {'bytes': 1231, 'sha256': 'a479fae4a5c27be73d5ee8a6405e23daec16e1f04e80da34a7e2d530be7b99ca'}
CASES = {
    'clean': (0, 'REPRODUCED', 'REPLAY_REPRODUCED', 'EQUAL'),
    'custody_difference': (0, 'REPRODUCED', 'REPLAY_REPRODUCED', 'EQUAL'),
    'old_cut_offline': (0, 'REPRODUCED', 'REPLAY_REPRODUCED', 'EQUAL'),
    'wrong_identity': (2, 'ERROR', 'REPLAY_INTEGRITY', 'NOT_EVALUATED'),
    'numeric_divergence': (1, 'DIVERGED', 'REPLAY_DIVERGED', 'DIFFERENT'),
    'trace_divergence': (1, 'DIVERGED', 'REPLAY_DIVERGED', 'DIFFERENT'),
    'protected_recorded': (0, 'REPRODUCED', 'REPLAY_REPRODUCED', 'EQUAL'),
}
PROTECTED_ID = 'b4ef410ef6066b2468a7049d8750aead659f7a889dd7087c006464cfe50ac0fd'
PROTECTED_INPUTS = {
    'context': {'bytes': 138090, 'sha256': 'db18fa42e2f81140172745a3a6f993221d9d4f2462dad44615044c8a0efe099e'},
    'run': {'bytes': 36958, 'sha256': '14c675e3bdb3106451c069915db22095e9cacf26c1ab9e674b64d04754738dd0'},
}
CLAIMS = {
    'expected_identity_trust': 'CALLER_SELECTED_PIN',
    'external_database_capture_completeness': 'NOT_VERIFIED',
    'independent_financial_algorithm': 'NOT_PERFORMED',
    'original_executable_identity': 'NOT_RECORDED',
    'run_actor_authorization': 'NOT_DEFINED',
    'source_signature_verification': 'NOT_PERFORMED',
    'verified_input_files': ['context.json', 'run.json'],
}
MODULES = ('engine', 'model', 'corrections', 'correction_model', 'quarantine', 'store',
           'execution.capture', 'execution.common', 'review.validation', 'replay.api',
           'replay.adapter', 'replay.worker', 'replay.common', 'replay.comparison', 'replay.report', 'replay.validation')


def require(value, message):
    if not value:
        raise ValueError('REPLAY_COVERAGE: ' + message)


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def member(root, name):
    relative = Path(name)
    target = root / relative
    require(not relative.is_absolute() and '..' not in relative.parts
            and target.is_file() and not target.is_symlink()
            and target.resolve().is_relative_to(root.resolve()), 'missing or unsafe member: ' + name)
    raw = target.read_bytes()
    require(len(raw) <= 32 * 1024 * 1024, 'oversized member: ' + name)
    return raw


def parsed(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('REPLAY_COVERAGE: nonfinite JSON')))


def financial(summary, *, mismatch):
    rows = summary.get('findings', [])
    require(summary.get('finding_count') == 6 and summary.get('reported_findings') == 6
            and summary.get('truncated') is False and len(rows) == 6, 'literal financial coverage differs')
    wanted = {
        ('A', 'ASSET_A', 'I1'): ('7', '7', '0', 'MATCHED'),
        ('A', 'ASSET_A', 'I2'): ('4', '4', '0', 'MATCHED'),
        ('B', 'ASSET_A', 'customer_liability'): ('11', '11', '0', 'MATCHED'),
        ('A', 'ASSET_B', 'I1'): ('0.3', '0.3', '0', 'MATCHED'),
        ('A', 'ASSET_B', 'I2'): ('0.2', '0.2', '0', 'MATCHED'),
        ('B', 'ASSET_B', 'customer_liability'): ('0.5', '0.5', '0', 'MATCHED'),
    }
    if mismatch:
        wanted[('B', 'ASSET_A', 'customer_liability')] = ('11', '10', '1', 'MISMATCH')
    actual = {(row['comparison'], row['asset'], row['scope']):
              (row['expected'], row['reported'], row['difference'], row['reconciliation_state']) for row in rows}
    require(actual == wanted and all(row['data_state'] == 'COMPLETE' for row in rows),
            'independent literal amounts or states differ')


def validate_demo(root, *, package_origin, executable, isolated, cwd):
    root = Path(root).resolve()
    summary_raw, catalog_raw = member(root, 'summary.json'), member(root, 'catalog.json')
    summary, catalog = parsed(summary_raw), parsed(catalog_raw)
    require(identity(catalog_raw) == CATALOG and summary.get('catalog') == CATALOG,
            'fixed catalog identity differs')
    expected_catalog = [{'id': name, 'exit_code': values[0], 'status': values[1],
                         'reason_code': values[2], 'comparison': values[3]} for name, values in CASES.items()]
    require(catalog == {'format': 'execution-replay-demo-catalog-v1', 'cases': expected_catalog},
            'fixed catalog contents differ')
    require(summary.get('format') == 'execution-replay-demo-v1' and summary.get('status') == 'PASS'
            and summary.get('package_version') == '0.11.0' and summary.get('case_count') == 7,
            'demonstration did not complete all seven cases')
    rows = summary.get('cases')
    require(type(rows) is list and len(rows) == 7
            and tuple(row.get('id') for row in rows) == tuple(CASES), 'fixed case inventory differs')
    environment = summary['environment']
    require(environment['import_origin'] == str(package_origin) and environment['executable'] == str(executable)
            and environment['isolated'] is isolated and Path(environment['cwd']).resolve() == Path(cwd).resolve(),
            'demo interpreter, import origin or isolation differs')
    lifecycle = summary.get('source_lifecycle', {})
    databases = lifecycle.get('created_databases', [])
    require(len(databases) == 3 and len(set(databases)) == 3
            and lifecycle.get('removed_before_cli') is True and lifecycle.get('all_database_paths_absent') is True
            and lifecycle.get('new_product_db_during_replay') == 'NOT_CREATED'
            and all(not Path(path).exists() for path in databases), 'test source database remains available')
    package = Path(package_origin).resolve().parent
    controls, contexts = {}, {}
    for row, expected in zip(rows, expected_catalog):
        name = row['id']
        require(row.get('actual') == expected and row.get('passed') is True
                and row.get('inputs_unchanged') is True, 'actual fixed result differs: ' + name)
        command_name, result_name = 'commands/' + name + '/command.json', 'commands/' + name + '/result.json'
        require(row.get('command') == command_name and row.get('result') == result_name,
                'command/result member coverage differs: ' + name)
        command_raw, result_raw = member(root, command_name), member(root, result_name)
        command, result = parsed(command_raw), parsed(result_raw)
        require(row.get('command_identity') == identity(command_raw)
                and row.get('result_identity') == identity(result_raw), 'command/result identity differs: ' + name)
        pin = row.get('expected_execution_id')
        args = [str(executable), '-B', *(['-I'] if isolated else []), '-m', 'crypto_reconciliation_lab',
                'verify-execution-replay', '--context', str(root / 'cases' / name / 'context.json'),
                '--run', str(root / 'cases' / name / 'run.json'), '--expected-execution-id', pin]
        require(command.get('argv') == args and Path(command['cwd']).resolve() == Path(cwd).resolve()
                and command.get('status') == 'COMPLETED' and type(command.get('exit_code')) is int
                and command['exit_code'] == expected['exit_code']
                and isinstance(command.get('started_at'), str) and isinstance(command.get('finished_at'), str),
                'actual CLI command or exit differs: ' + name)
        for stream in ('stdout', 'stderr'):
            raw = member(root, 'commands/' + name + '/' + stream + '.txt')
            require(command.get(stream) == identity(raw), 'actual CLI log identity differs: ' + name)
            if stream == 'stdout':
                require(parsed(raw) == result, 'CLI stdout/result differs: ' + name)
        raw_inputs = {part: member(root, 'cases/' + name + '/' + part + '.json') for part in ('context', 'run')}
        inputs = {part: identity(raw) for part, raw in raw_inputs.items()}
        require(row.get('inputs') == inputs and result.get('inputs') == inputs, 'actual input identity differs: ' + name)
        contexts[name] = parsed(raw_inputs['context'])
        require(result.get('format') == 'execution-replay-report-v1' and result.get('claims') == CLAIMS
                and result.get('expected_execution_id') == pin
                and (result.get('exit_code'), result.get('status'), result.get('reason_code'),
                     result.get('comparison', {}).get('state')) == CASES[name], 'report result or claims differ: ' + name)
        runtime = result['runtime']
        require(runtime.get('package_version') == '0.11.0' and runtime.get('rule_version') == 'stage2-v2'
                and runtime.get('executable') == str(executable) and runtime.get('identity_scope') == 'THIS_REPLAY_ONLY'
                and set(runtime.get('modules', {})) == set(MODULES), 'replay runtime coverage differs')
        for module, item in runtime['modules'].items():
            path = package.joinpath(*module.split('.')).with_suffix('.py')
            require(item == {'path': str(path), **identity(path.read_bytes())}, 'replay module identity differs: ' + module)
        if name == 'wrong_identity':
            require(pin == '0' * 64 and result['completion'] == dict.fromkeys(
                ('validation', 'calculation', 'comparison'), 'NOT_COMPLETED')
                and result['financial_summary'] is None and result['recomputed_canonical_run_id'] is None,
                'wrong identity reached calculation')
        else:
            require(result['completion'] == dict.fromkeys(('validation', 'calculation', 'comparison'), 'COMPLETED')
                    and result['derived_execution_id'] == pin and result['context_hash'] == inputs['context']['sha256']
                    and result['saved_raw_run_hash'] == inputs['run']['sha256'], 'hash-valid calculation did not complete')
            financial(result['financial_summary']['saved'], mismatch=name == 'custody_difference')
            financial(result['financial_summary']['recomputed'], mismatch=name == 'custody_difference')
            comparison = result['comparison']
            if expected['exit_code'] == 0:
                require(result['saved_canonical_run_id'] == result['recomputed_canonical_run_id']
                        and comparison['equal'] is True and comparison['total_differences'] == 0
                        and comparison['differences'] == [], 'equal replay has comparison differences')
            else:
                pointer = ('/ledgers/ASSET_A/liability' if name == 'numeric_divergence'
                           else '/ledgers/ASSET_A/trace/0/balances_after/I1')
                require(result['saved_canonical_run_id'] != result['recomputed_canonical_run_id']
                        and comparison['equal'] is False and comparison['total_differences'] >= 1
                        and pointer in {item['path'] for item in comparison['differences']},
                        'hash-valid semantic comparison witness missing')
                require(row['pin_observation']['role'] == 'TEST_ONLY_SELF_CONSISTENT_REBOUND_PIN_NOT_EXTERNAL_DATABASE_PROOF',
                        'sensitivity pin overclaims external trust')
        controls[name] = {'actual': expected, 'command': identity(command_raw), 'result': identity(result_raw), 'inputs': inputs}
    require(contexts['numeric_divergence']['tables'] == contexts['trace_divergence']['tables'] == contexts['clean']['tables'],
            'sensitivity fixture changed captured database inputs')
    protected = rows[-1]
    require(protected['expected_execution_id'] == PROTECTED_ID and protected['inputs'] == PROTECTED_INPUTS
            and contexts['protected_recorded']['claims']['admission_mode'] == 'PROTECTED', 'genuine protected historical pair differs')
    old = next(row for row in rows if row['id'] == 'old_cut_offline')['pin_observation']
    require(old['later_run_id'] != old['run_id'] and old['later_execution_id'] != old['execution_id'],
            'old cut lacks the later changed source observation')
    return {'status': 'PASS', 'case_count': 7, 'case_ids': list(CASES), 'controls': controls,
            'catalog': CATALOG, 'summary': identity(summary_raw), 'package_origin': str(package_origin),
            'source_databases_absent': True, 'protected_fixture_original_package': '0.10.1',
            'expected_results_source': 'release-owned fixed catalog and independent literal findings', 'claims': CLAIMS}


def validate_timeout(root, *, executable, isolated):
    root = Path(root)
    path = 'test_real_blocked_child_hits_deadline_is_killed_and_reaped/observation.json'
    raw = member(root, path)
    row = parsed(raw)
    require(row['interpreter'] == str(executable) and row['isolated'] is isolated
            and row['returncode'] == -9 and type(row['child']['pid']) is int and row['child']['pid'] > 0
            and row['result']['status'] == 'ERROR' and row['result']['exit_code'] == 2
            and row['child']['mode'] == 'hang' and row['result']['reason_code'] == 'REPLAY_TIMEOUT'
            and row['result']['completion']['calculation'] == 'NOT_COMPLETED', 'real timeout child was not killed and reaped')
    return {'status': 'PASS', 'test_id': 'test_execution_replay_process.ExecutionReplayProcessTests.test_real_blocked_child_hits_deadline_is_killed_and_reaped',
            'path': str(root / path), **identity(raw), 'child': row['child'], 'returncode': -9,
            'duration_seconds': row['duration_seconds'], 'reason_code': 'REPLAY_TIMEOUT'}
