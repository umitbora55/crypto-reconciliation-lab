"""Small predeclared process-crash experiment, not a production fault simulator."""
import base64
from collections import Counter
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import selectors
import signal
import sqlite3
import subprocess
import sys
import time

from ..demo import fixtures, BALANCE_AT, KNOWLEDGE_AT
from ..correction_demo import correction_fixtures, T3
from ..engine import reconcile
from ..store import Store
from .feed import snapshot_feed, ingest_feed
from .scope import load_scope, validate_plan, validate_schedule, validate_case, validate_report
from .oracle import check, observed, delivery_checks, financial_checks, negative_control, record_inventory_checks

SCENARIO_IDS = (
    'clean', 'custody_difference', 'transport_replay', 'economic_duplicate',
    'economic_conflict', 'transport_conflict', 'gap_recovery', 'invalid_payload',
    'crash_after_record', 'crash_after_receipt', 'crash_after_disposition', 'lost_ack',
    'ack_restart', 'writers_same_stream', 'writers_separate_stream', 'busy_retry',
    'save_run_crash', 'changed_prefix', 'truncated_file', 'new_receipt_economic_parity',
    'rejected_json')
BARRIERS = {'crash_after_record': 'ingest_before_receipt',
            'crash_after_receipt': 'delivery_after_receipt',
            'crash_after_disposition': 'delivery_before_commit',
            'lost_ack': 'delivery_after_commit', 'save_run_crash': 'save_before_commit'}
PROCESS_TIMEOUT_SECONDS = 15
BUSY_TIMEOUT_MS = 100
RETRY_BUDGET = 2
_WRITER_OBSERVATIONS = []


def _writer(store, operation):
    observation = {"pid": os.getpid(), "operation": operation,
        "journal_mode": store.db.execute("PRAGMA journal_mode").fetchone()[0],
        "synchronous": store.db.execute("PRAGMA synchronous").fetchone()[0],
        "busy_timeout_ms": store.db.execute("PRAGMA busy_timeout").fetchone()[0]}
    _WRITER_OBSERVATIONS.append(observation)


def _phase(checks, name):
    return [{**c, "name": name + ":" + c["name"]} for c in checks]


def _state_proof(actual):
    def proof(rows):
        def safe(v):
            if isinstance(v, bytes): return {"bytes": len(v), "sha256": hashlib.sha256(v).hexdigest()}
            if isinstance(v, dict): return {k:safe(x) for k,x in v.items()}
            if isinstance(v, (tuple,list)): return [safe(x) for x in v]
            return v
        data = json.dumps(safe(rows), sort_keys=True, separators=(",", ":")).encode()
        return {"rows":len(rows),"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()}
    return {"core_tables":{k:proof(actual[k]) for k in ("streams","effects","attempts","receipts","records")},
            "run_tables":{k:proof(rows) for k,rows in actual["run_tables"].items()},
            "run_payload_hashes":{k:hashlib.sha256(v.encode()).hexdigest() for k,v in actual["runs"].items()}}


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False) + '\n').encode()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n')


def input_bytes(rows):
    return tuple(encoded(r) for r in rows)


def _initialize(path, config):
    store = Store(path, config)
    _writer(store, "initialize")
    store.close()


def _reopen(path):
    # Opening a writer-capable connection lets SQLite recover a hot rollback journal.
    # Initialization/migration happened before any fault was enabled.
    store = Store(path)
    store.close()


def _feed(path, input_path, stream='feed'):
    store = Store(path)
    try:
        _writer(store, "feed")
        return ingest_feed(store, input_path, stream, busy_timeout_ms=BUSY_TIMEOUT_MS)
    finally:
        store.close()


def _delivery(path, stream, sequence, payload, plan, *, timeout=BUSY_TIMEOUT_MS):
    store = Store(path)
    try:
        _writer(store, "delivery")
        return store.ingest_delivery(stream, sequence, payload, plan, busy_timeout_ms=timeout)
    finally:
        store.close()


def _evaluate(path, variant='clean', knowledge=KNOWLEDGE_AT):
    store = Store(path)
    try:
        _writer(store, "reconcile")
        result = reconcile(store, BALANCE_AT, knowledge)
    finally:
        store.close()
    return result, financial_checks(result, variant)


