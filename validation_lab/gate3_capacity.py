"""Finite Gate3 capacity diagnostics; production sources remain unchanged."""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import contextmanager
import csv
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import time

from validation_lab import benchmark as previous
from validation_lab import benchmark_gate2 as gate2

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / 'contracts/gate3-capacity-protocol.json'
ACTIVE_PROCESS = None
PROGRAM_RECORD = None
CONTROLLER_DEADLINE = None
CURRENT_TRIAL = None


class BudgetStop(RuntimeError):
    pass


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def proof(path):
    return previous.file_proof(path)


def source_paths():
    names = set(gate2.bindings())
    names.update(('validation_lab/gate3_capacity.py',
                  'contracts/gate3-capacity-protocol.json'))
    if (ROOT/'contracts/gate3-capacity-continuation.json').exists():
        names.add('contracts/gate3-capacity-continuation.json')
    return sorted(names)


def source_bindings(root=ROOT):
    return {name: proof(root / name) for name in source_paths()}


def disk_bytes(root):
    total=0
    for path in Path(root).rglob('*'):
        try:
            observed=path.stat()
        except FileNotFoundError:
            # SQLite DELETE journals can disappear between enumeration and stat.
            continue
        if stat.S_ISREG(observed.st_mode):
            total+=observed.st_size
    return total


class Recorder:
    def __init__(self, folder):
        self.buckets = defaultdict(lambda: {'calls': 0, 'wall_seconds': 0.0, 'cpu_seconds': 0.0})
        self.phase = 'initialize'
        self.handle = (folder / 'transactions.csv').open('w', newline='')
        self.csv = csv.writer(self.handle)
        self.csv.writerow(('phase', 'ordinal', 'boundary', 'wall_seconds', 'cpu_seconds'))
        self.ordinal = 0

    def call(self, label, fn, *args, **kwargs):
        wall, cpu = time.perf_counter(), time.process_time()
        try:
            return fn(*args, **kwargs)
        finally:
            w, c = time.perf_counter()-wall, time.process_time()-cpu
            bucket = self.buckets[f'{self.phase}:{label}']
            bucket['calls'] += 1
            bucket['wall_seconds'] += w
            bucket['cpu_seconds'] += c
            if label in ('sql_begin', 'sql_commit', 'sql_rollback'):
                self.ordinal += 1
                self.csv.writerow((self.phase, self.ordinal, label, w, c))

    def close(self):
        self.handle.close()

    def add_interval(self, label, wall, cpu):
        bucket = self.buckets[f'{self.phase}:{label}']
        bucket['calls'] += 1
        bucket['wall_seconds'] += time.perf_counter()-wall
        bucket['cpu_seconds'] += time.process_time()-cpu


def sql_class(sql):
    tokens = sql.lstrip().upper().split()
    first = tokens[0] if tokens else 'EMPTY'
    if first in ('BEGIN', 'COMMIT', 'ROLLBACK'):
        return 'sql_' + first.lower()
    if first == 'CREATE' and 'INDEX' in tokens[:5]:
        return 'sql_create_index'
    return 'sql_' + first.lower()


@contextmanager
def observe_calls(recorder):
    """Scoped delegates preserve every original argument, return and exception."""
    module = importlib.import_module('crypto_reconciliation_lab.store')
    old_connect = sqlite3.connect
    originals = {name: getattr(module, name) for name in ('digest', 'normalize', 'dumps')}

    class ObservedConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            return recorder.call(sql_class(sql), super().execute, sql, *args, **kwargs)

        def executescript(self, sql):
            previous_statement = []
            def trace(statement):
                if previous_statement:
                    label, wall, cpu = previous_statement[0]
                    recorder.add_interval(label,wall,cpu)
                previous_statement[:] = [(sql_class(statement)+'_trace_interval',time.perf_counter(),time.process_time())]
            self.set_trace_callback(trace)
            try:
                return recorder.call('sql_schema_script_including_initial_indices', super().executescript, sql)
            finally:
                if previous_statement:
                    recorder.add_interval(*previous_statement[0])
                self.set_trace_callback(None)

    def connect(*args, **kwargs):
        kwargs['factory'] = ObservedConnection
        return old_connect(*args, **kwargs)

    try:
        sqlite3.connect = connect
        for name, original in originals.items():
            def wrapper(*args, _fn=original, _name=name, **kwargs):
                return recorder.call(_name, _fn, *args, **kwargs)
            setattr(module, name, wrapper)
        yield
    finally:
        sqlite3.connect = old_connect
        for name, original in originals.items():
            setattr(module, name, original)


