"""Versioned finite experiment scope; independent of submitted phase/result lists."""
import re
from .common import encoded
from .world import generate,config

EXPERIMENT_VERSION='lab-contract-v2'
from . import GENERATOR_VERSION,FAULT_PLAN_VERSION
KEY=('asset','comparison','scope','balance_at','knowledge_at')
FIELDS=('data_state','reconciliation_state','provisional','expected','reported','difference')
# (stable phase identity, economic cut index, knowledge cut index).
CATALOG={
 'CLEAN':(('earlier_economic_cut',0,0),('final',1,0)),
 'LATE_EVENT':(('K1_missing_event',1,0),('K2_event_arrived',1,1)),
 'LATE_MANIFEST':(('K1_manifest_absent',1,0),('K2_manifest_arrived',1,1)),
 'EXACT_RETRY':(('K1_original',1,0),('K2_retry',1,1)),
 'IDENTITY_CONFLICT':(('conflict',1,0),),
 'CUSTODY_SHORTFALL':(('shortfall',1,0),),
 'INVESTOR_DISTRIBUTION_ERROR':(('distribution',1,0),),
 'STALE_AND_REVISED_REPORTS':(('K1_stale',1,0),('K2_version1_wrong',1,1),('K3_version2',1,2),('K4_old_version_retry',1,3)),
 **{name:(('K1_original_reports',1,0),('K2_corrected_old_reports',1,1),('K3_investor_revision',1,2),('K4_custody_revision',1,3))
    for name in ('VOID_DEPOSIT','REPLACE_DEPOSIT','VOID_WITHDRAWAL','REPLACE_WITHDRAWAL','VOID_TRANSFER','REPLACE_TRANSFER')},
 'CORRECTION_MEMBER_LATE':(('K1_member_shortfall_despite_retry',1,0),('K2_dependency_arrived',1,1),('K3_independent_reports',1,2)),
 'CORRECTION_BEFORE_TARGET':(('K1_target_pending',1,0),('K2_dependency_arrived',1,1),('K3_independent_reports',1,2)),
 'F1':(('known_target_false_future',1,0),),
 **{name:(('quarantined',1,0),) for name in ('F2_STREAM','F2_STREAM_TIME','F3_LIST','F3_OBJECT')},
 'COMBINED_LATE_EVENT_AND_CUSTODY_DIFFERENCE':(('K1_missing_event',1,0),('K2_event_arrived',1,1),('K3_custody_revised',1,2)),
 'OBSERVABILITY_LIMIT':(('same_count_same_effect',1,0),),
}

class ContractError(ValueError):
    def __init__(self,location,detail):
        self.location=location;self.detail=detail
        super().__init__(f'LAB_CONTRACT: {location}: {detail}')

def require(condition,location,detail):
    if not condition:raise ContractError(location,detail)

def unique_list(value,location,kind=str,nonempty=True):
    require(isinstance(value,list) and (bool(value) or not nonempty),location,'expected '+('nonempty ' if nonempty else '')+'list')
    require(all(type(v) is kind for v in value),location,'invalid element type')
    require(len(value)==len(set(value)),location,'duplicate identity')
    return value

def amount(value,location):
    require(value is None or isinstance(value,str) and re.fullmatch(r'-?[0-9]+(?:\.[0-9]+)?',value) is not None,location,'expected decimal text or explicit null')

def fields(row,location):
    require(isinstance(row,dict) and set(FIELDS)<=row.keys(),location,'missing financial/state fields')
    require(row['data_state'] in ('COMPLETE','INCOMPLETE','STALE','CONFLICT'),location,'invalid data_state')
    require(row['reconciliation_state'] in ('MATCHED','MISMATCH','NOT_EVALUATED'),location,'invalid reconciliation_state')
    require(type(row['provisional']) is bool,location,'provisional must be bool')
    for k in ('expected','reported','difference'):amount(row[k],location+'/'+k)

def phase_specs(world,name):
    require(name in CATALOG,name,'unknown scenario')
    return [dict(label=label,balance_at=world['cuts'][cut],knowledge_at=world['knowledge'][known]) for label,cut,known in CATALOG[name]]

def finding_keys(cfg,phase):
    return {(a,c,s,phase['balance_at'],phase['knowledge_at']) for a in cfg['assets'] for c,s in [('A',i) for i in cfg['investors']]+[('B','customer_liability')]}

