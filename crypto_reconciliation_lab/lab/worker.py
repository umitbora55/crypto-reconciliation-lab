"""One fresh-process generation or durable SQLite benchmark trial."""
import argparse
import json
import platform
import resource
import sqlite3
import sys
import time
import traceback
from pathlib import Path
from .common import digest_bytes,load,save
from .outcomes import correctness_of


def peak_rss():
    raw=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    system=platform.system()
    if system=='Darwin':return int(raw),'getrusage(RUSAGE_SELF).ru_maxrss; macOS bytes'
    if system=='Linux':return int(raw)*1024,'getrusage(RUSAGE_SELF).ru_maxrss; Linux KiB converted to bytes'
    return None,'ru_maxrss units not supported on this OS'


def environment():
    import crypto_reconciliation_lab as package
    return dict(os=platform.platform(),architecture=platform.machine(),python=sys.version,sqlite=sqlite3.sqlite_version,
                interpreter=sys.executable,package_version=package.__version__,package_file=package.__file__)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--job',required=True);args=parser.parse_args()
    job=load(args.job);root=Path(job['trial']);timings={};record=dict(status='RUNNING',worker_role=job['mode'],correctness='NOT_APPLICABLE' if job['mode']=='generate' else 'UNKNOWN',completion_state='RUNNING',environment=environment(),timings=timings)
    def checkpoint():
        record['correctness']=correctness_of(record,job['mode'])
        tmp=root/'result.tmp';save(tmp,record);tmp.replace(root/'result.json')
    def phase(name,fn):
        tmp=root/'phase.tmp';save(tmp,dict(phase=name,started_monotonic=time.monotonic()));tmp.replace(root/'phase.json')
        start=time.perf_counter();value=fn();timings[name]=time.perf_counter()-start;return value
    store=None
    try:
        if job['mode']=='generate':
            from .runner import generate_bundle
            manifest=phase('generation_seconds',lambda:generate_bundle(job['bundle'],seeds=(job['seed'],),events=job['events'],investors=job['investors'],scenarios=('CLEAN',)))
            record.update(status='COMPLETED',manifest=manifest)
        else:
            from ..store import Store
            from ..engine import reconcile
            from ..reporting import write_report
            from .scoring import score
            case=Path(job['case']);config=load(case/'config.json');phases=load(case/'expectations.json');expected=phases[-1]
            inputs=case/'input.jsonl'
            record.update(seed=job['seed'],config=config,generator_version=job['generator_version'],fault_plan_version=job['fault_plan_version'],
                          input_sha256=digest_bytes(inputs.read_bytes()),config_sha256=digest_bytes((case/'config.json').read_bytes()),
                          original_events=job['events'],investors=job['investors'],assets=len(config['assets']),corrections=0,
                          generation_seconds=job['generation_seconds'])
            db=root/'trial.sqlite3'
            store=phase('db_setup_seconds',lambda:Store(db,config))
            record['pragmas']={name:store.db.execute('PRAGMA '+name).fetchone()[0] for name in ('synchronous','journal_mode','foreign_keys','page_size','cache_size')}
            if record['pragmas']['synchronous']!=2:raise ValueError('FULL synchronous durability is required')
            def ingest():
                count=0
                with inputs.open() as source:
                    for line in source:
                        row=json.loads(line);response=store.ingest(row['record'],row['received_at'])
                        if response['status']!='ACCEPTED':raise ValueError('clean input intake failed: '+str(response))
                        count+=1
                return count
            receipts=phase('ingest_jsonl_seconds',ingest)
            result=phase('reconcile_and_persist_seconds',lambda:reconcile(store,expected['balance_at'],expected['knowledge_at']))
            phase('export_seconds',lambda:write_report(root/'report',result))
            record['counts']={t:store.db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('records','receipts','findings','evidence','correction_groups')}
            record['counts']['trace']=sum(len(l['trace']) for l in result['ledgers'].values())
            store.close();store=None
            def readback():
                reopened=Store(db)
                try:return reopened.read_run(result['run_id'])==result
                finally:reopened.close()
            record['restart_equal']=phase('reopen_readback_seconds',readback)
            checkpoint()
            # Reference comparisons are explicitly outside setup/ingest/reconcile/export timings.
            checked=phase('oracle_check_seconds',lambda:score(result,expected,clean=True))
            record['oracle']=dict(passed=checked['passed'],counters=checked['counters'],errors=checked['errors'])
            checkpoint()
            record['run_id']=result['run_id']
            record['receipts_per_ingest_second']=receipts/timings['ingest_jsonl_seconds']
            def inventory():
                return {p.name:dict(bytes=p.stat().st_size,sha256=digest_bytes(p.read_bytes())) for p in sorted(root.iterdir()) if p.name.startswith(('trial.sqlite3','report.')) and p.is_file()}
            record['files']=phase('artifact_inventory_seconds',inventory)
            record['status']='COMPLETED' if checked['passed'] and record['restart_equal'] else 'CORRECTNESS_FAILED'
        record['peak_rss_bytes'],record['peak_rss_method']=peak_rss()
        record['completion_state']='COMPLETED'
        checkpoint()
        return 0 if record['status']=='COMPLETED' else 3
    except Exception as exc:
        record.update(status='ERROR',error=repr(exc),traceback=traceback.format_exc())
        record['peak_rss_bytes'],record['peak_rss_method']=peak_rss();record['completion_state']='ERROR';checkpoint()
        return 2
    finally:
        if store is not None:store.close()

if __name__=='__main__':raise SystemExit(main())
