"""Wire-only engine boundary, immutable experiment bundles and exact reports."""
import json
import shutil
import tempfile
import traceback
from pathlib import Path
from . import GENERATOR_VERSION,FAULT_PLAN_VERSION
from .common import encoded,digest_bytes,fresh,load,save,build_fingerprint
from .world import generate,config
from .faults import SCENARIOS,build_case
from .scoring import score,COUNTERS
from .contracts import EXPERIMENT_VERSION,ContractError,require,unique_list,validate_manifest,validate_case


def generate_bundle(output,seeds=(11,29,47),events=100,investors=6,scenarios=SCENARIOS):
    seeds=list(seeds);scenarios=list(scenarios)
    unique_list(seeds,'seeds',int);unique_list(scenarios,'scenarios')
    require(set(scenarios)<=set(SCENARIOS),'scenarios','unknown scenario')
    root=fresh(output);manifest={'experiment_contract_version':EXPERIMENT_VERSION,'scenarios':scenarios,'generator_version':GENERATOR_VERSION,'fault_plan_version':FAULT_PLAN_VERSION,
                                'seeds':list(seeds),'events':events,'investors':investors,'cases':[],'files':{}}
    for seed in seeds:
        world=generate(seed,events,investors);folder=root/f'seed-{seed}';folder.mkdir()
        save(folder/'truth.json',world)
        for name in scenarios:
            case=build_case(world,name);path=folder/name;path.mkdir()
            save(path/'config.json',config(world))
            (path/'input.jsonl').write_bytes(b''.join(encoded(r) for r in case.pop('rows')))
            save(path/'expectations.json',case.pop('phases'));save(path/'fault_plan.json',case)
            manifest['cases'].append(str(path.relative_to(root)))
    for p in sorted(root.rglob('*')):
        if p.is_file():manifest['files'][str(p.relative_to(root))]=dict(bytes=p.stat().st_size,sha256=digest_bytes(p.read_bytes()))
    save(root/'bundle.json',manifest)
    return manifest


def _verify_bundle_files(root):
    root=Path(root).resolve();manifest=load(root/'bundle.json');validate_manifest(manifest)
    for name,entry in manifest['files'].items():
        path=(root/name).resolve()
        if not path.is_relative_to(root):raise ValueError('bundle path escapes root')
        data=path.read_bytes()
        if len(data)!=entry['bytes'] or digest_bytes(data)!=entry['sha256']:raise ValueError('bundle content hash mismatch: '+name)
    required={f'seed-{seed}/truth.json' for seed in manifest['seeds']}|{case+'/'+name for case in manifest['cases'] for name in ('config.json','input.jsonl','expectations.json','fault_plan.json')}
    require(isinstance(manifest['files'],dict) and set(manifest['files'])==required,'bundle.json/files','file inventory differs from declared scope')
    for seed in manifest['seeds']:
        world=generate(seed,manifest['events'],manifest['investors'])
        require(load(root/f'seed-{seed}/truth.json')==world,f'seed-{seed}/truth.json','truth identity/config differs from generator')
        for name in manifest['scenarios']:
            path=root/f'seed-{seed}/{name}'
            try:
                rows=[load_line(line) for line in (path/'input.jsonl').read_text().splitlines()]
                validate_case(world,name,load(path/'config.json'),load(path/'fault_plan.json'),load(path/'expectations.json'),rows,str(path.relative_to(root)))
            except ContractError:raise
            except (ValueError,KeyError,TypeError,IndexError,AttributeError) as exc:raise ContractError(str(path.relative_to(root)),'malformed experiment: '+str(exc)) from exc
    return manifest


def verify_bundle_files(root):
    try:return _verify_bundle_files(root)
    except ContractError:raise
    except (ValueError,KeyError,TypeError,AttributeError,IndexError,OSError) as exc:
        raise ContractError(str(root),'malformed bundle: '+str(exc)) from exc


def load_line(line):
    from ..cli import strict_loads
    return strict_loads(line)


def evaluate(config,rows,phases,path):
    """Only config, JSONL receipts and explicit time cuts cross this boundary."""
    from ..store import Store
    from ..engine import reconcile
    s=Store(path,config);results=[];intake={}
    try:
        for row in rows:
            reply=s.ingest(row['record'],row['received_at']);status=reply['status'];intake[status]=intake.get(status,0)+1
        for phase in phases:
            result=reconcile(s,phase['balance_at'],phase['knowledge_at']);results.append(result)
            for old in results:
                if s.read_run(old['run_id'])!=old:raise ValueError('stored history changed')
        counts={table:s.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('records','receipts','runs','findings','evidence')}
    finally:s.close()
    s=Store(path)
    try:
        if any(s.read_run(r['run_id'])!=r for r in results):raise ValueError('restart readback differs')
    finally:s.close()
    return results,dict(intake=intake,counts=counts,history_unchanged=True,restart_equal=True)