def full_worker(input_path, output, instrument):
    output.mkdir(parents=True, exist_ok=False)
    phases, committed = {}, 0
    start, cpu_start = time.perf_counter(), time.process_time()
    io_before = gate2.physical_io()
    observer = Recorder(output) if instrument else None

    def progress(name, state):
        write(output / 'progress.json', {'phase': name, 'state': state,
              'committed_receipts_periodic_lower_bound': committed,
              'elapsed_seconds': time.perf_counter()-start, 'completed_phases': phases})

    def phase(name, fn):
        prior_phase=observer.phase if observer else None
        if observer:
            observer.phase = name
        progress(name, 'STARTED')
        wall, cpu = time.perf_counter(), time.process_time()
        try:
            value = fn()
        finally:
            if observer:
                observer.phase=prior_phase
        phases[name] = {'wall_seconds': time.perf_counter()-wall, 'cpu_seconds': time.process_time()-cpu}
        progress(name, 'COMPLETED')
        return value

    raw = phase('input_read', lambda: input_path.read_bytes())
    data = phase('json_parse', lambda: json.loads(raw))
    phase('input_content_hash', lambda: hashlib.sha256(raw).hexdigest())
    phase('validate_common_contract', lambda: gate2.finite_gate(data))
    from crypto_reconciliation_lab import Store, reconcile

    class MeasuredStore(Store):
        def save_run(self, result, *, fault=None):
            return phase('run_persistence', lambda: super(MeasuredStore, self).save_run(result, fault=fault))

    @contextmanager
    def unobserved():
        yield

    with observe_calls(observer) if observer else unobserved():
        store = phase('initialize', lambda: MeasuredStore(output / 'input.sqlite3', data['config']))
        settings = {key: store.db.execute('PRAGMA ' + key).fetchone()[0] for key in ('journal_mode', 'synchronous', 'page_size')}
        indexes = [dict(row) for row in store.db.execute("SELECT name,sql FROM sqlite_master WHERE type='index' ORDER BY name")]
        with (output / 'receipts.csv').open('w', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(('ordinal', 'kind', 'wall_seconds', 'cpu_seconds', 'status'))
            def ingest():
                nonlocal committed
                for ordinal, envelope in enumerate(data['rows'], 1):
                    wall, cpu = time.perf_counter(), time.process_time()
                    response = store.ingest(envelope['record'], envelope['received_at'])
                    elapsed, cpu_elapsed = time.perf_counter()-wall, time.process_time()-cpu
                    if response['status'] != 'ACCEPTED':
                        raise AssertionError(response)
                    committed += 1
                    if instrument:
                        writer.writerow((ordinal, envelope['record']['kind'], elapsed, cpu_elapsed, response['status']))
                    if committed % 1000 == 0:
                        progress('ingest', 'RUNNING')
            phase('ingest', ingest)
        result = phase('recompute_including_run_persistence', lambda: reconcile(store, data['balance_at'], data['knowledge_at']))
        text = phase('restricted_export_json_serialization', lambda: gate2.payload(result))
        phase('restricted_export_write', lambda: (output / 'export.json').write_text(text))
        def verify():
            expected = previous.with_findings(previous.analytic_oracle(data['events'], data['seed']), data)
            if previous.project_production(result) != expected:
                raise AssertionError('independent closed-form financial oracle mismatch')
            if store.read_run(result['run_id']) != result or json.loads((output / 'export.json').read_text()) != result:
                raise AssertionError('full persisted/exported evidence mismatch')
            counts = {table: store.db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                      for table in ('records', 'receipts', 'runs', 'findings', 'evidence')}
            if counts['receipts'] != len(data['rows']) or counts['runs'] != 1:
                raise AssertionError('physical receipt / saved run mismatch')
            return counts
        counts = phase('reread_verify', verify)
        phase('close', store.close)
    if observer:
        observer.close()
    wall, cpu = time.perf_counter()-start, time.process_time()-cpu_start
    record = {'status': 'PASS', 'mode': 'full', 'instrumented': instrument, 'events': data['events'],
              'seed': data['seed'], 'physical_receipts': len(data['rows']), 'wall_seconds': wall,
              'cpu_seconds': cpu, 'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              'phases': phases, 'counts': counts, 'sqlite_settings': settings, 'indexes': indexes,
              'buckets': dict(observer.buckets) if observer else {},
              'bucket_semantics': 'Inclusive nested timing, not additive. SQL execute excludes later cursor fetch. Initial index construction separately observed by before-statement trace intervals within unchanged executescript (includes callback dispatch). Index maintenance remains inseparable from inserts. Off control still includes phase/receipt clock calls and CSV header; paired difference is incremental observer cost, not total measurement overhead.',
              'artifacts': {name: proof(output / name) for name in ('input.sqlite3', 'export.json')},
              'financial_projection': previous.project_production(result), 'run_id': result['run_id'],
              'physical_io_before': io_before, 'physical_io_after': gate2.physical_io()}
    write(output / 'metrics.json', record)
    return record


def worker(args):
    resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (args.cpu_limit, args.cpu_limit))
    resource.setrlimit(resource.RLIMIT_FSIZE, (384*1024**2, 384*1024**2))
    origins = {name: importlib.import_module(name).__file__ for name in
               ('crypto_reconciliation_lab', 'crypto_reconciliation_lab.store',
                'validation_lab.benchmark', 'validation_lab.benchmark_gate2', 'validation_lab.gate3_capacity')}
    identity = {'interpreter': sys.executable, 'python': sys.version,
        'import_origins': origins, 'source_bindings': source_bindings(),
        'effective_rlimits': {name: list(resource.getrlimit(getattr(resource, name))) for name in ('RLIMIT_AS', 'RLIMIT_CPU', 'RLIMIT_FSIZE')}}
    write(args.output.with_name(args.output.name+'.worker-start.json'), identity)
    result = gate2.run_worker('production', args.input, args.output) if args.worker == 'common' else full_worker(args.input, args.output, args.instrument)
    result['execution_identity'] = identity
    write(args.output / 'metrics.json', result)
    return result


