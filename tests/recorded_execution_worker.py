"""Private test process: explicit pipe barriers, never a product fault CLI."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch


def emit(kind, **fields):
    print(json.dumps({'type': kind, 'pid': os.getpid(), **fields}, sort_keys=True), file=sys.__stdout__, flush=True)


def command(wanted):
    if sys.stdin.readline().strip() != wanted:
        raise RuntimeError('missing private supervisor command: ' + wanted)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', type=Path, required=True)
    request = json.loads(parser.parse_args().request.read_bytes())
    import crypto_reconciliation_lab as package
    from crypto_reconciliation_lab import Store
    from crypto_reconciliation_lab.execution import reconcile_recorded
    store = Store(request['db'], busy_timeout_ms=request.get('busy_timeout_ms', 250))
    active_store = store

    def settings():
        return {name: active_store.db.execute('PRAGMA ' + name).fetchone()[0]
                for name in ('journal_mode', 'synchronous', 'busy_timeout')}

    def counts():
        return {name: active_store.db.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0]
                for name in ('runs', 'findings', 'evidence', 'correction_groups',
                             'correction_effects', 'execution_contexts', 'recorded_executions')}

    emit('READY', origin=package.__file__, interpreter=sys.executable,
         isolated=bool(sys.flags.isolated), sqlite=sqlite3.sqlite_version,
         settings=settings(), counts=counts())
    command('GO')
    reached = False

    def fault(point):
        nonlocal reached
        if not reached and point == request.get('barrier'):
            reached = True
            emit('BARRIER', point=point, in_transaction=active_store.db.in_transaction,
                 settings=settings(), counts=counts())
            command('CONTINUE')

    if request.get('observe_begin'):
        def trace(sql):
            if sql.strip().upper() == 'BEGIN IMMEDIATE':
                emit('SQL_BEGIN_ATTEMPT', statement='BEGIN IMMEDIATE')
        store.db.set_trace_callback(trace)
    try:
        action = request['action']
        if action == 'recorded':
            # The FIRST operation is the real CLI, with only its imported
            # Python function wrapped to add a private fault callback. Thus the
            # commit barrier is inside that invocation, before its first ACK.
            from crypto_reconciliation_lab.cli import main as cli_main
            stdout, stderr = io.StringIO(), io.StringIO()
            calls = []
            errors = []
            def invoke(cli_store, *args, **kwargs):
                nonlocal active_store
                active_store = cli_store
                try:
                    value = reconcile_recorded(cli_store, *args, **kwargs, _fault=fault)
                    calls.append(value)
                    return value
                except Exception as exc:
                    errors.append(exc)
                    raise
                finally:
                    active_store = store
            argv = ['reconcile-recorded', '--db', request['db'], '--balance-at', request['balance_at'],
                    '--knowledge-at', request['knowledge_at'], '--request-id', request['request_id'],
                    '--busy-timeout-ms', str(request.get('busy_timeout_ms', 250))]
            with patch('crypto_reconciliation_lab.execution.reconcile_recorded', invoke), redirect_stdout(stdout), redirect_stderr(stderr):
                code = cli_main(argv)
            if errors:
                raise errors[0]
            if len(calls) != 1:
                raise AssertionError('CLI must invoke recorded execution once')
            result = calls[0]
            ack = {'argv': argv, 'exit_code': code, 'stdout': stdout.getvalue(), 'stderr': stderr.getvalue()}
        elif action == 'admission':
            from crypto_reconciliation_lab.source_auth.runtime import ingest_signed
            result = ingest_signed(store, Path(request['snapshot']).read_bytes(),
                                   Path(request['envelope']).read_bytes(),
                                   busy_timeout_ms=request.get('busy_timeout_ms', 250),
                                   observed_at='2026-11-15T12:00:00Z')
        elif action == 'policy':
            from crypto_reconciliation_lab.source_auth.runtime import activate_policy
            result = activate_policy(store, request['policy'], request['expected_epoch'],
                                     request['expected_hash'], observed_at='2026-11-15T12:00:00Z')
        else:
            raise ValueError('unknown private worker action')
        final = {'result': result, 'settings': settings(), 'counts': counts()}
        if action == 'recorded':
            final['ack'] = ack
    except Exception as exc:
        reason = getattr(exc, 'reason_code', getattr(exc, 'code', None))
        reason = reason or getattr(exc, 'sqlite_errorname', None) or str(exc).split(':', 1)[0]
        emit('ERROR', reason_code=reason, error_type=type(exc).__name__, error=str(exc),
             in_transaction=store.db.in_transaction, settings=settings(), counts=counts())
        return 2
    finally:
        store.close()
    emit('RESULT', **final)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
