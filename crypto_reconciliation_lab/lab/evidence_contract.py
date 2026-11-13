"""Wire identity, finite-scenario minimum evidence, and output link integrity.

This does not resolve arbitrary deliveries. Selected trace arithmetic is checked
in integer units; minimum selection remains limited to the generated catalog.
"""
from datetime import datetime,timezone
from collections import Counter
from .oracle import units,decimal_text
from .common import encoded,digest_bytes,receipt_id
from .contracts import require,unique_list,amount,ContractError


def identity(value):return digest_bytes(encoded(value).rstrip(b'\n'))
def canonical_wire(record):
    # Identity-level canonicalization only. No economic acceptance/resolution rules.
    r=dict(record)
    for k in ('occurred_at','balance_at','coverage_from','coverage_to','target_occurred_at'):
        if k in r:
            dt=datetime.fromisoformat(r[k].replace('Z','+00:00'));require(dt.tzinfo is not None,k,'aware wire timestamp required')
            r[k]=dt.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')
    for k in ('amount','replacement_amount'):
        if k in r:
            text=r[k];amount(text,k);require(isinstance(text,str),k,'source quantity cannot be null')
            sign='-' if text.startswith('-') else '';whole,_,fraction=text.lstrip('-').partition('.')
            whole=str(int(whole));fraction=fraction.rstrip('0');r[k]=sign+whole+('.'+fraction if fraction else '')
            if r[k]=='-0':r[k]='0'
    return r

def record_shape(r,cfg,loc):
    common={'kind','source','platform','asset'}
    extras={
        'event':{'business_day','ref','occurred_at','sequence','type','from_investor','to_investor','custody','amount'},
        'opening':{'scope','balance_at','amount'},
        'report':{'stream','scope','balance_at','version','amount'},
        'manifest':{'stream','coverage_from','coverage_to','expected_count'},
        'correction':{'batch_id','correction_id','target','target_occurred_at','mode','source_ref','reason'}|({'replacement_amount'} if r.get('mode')=='REPLACE' else set()),
        'correction_manifest':{'batch_id','coverage_from','coverage_to','expected_count'},
    }
    kind=r.get('kind');require(isinstance(kind,str) and kind in extras and set(r)==common|extras[kind],loc,'source payload fields differ from wire kind')
    for k in ('source','platform','asset','stream','scope','business_day','ref','type','batch_id','correction_id','mode','source_ref','reason'):
        if k in r:require(isinstance(r[k],str) and bool(r[k]),loc+'/'+k,'nonempty text required')
    for k in ('sequence','version','expected_count'):
        if k in r:require(type(r[k]) is int and (1 if k=='version' else 0)<=r[k]<=2**31-1,loc+'/'+k,'bounded count/version integer required')
    for k in ('occurred_at','balance_at','coverage_from','coverage_to','target_occurred_at'):
        if k in r:require(isinstance(r[k],str) and datetime.fromisoformat(r[k].replace('Z','+00:00')).tzinfo is not None,loc+'/'+k,'aware timestamp required')
    require(r['asset'] in cfg['assets'],loc,'unknown source asset')
    require(r['source']==(cfg['custodian'] if r.get('stream')=='external_custody' else cfg['platform']),loc,'unexpected source for wire stream')
    for k in ('amount','replacement_amount'):
        if k in r:
            q=units(r[k],cfg['assets'][r['asset']]);require(q>0 if kind=='event' or k=='replacement_amount' else q>=0,loc+'/'+k,'invalid source quantity')
    if kind=='event':
        require(r['type'] in ('deposit','withdrawal','transfer') and r['custody'] in (None,'platform','external'),loc,'invalid event category/location')
        require(all(r[k] is None or isinstance(r[k],str) and r[k] in cfg['investors'] for k in ('from_investor','to_investor')),loc,'invalid participant field')
    if kind=='correction':
        target=r['target'];require(isinstance(target,dict) and set(target)=={'kind','source','platform','business_day','ref'} and all(isinstance(v,str) for v in target.values()) and target['kind']=='event' and r['mode'] in ('VOID','REPLACE'),loc,'invalid target/mode shape')


