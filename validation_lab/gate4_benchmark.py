"""Fixed Gate 4 DELETE/FULL versus WAL/FULL research experiment.

No production settings, financial calculations or transaction boundaries change.
Every started worker is owned and waited even after controller errors/signals.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import random
import resource
import shutil
import signal
import sqlite3
import stat
import statistics
import subprocess
import sys
import time

from validation_lab import benchmark as original
from validation_lab import benchmark_gate2 as gate2
from validation_lab.gate3_capacity import Recorder, observe_calls
from validation_lab.gate4_storage import (METHODS, checkpoint, disk_snapshot,
                                         logical_snapshot, open_store, read_pragmas)

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / 'contracts/gate4-benchmark-protocol.json'
ACTIVE = None


def write(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.writing')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')
    temporary.replace(path)


def proof(path):
    return original.file_proof(path)


def source_bindings(root=ROOT):
    names = [str(p.relative_to(root)) for p in (root / 'crypto_reconciliation_lab').rglob('*')
             if p.is_file() and p.suffix in ('.py', '.json')]
    names += ['validation_lab/benchmark.py', 'validation_lab/benchmark_gate2.py',
              'validation_lab/gate3_capacity.py', 'validation_lab/gate4_storage.py',
              'validation_lab/gate4_benchmark.py', 'contracts/gate4-benchmark-protocol.json']
    if (root / 'contracts/gate4-benchmark-continuation.json').exists():
        names.append('contracts/gate4-benchmark-continuation.json')
    return {name: proof(root / name) for name in sorted(names)}


def disk_bytes(root):
    total = 0
    for path in Path(root).rglob('*'):
        try:
            observation = path.stat()
        except FileNotFoundError:
            continue
        if stat.S_ISREG(observation.st_mode):
            total += observation.st_size
    return total


def process_sample(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        status = dict(line.split(':', 1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
        return {'cpu_seconds': (int(fields[11]) + int(fields[12])) / os.sysconf('SC_CLK_TCK'),
                'rss_kib': int(status.get('VmRSS', '0 kB').split()[0])}
    except (FileNotFoundError, ProcessLookupError):
        return None


def host_observation():
    commands = {}
    for command in (['uname', '-a'], ['findmnt', '-T', str(ROOT), '-o', 'TARGET,SOURCE,FSTYPE,OPTIONS'], ['df', '-T', str(ROOT)]):
        try:
            result = subprocess.run(command, text=True, capture_output=True, timeout=5)
            commands[' '.join(command)] = {'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
        except (OSError, subprocess.TimeoutExpired) as exc:
            commands[' '.join(command)] = {'error': repr(exc)}
    packages = {}
    for name in ('pip', 'setuptools', 'wheel', 'build', 'cryptography', 'scikit-learn', 'numpy'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = 'NOT_INSTALLED'
    return {'python': sys.version, 'interpreter': sys.executable, 'sqlite': sqlite3.sqlite_version,
            'platform': platform.platform(), 'affinity': sorted(os.sched_getaffinity(0)),
            'loadavg': os.getloadavg(), 'cpuinfo': Path('/proc/cpuinfo').read_text(),
            'commands': commands, 'packages': packages,
            'cgroup': {name: (Path('/sys/fs/cgroup') / name).read_text().strip()
                       for name in ('cpu.max', 'memory.max') if (Path('/sys/fs/cgroup') / name).exists()}}


def receipt_digest(envelope):
    # Independent canonical serializer, no production digest/normalizer call.
    return hashlib.sha256(json.dumps(envelope, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def run_worker(input_path, output, method, instrumented=False):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started, cpu_started = time.perf_counter(), time.process_time()
    phases, committed, store = {}, 0, None
    observer = Recorder(output) if instrumented else None
    io_before = gate2.physical_io()

    def progress(name, state):
        write(output / 'progress.json', {'phase': name, 'state': state,
              'committed_receipts_periodic_lower_bound': committed,
              'elapsed_seconds': time.perf_counter() - started, 'completed_phases': phases})

    def phase(name, function):
        prior = observer.phase if observer else None
        if observer:
            observer.phase = name
        progress(name, 'STARTED')
        w, c = time.perf_counter(), time.process_time()
        try:
            value = function()
        finally:
            if observer:
                observer.phase = prior
        phases[name] = {'wall_seconds': time.perf_counter() - w, 'cpu_seconds': time.process_time() - c}
        progress(name, 'COMPLETED')
        return value

    raw = phase('input_read', lambda: Path(input_path).read_bytes())
    data = phase('json_parse', lambda: json.loads(raw))
    phase('validate_fixed_synthetic_contract', lambda: gate2.finite_gate(data))
    from crypto_reconciliation_lab import reconcile
    db_path = output / 'input.sqlite3'
    try:
        with observe_calls(observer) if observer else nullcontext():
            store = phase('initialize_including_journal_conversion', lambda: open_store(db_path, data['config'], method))
            initial = read_pragmas(store)
            save_run = store.save_run
            # Delegates once, with original arguments/returns. No adapter persistence.
            store.save_run = lambda result, **kwargs: phase('run_persistence', lambda: save_run(result, **kwargs))
            with (output / 'receipts.jsonl').open('w') as receipt_log:
                def ingest():
                    nonlocal committed
                    for ordinal, envelope in enumerate(data['rows'], 1):
                        answer = store.ingest(envelope['record'], envelope['received_at'])
                        if answer['status'] != 'ACCEPTED' or answer['receipt_id'] != receipt_digest(envelope) or store.db.in_transaction:
                            raise AssertionError('receipt response/identity/commit boundary differs')
                        committed += 1
                        receipt_log.write(json.dumps({'ordinal': ordinal, **answer}, sort_keys=True, separators=(',', ':')) + '\n')
                        if committed % 1000 == 0:
                            progress('ingest', 'RUNNING')
                phase('ingest', ingest)
            full = phase('reconcile_including_run_persistence', lambda: reconcile(store, data['balance_at'], data['knowledge_at']))
            text = phase('canonical_export_serialization', lambda: gate2.payload(full))
            phase('canonical_export_write', lambda: (output / 'export.json').write_text(text))
            def verify():
                expected = original.with_findings(original.analytic_oracle(data['events'], data['seed']), data)
                observed = original.project_production(full)
                if observed != expected or store.read_run(full['run_id']) != full:
                    raise AssertionError('outside-engine arithmetic/persisted evidence mismatch')
                ids = [row[0] for row in store.db.execute('SELECT receipt_hash FROM receipts ORDER BY id')]
                if ids != [receipt_digest(envelope) for envelope in data['rows']]:
                    raise AssertionError('ordered receipt identity mismatch')
                if json.loads((output / 'export.json').read_text()) != full:
                    raise AssertionError('canonical export differs')
                return observed
            projection = phase('reread_financial_and_receipt_verification', verify)
            logical = phase('logical_table_verification', lambda: logical_snapshot(store))
            phase('logical_snapshot_write', lambda: write(output / 'logical-snapshot.json', logical))
            disk_before = disk_snapshot(db_path)
            checkpoint_result = phase('explicit_final_checkpoint', lambda: checkpoint(store))
            if checkpoint_result[0] != 0:
                raise AssertionError('checkpoint busy')
            disk_after = disk_snapshot(db_path)
            phase('close', store.close)
            store = None
            store = phase('reopen', lambda: open_store(db_path, method=method))
            reopened = read_pragmas(store)
            def verify_reopen():
                if store.read_run(full['run_id']) != full or logical_snapshot(store) != logical:
                    raise AssertionError('reopened persisted evidence differs')
                integrity = store.db.execute('PRAGMA integrity_check').fetchone()[0]
                if integrity != 'ok' or store.db.execute('PRAGMA foreign_key_check').fetchall():
                    raise AssertionError('integrity/foreign key check failed')
                return integrity
            integrity = phase('reopen_logical_and_integrity_verification', verify_reopen)
            phase('final_close', store.close)
            store = None
    finally:
        if store is not None:
            store.close()
        if observer:
            observer.close()
    result = {'format': 'gate4-worker-v1', 'status': 'PASS', 'method': method,
              'events': data['events'], 'seed': data['seed'], 'instrumented': instrumented,
              'physical_receipts': committed, 'wall_seconds': time.perf_counter() - started,
              'cpu_seconds': time.process_time() - cpu_started,
              'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              'phases': phases, 'pragmas_initial': initial, 'pragmas_reopen': reopened,
              'logical_snapshot': logical, 'counts': {k: v['rows'] for k, v in logical['tables'].items()},
              'ordered_receipts_sha256': logical['ordered_receipts_sha256'],
              'financial_projection': projection, 'run_id': full['run_id'],
              'checkpoint_result': checkpoint_result, 'disk_before_checkpoint': disk_before,
              'disk_after_checkpoint': disk_after, 'disk_after_close': disk_snapshot(db_path),
              'integrity_check': integrity, 'buckets': dict(observer.buckets) if observer else {},
              'input': proof(input_path), 'physical_io_before': io_before, 'physical_io_after': gate2.physical_io(),
              'artifacts': {name: proof(output / name) for name in ('input.sqlite3', 'export.json', 'receipts.jsonl', 'logical-snapshot.json')},
              'qualifications': ['All primary trials include unchanged Store full persistence and full canonical result export.',
                'Nested run_persistence is included in reconcile; phase totals are not additive.',
                'Instrumented COMMIT execute time includes implicit SQLite auto-checkpoint work where triggered; physical device latency is unknown.',
                'Final checkpoint runs on both methods inside timed work, including close and reopened readback.',
                'Off still has phase, receipt-id/readback and progress diagnostics; overhead controls estimate incremental observer overhead.',
                'ru_maxrss is whole child high water; sampled RSS is separately recorded, neither is isolated allocation.']}
    result['export_sha256'] = result['artifacts']['export.json']['sha256']
    write(output / 'metrics.json', result)
    return result


def equivalent(left, right):
    keys = ('input', 'physical_receipts', 'logical_snapshot', 'financial_projection',
            'run_id', 'export_sha256', 'ordered_receipts_sha256')
    return all(left.get(key) == right.get(key) for key in keys)


def bootstrap_median(values, seed=424271, samples=10000):
    if not values:
        raise ValueError('empty paired values')
    rng = random.Random(seed)
    draws = sorted(statistics.median(rng.choices(values, k=len(values))) for _ in range(samples))
    return [draws[int(samples * .025)], draws[int(samples * .975) - 1]]


def summarize(trials, protocol):
    profiles = []
    for events in (10000, 25000):
        pairs = []
        for pair in range(1, 8):
            rows = [t for t in trials if t['role'] == 'paired' and t['events'] == events and t['pair'] == pair]
            by_method = {t['method']: t for t in rows}
            if len(rows) != 2 or set(by_method) != set(METHODS) or any(t['status'] != 'PASS' for t in rows):
                continue
            b, c = (by_method[method] for method in METHODS)
            if not equivalent(b['metrics'], c['metrics']):
                continue
            bw, cw = b['parent_wall_seconds'], c['parent_wall_seconds']
            pairs.append({'pair': pair, 'baseline_seconds': bw, 'candidate_seconds': cw,
                          'difference_seconds': bw - cw, 'gain_fraction': (bw - cw) / bw})
        profile = {'events': events, 'expected_pairs': 7, 'complete_equivalent_pairs': len(pairs), 'pairs': pairs}
        if pairs:
            gains = [p['gain_fraction'] for p in pairs]
            differences = [p['difference_seconds'] for p in pairs]
            profile.update(baseline_median_seconds=statistics.median(p['baseline_seconds'] for p in pairs),
                candidate_median_seconds=statistics.median(p['candidate_seconds'] for p in pairs),
                median_paired_difference_seconds=statistics.median(differences),
                median_paired_gain_fraction=statistics.median(gains),
                paired_difference_bootstrap95=bootstrap_median(differences),
                paired_gain_bootstrap95=bootstrap_median(gains),
                baseline_empirical_p95_equals_observed_max_seconds=max(p['baseline_seconds'] for p in pairs),
                candidate_empirical_p95_equals_observed_max_seconds=max(p['candidate_seconds'] for p in pairs))
        profile['speed_threshold_met'] = bool(len(pairs) == 7 and profile.get('median_paired_gain_fraction', -1) >= protocol['threshold']['median_paired_gain_fraction'] and profile.get('paired_gain_bootstrap95', [-1])[0] > protocol['threshold']['bootstrap_lower_gain_fraction'])
        profiles.append(profile)
    controls = []
    for method in METHODS:
        rows = [t for t in trials if t['role'] == 'instrumentation_control' and t['method'] == method]
        off = next((t for t in rows if not t['instrumented']), None)
        on = next((t for t in rows if t['instrumented']), None)
        value = {'method': method, 'n_pairs': 1, 'status': 'NOT_RUN'}
        if off and on and off['status'] == on['status'] == 'PASS':
            equal = equivalent(off['metrics'], on['metrics'])
            value.update(status='PASS' if equal else 'NON_EQUIVALENT', equivalent=equal,
                         off_parent_seconds=off['parent_wall_seconds'], on_parent_seconds=on['parent_wall_seconds'],
                         incremental_seconds=on['parent_wall_seconds'] - off['parent_wall_seconds'],
                         incremental_fraction=on['parent_wall_seconds'] / off['parent_wall_seconds'] - 1)
        controls.append(value)
    eligible = all(p['speed_threshold_met'] for p in profiles) and all(t['status'] == 'PASS' for t in trials) and all(c['status'] == 'PASS' for c in controls)
    return {'format': 'gate4-benchmark-summary-v1', 'profiles': profiles, 'instrumentation_controls': controls,
            'performance_gate': 'MATERIAL_GAIN' if eligible else 'NO_CHANGE',
            'candidate_acceptance': 'PENDING_SEMANTICS_CRASH_PORTABILITY_AND_INDEPENDENT_READER',
            'n_small_warning': 'Seven fixed pairs estimate this host/workload only. Bootstrap interval is not an institutional SLA; empirical p95 is sample maximum.',
            'method': 'Primary endpoint parent wall includes startup, all worker validation, full persistence/export, final checkpoint, close/reopen and process completion. All fixed paired rows retained; missing pairs not refilled.'}


def kill_wait(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return process.wait()


def controller_limits(budgets):
    # The effective parent bound is its soft limit. A separate inherited hard
    # ceiling must permit the explicitly larger, still bounded child limit.
    resource.setrlimit(resource.RLIMIT_AS, (budgets['controller_address_space_bytes'],
        max(budgets['controller_address_space_bytes'], budgets['worker_address_space_bytes'])))


def launch_owned(command, *, cwd, stdout, stderr):
    global ACTIVE
    mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM, signal.SIGINT, signal.SIGTERM})
    try:
        ACTIVE = subprocess.Popen(command, cwd=cwd, stdout=stdout, stderr=stderr, start_new_session=True)
        return ACTIVE
    finally:
        # A pending exception-producing signal now sees the assigned child.
        signal.pthread_sigmask(signal.SIG_SETMASK, mask)


def stopped_readback(folder):
    path = folder / 'input.sqlite3'
    if not path.exists():
        return {'status': 'NOT_RUN', 'reason': 'database absent'}
    copy = folder / 'recovery-copy'
    copy.mkdir()
    bindings = {}
    for original_path in folder.glob('input.sqlite3*'):
        if original_path.is_file():
            bindings[original_path.name] = proof(original_path)
            shutil.copyfile(original_path, copy / original_path.name)
    try:
        with sqlite3.connect(copy / path.name, timeout=1) as db:
            read_deadline = time.monotonic() + 10
            db.set_progress_handler(lambda: int(time.monotonic() >= read_deadline), 10000)
            counts = {name: db.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0] for name in ('records', 'receipts', 'runs', 'findings', 'evidence')}
            result = {'status': 'PASS', 'committed_counts': counts, 'integrity_check': db.execute('PRAGMA integrity_check').fetchone()[0]}
    except (sqlite3.Error, ValueError) as exc:
        result = {'status': 'ERROR', 'error': repr(exc)}
    finally:
        shutil.rmtree(copy)
    result.update(original_artifacts=bindings, originals_unchanged=all(proof(folder / name) == pin for name, pin in bindings.items()), qualification='Recovery on a copied stopped database; this is not a durable ACK or RPO claim.')
    return result


def validate_protocol(protocol):
    if protocol['format'] != 'gate4-benchmark-protocol-v1' or protocol['methods'] != list(METHODS):
        raise ValueError('protocol format/method mismatch')
    rows = protocol['roster']
    if len(rows) != 34 or len({t['id'] for t in rows}) != len(rows):
        raise ValueError('exact unique fixed roster required')
    for events in (10000, 25000):
        for pair in range(1, 8):
            chosen = [t for t in rows if t['role'] == 'paired' and t['events'] == events and t['pair'] == pair]
            if len(chosen) != 2 or {t['method'] for t in chosen} != set(METHODS):
                raise ValueError('paired roster incomplete')
    if any(t['method'] not in METHODS for t in rows):
        raise ValueError('unknown method')


def program(output, protocol_path, input_audit):
    global ACTIVE
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    protocol = json.loads(Path(protocol_path).read_text())
    validate_protocol(protocol)
    budgets = protocol['budgets']
    controller_limits(budgets)
    budget_root = Path(protocol.get('continuation', {}).get('owned_disk_root', output))
    start, cpu_start = time.monotonic(), time.process_time()
    initial_children = resource.getrusage(resource.RUSAGE_CHILDREN)
    record = {'format': 'gate4-benchmark-ledger-v1', 'status': 'RUNNING', 'trials': [],
              'argv': sys.argv, 'cwd': str(ROOT), 'protocol': protocol, 'protocol_proof': proof(protocol_path),
              'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'host': host_observation(), 'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'tree': subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=ROOT, text=True).strip()}
    record['effective_controller_rlimit_as'] = list(resource.getrlimit(resource.RLIMIT_AS))
    if protocol.get('continuation'):
        prior = protocol['continuation']
        for name, expected in prior['prior_file_proofs'].items():
            if proof(Path(name)) != expected:
                raise ValueError('PRIOR_ATTEMPT_CHANGED: ' + name)
        record['continuation'] = prior
    stop = None
    peak_disk = 0
    old_handler = signal.getsignal(signal.SIGALRM)
    old_term_handler = signal.getsignal(signal.SIGTERM)
    def deadline(signum, frame):
        raise TimeoutError('TOTAL_WALL_BUDGET')
    signal.signal(signal.SIGALRM, deadline)
    def terminated(signum, frame):
        raise RuntimeError('CONTROLLER_TERMINATED')
    signal.signal(signal.SIGTERM, terminated)
    signal.setitimer(signal.ITIMER_REAL, budgets['total_wall_seconds'])
    try:
        audit = json.loads(Path(input_audit).read_text())
        if audit.get('status') != 'PASS':
            raise ValueError('independent input audit must PASS before timing')
        audited = audit.get('input_audits', [])
        if len(audited) != 2 or len({(row['events'], row['seed']) for row in audited}) != 2:
            raise ValueError('independent input audit must contain exact unique input roster')
        for item in protocol['inputs']:
            row = next((row for row in audited if (row['events'], row['seed']) == (item['events'], item['seed'])), None)
            if (row is None or row.get('status') != 'PASS' or row['auxiliary_receipts'] != 17 or
                row['physical_receipts'] != item['events'] + 17 or
                {key: row['input'][key] for key in ('bytes', 'sha256')} != item['proof']):
                raise ValueError('independent input identity/receipt audit differs')
        record['independent_input_audit'] = {'path': str(input_audit), **proof(input_audit)}
        shutil.copyfile(input_audit, output / 'independent-input-audit.json')
        sources = source_bindings()
        record['source_bindings'] = sources
        snapshot = output / 'source'
        for name in sources:
            dest = snapshot / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, dest)
        if source_bindings(snapshot) != sources:
            raise AssertionError('execution source snapshot differs')
        inputs = {}
        (output / 'inputs').mkdir()
        for item in protocol['inputs']:
            src = Path(item['original_path'])
            if proof(src) != item['proof']:
                raise ValueError('HISTORICAL_INPUT_MISSING_OR_SUBSTITUTED')
            dest = output / 'inputs' / src.name
            shutil.copyfile(src, dest)
            if proof(dest) != item['proof']:
                raise ValueError('input copied bytes differ')
            inputs[(item['events'], item['seed'])] = {'path': str(dest), 'original_path': str(src), **proof(dest)}
        # Warmup is separately labelled synthetic construction, never an absent historical replacement.
        warmup = output / 'inputs' / 'warmup-events100-seed0.json'
        write(warmup, original.workload(100, 0))
        inputs[(100, 0)] = {'path': str(warmup), 'origin': 'SEPARATE_WARMUP_GENERATED', **proof(warmup)}
        record['inputs'] = list(inputs.values())
        write(output / 'preregistration.json', record)
        for spec in protocol['roster']:
            trial = {**spec, 'input': inputs[(spec['events'], spec['seed'])], 'status': 'NOT_RUN', 'exit_code': None}
            record['trials'].append(trial)
            children = resource.getrusage(resource.RUSAGE_CHILDREN)
            spent_cpu = time.process_time() - cpu_start + children.ru_utime + children.ru_stime - initial_children.ru_utime - initial_children.ru_stime
            remaining = budgets['total_wall_seconds'] - (time.monotonic() - start) - budgets['cleanup_reserve_seconds']
            if stop or remaining < spec['wall_cap'] or spent_cpu > budgets['total_cpu_seconds'] - budgets['cleanup_reserve_seconds']:
                trial['reason'] = stop or 'INSUFFICIENT_REMAINING_PREREGISTERED_BUDGET'
                write(output / 'ledger.json', record)
                continue
            folder = output / spec['id']
            cpu_cap = max(1, min(spec['wall_cap'], math.floor(budgets['total_cpu_seconds'] - spent_cpu - budgets['cleanup_reserve_seconds'])))
            bootstrap = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('validation_lab.gate4_benchmark',run_name='__main__')"
            command = [sys.executable, '-I', '-B', '-c', bootstrap, str(snapshot), '--worker', '--input', trial['input']['path'], '--output', str(folder), '--method', spec['method'], '--cpu-limit', str(cpu_cap)]
            if spec['instrumented']:
                command.append('--instrumented')
            trial.update(argv=command, cwd=str(snapshot), status='RUNNING', loadavg_before=os.getloadavg(), started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
            write(output / (spec['id'] + '.command-start.json'), trial)
            launch, samples, reason, startup = time.monotonic(), [], None, None
            launch_controller_cpu = time.process_time()
            try:
                with (output / (spec['id'] + '.stdout.txt')).open('w') as stdout, (output / (spec['id'] + '.stderr.txt')).open('w') as stderr:
                    launch_owned(command, cwd=snapshot, stdout=stdout, stderr=stderr)
                    trial['pid'] = ACTIVE.pid
                    next_disk = launch
                    while ACTIVE.poll() is None:
                        now = time.monotonic()
                        sampled = process_sample(ACTIVE.pid)
                        if sampled:
                            samples.append({'elapsed_seconds': now - launch, **sampled})
                            if spent_cpu + sampled['cpu_seconds'] + time.process_time() - launch_controller_cpu > budgets['total_cpu_seconds'] - budgets['cleanup_reserve_seconds']:
                                reason = stop = 'TOTAL_CPU_BUDGET'
                        if startup is None and (output / (spec['id'] + '.worker-start.json')).exists():
                            startup = now - launch
                        if now >= next_disk:
                            used = disk_bytes(budget_root)
                            peak_disk = max(peak_disk, used)
                            if used > budgets['owned_disk_bytes'] - budgets['disk_reserve_bytes']:
                                reason = stop = 'OWNED_DISK_GUARD'
                            next_disk = now + 1
                        if now - launch >= spec['wall_cap']:
                            reason = 'TRIAL_WALL_CAP'
                        if reason:
                            break
                        time.sleep(.1)
                    trial['exit_code'] = kill_wait(ACTIVE) if reason else ACTIVE.wait()
            except BaseException as exc:
                trial['controller_exception'] = repr(exc)
                if ACTIVE is not None:
                    trial['exit_code'] = kill_wait(ACTIVE)
                raise
            finally:
                if ACTIVE is not None:
                    if trial['exit_code'] is None:
                        trial['exit_code'] = kill_wait(ACTIVE)
                    ACTIVE = None
                trial['parent_wall_seconds'] = time.monotonic() - launch
                trial['startup_marker_observed_upper_bound_seconds'] = startup
                trial['samples'] = samples
                trial['loadavg_after'] = os.getloadavg()
                trial['stdout'] = proof(output / (spec['id'] + '.stdout.txt'))
                trial['stderr'] = proof(output / (spec['id'] + '.stderr.txt'))
                marker = output / (spec['id'] + '.worker-start.json')
                if marker.exists():
                    trial['worker_start'] = json.loads(marker.read_text())
                if (folder / 'progress.json').exists():
                    trial['last_progress'] = json.loads((folder / 'progress.json').read_text())
            if reason:
                trial.update(status='TIMEOUT' if reason == 'TRIAL_WALL_CAP' else 'RESOURCE_STOP', reason=reason)
            elif trial['exit_code'] != 0 or not (folder / 'metrics.json').exists():
                trial.update(status='ERROR', reason='worker exit or metrics missing')
                stop = 'WORKER_ERROR'
            else:
                metrics = json.loads((folder / 'metrics.json').read_text())
                trial.update(status=metrics['status'], metrics=metrics, metrics_proof=proof(folder / 'metrics.json'))
                if trial['status'] != 'PASS':
                    stop = 'WORKER_NONPASS'
            if trial['status'] != 'PASS':
                trial['postprocess_readback'] = stopped_readback(folder)
            if trial['role'] == 'paired' and trial['status'] == 'PASS':
                mates = [t for t in record['trials'] if t['role'] == 'paired' and t['pair'] == spec['pair'] and t['events'] == spec['events'] and t['id'] != spec['id'] and t['status'] == 'PASS']
                if mates and not equivalent(mates[0]['metrics'], trial['metrics']):
                    trial['status'] = 'NON_EQUIVALENT'
                    stop = 'LOGICAL_EQUIVALENCE_FAILURE'
            if source_bindings(snapshot) != sources or source_bindings(ROOT) != sources:
                stop = 'SOURCE_CHANGED'
                trial['status'] = 'ERROR'
            write(output / 'ledger.json', record)
            print(json.dumps({'trial': trial['id'], 'status': trial['status'], 'exit': trial['exit_code'], 'seconds': trial['parent_wall_seconds']}), flush=True)
        record['status'] = 'PASS' if all(t['status'] == 'PASS' for t in record['trials']) else 'PARTIAL'
    except BaseException as exc:
        stop = repr(exc)
        record['status'] = 'ERROR'
        record['error'] = stop
        if ACTIVE is not None:
            exit_code = kill_wait(ACTIVE)
            record['trials'][-1].update(exit_code=exit_code, status='ERROR', reason=stop)
            ACTIVE = None
        if record['trials'] and record['trials'][-1]['status'] == 'RUNNING':
            record['trials'][-1].update(status='ERROR', reason=stop)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        signal.signal(signal.SIGTERM, old_term_handler)
        done = {t['id'] for t in record['trials']}
        for spec in protocol['roster']:
            if spec['id'] not in done:
                record['trials'].append({**spec, 'status': 'NOT_RUN', 'exit_code': None, 'reason': stop or 'CONTROLLER_STOP'})
        children = resource.getrusage(resource.RUSAGE_CHILDREN)
        record['resource_summary'] = {'elapsed_seconds': time.monotonic() - start,
            'controller_cpu_seconds': time.process_time() - cpu_start,
            'waited_child_cpu_seconds': children.ru_utime + children.ru_stime - initial_children.ru_utime - initial_children.ru_stime,
            'peak_sampled_owned_disk_bytes': peak_disk, 'final_owned_disk_bytes': disk_bytes(budget_root),
            'qualification': 'Logical files sampled each second, including SQLite WAL/shm/journal; not physical I/O or continuous peak. CPU aggregate includes waited children.'}
        record['stop_reason'] = stop
        write(output / 'ledger.json', record)
        write(output / 'summary.json', summarize(record['trials'], protocol))
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--method', choices=METHODS)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--instrumented', action='store_true')
    parser.add_argument('--cpu-limit', type=int, default=150)
    parser.add_argument('--protocol', type=Path, default=PROTOCOL)
    parser.add_argument('--input-audit', type=Path)
    args = parser.parse_args()
    if args.worker:
        signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGALRM, signal.SIGINT, signal.SIGTERM})
        resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024**2, 1536 * 1024**2))
        resource.setrlimit(resource.RLIMIT_CPU, (args.cpu_limit, args.cpu_limit))
        resource.setrlimit(resource.RLIMIT_FSIZE, (512 * 1024**2, 512 * 1024**2))
        identity = {'interpreter': sys.executable, 'python': sys.version, 'sqlite': sqlite3.sqlite_version,
            'source_bindings': source_bindings(),
            'import_origins': {name: importlib.import_module(name).__file__ for name in ('crypto_reconciliation_lab', 'crypto_reconciliation_lab.store', 'validation_lab.gate4_storage', 'validation_lab.gate4_benchmark')},
            'effective_rlimits': {name: list(resource.getrlimit(getattr(resource, name))) for name in ('RLIMIT_AS', 'RLIMIT_CPU', 'RLIMIT_FSIZE')}}
        write(args.output.with_name(args.output.name + '.worker-start.json'), identity)
        run_worker(args.input, args.output, args.method, args.instrumented)
    else:
        if args.input_audit is None:
            parser.error('--input-audit is required before any benchmark launch')
        record = program(args.output, args.protocol, args.input_audit)
        raise SystemExit(0 if record['status'] == 'PASS' else 1)


if __name__ == '__main__':
    main()
