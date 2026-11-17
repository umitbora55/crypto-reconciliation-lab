"""Bounded Gate 4 portability witnesses around unchanged production code.

Public fixture keys provide LAB authority only. Observation wrappers read SQLite
settings; they never repair product settings or alter a transaction boundary.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback

from crypto_reconciliation_lab import Store, reconcile
from crypto_reconciliation_lab.execution import export_execution, read_execution, reconcile_recorded
from crypto_reconciliation_lab.migrations import (application_snapshot, assert_preserved,
    backup_database, migrate_database)
from crypto_reconciliation_lab.source_auth.fixtures import (CONFIG, RECEIVER, BALANCE_AT,
    KNOWLEDGE_AT, financial_records, policy, signed, snapshot)
from crypto_reconciliation_lab.source_auth.runtime import (activate_policy, enable_protection,
    ingest_signed)
from validation_lab.gate4_storage import METHODS, checkpoint, open_store, read_pragmas

REPO = Path(__file__).resolve().parents[1]
ROSTER = ['context.json', 'execution.json', 'run.json', 'summary.json', 'summary.md']
OBSERVED_AT = '2026-11-11T02:00:00.000000Z'
_CONNECT = sqlite3.connect
_CONNECTION_LOG = None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode()


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def write(path, value):
    path = Path(path)
    with path.open('xb') as output:
        output.write(canonical(value) + b'\n')


def namespace(path):
    return {suffix or 'database': identity(Path(str(path) + suffix).read_bytes())
            if Path(str(path) + suffix).is_file() else None
            for suffix in ('', '-wal', '-shm', '-journal')}


def observe(db, phase, target):
    try:
        row = {'phase': phase, 'pid': os.getpid(), 'database': str(target),
               'pragmas': read_pragmas(db),
               'query_only': db.execute('PRAGMA query_only').fetchone()[0]}
    except sqlite3.Error as exc:
        row = {'phase': phase, 'pid': os.getpid(), 'database': str(target), 'error': str(exc)}
    if _CONNECTION_LOG is not None:
        with _CONNECTION_LOG.open('ab') as output:
            output.write(canonical(row) + b'\n')
    return row


class ObservedConnection(sqlite3.Connection):
    def close(self):
        observe(self, 'before_close', getattr(self, '_gate4_target', 'unknown'))
        return super().close()


def observed_connect(*args, **kwargs):
    # All callers in this witness use the standard factory. Fail explicitly if
    # a new product path introduces a custom factory instead of hiding it.
    if 'factory' in kwargs:
        raise ValueError('unexpected custom SQLite factory in observation')
    kwargs['factory'] = ObservedConnection
    db = _CONNECT(*args, **kwargs)
    db._gate4_target = str(args[0] if args else kwargs['database'])
    observe(db, 'after_connect', db._gate4_target)
    return db


def install_observer(path):
    global _CONNECTION_LOG
    _CONNECTION_LOG = Path(path)
    _CONNECTION_LOG.touch(exist_ok=False)
    sqlite3.connect = observed_connect


def check(value, message):
    if not value:
        raise AssertionError(message)


def rejected(call, code=None):
    try:
        call()
    except (ValueError, OSError, sqlite3.Error) as exc:
        result = {'type': type(exc).__name__, 'code': getattr(exc, 'code', None),
                  'message': str(exc)}
        if code is not None:
            check(result['code'] == code or code in str(exc), 'wrong rejection: ' + str(result))
        return result
    raise AssertionError('negative witness unexpectedly succeeded')


def financial_literals(result):
    ledgers = result['ledgers']
    expected = {'ASSET_A': ({'I1': '7', 'I2': '4'}, '11', {'platform': '2', 'external': '9'}),
                'ASSET_B': ({'I1': '0.3', 'I2': '0.2'}, '0.5', {'platform': '0.05', 'external': '0.45'})}
    for asset, (investors, liability, custody) in expected.items():
        ledger = ledgers[asset]
        check((ledger['investor_balances'], ledger['liability'], ledger['custody_rollforward'])
              == (investors, liability, custody), 'literal financial balances differ')


def table_count(db, name):
    return db.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0]


def case_auth(root, method):
    path = root / 'protected.sqlite3'
    feeds = financial_records()
    p1, c1 = snapshot(feeds['P1']), snapshot(feeds['C1'])
    old = signed(p1)
    new = signed(p1, key_id='P1-new')
    custodian = signed(c1, stream='custodian-demo:sample', key_id='C1-key')
    for name, raw in [('p1.jsonl', p1), ('c1.jsonl', c1), ('p1-old.dsse.json', old),
                      ('p1-new.dsse.json', new), ('c1.dsse.json', custodian)]:
        (root / name).write_bytes(raw)
    with closing(open_store(path, CONFIG, method)) as store:
        initial = enable_protection(store, RECEIVER, policy(), observed_at=OBSERVED_AT)
        row = feeds['P1'][0]
        unsigned = rejected(lambda: store.ingest(row['record'], row['received_at']), 'SOURCE_AUTH_REQUIRED')
        from crypto_reconciliation_lab.source_auth.scope import snapshot_bytes
        unsigned_delivery = rejected(lambda: store.ingest_delivery('unsigned', 1, p1.splitlines(keepends=True)[0], snapshot_bytes(p1).plan), 'SOURCE_AUTH_REQUIRED')
        first = ingest_signed(store, p1, old, max_lines=1, observed_at=OBSERVED_AT)
        check(first['status'] == 'INCOMPLETE' and table_count(store.db, 'receipts') == 1, 'first receipt')
        earlier = reconcile_recorded(store, BALANCE_AT, KNOWLEDGE_AT, 'gate4-before-rotation')
        earlier_context = canonical(earlier['context'])
        active = activate_policy(store, policy(True), initial['epoch'], initial['policy_hash'], observed_at=OBSERVED_AT)
        denied = ingest_signed(store, p1, old, observed_at=OBSERVED_AT)
        check(denied['status'] == 'DENIED' and len(denied['responses']) == 1, 'revoked unseen suffix')
        authorization = denied['responses'][0]['authorization']
        check(authorization['decision'] == 'HISTORICAL_REPLAY' and authorization['original_decision_id'] == 1
              and authorization['currently_authorized'] is False, 'original historical acceptance')
        resumed = ingest_signed(store, p1, new, observed_at=OBSERVED_AT)
        accepted_c1 = ingest_signed(store, c1, custodian, observed_at=OBSERVED_AT)
        check(resumed['status'] == accepted_c1['status'] == 'COMPLETE', 'signed completion')
        check(resumed['responses'][0]['outcome'] == 'REPLAY', 'resume must reuse first physical receipt')
        check([r['core_receipt_row_id'] for r in resumed['responses']] == list(range(1, len(feeds['P1']) + 1)), 'ordered receipt identities')
        links = [list(r) for r in store.db.execute('SELECT l.core_receipt_id,d.epoch,e.key_id FROM auth_delivery_links l JOIN auth_decisions d ON d.id=l.decision_id JOIN auth_endorsements e ON e.id=d.endorsement_id ORDER BY l.core_receipt_id')]
        check(links == [[1, 1, 'P1-old']] + [[i, 2, 'P1-new'] for i in range(2, len(feeds['P1']) + 1)]
              + [[i, 2, 'C1-key'] for i in range(len(feeds['P1']) + 1, 31)], 'all original acceptance links')
        check(table_count(store.db, 'receipts') == 30, 'literal receipt count30')
        stale = rejected(lambda: activate_policy(store, policy(True), initial['epoch'], initial['policy_hash'], observed_at=OBSERVED_AT), 'AUTH_POLICY_STALE')
        malformed = {}
        for name, bad in [('truncated', p1[:-1]), ('aborted', p1.splitlines(keepends=True)[0]),
                          ('corrupted', p1.replace(b'"6"', b'"5"', 1)), ('bad_type', 'not bytes'),
                          ('oversized_value', b'{"record":"' + b'x' * 65537 + b'"}\n')]:
            before = table_count(store.db, 'receipts')
            result = ingest_signed(store, bad, new, observed_at=OBSERVED_AT)
            check(result['status'] == 'DENIED' and not result['responses'] and result['rejection']['code'], 'malformed false admission ' + name)
            check(table_count(store.db, 'receipts') == before, 'malformed adds receipt')
            malformed[name] = {'input': identity(bad if type(bad) is bytes else bad.encode()), 'python_type': type(bad).__name__, 'response': result}
        recorded = reconcile_recorded(store, BALANCE_AT, KNOWLEDGE_AT, 'gate4-final')
        financial_literals(recorded['financial_result'])
        check(recorded['context']['acceptance_epochs'] == [1, 2], 'original epoch inventory')
        check(canonical(read_execution(path, earlier['execution_id'])['context']) == earlier_context, 'old context changed')
        check(recorded['context']['counts']['receipts'] == 30, 'eligible replay receipt count')
        snapshot_before = application_snapshot(store.db)
        observe(store.db, 'research_method_ready', path)
        live_files = namespace(path)
        raw_snapshot = root / 'pre-checkpoint-raw'; raw_snapshot.mkdir()
        for suffix, label in (('', 'database'), ('-wal', 'wal'), ('-shm', 'shm')):
            original = Path(str(path) + suffix)
            if original.exists():
                shutil.copyfile(original, raw_snapshot / (label + '.bin'))
        shown = read_execution(path, recorded['execution_id'])
        exported = export_execution(path, recorded['execution_id'], root / 'recorded-export')
        check(shown == recorded, 'read stored recorded result')
        check(sorted(exported['files']) == ROSTER, 'five-file export roster')
        folder = root / 'recorded-export'
        check((folder / 'context.json').read_bytes() == canonical(recorded['context']), 'context bytes')
        raw_run = store.db.execute('SELECT CAST(payload AS BLOB) FROM runs WHERE id=?', (recorded['run_id'],)).fetchone()[0]
        check((folder / 'run.json').read_bytes() == raw_run, 'saved financial bytes')
        check(application_snapshot(store.db) == snapshot_before, 'read/export changed logical source')
        after_read_files = namespace(path)
        namespace_errors = {}
        for suffix in ('', '-wal', '-shm', '-journal'):
            target = Path(str(path) + suffix)
            namespace_errors[suffix or 'database'] = rejected(lambda target=target: export_execution(path, recorded['execution_id'], target / 'child'), 'EXECUTION_OUTPUT')
        repeat = rejected(lambda: export_execution(path, recorded['execution_id'], folder), 'EXECUTION_OUTPUT')
        marker = root / 'existing-export'; marker.mkdir(); (marker / 'marker').write_bytes(b'preserve')
        existing = rejected(lambda: export_execution(path, recorded['execution_id'], marker), 'EXECUTION_OUTPUT')
        check((marker / 'marker').read_bytes() == b'preserve', 'existing output overwritten')
        link = root / 'dangling-export'; link.symlink_to('absent-target')
        dangling = rejected(lambda: export_execution(path, recorded['execution_id'], link), 'EXECUTION_OUTPUT')
        check(link.is_symlink() and not (root / 'absent-target').exists(), 'dangling output altered')
        backup = root / 'online-backup.sqlite3'
        backup_database(path, backup)
        with closing(sqlite3.connect(backup)) as copied:
            check(application_snapshot(copied) == snapshot_before, 'online backup changed exact logical state')
        backup_bytes = backup.read_bytes()
        backup_repeat = rejected(lambda: backup_database(path, backup), 'never overwrite')
        check(backup.read_bytes() == backup_bytes, 'backup overwritten')
        # Copy only while this sole writer is quiescent: this is not a general
        # concurrently mutable file-copy backup recipe.
        sidecopy = root / 'quiescent-copy'; sidecopy.mkdir()
        copied_path = sidecopy / path.name
        copied_files = {}
        for suffix in ('', '-wal', '-shm'):
            original = Path(str(path) + suffix)
            if original.exists():
                shutil.copyfile(original, Path(str(copied_path) + suffix))
                copied_files[suffix or 'database'] = identity(original.read_bytes())
        with closing(sqlite3.connect(copied_path)) as copied:
            check(application_snapshot(copied) == snapshot_before, 'quiescent db+sidecars copy differs')
        dbonly = root / 'db-only.sqlite3'; shutil.copyfile(path, dbonly)
        with closing(sqlite3.connect(dbonly)) as copied:
            dbonly_receipts = table_count(copied, 'receipts')
            dbonly_equal = application_snapshot(copied) == snapshot_before
        check(dbonly_equal if method == 'BASELINE' else not dbonly_equal, 'DB-only copy risk witness not established')
        before_checkpoint = namespace(path); start = time.perf_counter()
        checkpoint_result = checkpoint(store)
        checkpoint_seconds = time.perf_counter() - start
        after_checkpoint = namespace(path)
        check(application_snapshot(store.db) == snapshot_before, 'checkpoint changes logical state')
        source_snapshot = snapshot_before
        result = {'unsigned': unsigned, 'unsigned_delivery': unsigned_delivery, 'first': first,
            'revoked_suffix': denied, 'resumed': resumed, 'custodian': accepted_c1, 'stale_policy': stale,
            'malformed': malformed, 'links': links, 'active_policy': active,
            'earlier_execution_id': earlier['execution_id'], 'execution_id': recorded['execution_id'],
            'run_id': recorded['run_id'], 'source_snapshot': source_snapshot,
            'five_files': exported['files'], 'before_read_files': live_files, 'after_read_files': after_read_files,
            'namespace_rejections': namespace_errors, 'existing_rejections': [repeat, existing, dangling],
            'backup_repeat': backup_repeat, 'quiescent_copy_files': copied_files,
            'db_only_copy': {'receipts': dbonly_receipts, 'exact_logical_equal': dbonly_equal},
            'checkpoint': {'before': before_checkpoint, 'after': after_checkpoint,
                           'seconds': checkpoint_seconds, 'result': checkpoint_result},
            'financial_result': recorded['financial_result']}
    result['after_close_files'] = namespace(path)
    with closing(Store(path)) as reopened:
        result['ordinary_reopen_pragmas'] = read_pragmas(reopened)
        check(application_snapshot(reopened.db) == source_snapshot, 'ordinary reopen differs')
        check(result['ordinary_reopen_pragmas']['synchronous'] == 2, 'ordinary reopen durability differs')
    before_closed_show = namespace(path)
    check(read_execution(path, result['execution_id'])['run_id'] == result['run_id'], 'closed show differs')
    result['closed_show_namespace'] = {'before': before_closed_show, 'after': namespace(path)}
    return result


def case_review(root, method, auth):
    from crypto_reconciliation_lab.review.export import export_selection
    database = root / 'protected.sqlite3'
    selection = root / 'review-selection.json'
    write(selection, {'format': 'review-selection-v1', 'sources': [
        {'alias': 'synthetic', 'database': str(database), 'run_ids': [auth['run_id']]}]})
    # The preceding mode=ro recorded read can itself create WAL/SHM. Close an
    # ordinary writer after a checkpoint before testing the header-only case.
    # Do not remove sidecars manually or convert the source to DELETE.
    with closing(open_store(database, method=method)) as store:
        final_checkpoint = checkpoint(store)
    before = namespace(database)
    check(all(before[suffix] is None for suffix in ('-wal', '-shm', '-journal')),
          'header-only review witness still has sidecars')
    header_mode = list(database.read_bytes()[18:20])
    if method == 'BASELINE':
        result = export_selection(selection, root / 'review-export')
        check(namespace(database) == before, 'review source bytes altered')
        return {'compatible': True, 'closed_result': result, 'source_unchanged': True,
                'closed_namespace': before, 'header_mode_bytes': header_mode,
                'checkpoint_result': final_checkpoint}
    closed = rejected(lambda: export_selection(selection, root / 'review-export-closed'), 'SNAPSHOT_UNSUPPORTED')
    check(namespace(database) == before, 'closed rejection changes source')
    check('WAL or unknown database header mode' in closed['message'] and header_mode == [2, 2],
          'header-only WAL rejection not observed')
    with closing(open_store(database, method=method)) as store:
        live_before = namespace(database)
        live = rejected(lambda: export_selection(selection, root / 'review-export-live'), 'SNAPSHOT_UNSUPPORTED')
        check(namespace(database) == live_before, 'live rejection changes source')
    return {'compatible': False, 'acceptance_invariant': 'FAIL', 'candidate_status': 'CANDIDATE_NOT_ACCEPTED',
            'closed_rejection': closed, 'live_rejection': live,
            'closed_namespace': before, 'header_mode_bytes': header_mode,
            'checkpoint_result': final_checkpoint,
            'reason': 'Existing read-only financial review requires a closed rollback-journal snapshot; WAL is unsupported even after checkpoint/close.'}


def case_replay(root, auth):
    from crypto_reconciliation_lab.replay import verify_execution_replay
    folder = root / 'recorded-export'
    context, run, expected = folder / 'context.json', folder / 'run.json', auth['execution_id']
    # This invocation is the unmodified public API with its default30-second
    # worker deadline. Its ephemeral worker files are intentionally not claimed
    # as retained; the additional observed worker below retains its transcript.
    native = verify_execution_replay(context, run, expected, output=root / 'native-replay')
    check((native['status'], native['reason_code']) == ('REPRODUCED', 'REPLAY_REPRODUCED'), 'native original replay')
    native_summary = root / 'native-replay' / 'report.json'
    before = native_summary.read_bytes()
    existing = verify_execution_replay(context, run, expected, output=root / 'native-replay')
    check(existing['reason_code'] == 'REPLAY_OUTPUT' and native_summary.read_bytes() == before, 'replay overwrite guard')
    wrong = verify_execution_replay(context, run, '0' * 64)
    check(wrong['status'] == 'ERROR', 'unbound external identity accepted')
    truncated = root / 'truncated-context.json'; truncated.write_bytes(context.read_bytes()[:-1])
    invalid = verify_execution_replay(truncated, run, expected)
    check(invalid['status'] == 'ERROR', 'truncated context accepted')
    evidence = root / 'observed-replay-worker'; evidence.mkdir()
    shutil.copyfile(context, evidence / 'context.input'); shutil.copyfile(run, evidence / 'run.input')
    command = [sys.executable, '-B', '-m', 'validation_lab.gate4_portability', 'replay-worker',
               '--output', str(evidence), '--expected', expected]
    observation = recorded_command(command, evidence / 'command', timeout=30)
    check(observation['exit_code'] == 0, 'observed replay worker failure')
    observed_result = json.loads((evidence / 'result.json').read_bytes())
    check(observed_result['status'] == native['status'] and observed_result['comparison'] == native['comparison'], 'observed/native replay mismatch')
    return {'eligible_receipts': 30, 'default_worker_timeout_seconds': 30, 'native': native,
            'existing_output': existing, 'wrong_identity': wrong, 'truncated': invalid,
            'observed_worker': observation,
            'native_worker_pragma_readback': 'NOT_OBSERVED; separate identical compute path observed in retained child',
            'observed_worker_result': observed_result}


def case_migration(root, method):
    path = root / 'legacy5.sqlite3'
    with closing(open_store(path, CONFIG, method, target_schema=5)) as store:
        for rows in financial_records().values():
            for row in rows:
                store.ingest(row['record'], row['received_at'])
        saved = reconcile(store, BALANCE_AT, KNOWLEDGE_AT)
        financial_literals(saved)
        before = application_snapshot(store.db)
    def fail(point):
        if point == 'migration_before_commit':
            raise ValueError('gate4 controlled migration-before-commit')
    failure = rejected(lambda: migrate_database(path, root / 'backups', fail), 'gate4 controlled')
    with closing(Store(path)) as store:
        check(application_snapshot(store.db) == before, 'aborted migration changes schema/data')
        check(store.read_run(saved['run_id']) == saved, 'old run after aborted migration')
    migrated = migrate_database(path, root / 'backups')
    check((migrated['status'], migrated['from_version'], migrated['schema_version']) == ('MIGRATED', 5, 6), 'migration status')
    with closing(Store(path)) as store:
        assert_preserved(store.db, before)
        check(store.read_run(saved['run_id']) == saved, 'migration changes financial run')
        observed = read_pragmas(store)
    restored = root / 'restored5.sqlite3'; backup_database(migrated['backup'], restored)
    with closing(Store(restored)) as store:
        check(application_snapshot(store.db) == before, 'restored old schema differs')
    idempotent = migrate_database(path, root / 'unused-backups')
    check(idempotent['status'] == 'ALREADY_CURRENT', 'migration repeat not idempotent')
    bad = root / 'corrupt.sqlite3'; bad.write_bytes(b'not a database')
    corruption = rejected(lambda: Store(bad))
    return {'injected_failure': failure, 'migrated': migrated, 'reopened_pragmas': observed,
            'restored_snapshot': before, 'idempotent': idempotent, 'corrupt_database_rejection': corruption}


def recorded_command(argv, target, timeout):
    target = Path(target); target.mkdir(parents=True, exist_ok=False)
    started = time.time(); timer = time.perf_counter()
    with (target / 'stdout.txt').open('xb') as stdout, (target / 'stderr.txt').open('xb') as stderr:
        process = subprocess.Popen(argv, cwd=REPO, stdin=subprocess.DEVNULL,
                                   stdout=stdout, stderr=stderr, start_new_session=True)
        timeout_hit = False
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timeout_hit = True
            os.killpg(process.pid, 9); code = process.wait()
        except BaseException:
            if process.poll() is None:
                os.killpg(process.pid, 9)
            process.wait()
            raise
    result = {'argv': argv, 'cwd': str(REPO), 'pid': process.pid, 'owned_and_reaped': True,
              'started_unix': started, 'seconds': time.perf_counter() - timer,
              'timeout_seconds': timeout, 'timeout': timeout_hit, 'exit_code': code,
              'stdout': identity((target / 'stdout.txt').read_bytes()),
              'stderr': identity((target / 'stderr.txt').read_bytes())}
    write(target / 'command.json', result)
    return result


def worker(root, method):
    root.mkdir(parents=True, exist_ok=False)
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    resource.setrlimit(resource.RLIMIT_AS, (805306368, 805306368))
    resource.setrlimit(resource.RLIMIT_FSIZE, (67108864, 67108864))
    install_observer(root / 'sqlite-connections.jsonl')
    results = {}
    auth = None
    for name in ('auth_export_backup', 'legacy_review', 'offline_replay', 'migration_restore'):
        start = time.perf_counter()
        try:
            if name == 'auth_export_backup':
                auth = case_auth(root, method); value = auth
            elif name == 'legacy_review':
                check(auth is not None, 'prerequisite auth fixture unavailable'); value = case_review(root, method, auth)
            elif name == 'offline_replay':
                check(auth is not None, 'prerequisite auth fixture unavailable'); value = case_replay(root, auth)
            else:
                value = case_migration(root, method)
            results[name] = {'status': 'PASS', 'seconds': time.perf_counter() - start, 'result': value}
        except Exception as exc:
            results[name] = {'status': 'ERROR', 'seconds': time.perf_counter() - start,
                             'error': str(exc), 'traceback': traceback.format_exc()}
        write(root / (name + '.json'), results[name])
    result = {'method': method, 'checks': results, 'status': 'PASS' if all(r['status'] == 'PASS' for r in results.values()) else 'ERROR',
              'acceptance': 'CANDIDATE_NOT_ACCEPTED' if method == 'CANDIDATE_WAL_FULL' else 'BASELINE_OBSERVATION',
              'unverified': ['network_filesystems', 'abrupt_power_loss', 'native_ephemeral_replay_worker_PRAGMAs']}
    write(root / 'result.json', result)
    print(json.dumps({'method': method, 'status': result['status'], 'acceptance': result['acceptance']}))
    return 0 if result['status'] == 'PASS' else 1


def compare_results(results):
    if len(results) != 2 or {r.get('method') for r in results} != set(METHODS):
        raise ValueError('exact distinct method roster required')
    by_method = {r['method']: r for r in results}
    required = {'auth_export_backup', 'legacy_review', 'offline_replay', 'migration_restore'}
    for result in results:
        if set(result.get('checks', {})) != required or any(r.get('status') != 'PASS' or 'result' not in r for r in result['checks'].values()):
            raise ValueError('complete successful witness roster required')
    left, right = [by_method[m]['checks']['auth_export_backup']['result'] for m in METHODS]
    equality = {key: left[key] == right[key] for key in
                ('source_snapshot', 'five_files', 'financial_result', 'links', 'execution_id', 'run_id')}
    if not all(equality.values()):
        raise ValueError('cross-method logical/export evidence differs: ' + repr(equality))
    check(by_method['BASELINE']['checks']['legacy_review']['result']['compatible'] is True, 'baseline review')
    check(by_method['CANDIDATE_WAL_FULL']['checks']['legacy_review']['result']['compatible'] is False, 'candidate incompatibility lost')
    return {'logical_and_export_equality': equality, 'witness_status': 'PASS',
            'candidate_acceptance': 'CANDIDATE_NOT_ACCEPTED', 'decision_under_existing_invariants': 'NO_CHANGE',
            'reason': 'Confirmed incompatibility: existing closed financial-review export rejects WAL. Untested device and power-loss guarantees are separate limitations.'}


def run(root):
    root.mkdir(parents=True, exist_ok=False)
    catalogue = REPO / 'contracts/gate4-portability-catalog.json'
    write(root / 'preregistration.json', {'path': str(catalogue), **identity(catalogue.read_bytes()),
         'read_before_execution_unix': time.time()})
    sources = sorted((REPO / 'crypto_reconciliation_lab').rglob('*.py')) + [Path(__file__), REPO / 'validation_lab/gate4_storage.py']
    write(root / 'source-before.json', {str(p.relative_to(REPO)): identity(p.read_bytes()) for p in sources})
    (root / 'harness-source.py').write_bytes(Path(__file__).read_bytes())
    results, commands = [], []
    for method in METHODS:
        target = root / method
        argv = [sys.executable, '-B', '-m', 'validation_lab.gate4_portability', 'worker', '--method', method, '--output', str(target)]
        commands.append(recorded_command(argv, root / (method + '-command'), 180))
        if (target / 'result.json').is_file():
            results.append(json.loads((target / 'result.json').read_bytes()))
    try:
        compared = compare_results(results)
    except Exception as exc:
        compared = {'witness_status': 'ERROR', 'candidate_acceptance': 'CANDIDATE_NOT_ACCEPTED', 'error': str(exc)}
    files = [p for p in root.rglob('*') if p.is_file() and not p.is_symlink()]
    total_bytes = sum(p.stat().st_size for p in files)
    compared.update(commands=commands, retained_logical_bytes=total_bytes,
                    within_disk_budget=total_bytes <= 268435456)
    after = {str(p.relative_to(REPO)): identity(p.read_bytes()) for p in sources}
    write(root / 'source-after.json', after)
    compared['source_unchanged'] = after == json.loads((root / 'source-before.json').read_bytes())
    write(root / 'summary.json', compared)
    print(json.dumps(compared, sort_keys=True))
    return 0 if compared['witness_status'] == 'PASS' and compared['source_unchanged'] and compared['within_disk_budget'] else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('run', 'worker', 'replay-worker'))
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--method', choices=METHODS)
    parser.add_argument('--expected')
    args = parser.parse_args()
    if args.action == 'run':
        return run(args.output)
    if args.action == 'worker':
        return worker(args.output, args.method)
    install_observer(args.output / 'sqlite-connections.jsonl')
    from crypto_reconciliation_lab.replay.worker import verify_bytes
    result = verify_bytes((args.output / 'context.input').read_bytes(),
                          (args.output / 'run.input').read_bytes(), args.expected)
    write(args.output / 'result.json', result)
    return 0 if result['status'] == 'REPRODUCED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
