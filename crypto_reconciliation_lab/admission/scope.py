"""Pinned semantic acceptance of the finite recovery experiment, not authenticity.

No engine, normalizer, admission runtime or candidate-generated scope is used.
"""
from __future__ import annotations
import hashlib
from collections import Counter
import json
from pathlib import Path
import re

CONTRACT_PATH = 'contracts/admission-recovery-scope-v2.json'
CONTRACT_BYTES = 235471
CONTRACT_SHA256 = '4b0f84fa393a7dceaacb4c62afa35a8a9aa2cda8a70c324b2d77a56711a18d71'
PACKAGE_PATH = 'crypto_reconciliation_lab/admission/recovery_scope_v2.json'
HEX = re.compile(r'^[0-9a-f]{64}$')
CORE_TABLES = ('streams','effects','attempts','receipts','records')
RUN_TABLES = ('runs','findings','evidence','correction_groups','correction_effects')


def require(condition, message):
    if not condition:
        raise ValueError('ADMISSION_SCOPE: ' + message)


def same(a, b):
    """JSON equality without Python's True == 1 / 1 == 1.0 loopholes."""
    return json.dumps(a, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':')) == json.dumps(b, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':'))


def digest(value):
    return type(value) is str and HEX.fullmatch(value) is not None


def positive(value):
    return type(value) is int and value > 0


def identity():
    return {'path': CONTRACT_PATH, 'bytes': CONTRACT_BYTES, 'sha256': CONTRACT_SHA256}


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'duplicate scope JSON key ' + ascii(key))
        value[key] = item
    return value


def load_scope(root=None):
    if root is not None:
        path = Path(root) / CONTRACT_PATH
        require(path.is_file() and not path.is_symlink(), 'fixed recovery scope is absent or unsafe')
        declared = path.read_bytes()
        require(len(declared) == CONTRACT_BYTES and hashlib.sha256(declared).hexdigest() == CONTRACT_SHA256,
                'fixed recovery scope identity differs')
    package = Path(__file__).with_name('recovery_scope_v2.json') if root is None else Path(root) / PACKAGE_PATH
    require(package.is_file() and not package.is_symlink(), 'packaged fixed recovery scope is absent or unsafe')
    data = package.read_bytes()
    require(len(data) == CONTRACT_BYTES and hashlib.sha256(data).hexdigest() == CONTRACT_SHA256, 'fixed recovery scope identity differs')
    if root is not None:
        require(declared == data, 'fixed recovery scope identity differs between source and package')
    value = json.loads(data, object_pairs_hook=unique_object)
    require(value.get('format') == 'admission-recovery-scope-v2' and value.get('release') == '0.7.1', 'recovery scope format/release differs')
    return value


def validate_plan(identifier, plan, scope=None):
    scope = load_scope() if scope is None else scope
    require(identifier in scope['scenarios'], 'unknown scenario')
    wanted = scope['scenarios'][identifier]['plan']
    require(type(plan) is dict and same(plan, wanted), 'scenario plan differs from independent required work: ' + identifier)


def validate_schedule(schedule, scope):
    require(type(schedule) is dict and schedule.get('format') == scope['schedule_format'], 'schedule format differs')
    rows = schedule.get('scenarios')
    require(type(rows) is list and all(type(r) is dict for r in rows) and [r.get('id') for r in rows] == scope['scenario_ids'], 'schedule roster differs')
    for row in rows:
        validate_plan(row['id'], row, scope)
    inputs = schedule.get('inputs')
    require(type(inputs) is dict and set(inputs) == set(scope['inputs']), 'schedule input roster differs')
    for name, expected in scope['inputs'].items():
        require(same(inputs[name], {'path':'inputs/'+name+'.jsonl', 'bytes':expected['input_bytes'], 'sha256':expected['input_sha256'], 'planned_lines':expected['planned_lines']}), 'schedule input identity differs: '+name)
    require(type(schedule.get('seed')) is int and 0 <= schedule['seed'] <= 2**31 - 1, 'schedule seed missing')
    require(type(schedule.get('busy_timeout_ms')) is int and schedule['busy_timeout_ms'] == 100 and type(schedule.get('retry_budget')) is int and schedule['retry_budget'] == 2 and schedule.get('timeout_seconds') == 15, 'schedule bounded execution settings differ')
    return True


