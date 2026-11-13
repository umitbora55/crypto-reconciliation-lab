"""Sequential, fingerprint-gated A/B measurement with one shared performance budget."""
import argparse
from contextlib import contextmanager
import importlib.util
from dataclasses import asdict
import json
import hashlib
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from crypto_reconciliation_lab.lab.common import digest_bytes, fresh, load, save
from crypto_reconciliation_lab.lab.outcomes import normalize_outcome, correctness_of
from crypto_reconciliation_lab.lab.watchdog import Budgets, directory_bytes, supervise, current_rss

PROFILES = (('P1',1000,20),('P3',1000,100),('P2',10000,20))
PAIR_ORDERS = (('A','B'),('B','A'),('A','B'))
CORE_PHASES = ('db_setup_seconds','ingest_jsonl_seconds','reconcile_and_persist_seconds','export_seconds','reopen_readback_seconds')


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

def skipped(variant, pair, position, mode, state, reason):
    return dict(variant=variant,pair=pair,order_in_pair=position,measurement_mode=mode,
        status=state,completion_state=state,correctness='UNKNOWN',exit_code=None,reason=reason)


def completion(states):
    if states == {'COMPLETED'}: return 'COMPLETED'
    if states & {'ERROR','NOT_ATTEMPTED_ERROR'}: return 'ERROR'
    if states & {'TIMED_OUT','RESOURCE_LIMIT','NOT_ATTEMPTED_BUDGET','PARTIAL_BUDGET'}: return 'PARTIAL_BUDGET'
    if states & {'NOT_ATTEMPTED_CORRECTNESS','STOPPED_CORRECTNESS'}: return 'STOPPED_CORRECTNESS'
    return 'STOPPED_EARLY'


def signature(worker):
    return tuple(worker[k] for k in ('input_sha256','config_sha256','run_id')) + (
        worker['files']['report.json']['sha256'],worker['files']['report.md']['sha256'],
        json.dumps(worker['pragmas'],sort_keys=True),json.dumps(worker['counts'],sort_keys=True))


def verified(trial):
    return (trial.get('status')=='COMPLETED' and trial.get('completion_state')=='COMPLETED'
        and trial.get('correctness')=='PASSED' and correctness_of(trial.get('worker'))=='PASSED')


def metric_values(trial):
    worker=trial['worker']
    values=dict(worker['timings'])
    values.update({'cpu_'+k:v for k,v in worker['process_cpu_seconds'].items()})
    values.update(financial_phase_wall_seconds=sum(worker['timings'][k] for k in CORE_PHASES),
        financial_phase_cpu_seconds=sum(worker['process_cpu_seconds'][k] for k in CORE_PHASES),
        supervisor_worker_elapsed_seconds=trial['elapsed_seconds'],
        worker_elapsed_seconds=worker.get('worker_elapsed_seconds',trial['elapsed_seconds']),
        unattributed_elapsed_seconds=trial['elapsed_seconds']-sum(worker['timings'].values()),
        peak_rss_bytes=worker['peak_rss_bytes'],receipts_per_ingest_second=worker['receipts_per_ingest_second'])
    values.update({key:worker['files'][filename]['bytes'] for key,filename in
        [('sqlite_bytes','trial.sqlite3'),('json_bytes','report.json'),('markdown_bytes','report.md')]})
    return values


def normal_statistics(trials,variant):
    chosen=[t for t in trials if t['variant']==variant and t['measurement_mode']=='normal']
    if len(chosen)!=3 or not all(verified(t) for t in chosen):return None
    if len({signature(t['worker']) for t in chosen})!=1:raise ValueError('incompatible normal trials')
    values=[metric_values(t) for t in chosen]
    return {k:dict(raw=[v[k] for v in values],min=min(v[k] for v in values),
        median=statistics.median(v[k] for v in values),max=max(v[k] for v in values)) for k in values[0]}


def paired_results(trials):
    result=[]
    for number,order in enumerate(PAIR_ORDERS,1):
        pair=[t for t in trials if t.get('pair')==number and t['measurement_mode']=='normal']
        row=dict(pair=number,order=list(order),verified=len(pair)==2 and all(verified(t) for t in pair),metrics=None)
        if row['verified']:
            values={t['variant']:metric_values(t) for t in pair}
            row['metrics']={k:dict(A=a,B=values['B'][k],B_minus_A=values['B'][k]-a,
                B_over_A=values['B'][k]/a if a else None) for k,a in values['A'].items()}
        result.append(row)
    return result


