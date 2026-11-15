"""Seven fixed TEST-ONLY offline cases with real CLI command evidence.

The caller pin is observed from a real recorded API call before export. The
protected pair is an exact genuine 0.10.1 capture, consumed without crypto.
No replay result is used to compute a financial expectation.
"""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from .. import __version__
from ..execution import export_execution, reconcile_recorded
from ..execution.common import binding, canonical
from ..execution.demo import BALANCE_AT, KNOWLEDGE_AT, CUSTODIAN, PLATFORM, build_fixture
from ..store import Store

CATALOG_IDENTITY = {'bytes': 1231, 'sha256': 'a479fae4a5c27be73d5ee8a6405e23daec16e1f04e80da34a7e2d530be7b99ca'}
CASE_IDS = ('clean', 'custody_difference', 'old_cut_offline', 'wrong_identity',
            'numeric_divergence', 'trace_divergence', 'protected_recorded')
PROTECTED_ID = 'b4ef410ef6066b2468a7049d8750aead659f7a889dd7087c006464cfe50ac0fd'
PROTECTED_INPUTS = {
    'context': {'bytes': 138090, 'sha256': 'db18fa42e2f81140172745a3a6f993221d9d4f2462dad44615044c8a0efe099e'},
    'run': {'bytes': 36958, 'sha256': '14c675e3bdb3106451c069915db22095e9cacf26c1ab9e674b64d04754738dd0'},
}


def _identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value) + b'\n')


def _require(condition, message):
    if not condition:
        raise ValueError('REPLAY_DEMO: ' + message)


def _catalog():
    raw = Path(__file__).with_name('demo_catalog_v1.json').read_bytes()
    _require(_identity(raw) == CATALOG_IDENTITY, 'fixed catalog bytes differ')
    value = json.loads(raw)
    _require(value['format'] == 'execution-replay-demo-catalog-v1'
             and tuple(row['id'] for row in value['cases']) == CASE_IDS,
             'fixed catalog inventory differs')
    return raw, value


def _literal_financial(result, *, mismatch=False):
    expected = {'ASSET_A': ({'I1': '7', 'I2': '4'}, '11'),
                'ASSET_B': ({'I1': '0.3', 'I2': '0.2'}, '0.5')}
    for asset, (balances, liability) in expected.items():
        ledger = result['ledgers'][asset]
        _require(ledger['investor_balances'] == balances and ledger['liability'] == liability,
                 'independent literal ledger differs: ' + asset)
    rows = {(f['comparison'], f['asset'], f['scope']): f for f in result['findings']}
    _require(len(rows) == 6, 'literal finding coverage differs')
    for key, finding in rows.items():
        bad = mismatch and key == ('B', 'ASSET_A', 'customer_liability')
        _require(finding['data_state'] == 'COMPLETE'
                 and finding['reconciliation_state'] == ('MISMATCH' if bad else 'MATCHED')
                 and finding['difference'] == ('1' if bad else '0'), 'literal financial status differs')


def _pair(folder, request_id, *, mismatch=False):
    fixture = build_fixture(folder / 'source', mismatch=mismatch)
    store = Store(fixture['database'])
    try:
        result = reconcile_recorded(store, BALANCE_AT, KNOWLEDGE_AT, request_id)
        _literal_financial(result['financial_result'], mismatch=mismatch)
    finally:
        store.close()
    # Observe the pin directly from the recorded call, before reading its export.
    pin = result['execution_id']
    export_execution(fixture['database'], pin, folder / 'export')
    inputs = {name: (folder / 'export' / (name + '.json')).read_bytes() for name in ('context', 'run')}
    observation = {'role': 'TEST_ONLY_RECORDED_API_RETURN', 'execution_id': pin,
                   'request_id': request_id, 'run_id': result['run_id'],
                   'pin_observed_before_export': True, 'source_database': str(fixture['database'])}
    return inputs, pin, observation, fixture['database']


def _rebound(inputs, *, kind):
    """Only two fixed sensitivity fixtures, never a general trust-from-bundle API."""
    run, context = json.loads(inputs['run']), json.loads(inputs['context'])
    if kind == 'numeric_divergence':
        run['ledgers']['ASSET_A']['liability'] = '12'
        changed_path = '/ledgers/ASSET_A/liability'
    elif kind == 'trace_divergence':
        run['ledgers']['ASSET_A']['trace'][0]['balances_after']['I1'] = '500'
        changed_path = '/ledgers/ASSET_A/trace/0/balances_after/I1'
    else:
        raise ValueError('unknown fixed sensitivity case')
    raw_run = canonical(run)
    context['run_id'] = hashlib.sha256(raw_run).hexdigest()
    context['run_payload_sha256'] = hashlib.sha256(raw_run).hexdigest()
    raw_context = canonical(context)
    pin = hashlib.sha256(canonical(binding({**context, 'context_hash': hashlib.sha256(raw_context).hexdigest()}))).hexdigest()
    _require(context['tables'] == json.loads(inputs['context'])['tables'], 'sensitivity fixture changed captured inputs')
    return {'context': raw_context, 'run': raw_run}, pin, {
        'role': 'TEST_ONLY_SELF_CONSISTENT_REBOUND_PIN_NOT_EXTERNAL_DATABASE_PROOF',
        'execution_id': pin, 'changed_saved_path': changed_path,
        'captured_tables_unchanged': True,
        'original_input_identities': {name: _identity(raw) for name, raw in inputs.items()},
    }