def _settings(value, label):
    require(type(value) is dict and value.get('journal_mode') == 'delete' and type(value.get('synchronous')) is int and value['synchronous'] == 2, label + ' connection settings differ')


def _proof(value):
    return (type(value) is dict and value.get('representation') == 'canonical JSON check value'
            and positive(value.get('bytes')) and digest(value.get('sha256')))


def _checks(checks, required, label, allow_fail=False):
    require(type(checks) is list and all(type(c) is dict for c in checks), label + ' readback checks missing')
    names = [c.get('name') for c in checks]
    require(all(type(n) is str for n in names) and len(names) == len(set(names)), label + ' duplicate/invalid control identities')
    require(set(required) <= set(names), label + ' required control missing: ' + ','.join(sorted(set(required)-set(names))))
    require(all(n in required or n.startswith('extra:') for n in names), label + ' unknown substituted control')
    result = {}
    for control in checks:
        name=control['name']; spec=required.get(name)
        require(set(control) == {'name','actual','expected','passed'}, label + ' malformed control '+name)
        require(type(control['passed']) is bool and control['passed'] is same(control['actual'], control['expected']), label+' contradictory expected/actual/passed: '+name)
        require(allow_fail or control['passed'], label + ' failed readback control: '+name)
        if spec and 'literal' in spec:
            require(same(control['expected'], spec['literal']), label+' independent expected value differs: '+name)
        elif spec:
            value=control['expected']; kind=spec['type']
            valid = (_proof(value) or (type(value) in (dict,list) and bool(value))) if kind=='proof' else positive(value) if kind=='positive_int' else type(value) is list and bool(value) if kind=='nonempty_list' else type(value) is dict and all(k in value for k in ('status','receipt_id','record_id','error','reason_code')) if kind=='core_result' else False
            require(valid, label+' invalid dynamic proof: '+name)
        result[name]=control
    return result


def _processes(row, scope):
    name=row['id'];processes=row.get('processes')
    require(type(processes) is list and all(type(p) is dict for p in processes), 'invalid process evidence')
    if name in scope['writer_scenarios']:
        require(len(processes)==2 and len({p.get('pid') for p in processes})==2 and all(positive(p.get('pid')) and p.get('joined') is True and type(p.get('exit_code')) is int and p['exit_code']==0 for p in processes), 'two completed independent writer processes missing')
    if name in scope['crash_barriers']:
        barrier=scope['crash_barriers'][name]
        require(len(processes)==1 and processes[0].get('barrier')==barrier and processes[0].get('barrier_reached') is True and type(processes[0].get('exit_code')) is int and processes[0]['exit_code']==-9 and processes[0].get('sender_result')=='UNKNOWN', 'required observed SIGKILL barrier missing: '+name)
    elif name not in scope['writer_scenarios']:
        require(len(processes)==(2 if name=='busy_retry' else 1 if name=='ack_restart' else 0), 'process inventory differs: '+name)
    for p in processes:
        require(positive(p.get('pid')) and p.get('joined') is True and type(p.get('exit_code')) is int, 'process PID/join/termination evidence missing')
        ready=p.get('ready');messages=p.get('messages')
        require(type(ready) is dict and ready.get('type')=='READY' and ready.get('pid')==p['pid'] and all(type(ready.get(k)) is str and ready[k] for k in ('interpreter','import_origin','sqlite')), 'process readiness identity differs')
        require(type(messages) is list and messages and same(messages[0],ready), 'observed process messages missing')
        require(all(type(m) is dict and m.get('pid')==p['pid'] for m in messages), 'observed process PID relationship differs')
        _settings(ready.get('writer_connection'),'actual child writer')
        if p.get('barrier') is not None:
            observed=[m for m in messages if m.get('type')=='BARRIER']
            require(len(observed)==1 and observed[0].get('point')==p['barrier'] and p.get('barrier_reached') is True,'observed SIGKILL/barrier message differs')
            _settings(observed[0].get('writer_connection'),'actual barrier writer')
        else:
            require(not any(m.get('type')=='BARRIER' for m in messages) and p.get('barrier_reached') is False,'undeclared barrier observation')
        results=[m for m in messages if m.get('type')=='RESULT']
        if p['exit_code']==-9:
            require(not results and 'result' not in p and p.get('sender_result')=='UNKNOWN','crashed process claimed response')
        else:
            require(p['exit_code']==0 and len(results)==1 and same(results[0].get('result'),p.get('result')) and p.get('sender_result')=='RESPONSE','successful process response evidence differs')
            _settings(results[0].get('writer_connection'),'actual completed child writer')


