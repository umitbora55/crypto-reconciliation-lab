"""Neutral A/B instrumentation: execute unchanged against either isolated package."""
import argparse
import cProfile
import json
import hashlib
import sys
import pstats
import time
import traceback
from pathlib import Path
from crypto_reconciliation_lab.lab.common import build_fingerprint, digest_bytes, load, save
from crypto_reconciliation_lab.lab.outcomes import correctness_of
from crypto_reconciliation_lab.lab.worker import environment, peak_rss

MODES = ('normal', 'cprofile')
PROFILE_PHASES = ('ingest_jsonl_seconds', 'reconcile_and_persist_seconds')

CORE_PHASES = ('db_setup_seconds', 'ingest_jsonl_seconds', 'reconcile_and_persist_seconds', 'export_seconds', 'reopen_readback_seconds')

def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

def provenance():
    import importlib.metadata
    import crypto_reconciliation_lab as package
    from crypto_reconciliation_lab.model import RULE_VERSION
    from crypto_reconciliation_lab.migrations import SCHEMA_VERSION
    return dict(interpreter=sys.executable, package_file=str(Path(package.__file__).resolve()),
        package_version=package.__version__, distribution_version=importlib.metadata.version('crypto-reconciliation-lab'),
        financial_rule=RULE_VERSION, schema_version=SCHEMA_VERSION, build_fingerprint=build_fingerprint(),
        python=sys.version, sqlite=__import__('sqlite3').sqlite_version, dont_write_bytecode=sys.dont_write_bytecode, pycache_prefix=sys.pycache_prefix, instrumentation_sha256=digest_bytes(Path(__file__).read_bytes()))

def check_provenance(actual, expected):
    for key in ('package_version', 'schema_version', 'build_fingerprint'):
        if actual[key] != expected[key]:
            raise ValueError('worker provenance differs for ' + key)
    if Path(actual['package_file']).resolve().parent != Path(expected['package_root']).resolve():
        raise ValueError('worker imported outside expected package root')
    if 'bytecode_policy' in expected:
        policy = expected['bytecode_policy']
        if actual['dont_write_bytecode'] is not True or actual['pycache_prefix'] != policy['pycache_prefix']:
            raise ValueError('worker bytecode policy differs')
    if actual['distribution_version'] != actual['package_version'] or actual['financial_rule'] != 'stage2-v2':
        raise ValueError('unexpected distribution/rule')