def logical_key(r):
    kind=r['kind'];base=[kind,r['source'],r['platform']]
    if kind=='event':parts=base+[r['business_day'],r['ref']]
    elif kind=='manifest':parts=base+[r['stream'],r['asset'],r['coverage_from'],r['coverage_to']]
    elif kind in ('opening','report'):
        parts=base+[r.get('stream',kind),r['asset'],r['scope'],r['balance_at']]
        if kind=='report':parts.append(r['version'])
    elif kind=='correction':parts=base+[r['correction_id']]
    elif kind=='correction_manifest':parts=base+[r['asset'],r['batch_id']]
    else:raise ValueError('unrecognized source record kind')
    return encoded(parts).rstrip(b'\n').decode()

def minimum_inventory(rows,cfg,name,phase):
    """Independent finite fixture selection, never derived from a reconcile result."""
    cut=phase['balance_at'];known=phase['knowledge_at'];valid={};receipts={};bad={}
    for row in rows:
        require(isinstance(row,dict) and set(row)=={'record','received_at'} and isinstance(row['record'],dict) and isinstance(row['received_at'],str),'input.jsonl','invalid catalog envelope')
        if row['received_at']>known:continue
        raw=row['record'];rid=receipt_id(row)
        # These are the explicit F2/F3 fault forms, not a generic quarantine resolver.
        invalid=(raw.get('kind')=='event' and (not isinstance(raw.get('asset'),str) or 'stream' in raw or 'balance_at' in raw))
        if invalid:bad[rid]=row;continue
        record=canonical_wire(raw);eid=identity(record);valid[eid]=record;receipts.setdefault(eid,{})[rid]=row
    selected={};reports={};ledger_refs={};finding_evidence={};applied=[]
    for asset in cfg['assets']:
        openings={eid:r for eid,r in valid.items() if r['kind']=='opening' and r['asset']==asset}
        events={eid:r for eid,r in valid.items() if r['kind']=='event' and r['asset']==asset and cfg['opening_at']<r['occurred_at']<=cut}
        # A catalog identity-conflict phase explicitly excludes both variants from replay.
        key_counts=Counter(logical_key(r) for r in events.values())
        replay=[eid for eid,r in events.items() if key_counts[logical_key(r)]==1]
        replay.sort(key=lambda eid:(events[eid]['occurred_at'],events[eid]['sequence'],events[eid]['source'],events[eid]['business_day'],events[eid]['ref']))
        manifests={eid:r for eid,r in valid.items() if r['kind']=='manifest' and r['asset']==asset and r['coverage_from']==(cfg['opening_at'] if r['stream'] in ('opening','event') else cut) and r['coverage_to']==(cfg['opening_at'] if r['stream']=='opening' else cut)}
        amendments={eid:r for eid,r in valid.items() if r['kind'] in ('correction','correction_manifest') and r['asset']==asset}
        selected.update(openings);selected.update(events);selected.update(manifests);selected.update(amendments)
        ledger_refs[asset]=dict(opening_record_ids=sorted(openings),event_ids=replay)
        base={*openings,*events,*amendments,*[eid for eid,r in manifests.items() if r['stream'] in ('opening','event')]}
        relevant_bad={eid for eid,row in bad.items() if not isinstance(row['record'].get('asset'),str) or row['record']['asset']==asset}
        for stream,scopes in [('investor',cfg['investors']),('platform_custody',['platform']),('external_custody',['external'])]:
            stream_evidence={eid for eid,r in manifests.items() if r['stream']==stream}
            for scope in scopes:
                candidates={eid:r for eid,r in valid.items() if r['kind']=='report' and r['asset']==asset and r['stream']==stream and r['scope']==scope and r['balance_at']<=cut}
                exact={eid:r for eid,r in candidates.items() if r['balance_at']==cut}
                chosen={eid:r for eid,r in exact.items() if r['version']==max(x['version'] for x in exact.values())} if exact else candidates
                selected.update(chosen);stream_evidence.update(chosen)
                reports[(asset,stream,scope)]=sorted(chosen) if exact else []
            if stream=='investor':
                for scope in scopes:finding_evidence[asset+'|A|'+scope]=sorted(base|relevant_bad|stream_evidence)
            else:
                key=asset+'|B|customer_liability';finding_evidence[key]=sorted(set(finding_evidence.get(key,[]))|base|relevant_bad|stream_evidence)
        if phase['applied_corrections']:
            for cid,c in amendments.items():
                if c['kind']!='correction':continue
                targets=[eid for eid,r in events.items() if all(r[k]==c['target'][k] for k in ('source','platform','business_day','ref'))]
                require(len(targets)==1,'fault plan/'+name,'applied correction target is not unique')
                mids=sorted(eid for eid,r in amendments.items() if r['kind']=='correction_manifest' and r['batch_id']==c['batch_id'])
                applied.append(dict(correction_record_id=cid,target_record_id=targets[0],manifest_ids=mids))
    chosen_receipts={rid:row for eid in selected for rid,row in receipts[eid].items()}
    report_refs={}
    for a in cfg['assets']:
        for i in cfg['investors']:report_refs[a+'|A|'+i]=reports[(a,'investor',i)]
        report_refs[a+'|B|customer_liability']=sorted(reports[(a,'platform_custody','platform')]+reports[(a,'external_custody','external')])
    return dict(source_records=selected,receipts=chosen_receipts,quarantine=bad,ledger_refs=ledger_refs,report_refs=report_refs,
                finding_evidence=finding_evidence,applied_links=sorted(applied,key=lambda x:x['correction_record_id']))


