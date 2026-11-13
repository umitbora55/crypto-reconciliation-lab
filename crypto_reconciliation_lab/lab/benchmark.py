"""Budgeted clean scale sweeps, three fresh process/database trials per profile."""
from dataclasses import asdict
import os
from pathlib import Path
import shutil
import statistics
import sys
import tempfile
import time
from . import GENERATOR_VERSION,FAULT_PLAN_VERSION
from .common import build_fingerprint,digest_bytes,fresh,load,save
from .faults import SCENARIOS
from .watchdog import Budgets,current_rss,supervise
from .contracts import EXPERIMENT_VERSION,validate_gate,ContractError
from .outcomes import normalize_outcome,correctness_of

PROFILES=(('events_100',100,20,'events'),('investors_10',1000,10,'investors'),('events_1000',1000,20,'events'),
          ('investors_100',1000,100,'investors'),('investors_300',1000,300,'investors'),('events_10000',10000,20,'events'))
TIMINGS=('db_setup_seconds','ingest_jsonl_seconds','reconcile_and_persist_seconds','export_seconds','reopen_readback_seconds')


def correctness_gate(path):
    from .scoring import COUNTERS
    report=load(path)
    try:validate_gate(report,COUNTERS,build_fingerprint())
    except (KeyError,TypeError,IndexError,AttributeError) as exc:raise ContractError(str(path),'malformed gate report: '+str(exc)) from exc
    return report


def statistics_for(trials):
    completed=[t['worker'] for t in trials if t.get('status')=='COMPLETED' and t.get('completion_state')=='COMPLETED' and t.get('correctness')=='PASSED' and correctness_of(t.get('worker'))=='PASSED']
    if len(trials)!=3 or len(completed)!=3:return None
    if len({r['input_sha256'] for r in completed})!=1 or len({str(r['pragmas']) for r in completed})!=1:
        raise ValueError('trial input or durability settings differ')
    series={name:[r['timings'][name] for r in completed] for name in TIMINGS}
    series['peak_rss_bytes']=[r['peak_rss_bytes'] for r in completed]
    series['receipts_per_ingest_second']=[r['receipts_per_ingest_second'] for r in completed]
    for key in ('sqlite_bytes','json_bytes','markdown_bytes'):
        filename={'sqlite_bytes':'trial.sqlite3','json_bytes':'report.json','markdown_bytes':'report.md'}[key]
        series[key]=[r['files'][filename]['bytes'] for r in completed]
    return {key:dict(raw=values,min=min(values),median=statistics.median(values),max=max(values)) if all(v is not None for v in values) else dict(raw=values,min=None,median=None,max=None) for key,values in series.items()}