def index_inventory(db):
    rows = [list(r) for r in db.execute('PRAGMA index_list(receipts)')]
    return dict(user_version=db.execute('PRAGMA user_version').fetchone()[0],receipts_count=db.execute('SELECT COUNT(*) FROM receipts').fetchone()[0],
        sqlite_version=__import__('sqlite3').sqlite_version, index_list=rows,
        indexes={r[1]: dict(info=[list(x) for x in db.execute('PRAGMA index_info("'+r[1].replace('"','""')+'")')],
            xinfo=[list(x) for x in db.execute('PRAGMA index_xinfo("'+r[1].replace('"','""')+'")')]) for r in rows},
        sqlite_master=[list(r) for r in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE tbl_name='receipts' ORDER BY type,name")])

def query_diagnostics(db):
    first=db.execute('SELECT receipt_hash FROM receipts ORDER BY id LIMIT 1').fetchone()
    last=db.execute('SELECT receipt_hash FROM receipts ORDER BY id DESC LIMIT 1').fetchone()
    probes=dict(first=first[0] if first else '', last=last[0] if last else '', missing='not-a-present-receipt-hash')
    return dict(inventory=index_inventory(db), probes={key:dict(hash=value,
        plan=[list(r) for r in db.execute('EXPLAIN QUERY PLAN SELECT raw FROM receipts WHERE receipt_hash=? LIMIT 1',(value,))],
        result=db.execute('SELECT raw FROM receipts WHERE receipt_hash=? LIMIT 1',(value,)).fetchone() is not None)
        for key,value in probes.items()})

def administrative_job(job):
    root=Path(job['trial']); mode=job['mode']; started=time.monotonic()
    record=dict(status='RUNNING',worker_role='generate',correctness='NOT_APPLICABLE',completion_state='RUNNING',timings={},process_cpu_seconds={},provenance=provenance(),provenance_verified=False)
    def save_result():
        record['peak_rss_bytes'],record['peak_rss_method']=peak_rss()
        save(root/'result.tmp',record);(root/'result.tmp').replace(root/'result.json')
    def phase(name, fn):
        save(root/'phase.json',dict(phase=name,started_monotonic=time.monotonic()))
        t,cpu=time.perf_counter(),time.process_time()
        try:return fn()
        finally:
            record['timings'][name]=time.perf_counter()-t
            record['process_cpu_seconds'][name]=time.process_time()-cpu
    try:
        check_provenance(record['provenance'],job['expected'])
        record['provenance_verified']=True
        if mode=='gate':
            from crypto_reconciliation_lab.lab.benchmark import correctness_gate
            gate=phase('gate_seconds',lambda:correctness_gate(job['correctness']))
            record['gate']=dict(status=gate['status'],build_fingerprint=gate['build_fingerprint'],evaluations=gate['evaluations'],cases=len(gate['cases']),report_sha256=file_sha256(job['correctness']))
        elif mode=='generate':
            from crypto_reconciliation_lab.lab.runner import generate_bundle
            record['manifest']=phase('generation_seconds',lambda:generate_bundle(job['bundle'],seeds=(11,),events=job['events'],investors=job['investors'],scenarios=('CLEAN',)))
        elif mode=='probe':
            pass
        else:
            raise ValueError('unsupported administrative mode')
        record.update(status='COMPLETED',completion_state='COMPLETED',elapsed_seconds=time.monotonic()-started)
        save_result();return 0
    except Exception as exc:
        record.update(status='ERROR',completion_state='ERROR',error=repr(exc),traceback=traceback.format_exc())
        if not record['provenance_verified']:
            record.update(correctness='FAILED',status='CORRECTNESS_FAILED')
        save_result();return 2



def run_job(job):
    worker_started = time.monotonic()
    root = Path(job['trial'])
    mode = job['mode']
    if mode not in MODES:
        raise ValueError('unknown profiling mode')
    timings, cpu, profiles = {}, {}, {}
    record = dict(status='RUNNING', worker_role='trial', measurement_mode=mode,
                  correctness='UNKNOWN', completion_state='RUNNING', environment=environment(),
                  timings=timings, process_cpu_seconds=cpu, cpu_profiles=profiles,
                  build_fingerprint=build_fingerprint())
    record['environment'].update(pycache_prefix=sys.pycache_prefix, dont_write_bytecode=sys.dont_write_bytecode, cache_tag=sys.implementation.cache_tag)
    record['variant'] = job.get('variant')
    record['provenance'] = provenance()
    record['provenance_verified'] = False
    store = None

    def checkpoint():
        record['correctness'] = correctness_of(record)
        record['worker_elapsed_seconds'] = time.monotonic() - worker_started
        path = root / 'result.tmp'
        save(path, record)
        path.replace(root / 'result.json')

    def announce(name):
        path = root / 'phase.tmp'
        save(path, dict(phase=name, started_monotonic=time.monotonic()))
        path.replace(root / 'phase.json')

    def auxiliary(name, fn):
        announce(name)
        started, cpu_started = time.perf_counter(), time.process_time()
        try:
            return fn()
        finally:
            timings[name] = timings.get(name, 0) + time.perf_counter() - started
            cpu[name] = cpu.get(name, 0) + time.process_time() - cpu_started

    def phase(name, fn):
        profiler = cProfile.Profile() if mode == 'cprofile' and name in PROFILE_PHASES else None
        announce(name)
        if profiler:
            profiler.enable()
        wall_start, cpu_start = time.perf_counter(), time.process_time()
        try:
            value = fn()
        finally:
            cpu[name] = time.process_time() - cpu_start
            timings[name] = time.perf_counter() - wall_start
            if profiler:
                profiler.disable()
        if name == 'reopen_readback_seconds':
            # Publish a known failure before any fallible profiler work.
            record['restart_equal'] = value
            checkpoint()
        if profiler:
            def cpu_artifacts():
                raw = root / (name + '.pstats')
                profiler.dump_stats(raw)
                stats = pstats.Stats(profiler)
                rows = []
                for (filename, line, function), (primitive, calls, self_time, cumulative, callers) in stats.stats.items():
                    rows.append(dict(file=filename, line=line, function=function, primitive_calls=primitive,
                        calls=calls, self_seconds=self_time, cumulative_seconds=cumulative,
                        callers=[dict(file=k[0], line=k[1], function=k[2], statistics=list(v) if isinstance(v, tuple) else v) for k,v in callers.items()]))
                rows.sort(key=lambda row: (-row['cumulative_seconds'], row['file'], row['line']))
                save(root / (name + '-functions.json'), rows)
                with (root / (name + '-functions.txt')).open('w') as output:
                    pstats.Stats(profiler, stream=output).sort_stats('cumulative').print_stats()
                profiles[name] = dict(raw=raw.name, functions=name + '-functions.json',
                    readable=name + '-functions.txt', total_calls=stats.total_calls,
                    primitive_calls=stats.prim_calls, profiler_total_self_seconds=stats.total_tt)
            auxiliary(name + '_profiler_artifacts_seconds', cpu_artifacts)
        checkpoint()
        return value

    try:
        check_provenance(record['provenance'], job['expected'])
        record['provenance_verified'] = True
        from crypto_reconciliation_lab.store import Store
        from crypto_reconciliation_lab.engine import reconcile
        from crypto_reconciliation_lab.reporting import write_report
        from crypto_reconciliation_lab.lab.scoring import score
        case = Path(job['case'])
        config = load(case / 'config.json')
        expected = load(case / 'expectations.json')[-1]
        inputs = case / 'input.jsonl'
        record.update(seed=job['seed'], original_events=job['events'], investors=job['investors'],
            assets=len(config['assets']), input_sha256=digest_bytes(inputs.read_bytes()),
            config_sha256=digest_bytes((case / 'config.json').read_bytes()),
            generation_seconds=job['generation_seconds'])
        db = root / 'trial.sqlite3'
        store = phase('db_setup_seconds', lambda: Store(db, config))
        record['pragmas'] = {name: store.db.execute('PRAGMA ' + name).fetchone()[0]
            for name in ('synchronous', 'journal_mode', 'foreign_keys', 'page_size', 'cache_size')}
        if record['pragmas']['synchronous'] != 2:
            raise ValueError('FULL synchronous durability is required')
        def ingest():
            count = 0
            with inputs.open() as source:
                for line in source:
                    envelope = json.loads(line)
                    answer = store.ingest(envelope['record'], envelope['received_at'])
                    if answer['status'] != 'ACCEPTED':
                        raise ValueError('CLEAN intake failed: ' + str(answer))
                    count += 1
            return count
        record['index_before_ingest'] = auxiliary('index_inventory_seconds', lambda: index_inventory(store.db))
        receipts = phase('ingest_jsonl_seconds', ingest)
        record['index_after_ingest'] = auxiliary('query_plan_seconds', lambda: query_diagnostics(store.db))
        result = phase('reconcile_and_persist_seconds', lambda: reconcile(store, expected['balance_at'], expected['knowledge_at']))
        phase('export_seconds', lambda: write_report(root / 'report', result))
        record['counts'] = {table: store.db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
            for table in ('records', 'receipts', 'runs', 'findings', 'evidence', 'correction_groups')}
        record['counts']['trace'] = sum(len(ledger['trace']) for ledger in result['ledgers'].values())
        record['counts']['ledger_evidence'] = len(result['evidence'])
        store.close()
        store = None
        def readback():
            reopened = Store(db)
            try:
                return reopened.read_run(result['run_id']) == result
            finally:
                reopened.close()
        record['restart_equal'] = phase('reopen_readback_seconds', readback)
        checkpoint()
        # The scorer and snapshots/serialization never enter ingest/reconcile timers.
        checked = auxiliary('oracle_check_seconds', lambda: score(result, expected, clean=True))
        record['oracle'] = dict(passed=checked['passed'], counters=checked['counters'], errors=checked['errors'])
        record['run_id'] = result['run_id']
        record['receipts_per_ingest_second'] = receipts / timings['ingest_jsonl_seconds']
        checkpoint()
        def inventory():
            return {p.name: dict(bytes=p.stat().st_size, sha256=file_sha256(p))
                for p in sorted(root.iterdir()) if p.is_file() and p.name not in ('result.tmp', 'result.json', 'phase.json', 'stdout.txt', 'stderr.txt')}
        record['files'] = auxiliary('artifact_inventory_seconds', inventory)
        record['peak_rss_bytes'], record['peak_rss_method'] = peak_rss()
        record['financial_phase_wall_seconds'] = sum(timings[k] for k in CORE_PHASES)
        record['financial_phase_cpu_seconds'] = sum(cpu[k] for k in CORE_PHASES)
        record['rss_scope'] = 'Whole worker, including oracle and profiler overhead; not reconcile-only memory.'
        record['status'] = 'COMPLETED' if checked['passed'] and record['restart_equal'] else 'CORRECTNESS_FAILED'
        record['completion_state'] = 'COMPLETED'
        checkpoint()
        return 0 if record['status'] == 'COMPLETED' else 3
    except Exception as exc:
        record.update(status='ERROR', completion_state='ERROR', error=repr(exc), traceback=traceback.format_exc())
        if not record['provenance_verified']:
            record.update(correctness='FAILED', status='CORRECTNESS_FAILED')
        record['peak_rss_bytes'], record['peak_rss_method'] = peak_rss()
        checkpoint()
        return 2
    finally:
        if store is not None:
            store.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--job',required=True);job=load(parser.parse_args().job)
    return run_job(job) if job['mode'] in MODES else administrative_job(job)

if __name__=='__main__':raise SystemExit(main())