def event_effect(event,text,scale):
    """Signed wire effect only; caller has already selected/validated the source."""
    q=units(text,scale);changes={}
    if event['from_investor']:changes[event['from_investor']]=decimal_text(-q,scale)
    if event['to_investor']:changes[event['to_investor']]=decimal_text(q,scale)
    delta=q if event['type']=='deposit' else -q if event['type']=='withdrawal' else 0
    return dict(investor_deltas=changes,custody_location=event['custody'],custody_delta=decimal_text(delta,scale))


def validate_evidence(result,phase):
    """Raise a located evidence error; score converts it to a controlled failure."""
    ev=result.get('evidence');require(isinstance(ev,dict) and bool(ev),'evidence','nonempty mapping required')
    cfg=result['configuration'];types={};records={};groups={}
    require(result.get('rule_version')=='stage2-v2','rule_version','unexpected financial rule version')
    def ids(value,loc):return unique_list(value,loc,nonempty=False)
    def ref(eid,wanted,loc):
        require(isinstance(eid,str) and eid in types,loc,'missing evidence '+str(eid))
        require(types[eid] in wanted,loc,'wrong evidence payload kind '+eid)
        return records.get(eid)
    for eid,p in ev.items():
        loc='evidence/'+str(eid)
        require(isinstance(eid,str) and isinstance(p,dict) and bool(p),loc,'nonempty object payload required')
        if set(p)=={'record','logical_key','receipt_ids'}:
            r=p['record'];require(isinstance(r,dict),loc,'record must be object')
            require(r.get('kind') in ('event','opening','report','manifest','correction','correction_manifest'),loc,'unknown source kind')
            record_shape(r,cfg,loc)
            require(identity(r)==eid and canonical_wire(r)==r and p['logical_key']==logical_key(r),loc,'record identity/content/logical key differs')
            require(all(isinstance(r.get(k),str) for k in ('source','platform','asset')) and r['asset'] in cfg['assets'] and r['platform']==cfg['platform'],loc,'record scope invalid')
            unique_list(p['receipt_ids'],loc+'/receipt_ids');types[eid]=r['kind'];records[eid]=r
        elif set(p)=={'receipt'}:
            raw=p['receipt'];require(isinstance(raw,dict) and set(raw)=={'record','received_at'} and isinstance(raw['record'],dict) and isinstance(raw['received_at'],str),loc,'invalid receipt envelope')
            require(receipt_id(raw)==eid and raw['received_at']<=result['knowledge_at'],loc,'receipt identity/knowledge mismatch');types[eid]='receipt'
        elif set(p)=={'quarantined_receipt'}:
            raw=p['quarantined_receipt'];require(isinstance(raw,dict) and set(raw)=={'id','record','received_at','error'} and isinstance(raw['error'],str) and bool(raw['error']),loc,'invalid quarantine payload')
            require(raw['id']==eid and receipt_id({k:raw[k] for k in ('record','received_at')})==eid,loc,'quarantine identity mismatch')
            require(raw['received_at'] is None or isinstance(raw['received_at'],str) and raw['received_at']<=result['knowledge_at'],loc,'future quarantine receipt');types[eid]='quarantine'
        elif set(p)=={'derived_correction_group'}:
            g=p['derived_correction_group'];require(isinstance(g,dict) and set(g)=={'id','correction_record_id','target_record_id','target_key','occurred_at','mode','original_amount','effective_amount','original_effect','effects','net_effect','manifest_ids','first_known_at'} and g.get('id')==eid,loc,'invalid derived group')
            require(identity({k:v for k,v in g.items() if k!='id'})==eid,loc,'derived group content-ID mismatch');types[eid]='group';groups[eid]=g
        else:raise ContractError(loc,'unknown payload form')
    for eid,r in records.items():
        for rid in ev[eid]['receipt_ids']:
            ref(rid,{'receipt'},eid+'/receipt_ids')
            require(canonical_wire(ev[rid]['receipt']['record'])==r,eid,'receipt belongs to a different source record')
    for gid,g in groups.items():
        loc='group/'+gid
        target=ref(g.get('target_record_id'),{'event'},loc);correction=ref(g.get('correction_record_id'),{'correction'},loc)
        mids=unique_list(g.get('manifest_ids'),loc+'/manifest_ids')
        require(g.get('target_key')==correction['target'] and all(target[k]==correction['target'][k] for k in ('source','platform','business_day','ref')),loc,'target content/key differs')
        require(g.get('mode')==correction['mode'] and g.get('original_amount')==target['amount'] and g.get('effective_amount')==(correction.get('replacement_amount') if correction['mode']=='REPLACE' else '0') and g.get('occurred_at')==target['occurred_at'],loc,'group source amounts/time/mode differ')
        known=min(ev[rid]['receipt']['received_at'] for rid in ev[g['correction_record_id']]['receipt_ids'])
        require(g.get('first_known_at')==known,loc,'group first-known time differs')
        for mid in mids:
            m=ref(mid,{'correction_manifest'},loc)
            require(m['asset']==target['asset']==correction['asset'] and m['batch_id']==correction['batch_id'] and m['coverage_from']<target['occurred_at']<=m['coverage_to'],loc,'group manifest scope differs')
        effects=g.get('effects');require(isinstance(effects,list) and [e.get('role') for e in effects if isinstance(e,dict)]==(['reversal','replacement'] if g['mode']=='REPLACE' else ['reversal']),loc,'group effect roles differ')
        scale=cfg['assets'][target['asset']]
        original=event_effect(target,g['original_amount'],scale);net=event_effect(target,g['effective_amount'],scale)
        reversal=event_effect(target,decimal_text(-units(g['original_amount'],scale),scale),scale)
        wanted=[dict(role='reversal',**reversal)]+([dict(role='replacement',**net)] if g['mode']=='REPLACE' else [])
        require(g.get('original_effect')==original and g.get('net_effect')==net and effects==wanted,loc,'derived effects disagree with linked source quantities')
        for effect in [g.get('original_effect'),g.get('net_effect'),*effects]:
            require(isinstance(effect,dict) and isinstance(effect.get('investor_deltas'),dict) and set(effect['investor_deltas'])<=set(cfg['investors']) and effect.get('custody_location')==target['custody'],loc,'invalid effect links')
            require('custody_delta' in effect,loc,'missing custody effect');amount(effect['custody_delta'],loc)
            for value in effect['investor_deltas'].values():amount(value,loc)
    def issues(items,loc,allowed=None):
        require(isinstance(items,list),loc,'issues must be list')
        for issue in items:
            require(isinstance(issue,dict) and isinstance(issue.get('code'),str) and issue.get('state') in ('INCOMPLETE','STALE','CONFLICT'),loc,'invalid issue')
            for eid in ids(issue.get('evidence_ids',[]),loc):
                ref(eid,set(types.values()),loc)
                if allowed is not None:require(eid in allowed,loc,'issue outside finding evidence')
            for observation in issue.get('observations',[]):ref(observation['event_id'],{'event'},loc+'/observations')
    ledgers=result['ledgers'];require(isinstance(ledgers,dict) and set(ledgers)==set(cfg['assets']),'ledgers','asset roster differs')
    used_groups=set()
    for a,l in ledgers.items():
        require(isinstance(l,dict),'ledger/'+a,'object required')
        for field,kind in [('opening_record_ids','opening'),('event_ids','event')]:
            for eid in ids(l.get(field),a+'/'+field):require(ref(eid,{kind},a+'/'+field)['asset']==a,a,'ledger source asset differs')
        require(l.get('opening_amounts')=={records[eid]['scope']:records[eid]['amount'] for eid in l['opening_record_ids']},a,'opening amounts differ from linked source')
        require(isinstance(l.get('trace'),list),a,'trace missing')
        require([t.get('event_id') for t in l['trace'] if isinstance(t,dict)]==l['event_ids'],a,'trace/event sequence differs')
        local_groups=l.get('correction_groups');require(isinstance(local_groups,list),a,'correction_groups missing')
        local_ids=[]
        for g in local_groups:
            require(isinstance(g,dict),a,'group must be object');gid=g.get('id');ref(gid,{'group'},a);require(g==groups[gid],a,'ledger group differs from evidence');local_ids.append(gid);used_groups.add(gid)
        require(len(local_ids)==len(set(local_ids)),a,'duplicate correction group')
        # No event/correction selection occurs here: replay the already linked rows.
        target_groups={}
        for gid in local_ids:
            target=groups[gid]['target_record_id']
            require(target in l['event_ids'] and records[target]['asset']==a,a+'/correction_groups','applied group target is outside this ledger')
            require(target not in target_groups,a+'/correction_groups','multiple applied groups for one trace target')
            target_groups[target]=gid
        scale=cfg['assets'][a]
        opening=l['opening_amounts']
        require(len(opening)==len(l['opening_record_ids']),a+'/opening_amounts','duplicate selected opening scope')
        balances={i:units(opening[i],scale) if i in opening else None for i in cfg['investors']}
        for index,t in enumerate(l['trace']):
            loc=f'ledger/{a}/trace/{index}'
            require(isinstance(t,dict) and set(t)=={'event_id','occurred_at','sequence','investor_deltas','custody_location','custody_delta','correction_group_id','balances_after'},loc,'trace fields differ')
            require(isinstance(t['balances_after'],dict) and set(t['balances_after'])==set(cfg['investors']) and isinstance(t['investor_deltas'],dict) and set(t['investor_deltas'])<=set(cfg['investors']),loc,'trace roster differs')
            event=ref(t['event_id'],{'event'},loc)
            require(t.get('occurred_at')==event['occurred_at'] and type(t.get('sequence')) is int and t['sequence']==event['sequence'],loc,'trace event time/sequence differs')
            gid=t.get('correction_group_id');wanted_gid=target_groups.get(t['event_id'])
            require(gid==wanted_gid,loc+'/correction_group_id','trace must link exactly its applied target group, or null when unamended')
            expected=groups[gid]['net_effect'] if gid is not None else event_effect(event,event['amount'],scale)
            require(all(t[k]==expected[k] for k in ('investor_deltas','custody_location','custody_delta')),loc,'trace effect differs from linked source/group quantities or custody location')
            for investor,delta in expected['investor_deltas'].items():
                if balances[investor] is not None:balances[investor]+=units(delta,scale)
            wanted_balances={i:None if q is None else decimal_text(q,scale) for i,q in balances.items()}
            require(t['balances_after']==wanted_balances,loc+'/balances_after','trace balances differ from linked opening and preceding verified deltas')
        final_balances={i:None if q is None else decimal_text(q,scale) for i,q in balances.items()}
        require(l.get('investor_balances')==final_balances,a+'/investor_balances','final ledger balances differ from verified trace')
        issues(l.get('issues'),a+'/issues')
        deliveries=l.get('correction_deliveries');require(isinstance(deliveries,list),a,'delivery list missing')
        applied=[]
        for d in deliveries:
            require(isinstance(d,dict) and isinstance(d.get('batch_id'),str) and type(d.get('complete')) is bool and type(d.get('observed_unique_valid_count')) is int and d['observed_unique_valid_count']>=0 and (d.get('expected_count') is None or type(d['expected_count']) is int and d['expected_count']>=0),a,'invalid delivery')
            mids=ids(d.get('manifest_ids'),a+'/delivery/manifests')
            for mid in mids:require(ref(mid,{'correction_manifest'},a)['batch_id']==d['batch_id'],a,'delivery manifest batch differs')
            require(d.get('expected_count')==(records[mids[0]]['expected_count'] if len(mids)==1 else None),a,'delivery expected count differs from manifest')
            cids=ids(d.get('applied_correction_ids'),a+'/delivery/applied')
            for cid in cids:require(ref(cid,{'correction'},a)['batch_id']==d['batch_id'],a,'applied correction batch differs')
            applied+=cids;issues(d.get('issues'),a+'/delivery/issues')
        require(sorted(applied)==sorted(g['correction_record_id'] for g in local_groups),a,'delivery/group applied links differ')
    require(used_groups==set(groups),'groups','orphan derived group evidence')
    for f in result['findings']:
        loc='finding/'+f['asset']+'/'+f['scope'];a=f['asset'];eids=ids(f.get('evidence_ids'),loc)
        require(f.get('rule_version')==result['rule_version'] and f.get('platform')==cfg['platform'],loc,'finding rule/platform differs')
        require(bool(eids),loc,'empty finding evidence')
        for eid in eids:ref(eid,set(types.values()),loc)
        for field,kind in [('event_ids','event'),('report_ids','report'),('correction_ids','correction')]:
            for eid in ids(f.get(field),loc+'/'+field):
                r=ref(eid,{kind},loc);require(eid in eids and r['asset']==a,loc,'finding evidence source scope differs')
                if kind=='report':require(r['balance_at']==f['balance_at'] and (r['stream']=='investor' and r['scope']==f['scope'] if f['comparison']=='A' else r['stream'] in ('platform_custody','external_custody')),loc,'report comparison scope differs')
        require(f['event_ids']==ledgers[a]['event_ids'],loc,'finding and ledger events differ')
        require(sorted(f['correction_ids'])==sorted(g['correction_record_id'] for g in ledgers[a]['correction_groups']),loc,'finding/group correction links differ')
        for g in ledgers[a]['correction_groups']:require(g['id'] in eids,loc,'derived group missing from finding evidence')
        issues(f.get('issues'),loc+'/issues',eids)
    minimum=phase.get('evidence_minimum');require(isinstance(minimum,dict),'expectation/evidence_minimum','independent inventory required')
    for eid,r in minimum['source_records'].items():require(records.get(eid)==r,'minimum/source/'+eid,'missing or changed expected source payload')
    for eid,raw in minimum['receipts'].items():require(ev.get(eid)=={'receipt':raw},'minimum/receipt/'+eid,'missing or changed required receipt')
    for eid,raw in minimum['quarantine'].items():
        p=ev.get(eid,{}).get('quarantined_receipt',{});require(all(p.get(k)==v for k,v in raw.items()) and types.get(eid)=='quarantine','minimum/quarantine/'+eid,'missing quarantine evidence')
    for a,wanted in minimum['ledger_refs'].items():
        for field,value in wanted.items():require(ledgers[a].get(field)==value,'minimum/ledger/'+a+'/'+field,'independent replay source inventory differs')
    for f in result['findings']:
        key=f['asset']+'|'+f['comparison']+'|'+f['scope']
        require(f['report_ids']==minimum['report_refs'][key],'minimum/reports/'+key,'selected source report inventory differs')
        require(set(minimum['finding_evidence'][key])<=set(f['evidence_ids']),'minimum/finding/'+key,'required source evidence link missing')
    links=sorted([{k:g[k] for k in ('correction_record_id','target_record_id','manifest_ids')} for g in groups.values()],key=lambda g:g['correction_record_id'])
    require(links==minimum['applied_links'],'minimum/groups','independent applied correction links differ')

    require(result.get('run_id')==identity({k:v for k,v in result.items() if k!='run_id'}),'run_id','run content-ID mismatch')