def markdown(report):
    lines=['# Stage 3 resource-budgeted benchmark','','Fresh file-based DBs are not a cold-cache guarantee. Three trials include the first run; no p95 or production capacity claim.',
           'reconcile_and_persist_seconds includes computation and durable run/findings/evidence writes. Export includes both full JSON and Markdown.',
           'Oracle comparison is outside the measured engine phases. RSS and disk targets use sampled watchdog enforcement; short spikes can escape sampling.',
           '',f"Gate: {report['gate_status']}; trial correctness: {report['correctness']}; completion: {report['completion_state']}; benchmark: {report['status']}; scope: {report['benchmark_scope']}.",'',
           '| Profile | Events | Investors | Status / reason | Trials completed | Median ingest / reconcile+persist / export seconds | Peak RSS bytes (max) | DB / JSON / Markdown bytes (max) |',
           '|---|---|---|---|---|---|---|---|']
    for p in report['profiles']:
        s=p.get('statistics');timing=' / '.join(f'{s[k]["median"]:.6f}' for k in ('ingest_jsonl_seconds','reconcile_and_persist_seconds','export_seconds')) if s else 'not a completed three-trial profile'
        memory=str(s['peak_rss_bytes']['max']) if s else 'see partial observations'
        sizes=' / '.join(str(s[k]['max']) for k in ('sqlite_bytes','json_bytes','markdown_bytes')) if s else 'see partial observations'
        lines.append(f"| {p['profile']} | {p['events']} | {p['investors']} | {p['status']} / correctness={p['correctness']} / completion={p['completion_state']}: {p.get('reason') or ''} | {sum(t['status']=='COMPLETED' for t in p.get('trials',[]))}/3 | {timing} | {memory} | {sizes} |")
    for p in report['profiles']:
        lines += ['',f"## {p['profile']}",'',f"Generation seconds: {p.get('generation_seconds')}. Input hash: `{p.get('input_sha256')}`.",'']
        if p.get('statistics'):
            lines += ['| Metric | Three raw trials | Min | Median | Max |','|---|---|---|---|---|']
            lines += [f"| {k} | {v['raw']} | {v['min']} | {v['median']} | {v['max']} |" for k,v in p['statistics'].items()]
        else:
            lines += ['```json',__import__('json').dumps([dict(status=t['status'],correctness=t.get('correctness'),completion_state=t.get('completion_state'),reason=t.get('reason'),exit_code=t.get('exit_code'),last_observation=t.get('last_observation')) for t in p.get('trials',[])],indent=2),'```']
    lines += ['','## Interpretation','',report['interpretation'],'', 'Complete raw worker measurements, environment, PRAGMAs, file hashes and monitoring methods are in benchmark.json.']
    return '\n'.join(lines)+'\n'


