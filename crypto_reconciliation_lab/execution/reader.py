"""Read stored observations without capture, migration or financial evaluation."""
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3

from ..migrations import validate_schema
from ..model import config_validate, digest, timestamp
from ..review.adapter import _parity
from ..review.publication import new_output_directory
from ..review.validation import validate_payload
from . import capture
from .common import (ExecutionError, FORMAT, PROFILE, MAX_REQUEST_BYTES, MAX_RUN_BYTES,
                     binding, canonical, is_digest, parse, require, sha256)


def read_run(db, run_id):
    header = db.execute('SELECT typeof(payload),length(CAST(payload AS BLOB)),balance_at,knowledge_at FROM runs WHERE id=?', (run_id,)).fetchone()
    require(header is not None, 'referenced financial run is absent')
    require(header[0] == 'text' and 0 < header[1] <= MAX_RUN_BYTES, 'saved run byte limit', 'EXECUTION_LIMIT')
    raw = bytes(db.execute('SELECT CAST(payload AS BLOB) FROM runs WHERE id=?', (run_id,)).fetchone()[0])
    run = validate_payload(raw.decode('utf-8'), run_id, db.execute('PRAGMA user_version').fetchone()[0])
    require(tuple(header[2:]) == (run['balance_at'], run['knowledge_at']), 'run time columns differ')
    # The old review adapter deliberately has a larger budget. Enforce this
    # feature's tighter limits before it fetches or parses any mirror payload.
    mirror_count = 0
    for table in ('findings', 'evidence'):
        key = 'ordinal' if table == 'findings' else 'evidence_id'
        headers = db.execute('SELECT typeof(payload),length(CAST(payload AS BLOB)),typeof(' + key
                             + '),length(CAST(' + key + ' AS BLOB)) FROM ' + table
                             + ' WHERE run_id=? LIMIT ?', (run_id, capture.MAX_ROWS + 1))
        for kind, size, key_kind, key_size in headers:
            mirror_count += 1
            require(mirror_count <= capture.MAX_ROWS and kind == 'text'
                    and 0 < size <= capture.MAX_VALUE_BYTES
                    and key_kind == ('integer' if table == 'findings' else 'text')
                    and 0 < key_size <= capture.MAX_VALUE_BYTES, 'financial mirror value/row limit', 'EXECUTION_LIMIT')
    _parity(db, {'findings', 'evidence'}, run_id, run, raw.decode('utf-8'))
    # Exact correction mirrors are required even when the expected set is empty.
    rows = capture.Rows(db)
    groups = rows.read('correction_groups', 'group_id correction_record_id target_record_id payload', 'run_id=?', (run_id,), 'group_id')
    expected = {g['id']: g for ledger in run['ledgers'].values() for g in ledger.get('correction_groups', [])}
    require({r['group_id'] for r in groups} == set(expected), 'correction group coverage differs')
    for row in groups:
        group = expected[row['group_id']]
        require(parse(row['payload'].encode(), capture.MAX_VALUE_BYTES) == group and row['correction_record_id'] == group['correction_record_id']
                and row['target_record_id'] == group['target_record_id'], 'correction group differs')
    effects = rows.read('correction_effects', 'group_id ordinal payload', 'run_id=?', (run_id,), 'group_id,ordinal')
    actual = [(r['group_id'], r['ordinal'], parse(r['payload'].encode(), capture.MAX_VALUE_BYTES)) for r in effects]
    desired = [(gid, i, e) for gid, group in sorted(expected.items()) for i, e in enumerate(group['effects'])]
    require(actual == desired, 'correction effect coverage differs')
    return raw, run


def validate_registry(db):
    require(db.execute('SELECT 1 FROM execution_contexts c LEFT JOIN recorded_executions e ON c.context_hash=e.context_hash WHERE e.execution_id IS NULL LIMIT 1').fetchone() is None,
            'orphan context has no execution/request binding')
    require(db.execute('SELECT 1 FROM recorded_executions e LEFT JOIN execution_contexts c ON c.context_hash=e.context_hash LEFT JOIN runs r ON r.id=e.run_id WHERE c.context_hash IS NULL OR r.id IS NULL LIMIT 1').fetchone() is None,
            'execution has a missing context or financial run')


