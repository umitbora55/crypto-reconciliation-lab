"""Fresh durable trial with optional, isolated CPU or Python allocation profiling."""
import argparse
import cProfile
import json
import sys
import pstats
import time
import traceback
import tracemalloc
from pathlib import Path
from .common import build_fingerprint, digest_bytes, load, save
from .outcomes import correctness_of
from .worker import environment, peak_rss

MODES = ('normal', 'cprofile', 'tracemalloc')
PROFILE_PHASES = ('ingest_jsonl_seconds', 'reconcile_and_persist_seconds')


def run_job(job):
    root = Path(job['trial'])
    mode = job['mode']
    if mode not in MODES:
        raise ValueError('unknown profiling mode')
    timings, cpu, profiles, memory = {}, {}, {}, {}
    record = dict(status='RUNNING', worker_role='trial', measurement_mode=mode,
                  correctness='UNKNOWN', completion_state='RUNNING', environment=environment(),
                  timings=timings, process_cpu_seconds=cpu, cpu_profiles=profiles,
                  python_memory=memory, build_fingerprint=build_fingerprint())
    record['environment'].update(pycache_prefix=sys.pycache_prefix, cache_tag=sys.implementation.cache_tag)
    store = None

    def checkpoint():
        record['correctness'] = correctness_of(record)
        path = root / 'result.tmp'
        save(path, record)
        path.replace(root / 'result.json')

    def announce(name):
        path = root / 'phase.tmp'
        save(path, dict(phase=name, started_monotonic=time.monotonic()))
        path.replace(root / 'phase.json')

    def auxiliary(name, fn):
        announce(name)
        started = time.perf_counter()
        value = fn()
        timings[name] = timings.get(name, 0) + time.perf_counter() - started
        return value

    def phase(name, fn):
        before = None
        if mode == 'tracemalloc':
            before = auxiliary(name + '_snapshot_before_seconds', tracemalloc.take_snapshot)
            start_current = tracemalloc.get_traced_memory()[0]
            tracemalloc.reset_peak()
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
        if mode == 'tracemalloc':
            end_current, peak = tracemalloc.get_traced_memory()
        if name == 'reopen_readback_seconds':
            # Publish a known failure before any fallible profiler work.
            record['restart_equal'] = value
            checkpoint()
        if mode == 'tracemalloc':
            def snapshot_artifacts():
                after = tracemalloc.take_snapshot()
                before.dump(str(root / (name + '-before.snapshot')))
                after.dump(str(root / (name + '-after.snapshot')))
                diffs = after.compare_to(before, 'lineno')
                memory[name] = dict(start_current_bytes=start_current, end_current_bytes=end_current,
                    peak_since_reset_bytes=peak, net_live_bytes=sum(x.size_diff for x in diffs),
                    net_live_blocks=sum(x.count_diff for x in diffs),
                    top_net_live_differences=[dict(traceback=str(x.traceback), size_diff_bytes=x.size_diff,
                        count_diff=x.count_diff, current_size_bytes=x.size, current_blocks=x.count) for x in diffs[:30]],
                    interpretation='Snapshot differences are net live Python allocations, not total allocation traffic; native SQLite and whole-worker RSS are separate.')
            auxiliary(name + '_snapshot_artifacts_seconds', snapshot_artifacts)
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
        from ..store import Store
        from ..engine import reconcile
        from ..reporting import write_report
        from .scoring import score
        case = Path(job['case'])
        config = load(case / 'config.json')
        expected = load(case / 'expectations.json')[-1]
        inputs = case / 'input.jsonl'
        record.update(seed=job['seed'], original_events=job['events'], investors=job['investors'],
            assets=len(config['assets']), input_sha256=digest_bytes(inputs.read_bytes()),
            config_sha256=digest_bytes((case / 'config.json').read_bytes()),
            generation_seconds=job['generation_seconds'])
        if mode == 'tracemalloc':
            tracemalloc.start(10)
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
        receipts = phase('ingest_jsonl_seconds', ingest)
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
        if mode == 'tracemalloc':
            record['python_traced_after_oracle'] = dict(zip(('current_bytes', 'peak_bytes'), tracemalloc.get_traced_memory()))
            tracemalloc.stop()
        def inventory():
            return {p.name: dict(bytes=p.stat().st_size, sha256=digest_bytes(p.read_bytes()))
                for p in sorted(root.iterdir()) if p.is_file() and p.name not in ('result.tmp', 'result.json', 'phase.json', 'stdout.txt', 'stderr.txt')}
        record['files'] = auxiliary('artifact_inventory_seconds', inventory)
        record['peak_rss_bytes'], record['peak_rss_method'] = peak_rss()
        record['rss_scope'] = 'Whole worker, including oracle and profiler overhead; not reconcile-only memory.'
        record['status'] = 'COMPLETED' if checked['passed'] and record['restart_equal'] else 'CORRECTNESS_FAILED'
        record['completion_state'] = 'COMPLETED'
        checkpoint()
        return 0 if record['status'] == 'COMPLETED' else 3
    except Exception as exc:
        record.update(status='ERROR', completion_state='ERROR', error=repr(exc), traceback=traceback.format_exc())
        record['peak_rss_bytes'], record['peak_rss_method'] = peak_rss()
        checkpoint()
        return 2
    finally:
        if store is not None:
            store.close()
        if tracemalloc.is_tracing():
            tracemalloc.stop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--job', required=True)
    return run_job(load(parser.parse_args().job))


if __name__ == '__main__':
    raise SystemExit(main())