def _protected():
    folder = Path(__file__).with_name('fixtures')
    inputs = {name: (folder / ('protected-' + name + '.json')).read_bytes() for name in ('context', 'run')}
    _require({name: _identity(raw) for name, raw in inputs.items()} == PROTECTED_INPUTS,
             'genuine 0.10.1 protected resource differs')
    return inputs, PROTECTED_ID, {
        'role': 'TEST_ONLY_OBSERVATION_FROM_GENUINE_0.10.1_RECORDED_CALL',
        'execution_id': PROTECTED_ID, 'request_id': 'before-rotation',
        'original_package': '0.10.1', 'original_source_head': '0aa26865d5a78d6c051e1c26ad6387bdc29c8abc',
        'generation_record_sha256': 'c647e63ff43b6ccee9448d8f94990849e0a14ffbeb33840fd6c8e713921e7515',
        'pin_source': 'Independent historical capture of reconcile_recorded API return; not derived from these demo inputs',
        'auth_or_signature_reverification': 'NOT_PERFORMED',
    }


def _cli(root, case, pin, expected):
    folder = root / 'commands' / case
    folder.mkdir(parents=True, exist_ok=False)
    args = [sys.executable, '-B', *(['-I'] if sys.flags.isolated else []), '-m', 'crypto_reconciliation_lab',
            'verify-execution-replay', '--context', str(root / 'cases' / case / 'context.json'),
            '--run', str(root / 'cases' / case / 'run.json'), '--expected-execution-id', pin]
    started, tick = datetime.now(timezone.utc).isoformat(), time.monotonic()
    command = {'argv': args, 'cwd': str(Path.cwd()), 'started_at': started, 'status': 'RUNNING'}
    _write(folder / 'command.json', command)
    try:
        process = subprocess.run(args, cwd=Path.cwd(), capture_output=True, timeout=65)
    except subprocess.TimeoutExpired as error:
        (folder / 'stdout.txt').write_bytes(error.stdout or b'')
        (folder / 'stderr.txt').write_bytes(error.stderr or b'')
        command.update(status='ERROR', exit_code=None, timed_out=True,
                       finished_at=datetime.now(timezone.utc).isoformat(), seconds=time.monotonic()-tick)
        _write(folder / 'command.json', command)
        raise ValueError('REPLAY_DEMO: actual CLI did not finish') from error
    for name, raw in (('stdout', process.stdout), ('stderr', process.stderr)):
        (folder / (name + '.txt')).write_bytes(raw)
        command[name] = _identity(raw)
    command.update(status='COMPLETED', exit_code=process.returncode,
                   finished_at=datetime.now(timezone.utc).isoformat(), seconds=time.monotonic()-tick)
    _write(folder / 'command.json', command)
    result = json.loads(process.stdout)
    _write(folder / 'result.json', result)
    actual = {'id': case, 'status': result['status'], 'exit_code': process.returncode,
              'reason_code': result['reason_code'], 'comparison': result['comparison']['state']}
    _require(actual == expected and result['exit_code'] == process.returncode, 'actual result differs: ' + case)
    _require(result['claims']['original_executable_identity'] == 'NOT_RECORDED'
             and result['claims']['source_signature_verification'] == 'NOT_PERFORMED'
             and result['claims']['run_actor_authorization'] == 'NOT_DEFINED', 'replay claims changed')
    if case != 'wrong_identity':
        _require(set(result['completion'].values()) == {'COMPLETED'}, 'comparison did not complete: ' + case)
    if case in ('numeric_divergence', 'trace_divergence'):
        path = ('/ledgers/ASSET_A/liability' if case == 'numeric_divergence'
                else '/ledgers/ASSET_A/trace/0/balances_after/I1')
        _require(path in {row['path'] for row in result['comparison']['differences']}, 'semantic calculation witness missing')
    return result, command, actual