def runtime_flags(pycache_prefix):
    return ['-I','-B','-X','pycache_prefix='+str(Path(pycache_prefix).resolve())]

def inspect_variant(python, correctness, cwd, pycache_prefix):
    if Path(pycache_prefix).exists():raise ValueError('bytecode cache prefix must not exist')
    code=('import json,sys,importlib.metadata,crypto_reconciliation_lab as p; '
        'from crypto_reconciliation_lab.lab.common import build_fingerprint; '
        'from crypto_reconciliation_lab.migrations import SCHEMA_VERSION; '
        'print(json.dumps(dict(package_version=p.__version__,distribution_version=importlib.metadata.version("crypto-reconciliation-lab"),'
        'package_root=str(__import__("pathlib").Path(p.__file__).resolve().parent),package_file=p.__file__,schema_version=SCHEMA_VERSION,'
        'build_fingerprint=build_fingerprint(),python=sys.version,interpreter=sys.executable,dont_write_bytecode=sys.dont_write_bytecode,pycache_prefix=sys.pycache_prefix,sqlite=__import__("sqlite3").sqlite_version)))')
    env=os.environ.copy();env.pop('PYTHONPATH',None);start=time.monotonic()
    command=[str(python),*runtime_flags(pycache_prefix),'-c',code]
    p=subprocess.run(command,cwd=cwd,env=env,capture_output=True,text=True)
    proof=dict(command=command,cwd=str(cwd),exit_code=p.returncode,seconds=time.monotonic()-start,stdout=p.stdout,stderr=p.stderr,PYTHONPATH_removed=True)
    if p.returncode:raise ValueError('variant import failed: '+json.dumps(proof))
    actual=json.loads(p.stdout)
    if actual['package_version']!=actual['distribution_version']:raise ValueError('package/distribution differs')
    actual.update(python_executable=str(Path(python).absolute()),correctness=str(Path(correctness).resolve()),import_proof=proof)
    return actual


def markdown(report):
    lines=['# Stage 3.3 fresh A/B comparison','',
        f"Status={report['status']}; correctness={report['correctness']}; completion={report['completion_state']}.",
        'Three paired normal observations per variant, including first runs. Order AB, BA, AB. No outliers removed, p95 or statistical certainty claimed.',
        'Financial phases exclude scorer, query diagnostics, profiler serialization and hashing. Whole worker and unassigned elapsed gaps remain separate.',
        '', '| Profile | Variant | Normal complete | Median ingest / reconcile / export seconds | SQLite bytes |', '|---|---|---|---|---|']
    for p in report['profiles']:
        for variant in ('A','B'):
            stats=p.get('statistics',{}).get(variant)
            durations=' / '.join(f'{stats[k]["median"]:.6f}' for k in ('ingest_jsonl_seconds','reconcile_and_persist_seconds','export_seconds')) if stats else 'unavailable'
            n=sum(verified(t) for t in p['trials'] if t['variant']==variant)
            lines.append(f"| {p['profile']} | {variant} | {n}/3 | {durations} | {stats['sqlite_bytes']['median'] if stats else 'unavailable'} |")
    lines += ['', 'All raw normal min/median/max, pair differences/ratios, exact provenance, count/size/hash data, query plans and separate diagnostic outcomes are in ab.json.',
        'One shared 1200-second deadline includes generation, normal workers, at most two P2 cProfile workers, retention and reporting. Sampled limits are not hard allocation caps.']
    return '\n'.join(lines)+'\n'


@contextmanager
def owned_jobs(root):
    path=Path(tempfile.mkdtemp(prefix='owned-ab-',dir=root))
    try:yield path
    except BaseException:
        # Preserve raw jobs/input on unexpected checkpoint or retention failure.
        raise
    else:shutil.rmtree(path)