def load_execution(db, execution_id, *, replayed=False):
    require(is_digest(execution_id), 'exact execution digest required', 'EXECUTION_INPUT')
    validate_registry(db)
    header = db.execute('SELECT typeof(request_payload),length(request_payload) FROM recorded_executions WHERE execution_id=?', (execution_id,)).fetchone()
    require(header is not None, 'unknown execution', 'EXECUTION_NOT_FOUND')
    require(header[0] == 'blob' and 0 < header[1] <= MAX_REQUEST_BYTES, 'invalid stored request size', 'EXECUTION_LIMIT')
    row = dict(db.execute('SELECT * FROM recorded_executions WHERE execution_id=?', (execution_id,)).fetchone())
    request = parse(row['request_payload'], MAX_REQUEST_BYTES)
    require(canonical(request) == row['request_payload'] and sha256(row['request_payload']) == row['request_fingerprint'], 'request fingerprint differs')
    require(sha256(canonical(binding(row))) == execution_id, 'execution binding identity differs')
    header = db.execute('SELECT format,typeof(payload),length(payload) FROM execution_contexts WHERE context_hash=?', (row['context_hash'],)).fetchone()
    require(header is not None and header[0] == FORMAT, 'missing or unsupported context')
    require(header[1] == 'blob' and 0 < header[2] <= capture.MAX_CONTEXT_BYTES, 'context byte limit', 'EXECUTION_LIMIT')
    raw_context = db.execute('SELECT payload FROM execution_contexts WHERE context_hash=?', (row['context_hash'],)).fetchone()[0]
    context = parse(raw_context, capture.MAX_CONTEXT_BYTES)
    require(canonical(context) == raw_context and sha256(raw_context) == row['context_hash'], 'context byte identity differs')
    raw_run, run = read_run(db, row['run_id'])
    require(sha256(raw_run) == row['run_payload_sha256'], 'raw saved financial payload differs')
    fields = {'format', 'schema_version', 'request_id', 'request', 'request_fingerprint', 'configuration', 'run_id',
              'run_payload_sha256', 'scope', 'binary_encoding', 'tables', 'selected_evidence', 'counts',
              'observed_policy_head', 'acceptance_epochs', 'claims'}
    require(type(context) is dict and set(context) == fields, 'context field coverage differs')
    require(context['format'] == FORMAT and context['schema_version'] == 6 and context['binary_encoding'] == 'hex', 'unsupported context format')
    for key in ('request_id', 'request_fingerprint', 'run_id', 'run_payload_sha256'):
        require(context[key] == row[key], 'context binding differs: ' + key)
    require(context['request'] == request and context['scope'] == capture.SCOPE, 'context request or scope differs')
    expected_request = {'format': FORMAT, 'db_scope': 'local-request-registry', 'balance_at': run['balance_at'],
                        'knowledge_at': run['knowledge_at'], 'configuration_digest': digest(run['configuration']),
                        'rule_version': run['rule_version'], 'profile': PROFILE}
    require(request == expected_request, 'request semantics differ from saved financial run')
    require(context['configuration'] == run['configuration'] == config_validate(context['configuration']), 'context configuration differs')
    capture.validate_inventory(context['tables'], context['configuration'], request['knowledge_at'])
    tables = context['tables']
    require(context['counts'] == {name: len(values) for name, values in tables.items()}, 'inventory counts differ')
    require(context['selected_evidence'] == capture.evidence_mapping(tables, run), 'selected evidence mapping differs')
    require(context['observed_policy_head'] == (tables['auth_policy_activations'][-1] if tables['auth_policy_activations'] else None), 'observed policy head differs')
    require(context['acceptance_epochs'] == capture.original_acceptance_epochs(tables), 'original acceptance epoch coverage differs')
    require(context['claims'] == capture.claims(tables), 'unsupported observation claims')
    result = {'status': 'RECORDED', 'replayed': replayed, **{key: row[key] for key in (
        'request_id', 'execution_id', 'run_id', 'context_hash', 'run_payload_sha256')},
        'request': request, 'context': context, 'financial_result': {'run_id': row['run_id'], **run}}
    return result, raw_context, raw_run


@contextmanager
def readonly(path):
    path = Path(path).absolute()
    require(path.is_file() and not path.is_symlink(), 'existing regular database required', 'EXECUTION_INPUT')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, isolation_level=None, timeout=0.25)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        version = db.execute('PRAGMA user_version').fetchone()[0]
        require(version in (5, 6), 'only schema 5/6 reads are supported', 'EXECUTION_SCHEMA')
        validate_schema(db, version)
        yield db, version
    finally:
        db.close()