def run_demo(output):
    catalog_raw, catalog = _catalog()
    requested = Path(output).expanduser().absolute()
    _require(not os.path.lexists(requested), 'output already exists')
    destination = requested.parent.resolve() / requested.name
    _require(not os.path.lexists(destination), 'canonical output already exists')
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'catalog.json').write_bytes(catalog_raw)
    import crypto_reconciliation_lab as package
    summary = {'format': 'execution-replay-demo-v1', 'status': 'RUNNING', 'package_version': __version__,
               'catalog': CATALOG_IDENTITY, 'case_count': 0, 'cases': [],
               'environment': {'import_origin': package.__file__, 'executable': sys.executable,
                               'isolated': bool(sys.flags.isolated), 'cwd': str(Path.cwd()),
                               'optional_available': {name: importlib.util.find_spec(name) is not None
                                                      for name in ('sklearn', 'numpy', 'scipy', 'cryptography', 'cffi', 'pycparser')}},
               'claim': 'Same-engine reproduction of exactly two files bound to a caller-selected pin; not independent financial or source-auth verification'}
    _write(destination / 'summary.json', summary)
    try:
        fixtures, databases = {}, []
        with tempfile.TemporaryDirectory(prefix='execution-replay-demo-source-') as temporary:
            temporary = Path(temporary)
            for case, mismatch in (('clean', False), ('custody_difference', True)):
                inputs, pin, observation, db = _pair(temporary / case, 'replay-demo-' + case, mismatch=mismatch)
                fixtures[case] = (inputs, pin, observation)
                databases.append(str(db))
            # The old pair is captured before later knowledge changes. The
            # original inputs remain immutable while the source learns v2.
            inputs, pin, observation, db = _pair(temporary / 'old-cut', 'replay-demo-old-cut')
            store = Store(db)
            try:
                changed = {'kind': 'report', 'source': CUSTODIAN, 'platform': PLATFORM, 'asset': 'ASSET_A',
                           'stream': 'external_custody', 'scope': 'external', 'balance_at': BALANCE_AT,
                           'version': 2, 'amount': '8'}
                receipt = store.ingest(changed, '2026-11-13T02:00:00Z')
                later = reconcile_recorded(store, BALANCE_AT, '2026-11-13T02:00:00Z', 'replay-demo-later-cut')
                _literal_financial(later['financial_result'], mismatch=True)
                _require(later['run_id'] != observation['run_id'], 'later source change did not create a different saved result')
                observation = {**observation, 'later_receipt_status': receipt['status'],
                               'later_execution_id': later['execution_id'], 'later_run_id': later['run_id'],
                               'old_input_identities': {name: _identity(raw) for name, raw in inputs.items()}}
            finally:
                store.close()
            fixtures['old_cut_offline'] = (inputs, pin, observation)
            databases.append(str(db))
        # All source DBs have actually been removed before any verifier CLI.
        _require(all(not Path(name).exists() for name in databases), 'source database remains available')
        summary['source_lifecycle'] = {'created_databases': databases, 'removed_before_cli': True,
                                       'all_database_paths_absent': True, 'new_product_db_during_replay': 'NOT_CREATED'}
        clean_inputs, clean_pin, _ = fixtures['clean']
        fixtures['wrong_identity'] = (clean_inputs, '0' * 64,
                                      {'role': 'TEST_ONLY_DELIBERATELY_WRONG_EXTERNAL_PIN', 'correct_observed_id': clean_pin})
        for case in ('numeric_divergence', 'trace_divergence'):
            fixtures[case] = _rebound(clean_inputs, kind=case)
        fixtures['protected_recorded'] = _protected()
        for expected in catalog['cases']:
            case = expected['id']
            inputs, pin, observation = fixtures[case]
            folder = destination / 'cases' / case
            folder.mkdir(parents=True, exist_ok=False)
            for name, raw in inputs.items():
                (folder / (name + '.json')).write_bytes(raw)
            before = {name: _identity(raw) for name, raw in inputs.items()}
            result, command, actual = _cli(destination, case, pin, expected)
            _require(before == {name: _identity((folder / (name + '.json')).read_bytes()) for name in inputs}, 'CLI changed an input')
            row = {'id': case, 'expected': expected, 'actual': actual, 'expected_execution_id': pin,
                   'pin_observation': observation, 'inputs': before, 'inputs_unchanged': True,
                   'command': 'commands/' + case + '/command.json', 'result': 'commands/' + case + '/result.json',
                   'command_identity': _identity(canonical(command) + b'\n'),
                   'result_identity': _identity(canonical(result) + b'\n'), 'passed': True}
            summary['cases'].append(row)
            summary['case_count'] = len(summary['cases'])
            _write(destination / 'summary.json', summary)
        _require(tuple(row['id'] for row in summary['cases']) == CASE_IDS, 'demonstration inventory incomplete')
        summary['status'] = 'PASS'
    except Exception as error:
        summary.update(status='ERROR', error=str(error))
    _write(destination / 'summary.json', summary)
    rows = '\n'.join('| ' + row['id'] + ' | ' + row['actual']['status'] + ' | ' + str(row['actual']['exit_code'])
                     + ' | ' + row['actual']['reason_code'] + ' |' for row in summary['cases'])
    (destination / 'summary.md').write_text(
        '# Offline execution replay demo\n\nStatus: **' + summary['status'] + '**.\n\n'
        '| Fixed case | Replay result | Actual CLI exit | Reason |\n|---|---|---:|---|\n' + rows
        + '\n\nThe genuine custody difference remains +1 while its replay succeeds. The old cut is checked after the test source databases are removed. '
        'Protected input is an exact 0.10.1 capture, consumed without crypto operations. Numeric and trace sensitivity fixtures use new TEST-ONLY pins; '
        'they demonstrate a full comparison after consistent hash checks. Only context.json and run.json are authoritative inputs. '
        'Original executable identity is NOT_RECORDED; independent mathematics, signatures and institutional authority are not verified.\n', encoding='utf-8')
    return summary