def _run_ab_runtime(variants, output, budgets=None, profiles=PROFILES, worker_script=None, cwd=None, invocation=None, pycache_prefix=None, controller_script=None, storage=None, prepared=False):
    budgets=budgets or Budgets();profiles=tuple(profiles)
    if not profiles or len({p[0] for p in profiles})!=len(profiles):raise ValueError('nonempty unique profile roster required')
    if set(variants)!={'A','B'}:raise ValueError('two explicit variants required')
    worker_script=Path(worker_script or Path(__file__).with_name('ab_worker_stage3_3.py')).resolve()
    cwd=Path(cwd or Path.cwd()).resolve();root=(Path(output) if prepared else fresh(output)).resolve()
    controller_script=Path(controller_script or __file__).resolve()
    budget_root=Path(storage["owned_runtime"]) if storage else root
    pycache_prefix=Path(pycache_prefix or root/'unused-bytecode-cache').resolve()
    if pycache_prefix.exists():raise ValueError('bytecode cache prefix must not exist')
    policy=dict(pycache_prefix=str(pycache_prefix),dont_write_bytecode=True,flags=runtime_flags(pycache_prefix),fresh_nonexistent_before=True)
    for variant in variants.values():variant['bytecode_policy']=dict(policy)
    env=os.environ.copy();env.pop('PYTHONPATH',None)
    report=dict(status='GATING',completion_state='GATING',correctness='UNKNOWN',version='stage3.3-ab-v1',
        variants=variants,baseline_fingerprint=variants['A']['build_fingerprint'],candidate_fingerprint=variants['B']['build_fingerprint'],
        instrumentation_sha256=digest_bytes(worker_script.read_bytes()),controller_sha256=digest_bytes(controller_script.read_bytes()),
        budgets=asdict(budgets),profile_order=[p[0] for p in profiles],pair_orders=[list(x) for x in PAIR_ORDERS],
        profiles=[],diagnostics=[],gate_status='RUNNING',gates={},seed=11,shared_deadline=True,invocation=invocation,bytecode_policy=policy,storage=storage)
    start=None;deadline=None;halt=None;blocked=[];signature_by_profile={};case_by_profile={}
    def checkpoint():
        report['elapsed_seconds']=0 if start is None else time.monotonic()-start
        save(root/'ab.json',report);(root/'ab.md').write_text(markdown(report))
    def launch(job,temp,trial,limit=None):
        variant=job['variant'];job['expected']=variants[variant]
        path=temp/(trial.parent.name+'-'+trial.name+'-job.json');save(path,job)
        worker_budgets=Budgets(**{**asdict(budgets),'temporary_bytes':max(1,budgets.temporary_bytes-directory_bytes(Path(storage['retained_destination'])) if storage else budgets.temporary_bytes)})
        result=supervise([variants[variant]['python_executable'],*runtime_flags(pycache_prefix),worker_script,'--job',path],cwd,trial,budget_root,
            worker_budgets,deadline if limit is None else limit,env)
        result=normalize_outcome(result,'trial' if job['mode'] in ('normal','cprofile') else 'generate')
        if (result.get('worker') or {}).get('provenance_verified') is False:
            result.update(correctness='FAILED',status='CORRECTNESS_FAILED',reason='worker provenance verification failed')
        result.update(variant=variant,measurement_mode=job['mode'],worker_job=job)
        return result
    def budget_after_parent(outcome):
        reason=None
        if deadline is not None and time.monotonic()>=deadline:reason='shared deadline during parent retention/reporting';state='TIMED_OUT'
        elif directory_bytes(budget_root)+(directory_bytes(Path(storage['retained_destination'])) if storage else 0)>budgets.temporary_bytes:reason='experiment tree budget during retention';state='RESOURCE_LIMIT'
        if reason:
            outcome.update(completion_state=state,status='CORRECTNESS_FAILED' if outcome['correctness']=='FAILED' else state,reason=reason)
            outcome.setdefault('violations',[]).append(dict(method='parent-post-retention',status=state,reason=reason))
    def retain(trial,destination,outcome,case=None,keep_db=False,remove=True):
        destination.mkdir(parents=True,exist_ok=True);started=time.monotonic()
        if 'worker_job' in outcome:save(destination/'worker-job.json',outcome['worker_job'])
        inventory=dict((outcome.get('worker') or {}).get('files',{}))
        if trial.exists():
            for path in sorted(trial.rglob('*')):
                if not path.is_file():continue
                name=str(path.relative_to(trial))
                if name not in inventory:inventory[name]=dict(bytes=path.stat().st_size,sha256=file_sha256(path))
                keep=(path.parent==trial and (path.name in ('stdout.txt','stderr.txt','result.json','phase.json') or path.suffix=='.pstats' or '-functions.' in path.name))
                if outcome['correctness']=='FAILED' and path.name.startswith('report.'):keep=True
                if keep:
                    shutil.copy2(path,destination/path.name)
                    if file_sha256(path)!=file_sha256(destination/path.name):raise ValueError('retained trial artifact differs')
            if keep_db and (trial/'trial.sqlite3').exists():
                target=root/'migration-source';target.mkdir(exist_ok=False)
                shutil.copy2(trial/'trial.sqlite3',target/'schema2.sqlite3')
                if file_sha256(trial/'trial.sqlite3')!=file_sha256(target/'schema2.sqlite3'):raise ValueError('migration source copy differs')
                save(target/'source.json',dict(variant='A',profile='P2',files=inventory,run_id=outcome['worker']['run_id'],
                    database='schema2.sqlite3',readonly_source=True))
                (target/'schema2.sqlite3').chmod(0o444)
                report['migration_source']='migration-source/schema2.sqlite3'
            if outcome['correctness']=='FAILED' and case is not None:
                shutil.copytree(case,destination/'counterexample-input')
                for item in case.rglob('*'):
                    if item.is_file() and file_sha256(item)!=file_sha256(destination/'counterexample-input'/item.relative_to(case)):raise ValueError('counterexample copy differs')
            save(destination/'artifact-manifest.json',dict(files=inventory,omitted=['successful DB and full reports except owned migration-source'],
                reproduction=outcome.get('reproduction'),correctness=outcome['correctness'],
                completion_before_retention_check=outcome['completion_state']))
            budget_after_parent(outcome)
            if remove:shutil.rmtree(trial)
        outcome['retained_artifact_inventory']=inventory
        outcome['parent_retention_seconds']=time.monotonic()-started
        checkpoint();budget_after_parent(outcome);checkpoint()
    def stop_state(reason):
        return 'NOT_ATTEMPTED_CORRECTNESS' if reason=='known correctness failure' else 'NOT_ATTEMPTED_ERROR'
    def observe_failure(outcome,events,investors):
        nonlocal halt
        if outcome['correctness']=='FAILED':halt='known correctness failure'
        elif outcome['status']=='ERROR':halt='application failure'
        elif outcome['status']!='COMPLETED':blocked.append((events,investors))
    def validate_measured(trial,profile):
        worker=trial.get('worker') or {};variant=trial['variant']
        if trial['status']=='COMPLETED':
            try:
                expected=variants[variant];actual=worker['provenance']
                for key in ('package_version','schema_version','build_fingerprint','package_root'):
                    got=str(Path(actual['package_file']).parent) if key=='package_root' else actual[key]
                    if got!=expected[key]:raise ValueError('wrong variant '+key)
                if actual['dont_write_bytecode'] is not True or actual['pycache_prefix']!=str(pycache_prefix):raise ValueError('worker bytecode policy differs')
                if actual['instrumentation_sha256']!=report['instrumentation_sha256']:raise ValueError('instrumentation changed')
                if (worker['input_sha256'],worker['config_sha256'])!=(profile['input_sha256'],profile['config_sha256']):raise ValueError('input/config differs')
                before=worker['index_before_ingest'];indexes={r[1]:r for r in before['index_list']}
                if before['receipts_count']!=0:raise ValueError('fresh database already has receipts')
                if before['user_version']!=expected['schema_version']:raise ValueError('fresh database physical schema differs')
                if variant=='A' and 'receipts_hash_lookup' in indexes:raise ValueError('baseline gained candidate index')
                if variant=='B':
                    row=indexes.get('receipts_hash_lookup')
                    info=before['indexes'].get('receipts_hash_lookup',{})
                    if not row or row[2]!=0 or row[4]!=0 or [r[2] for r in info.get('info',[])]!=['receipt_hash'] or [(r[2],r[3],r[4]) for r in info.get('xinfo',[]) if r[5]]!=[('receipt_hash',0,'BINARY')]:
                        raise ValueError('candidate index missing or incompatible before ingestion')
                current=signature(worker);previous=signature_by_profile.get(profile['profile'])
                if previous is not None and previous!=current:raise ValueError('financial/receipt/evidence/run/durability parity failed')
                signature_by_profile[profile['profile']]=current
                trial['unattributed_elapsed_seconds']=trial['elapsed_seconds']-sum(worker['timings'].values())
            except (KeyError,ValueError,TypeError) as exc:
                trial.update(status='CORRECTNESS_FAILED',correctness='FAILED',reason=str(exc),parity_failed=True)
    checkpoint()
    with owned_jobs(root) as temporary:
        temp=Path(temporary).resolve();(temp/'STAGE3_3_OWNED').write_text('Only this task-owned tree may be cleaned.\n')
        for variant in ('A','B'):
            trial=temp/('gate-'+variant)
            result=launch(dict(mode='gate',variant=variant,trial=str(trial),correctness=variants[variant]['correctness']),temp,trial,
                limit=time.monotonic()+budgets.total_seconds)
            report['gates'][variant]=result;checkpoint();retain(trial,root/'gates'/variant,result)
            if result['status']!='COMPLETED':
                report.update(status='CORRECTNESS_FAILED' if result['correctness']=='FAILED' else 'ERROR',correctness='FAILED' if result['correctness']=='FAILED' else 'UNKNOWN',completion_state='ERROR',gate_status='FAILED',reason='variant gate failed');checkpoint();return report
        if variants['A']['python']!=variants['B']['python'] or variants['A']['sqlite']!=variants['B']['sqlite']:
            report.update(status='ERROR',completion_state='ERROR',gate_status='FAILED',reason='Python/SQLite versions differ');checkpoint();return report
        report['gate_status']='PASS';report['status']='RUNNING';start=time.monotonic();deadline=start+budgets.total_seconds
        report.update(performance_started_monotonic=start,performance_deadline_monotonic=deadline);checkpoint()
        for name,events,investors in profiles:
            profile=dict(profile=name,events=events,investors=investors,trials=[],statistics={},pairs=[],status='RUNNING')
            report['profiles'].append(profile)
            reason=halt;state=stop_state(halt) if halt else 'NOT_ATTEMPTED_BUDGET'
            if not reason and (time.monotonic()>=deadline or any(events>=e and investors>=i for e,i in blocked)):
                reason='shared deadline or larger related workload budget'
            if not reason:
                folder=temp/name;folder.mkdir();gen=folder/'generation';bundle=gen/'bundle'
                outcome=launch(dict(mode='generate',variant='A',trial=str(gen),bundle=str(bundle),events=events,investors=investors),temp,gen)
                profile['generation']=outcome
                retain(gen,root/name/'generation',outcome,remove=False)
                if outcome['status']!='COMPLETED':
                    observe_failure(outcome,events,investors);reason='generation incomplete';state=stop_state(halt) if halt else 'NOT_ATTEMPTED_BUDGET'
                else:
                    case=bundle/'seed-11/CLEAN';case_by_profile[name]=case
                    profile.update(input_sha256=digest_bytes((case/'input.jsonl').read_bytes()),config_sha256=digest_bytes((case/'config.json').read_bytes()),
                        generation_seconds=outcome['worker']['timings']['generation_seconds'],
                        reproduction=['lab-generate','--seed','11','--events',str(events),'--investors',str(investors),'--scenario','CLEAN'])
                    for path in bundle.rglob('*'):
                        if path.is_file():path.chmod(0o444)
            for pair,order in enumerate(PAIR_ORDERS,1):
                for position,variant in enumerate(order,1):
                    if halt or reason or time.monotonic()>=deadline:
                        why=halt or reason or 'shared deadline exhausted';state=stop_state(halt) if halt else 'NOT_ATTEMPTED_BUDGET'
                        profile['trials'].append(skipped(variant,pair,position,'normal',state,why));checkpoint();continue
                    trial=folder/f'pair-{pair}-{variant}'
                    job=dict(mode='normal',variant=variant,trial=str(trial),case=str(case),seed=11,events=events,investors=investors,generation_seconds=profile['generation_seconds'])
                    result=launch(job,temp,trial);result.update(pair=pair,order_in_pair=position,reproduction=profile['reproduction']);profile['trials'].append(result)
                    validate_measured(result,profile);checkpoint()
                    retain(trial,root/name/trial.name,result,case,keep_db=name=='P2' and variant=='A' and pair==1 and verified(result))
                    observe_failure(result,events,investors)
                    if result['status']!='COMPLETED':reason='prior worker did not complete'
                    checkpoint()
            profile['statistics']={v:normal_statistics(profile['trials'],v) for v in ('A','B')}
            profile['pairs']=paired_results(profile['trials']);profile['completion_state']=completion({t['completion_state'] for t in profile['trials']})
            profile['correctness']='FAILED' if any(t['correctness']=='FAILED' for t in profile['trials']) else 'PASSED' if all(verified(t) for t in profile['trials']) else 'UNKNOWN'
            profile['status']='CORRECTNESS_FAILED' if profile['correctness']=='FAILED' else profile['completion_state'];checkpoint()
        p2=next((p for p in report['profiles'] if p['profile']=='P2'),None)
        diagnostic_budget_stop=False
        for variant in ('A','B'):
            reason=halt or ('prior diagnostic exceeded budget' if diagnostic_budget_stop else None) or ('P2 normal comparison incomplete' if p2 is None or p2['status']!='COMPLETED' else None)
            if not reason and time.monotonic()>=deadline:reason='shared deadline exhausted'
            if reason:
                state=stop_state(halt) if halt else 'NOT_ATTEMPTED_BUDGET'
                report['diagnostics'].append(skipped(variant,None,None,'cprofile',state,reason));checkpoint();continue
            case=case_by_profile['P2'];trial=temp/'P2'/('cprofile-'+variant)
            result=launch(dict(mode='cprofile',variant=variant,trial=str(trial),case=str(case),seed=11,events=p2['events'],investors=p2['investors'],generation_seconds=p2['generation_seconds']),temp,trial)
            report['diagnostics'].append(result);validate_measured(result,p2);checkpoint();retain(trial,root/'P2'/trial.name,result,case)
            observe_failure(result,p2['events'],p2['investors'])
            diagnostic_budget_stop=result['completion_state'] in ('TIMED_OUT','RESOURCE_LIMIT','PARTIAL_BUDGET')
            checkpoint()
        report['final_probes']={}
        for variant in ('A','B'):
            if halt or time.monotonic()>=deadline:
                report['final_probes'][variant]=dict(status='NOT_ATTEMPTED',reason=halt or 'shared deadline exhausted');continue
            trial=temp/('final-probe-'+variant)
            result=launch(dict(mode='probe',variant=variant,trial=str(trial)),temp,trial)
            report['final_probes'][variant]=result;checkpoint();retain(trial,root/'final-probes'/variant,result)
            if result['correctness']=='FAILED':halt='known correctness failure'
            elif result['status']!='COMPLETED':halt='application failure' if result['status']=='ERROR' else halt
    trials=[t for p in report['profiles'] for t in p['trials']]+report['diagnostics']
    report['correctness']='FAILED' if any(t.get('correctness')=='FAILED' for t in trials+list(report['final_probes'].values())) else 'PASSED' if all(verified(t) for t in trials) else 'UNKNOWN'
    report['completion_state']=completion({t['completion_state'] for t in trials})
    report['source_unchanged']=all(report['final_probes'].get(v,{}).get('status')=='COMPLETED' for v in ('A','B'))
    report['instrumentation_unchanged']=report['instrumentation_sha256']==digest_bytes(worker_script.read_bytes()) and report['controller_sha256']==digest_bytes(controller_script.read_bytes())
    report['bytecode_policy']['cache_path_exists_after']=pycache_prefix.exists()
    if not report['instrumentation_unchanged'] or pycache_prefix.exists():report['correctness']='FAILED'
    if not report['source_unchanged'] and report['completion_state']=='COMPLETED':report['completion_state']='ERROR'
    report['status']='CORRECTNESS_FAILED' if report['correctness']=='FAILED' else report['completion_state'];checkpoint()
    report['final_budget_observation']=dict(elapsed_seconds=time.monotonic()-start,experiment_tree_bytes=directory_bytes(budget_root),sampled=True)
    if time.monotonic()>=deadline or report['final_budget_observation']['experiment_tree_bytes']>budgets.temporary_bytes:
        report['completion_state']='PARTIAL_BUDGET';report['status']='CORRECTNESS_FAILED' if report['correctness']=='FAILED' else 'PARTIAL_BUDGET'
    checkpoint();return report