def run_benchmark(correctness,output,budgets=None,seed=11,stress=False,smoke=False):
    if stress and smoke:raise ValueError('smoke and stress are mutually exclusive')
    gate=correctness_gate(correctness);budgets=budgets or Budgets();root=fresh(output)
    report=dict(status='RUNNING',completion_state='RUNNING',correctness='UNKNOWN',gate_status='PASS',experiment_contract_version=EXPERIMENT_VERSION,benchmark_scope='SMOKE_ONE_PROFILE' if smoke else 'FULL_PROFILES',correctness_report_sha256=digest_bytes(Path(correctness).read_bytes()),
                build_fingerprint=gate['build_fingerprint'],seed=seed,budgets=asdict(budgets),profiles=[],
                rss_monitor_available=current_rss(os.getpid()) is not None,stress_requested=stress,
                interpretation='Measurements pending; no optimization performed.')
    deadline=time.monotonic()+budgets.total_seconds;blocked=[];halt=None
    profiles=list(PROFILES[:1] if smoke else PROFILES)
    if stress:profiles.append(('stress_100000',100000,20,'stress'))
    def checkpoint():save(root/'benchmark.json',report);(root/'benchmark.md').write_text(markdown(report))
    checkpoint()
    env=os.environ.copy();env.pop('PYTHONPATH',None)
    flags=['-I'] if sys.flags.isolated else []
    def launch(job,temp,trial):
        jobpath=temp/(trial.parent.name+'-'+trial.name+'-job.json');save(jobpath,job)
        outcome=supervise([sys.executable,*flags,'-m','crypto_reconciliation_lab.lab.worker','--job',jobpath],Path.cwd(),trial,temp,budgets,deadline,env)
        return normalize_outcome(outcome,job['mode'])
    with tempfile.TemporaryDirectory(prefix='crypto-stage3-benchmark-') as directory:
        temp=Path(directory).resolve();(temp/'STAGE3_OWNED').write_text('Only this temporary tree may be removed by the benchmark.\n')
        for name,events,investors,sweep in profiles:
            p=dict(profile=name,events=events,investors=investors,assets=2,sweep=sweep,trials=[],status='NOT_ATTEMPTED_BUDGET',completion_state='NOT_ATTEMPTED_BUDGET',correctness='UNKNOWN')
            report['profiles'].append(p)
            reason=None
            if halt:reason=halt;p['status']='NOT_ATTEMPTED_CORRECTNESS' if halt=='prior oracle mismatch' else 'NOT_ATTEMPTED_ERROR'
            elif time.monotonic()>=deadline:reason='total 20-minute/configured benchmark deadline exhausted'
            elif any(events>=e and investors>=i for e,i in blocked):reason='larger related profile blocked by an earlier resource/time budget'
            elif sweep=='stress' and (not report['rss_monitor_available'] or not all(x['status']=='COMPLETED' for x in report['profiles'][:-1])):
                reason='stress requires all smaller profiles and working RSS monitoring'
            if reason:
                p['reason']=reason;p['completion_state']=p['status']
                p['trials']=[dict(status=p['status'],completion_state=p['status'],correctness='UNKNOWN',reason=reason,exit_code=None) for _ in range(3)]
                checkpoint();continue
            profile=temp/name;profile.mkdir();bundle=profile/'bundle';gen_trial=profile/'generation'
            generation=launch(dict(mode='generate',trial=str(gen_trial),bundle=str(bundle),seed=seed,events=events,investors=investors),temp,gen_trial)
            p['generation']=generation
            if generation['status']!='COMPLETED':
                p.update(status=generation['status'],completion_state=generation['completion_state'],reason='generation '+str(generation.get('reason')))
                p['trials']=[dict(status='NOT_ATTEMPTED_BUDGET' if generation['status'] in ('RESOURCE_LIMIT','TIMED_OUT') else 'NOT_ATTEMPTED_ERROR',correctness='UNKNOWN',completion_state='NOT_ATTEMPTED',exit_code=None,reason='generation did not complete') for _ in range(3)]
                if p['status'] in ('RESOURCE_LIMIT','TIMED_OUT'):blocked.append((events,investors))
                else:halt='generation application error'
                generation['partial_files']={str(f.relative_to(profile)):dict(bytes=f.stat().st_size,sha256=digest_bytes(f.read_bytes())) for f in profile.rglob('*') if f.is_file()}
                failure=root/name/'generation';failure.mkdir(parents=True)
                for filename in ('stdout.txt','stderr.txt','result.json','phase.json'):
                    if (gen_trial/filename).exists():shutil.copy2(gen_trial/filename,failure/filename)
                checkpoint();shutil.rmtree(profile);continue
            p['generation_seconds']=generation['worker']['timings']['generation_seconds']
            case=bundle/f'seed-{seed}/CLEAN';p['input_sha256']=digest_bytes((case/'input.jsonl').read_bytes())
            for trial_number in range(1,4):
                trial=profile/f'trial-{trial_number}'
                if p['trials'] and p['trials'][-1]['status']!='COMPLETED':
                    state='NOT_ATTEMPTED_CORRECTNESS' if halt=='prior oracle mismatch' else 'NOT_ATTEMPTED_ERROR' if halt else 'NOT_ATTEMPTED_BUDGET'
                    p['trials'].append(dict(status=state,completion_state=state,correctness='UNKNOWN',reason='prior trial stopped this profile',exit_code=None));continue
                job=dict(mode='trial',trial=str(trial),case=str(case),seed=seed,events=events,investors=investors,
                         generator_version=GENERATOR_VERSION,fault_plan_version=FAULT_PLAN_VERSION,generation_seconds=p['generation_seconds'])
                measured=launch(job,temp,trial);p['trials'].append(measured)
                # Preserve worker logs/records; keep complete small reports and failures.
                destination=root/name/f'trial-{trial_number}';destination.mkdir(parents=True)
                if trial.exists():
                    for filename in ('stdout.txt','stderr.txt','result.json','phase.json'):
                        if (trial/filename).exists():shutil.copy2(trial/filename,destination/filename)
                if measured['status']=='COMPLETED':
                    if events<=100:
                        for filename in ('report.json','report.md'):shutil.copy2(trial/filename,destination/filename)
                    measured['artifacts_removed_after_measurement']=True
                    # Hashes/sizes and complete metadata are persisted before cleanup.
                    checkpoint();shutil.rmtree(trial)
                else:
                    p['status']=measured['status'];p['completion_state']=measured['completion_state'];p['correctness']=measured['correctness'];p['reason']=measured.get('reason')
                    measured['partial_files']={str(f.relative_to(trial)):dict(bytes=f.stat().st_size,sha256=digest_bytes(f.read_bytes())) for f in trial.rglob('*') if f.is_file()}
                    if measured['correctness']=='FAILED':
                        halt='prior oracle mismatch';shutil.copytree(case,destination/'counterexample-input');shutil.copy2(bundle/f'seed-{seed}/truth.json',destination/'truth.json')
                        for filename in ('report.json','report.md'):
                            if (trial/filename).exists():shutil.copy2(trial/filename,destination/filename)
                        (destination/'REPRODUCE.md').write_text(f'Generate identical clean input: `python3 -m crypto_reconciliation_lab lab-generate --seed {seed} --events {events} --investors {investors} --scenario CLEAN --output replay-input`\nThen `python3 -m crypto_reconciliation_lab lab-verify --input replay-input --output replay-results`.\n')
                    elif measured['status']=='ERROR':halt='prior worker application error'
                    else:blocked.append((events,investors))
                    checkpoint();shutil.rmtree(trial,ignore_errors=True)
                checkpoint()
            p['correctness']='FAILED' if any(t['correctness']=='FAILED' for t in p['trials']) else 'PASSED' if all(t['correctness']=='PASSED' for t in p['trials']) else 'UNKNOWN'
            if all(t['status']=='COMPLETED' for t in p['trials']):
                try:p['statistics']=statistics_for(p['trials'])
                except ValueError as exc:p['statistics']=None;p['reason']=str(exc)
                if p['statistics'] is None:p.update(status='ERROR',completion_state='ERROR',reason='unverified/incompatible trials');halt='invalid trial statistics'
                else:p.update(status='COMPLETED',completion_state='COMPLETED',correctness='PASSED')
            checkpoint()
            shutil.rmtree(profile)
    completions={p['completion_state'] for p in report['profiles']}
    report['correctness']='FAILED' if any(p['correctness']=='FAILED' for p in report['profiles']) else 'PASSED' if all(p['correctness']=='PASSED' for p in report['profiles']) else 'UNKNOWN'
    report['completion_state']='ERROR' if 'ERROR' in completions else 'COMPLETED' if completions=={'COMPLETED'} else 'PARTIAL_BUDGET' if completions&{'RESOURCE_LIMIT','TIMED_OUT','NOT_ATTEMPTED_BUDGET'} else 'STOPPED_EARLY'
    report['status']='CORRECTNESS_FAILED' if report['correctness']=='FAILED' else 'ERROR' if report['completion_state']=='ERROR' else 'COMPLETED' if report['completion_state']=='COMPLETED' else 'PARTIAL_BUDGET'
    complete=[p for p in report['profiles'] if p['status']=='COMPLETED']
    if complete:
        largest=max(complete,key=lambda p:(p['events'],p['investors']));s=largest['statistics']
        slow=max(('db_setup_seconds','ingest_jsonl_seconds','reconcile_and_persist_seconds','export_seconds'),key=lambda k:s[k]['median'])
        report['interpretation']=f"For completed profile {largest['profile']}, the largest measured median phase was {slow} ({s[slow]['median']:.6f}s). This is phase-level timing, not a CPU/I/O profiler attribution. Event and investor sweeps are reported separately; evidence/trace/output size must be considered with time and RSS. A next narrow task should profile this phase on the same hashes before changing code, then rerun the complete correctness matrix, historical preservation checks and the same three-trial profiles. Any inner-function cause remains a hypothesis. No performance optimization was made."
    else:report['interpretation']='No complete three-trial profile: no throughput or bottleneck conclusion. Inspect budget/error observations; do not infer production capacity.'
    checkpoint();return report