def _table_proofs(value, tables, label):
    require(type(value) is dict and set(value)==set(tables),label+' table inventory differs')
    for table,p in value.items():
        require(type(p) is dict and type(p.get('rows')) is int and p['rows']>=0 and positive(p.get('bytes')) and digest(p.get('sha256')),label+' invalid '+table+' proof')


def _boundaries(row, spec):
    name=row['id']; bounds=row.get('boundaries');required= ('before','after_crash','after_retry') if name=='lost_ack' else ('before','after_crash') if name in ('crash_after_record','crash_after_receipt','crash_after_disposition','save_run_crash') else ('before','after_replay') if name=='transport_replay' else ()
    require(type(bounds) is dict and set(bounds)==set(required),'atomic boundary inventory differs: '+name)
    for snap in bounds.values():
        require(type(snap) is dict,'invalid boundary snapshot')
        _table_proofs(snap.get('core_tables'),CORE_TABLES,'boundary core')
        _table_proofs(snap.get('run_tables'),RUN_TABLES,'boundary run')
        require(type(snap.get('run_payload_hashes')) is dict and all(digest(k) and digest(v) for k,v in snap['run_payload_hashes'].items()),'boundary saved payload hashes missing')
        require(snap['run_tables']['runs']['rows']==len(snap['run_payload_hashes']),'boundary saved run inventory differs')
    if name.startswith('crash_after_'):
        require(same(bounds['before'],bounds['after_crash']),'precommit before/after evidence differs')
        require(all(bounds['before']['core_tables'][t]['rows']==(1 if t=='streams' else 8) for t in CORE_TABLES),'precommit eight-record prefix missing')
        require(bounds['before']['run_tables']['runs']['rows']==0,'precommit unexpected financial run')
    if name=='save_run_crash':
        require(same(bounds['before'],bounds['after_crash']),'save_run before/after all-table rollback differs')
        require(bounds['before']['run_tables']['runs']['rows']==1 and bounds['before']['run_tables']['findings']['rows']==6,'old complete saved run missing')
        require(all(row['observed']['run_payload_hashes'].get(k)==v for k,v in bounds['before']['run_payload_hashes'].items()),'old run payload changed')
        require(row['observed']['run_table_counts']=={'runs':2,'findings':12,'evidence':row['observed']['run_table_counts']['evidence'],'correction_groups':1,'correction_effects':2},'corrected run table inventory differs')
        require(positive(row['observed']['run_table_counts']['evidence']),'saved evidence empty')
    if name=='transport_replay':
        before=bounds['before'];after=bounds['after_replay']
        require(all(same(before['core_tables'][t],after['core_tables'][t]) for t in CORE_TABLES if t!='attempts') and same(before['run_tables'],after['run_tables']) and same(before['run_payload_hashes'],after['run_payload_hashes']),'replay modified original core/run evidence')
        require(before['core_tables']['attempts']['rows']==30 and after['core_tables']['attempts']['rows']==60,'replay attempt inventory differs')
    if name=='lost_ack':
        before,after,retry=(bounds[k] for k in required)
        require(before['core_tables']['receipts']['rows']==8 and after['core_tables']['receipts']['rows']==9,'lost ACK commit receipt evidence missing')
        require(all(same(after['core_tables'][t],retry['core_tables'][t]) for t in CORE_TABLES if t!='attempts'),'lost ACK retry changed receipt/effect')
        require(after['core_tables']['attempts']['rows']==9 and retry['core_tables']['attempts']['rows']==10,'lost ACK retry attempt differs')
        for state,count in ((before,8),(after,9),(retry,9)):
            require(state['core_tables']['effects']['rows']==count and state['core_tables']['records']['rows']==count and state['run_tables']['runs']['rows']==0,'lost ACK boundary scope differs')


