"""Fixed admission experiment coverage; never infer required cases from a report."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

CONTRACT_PATH = 'contracts/admission-recovery-scope-v1.json'
CONTRACT_BYTES = 1210
CONTRACT_SHA256 = '64ac4582e849f2195b0d90452c5381d3e7fd882a8c0d198a697e69678c738a53'


def require(condition, message):
    if not condition:
        raise ValueError('ADMISSION_SCOPE: ' + message)


def identity():
    return {'path': CONTRACT_PATH, 'bytes': CONTRACT_BYTES, 'sha256': CONTRACT_SHA256}


def unique_object(pairs):
    result = {}
    for name, value in pairs:
        require(name not in result, 'duplicate JSON key: ' + name)
        result[name] = value
    return result


def load_scope(root):
    path = Path(root) / CONTRACT_PATH
    require(path.is_file() and not path.is_symlink(), 'fixed recovery scope is absent or unsafe')
    data = path.read_bytes()
    require(len(data) == CONTRACT_BYTES and hashlib.sha256(data).hexdigest() == CONTRACT_SHA256,
            'fixed recovery scope identity differs')
    value = json.loads(data, object_pairs_hook=unique_object)
    require(value['format'] == 'admission-recovery-scope-v1' and value['release'] == '0.7.0',
            'recovery scope format/release differs')
    ids = value['scenario_ids']
    require(type(ids) is list and len(ids) == len(set(ids)) == 21, 'required scenario roster differs')
    return value


def validate_report(report, scope, *, schedule_sha256):
    require(type(report) is dict and report.get('format') == 'admission-recovery-v1'
            and report.get('status') == 'PASS', 'recovery did not complete successfully')
    expected = scope['scenario_ids']
    for field in ('planned_scenario_ids', 'executed_scenario_ids'):
        ids = report.get(field)
        require(type(ids) is list and all(type(n) is str for n in ids)
                and len(ids) == len(set(ids)) == len(expected) and set(ids) == set(expected),
                field + ' differs from fixed recovery scope')
    require(report.get('schedule_sha256') == schedule_sha256, 'saved schedule differs from executed plan')
    scenarios = report.get('scenarios')
    require(type(scenarios) is list and len(scenarios) == len(expected)
            and all(type(row) is dict for row in scenarios), 'scenario observations missing')
    ids = [row.get('id') for row in scenarios]
    require(all(type(n) is str for n in ids) and len(set(ids)) == len(expected) and set(ids) == set(expected),
            'scenario observation identities differ')
    for row in scenarios:
        require(row.get('status') == 'PASS', 'scenario failed or incomplete: ' + row['id'])
        checks = row.get('checks')
        require(type(checks) is list and checks and all(type(c) is dict and c.get('passed') is True for c in checks),
                'scenario has missing or failed readback checks: ' + row['id'])
        processes = row.get('processes', [])
        require(type(processes) is list and all(type(p) is dict for p in processes), 'invalid process evidence')
        if row['id'] in scope['crash_barriers']:
            barrier = scope['crash_barriers'][row['id']]
            matches = [p for p in processes if p.get('barrier') == barrier and p.get('barrier_reached') is True
                       and type(p.get('exit_code')) is int and p['exit_code'] == -9
                       and p.get('sender_result') == 'UNKNOWN']
            require(matches, 'required observed SIGKILL barrier missing: ' + row['id'])
        if row['id'] in scope['writer_scenarios']:
            writers = [p for p in processes if type(p.get('pid')) is int and p.get('joined') is True
                       and type(p.get('exit_code')) is int and p['exit_code'] == 0]
            require(len({p['pid'] for p in writers}) >= 2, 'two completed independent writer processes missing')
    negative = report.get('negative_control', {})
    require(type(negative) is dict and negative.get('status') == 'EXPECTED_FAILURE', 'negative harness control missing')
    models = negative.get('models')
    require(type(models) is list and all(type(m) is dict for m in models), 'negative model evidence missing')
    require({m.get('name') for m in models} == set(scope['negative_models'])
            and len(models) == len(scope['negative_models'])
            and all(m.get('observed_status') == 'FAIL' for m in models), 'broken transport models were not rejected')
    environment = report.get('environment', {})
    require(type(environment) is dict and all(environment.get(n) for n in
            ('python', 'interpreter', 'import_origin', 'sqlite', 'platform')), 'actual recovery environment missing')
    require(environment.get('journal_mode') == 'delete' and environment.get('synchronous') == 2,
            'rollback-journal/full synchronous experiment settings differ')
    return {'status': 'PASS', 'scope_identity': identity(), 'expected_count': len(expected),
            'executed_count': len(scenarios), 'required_crash_barriers': scope['crash_barriers'],
            'negative_models_rejected': scope['negative_models'], 'schedule_sha256': schedule_sha256}