def sample_process(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        status = dict(line.split(':', 1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
        return {'cpu_seconds': (int(fields[11])+int(fields[12])) / os.sysconf('SC_CLK_TCK'),
                'rss_kib': int(status.get('VmRSS', '0 kB').split()[0])}
    except (FileNotFoundError, ProcessLookupError):
        return None


def database_readback(folder, budget_root=None, disk_limit=1024**3):
    path = folder / 'input.sqlite3'
    if not path.exists():
        return {'status': 'NOT_RUN', 'reason': 'database absent'}
    originals = {p.name: proof(p) for p in folder.glob('input.sqlite3*') if p.is_file()}
    current_bytes = disk_bytes(budget_root) if budget_root else disk_bytes(folder)
    # A conservative64MiB reserve covers recovery journal/transient bookkeeping.
    if current_bytes + sum(pin['bytes'] for pin in originals.values()) + 64*1024**2 >= disk_limit:
        return {'status': 'NOT_RUN', 'reason': 'recovery copy would exceed fixed owned disk budget',
                'original_artifacts': originals, 'current_disk_bytes': current_bytes}
    recovered = folder / 'postprocess-recovery-copy'
    recovered.mkdir()
    for name in originals:
        shutil.copyfile(folder / name, recovered / name)
    try:
        # Read/write connection permits SQLite hot-journal recovery only on copy.
        with sqlite3.connect(recovered / 'input.sqlite3', timeout=5) as db:
            if CONTROLLER_DEADLINE is not None:
                db.set_progress_handler(lambda: int(time.monotonic() >= CONTROLLER_DEADLINE), 10000)
            integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
            counts = {table: db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                      for table in ('records', 'receipts', 'runs', 'findings', 'evidence')}
            statuses = dict(db.execute('SELECT status,COUNT(*) FROM receipts GROUP BY status'))
        if integrity != 'ok':
            raise ValueError(integrity)
        result = {'status': 'PASS', 'integrity_check': integrity, 'committed_rows': counts,
                  'receipt_statuses': statuses, 'original_artifacts': originals,
                  'recovered_database': proof(recovered / 'input.sqlite3'),
                  'scope': 'direct SQLite recovered copy after process exit; not operational RPO'}
    except (sqlite3.Error, ValueError) as exc:
        result = {'status': 'ERROR', 'error': repr(exc), 'original_artifacts': originals}
    result['originals_unchanged'] = all(proof(folder/name) == pin for name, pin in originals.items())
    result['disk_bytes_with_recovery_copy'] = disk_bytes(budget_root) if budget_root else disk_bytes(folder)
    shutil.rmtree(recovered)
    result['recovery_copy_retention'] = 'REMOVED_AFTER_RECORDED_READBACK_AND_HASH; originals retained'
    return result


def _program(output, history, protocol):
    global ACTIVE_PROCESS, PROGRAM_RECORD, CURRENT_TRIAL
    start, cpu_start = time.monotonic(), time.process_time()
    child_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    output.mkdir(parents=True, exist_ok=False)
    budget_root=output.parent if protocol.get('continuation') else output
    PROGRAM_RECORD = {'format': 'gate3-capacity-v1', 'data_class': 'FULLY_SYNTHETIC',
                      'trials': [], 'setup_status': 'RUNNING', 'controller_started_monotonic': start}
    write(output / 'protocol.json', protocol)
    sources = source_bindings()
    snapshot = output / 'source'
    for name in sources:
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/name, target)
    if source_bindings(snapshot) != sources:
        raise AssertionError('snapshot mismatch')
    inputs, generation = {}, []
    (output/'inputs').mkdir()
    for trial in protocol['roster']:
        key = f"events{trial['events']}-seed{trial['seed']}"
        if key in inputs:
            continue
        dest = output / 'inputs' / (key+'.json')
        candidates = [history/'capacity-triage/inputs'/dest.name, history/'common-full/inputs'/dest.name]
        if protocol.get('continuation'):
            candidates=[Path(protocol['continuation']['input_root'])/dest.name]
        prior = next((p for p in candidates if p.is_file()), None)
        generation_wall, generation_cpu = time.perf_counter(), time.process_time()
        historical_pin=protocol['historical_input_pins'].get(key)
        if historical_pin is not None and (prior is None or proof(prior)!=historical_pin):
            raise ValueError('HISTORICAL_INPUT_MISSING_OR_SUBSTITUTED: '+key)
        if prior:
            shutil.copyfile(prior, dest)
        else:
            write(dest, previous.workload(trial['events'], trial['seed']))
        gate2.finite_gate(json.loads(dest.read_text()))
        inputs[key] = {'path': str(dest), **proof(dest), 'origin': str(prior) if prior else 'PREREGISTERED_SEED29_GATE2_FINITE_GENERATOR'}
        if historical_pin is not None:
            if proof(dest)!=historical_pin:
                raise ValueError('HISTORICAL_INPUT_COPY_CHANGED: '+key)
            inputs[key]['historical_pin']=historical_pin
        generation.append({'input': key, 'wall_seconds': time.perf_counter()-generation_wall,
                           'cpu_seconds': time.process_time()-generation_cpu, 'operation': 'COPY_AND_VALIDATE' if prior else 'GENERATE_AND_VALIDATE'})
    record = {'format': 'gate3-capacity-v1', 'data_class': 'FULLY_SYNTHETIC',
        'head_at_preregistration': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'source_bindings': sources, 'protocol': proof(output/'protocol.json'), 'inputs': inputs,
        'generation': generation, 'argv': sys.argv, 'cwd': str(ROOT), 'interpreter': sys.executable,
        'python': sys.version, 'platform': platform.platform(), 'trials': [],
        'host': {'affinity': sorted(os.sched_getaffinity(0)), 'loadavg': os.getloadavg(),
                 'cgroup': {name: (Path('/sys/fs/cgroup')/name).read_text().strip() for name in ('cpu.max','memory.max') if (Path('/sys/fs/cgroup')/name).exists()}},
        'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
    PROGRAM_RECORD = record
    record['setup_status']='PASS'
    record['setup_wall_seconds']=time.monotonic()-start
    write(output/'preregistration.json', record)
    peak_sampled_disk = disk_bytes(budget_root)
    stop_reason = None
    for spec in protocol['roster']:
        trial = dict(spec)
        key = f"events{spec['events']}-seed{spec['seed']}"
        trial['input'] = inputs[key]
        trial['expected'] = {'physical_receipts': spec['events']+17, 'finite_seed': spec['seed'],
                             'financial_oracle': previous.analytic_oracle(spec['events'],spec['seed'])}
        remaining = protocol['budgets']['total_wall_seconds'] - 20 - (time.monotonic()-start)
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        spent_cpu = time.process_time()-cpu_start + usage.ru_utime+usage.ru_stime-child_start.ru_utime-child_start.ru_stime
        if stop_reason or remaining < spec['wall_cap'] or spent_cpu >= protocol['budgets']['total_cpu_seconds']-20:
            trial.update(status='NOT_RUN', exit_code=None, reason=stop_reason or 'remaining finite total wall/CPU budget cannot grant preregistered cap')
            record['trials'].append(trial)
            continue
        folder = output / spec['id']
        stdout_path, stderr_path = output/(spec['id']+'.stdout.txt'), output/(spec['id']+'.stderr.txt')
        cpu_limit = min(spec['wall_cap'], math.floor(protocol['budgets']['total_cpu_seconds']-20-spent_cpu))
        bootstrap = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('validation_lab.gate3_capacity',run_name='__main__')"
        command = [sys.executable,'-I','-B','-c',bootstrap,str(snapshot),'--worker',spec['mode'],
                   '--input',inputs[key]['path'],'--output',str(folder),'--cpu-limit',str(cpu_limit)]
        if spec['instrument']:
            command.append('--instrument')
        trial.update(argv=command, cwd=str(snapshot), interpreter=sys.executable,
                     started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                     effective_limits={'wall_seconds':spec['wall_cap'], 'cpu_seconds':cpu_limit,'address_space_bytes':1024**3,'single_file_bytes':384*1024**2},
                     loadavg_before=os.getloadavg())
        write(output/(spec['id']+'.command-start.json'),trial)
        CURRENT_TRIAL=trial
        samples, reason, startup_observed = [], None, None
        launch = time.monotonic()
        with stdout_path.open('w') as out, stderr_path.open('w') as err:
            old_mask=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGALRM})
            try:
                process = subprocess.Popen(command,cwd=snapshot,stdout=out,stderr=err,start_new_session=True)
                ACTIVE_PROCESS = process
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK,old_mask)
            next_disk = launch
            while process.poll() is None:
                now = time.monotonic()
                observed = sample_process(process.pid)
                if observed:
                    samples.append({'elapsed_seconds':now-launch,**observed})
                if startup_observed is None and (output/(spec['id']+'.worker-start.json')).exists():
                    startup_observed = now-launch
                if now >= next_disk:
                    used = disk_bytes(budget_root)
                    peak_sampled_disk = max(peak_sampled_disk,used)
                    next_disk = now+1
                    # Leave headroom for subsequent copy recovery and writeout.
                    if used >= 850*1024**2:
                        reason = stop_reason = 'DISK_BUDGET_GUARD'
                if now-launch >= spec['wall_cap']:
                    reason = 'WALL_DEADLINE'
                if reason:
                    try:
                        os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
                    break
                time.sleep(0.1)
            exit_code = process.wait()
            trial['exit_code']=exit_code
            ACTIVE_PROCESS = None
        elapsed = time.monotonic()-launch
        status = 'TIMEOUT' if reason == 'WALL_DEADLINE' else 'PARTIAL' if reason else 'PASS' if exit_code==0 else 'ERROR'
        trial.update(status=status, exit_code=exit_code, termination_reason=reason,
                     subprocess_wall_seconds=elapsed, completed_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                     stdout=proof(stdout_path),stderr=proof(stderr_path), loadavg_after=os.getloadavg(),
                     worker_start_identity_observed_within_seconds=startup_observed,
                     final_worker_cpu_seconds='NOT_MEASURED', final_worker_peak_rss_kib='NOT_MEASURED',
                     sampled_cpu_seconds=samples[-1]['cpu_seconds'] if samples else 'NOT_MEASURED',
                     sampled_peak_rss_kib=max(s['rss_kib'] for s in samples) if samples else 'NOT_MEASURED')
        write(output/(spec['id']+'.process-samples.json'),samples)
        if folder.exists():
            if (folder/'progress.json').exists():
                trial['last_progress']=json.loads((folder/'progress.json').read_text())
            if status=='PASS':
                trial['metrics']=json.loads((folder/'metrics.json').read_text())
                trial['final_worker_cpu_seconds']=trial['metrics']['cpu_seconds']
                trial['final_worker_peak_rss_kib']=trial['metrics']['peak_rss_kib']
                if trial['metrics']['execution_identity']['source_bindings'] != sources:
                    trial.update(status='ERROR',reason='SOURCE_BINDING_MISMATCH')
            trial['postprocess_readback']=database_readback(folder,budget_root)
            peak_sampled_disk=max(peak_sampled_disk,trial['postprocess_readback'].get('disk_bytes_with_recovery_copy',0))
            trial['artifact_inventory']={str(p.relative_to(folder)):proof(p) for p in folder.rglob('*') if p.is_file()}
        trial['input_unchanged']=proof(inputs[key]['path'])=={k:inputs[key][k] for k in ('sha256','bytes')}
        write(output/(spec['id']+'.command.json'),trial)
        record['trials'].append(trial)
        CURRENT_TRIAL=None
        write(output/'results.json',record)
    record['status']='COMPLETE' if all(t['status']=='PASS' for t in record['trials']) else 'PARTIAL'
    end_children=resource.getrusage(resource.RUSAGE_CHILDREN)
    record['program_cost']={'wall_seconds':time.monotonic()-start,'controller_cpu_seconds':time.process_time()-cpu_start,
        'aggregate_waited_children_cpu_seconds':end_children.ru_utime+end_children.ru_stime-child_start.ru_utime-child_start.ru_stime,
        'max_sampled_disk_bytes':peak_sampled_disk,'retained_disk_bytes':disk_bytes(budget_root),
        'disk_budget_root':str(budget_root),'current_attempt_retained_disk_bytes':disk_bytes(output),
        'qualification':'Aggregate OS wait usage does not fill individual killed-worker final usage. Disk sampled each second and once during recovery-copy readback; not continuous peak. Recovery copy requires enough remaining owned disk budget.'}
    record['snapshot_unchanged']=source_bindings(snapshot)==sources
    record['working_source_unchanged']=source_bindings()==sources
    pairs={t['id']:t for t in record['trials']}
    off,on=pairs['full-10000-control'],pairs['full-10000-instrumented']
    if off['status']==on['status']=='PASS':
        parity=all(off['metrics'][key]==on['metrics'][key] for key in ('artifacts','financial_projection','run_id','counts','sqlite_settings'))
        record['instrumentation_comparison']={'status':'PASS' if parity else 'ERROR','exact_artifact_and_financial_parity':parity,
            'wall_difference_seconds':on['metrics']['wall_seconds']-off['metrics']['wall_seconds'],
            'cpu_difference_seconds':on['metrics']['cpu_seconds']-off['metrics']['cpu_seconds'],
            'n_pairs':1,'interpretation':'Observed same-input off/on difference; order/cache/host noise unresolved, not a statistical overhead estimate.'}
    else:
        record['instrumentation_comparison']={'status':'NOT_RUN','reason':'both paired controls must complete'}
    problems=[]
    if not record['snapshot_unchanged'] or not record['working_source_unchanged']:
        problems.append('SOURCE_CHANGED')
    if record['instrumentation_comparison']['status']=='ERROR':
        problems.append('INSTRUMENTATION_PARITY_FAILED')
    for trial in record['trials']:
        if trial.get('input_unchanged') is False:
            problems.append(trial['id']+':INPUT_CHANGED')
        if trial.get('postprocess_readback',{}).get('status')=='ERROR' or trial.get('postprocess_readback',{}).get('originals_unchanged') is False:
            problems.append(trial['id']+':READBACK_FAILED')
        if trial['status']=='ERROR':
            problems.append(trial['id']+':WORKER_ERROR')
    record['integrity_audit']={'status':'ERROR' if problems else 'PASS','problems':problems}
    if problems:
        record['status']='ERROR'
    write(output/'results.json',record)
    return record