def _delivery_response(value, observed):
    require(type(value) is dict and value.get('format')=='delivery-response-v1','delivery response missing')
    outcome=value.get('outcome');require(outcome in ('COMMITTED','REPLAY','RETRYABLE_BUSY','GAP','OUT_OF_RANGE','TRANSPORT_CONFLICT','PLAN_CONFLICT','BLOCKED'),'unknown delivery outcome');require(type(value.get('ack')) is bool and type(value.get('durable')) is bool,'delivery ACK/durable types differ')
    require(value['ack'] is (outcome in ('COMMITTED','REPLAY')),'delivery outcome/ACK contradiction')
    if outcome=='RETRYABLE_BUSY':
        require(value['durable'] is False and value.get('attempt_id') is None,'busy claimed durable attempt')
    else:
        require(value['durable'] is True and positive(value.get('attempt_id')),'durable response attempt missing')
    if value['ack']:
        found=[e for e in observed['effect_identities'] if e[0]==value.get('stream_id') and e[1]==value.get('sequence')]
        require(len(found)==1,'response effect identity absent')
        effect=found[0];require(value.get('core_receipt_row_id')==effect[3] and value.get('disposition')==effect[4],'response original receipt/disposition differs')
        result=value.get('core_result')
        if effect[4]=='REJECTED_FRAME':require(result is None and effect[3] is None,'rejected frame fabricated receipt')
        else:
            links=[r for r in observed['receipt_links'] if r[0]==effect[3]]
            require(len(links)==1 and type(result) is dict,'response receipt link missing')
            receipt=links[0]
            require([result.get('receipt_id'),result.get('record_id'),result.get('status')]==receipt[1:],'response core result differs from stored receipt')


