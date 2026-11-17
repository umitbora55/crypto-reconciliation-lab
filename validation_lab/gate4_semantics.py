"""Finite paired Gate4 semantic witnesses; no product monkeypatch or setting changes.

Fixture helpers construct inputs only. Expected economic quantities are literal
preregistered values. The receipt hash checker and all-table reader use stdlib.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import sqlite3
import sys
import time
import traceback

from crypto_reconciliation_lab import Store, reconcile
from crypto_reconciliation_lab.admission.feed import snapshot_feed
from crypto_reconciliation_lab.correction_demo import correction, correction_manifest
from crypto_reconciliation_lab.demo import fixtures
from validation_lab.gate4_storage import METHODS, open_store, read_pragmas, disk_snapshot

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'contracts/gate4-semantics-catalog.json'
BALANCE = '2026-11-10T23:59:59Z'
EARLY = '2026-11-11T01:00:00Z'
LATE = '2026-11-11T03:00:00Z'
OBSERVED = '2026-11-12T00:00:00Z'


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    path.write_bytes(wire(value) + b'\n')


def check(condition, label):
    if not condition:
        raise AssertionError(label)


def plan(lines):
    raw = b''.join(lines)
    return {'format': 'admission-plan-v1', 'input_sha256': sha(raw), 'input_bytes': len(raw),
            'planned_lines': len(lines), 'framing': 'utf8-lf-jsonl-v1'}


def snapshot(store):
    """All logical rows, exact BLOB bytes, schema and physical receipt order."""
    def encode(value):
        return {'blob_hex': value.hex()} if isinstance(value, bytes) else value
    tables = {}
    for (name,) in store.db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        quoted = '"' + name.replace('"', '""') + '"'
        columns = [r[1] for r in store.db.execute('PRAGMA table_info(' + quoted + ')')]
        rows = [[encode(v) for v in r] for r in store.db.execute('SELECT * FROM ' + quoted)]
        tables[name] = {'columns': columns, 'rows': sorted(rows, key=wire)}
    receipts = [dict(r) for r in store.db.execute('SELECT * FROM receipts ORDER BY id')]
    schema = [list(r) for r in store.db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name')]
    return {'tables': tables, 'receipts_in_id_order': receipts, 'schema': schema}


def source_identity():
    names = [p for p in (ROOT/'crypto_reconciliation_lab').rglob('*.py')]
    names += [Path(__file__), ROOT/'validation_lab/gate4_storage.py', CATALOG]
    return {str(p.relative_to(ROOT)): {'bytes': p.stat().st_size, 'sha256': sha(p.read_bytes())} for p in sorted(names)}


def case_input(spec):
    name = spec['id']
    config, initial, later = fixtures('late_event' if name == 'late_event' else 'clean')
    extra = []
    if name == 'one_asset':
        config['assets'] = {'ASSET_A': 8}
        initial = [r for r in initial if r['record']['asset'] == 'ASSET_A']
    if name == 'cross_asset':
        for row in initial:
            r = row['record']
            if r['kind'] == 'report' and r['stream'] == 'external_custody':
                r['amount'] = '8' if r['asset'] == 'ASSET_A' else '1.45'
    if name == 'direct_redelivery':
        extra = copy.deepcopy(initial)
    if name in ('normalized_duplicate', 'same_key_conflict', 'invalid_quarantine'):
        target = copy.deepcopy(next(r for r in initial if r['record'].get('ref') == 'A1'))
        target['received_at'] = LATE
        if name == 'normalized_duplicate':
            target['record']['amount'] = '1.00000000'
            target['record']['occurred_at'] = '2026-11-10T04:00:00+03:00'
        else:
            target['record']['amount'] = '2' if name == 'same_key_conflict' else 'NaN'
        extra = [target]
    if name in ('correction_void', 'correction_replace'):
        extra = [{'record': correction(mode='VOID' if name.endswith('void') else 'REPLACE'), 'received_at': LATE},
                 {'record': correction_manifest(), 'received_at': LATE}]
    return {'config': config, 'initial': initial, 'extra': extra, 'later': later}


def assert_receipts(store, expected):
    rows = list(store.db.execute('SELECT id,receipt_hash,raw,status FROM receipts ORDER BY id'))
    check(len(rows) == len(expected), 'exact receipt count')
    for index, (actual, (envelope, status)) in enumerate(zip(rows, expected), 1):
        check(actual[0] == index, 'receipt physical insertion id')
        check(actual[1] == sha(wire(envelope)), 'receipt identity independently bound to exact request')
        check(actual[2] == wire(envelope).decode(), 'receipt raw request bytes')
        check(actual[3] == status, 'receipt status order')


def finding(run, asset, scope='customer_liability'):
    return next(r for r in run['findings'] if r['asset'] == asset and r['scope'] == scope)


def quantities(run, expected):
    check(set(run['ledgers']) == set(expected), 'exact asset set')
    for asset, fields in expected.items():
        for field, value in fields.items():
            check(run['ledgers'][asset][field] == value, 'literal economic oracle ' + asset + '/' + field)


def all_matched(run):
    check(all(r['data_state'] == 'COMPLETE' and r['reconciliation_state'] == 'MATCHED' for r in run['findings']), 'all findings complete matched')


def persisted_run(store, run, folder, label):
    payload = store.db.execute('SELECT payload FROM runs WHERE id=?', (run['run_id'],)).fetchone()[0].encode()
    check(sha(payload) == run['run_id'], 'canonical run id independently hashed')
    check(wire({k:v for k,v in run.items() if k != 'run_id'}) == payload, 'exact canonical saved run')
    check(store.read_run(run['run_id']) == run, 'saved read equality')
    check([json.loads(r[0]) for r in store.db.execute('SELECT payload FROM findings WHERE run_id=? ORDER BY ordinal', (run['run_id'],))] == run['findings'], 'finding persistence')
    evidence = {r[0]: json.loads(r[1]) for r in store.db.execute('SELECT evidence_id,payload FROM evidence WHERE run_id=?', (run['run_id'],))}
    check(evidence == run['evidence'], 'exact selected evidence links')
    (folder / (label + '-canonical-run.json')).write_bytes(payload)


def run_financial(store, spec, data, folder):
    expected_receipts, responses, runs = [], [], {}
    def ingest(envelope, status):
        result = store.ingest(envelope['record'], envelope['received_at'])
        check(result['status'] == status, 'expected direct disposition')
        check(not store.db.in_transaction, 'return after transaction completion')
        responses.append(result); expected_receipts.append((envelope, status))
    for r in data['initial']: ingest(r, 'ACCEPTED')
    before = reconcile(store, BALANCE, EARLY); runs['initial'] = before
    e = spec['expected']; quantities(before, e['initial'])
    if e['initial_all_matched']: all_matched(before)
    if 'initial_A_data_state' in e:
        check(finding(before, 'ASSET_A')['data_state'] == e['initial_A_data_state'], 'early incomplete classification')
        check(finding(before, 'ASSET_A')['difference'] == e['initial_A_liability_difference'], 'early liability difference')
    for asset, value in e.get('initial_differences', {}).items():
        check(finding(before, asset)['difference'] == value, 'assets cannot offset')
        check(finding(before, asset)['reconciliation_state'] == 'MISMATCH', 'per-asset mismatch')
    for r in data['extra']:
        status = {'direct_redelivery':'DUPLICATE','normalized_duplicate':'DUPLICATE','same_key_conflict':'CONFLICT','invalid_quarantine':'INVALID'}.get(spec['id'], 'ACCEPTED')
        ingest(r, status)
    for r in data['later']: ingest(r, 'ACCEPTED')
    if data['extra'] or data['later']:
        after = reconcile(store, BALANCE, LATE); runs['later'] = after
        if 'later' in e: quantities(after, e['later'])
        if e.get('later_all_matched'): all_matched(after)
        if 'later_A_data_state' in e:
            check(finding(after,'ASSET_A')['data_state'] == e['later_A_data_state'], 'late noncomplete classification')
            check(finding(after,'ASSET_A')['reconciliation_state'] == 'NOT_EVALUATED', 'invalid/conflict never definite outcome')
        if 'later_A_issue' in e:
            check(e['later_A_issue'] in [i['code'] for i in finding(after, 'ASSET_A')['issues']], 'conflict issue retained')
        for scope, value in e.get('later_A_differences', {}).items():
            check(finding(after,'ASSET_A',scope)['difference'] == value, 'correction difference literal')
        if 'correction_effects' in e:
            groups = after['ledgers']['ASSET_A']['correction_groups']
            check(len(groups) == 1 and len(groups[0]['effects']) == e['correction_effects'], 'correction group effect inventory')
            for key in ('id','target_record_id','correction_record_id'):
                check(groups[0][key] in after['evidence'], 'correction causal evidence')
        check(reconcile(store,BALANCE,EARLY) == before, 'historical knowledge cut immutable')
    for label, run in runs.items(): persisted_run(store, run, folder, label)
    assert_receipts(store, expected_receipts)
    return {'responses': responses, 'run_ids': {k:v['run_id'] for k,v in runs.items()}, 'runs':runs,
            'expected_receipt_bindings': [{'physical_id':i,'receipt_hash':sha(wire(r)),'status':s} for i,(r,s) in enumerate(expected_receipts,1)]}


def run_transport(store, spec, data, folder):
    name, e = spec['id'], spec['expected']; responses=[]; errors=[]; expected_receipts=[]; runs={}
    line = wire(data['initial'][0])+b'\n'
    def deliver(stream, seq, payload, delivery_plan, fault=None):
        result = store.ingest_delivery(stream,seq,payload,delivery_plan,observed_at=OBSERVED,fault=fault)
        check(not store.db.in_transaction, 'transport result after transaction completion')
        responses.append(result)
        if result['outcome']=='COMMITTED' and result['core_result'] is not None:
            expected_receipts.append((json.loads(payload), result['disposition']))
        return result
    def rejected(action):
        before=snapshot(store)
        try: action()
        except ValueError as exc: errors.append({'type':'ValueError','message':str(exc)})
        else: raise AssertionError('required explicit rejection absent')
        check(snapshot(store)==before, 'rejected input made no durable change')
    if name in ('exact_replay','duplicate_sequence','conflicting_key'):
        changed = copy.deepcopy(data['initial'][0]);changed['record']['amount']='9'
        lines=[line,wire(changed)+b'\n'] if name=='conflicting_key' else [line,line]
        p=plan(lines[:1] if name=='exact_replay' else lines)
        deliver('S',1,line,p);deliver('S',1 if name=='exact_replay' else 2,lines[1],p)
        check([r['disposition'] for r in responses]==e['dispositions'], 'literal transport dispositions')
        check([r['outcome'] for r in responses]==e['outcomes'], 'literal transport outcomes')
        check(all(r['ack'] and r['durable'] for r in responses), 'committed terminal disposition ACK')
        if name=='exact_replay':
            check(responses[0]['core_receipt_row_id']==responses[1]['core_receipt_row_id'], 'replay reuses original physical receipt')
            check(responses[0]['core_result']==responses[1]['core_result'], 'replay original result binding')
    elif name in ('invalid_types','frame_errors'):
        if name=='invalid_types':
            lines=[]
            for bad in ('NaN',0.25,None,'9'*65,[]):
                row=copy.deepcopy(data['initial'][0]);row['record']['amount']=bad;lines.append(wire(row)+b'\n')
        else: lines=[b'{bad}\n',b'{"record":{},"record":{},"received_at":null}\n',b'{"record":NaN,"received_at":null}\n',b'{"record":1e999,"received_at":null}\n',b'\xff\n']
        p=plan(lines)
        for n,payload in enumerate(lines,1):
            result=deliver('S',n,payload,p)
            check(result['ack'] and result['disposition']==e['all_disposition'], 'terminal rejection disposition explicit')
            check(result['disposition']!='ACCEPTED','no false economic acceptance')
    elif name=='transport_conflict':
        p=plan([line,line]);deliver('S',1,line,p);deliver('S',1,line[:-1]+b' \n',p);deliver('S',2,line,p)
        check([r['outcome'] for r in responses]==e['outcomes'],'same identity payload conflict blocks')
        check([r['ack'] for r in responses]==e['acks'],'no false conflict ACK')
    elif name=='aborted_prefix':
        lines=[wire(r)+b'\n' for r in data['initial']];p=plan(lines);deliver('S',1,lines[0],p)
        before=snapshot(store)
        def abort(point):
            if point=='delivery_after_receipt':raise RuntimeError('owned input abort before commit')
        try:deliver('S',2,lines[1],p,fault=abort)
        except RuntimeError as exc:errors.append({'type':'RuntimeError','message':str(exc)})
        else:raise AssertionError('aborted delivery returned false success')
        check(snapshot(store)==before,'aborted transaction entirely rolled back')
        check(store.db.execute('SELECT count(*) FROM receipts').fetchone()[0]==e['rollback_receipts'],'prefix remains exact')
        for n,payload in enumerate(lines,1):deliver('S',n,payload,p)
        run=reconcile(store,BALANCE,EARLY);all_matched(run);persisted_run(store,run,folder,'recovered');runs['recovered']=run
    elif name=='changed_partial_file':
        lines=[wire(r)+b'\n' for r in data['initial'][:2]];original=folder/'original.jsonl';original.write_bytes(b''.join(lines))
        first=snapshot_feed(original);deliver('S',1,first.lines[0],first.plan)
        partial=folder/'shortened.jsonl';partial.write_bytes(lines[0]);short=snapshot_feed(partial)
        response=deliver('S',1,short.lines[0],short.plan)
        check(response['outcome']==e['outcome'] and response['ack']==e['ack'],'shortened valid prefix is not complete stream')
        check(store.feed_status('S')['pending_sequences']==e['pending_sequences'],'uncommitted suffix remains pending')
    elif name=='snapshot_malformed':
        for n,payload in enumerate((b'',b'{}',b'{}\r\n',b'\n',b'{}\n \n',b'\xef\xbb\xbf{}\n',b'x'*65536+b'\n',line+b'{"record":')):
            path=folder/('malformed-'+str(n)+'.jsonl');path.write_bytes(payload);rejected(lambda:snapshot_feed(path))
    elif name=='protocol_bad_types':
        p=plan([line])
        for stream,sequence,payload,kwargs in [(' bad',1,line,{}),('S',True,line,{}),('S',0,line,{}),('S',1,'text',{}),('S',1,b'x'*65537,{}),('S',1,line,{'busy_timeout_ms':5001})]:
            rejected(lambda:store.ingest_delivery(stream,sequence,payload,p,observed_at=OBSERVED,**kwargs))
        rejected(lambda:store.ingest_delivery('S',1,line,dict(p,planned_lines=True),observed_at=OBSERVED))
    else:raise AssertionError('unknown preregistered transport case')
    for table in ('receipts','records'):
        check(store.db.execute('SELECT count(*) FROM '+table).fetchone()[0]==e[table], 'literal '+table+' count')
    if 'explicit_errors' in e:check(len(errors)==e['explicit_errors'],'all specified explicit input errors')
    assert_receipts(store,expected_receipts)
    # Bind every delivery effect to exact payload/plan and its physical core receipt.
    for row in store.db.execute('SELECT * FROM delivery_effects ORDER BY stream_id,sequence'):
        check(row['payload_sha256']==sha(bytes(row['payload'])),'delivery exact payload hash')
        if row['core_receipt_id'] is not None:
            receipt=store.db.execute('SELECT receipt_hash FROM receipts WHERE id=?',(row['core_receipt_id'],)).fetchone()
            check(receipt is not None and receipt[0]==row['core_receipt_hash'],'effect original receipt foreign key/hash')
    return {'responses':responses,'errors':errors,'runs':runs,'expected_receipt_bindings':[{'physical_id':i,'receipt_hash':sha(wire(r)),'status':s} for i,(r,s) in enumerate(expected_receipts,1)]}


def compare_pair(baseline, candidate):
    for key in ('observations','logical_before_reopen','logical_after_reopen','canonical_files'):
        check(baseline[key]==candidate[key],'exact paired '+key)


def run(output):
    output.mkdir(parents=True,exist_ok=False)
    catalog=json.loads(CATALOG.read_bytes());limits=catalog['limits']
    resource.setrlimit(resource.RLIMIT_AS,(limits['address_space_bytes'],limits['address_space_bytes']))
    resource.setrlimit(resource.RLIMIT_CPU,(limits['cpu_seconds'],limits['cpu_seconds']))
    resource.setrlimit(resource.RLIMIT_FSIZE,(limits['file_size_bytes'],limits['file_size_bytes']))
    signal.alarm(limits['wall_seconds'])
    start=time.monotonic();source=source_identity();save(output/'source-before.json',source)
    (output/'preregistered-catalog.json').write_bytes(CATALOG.read_bytes())
    # Materialize every input before the first candidate execution. Hashes retained.
    inputs=output/'inputs';inputs.mkdir();input_manifest={}
    for spec in catalog['cases']:
        path=inputs/(spec['id']+'.json');save(path,case_input(spec));input_manifest[spec['id']]={'path':str(path),'bytes':path.stat().st_size,'sha256':sha(path.read_bytes())}
    save(output/'input-manifest.json',input_manifest)
    results=[]
    for spec in catalog['cases']:
        case=output/spec['id'];case.mkdir();data=json.loads((inputs/(spec['id']+'.json')).read_bytes())
        master=case/'initial.sqlite3';initial=Store(master,data['config']);initial_pragmas=read_pragmas(initial);initial.close()
        initial_hash=sha(master.read_bytes());pair=[]
        for method in METHODS:
            folder=case/method;folder.mkdir();dbpath=folder/'owned.sqlite3';shutil.copyfile(master,dbpath)
            check(sha(dbpath.read_bytes())==initial_hash,'identical initial DB bytes')
            record={'case':spec['id'],'method':method,'input':input_manifest[spec['id']],'initial_database_sha256':initial_hash,'initial_database_pragmas':initial_pragmas,'status':'RUNNING'}
            save(folder/'started.json',record);store=None
            try:
                store=open_store(dbpath,method=method);record['pragmas_open']=read_pragmas(store)
                record['observations']=(run_financial if spec['family']=='financial' else run_transport)(store,spec,data,folder)
                record['logical_before_reopen']=snapshot(store);record['disk_before_close']=disk_snapshot(dbpath)
                save(folder/'logical-before-reopen.json',record['logical_before_reopen'])
                store.close();store=None;record['disk_after_close']=disk_snapshot(dbpath)
                store=open_store(dbpath,method=method);record['pragmas_reopen']=read_pragmas(store)
                record['logical_after_reopen']=snapshot(store)
                check(record['logical_before_reopen']==record['logical_after_reopen'],'all rows and schema survive reopen')
                for label,saved in record['observations']['runs'].items():
                    check(store.read_run(saved['run_id'])==saved,'saved run survives reopen')
                check(store.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','SQLite integrity')
                check(store.db.execute('PRAGMA foreign_key_check').fetchall()==[],'foreign key integrity')
                record['canonical_files']={p.name:sha(p.read_bytes()) for p in sorted(folder.glob('*-canonical-run.json'))}
                record['status']='PASS'
            except Exception as exc:
                record.update(status='FAIL',error=repr(exc),traceback=traceback.format_exc())
            finally:
                if store is not None:store.close()
            save(folder/'result.json',record);pair.append(record)
        pair_result={'case':spec['id'],'methods':{r['method']:r['status'] for r in pair},'status':'FAIL'}
        if all(r['status']=='PASS' for r in pair):
            try:compare_pair(*pair);pair_result['status']='PASS'
            except AssertionError as exc:pair_result['error']=str(exc)
        results.append(pair_result);save(case/'pair.json',pair_result)
        owned=sum(p.stat().st_size for p in output.rglob('*') if p.is_file())
        check(owned<=limits['owned_disk_bytes'],'owned evidence disk budget')
    after=source_identity();save(output/'source-after.json',after);check(source==after,'executed source closure unchanged')
    summary={'format':'gate4-semantics-result-v1','status':'PASS' if all(r['status']=='PASS' for r in results) else 'CANDIDATE_NOT_ACCEPTED','cases':results,'pair_count':len(results),'method_executions':2*len(results),'limits':limits,'wall_seconds':time.monotonic()-start,'owned_bytes':sum(p.stat().st_size for p in output.rglob('*') if p.is_file()),'argv':sys.argv,'cwd':os.getcwd(),'executable':sys.executable,'python':sys.version,'sqlite':sqlite3.sqlite_version,'import_source':str(Path(sys.modules['crypto_reconciliation_lab'].__file__).resolve()),'catalog_sha256':sha(CATALOG.read_bytes()),'scope_limit':'Component result only; final acceptance also requires crash, auth, portability and benchmark gates. ACK of INVALID/REJECTED_FRAME is explicit durable rejection, not successful economic admission.'}
    save(output/'summary.json',summary);print(json.dumps(summary));signal.alarm(0)
    return 0 if summary['status']=='PASS' else 1


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();return run(args.output)


if __name__=='__main__':raise SystemExit(main())