def supervise_final_retention(retention, *args, **kwargs):
    return retention.retain_runtime(*args, **kwargs)


def run_ab(variants, output, budgets=None, profiles=PROFILES, worker_script=None, cwd=None,
           invocation=None, pycache_prefix=None):
    """Keep live SQLite/phase files local; retain once within the same deadline."""
    budgets=budgets or Budgets()
    if pycache_prefix is not None and Path(pycache_prefix).exists():
        raise ValueError('bytecode cache prefix must not exist')
    destination=fresh(output).resolve()
    owned=Path(tempfile.mkdtemp(prefix='crypto-stage3_3-ab-')).resolve()
    source=owned/'ab';source.mkdir()
    tools_directory=source/'instrumentation';tools_directory.mkdir()
    storage=dict(owned_runtime=str(owned),runtime_artifacts=str(source),retained_destination=str(destination),
        runtime_device=os.stat(owned).st_dev,destination_device=os.stat(destination).st_dev,
        reason='Documents File Provider can dehydrate SQLite, phase and bytecode files; both variants use newly owned system-temporary storage.',
        cleanup_policy='Only the newly owned runtime may be removed, after all destination-byte hashes verify, within the original shared deadline.')
    save(destination/'runtime-location.json',storage)
    snapshot_started=time.monotonic();snapshots={}
    originals=(Path(__file__).resolve(),Path(worker_script or Path(__file__).with_name('ab_worker_stage3_3.py')).resolve(),
        Path(__file__).with_name('ab_retention_stage3_3.py').resolve())
    for original in originals:
        data=original.read_bytes();target=tools_directory/original.name
        target.write_bytes(data);target.chmod(0o444)
        snapshots[original.name]=dict(origin=str(original),runtime=str(target),sha256=digest_bytes(data))
    storage.update(instrumentation=snapshots,instrumentation_snapshot_seconds=time.monotonic()-snapshot_started)
    spec=importlib.util.spec_from_file_location('stage3_3_retention',tools_directory/'ab_retention_stage3_3.py')
    retention=importlib.util.module_from_spec(spec);spec.loader.exec_module(retention)
    (owned/retention.MARKER).write_text(retention.MARKER_TEXT)
    policy_prefix=Path(pycache_prefix or owned/'unused-bytecode-cache').resolve()
    try:
        report=_run_ab_runtime(variants,source,budgets,profiles,tools_directory/'ab_worker_stage3_3.py',cwd,
            invocation,policy_prefix,controller_script=tools_directory/'run_ab_stage3_3.py',storage=storage,prepared=True)
    except Exception as exc:
        report=load(source/'ab.json') if (source/'ab.json').exists() else dict(profiles=[],diagnostics=[],correctness='UNKNOWN')
        trials=[t for p in report.get('profiles',[]) for t in p.get('trials',[])]+report.get('diagnostics',[])+list(report.get('gates',{}).values())+list(report.get('final_probes',{}).values())
        known=report.get('correctness')=='FAILED' or any(t.get('correctness')=='FAILED' or correctness_of(t.get('worker'))=='FAILED' for t in trials)
        report.update(status='CORRECTNESS_FAILED' if known else 'ERROR',correctness='FAILED' if known else 'UNKNOWN',
            completion_state='ERROR',error=repr(exc),storage=storage)
        save(source/'ab.json',report);(source/'ab.md').write_text(markdown(report))
    started=report.get('performance_started_monotonic')
    deadline=report.get('performance_deadline_monotonic')
    # A rejected gate never starts a performance experiment. Its evidence still
    # has a bounded copy; this is recorded separately, not a restarted deadline.
    if deadline is None:
        deadline=time.monotonic()+budgets.phase_seconds
        report['retention_deadline_basis']='gate rejected before performance start; separate bounded evidence copy'
    else:
        report['retention_deadline_basis']='original performance deadline without reset'
    report['experiment_elapsed_before_retention_seconds']=report.get('elapsed_seconds')
    retained=supervise_final_retention(retention,tools_directory/'ab_retention_stage3_3.py',sys.executable,
        runtime_flags(policy_prefix),source,destination,owned,asdict(budgets),deadline,current_rss)
    report['retention']=retained
    report['storage']=storage
    observed_worker=retained.get('worker') or {}
    expected_helper=snapshots['ab_retention_stage3_3.py']['sha256']
    if observed_worker.get('script_sha256') not in (None,expected_helper):
        report['correctness']='FAILED';retained['reason']='retention instrumentation fingerprint differs'
        retained['status']=retained['completion_state']='ERROR'
    if retained['completion_state']!='COMPLETED':
        report['completion_state']='PARTIAL_BUDGET' if retained['completion_state'] in ('TIMED_OUT','RESOURCE_LIMIT') else 'ERROR'
    report['status']='CORRECTNESS_FAILED' if report['correctness']=='FAILED' else report['completion_state']
    job=owned/'finalization-input.json'
    save(job,dict(report=report,markdown=markdown(report),destination=str(destination),owned_runtime=str(owned),
        deadline=deadline,performance_started=started,cleanup_requested=retained['completion_state']=='COMPLETED' and retained['verified']))
    finalized=retention.retain_runtime(tools_directory/'ab_retention_stage3_3.py',sys.executable,
        runtime_flags(policy_prefix),source,destination,owned,asdict(budgets),deadline,current_rss,finalize_job=job)
    report['finalization']=finalized
    report['runtime_preserved']=owned.exists()
    if finalized['completion_state']!='COMPLETED':
        report['completion_state']='PARTIAL_BUDGET' if finalized['completion_state'] in ('TIMED_OUT','RESOURCE_LIMIT') else 'ERROR'
    final_worker=finalized.get('worker') or {}
    if final_worker.get('script_sha256') not in (None,expected_helper):
        report['correctness']='FAILED';report['completion_state']='ERROR'
    report['elapsed_seconds']=0 if started is None else time.monotonic()-started
    report['shared_deadline_met']=started is None or time.monotonic()<deadline
    if not report['shared_deadline_met']:report['completion_state']='PARTIAL_BUDGET'
    report['status']='CORRECTNESS_FAILED' if report['correctness']=='FAILED' else report['completion_state']
    # No unsupervised destination writes after the deadline-observed finalizer.
    return report