def program(output, history, protocol_path=PROTOCOL):
    """Bound controller setup, workers and postprocessing, reserving cleanup time."""
    global ACTIVE_PROCESS, PROGRAM_RECORD, CONTROLLER_DEADLINE, CURRENT_TRIAL
    if output.exists():
        raise FileExistsError('refusing to overwrite an existing evidence directory')
    protocol=json.loads(protocol_path.read_text())
    started=time.monotonic()
    cpu_started=time.process_time()
    children_started=resource.getrusage(resource.RUSAGE_CHILDREN)
    CONTROLLER_DEADLINE=started+protocol['budgets']['total_wall_seconds']-20
    prior_handler=signal.getsignal(signal.SIGALRM)
    old_as=resource.getrlimit(resource.RLIMIT_AS)
    # Parent and sole worker each cap address space at1GiB; kernel cache excluded.
    resource.setrlimit(resource.RLIMIT_AS,(min(old_as[0],1024**3) if old_as[0]>=0 else 1024**3,old_as[1]))

    def guard(signum,frame):
        used=resource.getrusage(resource.RUSAGE_CHILDREN)
        aggregate=time.process_time()-cpu_started+used.ru_utime+used.ru_stime-children_started.ru_utime-children_started.ru_stime
        if ACTIVE_PROCESS is not None and ACTIVE_PROCESS.poll() is None:
            observed=sample_process(ACTIVE_PROCESS.pid)
            if observed:
                aggregate+=observed['cpu_seconds']
        if time.monotonic()>=CONTROLLER_DEADLINE or aggregate>=protocol['budgets']['total_cpu_seconds']-20:
            raise BudgetStop('GLOBAL_WALL_OR_CPU_WORK_BUDGET;20s/20CPU reserved for cleanup')

    signal.signal(signal.SIGALRM,guard)
    signal.setitimer(signal.ITIMER_REAL,0.25,0.25)
    try:
        return _program(output,history,protocol)
    except BaseException as exc:
        signal.setitimer(signal.ITIMER_REAL,0)
        active_exit=None
        if ACTIVE_PROCESS is not None:
            if ACTIVE_PROCESS.poll() is None:
                try:
                    os.killpg(ACTIVE_PROCESS.pid,signal.SIGKILL)
                except ProcessLookupError:
                    pass
            active_exit=ACTIVE_PROCESS.wait()
        record=PROGRAM_RECORD or {'format':'gate3-capacity-v1','trials':[]}
        seen={t['id'] for t in record['trials']}
        for row in protocol['roster']:
            if row['id'] not in seen:
                started_file=output/(row['id']+'.command-start.json')
                if started_file.exists():
                    trial=dict(CURRENT_TRIAL) if CURRENT_TRIAL and CURRENT_TRIAL['id']==row['id'] else json.loads(started_file.read_text())
                    trial.update(status='PARTIAL' if isinstance(exc,BudgetStop) else 'ERROR',exit_code=trial.get('exit_code',active_exit),reason=str(exc),
                                 final_worker_cpu_seconds='NOT_MEASURED',final_worker_peak_rss_kib='NOT_MEASURED')
                    progress=output/row['id']/'progress.json'
                    if progress.exists():
                        trial['last_progress']=json.loads(progress.read_text())
                else:
                    trial={**row,'status':'NOT_RUN','exit_code':None,'reason':str(exc)}
                record['trials'].append(trial)
        record.update(status='PARTIAL' if isinstance(exc,BudgetStop) else 'ERROR',
                      termination_type=type(exc).__name__,termination_reason=str(exc),
                      active_worker_exit_code=active_exit,controller_wall_seconds=time.monotonic()-started,
                      integrity_audit={'status':'NOT_RUN','reason':'early termination requires independent retained-file review'})
        output.mkdir(parents=True,exist_ok=True)
        write(output/'results.json',record)
        return record
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        if ACTIVE_PROCESS is not None:
            if ACTIVE_PROCESS.poll() is None:
                try:
                    os.killpg(ACTIVE_PROCESS.pid,signal.SIGKILL)
                except ProcessLookupError:
                    pass
            ACTIVE_PROCESS.wait()
        signal.signal(signal.SIGALRM,prior_handler)
        resource.setrlimit(resource.RLIMIT_AS,old_as)
        CONTROLLER_DEADLINE=None
        ACTIVE_PROCESS=None
        CURRENT_TRIAL=None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--history',type=Path,default=Path('/workspace/validation-gate2-evidence/benchmark'))
    parser.add_argument('--worker',choices=('common','full'))
    parser.add_argument('--input',type=Path)
    parser.add_argument('--instrument',action='store_true')
    parser.add_argument('--cpu-limit',type=int,default=60)
    parser.add_argument('--protocol',type=Path,default=PROTOCOL)
    args=parser.parse_args()
    result=worker(args) if args.worker else program(args.output,args.history,args.protocol)
    print(json.dumps({'status':result['status'],'output':str(args.output)}))
    return 0 if result['status'] in ('PASS','COMPLETE') else 3


if __name__=='__main__':
    raise SystemExit(main())