def _message(child, expected, timeout=PROCESS_TIMEOUT_SECONDS):
    deadline = time.monotonic() + timeout
    buffer = child.pop('stdout_buffer', b'')
    with selectors.DefaultSelector() as selector:
        selector.register(child['process'].stdout, selectors.EVENT_READ)
        while b'\n' not in buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise TimeoutError('child did not reach ' + expected)
            chunk = os.read(child['process'].stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError('child closed before ' + expected)
            buffer += chunk
            if len(buffer) > 2 * 1024 * 1024:
                raise RuntimeError('bounded child protocol exceeded 2 MiB')
    line, remainder = buffer.split(b'\n', 1)
    child['stdout_buffer'] = remainder
    message = json.loads(line)
    child['messages'].append(message)
    if message.get('type') != expected:
        raise RuntimeError('unexpected child message: ' + repr(message))
    return message


def _start(folder, name, request):
    request_path = folder / (name + '-request.json')
    write_json(request_path, request)
    argv = [sys.executable]
    if sys.flags.isolated:
        argv.append('-I')
    argv += ['-B', '-m', 'crypto_reconciliation_lab.admission.worker', '--request', str(request_path)]
    env = dict(os.environ)
    env.pop('PYTHONPATH', None); env.pop('PYTHONHOME', None)
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, bufsize=1, env=env)
    child = {'process': process, 'messages': [], 'name': name, 'request': request,
             'argv': argv, 'cwd': str(Path.cwd()), 'started': time.monotonic(), 'folder': folder}
    try:
        ready = _message(child, 'READY')
        child['ready'] = ready
        if ready['pid'] != process.pid:
            raise RuntimeError('child readiness PID mismatch')
        return child
    except BaseException:
        _finish(child, kill=True)
        raise


def _go(child):
    child['process'].stdin.write('GO\n'); child['process'].stdin.flush()


def _compact_response(value):
    if not isinstance(value, dict) or value.get('format') != 'feed-admission-v1':
        return value
    state = value['delivery_status']
    return {k: value[k] for k in ('format', 'stream_id', 'plan', 'status', 'financial_evaluation')} | {
        'response_count': len(value['responses']),
        'response_outcomes': dict(Counter(r['outcome'] for r in value['responses'])),
        'last_response': value['responses'][-1] if value['responses'] else None,
        'committed_prefix': state['committed_prefix'], 'blocked': state['blocked'],
        'state_observation': state['status']}


