"""Bounded reports; current implementation identity is not historical identity."""
from collections import Counter
import hashlib
import platform
from pathlib import Path
import sqlite3
import sys

from .. import __version__
from ..execution.common import canonical
from .common import FORMAT, MAX_REPORT_BYTES, ReplayError


def empty_report(expected):
    return {
        'format': FORMAT, 'status': 'ERROR', 'exit_code': 2,
        'replay_state': 'NOT_EVALUATED', 'operation_state': 'ERROR',
        'reason_code': 'REPLAY_INPUT', 'message': '',
        'expected_execution_id': expected if type(expected) is str else None,
        'derived_execution_id': None, 'context_hash': None,
        'saved_raw_run_hash': None, 'saved_canonical_run_id': None,
        'recomputed_canonical_run_id': None, 'inputs': {}, 'captured_counts': {},
        'completion': dict.fromkeys(('validation', 'calculation', 'comparison'), 'NOT_COMPLETED'),
        'comparison': {'state': 'NOT_EVALUATED', 'equal': None, 'total_differences': 0,
                       'reported_differences': 0, 'truncated': False, 'differences': []},
        'financial_summary': None, 'runtime': None,
        'claims': {'original_executable_identity': 'NOT_RECORDED',
                   'source_signature_verification': 'NOT_PERFORMED',
                   'run_actor_authorization': 'NOT_DEFINED',
                   'independent_financial_algorithm': 'NOT_PERFORMED',
                   'external_database_capture_completeness': 'NOT_VERIFIED',
                   'expected_identity_trust': 'CALLER_SELECTED_PIN',
                   'verified_input_files': ['context.json', 'run.json']},
    }


def fail(report, code, message):
    report.update(status='ERROR', exit_code=2, operation_state='ERROR',
                  reason_code=code, message=str(message)[:2048])
    return report


def runtime_identity():
    names = ['engine', 'model', 'corrections', 'correction_model', 'quarantine', 'store',
             'execution.capture', 'execution.common', 'review.validation',
             'replay.api', 'replay.validation', 'replay.adapter', 'replay.comparison',
             'replay.worker', 'replay.report', 'replay.common']
    modules = {}
    for name in names:
        module = sys.modules.get('crypto_reconciliation_lab.' + name)
        if module is None and name == 'replay.worker':
            module = sys.modules.get('__main__')
        if module is None or not getattr(module, '__file__', None):
            continue
        path = Path(module.__file__).resolve()
        raw = path.read_bytes()
        modules[name] = {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    return {'package_version': __version__, 'python': platform.python_version(),
            'executable': sys.executable, 'sqlite': sqlite3.sqlite_version,
            'rule_version': 'stage2-v2', 'modules': modules,
            'identity_scope': 'THIS_REPLAY_ONLY'}


def financial_summary(payload):
    findings = payload['findings']
    fields = ('comparison', 'scope', 'asset', 'data_state', 'reconciliation_state',
              'expected', 'reported', 'difference', 'provisional')
    return {'finding_count': len(findings),
            'data_states': dict(sorted(Counter(f['data_state'] for f in findings).items())),
            'reconciliation_states': dict(sorted(Counter(f['reconciliation_state'] for f in findings).items())),
            'findings': [{k: f[k] for k in fields if k in f} for f in findings[:100]],
            'reported_findings': min(100, len(findings)), 'truncated': len(findings) > 100}


def report_bytes(report):
    raw = canonical(report)
    if len(raw) > MAX_REPORT_BYTES:
        raise ReplayError('REPLAY_LIMIT', 'serialized replay report byte limit')
    return raw


def markdown(report):
    return ('# Offline execution replay\n\n'
            + f"Status: **{report['status']}**; reason: `{report['reason_code']}`; exit: {report['exit_code']}.\n\n"
            + f"Replay: {report['replay_state']}; operation: {report['operation_state']}.\n\n"
            + 'The complete structured evidence is in `report.json`. Only the two explicit input files were checked.\n\n'
            + 'This uses the current preserved financial engine. Original executable identity: NOT_RECORDED. '
            + 'Source signatures: NOT_PERFORMED; run actor authority: NOT_DEFINED; independent financial algorithm: NOT_PERFORMED.\n\n'
            + '```json\n' + report_bytes(report).decode('ascii') + '\n```\n')