def terminal_details(outcome):
    detail=dict(outcome)
    if isinstance(detail.get('worker'),dict):
        detail['worker']=dict(detail['worker'])
        manifest=detail['worker'].pop('files',None)
        if manifest is not None:detail['worker']['manifest_entries_omitted_from_terminal']=len(manifest)
    return detail


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for label in ('baseline','candidate'):
        parser.add_argument('--'+label+'-python',required=True);parser.add_argument('--'+label+'-correctness',required=True)
    parser.add_argument('--output',required=True);parser.add_argument('--pycache-prefix',required=True);args=parser.parse_args()
    pycache_prefix=Path(args.pycache_prefix).resolve()
    if pycache_prefix.exists():raise ValueError('bytecode cache prefix must not exist')
    invocation=dict(command=[sys.executable,*getattr(sys,'orig_argv',[sys.executable])[1:]],cwd=str(Path.cwd()),isolated=bool(sys.flags.isolated),dont_write_bytecode=sys.dont_write_bytecode,pycache_prefix=sys.pycache_prefix)
    with tempfile.TemporaryDirectory(prefix='ab-external-cwd-') as tmp:
        cwd=Path(tmp).resolve()
        variants={v:inspect_variant(getattr(args,label+'_python'),getattr(args,label+'_correctness'),cwd,pycache_prefix) for v,label in [('A','baseline'),('B','candidate')]}
        if [(variants[v]['package_version'],variants[v]['schema_version']) for v in ('A','B')]!=[('0.3.2',2),('0.3.3',3)]:raise ValueError('expected distinct 0.3.2/schema2 and 0.3.3/schema3 variants')
        if variants['A']['package_root']==variants['B']['package_root']:raise ValueError('separate import roots required')
        invocation['worker_cwd']=str(cwd)
        result=run_ab(variants,args.output,cwd=cwd,invocation=invocation,pycache_prefix=pycache_prefix)
    print(json.dumps(dict(version='stage3.3-terminal-v1',status=result['status'],correctness=result['correctness'],completion_state=result['completion_state'],elapsed_seconds=result['elapsed_seconds'],shared_deadline_met=result['shared_deadline_met'],retention_status=result['retention']['status'],finalization_status=result['finalization']['status'],runtime_preserved=result['runtime_preserved'],owned_runtime=result['storage']['owned_runtime'],receipt_file='finalization.json',retention_details=terminal_details(result['retention']),finalization_details=terminal_details(result['finalization'])),sort_keys=True))
    return 0 if result['status']=='COMPLETED' else 3 if result['correctness']=='FAILED' else 4 if result['status']=='PARTIAL_BUDGET' else 2

if __name__=='__main__':raise SystemExit(main())