def validate_findings(rows,cfg,phase,location):
    require(isinstance(rows,list),location,'findings must be list')
    keys=[]
    for n,row in enumerate(rows):
        loc=f'{location}/{n}'
        require(isinstance(row,dict) and all(isinstance(row.get(k),str) for k in KEY),loc,'missing/invalid finding key')
        keys.append(tuple(row[k] for k in KEY));fields(row,loc)
        unique_list(row.get('required_codes'),loc+'/required_codes',nonempty=False)
    require(len(keys)==len(set(keys)) and set(keys)==finding_keys(cfg,phase),location,'finding identities or uniqueness differ from configured A/B roster')

def applied_count(name,label):
    if label.startswith('K1_'):return 0
    if name.startswith(('VOID_','REPLACE_')) or name=='CORRECTION_BEFORE_TARGET':return 1
    if name=='CORRECTION_MEMBER_LATE':return 2
    return 0

def validate_case(world,name,cfg,plan,phases,rows,location):
    from .evidence_contract import minimum_inventory
    from . import FAULT_PLAN_VERSION
    require(cfg==config(world),location+'/config.json','configuration differs from seed world/asset/investor roster')
    require(isinstance(plan,dict) and type(plan.get('seed')) is int and plan['seed']==world['seed'] and plan.get('name')==name,location+'/fault_plan.json','case/plan/seed identity conflict')
    require(plan.get('fault_plan_version')==FAULT_PLAN_VERSION,location+'/fault_plan.json','unsupported fault plan version')
    for key,wanted in [('clean',name=='CLEAN'),('negative_control',name=='OBSERVABILITY_LIMIT')]:
        require(type(plan.get(key)) is bool and plan[key]==wanted,location+'/fault_plan.json','incorrect '+key)
    expected=phase_specs(world,name)
    require(isinstance(phases,list) and len(phases)==len(expected),location+'/expectations.json','missing/extra/empty phase scope')
    labels=[p.get('label') if isinstance(p,dict) else None for p in phases]
    require(all(isinstance(x,str) for x in labels) and len(labels)==len(set(labels)) and set(labels)=={p['label'] for p in expected},location+'/expectations.json','phase identity set/uniqueness differs from catalog')
    by_label={p['label']:p for p in expected}
    for phase in phases:
        loc=location+'/expectations.json/'+phase['label']
        require(all(phase.get(k)==v for k,v in by_label[phase['label']].items()),loc,'economic/knowledge cut differs from catalog')
        require(phase.get('configuration')==cfg,loc,'phase configuration differs')
        validate_findings(phase.get('findings'),cfg,phase,loc+'/findings')
        require(type(phase.get('applied_corrections')) is int and phase['applied_corrections']==applied_count(name,phase['label']),loc,'applied correction count differs from scenario')
        unique_list(phase.get('required_receipts'),loc+'/required_receipts',nonempty=False)
        for field in ('available_ledger','economic_truth'):
            ledger=phase.get(field);require(isinstance(ledger,dict) and set(ledger)==set(cfg['assets']),loc+'/'+field,'asset roster differs')
            for a,item in ledger.items():
                require(isinstance(item,dict) and set(item.get('investor_balances',{}))==set(cfg['investors']) and set(item.get('custody_rollforward',{}))=={'platform','external'},loc+'/'+field+'/'+a,'ledger roster differs')
                for value in [item.get('liability'),*item['investor_balances'].values(),*item['custody_rollforward'].values()]:amount(value,loc+'/'+field+'/'+a)
                require('liability' in item,loc+'/'+field+'/'+a,'missing liability')
                if field=='available_ledger':require(item.get('data_state') in ('COMPLETE','INCOMPLETE','STALE','CONFLICT'),loc,'invalid ledger data_state')
        wanted=minimum_inventory(rows,cfg,name,phase)
        require(phase.get('evidence_minimum')==wanted,loc+'/evidence_minimum','independent wire inventory differs')

def validate_manifest(manifest):
    loc='bundle.json'
    require(isinstance(manifest,dict) and manifest.get('experiment_contract_version')==EXPERIMENT_VERSION,loc,'unsupported/missing experiment contract; regenerate old 0.3.0 bundles')
    require(manifest.get('generator_version')==GENERATOR_VERSION and manifest.get('fault_plan_version')==FAULT_PLAN_VERSION,loc,'unsupported generator/fault version')
    seeds=unique_list(manifest.get('seeds'),loc+'/seeds',int)
    names=unique_list(manifest.get('scenarios'),loc+'/scenarios')
    require(set(names)<=CATALOG.keys(),loc,'unknown scenario')
    for k,minimum in [('events',12),('investors',2)]:require(type(manifest.get(k)) is int and manifest[k]>=minimum,loc,'invalid '+k)
    ids=unique_list(manifest.get('cases'),loc+'/cases')
    require(set(ids)=={f'seed-{s}/{n}' for s in seeds for n in names},loc,'case/seed/scenario cross product differs')
    return ids