def report_markdown(summary):
    lines=['# Stage 3 correctness','','Scenario PASS is agreement with the experiment oracle, not necessarily financial MATCHED.',
           'The observability negative control is separate from fault detection; no aggregate accuracy or detection-rate percentage is claimed.','',
           '| Seed | Scenario | Cut / phase | Expected states | Actual states | Oracle |','|---|---|---|---|---|---|']
    for c in summary['cases']:
        if not c['phases']:
            lines.append(f"| {c['seed']} | {c['scenario']} | engine failure | see expectation files | ERROR | FAIL |")
        for p in c['phases']:
            expected=sorted({r['expected']['data_state']+'/'+r['expected']['reconciliation_state'] for r in p['rows']})
            actual=sorted({str(r['actual']['data_state'])+'/'+str(r['actual']['reconciliation_state']) for r in p['rows']})
            lines.append(f"| {c['seed']} | {c['scenario']} | {p['label']} | {', '.join(expected)} | {', '.join(actual)} | {'PASS' if p['passed'] else 'FAIL'} |")
    lines+=['','## Error counters','', '| Counter | Count | Definition |','|---|---|---|']
    lines += [f'| {k} | {summary["counters"][k]} | {v} |' for k,v in COUNTERS.items()]
    lines+=['','## Exact finding expectations and observations','','Quantities are decimal text or null; no tolerance or null-to-zero equivalence.','']
    for c in summary['cases']:
        for p in c['phases']:
            lines += [f'### Seed {c["seed"]} / {c["scenario"]} / {p["label"]}','','| Asset / comparison / scope | Expected: amount / reported / difference / state | Actual: amount / reported / difference / state | Required / actual codes |','|---|---|---|---|']
            for row in p['rows']:
                def show(x):return ' / '.join(str(x[k]) for k in ('expected','reported','difference','data_state','reconciliation_state','provisional'))
                lines.append('| '+' / '.join(row['key'][:3])+' | '+show(row['expected'])+' | '+show(row['actual'])+' | '+','.join(row['required_codes'])+' / '+','.join(row['actual_codes'])+' |')
    return '\n'.join(lines)+'\n'


def run_bundle(input_path,output,case_filter=None):
    from ..reporting import write_report
    source=Path(input_path).resolve();root=fresh(output)
    try:manifest=verify_bundle_files(source)
    except (ValueError,KeyError,TypeError,OSError) as exc:
        save(root/'contract-error.json',dict(status='ERROR',experiment_contract_version=EXPERIMENT_VERSION,input=str(source),error=str(exc),reproduce=f'python3 -m crypto_reconciliation_lab lab-verify --input {source} --output replay-new'))
        raise ValueError(str(exc)) from exc
    summary=dict(status='RUNNING',experiment_contract_version=EXPERIMENT_VERSION,scope='FULL_CATALOG' if case_filter is None and set(manifest['scenarios'])==set(SCENARIOS) else 'PARTIAL',build_fingerprint=build_fingerprint(),generator_version=manifest['generator_version'],fault_plan_version=manifest['fault_plan_version'],
                 events=manifest['events'],investors=manifest['investors'],seeds=manifest['seeds'],bundle_hash=digest_bytes((source/'bundle.json').read_bytes()),
                 counters={k:0 for k in COUNTERS},cases=[],negative_controls=0,evaluations=0)
    all_results={}
    selected=[c for c in manifest['cases'] if case_filter is None or c==case_filter]
    if not selected:raise ValueError('no matching scenario; no silent PASS')
    for name in selected:
        path=source/name;plan=load(path/'fault_plan.json');phases=load(path/'expectations.json')
        rows=[json.loads(line) for line in (path/'input.jsonl').read_text().splitlines()]
        case_out=root/name;case_out.mkdir(parents=True)
        try:
            with tempfile.TemporaryDirectory(prefix='crypto-stage3-correctness-') as tmp:
                results,audit=evaluate(load(path/'config.json'),rows,phases,Path(tmp)/'trial.sqlite3')
        except Exception as exc:
            # Experiment failure is recorded as ERROR, never converted into a financial verdict.
            results=[];audit=dict(error=repr(exc),traceback=traceback.format_exc())
            summary['counters']['structural_error']+=1
        case_summary=dict(seed=plan['seed'],scenario=plan['name'],negative_control=plan['negative_control'],audit=audit,phases=[])
        if plan['negative_control']:summary['negative_controls']+=1
        for phase,result in zip(phases,results):
            scored=score(result,phase,plan['clean']);scored.update(label=phase['label'],balance_at=phase['balance_at'],knowledge_at=phase['knowledge_at']);case_summary['phases'].append(scored)
            for counter,value in scored['counters'].items():summary['counters'][counter]+=value
            summary['evaluations']+=1
            write_report(case_out/phase['label'],result)
        case_summary['passed']=len(results)==len(phases) and all(p['passed'] for p in case_summary['phases']);summary['cases'].append(case_summary)
        all_results[name]=results
        if not case_summary['passed']:
            fail=root/'counterexamples'/name;fail.mkdir(parents=True)
            shutil.copytree(path,fail/'input'/name)
            truth=source/Path(name).parent/'truth.json';(fail/'input'/Path(name).parent/'truth.json').write_bytes(truth.read_bytes())
            mini={**manifest,'cases':[name],'seeds':[plan['seed']],'scenarios':[plan['name']],'files':{n:v for n,v in manifest['files'].items() if n.startswith(name+'/') or n==str(Path(name).parent/'truth.json')}}
            save(fail/'input/bundle.json',mini);save(fail/'actual.json',results);save(fail/'audit.json',audit)
            (fail/'REPRODUCE.md').write_text('Run from this counterexample directory:\n\n`python3 -m crypto_reconciliation_lab lab-verify --input input --output replay-new`\n')
    summary['status']='ERROR' if any('error' in c['audit'] for c in summary['cases']) else 'PASS' if all(c['passed'] for c in summary['cases']) else 'CORRECTNESS_FAILED'
    save(root/'correctness.json',summary);save(root/'results.json',all_results)
    (root/'correctness.md').write_text(report_markdown(summary))
    return summary