def validate_case(row, scope):
    require(type(row) is dict and row.get('id') in scope['scenarios'],'unknown scenario observation')
    name=row['id'];spec=scope['scenarios'][name]
    validate_plan(name,row.get('expected'),scope)
    require(row.get('status')=='PASS','scenario failed or incomplete: '+name)
    checks=_checks(row.get('checks'),spec['required_checks'],name)
    _processes(row,scope)
    obs=row.get('observed');require(type(obs) is dict,'observed delivery evidence missing')
    require(same(obs.get('core_receipts'),spec['receipts']) and same(obs.get('unique_records'),spec['records']) and same(obs.get('core_statuses'),spec['core_statuses']),'observed core inventory differs')
    require(obs.get('integrity_check')=='ok' and obs.get('foreign_key_check')==[],'observed SQLite integrity evidence differs')
    effects=obs.get('effect_identities');require(type(effects) is list and all(type(e) is list and len(e)==5 for e in effects),'observed effect identities missing')
    require(same([e[:2] for e in effects],sorted([[s,i] for s,n in spec['streams'].items() for i in range(1,n+1)])),'observed exact effect sequence inventory differs')
    receipts=obs.get('receipt_links');require(type(receipts) is list and len(receipts)==spec['receipts'] and all(type(r) is list and len(r)==4 and positive(r[0]) and digest(r[1]) and (r[2] is None or digest(r[2])) for r in receipts),'observed receipt links missing')
    require(len({r[0] for r in receipts})==len(receipts),'duplicate physical receipt row')
    records=obs.get('record_ids');require(type(records) is list and len(set(records))==len(records)==spec['records'] and all(digest(r) for r in records),'observed record IDs differ')
    require(all(r[2] is None or r[2] in records for r in receipts),'observed receipt record link differs')
    seen=[]
    for stream,seq,payload_hash,receipt_id,disposition in effects:
        inp=scope['inputs'][spec['stream_inputs'][stream]]
        require(payload_hash==inp['line_hashes'][seq-1],'observed first exact payload hash differs')
        if disposition=='REJECTED_FRAME':require(name=='rejected_json' and seq==31 and receipt_id is None,'unexpected rejected-frame identity')
        else:
            linked=[r for r in receipts if r[0]==receipt_id]
            require(len(linked)==1 and linked[0][3]==disposition,'effect/receipt disposition link differs');seen.append(receipt_id)
    require(len(seen)==len(set(seen))==spec['receipts'],'effect/core receipt inventory differs')
    streams=obs.get('streams');require(type(streams) is list and sorted(s.get('stream_id') for s in streams)==sorted(spec['streams']),'observed immutable stream inventory differs')
    for stream in streams:
        sid=stream['stream_id'];inp=scope['inputs'][spec['stream_inputs'][sid]]
        require(all(same(stream.get(k),inp[k]) for k in ('input_sha256','input_bytes','planned_lines','framing')),'observed immutable plan differs')
    runs=obs.get('run_ids');hashes=obs.get('run_payload_hashes')
    require(type(runs) is list and len(runs)==len(set(runs))==spec['run_count'] and all(digest(r) for r in runs) and type(hashes) is dict and set(hashes)==set(runs) and all(digest(v) for v in hashes.values()),'required/forbidden saved financial run inventory differs')
    run_rows=obs.get('run_rows');require(type(run_rows) is list and all(type(r) is dict for r in run_rows) and [r.get('run_id') for r in run_rows]==runs,'saved run row evidence missing')
    for run in run_rows:
        require(run.get('payload_sha256')==hashes[run['run_id']] and type(run.get('findings')) is int and run['findings']==6 and positive(run.get('evidence')),'saved payload/count linkage differs')
    counts=obs.get('run_table_counts');require(type(counts) is dict and set(counts)==set(RUN_TABLES) and all(type(v) is int and v>=0 for v in counts.values()) and counts['runs']==len(runs),'saved run table evidence missing')
    require(counts['findings']==sum(r['findings'] for r in run_rows) and counts['evidence']==sum(r['evidence'] for r in run_rows),'saved run rows/table counts disagree')
    if name=='save_run_crash':
        require(same(checks['all_saved_evidence_rows']['actual'],counts['evidence']),'saved evidence control/readback differs')
    financial=row.get('financial');variant=spec['plan']['financial_projection']
    if variant=='NOT_RUN':
        require(type(financial) is dict and financial.get('status')=='NOT_RUN' and type(financial.get('reason')) is str and financial['reason'] and all(v==0 for v in counts.values()),'forbidden financial phase ran or evidence missing')
    else:
        reference=scope['financial_references'][variant]
        require(type(financial) is dict and financial.get('status')=='EVALUATED' and financial.get('variant')==variant and financial.get('run_id') in runs,'required financial phase absent')
        require(same(financial.get('findings'),reference['findings']) and same(financial.get('ledgers'),reference['ledgers']),'financial literal projection evidence differs')
        require(counts['findings']==6*len(runs) and positive(counts['evidence']),'saved financial findings/evidence missing')
    responses=row.get('responses');require(type(responses) is list,'response evidence missing')
    require(bool(responses) or name in scope['writer_scenarios'],'required response evidence empty')
    all_responses=list(responses)+[p['result'] for p in row['processes'] if 'result' in p]
    attempts=Counter()
    for response in all_responses:
        require(type(response) is dict,'response must be an object')
        if response.get('format')=='feed-admission-v1':
            sid=response.get('stream_id');require(sid in spec['streams'],'feed response stream differs')
            input_name=spec['stream_inputs'][sid]
            if name in ('changed_prefix','truncated_file'): input_name=name+'_snapshot'
            inp=scope['inputs'][input_name]
            wanted_plan={'format':'admission-plan-v1',**{k:inp[k] for k in ('input_sha256','input_bytes','planned_lines','framing')}}
            require(same(response.get('plan'),wanted_plan),'feed response plan evidence differs')
            outcomes=response.get('response_outcomes')
            require(type(outcomes) is dict and outcomes and all(type(k) is str and positive(v) for k,v in outcomes.items()),'feed response outcome counts missing')
            require(response.get('financial_evaluation')=='NOT_RUN' and positive(response.get('response_count')) and sum(outcomes.values())==response['response_count'],'finite feed response scope missing')
            last=response.get('last_response');_delivery_response(last,obs)
            require(last.get('stream_id')==sid and outcomes.get(last['outcome'],0)>0,'feed last response/outcome linkage differs')
            terminal=response.get('status');prefix=response.get('committed_prefix')
            unknown_busy = (name in scope['writer_scenarios'] and terminal == 'INCOMPLETE'
                and response.get('state_observation') == 'UNKNOWN'
                and prefix is None and response.get('blocked') is None
                and last.get('outcome') == 'RETRYABLE_BUSY' and last.get('ack') is False
                and last.get('durable') is False and last.get('attempt_id') is None
                and last.get('committed_prefix') is None and last.get('blocked') is None)
            require(type(response.get('blocked')) is bool or unknown_busy,'feed blocked observation missing')
            if terminal=='COMPLETE':
                require(response.get('state_observation','COMPLETE') == 'COMPLETE' and response['blocked'] is False and type(prefix) is int and prefix==inp['planned_lines'] and response['response_count']==inp['planned_lines'] and set(outcomes)<= {'COMMITTED','REPLAY'} and last.get('sequence')==inp['planned_lines'] and last.get('ack') is True,'complete feed response scope/terminal differs')
            elif terminal=='BLOCKED':
                require(response.get('state_observation','BLOCKED') == 'BLOCKED' and name in ('changed_prefix','truncated_file') and response['blocked'] is True and type(prefix) is int and prefix==8 and outcomes=={'PLAN_CONFLICT':1} and last.get('outcome')=='PLAN_CONFLICT','blocked feed response differs')
            else:
                require(terminal=='INCOMPLETE' and name in scope['writer_scenarios'] and last.get('ack') is False and last.get('outcome') in ('GAP','RETRYABLE_BUSY') and response['response_count']<=inp['planned_lines'] and (unknown_busy or (response.get('state_observation','INCOMPLETE') in ('INCOMPLETE','COMPLETE') and response['blocked'] is False and type(prefix) is int and 0<=prefix<=inp['planned_lines'])),'unexpected incomplete feed response')
            for outcome,count in outcomes.items():
                if outcome!='RETRYABLE_BUSY':attempts[outcome]+=count
        else:
            _delivery_response(response,obs)
            if response['durable']:attempts[response['outcome']]+=1
    if name=='lost_ack': attempts['COMMITTED']+=1  # committed child has no response
    require(same(obs.get('attempt_outcomes'),dict(attempts)),'observed attempt history differs from durable responses')
    require(attempts['COMMITTED']==sum(spec['streams'].values()),'committed attempt/effect inventory differs')
    if name=='lost_ack':
        replay=[r for r in responses if r.get('format')=='delivery-response-v1' and r.get('sequence')==9]
        require(len(replay)==1 and replay[0]['outcome']=='REPLAY','lost ACK retry response is not original replay')
        require(same(checks['unknown_retry_returns_original']['actual'],replay[0]['core_result']) and same(checks['unknown_retry_reuses_receipt_row']['actual'],replay[0]['core_receipt_row_id']),'lost ACK check/response inconsistency')
    _boundaries(row,spec)
    writers=row.get('writer_connections');require(type(writers) is list and writers,'actual writer connection observations missing')
    for writer in writers:
        require(type(writer) is dict and positive(writer.get('pid')) and type(writer.get('operation')) is str and writer['operation'],'writer provenance missing');_settings(writer,'actual parent writer')
    operations=[writer['operation'] for writer in writers]; policy=spec['writer_operations']
    if 'exact' in policy:
        require(same(operations,policy['exact']),'required actual writer operation inventory differs')
    else:
        require(operations[:1]==policy['prefix'] and operations[-1:]==policy['suffix'] and len(operations)-2<=policy['maximum_optional'] and all(op==policy['optional'] for op in operations[1:-1]),'bounded parent retry writer inventory differs')
    parent_pids={writer['pid'] for writer in writers}
    require(len(parent_pids)==1 and not parent_pids.intersection(p['pid'] for p in row['processes']),'parent writer process identity differs')
    _settings(row.get('readback_connection'),'separate readback')
    return True


