"""Exact expected/actual comparisons and separately defined error counters."""
from collections import Counter

KEY=('asset','comparison','scope','balance_at','knowledge_at')
FIELDS=('data_state','reconciliation_state','provisional','expected','reported','difference')
COUNTERS={
 'false_definitive':'Expected non-COMPLETE data received MATCHED or MISMATCH.',
 'missed_mismatch':'Expected MISMATCH received MATCHED.',
 'clean_false_mismatch':'A clean scenario received MISMATCH instead of MATCHED.',
 'unnecessary_not_evaluated':'Expected COMPLETE received NOT_EVALUATED.',
 'wrong_amount':'A finding amount or an asset ledger quantity differs, including null versus zero.',
 'healthy_scope_block':'An expected COMPLETE scope received non-COMPLETE data.',
 'missing_evidence':'A required receipt or referenced evidence payload/link is missing.',
 'wrong_state':'Any exact state/provisional field differs.',
 'missing_reason':'A required blocking code is missing.',
 'structural_error':'Missing/duplicate/unexpected findings or wrong correction count/direction.'}


def _score(result,phase,clean=False):
    counters={k:0 for k in COUNTERS};errors=[];rows=[]
    def fail(category,detail):counters[category]+=1;errors.append(dict(category=category,detail=detail))
    expected={tuple(r[k] for k in KEY):r for r in phase['findings']}
    actual={tuple(r.get(k) for k in KEY):r for r in result.get('findings',[])}
    if len(actual)!=len(result.get('findings',[])) or set(actual)!=set(expected):fail('structural_error','finding key set or uniqueness differs')
    evidence=result.get('evidence',{})
    for key,e in expected.items():
        r=actual.get(key,{})
        rows.append(dict(key=list(key),expected={k:e[k] for k in FIELDS},actual={k:r.get(k) for k in FIELDS},required_codes=e['required_codes'],actual_codes=[i['code'] for i in r.get('issues',[])]))
        if e['data_state']!='COMPLETE' and r.get('reconciliation_state') in ('MATCHED','MISMATCH'):fail('false_definitive',list(key))
        if e['reconciliation_state']=='MISMATCH' and r.get('reconciliation_state')=='MATCHED':fail('missed_mismatch',list(key))
        if clean and e['reconciliation_state']=='MATCHED' and r.get('reconciliation_state')=='MISMATCH':fail('clean_false_mismatch',list(key))
        if e['data_state']=='COMPLETE' and r.get('reconciliation_state')=='NOT_EVALUATED':fail('unnecessary_not_evaluated',list(key))
        if e['data_state']=='COMPLETE' and r.get('data_state')!='COMPLETE':fail('healthy_scope_block',list(key))
        for field in FIELDS:
            if field not in r or r[field]!=e[field]:fail('wrong_amount' if field in ('expected','reported','difference') else 'wrong_state',{'key':list(key),'field':field,'expected':e[field],'actual':r.get(field)})
        codes={i['code'] for i in r.get('issues',[])}
        for code in e['required_codes']:
            if code not in codes:fail('missing_reason',{'key':list(key),'code':code})
        if r.get('difference_direction')!='expected_minus_reported':fail('structural_error','wrong difference direction')
        refs=set(r.get('evidence_ids',[]))
        if not refs or not refs<=evidence.keys() or not set(r.get('event_ids',[])+r.get('report_ids',[])+r.get('correction_ids',[]))<=refs:
            fail('missing_evidence',list(key))
        for issue in r.get('issues',[]):
            if not set(issue.get('evidence_ids',[]))<=refs:fail('missing_evidence',{'key':list(key),'issue':issue['code']})
    for rid in phase['required_receipts']:
        if rid not in evidence:fail('missing_evidence',{'required_receipt':rid})
    for eid,payload in evidence.items():
        if 'record' in payload and (not payload.get('receipt_ids') or not set(payload['receipt_ids'])<=evidence.keys()):fail('missing_evidence',eid)
        if 'derived_correction_group' in payload:
            g=payload['derived_correction_group']
            if not {g['target_record_id'],g['correction_record_id'],*g['manifest_ids']}<=evidence.keys():fail('missing_evidence',eid)
    for asset,e in phase['available_ledger'].items():
        r=result.get('ledgers',{}).get(asset,{})
        for field in ('investor_balances','liability','custody_rollforward','data_state'):
            if r.get(field)!=e[field]:fail('wrong_state' if field=='data_state' else 'wrong_amount',{'asset':asset,'field':field,'expected':e[field],'actual':r.get(field)})
    count=sum(len(l.get('correction_groups',[])) for l in result.get('ledgers',{}).values())
    if count!=phase['applied_corrections']:fail('structural_error',{'expected_groups':phase['applied_corrections'],'actual_groups':count})
    return dict(passed=not errors,counters=counters,errors=errors,rows=rows)


def score(result,phase,clean=False):
    """Malformed results fail explicitly; financial and evidence errors stay distinct."""
    from .contracts import require,fields,validate_findings
    from .evidence_contract import validate_evidence
    checked=dict(passed=False,counters={k:0 for k in COUNTERS},errors=[],rows=[])
    def add(category,error):
        checked['counters'][category]+=1
        checked['errors'].append(dict(category=category,detail=str(error)))
    try:
        require(isinstance(result,dict) and isinstance(phase,dict),'score','result/expectation must be objects')
        cfg=phase['configuration']
        require(result.get('configuration')==cfg,'configuration','result differs from independent experiment config')
        require(result.get('balance_at')==phase['balance_at'] and result.get('knowledge_at')==phase['knowledge_at'],'cuts','result cuts differ')
        validate_findings(phase['findings'],cfg,phase,'expectation/findings')
        require(isinstance(result.get('findings'),list),'findings','result findings must be list')
        for f in result['findings']:
            require(isinstance(f,dict) and all(isinstance(f.get(k),str) for k in KEY),'findings','invalid finding key')
            fields(f,'findings')
            require(isinstance(f.get('issues'),list) and all(isinstance(i,dict) and isinstance(i.get('code'),str) for i in f['issues']),'findings/issues','invalid issue list')
        checked=_score(result,phase,clean)
    except (ValueError,TypeError,KeyError,IndexError,AttributeError) as exc:
        add('structural_error',exc)
    try:
        validate_evidence(result,phase)
        checked['evidence_verified']=True
    except (ValueError,TypeError,KeyError,IndexError,AttributeError) as exc:
        add('missing_evidence',exc);checked['evidence_verified']=False
    checked['passed']=not checked['errors']
    return checked