def _finish(child, *, kill=False, result=None, barrier=None):
    process = child['process']
    if kill and process.poll() is None:
        process.kill()
    try:
        tail, stderr = process.communicate(timeout=PROCESS_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill(); tail, stderr = process.communicate(timeout=PROCESS_TIMEOUT_SECONDS)
        raise TimeoutError('child timeout after forced cleanup: ' + child['name'])
    (child['folder'] / (child['name'] + '-stderr.txt')).write_text(stderr)
    event = {'argv': child['argv'], 'cwd': child['cwd'], 'pid': process.pid,
             'joined': True, 'exit_code': process.returncode,
             'barrier': barrier, 'barrier_reached': barrier is not None,
             'sender_result': 'UNKNOWN' if kill else 'RESPONSE',
             'messages': [{**m, 'result': _compact_response(m['result'])} if 'result' in m else m for m in child['messages']], 'stdout_tail': child.get('stdout_buffer', b'').decode('utf-8', errors='replace') + tail, 'stderr': stderr,
             'seconds': time.monotonic() - child['started'], 'ready': child.get('ready')}
    if result is not None:
        event['result'] = _compact_response(result)
    write_json(child['folder'] / (child['name'] + '-process.json'), event)
    return event


def _normal_child(folder, name, request):
    child = _start(folder, name, request)
    try:
        _go(child)
        message = _message(child, 'RESULT')
        event = _finish(child, result=message['result'])
        if event['exit_code'] != 0:
            raise RuntimeError('normal child failed')
        return event
    finally:
        if child['process'].poll() is None:
            _finish(child, kill=True)


def _crash_child(folder, name, request, barrier):
    child = _start(folder, name, {**request, 'barrier': barrier})
    try:
        _go(child)
        message = _message(child, 'BARRIER')
        if message['point'] != barrier or message['pid'] != child['process'].pid:
            raise RuntimeError('wrong fault barrier reached')
        event = _finish(child, kill=True, barrier=barrier)
        if event['exit_code'] != -signal.SIGKILL:
            raise RuntimeError('child did not exit through observed SIGKILL')
        return event
    finally:
        if child['process'].poll() is None:
            _finish(child, kill=True)


def _delivery_request(db, snapshot, sequence, stream='feed'):
    return {'action': 'delivery', 'db': str(db), 'stream_id': stream,
            'sequence': sequence, 'payload_base64': base64.b64encode(snapshot.lines[sequence - 1]).decode(),
            'plan': snapshot.plan, 'busy_timeout_ms': BUSY_TIMEOUT_MS}


def _compact(actual):
    return {'streams': [{k: v for k, v in row.items()} for row in actual['streams']],
            'effect_identities': [[r['stream_id'], r['sequence'], r['payload_sha256'], r['core_receipt_id'], r['disposition']]
                                  for r in actual['effects']],
            'attempt_outcomes': dict(Counter(r['outcome'] for r in actual['attempts'])),
            'core_statuses': dict(Counter(r['status'] for r in actual['receipts'])),
            'core_receipts': len(actual['receipts']), 'unique_records': len(actual['records']),
            'receipt_links': [[r['id'],r['receipt_hash'],r['record_id'],r['status']] for r in actual['receipts']],
            'run_table_counts': {k:len(v) for k,v in actual['run_tables'].items()},
            'run_rows': [{'run_id':rid,'payload_sha256':hashlib.sha256(payload.encode()).hexdigest(),
                          'findings':len(json.loads(payload)['findings']), 'evidence':len(json.loads(payload)['evidence'])}
                         for rid,payload in sorted(actual['runs'].items())],
            'record_ids': [r['id'] for r in actual['records']], 'run_ids': sorted(actual['runs']),
            'run_payload_hashes': {rid: hashlib.sha256(payload.encode()).hexdigest() for rid, payload in actual['runs'].items()},
            'integrity_check': actual['integrity_check'], 'foreign_key_check': actual['foreign_key_check']}


def _plan_item(identifier, input_name, line_count):
    financial = ('NOT_RUN' if identifier in ('transport_conflict', 'busy_retry', 'changed_prefix', 'truncated_file', 'rejected_json')
                 else 'custody_difference' if identifier == 'custody_difference'
                 else 'economic_conflict' if identifier == 'economic_conflict'
                 else 'invalid_payload' if identifier == 'invalid_payload'
                 else 'corrected' if identifier == 'save_run_crash' else 'clean')
    terminal = 'BLOCKED' if identifier in ('transport_conflict', 'changed_prefix', 'truncated_file') else 'COMPLETE'
    return {'id': identifier, 'input': input_name, 'planned_lines': line_count,
            'barrier': BARRIERS.get(identifier), 'expected_terminal': terminal,
            'financial_projection': financial,
            'expected_crash_exit': -9 if identifier in BARRIERS else None}


def _case(identifier, folder, config, input_path, item):
    scope = load_scope()
    validate_plan(identifier, item, scope)
    _WRITER_OBSERVATIONS.clear()
    boundaries = {}
    db = folder / 'evidence.sqlite3'
    _initialize(db, config)
    snapshot = snapshot_feed(input_path)
    # Expectations come from independent literal file bytes, never snapshot_feed's output.
    lines = tuple(input_path.read_bytes().splitlines(keepends=True))
    plan = snapshot.plan
    stream = 'feed'
    expected_streams = {stream: lines}
    receipt_count = len(lines)
    record_count = len(lines)
    core_statuses = {'ACCEPTED': len(lines)}
    attempts = None
    blocked = ()
    checks, processes, responses = [], [], []
    financial = {'status': 'NOT_RUN', 'reason': 'not reached'}
    old_run = None
    old_tables = None
    if identifier in ('clean', 'custody_difference', 'rejected_json'):
        responses.append(_feed(db, input_path))
        if identifier == 'rejected_json':
            receipt_count = record_count = 30
            core_statuses = {'ACCEPTED': 30}
            checks.append(check('terminal_rejected_frame', observed(db)['effects'][-1]['disposition'], 'REJECTED_FRAME'))
    elif identifier == 'transport_replay':
        responses.append(_feed(db, input_path))
        old_run, cs = _evaluate(db); checks += _phase(cs, 'initial_financial')
        before = observed(db)
        responses.append(_feed(db, input_path))
        after = observed(db)
        boundaries = {'before': _state_proof(before), 'after_replay': _state_proof(after)}
        checks += [check('replay_core_receipts_unchanged', after['receipts'], before['receipts']),
                   check('replay_first_effects_unchanged', after['effects'], before['effects']),
                   check('replay_old_saved_payload_unchanged', after['runs'], before['runs'])]
        attempts = {'COMMITTED': 30, 'REPLAY': 30}
    elif identifier in ('economic_duplicate', 'economic_conflict', 'invalid_payload'):
        responses.append(_feed(db, input_path))
        if identifier == 'economic_duplicate':
            record_count = 30; core_statuses = {'ACCEPTED': 30, 'DUPLICATE': 1}
        elif identifier == 'economic_conflict':
            core_statuses = {'ACCEPTED': 30, 'CONFLICT': 1}
        else:
            record_count = 30; core_statuses = {'ACCEPTED': 30, 'INVALID': 1}
    elif identifier == 'transport_conflict':
        responses.append(_delivery(db, stream, 1, lines[0], plan))
        changed = (input_path.parent / 'transport_conflict_payload.jsonl').read_bytes()
        responses.append(_delivery(db, stream, 1, changed, plan))
        responses.append(_delivery(db, stream, 2, lines[1], plan))
        checks += [check('changed_identity_rejected', responses[-2]['outcome'], 'TRANSPORT_CONFLICT'),
                   check('subsequent_effect_blocked', responses[-1]['outcome'], 'BLOCKED')]
        expected_streams = {stream: lines[:1]}; receipt_count = record_count = 1
        core_statuses = {'ACCEPTED': 1}; blocked = (stream,)
        attempts = {'COMMITTED': 1, 'TRANSPORT_CONFLICT': 1, 'BLOCKED': 1}
    elif identifier == 'gap_recovery':
        response = _delivery(db, stream, 2, lines[1], plan); responses.append(response)
        gap = observed(db)
        checks += [check('gap_outcome', response['outcome'], 'GAP'),
                   check('gap_no_effect_or_core', [len(gap['effects']), len(gap['receipts']), len(gap['records'])], [0, 0, 0])]
        responses.append(_feed(db, input_path)); attempts = {'GAP': 1, 'COMMITTED': 30}
    elif identifier in ('crash_after_record', 'crash_after_receipt', 'crash_after_disposition', 'lost_ack'):
        for i in range(1, 9):
            responses.append(_delivery(db, stream, i, lines[i - 1], plan))
        before = observed(db)
        processes.append(_crash_child(folder, 'crashed-delivery', _delivery_request(db, snapshot, 9), BARRIERS[identifier]))
        _reopen(db)
        after = observed(db)
        boundaries = {'before': _state_proof(before), 'after_crash': _state_proof(after)}
        expected_after = 9 if identifier == 'lost_ack' else 8
        checks += _phase(delivery_checks(after, {stream: lines[:expected_after]}, receipt_count=expected_after,
                                  record_count=expected_after, core_statuses={'ACCEPTED': expected_after}), 'interrupted')
        if identifier != 'lost_ack':
            checks += [check('precommit_all_core_and_transport_rollback',
                             [after[k] for k in ('streams', 'effects', 'attempts', 'receipts', 'records')],
                             [before[k] for k in ('streams', 'effects', 'attempts', 'receipts', 'records')])]
        else:
            persisted = after['effects'][-1]
            retry = _delivery(db, stream, 9, lines[8], plan); responses.append(retry)
            boundaries['after_retry'] = _state_proof(observed(db))
            checks += [check('unknown_retry_returns_original', retry['core_result'], json.loads(persisted['core_result'])),
                       check('unknown_retry_reuses_receipt_row', retry['core_receipt_row_id'], persisted['core_receipt_id']),
                       check('unknown_retry_is_replay', retry['outcome'], 'REPLAY')]
        responses.append(_feed(db, input_path))
    elif identifier == 'ack_restart':
        processes.append(_normal_child(folder, 'acknowledged', _delivery_request(db, snapshot, 1)))
        checks.append(check('ack_response_delivered', processes[-1]['result']['ack'], True))
        _reopen(db)
        checks += _phase(delivery_checks(observed(db), {stream: lines[:1]}, receipt_count=1, record_count=1, core_statuses={'ACCEPTED': 1}), 'ack_reopen')
        responses.append(_feed(db, input_path))
    elif identifier in ('writers_same_stream', 'writers_separate_stream'):
        stream_ids = ('feed', 'feed') if identifier == 'writers_same_stream' else ('feed', 'other')
        children = []
        try:
            for i, sid in enumerate(stream_ids):
                children.append(_start(folder, 'writer-' + str(i), {'action': 'feed', 'db': str(db),
                    'input': str(input_path), 'stream_id': sid, 'busy_timeout_ms': BUSY_TIMEOUT_MS}))
            for child in children:
                _go(child)
            for child in children:
                response = _message(child, 'RESULT')['result']
                processes.append(_finish(child, result=response))
            checks += [check('two_distinct_processes', len({p['pid'] for p in processes}), 2),
                       check('all_writers_joined_successfully', all(p['joined'] and p['exit_code'] == 0 for p in processes), True)]
            # Bounded exact-file retries are allowed after a contended writer explicitly stops.
            for sid in dict.fromkeys(stream_ids):
                store = Store(db)
                try:
                    status = store.feed_status(sid)
                finally:
                    store.close()
                for _ in range(RETRY_BUDGET):
                    if status['status'] == 'COMPLETE':
                        break
                    responses.append(_feed(db, input_path, sid))
                    store = Store(db)
                    try:
                        status = store.feed_status(sid)
                    finally:
                        store.close()
                checks.append(check('writer_stream_completed:' + sid, status['status'], 'COMPLETE'))
        finally:
            for child in children:
                if child['process'].poll() is None:
                    _finish(child, kill=True)
        if identifier == 'writers_separate_stream':
            expected_streams['other'] = lines; receipt_count = 60; record_count = 30
            core_statuses = {'ACCEPTED': 30, 'DUPLICATE': 30}
    elif identifier == 'busy_retry':
        request = _delivery_request(db, snapshot, 1)
        holder = _start(folder, 'holder', {**request, 'barrier': 'delivery_before_commit'})
        try:
            _go(holder); reached = _message(holder, 'BARRIER')
            if reached['point'] != 'delivery_before_commit':
                raise RuntimeError('holder did not establish the declared lock boundary')
            busy = _normal_child(folder, 'contender', request); processes.append(busy)
            checks += [check('bounded_busy_result', busy['result']['outcome'], 'RETRYABLE_BUSY'),
                       check('busy_no_ack', busy['result']['ack'], False),
                       check('busy_no_durable_attempt_claim', busy['result']['durable'], False)]
            holder['process'].stdin.write('CONTINUE\n'); holder['process'].stdin.flush()
            response = _message(holder, 'RESULT')['result']
            processes.append(_finish(holder, result=response, barrier='delivery_before_commit'))
        finally:
            if holder['process'].poll() is None:
                _finish(holder, kill=True)
        retry = _delivery(db, stream, 1, lines[0], plan); responses.append(retry)
        checks.append(check('busy_retry_original_replayed', retry['outcome'], 'REPLAY'))
        attempts = {'COMMITTED': 1, 'REPLAY': 1}
    elif identifier == 'save_run_crash':
        # Two complete finite streams: the old clean run, then independently delivered corrections.
        initial_path = input_path.parent / 'save_run_initial.jsonl'
        corrections_path = input_path.parent / 'save_run_corrections.jsonl'
        initial = snapshot_feed(initial_path); corrections = snapshot_feed(corrections_path)
        responses.append(_feed(db, initial_path)); old_run, cs = _evaluate(db); checks += _phase(cs, 'initial_financial')
        responses.append(_feed(db, corrections_path, 'corrections'))
        before = observed(db); old_tables = before['run_tables']
        processes.append(_crash_child(folder, 'crashed-save-run', {'action': 'reconcile', 'db': str(db),
            'balance_at': BALANCE_AT, 'knowledge_at': T3}, BARRIERS[identifier]))
        _reopen(db); after = observed(db)
        boundaries = {'before': _state_proof(before), 'after_crash': _state_proof(after)}
        checks.append(check('save_crash_all_run_tables_rollback', after['run_tables'], old_tables))
        expected_streams = {stream: tuple(initial_path.read_bytes().splitlines(keepends=True)),
                            'corrections': tuple(corrections_path.read_bytes().splitlines(keepends=True))}
    elif identifier in ('changed_prefix', 'truncated_file'):
        for i in range(1, 9):
            responses.append(_delivery(db, stream, i, lines[i - 1], plan))
        changed_path = input_path.parent / (identifier + '_snapshot.jsonl')
        before = observed(db)
        responses.append(_feed(db, changed_path))
        after = observed(db)
        checks += [check('original_plan_binding_retained', after['streams'], before['streams']),
                   check('changed_snapshot_no_core_effect', after['effects'], before['effects']),
                   check('changed_snapshot_plan_conflict_retained', after['attempts'][-1]['outcome'], 'PLAN_CONFLICT')]
        expected_streams = {stream: lines[:8]}; receipt_count = record_count = 8
        core_statuses = {'ACCEPTED': 8}; blocked = (stream,)
    elif identifier == 'new_receipt_economic_parity':
        responses.append(_feed(db, input_path))
        same_cut = '2026-11-11T03:00:00Z'
        old_run, cs = _evaluate(db, knowledge=same_cut); checks += _phase(cs, 'initial_financial')
        later_path = input_path.parent / 'late_receipt.jsonl'
        later = snapshot_feed(later_path)
        responses.append(_feed(db, later_path, 'late'))
        expected_streams['late'] = tuple(later_path.read_bytes().splitlines(keepends=True))
        receipt_count = 31; record_count = 30
        core_statuses = {'ACCEPTED': 30, 'DUPLICATE': 1}
    else:
        raise ValueError('unknown predeclared case')

    _reopen(db)
    actual = observed(db)
    checks += delivery_checks(actual, expected_streams, receipt_count=receipt_count, record_count=record_count,
                              core_statuses=core_statuses, blocked=blocked, attempt_counts=attempts)
    # Bind the immutable stream metadata to complete *original* input snapshots.
    for sid, expected_lines in expected_streams.items():
        bound = next((r for r in actual['streams'] if r['stream_id'] == sid), None)
        if identifier == 'save_run_crash':
            original_path = initial_path if sid == 'feed' else corrections_path
        elif identifier == 'new_receipt_economic_parity' and sid == 'late':
            original_path = later_path
        else:
            original_path = input_path
        original_bytes = original_path.read_bytes()
        independent_plan = {'input_sha256': hashlib.sha256(original_bytes).hexdigest(),
                            'input_bytes': len(original_bytes),
                            'planned_lines': len(original_bytes.splitlines(keepends=True)),
                            'framing': 'utf8-lf-jsonl-v1'}
        checks.append(check('immutable_plan:' + sid,
            {k: bound[k] for k in independent_plan} if bound else None, independent_plan))
    inventory_variant = ('prefix1' if identifier in ('transport_conflict', 'busy_retry') else
                         'prefix8' if identifier in ('changed_prefix', 'truncated_file') else
                         'economic_conflict' if identifier == 'economic_conflict' else
                         'corrected' if identifier == 'save_run_crash' else 'clean')
    checks += record_inventory_checks(actual, inventory_variant)
    store = Store(db)
    try:
        statuses = {sid: store.feed_status(sid) for sid in expected_streams}
    finally:
        store.close()
    terminal = 'BLOCKED' if blocked else 'COMPLETE'
    checks.append(check('operational_terminal', {sid: s['status'] for sid, s in statuses.items()},
                        {sid: terminal for sid in expected_streams}))
    if item['financial_projection'] != 'NOT_RUN' and all(c['passed'] for c in checks):
        # Every writer has been joined and the independent scope oracle passed first.
        variant = item['financial_projection']
        knowledge = T3 if identifier == 'save_run_crash' else ('2026-11-11T03:00:00Z' if identifier == 'new_receipt_economic_parity' else KNOWLEDGE_AT)
        result, cs = _evaluate(db, variant, knowledge); checks += cs
        financial = {'status': 'EVALUATED', 'variant': variant, 'run_id': result['run_id'],
                     'ledgers': {a: {k:result['ledgers'][a][k] for k in ('investor_balances','liability','custody_rollforward','data_state')} for a in ('ASSET_A','ASSET_B')},
                     'findings': [{k: f[k] for k in ('asset', 'comparison', 'scope', 'data_state', 'reconciliation_state', 'difference')}
                                  for f in result['findings']]}
        write_json(folder / 'financial-result.json', result)
        if old_run is not None:
            store = Store(db)
            try:
                checks.append(check('old_run_payload_preserved', store.read_run(old_run['run_id']), old_run))
            finally:
                store.close()
        if identifier == 'transport_replay':
            checks.append(check('same_transport_replay_same_financial_payload_and_id', result, old_run))
        if identifier == 'new_receipt_economic_parity':
            checks += [check('new_receipt_same_economic_ledgers',
                              {a: result['ledgers'][a]['investor_balances'] for a in result['ledgers']},
                              {a: old_run['ledgers'][a]['investor_balances'] for a in old_run['ledgers']}),
                       check('new_receipt_changes_evidence_run_identity', result['run_id'] != old_run['run_id'], True),
                       check('same_financial_cut_for_receipt_comparison', result['knowledge_at'], old_run['knowledge_at'])]
            financial['equality_note'] = 'Same quantities and cuts; new received_at receipt evidence changes run ID. Old snapshot retained.'
        if identifier == 'save_run_crash':
            saved = observed(db)
            checks += [check('corrected_run_count', len(saved['runs']), 2),
                       check('corrected_group_count', len(saved['run_tables']['correction_groups']), 1),
                       check('corrected_effect_count', len(saved['run_tables']['correction_effects']), 2),
                       check('all_saved_finding_rows', len(saved['run_tables']['findings']), 12),
                       check('all_saved_evidence_rows', len(saved['run_tables']['evidence']),
                             len(old_run['evidence']) + len(result['evidence']))]
    else:
        financial = {'status': 'NOT_RUN', 'reason': 'blocked/rejected-frame/micro transport case or failed independent admission checks'}
        if identifier in ('transport_conflict', 'changed_prefix', 'truncated_file', 'rejected_json', 'busy_retry'):
            checks.append(check('no_financial_run_for_operational_only_case', len(actual['runs']), 0))
    final = observed(db)
    status = 'PASS' if checks and all(c['passed'] for c in checks) else 'FAILED'
    report = {'id': identifier, 'status': status, 'expected': item,
              'observed': _compact(final), 'checks': checks, 'processes': processes,
              'responses': [_compact_response(r) for r in responses], 'financial': financial,
              'boundaries': boundaries, 'writer_connections': list(_WRITER_OBSERVATIONS),
              'readback_connection': {'journal_mode':final['journal_mode'], 'synchronous':final['synchronous'], 'role':'new read-only observation connection'},
              'environment': {'journal_mode': final['journal_mode'], 'synchronous': final['synchronous'],
                              'busy_timeout_ms': BUSY_TIMEOUT_MS, 'retry_budget': RETRY_BUDGET}}
    if status == 'PASS':
        try:
            validate_case(report, scope)
        except ValueError as exc:
            report['status'] = 'FAILED'
            report['semantic_error'] = str(exc)
    write_json(folder / 'result.json', report)
    return report


def run_recovery(output, seed=9):
    """Run one bounded fixed schedule into a new directory, preserving all attempts."""
    if type(seed) is not int or not 0 <= seed <= 2**31 - 1:
        raise ValueError('seed must be a nonnegative 31-bit integer')
    root = Path(output).resolve()
    if root.exists():
        raise ValueError('recovery output must be a new directory')
    root.mkdir(parents=True)
    config, clean_rows, _ = fixtures('clean')
    _, custody_rows, _ = fixtures('custody_difference')
    if len(clean_rows) != 30 or len(custody_rows) != 30:
        raise ValueError('small fixture inventory changed from independent 30-line reference')
    inputs = root / 'inputs'; inputs.mkdir()
    variants = {'clean': input_bytes(clean_rows), 'custody_difference': input_bytes(custody_rows)}
    for variant in ('economic_duplicate', 'economic_conflict', 'invalid_payload'):
        extra = copy.deepcopy(clean_rows[9])
        if variant == 'economic_conflict':
            extra['record']['amount'] = '3'
        elif variant == 'invalid_payload':
            extra['record']['amount'] = ''
        variants[variant] = input_bytes(clean_rows + [extra])
    _, corrected_rows, _ = correction_fixtures('deposit_amount_correction')
    variants['save_run_crash'] = input_bytes(corrected_rows)
    variants['busy_retry'] = input_bytes(clean_rows[:1])
    variants['rejected_json'] = input_bytes(clean_rows) + (b'{"record": invalid-json}\n',)
    variants['save_run_initial'] = input_bytes(corrected_rows[:30])
    variants['save_run_corrections'] = input_bytes(corrected_rows[30:])
    changed = list(variants['clean'])
    changed[0] = changed[0].replace(b'"6"', b'"7"', 1)
    variants['changed_prefix_snapshot'] = tuple(changed)
    variants['truncated_file_snapshot'] = variants['clean'][:8]
    variants['transport_conflict_payload'] = (changed[0],)
    late = copy.deepcopy(clean_rows[9]); late['received_at'] = '2026-11-11T03:00:00Z'
    variants['late_receipt'] = input_bytes([late])
    input_proofs = {}
    for name, lines in variants.items():
        path = inputs / (name + '.jsonl'); data = b''.join(lines); path.write_bytes(data)
        input_proofs[name] = {'path': str(path.relative_to(root)), 'bytes': len(data),
                             'sha256': hashlib.sha256(data).hexdigest(), 'planned_lines': len(lines)}
    write_json(inputs / 'config.json', config)
    schedule = {'format': 'admission-recovery-schedule-v2', 'seed': seed,
                'seed_scope': 'Fixed declared scenario and barrier program; OS and disk timing are not deterministic.',
                'inputs': input_proofs, 'scenarios': [],
                'fault_model': 'Initialized local rollback-journal SQLite; application-process SIGKILL and bounded writer contention only.',
                'excluded': ['database initialization crash', 'power loss', 'kernel crash', 'disk corruption',
                             'network partition', 'distributed consensus', 'Byzantine sources', 'production concurrency'],
                'timeout_seconds': PROCESS_TIMEOUT_SECONDS, 'busy_timeout_ms': BUSY_TIMEOUT_MS,
                'retry_budget': RETRY_BUDGET}
    for identifier in SCENARIO_IDS:
        name = identifier if identifier in variants else 'clean'
        item = _plan_item(identifier, input_proofs[name]['path'], len(variants[name]))
        extras = {'save_run_crash': ['save_run_initial', 'save_run_corrections'],
                  'changed_prefix': ['changed_prefix_snapshot'], 'truncated_file': ['truncated_file_snapshot'],
                  'new_receipt_economic_parity': ['late_receipt'],
                  'transport_conflict': ['transport_conflict_payload']}.get(identifier, [])
        item['auxiliary_inputs'] = [input_proofs[n]['path'] for n in extras]
        schedule['scenarios'].append(item)
    scope = load_scope()
    validate_schedule(schedule, scope)
    write_json(root / 'schedule.json', schedule)
    schedule_hash = hashlib.sha256((root / 'schedule.json').read_bytes()).hexdigest()
    write_json(root / 'invocation.json', {'argv': sys.argv, 'cwd': str(Path.cwd()),
        'interpreter': sys.executable, 'python': sys.version, 'import_origin': str(Path(__file__).resolve()),
        'sqlite': sqlite3.sqlite_version, 'platform': platform.platform(), 'isolated': bool(sys.flags.isolated),
        'started_at_utc': datetime.now(timezone.utc).isoformat()})
    results = []
    started = time.monotonic()
    for item in schedule['scenarios']:
        folder = root / item['id']; folder.mkdir()
        try:
            result = _case(item['id'], folder, config, root / item['input'], item)
        except (Exception, KeyboardInterrupt) as exc:
            result = {'id': item['id'], 'status': 'INCOMPLETE' if isinstance(exc, (TimeoutError, KeyboardInterrupt)) else 'FAILED',
                      'expected': item, 'checks': [check('scenario_completed', type(exc).__name__ + ': ' + str(exc), 'completed')],
                      'processes': [], 'financial': {'status': 'NOT_RUN', 'reason': 'scenario failed'},
                      'error': type(exc).__name__ + ': ' + str(exc)}
            write_json(folder / 'result.json', result)
        results.append(result)
        # Keep partial evidence even if an outside interruption stops a later case.
        write_json(root / 'progress.json', {'planned_scenario_ids': list(SCENARIO_IDS), 'scenarios': results})
    negative = negative_control()
    complete = [r['id'] for r in results] == list(SCENARIO_IDS) and len(set(r['id'] for r in results)) == len(SCENARIO_IDS)
    status = ('PASS' if complete and all(r['status'] == 'PASS' for r in results) and negative['status'] == 'EXPECTED_FAILURE'
              else 'INCOMPLETE' if any(r['status'] == 'INCOMPLETE' for r in results) else 'FAILED')
    summary = {'format': 'admission-recovery-v2', 'status': status, 'seed': seed,
        'planned_scenario_ids': list(SCENARIO_IDS), 'executed_scenario_ids': [r['id'] for r in results],
        'scenarios': results, 'negative_control': negative, 'schedule_sha256': schedule_hash,
        'environment': {'python': sys.version, 'interpreter': sys.executable, 'import_origin': str(Path(__file__).resolve()),
                        'sqlite': sqlite3.sqlite_version, 'platform': platform.platform(),
                        'settings_provenance': 'Per-case writer_connections and child READY/BARRIER/RESULT; separate readback_connection', 'busy_timeout_ms': BUSY_TIMEOUT_MS, 'retry_budget': RETRY_BUDGET},
        'seconds': time.monotonic() - started,
        'equality_contract': ['legacy fixed reference: 373 financial files (release verification)',
            'identical transport replay: same core receipt inventory, financial payload and run ID',
            'new core receipt history: economic equality does not require evidence/run ID equality'],
        'not_run': ['frozen main generation', 'frozen main training', 'final holdout', 'heavy benchmark'],
        'fault_model': schedule['fault_model'], 'excluded': schedule['excluded']}
    if status == 'PASS':
        try:
            validate_report(summary, scope, schedule_sha256=schedule_hash)
        except ValueError as exc:
            status = summary['status'] = 'FAILED'
            summary['semantic_error'] = str(exc)
    write_json(root / 'delivery-summary.json', summary)
    lines = ['# Recovery experiment', '', 'Status: **' + status + '**. Synthetic inputs; no capacity or recovery-time guarantee.', '',
             '| Scenario | Expected terminal | Financial reference | Actual acceptance |', '|---|---|---|---|']
    lines += ['| ' + r['id'] + ' | ' + r['expected']['expected_terminal'] + ' | ' +
              r['expected']['financial_projection'] + ' | ' + r['status'] + ' |' for r in results]
    lines += ['', 'Each fault uses a positively observed named child barrier followed by SIGKILL and join. ',
              'A missing ACK means UNKNOWN, not rollback. Core INVALID/CONFLICT can still be durably delivered.',
              'Writers finish before scope checks and financial evaluation. Blocked cases do not create financial runs.',
              'The negative test double must be rejected by the same independent SQL acceptance checks.',
              '', 'See schedule.json, delivery-summary.json, invocation.json and per-case process/result records.',
              'The database was initialized before injection. This covers application-process termination and bounded writer contention,',
              'not power/kernel/disk failures, source authentication or production concurrency. Timing is observational.']
    (root / 'report.md').write_text('\n'.join(lines) + '\n')
    return summary


def run_demo(output, seed=19):
    """CLI-compatible spelling; same complete finite program as run_recovery."""
    return run_recovery(output, seed=seed)