def validate_report(report, scope, *, schedule_sha256):
    require(type(report) is dict and report.get('format')==scope['report_format'] and report.get('status')=='PASS','recovery did not complete successfully or format differs')
    expected=scope['scenario_ids']
    for field in ('planned_scenario_ids','executed_scenario_ids'):
        require(same(report.get(field),expected),field+' differs from fixed recovery scope')
    require(digest(schedule_sha256) and report.get('schedule_sha256')==schedule_sha256,'saved schedule differs from executed plan')
    rows=report.get('scenarios');require(type(rows) is list and all(type(r) is dict for r in rows) and [r.get('id') for r in rows]==expected,'scenario observations missing/duplicated')
    for row in rows:validate_case(row,scope)
    negative=report.get('negative_control');require(type(negative) is dict and negative.get('status')=='EXPECTED_FAILURE','negative harness control missing')
    checks=negative.get('checks');require(type(checks) is list and checks,'negative invariant evidence absent')
    verified_negative=_checks(checks,scope['negative_checks'],'negative controls',allow_fail=True)
    require(all(same(verified_negative[k]['actual'],v) for k,v in scope['negative_actual'].items()),'negative model empty-state observations differ')
    names=[c.get('name') for c in checks];require(all(type(n) is str for n in names) and len(names)==len(set(names)),'negative invariant identity differs')
    for c in checks:
        require(set(c)=={'name','actual','expected','passed'} and type(c['passed']) is bool and c['passed'] is same(c['actual'],c['expected']),'negative expected/actual/passed inconsistency')
    rejected=[c['name'] for c in checks if c['passed'] is False]
    require(same(negative.get('rejected_checks'),rejected) and set(scope['negative_required_failures'])<=set(rejected),'negative required failed invariants missing')
    models=negative.get('models');require(type(models) is list and [m.get('name') for m in models]==scope['negative_models'] and all(m.get('observed_status')=='FAIL' and same(m.get('rejected_checks'),rejected) for m in models),'broken transport models were not rejected by recorded invariants')
    require(negative.get('claimed_ack') is True and type(negative.get('claimed_cursor')) is int and negative['claimed_cursor']==1,'negative model claims missing')
    environment=report.get('environment');require(type(environment) is dict and all(type(environment.get(k)) is str and environment[k] for k in ('python','interpreter','import_origin','sqlite','platform')),'actual recovery environment missing')
    require(environment.get('settings_provenance')=='Per-case writer_connections and child READY/BARRIER/RESULT; separate readback_connection','connection observation provenance missing')
    return {'status':'PASS','scope_identity':identity(),'expected_count':len(expected),'executed_count':len(rows),'required_crash_barriers':scope['crash_barriers'],'negative_models_rejected':scope['negative_models'],'schedule_sha256':schedule_sha256,'semantic_scope':'v2 required work, controls and evidence links'}
