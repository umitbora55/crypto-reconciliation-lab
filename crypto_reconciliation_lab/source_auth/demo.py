"""Fixed, bounded source-auth experiments; never runs the frozen AI experiment."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
from .. import __file__ as PACKAGE_ORIGIN
from ..engine import reconcile
from ..model import digest
from ..reporting import write_report
from ..store import Store
from .fixtures import (CONFIG, RECEIVER, BALANCE_AT, KNOWLEDGE_AT, TEST_KEYS,
                       financial_records, small_records, snapshot, signed, policy, operator_anchor)


def _write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')


def sql_readback(store):
    """Exact bounded rows, with BLOBs represented as hex; no quantity SQL arithmetic."""
    names=[r[0] for r in store.db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
           if r[0].startswith('auth_') or r[0] in ('admission_streams','delivery_effects','delivery_attempts','records','receipts','runs')]
    return {name:[{k:(v.hex() if isinstance(v,bytes) else v) for k,v in dict(row).items()}
                  for row in store.db.execute('SELECT * FROM '+name+' ORDER BY rowid')]
            for name in names}


def _claim(data,stream='platform-demo:sample',key='P1-old',caps=None,**changes):
    from .crypto import sign_statement
    from .scope import snapshot_bytes, capabilities
    snap=snapshot_bytes(data)
    if caps is None:
        caps=capabilities(snap,CONFIG)
    value={'format':'source-admission-statement-v1','source':TEST_KEYS[key][2],
           'receiver':RECEIVER,'configuration_digest':digest(CONFIG),'stream_id':stream,
           'plan':snap.plan,'capabilities':caps}
    value.update(changes)
    return sign_statement(value,bytes.fromhex(TEST_KEYS[key][0]),key)


def _worker(folder,db,data_path,envelope_path,barrier,rotate=None):
    request={'db':str(db),'snapshot':str(data_path),'envelope':str(envelope_path),'barrier':barrier}
    _write(folder/'worker-request.json',request)
    # Preserve the parent's isolation mode; source runs deliberately resolve this source.
    argv=[sys.executable]+(['-I'] if sys.flags.isolated else [])+['-m','crypto_reconciliation_lab.source_auth.worker','--request',str(folder/'worker-request.json')]
    child=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
    observations=[]
    def receive():
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout,selectors.EVENT_READ)
            if not selector.select(20):
                raise RuntimeError('auth worker barrier timeout')
        line=child.stdout.readline()
        if not line:
            raise RuntimeError('auth worker stopped: '+child.stderr.read())
        item=json.loads(line)
        observations.append(item)
        if item['pid']!=child.pid:
            raise RuntimeError('worker PID mismatch')
        return item
    try:
        if receive()['type']!='READY':
            raise RuntimeError('missing worker READY')
        child.stdin.write('GO\n'); child.stdin.flush()
        point=receive()
        if point.get('type')!='BARRIER' or point.get('point')!=barrier:
            raise RuntimeError('worker did not reach requested barrier')
        if rotate is None:
            child.send_signal(signal.SIGKILL)
            sender='UNKNOWN'
        else:
            rotate()
            child.stdin.write('CONTINUE\n');child.stdin.flush()
            if receive()['type']!='RESULT':
                raise RuntimeError('missing worker RESULT')
            sender='RESPONSE'
        exit_code=child.wait(timeout=20)
        stderr=child.stderr.read()
    finally:
        if child.poll() is None:
            child.kill();child.wait(timeout=10)
        for pipe in (child.stdin,child.stdout,child.stderr):
            pipe.close()
    return {'argv':argv,'pid':child.pid,'observations':observations,'requested_barrier':barrier,
            'exit':exit_code,'joined':True,'signal':'SIGKILL' if rotate is None else None,
            'sender':sender,'stderr':stderr}


def _case(root,case_id):
    from .runtime import enable_protection,activate_policy,ingest_signed,auth_status
    from .scope import capabilities,snapshot_bytes
    folder=root/case_id;folder.mkdir()
    p=policy()
    data=snapshot(small_records())
    key='P1-old';stream='platform-demo:sample'
    if case_id=='unauthorized_asset':
        data=snapshot([financial_records()['P1'][4]])
        p['sources'][0]['capabilities']=[c for c in p['sources'][0]['capabilities'] if c['asset']=='ASSET_A']
    elif case_id=='unauthorized_kind':
        p['sources'][0]['capabilities']=[c for c in p['sources'][0]['capabilities'] if c['kind']!='opening']
    elif case_id=='unauthorized_channel':
        data=snapshot([next(x for x in financial_records()['P1'] if x['record'].get('stream')=='investor' and x['record']['kind']=='report')])
        p['sources'][0]['capabilities']=[c for c in p['sources'][0]['capabilities'] if c['channel']!='investor']
    elif case_id=='cartesian_hole':
        data=snapshot([next(x for x in financial_records()['P1'] if x['record']['kind']=='event')])
        p['sources'][0]['capabilities']=[c for c in p['sources'][0]['capabilities'] if (c['asset'],c['kind']) in (('ASSET_A','opening'),('ASSET_B','event'))]
    store=Store(folder/'evidence.sqlite3',CONFIG)
    enable_protection(store,RECEIVER,p)
    case={'id':case_id,'initial_policy':p,'operations':[],'policy_updates':[]}
    _write(folder/'config.json',CONFIG);_write(folder/'initial-policy.json',p)
    def operation(data,envelope=None,**kw):
        envelope=envelope if envelope is not None else signed(data,stream,key)
        ordinal=len(case['operations'])+1
        dp=folder/f'{ordinal:02d}-snapshot.jsonl'; ep=folder/f'{ordinal:02d}-envelope.json'
        dp.write_bytes(data);ep.write_bytes(envelope)
        before=sql_readback(store)
        result=ingest_signed(store,data,envelope,**kw)
        item={'snapshot':str(dp.relative_to(root)),'envelope':str(ep.relative_to(root)),
              'before':before,'after':sql_readback(store),'result':result}
        case['operations'].append(item)
        return item
    def rotate():
        active=auth_status(store)['active_policy']
        candidate=policy(rotated=True)
        result=activate_policy(store,candidate,active['epoch'],active['policy_hash'])
        case['policy_updates'].append({'policy':candidate,'expected_epoch':active['epoch'],
                                       'expected_hash':active['policy_hash'],'result':result})
    try:
        if case_id in ('valid_publishers','wrong_custody'):
            feeds=financial_records(case_id=='wrong_custody')
            for source,k,s in (('P1','P1-old','platform-demo:financial'),('C1','C1-key','custodian-demo:financial')):
                raw=snapshot(feeds[source]);operation(raw,signed(raw,s,k))
            result=reconcile(store,BALANCE_AT,KNOWLEDGE_AT)
            write_report(folder/'financial',result)
            case['financial']='%s/financial.json'%case_id
            if case_id=='valid_publishers':
                legacy=Store(folder/'legacy.sqlite3',CONFIG)
                try:
                    for source in ('P1','C1'):
                        for env in feeds[source]:
                            legacy.ingest(env['record'],env['received_at'])
                    old=reconcile(legacy,BALANCE_AT,KNOWLEDGE_AT)
                    write_report(folder/'legacy-financial',old)
                    case['legacy_sql']=sql_readback(legacy)
                finally:
                    legacy.close()
                case['legacy_financial']='%s/legacy-financial.json'%case_id
        elif case_id=='invalid_amount':
            records=small_records()[:1];records[0]['record']['amount']='NaN'
            operation(snapshot(records))
        elif case_id in ('normal_replay','revoked_replay','new_key_resume','authorized_plan_conflict'):
            first=operation(data,max_lines=None if case_id=='normal_replay' else 1)
            if case_id=='normal_replay':
                operation(data)
            elif case_id in ('revoked_replay','new_key_resume'):
                rotate()
                operation(data,signed(data,key_id='P1-new') if case_id=='new_key_resume' else None)
            else:
                changed=small_records();changed[1]['record']['amount']='5'
                operation(snapshot(changed));operation(data)
        elif case_id in ('precommit_kill','lost_ack','policy_race'):
            dp=folder/'worker-snapshot.jsonl';ep=folder/'worker-envelope.json'
            dp.write_bytes(data);ep.write_bytes(signed(data))
            before=sql_readback(store)
            barrier={'precommit_kill':'auth_before_commit','lost_ack':'auth_after_commit','policy_race':'auth_after_preflight'}[case_id]
            process=_worker(folder,folder/'evidence.sqlite3',dp,ep,barrier,rotate if case_id=='policy_race' else None)
            case['process']=process
            case['interrupted']={'before':before,'after':sql_readback(store),'snapshot':str(dp.relative_to(root)),'envelope':str(ep.relative_to(root))}
            if case_id!='policy_race':
                operation(data)
            else:
                result=next(o['result'] for o in process['observations'] if o['type']=='RESULT')
                case['operations'].append({'snapshot':str(dp.relative_to(root)),'envelope':str(ep.relative_to(root)),
                                           'before':before,'after':sql_readback(store),'result':result})
        elif case_id=='stale_policy':
            old=auth_status(store)['active_policy'];rotate()
            try:
                activate_policy(store,policy(),old['epoch'],old['policy_hash'])
            except ValueError as exc:
                case['stale_update']={'rejected':True,'reason':str(exc),'expected_epoch':old['epoch'],'expected_hash':old['policy_hash']}
            else:
                case['stale_update']={'rejected':False}
        elif case_id=='unsigned_paths':
            from ..admission.runtime import ingest_delivery
            from ..admission.feed import ingest_feed
            dp=folder/'unsigned.jsonl';dp.write_bytes(data)
            snap=snapshot_bytes(data);env=small_records()[0]
            calls={'store_ingest':lambda s:s.ingest(env['record'],env['received_at']),
                   'store_delivery':lambda s:s.ingest_delivery('legacy:one',1,snap.lines[0],snap.plan),
                   'module_delivery':lambda s:ingest_delivery(s,'legacy:two',1,snap.lines[0],snap.plan),
                   'feed':lambda s:ingest_feed(s,dp,'legacy:three')}
            case['unsigned']={}
            for name,call in calls.items():
                try: result=call(store)
                except ValueError as exc: result={'status':'DENIED','reason':str(exc)}
                case['unsigned'][name]=result
            legacy=Store(folder/'legacy.sqlite3',CONFIG)
            try:
                # Each path is exercised once; feed uses a single-line fresh file.
                dp.write_bytes(snap.lines[0])
                for call in calls.values():call(legacy)
                case['legacy_sql']=sql_readback(legacy)
            finally:legacy.close()
        else:
            env=signed(data)
            if case_id=='tampered_bytes':
                data=data.replace(b'"6"',b'"5"',1)
            elif case_id=='unsigned_hash':env=b'{}'
            elif case_id in ('unknown_key','wrong_key','bad_signature','duplicate_key'):
                value=json.loads(env)
                if case_id=='unknown_key':value['signatures'][0]['keyid']='unknown-test-key'
                elif case_id=='wrong_key':value['signatures'][0]['keyid']='C1-key'
                elif case_id=='bad_signature':value['signatures'][0]['sig']=base64.b64encode(b'\0'*64).decode()
                env=json.dumps(value).encode()
                if case_id=='duplicate_key':env=env.replace(b'{',b'{"payload":"duplicate",',1)
            elif case_id=='wrong_receiver':env=_claim(data,receiver='TEST-ONLY:other')
            elif case_id=='wrong_config':env=_claim(data,configuration_digest='0'*64)
            elif case_id=='wrong_namespace':env=_claim(data,stream='custodian-demo:sample')
            elif case_id=='scope_missing':env=_claim(data,caps=[])
            elif case_id=='scope_substitution':
                caps=capabilities(snapshot_bytes(data),CONFIG);caps[0]['asset']='ASSET_B';env=_claim(data,caps=caps)
            elif case_id=='malformed_type':env=_claim(data,source=['P1'])
            elif case_id in ('unicode_surrogate','authority_redirection'):
                records=small_records()[:1] if case_id=='unicode_surrogate' else [next(x for x in financial_records()['P1'] if x['record']['kind']=='event')]
                caps=capabilities(snapshot_bytes(snapshot(records)),CONFIG)
                if case_id=='unicode_surrogate':records[0]['record']['source']='\ud800'
                else:records[0]['record']['stream']='external_custody'
                data=snapshot(records);env=_claim(data,caps=caps)
            elif case_id in ('hijack_empty','hijack_populated'):
                if case_id=='hijack_populated':operation(data,max_lines=1)
                data=snapshot(financial_records()['C1'][:1]);env=signed(data,'platform-demo:sample','C1-key')
            operation(data,env)
        case['sql_final']=sql_readback(store)
        case['auth_status']=auth_status(store)
        return case
    finally:
        store.close()


def demo_source_auth(output,seed=19):
    """Run the fixed small inventory, retaining failures in the fresh output path."""
    from .crypto import require_crypto
    require_crypto()
    from .verifier import load_contract, derive_controls, verify_bundle, mutation_checks, rehash
    if type(seed) is not int or seed!=19:
        raise ValueError('source-auth demo uses the fixed declared seed 19')
    root=Path(output).resolve()
    if root.exists():
        raise ValueError('source-auth output must be fresh')
    root.mkdir(parents=True)
    contract=load_contract()
    report={'format':'source-auth-experiment-v1','seed':seed,'operator_anchor':operator_anchor(),
            'environment':{'import_origin':PACKAGE_ORIGIN,'python':sys.version,'executable':sys.executable,
                           'isolated':bool(sys.flags.isolated),'cwd':str(Path.cwd())},'cases':[],'status':'RUNNING'}
    try:
        for spec in contract['scenarios']:
            if spec['id']=='verifier_mutations':continue
            case=_case(root,spec['id'])
            actual=derive_controls(case,root)
            case['controls']={name:{'expected':expected,'actual':actual.get(name),'passed':type(expected) is type(actual.get(name)) and expected==actual[name]}
                              for name,expected in spec['required_controls'].items()}
            report['cases'].append(case)
            _write(root/'report.json',report)
        report['cases'].append({'id':'verifier_mutations','mutations':{},'controls':{}})
        report['status']='PASSED'
        _write(root/'report.json',report);rehash(root)
        mutations=mutation_checks(root)
        last=report['cases'][-1];last['mutations']=mutations
        last['controls']={name:{'expected':expected,'actual':mutations.get(name),'passed':mutations.get(name)==expected}
                          for name,expected in contract['scenarios'][-1]['required_controls'].items()}
        _write(root/'report.json',report);rehash(root)
        verified=verify_bundle(root,operator_anchor())
        _write(root/'verification.json',verified)
        lines=['# Source authorization experiment','','TEST-ONLY publishers; financial correctness is checked separately.','',
               '| Scenario | Required controls | Result |','|---|---:|---|']
        lines += [f"| {c['id']} | {len(c['controls'])} | {'PASS' if all(x['passed'] for x in c['controls'].values()) else 'FAIL'} |" for c in report['cases']]
        (root/'report.md').write_text('\n'.join(lines)+'\n')
        rehash(root)
        return report
    except Exception as exc:
        report['status']='FAILED';report['failure']={'type':type(exc).__name__,'reason':str(exc)}
        _write(root/'report.json',report)
        raise