def counters(value,names,location):
    require(isinstance(value,dict) and set(value)==set(names),location,'missing/extra counter names')
    require(all(type(n) is int and n>=0 for n in value.values()),location,'counters must be nonnegative integers, never bool')

def validate_gate(report,names,fingerprint):
    loc='correctness report'
    require(isinstance(report,dict) and report.get('experiment_contract_version')==EXPERIMENT_VERSION,loc,'unsupported/missing experiment contract version')
    require(report.get('generator_version')==GENERATOR_VERSION and report.get('fault_plan_version')==FAULT_PLAN_VERSION,loc,'unsupported generator/fault version')
    require(report.get('build_fingerprint')==fingerprint,loc,'different source build')
    require(report.get('status')=='PASS' and report.get('scope')=='FULL_CATALOG',loc,'full correctness matrix must PASS')
    require(type(report.get('events')) is int and report['events']==100 and type(report.get('investors')) is int and report['investors']==6,loc,'requires 100 events / 6 investors')
    seeds=unique_list(report.get('seeds'),loc+'/seeds',int);require(len(seeds)>=3,loc,'at least three seeds required')
    counters(report.get('counters'),names,loc+'/counters')
    require(not any(report['counters'].values()),loc,'nonzero correctness counters')
    cases=report.get('cases');require(isinstance(cases,list),loc,'missing case results')
    expected={(s,n) for s in seeds for n in CATALOG};seen=set();totals={k:0 for k in names};evaluations=0
    for case in cases:
        require(isinstance(case,dict) and type(case.get('seed')) is int and isinstance(case.get('scenario'),str),loc,'invalid case identity')
        key=(case['seed'],case['scenario']);where=f'{loc}/seed-{key[0]}/{key[1]}'
        require(key in expected and key not in seen,where,'unexpected/duplicate case');seen.add(key)
        require(case.get('passed') is True and case.get('audit',{}).get('history_unchanged') is True and case.get('audit',{}).get('restart_equal') is True,where,'case/audit not passed')
        require(type(case.get('negative_control')) is bool and case['negative_control']==(key[1]=='OBSERVABILITY_LIMIT'),where,'negative-control identity differs')
        world=generate(key[0],100,6);cfg=config(world);specs={p['label']:p for p in phase_specs(world,key[1])}
        phases=case.get('phases');require(isinstance(phases,list),where,'missing phase results');phase_seen=set()
        for p in phases:
            require(isinstance(p,dict) and isinstance(p.get('label'),str),where,'invalid phase result')
            label=p['label'];here=where+'/'+label
            require(label in specs and label not in phase_seen,here,'unexpected/duplicate phase');phase_seen.add(label)
            require(all(p.get(k)==v for k,v in specs[label].items()),here,'phase cuts differ')
            require(p.get('passed') is True and p.get('errors')==[] and p.get('evidence_verified') is True,here,'phase not passed')
            counters(p.get('counters'),names,here+'/counters')
            for k in totals:totals[k]+=p['counters'][k]
            rows=p.get('rows');require(isinstance(rows,list),here,'missing finding observations');found=[]
            for row in rows:
                require(isinstance(row,dict) and isinstance(row.get('key'),list) and len(row['key'])==5 and all(isinstance(v,str) for v in row['key']),here,'invalid finding observation key')
                found.append(tuple(row['key']))
                fields(row.get('expected'),here+'/expected');fields(row.get('actual'),here+'/actual')
                require(row['expected']==row['actual'],here,'reported phase has financial/state difference')
                unique_list(row.get('required_codes'),here+'/required_codes',nonempty=False)
                require(isinstance(row.get('actual_codes'),list) and all(isinstance(c,str) for c in row['actual_codes']) and set(row['required_codes'])<=set(row['actual_codes']),here,'missing reason codes')
            require(len(found)==len(set(found)) and set(found)==finding_keys(cfg,specs[label]),here,'finding scope differs')
            evaluations+=1
        require(phase_seen==set(specs),where,'missing required phase results')
    require(seen==expected,loc,'missing cases')
    require(type(report.get('evaluations')) is int and report['evaluations']==evaluations==54*len(seeds),loc,'evaluation count differs')
    require(type(report.get('negative_controls')) is int and report['negative_controls']==len(seeds),loc,'negative-control total differs')
    require(totals==report['counters'],loc,'aggregate counters differ from phase totals')
