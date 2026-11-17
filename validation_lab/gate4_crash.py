"""Preregistered, bounded process-crash witnesses around unchanged Store APIs.

The pipe barrier is outside production code. ACK means the research client's
fsynced receipt ledger, not a new product/API promise or a power-loss claim.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import select
import shutil
import signal
import sqlite3
import subprocess
import sys
import time

from crypto_reconciliation_lab import reconcile
from crypto_reconciliation_lab.demo import BALANCE_AT, KNOWLEDGE_AT, fixtures
from crypto_reconciliation_lab.model import dumps
from validation_lab.gate4_storage import METHODS, disk_snapshot, logical_snapshot, open_store, read_pragmas

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'contracts/gate4-crash-catalog.json'
APIS = ('ordinary_ingest', 'restartable_ingest_delivery')
STAGES = ('before_begin', 'after_begin', 'after_insert_before_commit', 'after_commit_before_ack', 'after_ack')
OBSERVED_AT = '2026-11-11T01:00:00Z'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n')


def proof(path):
    data = Path(path).read_bytes()
    return {'bytes': len(data), 'sha256': sha(data)}


def source_bindings():
    names = [Path(__file__), CATALOG, ROOT / 'validation_lab/gate4_storage.py']
    names += sorted((ROOT / 'crypto_reconciliation_lab').rglob('*.py'))
    return {str(path.relative_to(ROOT)): proof(path) for path in names}


@contextmanager
def finite_controller(seconds=120):
    def stop(signum, frame):
        raise TimeoutError('Gate4 crash controller finite deadline/signal ' + str(signum))
    old = {sig: signal.signal(sig, stop) for sig in (signal.SIGALRM, signal.SIGTERM)}
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        for sig, handler in old.items():
            signal.signal(sig, handler)


def plan(payload):
    return {'format': 'admission-plan-v1', 'input_sha256': sha(payload), 'input_bytes': len(payload),
            'planned_lines': 1, 'framing': 'utf8-lf-jsonl-v1'}


def invoke(store, api, payload):
    envelope = json.loads(payload)
    if api == 'ordinary_ingest':
        return store.ingest(envelope['record'], envelope['received_at'])
    if api == 'restartable_ingest_delivery':
        return store.ingest_delivery('Gate4Crash', 1, payload, plan(payload), observed_at=OBSERVED_AT)
    raise ValueError('unknown API')


def assert_financial(result, committed):
    """Literal ledger/classification oracle; no engine-derived expectation."""
    expected = {
        'ASSET_A': {'investor_balances': {'I1': '7', 'I2': '4' if committed else '5'},
                    'liability': '11' if committed else '12',
                    'custody_rollforward': {'platform': '2', 'external': '9' if committed else '10'}},
        'ASSET_B': {'investor_balances': {'I1': '0.3', 'I2': '0.2'}, 'liability': '0.5',
                    'custody_rollforward': {'platform': '0.05', 'external': '0.45'}}}
    for asset, fields in expected.items():
        for key, value in fields.items():
            if result['ledgers'][asset][key] != value:
                raise AssertionError(('literal ledger mismatch', asset, key, value))
    if len(result['findings']) != 6:
        raise AssertionError('expected exactly six findings')
    for row in result['findings']:
        missing = row['asset'] == 'ASSET_A' and not committed
        expected_tuple = ('INCOMPLETE', 'NOT_EVALUATED', '0' if row['scope'] == 'I1' else '1') if missing else ('COMPLETE', 'MATCHED', '0')
        if tuple(row[k] for k in ('data_state', 'reconciliation_state', 'difference')) != expected_tuple:
            raise AssertionError(('literal classification mismatch', row, expected_tuple))


def evaluate_copy(store, path, method, committed):
    target = sqlite3.connect(path)
    try:
        store.db.backup(target)
    finally:
        target.close()
    evaluated = open_store(path, method=method)
    try:
        result = reconcile(evaluated, BALANCE_AT, KNOWLEDGE_AT)
        assert_financial(result, committed)
        if evaluated.read_run(result['run_id']) != result:
            raise AssertionError('saved run differs from returned financial result')
        return {'pragmas': read_pragmas(evaluated), 'result': result,
                'logical_snapshot_after_save': logical_snapshot(evaluated)}
    finally:
        evaluated.close()


def emit(fd, event):
    data = (json.dumps(event, sort_keys=True, separators=(',', ':')) + '\n').encode()
    if len(data) > 4096:
        raise ValueError('barrier frame exceeds atomic pipe write size')
    os.write(fd, data)


def worker(args):
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGALRM, signal.SIGINT, signal.SIGTERM})
    payload = Path(args.request).read_bytes()
    original_connect = sqlite3.connect
    state = {'armed': False, 'commit_completed': False, 'commits': 0}

    def event(stage, connection):
        value = {'stage': stage, 'pid': os.getpid(), 'request_sha256': sha(payload),
                 'in_transaction': connection.in_transaction, 'commit_completed': state['commit_completed'],
                 'commits': state['commits'], 'pragmas': read_pragmas(connection)}
        emit(args.event_fd, value)
        if stage == args.stage:
            # Real synchronization: controller owns the only writer and kills us
            # after observing this exact event. No timing sleep defines a gate.
            if os.read(args.gate_fd, 1) != b'X':
                raise RuntimeError('controller gate closed without termination')
            raise RuntimeError('crash gate unexpectedly released')

    class GatedConnection(sqlite3.Connection):
        def execute(self, sql, *values, **kwargs):
            token = sql.lstrip().upper().split()[0]
            if state['armed'] and token == 'BEGIN':
                event('before_begin', self)
            if state['armed'] and token == 'COMMIT':
                event('after_insert_before_commit', self)
            result = super().execute(sql, *values, **kwargs)
            if state['armed'] and token == 'BEGIN':
                event('after_begin', self)
            if state['armed'] and token == 'COMMIT':
                state['commits'] += 1
                state['commit_completed'] = True
                event('after_commit_before_ack', self)
            return result

    def connect(*values, **kwargs):
        kwargs['factory'] = GatedConnection
        return original_connect(*values, **kwargs)

    sqlite3.connect = connect
    try:
        store = open_store(args.db, method=args.method)
    finally:
        sqlite3.connect = original_connect
    try:
        state['armed'] = True
        response = invoke(store, args.api, payload)
        if not state['commit_completed'] or store.db.in_transaction or state['commits'] != 1:
            raise AssertionError('ACK attempted without exactly one completed commit')
        if args.api == 'restartable_ingest_delivery' and not response['ack']:
            raise AssertionError('expected committed delivery ACK')
        ledger = {'format': 'gate4-research-client-ack-v1', 'request_sha256': sha(payload),
                  'api': args.api, 'response': response, 'commit_completed': True, 'commits': 1}
        with Path(args.ack).open('x') as handle:
            handle.write(json.dumps(ledger, sort_keys=True) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        directory = os.open(str(Path(args.ack).parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        event('after_ack', store.db)
    finally:
        store.close()


def read_barrier(process, fd, stage, seconds):
    deadline, buffered, events = time.monotonic() + seconds, b'', []
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], max(0, deadline - time.monotonic()))
        if not ready:
            break
        data = os.read(fd, 8192)
        if not data:
            raise RuntimeError('child exited before selected barrier; actual exit=' + str(process.poll()))
        buffered += data
        while b'\n' in buffered:
            line, buffered = buffered.split(b'\n', 1)
            event = json.loads(line)
            if event['pid'] != process.pid:
                raise AssertionError('barrier PID does not match owned subprocess')
            events.append(event)
            if event['stage'] == stage:
                return events
    raise TimeoutError('child did not reach selected barrier within finite budget')


def kill_at_gate(folder, db, request, method, api, stage):
    event_read, event_write = os.pipe()
    gate_read, gate_write = os.pipe()
    command = [sys.executable, '-B', '-m', 'validation_lab.gate4_crash', 'worker',
               '--db', str(db), '--request', str(request), '--method', method,
               '--api', api, '--stage', stage, '--ack', str(folder / 'ack.json'),
               '--event-fd', str(event_write), '--gate-fd', str(gate_read)]
    metadata = {'argv': command, 'cwd': str(ROOT), 'interpreter': sys.executable,
                'request': proof(request), 'method': method, 'api': api, 'stage': stage,
                'child_wall_budget_seconds': 5, 'signal_sent': None, 'actual_exit': None}
    write(folder / 'command.json', metadata)
    process, start, events = None, time.monotonic(), []
    try:
        with (folder / 'stdout.txt').open('wb') as stdout, (folder / 'stderr.txt').open('wb') as stderr:
            previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM, signal.SIGINT, signal.SIGTERM})
            try:
                process = subprocess.Popen(command, cwd=ROOT, pass_fds=(event_write, gate_read),
                                           stdout=stdout, stderr=stderr, start_new_session=True)
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous)
            metadata['pid'] = process.pid
            os.close(event_write); event_write = None
            os.close(gate_read); gate_read = None
            events = read_barrier(process, event_read, stage, 5)
            write(folder / 'barrier-events.json', events)
            os.kill(process.pid, signal.SIGKILL)
            metadata['signal_sent'] = 'SIGKILL'
            metadata['actual_exit'] = process.wait(timeout=5)
    finally:
        if process is not None:
            if process.poll() is None:
                os.kill(process.pid, signal.SIGKILL)
                metadata['cleanup_signal'] = 'SIGKILL'
            metadata['actual_exit'] = process.wait(timeout=5)
            metadata['reaped'] = True
        for fd in (event_read, event_write, gate_read, gate_write):
            if fd is not None:
                os.close(fd)
        metadata['wall_seconds'] = time.monotonic() - start
        write(folder / 'command.json', metadata)
    if metadata['actual_exit'] != -signal.SIGKILL or metadata['signal_sent'] != 'SIGKILL':
        raise AssertionError('no observed, owned SIGKILL result')
    return metadata, events


def preserve_files(db, folder):
    folder.mkdir()
    files = {}
    for suffix in ('', '-wal', '-shm', '-journal'):
        source = Path(str(db) + suffix)
        if source.exists():
            target = folder / source.name
            shutil.copy2(source, target)
            files[source.name] = proof(target)
    return files


def validate_ack(folder, stage, payload, response):
    path = folder / 'ack.json'
    expected = stage == 'after_ack'
    if path.exists() != expected:
        raise AssertionError('external ACK exists at wrong crash boundary')
    if expected:
        value = json.loads(path.read_bytes())
        if value['request_sha256'] != sha(payload) or value['response'] != response:
            raise AssertionError('external ACK request/response binding differs')
        if value['commit_completed'] is not True or value['commits'] != 1:
            raise AssertionError('external ACK lacks single completed commit')
    return {'expected_ack_count': int(expected), 'observed_ack_count': int(path.exists()),
            'ledger': proof(path) if expected else None}


def run_trial(root, initial, request, method, api, stage, references, initial_run):
    folder = root / (method + '--' + api + '--' + stage)
    folder.mkdir()
    db = folder / 'active.sqlite3'
    shutil.copy2(initial, db)
    write(folder / 'initial-database.json', proof(db))
    committed = stage in ('after_commit_before_ack', 'after_ack')
    result = {'method': method, 'api': api, 'stage': stage, 'status': 'ERROR'}
    try:
        command, events = kill_at_gate(folder, db, request, method, api, stage)
        result['process'] = command
        result['barrier_events'] = events
        result['raw_files_after_kill'] = preserve_files(db, folder / 'raw-after-kill')
        preserve_files(db, folder / 'recovery-copy')
        result['disk_before_reopen'] = disk_snapshot(db)
        payload = request.read_bytes()
        result['ack'] = validate_ack(folder, stage, payload, references[api]['responses'][0])
        store = open_store(db, method=method)
        try:
            before = logical_snapshot(store)
            result['reopen_pragmas'] = read_pragmas(store)
            if before != references[api]['snapshots'][int(committed)]:
                raise AssertionError('direct recovered logical tables differ from expected commit state')
            if store.read_run(initial_run['run_id']) != initial_run:
                raise AssertionError('preexisting saved run changed during recovery')
            copied = open_store(folder / 'recovery-copy/active.sqlite3', method=method)
            try:
                result['copied_reopen_pragmas'] = read_pragmas(copied)
                if logical_snapshot(copied) != before:
                    raise AssertionError('raw copy recovery differs from direct reopen')
            finally:
                copied.close()
            evaluated = evaluate_copy(store, folder / 'recovered-evaluation.sqlite3', method, committed)
            if evaluated['result'] != references[api]['evaluations'][int(committed)]['result']:
                raise AssertionError('recovered result/run ID/selected evidence differs')
            write(folder / 'recovered-state.json', {'snapshot': before, 'evaluation': evaluated})
            retry = invoke(store, api, payload)
            if retry != references[api]['responses'][int(committed)]:
                raise AssertionError('retry differs from literal commit/replay branch')
            if logical_snapshot(store) != references[api]['snapshots'][1 + int(committed)]:
                raise AssertionError('retry table contents or receipt order differs')
            final_evaluation = evaluate_copy(store, folder / 'retry-evaluation.sqlite3', method, True)
            if final_evaluation['result'] != references[api]['evaluations'][1 + int(committed)]['result']:
                raise AssertionError('retry financial output/run ID/evidence differs')
            if store.read_run(initial_run['run_id']) != initial_run:
                raise AssertionError('preexisting saved run changed after retry')
            write(folder / 'retry-state.json', {'response': retry, 'snapshot': logical_snapshot(store),
                                              'evaluation': final_evaluation})
            result['receipt_count_before_retry'] = before['tables']['receipts']['rows']
            result['receipt_count_after_retry'] = logical_snapshot(store)['tables']['receipts']['rows']
            result['retry_outcome'] = retry.get('outcome', retry.get('status'))
            result['status'] = 'PASS'
        finally:
            store.close()
    except Exception as exc:
        result['error'] = {'type': type(exc).__name__, 'message': str(exc)}
    write(folder / 'result.json', result)
    return result


def run(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    bindings = source_bindings()
    shutil.copy2(CATALOG, output / 'preregistered-catalog.json')
    write(output / 'source-before.json', bindings)
    write(output / 'invocation.json', {'argv': sys.argv, 'cwd': str(Path.cwd()), 'interpreter': sys.executable,
         'python': sys.version, 'sqlite': sqlite3.sqlite_version, 'platform': platform.platform(),
         'production_import': __import__('crypto_reconciliation_lab').__file__, 'catalog': proof(CATALOG)})
    config, rows, _ = fixtures('clean')
    request = next(row for row in rows if row['record'].get('ref') == 'A3')
    initial_rows = [row for row in rows if row is not request]
    payload = (dumps(request) + '\n').encode()
    (output / 'request.jsonl').write_bytes(payload)
    (output / 'initial-input.jsonl').write_text(''.join(dumps(row) + '\n' for row in initial_rows))
    write(output / 'config.json', config)
    initial = output / 'initial.sqlite3'
    store = open_store(initial, config)
    try:
        for row in initial_rows:
            response = store.ingest(row['record'], row['received_at'])
            if response['status'] != 'ACCEPTED':
                raise AssertionError('unexpected initial admission')
        initial_run = reconcile(store, BALANCE_AT, KNOWLEDGE_AT)
        assert_financial(initial_run, False)
        initial_snapshot = logical_snapshot(store)
        if initial_snapshot['tables']['receipts']['rows'] != 29:
            raise AssertionError('initial independent receipt count is not 29')
        write(output / 'initial-state.json', {'pragmas': read_pragmas(store), 'run': initial_run,
                                            'snapshot': initial_snapshot})
    finally:
        store.close()
    references = {}
    for api in APIS:
        folder = output / ('reference--' + api)
        folder.mkdir()
        db = folder / 'reference.sqlite3'
        shutil.copy2(initial, db)
        store = open_store(db)
        try:
            snapshots, evaluations, responses = [logical_snapshot(store)], [], []
            evaluations.append(evaluate_copy(store, folder / 'evaluate-0.sqlite3', 'BASELINE', False))
            for ordinal in (1, 2):
                responses.append(invoke(store, api, payload))
                snapshots.append(logical_snapshot(store))
                evaluations.append(evaluate_copy(store, folder / f'evaluate-{ordinal}.sqlite3', 'BASELINE', True))
            references[api] = {'responses': responses, 'snapshots': snapshots, 'evaluations': evaluations}
            if api == 'ordinary_ingest':
                if [r['status'] for r in responses] != ['ACCEPTED', 'DUPLICATE'] or [s['tables']['receipts']['rows'] for s in snapshots] != [29, 30, 31]:
                    raise AssertionError('ordinary literal retry oracle failed')
            elif [r['outcome'] for r in responses] != ['COMMITTED', 'REPLAY'] or [s['tables']['receipts']['rows'] for s in snapshots] != [29, 30, 30]:
                raise AssertionError('restartable literal retry oracle failed')
            write(folder / 'reference.json', references[api])
        finally:
            store.close()
    results = []
    for method in METHODS:
        for api in APIS:
            for stage in STAGES:
                if time.monotonic() - started > 110:
                    results.append({'method': method, 'api': api, 'stage': stage, 'status': 'NOT_RUN', 'reason': 'whole wall reserve'})
                    continue
                results.append(run_trial(output, initial, output / 'request.jsonl', method, api, stage, references, initial_run))
    final_bindings = source_bindings()
    write(output / 'source-after.json', final_bindings)
    disk = sum(path.stat().st_size for path in output.rglob('*') if path.is_file())
    summary = {'format': 'gate4-crash-results-v1', 'trials': results,
               'source_unchanged': bindings == final_bindings,
               'wall_seconds': time.monotonic() - started, 'retained_bytes': disk,
               'status': 'PASS' if len(results) == 20 and all(r['status'] == 'PASS' for r in results) and bindings == final_bindings and disk <= 1073741824 else 'CANDIDATE_NOT_ACCEPTED',
               'power_loss': 'NOT_RUN: process SIGKILL does not remove host/device power',
               'production_change': False}
    write(output / 'summary.json', summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    run_parser = subs.add_parser('run'); run_parser.add_argument('--output', required=True)
    child = subs.add_parser('worker')
    for name in ('db', 'request', 'method', 'api', 'stage', 'ack'):
        child.add_argument('--' + name, required=True)
    for name in ('event-fd', 'gate-fd'):
        child.add_argument('--' + name, type=int, required=True)
    args = parser.parse_args(argv)
    if args.command == 'worker':
        worker(args)
        return 3
    with finite_controller():
        result = run(args.output)
    print(json.dumps({'status': result['status'], 'trials': len(result['trials']), 'wall_seconds': result['wall_seconds']}))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
