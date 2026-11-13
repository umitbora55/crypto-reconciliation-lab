"""Finite, preconditioned faults and explicit scenario tables. No engine imports."""
import copy
from datetime import datetime,timedelta
from . import FAULT_PLAN_VERSION
from .common import receipt_id
from .oracle import balances,decimal_text,expectations,financial_text,units
from .world import base,envelope,iso,report_rows,wire,config
from .evidence_contract import minimum_inventory

SCENARIOS=('CLEAN','LATE_EVENT','LATE_MANIFEST','EXACT_RETRY','IDENTITY_CONFLICT','CUSTODY_SHORTFALL',
           'INVESTOR_DISTRIBUTION_ERROR','STALE_AND_REVISED_REPORTS','VOID_DEPOSIT','REPLACE_DEPOSIT',
           'VOID_WITHDRAWAL','REPLACE_WITHDRAWAL','VOID_TRANSFER','REPLACE_TRANSFER','CORRECTION_MEMBER_LATE',
           'CORRECTION_BEFORE_TARGET','F1','F2_STREAM','F2_STREAM_TIME','F3_LIST','F3_OBJECT',
           'COMBINED_LATE_EVENT_AND_CUSTODY_DIFFERENCE','OBSERVABILITY_LIMIT')


def correction_record(world,event,mode='REPLACE',number=1,batch='BATCH1'):
    record={**base('correction',event['asset']),'batch_id':batch,'correction_id':f'C{number}',
            'target':dict(kind='event',source='P1',platform='P1',business_day=event['at'][:10],ref=event['ref']),
            'target_occurred_at':event['at'],'mode':mode,'source_ref':f'SOURCE{number}','reason':'Synthetic reporting amendment'}
    if mode=='REPLACE':record['replacement_amount']=decimal_text(event['units']+7,world['assets'][event['asset']])
    return record


def correction_manifest(world,count=1,batch='BATCH1'):
    return {**base('correction_manifest','ASSET_A'),'batch_id':batch,'coverage_from':world['opening_at'],
            'coverage_to':world['cuts'][-1],'expected_count':count}