def _convert(exc):
    if isinstance(exc, ExecutionError):
        return exc
    return ExecutionError('EXECUTION_INTEGRITY', str(exc))


def read_execution(db_path, execution_id=None, *, run_id=None):
    try:
        require((execution_id is None) != (run_id is None), 'select exactly one execution or run', 'EXECUTION_INPUT')
        with readonly(db_path) as (db, version):
            if execution_id is not None:
                require(version == 6, 'recorded execution requires schema 6', 'EXECUTION_SCHEMA')
                return load_execution(db, execution_id)[0]
            require(is_digest(run_id), 'exact run digest required', 'EXECUTION_INPUT')
            _, run = read_run(db, run_id)
            ids = []
            if version == 6:
                validate_registry(db)
                for row in db.execute('SELECT execution_id FROM recorded_executions WHERE run_id=? ORDER BY execution_id LIMIT ?', (run_id, capture.MAX_ROWS + 1)):
                    ids.append(row[0])
                require(len(ids) <= capture.MAX_ROWS, 'execution lookup limit', 'EXECUTION_LIMIT')
            if len(ids) == 1:
                return load_execution(db, ids[0])[0]
            return {'status': 'MULTIPLE_EXECUTIONS' if ids else 'NOT_RECORDED', 'run_id': run_id,
                    'execution_ids': ids, 'financial_result': {'run_id': run_id, **run},
                    'run_creation_authorization_cut': 'NOT_RECORDED'}
    except (ValueError, TypeError, KeyError, sqlite3.Error, OSError, RecursionError) as exc:
        raise _convert(exc) from exc


def export_execution(db_path, execution_id, output):
    try:
        requested, database = Path(output).absolute(), Path(db_path).absolute()
        require(not os.path.lexists(requested), 'output exists', 'EXECUTION_OUTPUT')
        # Resolve parents before publication can mkdir a skipped '..' component;
        # inspect the final name before resolving a dangling destination link.
        destination = requested.parent.resolve() / requested.name
        require(not os.path.lexists(destination), 'output exists', 'EXECUTION_OUTPUT')
        destination = destination.resolve()
        require(not os.path.lexists(destination), 'output exists', 'EXECUTION_OUTPUT')
        protected = [database, *(Path(str(database) + suffix) for suffix in ('-wal', '-shm', '-journal'))]
        require(not any(destination.is_relative_to(p.resolve()) for p in protected), 'output overlaps database namespace', 'EXECUTION_OUTPUT')
        with readonly(database) as (db, version):
            require(version == 6, 'recorded execution requires schema 6', 'EXECUTION_SCHEMA')
            result, raw_context, raw_run = load_execution(db, execution_id)
        summary = {key: result[key] for key in ('status', 'request_id', 'execution_id', 'run_id', 'context_hash', 'run_payload_sha256', 'request')}
        summary.update({key: result['context'][key] for key in ('counts', 'observed_policy_head', 'acceptance_epochs', 'claims', 'selected_evidence')})
        summary['financial_states'] = [{k: f[k] for k in ('comparison', 'asset', 'scope', 'data_state', 'reconciliation_state')} for f in result['financial_result']['findings']]
        markdown = '# Recorded execution\n\nThis is a saved local observation, not independent source-signature verification or run-actor authorization.\n\n'
        markdown += '\n'.join('- **' + key + '**: `' + str(summary[key]) + '`' for key in ('request_id', 'execution_id', 'run_id', 'context_hash', 'run_payload_sha256'))
        markdown += '\n\n```json\n' + canonical(summary).decode() + '\n```\n'
        members = {'context.json': raw_context, 'run.json': raw_run, 'execution.json': canonical(result),
                   'summary.json': canonical(summary), 'summary.md': markdown.encode()}
        with new_output_directory(destination) as staging:
            for name, data in members.items():
                (staging / name).write_bytes(data)
        return {'status': 'EXPORTED', 'execution_id': execution_id, 'output': str(destination),
                'files': {name: {'bytes': len(raw), 'sha256': sha256(raw)} for name, raw in members.items()}}
    except (ValueError, TypeError, KeyError, sqlite3.Error, OSError, RecursionError) as exc:
        raise _convert(exc) from exc