def build_case(world,name):
    if name not in SCENARIOS:raise ValueError('unknown scenario')
    rows=copy.deepcopy(wire(world));cut=world['cuts'][-1];k1,k2,k3,k4=world['knowledge'];a='ASSET_A';q=7
    full=balances(world,cut);phases=[];corrections=[]
    def event(kind):
        matches=[e for e in world['events'] if e['asset']==a and e['kind']==kind]
        if not matches:raise ValueError('fault precondition: required event kind absent')
        return matches[0]
    def event_row(e):return next(r for r in rows if r['record'].get('ref')==e['ref'])
    def report_row(stream,scope=None):
        matches=[r for r in rows if r['record']['kind']=='report' and r['record']['asset']==a and r['record']['stream']==stream and r['record']['balance_at']==cut and (scope is None or r['record']['scope']==scope)]
        if not matches:raise ValueError('fault precondition: report absent')
        return matches[0]
    def revisions(ledger,time,streams=None):
        new=[r for r in report_rows(world,cut,time,ledger,2,streams) if r['record']['asset']==a]
        rows.extend(new);return new
    def phase(label,time,available=None,reported=None,states=None,reasons=None,required=(),at=None,applied=()):
        at=at or cut
        available=balances(world,at) if available is None else available
        reported=balances(world,at) if reported is None else reported
        states=states or {}
        text=financial_text(world,available)
        for asset in text:text[asset]['data_state']=states.get(asset,'COMPLETE')
        phases.append(dict(label=label,balance_at=at,knowledge_at=time,
                           available_ledger=text,findings=expectations(world,at,time,available,reported,states,reasons),
                           required_receipts=[receipt_id(r) for r in required],
                           applied_corrections=len(applied),
                           economic_truth=financial_text(world,balances(world,at,corrections))))
    if name=='CLEAN':
        phase('earlier_economic_cut',k1,at=world['cuts'][0]);phase('final',k1)
    elif name in ('LATE_EVENT','COMBINED_LATE_EVENT_AND_CUSTODY_DIFFERENCE'):
        e=event('withdrawal');delayed=event_row(e);delayed['received_at']=k2
        reported=copy.deepcopy(full)
        if name.startswith('COMBINED'):
            r=report_row('external_custody');reported[a]['custody']['external']-=q
            assert reported[a]['custody']['external']>=0
            r['record']['amount']=decimal_text(reported[a]['custody']['external'],world['assets'][a])
        phase('K1_missing_event',k1,balances(world,cut,exclude=[e['ref']]),reported,{a:'INCOMPLETE'},{a:['MANIFEST_COUNT']})
        phase('K2_event_arrived',k2,reported=reported,required=[delayed])
        if name.startswith('COMBINED'):
            new=revisions(full,k3,['external_custody']);phase('K3_custody_revised',k3,required=new)
    elif name=='LATE_MANIFEST':
        m=next(r for r in rows if r['record']['kind']=='manifest' and r['record']['stream']=='event' and r['record']['asset']==a and r['record']['coverage_to']==cut)
        m['received_at']=k2
        phase('K1_manifest_absent',k1,states={a:'INCOMPLETE'},reasons={a:['MANIFEST_ABSENT']})
        phase('K2_manifest_arrived',k2,required=[m])
    elif name=='EXACT_RETRY':
        extra=copy.deepcopy(event_row(event('deposit')));extra['received_at']=k2;rows.append(extra)
        phase('K1_original',k1);phase('K2_retry',k2,required=[extra])
    elif name=='IDENTITY_CONFLICT':
        e=event('deposit');extra=copy.deepcopy(event_row(e));extra['record']['amount']=decimal_text(e['units']+1,world['assets'][a]);extra['received_at']=k1;rows.append(extra)
        phase('conflict',k1,balances(world,cut,exclude=[e['ref']]),states={a:'CONFLICT'},reasons={a:['EVENT_ID_CONFLICT']},required=[extra,event_row(e)])
    elif name=='CUSTODY_SHORTFALL':
        r=report_row('external_custody');reported=copy.deepcopy(full);reported[a]['custody']['external']-=q
        if reported[a]['custody']['external']<0:raise ValueError('fault precondition: external custody too small')
        r['record']['amount']=decimal_text(reported[a]['custody']['external'],world['assets'][a])
        phase('shortfall',k1,reported=reported,required=[r])
    elif name=='INVESTOR_DISTRIBUTION_ERROR':
        i,j=world['investors'][:2];reported=copy.deepcopy(full)
        if reported[a]['investors'][j]<q:raise ValueError('fault precondition: second investor too small')
        reported[a]['investors'][i]+=q;reported[a]['investors'][j]-=q
        changed=[]
        for scope in (i,j):
            r=report_row('investor',scope);r['record']['amount']=decimal_text(reported[a]['investors'][scope],world['assets'][a]);changed.append(r)
        phase('distribution',k1,reported=reported,required=changed)
    elif name=='STALE_AND_REVISED_REPORTS':
        if not any(r['record']['kind']=='report' and r['record']['asset']==a and r['record']['stream']=='external_custody' and r['record']['balance_at']<cut for r in rows):
            raise ValueError('stale-report precondition: an older external report is required')
        r=report_row('external_custody');rows.remove(r);unknown=copy.deepcopy(full);unknown[a]['custody']['external']=None
        phase('K1_stale',k1,reported=unknown,states={(a,'B'):'STALE'},reasons={(a,'B'):['REPORT_STALE']})
        wrong=copy.deepcopy(full);wrong[a]['custody']['external']-=q
        r['record']['amount']=decimal_text(wrong[a]['custody']['external'],world['assets'][a]);r['received_at']=k2;rows.append(r)
        phase('K2_version1_wrong',k2,reported=wrong,required=[r])
        new=revisions(full,k3,['external_custody']);phase('K3_version2',k3,required=new)
        retry=copy.deepcopy(r);retry['received_at']=k4;rows.append(retry)
        phase('K4_old_version_retry',k4,required=new)
    elif name.startswith(('VOID_','REPLACE_')):
        mode,kind=name.split('_');e=event(kind.lower())
        c=correction_record(world,e,mode);corrections=[dict(target=e['ref'],mode=mode,units=e['units']+7)]
        corrected=balances(world,cut,corrections)
        phase('K1_original_reports',k1)
        added=[envelope(c,k2),envelope(correction_manifest(world),k2)];rows.extend(added)
        phase('K2_corrected_old_reports',k2,corrected,required=added,applied=corrections)
        new=revisions(corrected,k3,['investor']);investor_only=copy.deepcopy(full);investor_only[a]['investors']=corrected[a]['investors']
        phase('K3_investor_revision',k3,corrected,investor_only,required=new,applied=corrections)
        new=revisions(corrected,k4,['platform_custody','external_custody'])
        phase('K4_custody_revision',k4,corrected,corrected,required=new,applied=corrections)
    elif name in ('CORRECTION_MEMBER_LATE','CORRECTION_BEFORE_TARGET'):
        e=event('deposit');c=correction_record(world,e);corrections=[dict(target=e['ref'],mode='REPLACE',units=e['units']+7)]
        first=envelope(c,k1);rows.append(first)
        if name=='CORRECTION_MEMBER_LATE':
            other=event('withdrawal');corrections.append(dict(target=other['ref'],mode='REPLACE',units=other['units']+7))
            late=envelope(correction_record(world,other,number=2),k2);rows.append(late)
            retry=copy.deepcopy(first);rows.append(retry)
            m=envelope(correction_manifest(world,2),k1);rows.append(m)
            phase('K1_member_shortfall_despite_retry',k1,states={a:'INCOMPLETE'},reasons={a:['CORRECTION_MANIFEST_COUNT']},required=[first,m])
        else:
            late=event_row(e);late['received_at']=k2;m=envelope(correction_manifest(world),k1);rows.append(m)
            phase('K1_target_pending',k1,balances(world,cut,exclude=[e['ref']]),states={a:'INCOMPLETE'},reasons={a:['TARGET_PENDING']},required=[first,m])
        corrected=balances(world,cut,corrections)
        phase('K2_dependency_arrived',k2,corrected,required=[late],applied=corrections)
        new=revisions(corrected,k3);phase('K3_independent_reports',k3,corrected,corrected,required=new,applied=corrections)
    elif name=='F1':
        e=event('deposit');c=correction_record(world,e);end=datetime.fromisoformat(cut.replace('Z','+00:00'))
        asserted=iso(end+timedelta(seconds=60))
        if asserted[:10]!=e['at'][:10]:raise ValueError('F1 precondition: asserted time must share the target business day')
        c['target_occurred_at']=asserted;m=correction_manifest(world);m.update(coverage_from=cut,coverage_to=iso(end+timedelta(seconds=120)))
        added=[envelope(c,k1),envelope(m,k1)];rows.extend(added)
        phase('known_target_false_future',k1,states={a:'CONFLICT'},reasons={a:['TARGET_TIME_MISMATCH']},required=added)
    elif name.startswith(('F2_','F3_')):
        r=copy.deepcopy(event_row(event('deposit')));r['received_at']=k1
        if name.startswith('F2_'):
            r['record'].update(amount='3',stream='external_custody')
            if name=='F2_STREAM_TIME':r['record']['balance_at']='2026-11-09T00:00:00Z'
            states={a:'INCOMPLETE'}
        else:
            r['record']['asset']=[] if name=='F3_LIST' else {};states={asset:'INCOMPLETE' for asset in world['assets']}
        rows.append(r);phase('quarantined',k1,states=states,reasons={asset:['QUARANTINED_INPUT'] for asset in states},required=[r])
    elif name=='OBSERVABILITY_LIMIT':
        r=event_row(event('deposit'));r['record']['ref']='SUBSTITUTED_REFERENCE'
        if sum(x['record'].get('ref')=='SUBSTITUTED_REFERENCE' for x in rows)!=1:raise ValueError('replacement reference must be unique')
        phase('same_count_same_effect',k1,required=[r])
    for p in phases:
        p['configuration']=config(world)
        p['evidence_minimum']=minimum_inventory(rows,p['configuration'],name,p)
    return dict(name=name,seed=world['seed'],fault_plan_version=FAULT_PLAN_VERSION,
                negative_control=name=='OBSERVABILITY_LIMIT',clean=name=='CLEAN',quantity_units=q,
                corrections=corrections,rows=rows,phases=phases,
                observability_note='Count/coverage manifests cannot authenticate same-effect reference substitution; no detection-rate claim.' if name=='OBSERVABILITY_LIMIT' else None)
