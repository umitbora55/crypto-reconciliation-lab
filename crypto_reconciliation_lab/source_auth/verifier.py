"""Independent, fixed-scope evidence reader. Hashes alone never authorize a source."""
import base64
import copy
import hashlib
from importlib.resources import files
import json
import math
import re
from pathlib import Path
import shutil
import tempfile

SCOPE_SHA256='f31284225f0a3247759f6dea75cebc6065ea4c2847ace3091af3095cbdc655e1'
PAYLOAD_TYPE='application/vnd.crypto-reconciliation.source-admission.v1+json'


def _fail(message):
    raise ValueError('SOURCE_AUTH_EVIDENCE: '+message)


def _same(a,b):
    return type(a) is type(b) and (all(k in b and _same(v,b[k]) for k,v in a.items()) and len(a)==len(b) if isinstance(a,dict)
        else len(a)==len(b) and all(_same(x,y) for x,y in zip(a,b)) if isinstance(a,list) else a==b)


def _hash(data):return hashlib.sha256(data).hexdigest()


def _canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()


def _json(data,limit=64*1024*1024):
    if type(data) is not bytes or not 0<len(data)<=limit:_fail('bounded JSON bytes required')
    def pairs(items):
        out={}
        for k,v in items:
            if k in out:_fail('duplicate JSON key')
            out[k]=v
        return out
    def invalid(_):_fail('nonfinite JSON')
    def floating(text):
        value=float(text)
        if not math.isfinite(value):_fail('nonfinite JSON number')
        return value
    try:
        value=json.loads(data.decode('utf-8'),object_pairs_hook=pairs,parse_constant=invalid,parse_float=floating)
    except (UnicodeError,RecursionError,json.JSONDecodeError):
        _fail('invalid UTF-8, JSON or excessive nesting')
    def walk(v,depth=0):
        if depth>32:_fail('deep JSON')
        if isinstance(v,str) and any(0xD800<=ord(c)<=0xDFFF for c in v):_fail('surrogate')
        if isinstance(v,dict):
            for k,child in v.items():walk(k,depth+1);walk(child,depth+1)
        elif isinstance(v,list):
            for child in v:walk(child,depth+1)
    walk(value)
    return value


def load_contract():
    data=files('crypto_reconciliation_lab.source_auth').joinpath('experiment_scope_v1.json').read_bytes()
    if _hash(data)!=SCOPE_SHA256:_fail('fixed scope resource changed')
    return _json(data)


def _path(root,name):
    if type(name) is not str or Path(name).is_absolute() or '..' in Path(name).parts:_fail('unsafe evidence path')
    path=root/name
    if path.is_symlink() or not path.is_file() or root not in path.resolve().parents:_fail('missing or nonlocal evidence file')
    return path


def _scope(data):
    """Independent authority-only table; no financial normalizer or calculator."""
    if not data or len(data)>16*1024*1024 or not data.endswith(b'\n') or b'\r' in data:_fail('snapshot framing')
    lines=data[:-1].split(b'\n')
    if len(lines)>10000 or any(not line or len(line)+1>65536 for line in lines):_fail('snapshot bounds')
    found=[]
    for line in lines:
        env=_json(line)
        if type(env) is not dict or set(env)!={'record','received_at'} or type(env['record']) is not dict:_fail('financial envelope')
        r=env['record'];kind=r.get('kind');source=r.get('source');asset=r.get('asset');platform=r.get('platform')
        if any(type(x) is not str for x in (kind,source,asset,platform)) or platform!='P1' or asset not in ('ASSET_A','ASSET_B'):_fail('ambiguous authority')
        allowed = {
            'opening': {'scope','balance_at','amount'},
            'event': {'business_day','ref','occurred_at','sequence','type','from_investor','to_investor','custody','amount'},
            'report': {'stream','scope','balance_at','version','amount'},
            'manifest': {'stream','coverage_from','coverage_to','expected_count'},
            'correction': {'batch_id','correction_id','target','target_occurred_at','mode','source_ref','reason','replacement_amount'},
            'correction_manifest': {'batch_id','coverage_from','coverage_to','expected_count'},
        }
        if kind not in allowed or not set(r)<=allowed[kind]|{'kind','source','platform','asset'}:_fail('forbidden authority field')
        channel='none'
        if kind in ('report','manifest'):
            channel=r.get('stream')
            channels={'report':{'investor','platform_custody','external_custody'},'manifest':{'opening','event','investor','platform_custody','external_custody'}}
            if type(channel) is not str or channel not in channels[kind]:_fail('ambiguous channel')
            owner='C1' if channel=='external_custody' else 'P1'
        elif kind in ('opening','event','correction','correction_manifest'):
            owner='P1'
            if kind=='event' and any(k in r for k in ('stream','balance_at')):_fail('event field redirection')
            if kind=='correction':
                target=r.get('target')
                if (type(target) is not dict or set(target)!={'kind','source','platform','business_day','ref'} or any(type(v) is not str for v in target.values()) or target['kind']!='event' or target['source']!=source or target['platform']!=platform):_fail('correction target authority')
        else:_fail('unknown kind')
        if source!=owner:_fail('wrong publisher')
        cap={'source':source,'platform':platform,'asset':asset,'kind':kind,'channel':channel}
        if cap not in found:found.append(cap)
    if len({c['source'] for c in found})!=1:_fail('multiple publishers')
    return sorted(found,key=lambda x:_canonical(x))


def _verified_claim(data,envelope,anchor):
    """Direct library verification with literal DSSE PAE, independent of admission."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    env=_json(envelope,128*1024)
    if type(env) is not dict or env.get('payloadType')!=PAYLOAD_TYPE:_fail('payload type')
    sigs=env.get('signatures')
    if type(sigs) is not list or len(sigs)!=1:_fail('signature inventory')
    kid=sigs[0].get('keyid')
    if kid not in anchor['keys']:_fail('key outside operator anchor')
    payload=base64.b64decode(env['payload'],validate=True)
    sig=base64.b64decode(sigs[0]['sig'],validate=True)
    ptype=PAYLOAD_TYPE.encode()
    pae=b'DSSEv1 '+str(len(ptype)).encode()+b' '+ptype+b' '+str(len(payload)).encode()+b' '+payload
    key=anchor['keys'][kid]
    Ed25519PublicKey.from_public_bytes(bytes.fromhex(key['public_key'])).verify(sig,pae)
    statement=_json(payload,64*1024)
    if set(statement)!={'format','source','receiver','configuration_digest','stream_id','plan','capabilities'}:_fail('statement fields')
    if statement['format']!='source-admission-statement-v1' or statement['source']!=key['source']:_fail('statement source')
    if statement['receiver']!=anchor['receiver'] or statement['configuration_digest']!=anchor['configuration_digest']:_fail('receiver/configuration binding')
    if type(statement['stream_id']) is not str or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}',statement['stream_id']) is None or not statement['stream_id'].startswith(anchor['namespaces'][key['source']]):_fail('source namespace')
    plan={'format':'admission-plan-v1','input_sha256':_hash(data),'input_bytes':len(data),'planned_lines':data.count(b'\n'),'framing':'utf8-lf-jsonl-v1'}
    if not _same(statement['plan'],plan):_fail('snapshot plan')
    actual=_scope(data)
    if any(c['source']!=statement['source'] for c in actual):_fail('snapshot publisher differs from signer')
    if sorted(statement['capabilities'],key=lambda x:_canonical(x))!=actual:_fail('exact derived scope')
    return {'statement':statement,'payload':payload,'key_id':kid,'fingerprint':key['fingerprint'],'snapshot':data,'envelope':envelope}



def _denial_input_condition(case,op,data,envelope,anchor):
    """Prove the declared negative stimulus, independently of reported DENIED."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    cid=case['id']
    negative={'tampered_bytes','unsigned_hash','unknown_key','wrong_key','bad_signature',
              'wrong_receiver','wrong_config','wrong_namespace','unauthorized_asset','unauthorized_kind',
              'unauthorized_channel','scope_missing','scope_substitution','cartesian_hole','malformed_type',
              'duplicate_key','unicode_surrogate','authority_redirection','hijack_empty','hijack_populated'}
    if cid not in negative or op is not case['operations'][-1]:
        return
    valid=False
    try:
        if cid=='duplicate_key':
            try:_json(envelope,128*1024)
            except ValueError as exc:valid='duplicate JSON key' in str(exc)
        elif cid=='unsigned_hash':
            value=_json(envelope,128*1024)
            valid=(type(value) is dict and 'signatures' not in value and bool(_scope(data)))
        else:
            env=_json(envelope,128*1024)
            sigs=env['signatures']
            if env['payloadType']!=PAYLOAD_TYPE or type(sigs) is not list or len(sigs)!=1:_fail('signature inventory')
            kid=sigs[0]['keyid'];signature=base64.b64decode(sigs[0]['sig'],validate=True)
            payload=base64.b64decode(env['payload'],validate=True);statement=_json(payload,64*1024)
            if set(statement)!={'format','source','receiver','configuration_digest','stream_id','plan','capabilities'} or statement['format']!='source-admission-statement-v1':_fail('statement shape')
            ptype=PAYLOAD_TYPE.encode()
            message=b'DSSEv1 '+str(len(ptype)).encode()+b' '+ptype+b' '+str(len(payload)).encode()+b' '+payload
            verified_keys=[]
            for key_id,key in anchor['keys'].items():
                try:Ed25519PublicKey.from_public_bytes(bytes.fromhex(key['public_key'])).verify(signature,message)
                except Exception:continue
                verified_keys.append(key_id)
            signed=(kid in verified_keys)
            # Invalid signature cases retain an otherwise coherent, authenticatable
            # statement; the selected key identity is independently inspected.
            claimed_source=statement['source']
            fields_ok=(statement['receiver']==anchor['receiver'] and statement['configuration_digest']==anchor['configuration_digest'])
            plan={'format':'admission-plan-v1','input_sha256':_hash(data),'input_bytes':len(data),'planned_lines':data.count(b'\n'),'framing':'utf8-lf-jsonl-v1'}
            plan_ok=_same(statement['plan'],plan)
            try:actual_scope=_scope(data);scope_error=None
            except ValueError as exc:actual_scope=None;scope_error=str(exc)
            declared=statement['capabilities']
            scope_equal=(type(declared) is list and actual_scope is not None and sorted(declared,key=_canonical)==actual_scope)
            source_ok=(kid in anchor['keys'] and type(claimed_source) is str and claimed_source==anchor['keys'][kid]['source'] and actual_scope is not None and all(c['source']==claimed_source for c in actual_scope))
            stream=statement['stream_id']
            namespace_ok=(source_ok and type(stream) is str and stream.startswith(anchor['namespaces'][claimed_source]))
            if cid=='unknown_key':
                valid=(kid not in anchor['keys'] and len(verified_keys)==1 and fields_ok and plan_ok and scope_equal and claimed_source==anchor['keys'][verified_keys[0]]['source'])
            elif cid=='wrong_key':
                valid=(kid in anchor['keys'] and not signed and len(verified_keys)==1 and fields_ok and plan_ok and scope_equal and claimed_source==anchor['keys'][verified_keys[0]]['source'] and anchor['keys'][kid]['source']!=claimed_source)
            elif cid=='bad_signature':
                valid=(not verified_keys and len(signature)==64 and source_ok and namespace_ok and fields_ok and plan_ok and scope_equal)
            elif cid=='tampered_bytes':
                valid=(signed and source_ok and namespace_ok and fields_ok and not plan_ok and scope_equal and statement['plan']['input_sha256']!=_hash(data))
            elif cid=='wrong_receiver':
                valid=(signed and source_ok and namespace_ok and plan_ok and scope_equal and statement['receiver']!=anchor['receiver'] and statement['configuration_digest']==anchor['configuration_digest'])
            elif cid=='wrong_config':
                valid=(signed and source_ok and namespace_ok and plan_ok and scope_equal and statement['receiver']==anchor['receiver'] and statement['configuration_digest']!=anchor['configuration_digest'])
            elif cid=='wrong_namespace':
                valid=(signed and source_ok and not namespace_ok and fields_ok and plan_ok and scope_equal)
            elif cid in ('hijack_empty','hijack_populated'):
                owners=op['before']['auth_streams'];existing=next((x for x in owners if x['stream_id']==stream),None)
                valid=(signed and source_ok and claimed_source=='C1' and type(stream) is str and stream.startswith(anchor['namespaces']['P1']) and fields_ok and plan_ok and scope_equal
                       and ((existing is None) if cid=='hijack_empty' else (existing is not None and existing['source']=='P1')))
            elif cid in ('scope_missing','scope_substitution'):
                from .fixtures import policy
                permitted=[c for p in policy()['sources'] for c in p['capabilities']]
                declared_valid=(type(declared) is list and all(c in permitted for c in declared) and len({_canonical(c) for c in declared})==len(declared))
                valid=(signed and source_ok and namespace_ok and fields_ok and plan_ok and actual_scope is not None and declared_valid and not scope_equal)
                if cid=='scope_missing':valid=valid and len(declared)<len(actual_scope) and all(c in actual_scope for c in declared)
                else:valid=valid and len(declared)==len(actual_scope)
            elif cid=='malformed_type':
                valid=(signed and type(claimed_source) is not str and fields_ok and plan_ok and scope_equal)
            elif cid=='unicode_surrogate':
                valid=(signed and fields_ok and plan_ok and scope_error is not None and 'surrogate' in scope_error)
            elif cid=='authority_redirection':
                records=[_json(line)['record'] for line in data.splitlines()]
                valid=(signed and fields_ok and plan_ok and scope_error is not None and any(r.get('kind')=='event' and ('stream' in r or 'balance_at' in r) for r in records))
            else:
                # These files are authentic, fully bound and well scoped. Their
                # independently fixed exact policy tuples deny the actual file.
                state=op['after'];epoch=max(state['auth_policy_activations'],key=lambda x:x['epoch'])
                p=_json(next(x['payload'] for x in state['auth_policy_snapshots'] if x['policy_hash']==epoch['policy_hash']).encode())
                grants=next(x['capabilities'] for x in p['sources'] if x['source']==claimed_source)
                denied=[c for c in actual_scope or [] if c not in grants]
                valid=(signed and source_ok and namespace_ok and fields_ok and plan_ok and scope_equal and bool(denied))
                if cid=='unauthorized_asset':valid=valid and any(c['asset']=='ASSET_B' for c in denied)
                elif cid=='unauthorized_kind':valid=valid and any(c['kind']=='opening' for c in denied)
                elif cid=='unauthorized_channel':valid=valid and any(c['channel']=='investor' for c in denied)
                elif cid=='cartesian_hole':valid=valid and any(c['asset']=='ASSET_A' and c['kind']=='event' for c in denied)
    except (KeyError,TypeError,ValueError,IndexError):
        valid=False
    if not valid:_fail('denial input condition not exercised: '+cid)


def _denial_policy_and_audit(op,data,envelope,claim):
    """Valid claims may be denied only by the actual effective tuple/key policy."""
    result=op['result']
    if result['status']!='DENIED':return
    state=op['after'];rejection=result.get('rejection')
    if not rejection or rejection.get('durable') is not True:_fail('denial audit absent')
    audit=next((r for r in state['auth_rejections'] if r['id']==rejection['audit_id']),None)
    request_hash=_hash(_canonical({'snapshot':{'prefix_sha256':_hash(data[:16*1024*1024+1]),'bytes':len(data)},'envelope':{'prefix_sha256':_hash(envelope[:128*1024+1]),'bytes':len(envelope)}}))
    if not audit or any(audit[k]!=rejection[k] for k in ('code','reason')) or audit['request_hash']!=request_hash:_fail('denial audit exact input binding')
    if claim is None:return
    current=max(state['auth_policy_activations'],key=lambda x:x['epoch'])
    policy=_json(next(r['payload'] for r in state['auth_policy_snapshots'] if r['policy_hash']==current['policy_hash']).encode())
    key=next(k for k in policy['keys'] if k['key_id']==claim['key_id'])
    source=next(s for s in policy['sources'] if s['source']==claim['statement']['source'])
    authorized=key['status']=='active' and all(c in source['capabilities'] for c in claim['statement']['capabilities'])
    if authorized:_fail('denial input condition contradicts active authorization')

def _rows(state,name):
    value=state.get(name)
    if type(value) is not list:_fail('missing SQL readback table '+name)
    return value


def _index(rows,key):
    out={r[key]:r for r in rows}
    if len(out)!=len(rows):_fail('duplicate SQL identity')
    return out


# Literal identities from the retained schema, independent of runtime/DDL imports.
_SQL_KEYS = {
    'records': (('id', str),), 'receipts': (('id', int),), 'runs': (('id', str),),
    'admission_streams': (('stream_id', str),),
    'delivery_effects': (('stream_id', str), ('sequence', int)),
    'delivery_attempts': (('id', int),),
    'auth_configuration': (('id', int),),
    'auth_policy_snapshots': (('policy_hash', str),),
    'auth_policy_activations': (('epoch', int),),
    'auth_keys': (('key_id', str),), 'auth_streams': (('stream_id', str),),
    'auth_endorsements': (('id', str),), 'auth_decisions': (('id', int),),
    'auth_delivery_links': (('stream_id', str), ('sequence', int)),
    'auth_attempt_links': (('attempt_id', int),), 'auth_rejections': (('id', int),),
}


def _typed_index(rows, fields, label):
    result = {}
    for row in rows:
        if type(row) is not dict:_fail('SQL row type '+label)
        values = []
        for key, kind in fields:
            value = row[key]
            if type(value) is not kind or (kind is int and value < 1) or (kind is str and not value):
                _fail('SQL identity type '+label+'/'+key)
            values.append(value)
        identity = tuple(values)
        if identity in result:_fail('duplicate SQL identity '+label)
        result[identity] = row
    return result


def _sql_inventory(state):
    result = {name: _typed_index(_rows(state, name), fields, name) for name, fields in _SQL_KEYS.items()}
    # SQLite integer foreign keys are integers, not JSON booleans that compare
    # equal to 0/1 in Python. Validate references as well as primary identities.
    integers = {'sequence','epoch','first_epoch','decision_id','attempt_id',
                'input_bytes','planned_lines'}
    nullable_integers = {'core_receipt_id','previous_epoch','effect_sequence'}
    references = {'auth_decisions':('epoch','sequence','endorsement_id','policy_hash'),
                  'auth_delivery_links':('decision_id','core_receipt_id'),
                  'auth_attempt_links':('decision_id',), 'auth_keys':('first_epoch',),
                  'auth_policy_activations':('previous_epoch','previous_hash','policy_hash'),
                  'delivery_effects':('core_receipt_id',),
                  'delivery_attempts':('sequence','effect_sequence','effect_stream_id','plan_hash'),
                  'admission_streams':('input_bytes','planned_lines')}
    for table, fields in references.items():
        for row in _rows(state,table):
            for field in fields:
                value = row[field]
                if value is None and field in nullable_integers | {'previous_hash','effect_stream_id'}:continue
                kind = int if field in integers | nullable_integers else str
                if type(value) is not kind or (kind is int and value < 1):_fail('SQL reference type '+table+'/'+field)
    for table, field, kind in (('auth_keys', 'fingerprint', str),
                              ('auth_delivery_links', 'decision_id', int),
                              ('delivery_effects', 'core_receipt_id', int)):
        rows = [r for r in _rows(state, table) if r[field] is not None]
        _typed_index(rows, ((field, kind),), table+'/'+field)
    return result


def _transition(before, after, additions=None):
    """A finite readback relation, not a database or financial replay engine."""
    left, right = _sql_inventory(before), _sql_inventory(after)
    delta = {}
    for table in _SQL_KEYS:
        for key, row in left[table].items():
            if key not in right[table] or not _same(row, right[table][key]):
                _fail('append-only readback changed '+table)
        delta[table] = {k:v for k,v in right[table].items() if k not in left[table]}
        if additions is not None and table not in additions and delta[table]:
            _fail('unexpected readback transition '+table)
    return delta


def _fields(actual, expected, label):
    if type(actual) is not dict or any(k not in actual or not _same(actual[k], v) for k,v in expected.items()):
        _fail(label)


def _operation_scope(cid, index, claim):
    # These are the already fixed experiment's operation kinds. Snapshot line
    # counts come from verified bytes, never the candidate response list.
    if cid in ('revoked_replay', 'new_key_resume', 'authorized_plan_conflict', 'hijack_populated') and index == 0:
        return 1, 'INCOMPLETE'
    if cid == 'revoked_replay':return 1, 'DENIED'
    if cid == 'authorized_plan_conflict':return 1, 'BLOCKED'
    if cid in ('valid_publishers', 'wrong_custody', 'invalid_amount', 'normal_replay', 'lost_ack', 'precommit_kill', 'new_key_resume'):
        if claim is None:_fail('required verified operation input')
        return claim['statement']['plan']['planned_lines'], 'COMPLETE'
    return 0, 'DENIED'


def _check_operation(op, cid, index, claim):
    before, after, result = op['before'], op['after'], op['result']
    delta = _transition(before, after)
    responses = result['responses']
    count, status = _operation_scope(cid, index, claim)
    if type(responses) is not list or len(responses) != count:_fail('required response inventory '+cid)
    _fields(result, {'format':'source-auth-admission-v1', 'status':status,
                     'financial_evaluation':'NOT_RUN'}, 'operation result contract')
    if status != 'DENIED' and result['rejection'] is not None:_fail('unexpected operation rejection')
    if claim is not None:
        s = claim['statement']
        _fields(result, {'source':s['source'], 'stream_id':s['stream_id'], 'plan':s['plan'],
                         'statement_hash':_hash(claim['payload']), 'snapshot_hash':_hash(claim['snapshot'])},
                'operation verified input binding')
    elif any(result[k] is not None for k in ('source','stream_id','plan','statement_hash','snapshot_hash')):
        _fail('invalid preflight claims an accepted binding')
    attempts = sorted(delta['delivery_attempts'].values(), key=lambda a:a['id'])
    if len(attempts) != count:_fail('response/attempt transition inventory')
    if len(delta['auth_decisions']) != count or len(delta['auth_attempt_links']) != count:
        _fail('operation decision/attempt inventory')
    if len(delta['auth_rejections']) != (1 if status == 'DENIED' else 0):_fail('operation rejection transition')
    if status == 'DENIED' and (result['rejection']['audit_id'],) not in delta['auth_rejections']:
        _fail('operation reused historical rejection')
    if any(delta[t] for t in ('auth_configuration','auth_keys','runs')):_fail('operation changed setup or evaluations')
    if cid != 'policy_race' and any(delta[t] for t in ('auth_policy_snapshots','auth_policy_activations')):
        _fail('operation changed policy')
    effects = {(r['stream_id'], r['sequence']):r for r in after['delivery_effects']}
    links = {(r['stream_id'], r['sequence']):r for r in after['auth_delivery_links']}
    decisions = _index(after['auth_decisions'], 'id')
    endorsements = _index(after['auth_endorsements'], 'id')
    attempt_links = _index(after['auth_attempt_links'], 'attempt_id')
    prior_effects = {(r['stream_id'], r['sequence']) for r in before['delivery_effects']}
    seen_effects = set(prior_effects)
    prior_attempts = list(before['delivery_attempts'])
    new_effects = set()
    for sequence, (response, attempt) in enumerate(zip(responses, attempts), 1):
        identity = (claim['statement']['stream_id'], sequence)
        line = claim['snapshot'].splitlines(keepends=True)[sequence-1]
        _fields(attempt, {'stream_id':identity[0], 'sequence':sequence, 'payload':line.hex(),
                          'payload_sha256':_hash(line), 'plan_hash':_hash(_canonical(claim['statement']['plan']))},
                'attempt differs from operation input')
        effect = effects.get(identity)
        outcome = attempt['outcome']
        old_blocked = any(a['stream_id']==identity[0] and a['outcome'] in ('PLAN_CONFLICT','TRANSPORT_CONFLICT') for a in prior_attempts)
        if old_blocked and outcome != 'BLOCKED':_fail('permanent block priority')
        if outcome == 'COMMITTED':
            if identity in seen_effects or effect is None:_fail('committed attempt effect transition')
            seen_effects.add(identity);new_effects.add(identity)
        elif outcome == 'REPLAY':
            if identity not in seen_effects or effect is None or effect['payload'] != line.hex():_fail('replay changed original effect')
        elif outcome not in ('BLOCKED','PLAN_CONFLICT','TRANSPORT_CONFLICT','GAP','OUT_OF_RANGE'):
            _fail('attempt outcome')
        if outcome == 'BLOCKED' and not old_blocked:_fail('block has no original conflict')
        prefix_sequences = sorted(seq for stream,seq in seen_effects if stream==identity[0])
        if prefix_sequences != list(range(1,len(prefix_sequences)+1)):_fail('noncontiguous effect prefix')
        prior_attempts.append(attempt)
        blocked = old_blocked or outcome in ('PLAN_CONFLICT','TRANSPORT_CONFLICT')
        core = _json(effect['core_result'].encode()) if effect and effect['core_result'] is not None else None
        _fields(attempt, {'effect_stream_id':identity[0] if effect else None,
                          'effect_sequence':sequence if effect else None}, 'attempt effect reference')
        _fields(response, {'format':'delivery-response-v1','stream_id':identity[0], 'sequence':sequence,
                           'attempt_id':attempt['id'], 'outcome':outcome, 'ack':outcome in ('COMMITTED','REPLAY'),
                           'durable':True, 'committed_prefix':len(prefix_sequences), 'blocked':blocked,
                           'reason':attempt['reason'], 'disposition':effect['disposition'] if effect else None,
                           'core_receipt_row_id':effect['core_receipt_id'] if effect else None, 'core_result':core},
                'response delivery/effect/receipt linkage')
        if sequence < count and response['ack'] is not True:_fail('responses continue after negative acknowledgement')
        decision = decisions[attempt_links[attempt['id']]['decision_id']]
        end = endorsements[decision['endorsement_id']]
        if end['envelope'] != claim['envelope'].hex() or end['payload'] != claim['payload'].hex():
            _fail('response decision belongs to another operation endorsement')
        epoch = max(r['epoch'] for r in after['auth_policy_activations'])
        if decision['epoch'] != epoch:_fail('response decision is not current operation policy')
        link = links.get(identity)
        _fields(response['authorization'], {'decision_id':decision['id'], 'decision':decision['decision'],
                'epoch':decision['epoch'], 'policy_hash':decision['policy_hash'], 'key_id':end['key_id'],
                'key_status':decision['current_key_status'], 'currently_authorized':decision['decision']=='CURRENT',
                'endorsement_id':end['id'], 'original_decision_id':link['decision_id'] if link else None},
                'response authorization linkage')
    used_endorsements = {(d['endorsement_id'],) for d in delta['auth_decisions'].values()}
    old_endorsements = {(d['id'],) for d in before['auth_endorsements']}
    if set(delta['auth_endorsements']) != used_endorsements-old_endorsements:_fail('unexplained operation endorsement')
    if {k[0] for k in delta['records']} != {r['record_id'] for r in delta['receipts'].values() if r['record_id'] is not None} - {r['id'] for r in before['records']}:
        _fail('unexplained operation normalized record')
    if set(delta['delivery_effects']) != new_effects or set(delta['auth_delivery_links']) != new_effects:
        _fail('operation effects not explained by responses')
    if {key[0] for key in delta['receipts']} != {effects[k]['core_receipt_id'] for k in new_effects if effects[k]['core_receipt_id'] is not None}:
        _fail('operation receipts not explained by effects')
    if status == 'BLOCKED' and (not responses or responses[-1]['blocked'] is not True or responses[-1]['ack'] is not False):
        _fail('blocked operation lacks blocking response')
    if status in ('COMPLETE','INCOMPLETE') and any(r['ack'] is not True for r in responses):
        _fail('successful operation has negative acknowledgement')


def _check_history(case):
    cid = case['id'];ops = case['operations'];final = case['sql_final']
    expected_ops = {'valid_publishers':2,'wrong_custody':2,'normal_replay':2,'revoked_replay':2,
                    'new_key_resume':2,'hijack_populated':2,'authorized_plan_conflict':3,
                    'unsigned_paths':0,'stale_policy':0}.get(cid, 1)
    if type(ops) is not list or len(ops) != expected_ops:_fail('fixed operation inventory')
    initial = case['interrupted']['before'] if 'interrupted' in case else (ops[0]['before'] if ops else final)
    setup = {'auth_configuration','auth_keys','auth_policy_activations','auth_policy_snapshots'}
    if any(_rows(initial,t) for t in _SQL_KEYS if t not in setup):_fail('fixed experiment contains invented prehistory')
    if len(initial['auth_policy_activations']) != (2 if cid=='stale_policy' else 1):_fail('initial policy history')
    for previous, current in zip(ops, ops[1:]):
        allowed = ('auth_policy_snapshots','auth_policy_activations') if cid in ('revoked_replay','new_key_resume') else ()
        _transition(previous['after'], current['before'], allowed)
    if 'interrupted' in case:
        item = case['interrupted'];interrupted_delta = _transition(item['before'], item['after'])
        if cid == 'precommit_kill' and any(interrupted_delta.values()):_fail('precommit kill retained uncommitted changes')
        if cid == 'lost_ack':
            for table in ('delivery_attempts','auth_decisions','auth_attempt_links','delivery_effects','auth_delivery_links','receipts'):
                if len(interrupted_delta[table]) != 1:_fail('lost ACK committed boundary inventory')
            attempt = next(iter(interrupted_delta['delivery_attempts'].values()))
            if attempt['outcome']!='COMMITTED' or attempt['sequence']!=1:_fail('lost ACK lacks original committed attempt')
            if interrupted_delta['auth_rejections'] or interrupted_delta['runs']:_fail('lost ACK invented side effect')
            for table in setup:
                if interrupted_delta[table]:_fail('lost ACK changed setup or policy')
            if set(interrupted_delta['records']) != {(r['record_id'],) for r in interrupted_delta['receipts'].values() if r['record_id'] is not None}:
                _fail('lost ACK unexplained normalized record')
            if set(interrupted_delta['auth_endorsements']) != {(d['endorsement_id'],) for d in interrupted_delta['auth_decisions'].values()}:
                _fail('lost ACK unexplained endorsement')
            streams = {(stream,) for stream,sequence in interrupted_delta['delivery_effects']}
            if set(interrupted_delta['admission_streams']) != streams or set(interrupted_delta['auth_streams']) != streams:
                _fail('lost ACK unexplained stream')
        if cid == 'policy_race':
            _transition(item['before'],ops[0]['before'],());_transition(ops[0]['before'],item['before'],())
            _transition(item['after'],ops[0]['after'],());_transition(ops[0]['after'],item['after'],())
            if item['snapshot']!=ops[0]['snapshot'] or item['envelope']!=ops[0]['envelope']:_fail('worker operation input')
        else:
            _transition(item['after'],ops[0]['before'],());_transition(ops[0]['before'],item['after'],())
    if ops:_transition(ops[-1]['after'],final,('runs',) if cid in ('valid_publishers','wrong_custody') else ())
    status = case['auth_status'];tables = status['tables']
    for name in _SQL_KEYS:
        if name.startswith('auth_'):
            left = _typed_index(_rows(tables,name),_SQL_KEYS[name],name)
            right = _typed_index(_rows(final,name),_SQL_KEYS[name],name)
            if not _same(left,right):_fail('auth status/readback disagreement')
    _fields(status,{'format':'source-auth-status-v1','protected':final['auth_configuration'][0]},'auth status protection')
    active = max(final['auth_policy_activations'],key=lambda r:r['epoch'])
    payload = _json(next(r['payload'] for r in final['auth_policy_snapshots'] if r['policy_hash']==active['policy_hash']).encode())
    _fields(status['active_policy'],{**active,'payload':payload},'auth status active policy')


def _normalized_policy(value):
    value=copy.deepcopy(value)
    value['keys']=sorted(value['keys'],key=lambda k:k['key_id'])
    for source in value['sources']:
        source['capabilities']=sorted(source['capabilities'],key=_canonical)
    value['sources']=sorted(value['sources'],key=lambda s:s['source'])
    return value


def _expected_policy(case_id,rotated=False):
    # Fixed operator fixture, not report-supplied authority or runtime normalization.
    from .fixtures import policy
    value=policy(rotated)
    grants=value['sources'][0]['capabilities']
    if case_id=='unauthorized_asset':grants=[c for c in grants if c['asset']=='ASSET_A']
    elif case_id=='unauthorized_kind':grants=[c for c in grants if c['kind']!='opening']
    elif case_id=='unauthorized_channel':grants=[c for c in grants if c['channel']!='investor']
    elif case_id=='cartesian_hole':grants=[c for c in grants if (c['asset'],c['kind']) in (('ASSET_A','opening'),('ASSET_B','event'))]
    value['sources'][0]['capabilities']=grants
    return _normalized_policy(value)


def _check_sql(state,claims,anchor,case_id):
    _sql_inventory(state)
    receipts=_index(_rows(state,'receipts'),'id')
    effects={(r['stream_id'],r['sequence']):r for r in _rows(state,'delivery_effects')}
    links={(r['stream_id'],r['sequence']):r for r in _rows(state,'auth_delivery_links')}
    decisions=_index(_rows(state,'auth_decisions'),'id')
    endorsements=_index(_rows(state,'auth_endorsements'),'id')
    policies=_index(_rows(state,'auth_policy_snapshots'),'policy_hash')
    epochs=_index(_rows(state,'auth_policy_activations'),'epoch')
    keys=_index(_rows(state,'auth_keys'),'key_id')
    owners=_index(_rows(state,'auth_streams'),'stream_id')
    streams=_index(_rows(state,'admission_streams'),'stream_id')
    attempts=_index(_rows(state,'delivery_attempts'),'id')
    if set(effects)!=set(links) or set(owners)!=set(streams):_fail('every effect/stream needs immutable authorization linkage')
    if set(epochs)!=set(range(1,len(epochs)+1)):_fail('policy epoch gap')
    protected=_rows(state,'auth_configuration')
    if len(protected)!=1 or protected[0]['id']!=1 or protected[0]['receiver']!=anchor['receiver'] or protected[0]['configuration_digest']!=anchor['configuration_digest']:_fail('protected binding')
    if not epochs or protected[0]['initial_policy_hash']!=epochs[1]['policy_hash']:_fail('initial policy binding')
    previous_keys={}
    for epoch,row in sorted(epochs.items()):
        if row['policy_hash'] not in policies:_fail('activation without policy')
        p=_json(policies[row['policy_hash']]['payload'].encode())
        if not _same(p,_expected_policy(case_id,epoch>1)):_fail('policy differs from independent case fixture')
        if epoch>2 or (epoch==2 and case_id not in ('revoked_replay','new_key_resume','policy_race','stale_policy')):_fail('unexpected policy epoch')
        current_keys={k['key_id']:k for k in p['keys']}
        for kid,old in previous_keys.items():
            new=current_keys.get(kid)
            if not new or any(old[k]!=new[k] for k in ('public_key','fingerprint','source')) or (old['status']=='revoked' and new['status']!='revoked'):_fail('historical key identity/revocation')
        previous_keys=current_keys
        previous=epochs.get(epoch-1)
        if row['previous_epoch']!=(epoch-1 if previous else None) or row['previous_hash']!=(previous['policy_hash'] if previous else None):_fail('policy activation chain')
    for ph,row in policies.items():
        p=_json(row['payload'].encode())
        if _hash(_canonical(p))!=ph or p['receiver']!=anchor['receiver'] or p['configuration_digest']!=anchor['configuration_digest']:_fail('policy identity')
        for key in p['keys']:
            fixed=anchor['keys'].get(key['key_id'])
            if not fixed or any(key[k]!=fixed[k] for k in ('source','public_key','fingerprint')):_fail('policy outside operator key anchor')
        for source in p['sources']:
            if anchor['namespaces'].get(source['source'])!=source['namespace']:_fail('policy namespace anchor')
    for kid,key in keys.items():
        fixed=anchor['keys'].get(kid)
        if not fixed or any(key[k]!=fixed[k] for k in ('source','public_key','fingerprint')) or key['first_epoch']!=1:_fail('historical key anchor')
    for eid,end in endorsements.items():
        matching=[c for c in claims if c['envelope'].hex()==end['envelope'] and c['payload'].hex()==end['payload']]
        if not matching:_fail('endorsement lacks independently verified exact input')
        c=matching[0];s=c['statement']
        envelope_value=_json(c['envelope'],128*1024)
        signature=base64.b64decode(envelope_value['signatures'][0]['sig'],validate=True)
        expected_id=_hash(_canonical({'payload_sha256':_hash(c['payload']),'signature':signature.hex(),'fingerprint':c['fingerprint'],'key_id':c['key_id']}))
        if eid!=expected_id:_fail('endorsement identity')
        for name,want in (('source',s['source']),('key_id',c['key_id']),('fingerprint',c['fingerprint']),('statement_hash',_hash(c['payload'])),('snapshot_hash',_hash(c['snapshot'])),('plan_hash',_hash(_canonical(s['plan'])))):
            if end[name]!=want:_fail('endorsement '+name+' mismatch')
    for did,d in decisions.items():
        if d['epoch'] not in epochs or epochs[d['epoch']]['policy_hash']!=d['policy_hash'] or d['endorsement_id'] not in endorsements:_fail('decision policy/endorsement link')
        e=endorsements[d['endorsement_id']];p=_json(policies[d['policy_hash']]['payload'].encode())
        key=next((k for k in p['keys'] if k['key_id']==e['key_id']),None)
        s=_json(bytes.fromhex(e['payload']))
        grants=next((x for x in p['sources'] if x['source']==e['source']),None)
        if d['stream_id']!=s['stream_id'] or type(d['sequence']) is not int or not 1<=d['sequence']<=s['plan']['planned_lines']:_fail('decision statement stream/sequence')
        if not key or not grants or d['current_key_status']!=key['status']:_fail('decision key state')
        if d['decision']=='CURRENT' and (key['status']!='active' or any(c not in grants['capabilities'] for c in s['capabilities'])):_fail('unauthorized current decision')
        if d['decision'] not in ('CURRENT','HISTORICAL_REPLAY'):_fail('decision kind')
        if d['decision']=='HISTORICAL_REPLAY':
            original_link=links.get((d['stream_id'],d['sequence']))
            original=decisions.get(original_link['decision_id']) if original_link else None
            if (key['status']!='revoked' or not original or original['id']>=did or original['epoch']>=d['epoch']
                    or original['decision']!='CURRENT' or original['endorsement_id']!=d['endorsement_id']):_fail('historical replay lacks exact original approval')
            identity=(d['stream_id'],d['sequence'])
            if identity not in effects or effects[identity]['core_receipt_id']!=original_link['core_receipt_id']:_fail('historical replay lacks original effect')
    for identity,e in effects.items():
        link=links[identity];d=decisions.get(link['decision_id'])
        if not d or (d['stream_id'],d['sequence'])!=identity or d['decision']!='CURRENT':_fail('new effect lacks original current decision')
        end=endorsements[d['endorsement_id']];s=_json(bytes.fromhex(end['payload']))
        owner=owners.get(identity[0]);core_id=e.get('core_receipt_id')
        if not owner or any(owner[k]!=s[k] for k in ('source','receiver','configuration_digest')) or owner['plan_hash']!=end['plan_hash']:_fail('stream owner linkage')
        _fields(streams[identity[0]], {**{k:s['plan'][k] for k in ('input_sha256','input_bytes','planned_lines','framing')},
                                      'plan_hash':end['plan_hash']}, 'stream original signed plan')
        if link['core_receipt_id']!=core_id or core_id not in receipts:_fail('core receipt link')
        claim=next(c for c in claims if c['envelope'].hex()==end['envelope'])
        line=claim['snapshot'].splitlines(keepends=True)[identity[1]-1]
        if e['payload']!=line.hex() or e['payload_sha256']!=_hash(line):_fail('effect line membership')
        env=_json(line);r=receipts[core_id]
        if _json(r['raw'].encode())!=env or r['receipt_hash']!=_hash(_canonical(env)):_fail('receipt raw/hash linkage')
        core=_json(e['core_result'].encode())
        if core['receipt_id']!=r['receipt_hash'] or core['record_id']!=r['record_id'] or core['status']!=r['status'] or not _same(core['error'],r['error']) or r['received_at']!=env['received_at'] or e['core_receipt_hash']!=r['receipt_hash'] or e['disposition']!=r['status']:_fail('effect core result linkage')
        if r['record_id'] is not None:
            record=next((x for x in state['records'] if x['id']==r['record_id']),None)
            if record is None or _hash(_canonical(_json(record['payload'].encode())))!=record['id']:_fail('normalized record identity')
    if set(receipts)!={e['core_receipt_id'] for e in effects.values()}:_fail('unbound protected core receipt')
    attempt_links=_rows(state,'auth_attempt_links')
    if {l['attempt_id'] for l in attempt_links}!=set(attempts) or {l['decision_id'] for l in attempt_links}!=set(decisions) or len(attempt_links)!=len(attempts) or len(attempt_links)!=len(decisions):_fail('complete one-to-one attempt decision links')
    last_epoch=0
    for l in sorted(attempt_links,key=lambda x:x['attempt_id']):
        if l['attempt_id'] not in attempts or l['decision_id'] not in decisions:_fail('attempt decision link')
        a=attempts[l['attempt_id']];d=decisions[l['decision_id']]
        end=endorsements[d['endorsement_id']]
        claim=next(c for c in claims if c['envelope'].hex()==end['envelope'])
        identity=(d['stream_id'],d['sequence']);effect=effects.get(identity)
        line=claim['snapshot'].splitlines(keepends=True)[d['sequence']-1]
        _fields(a,{'payload':line.hex(),'payload_sha256':_hash(line),'plan_hash':end['plan_hash'],
                   'effect_stream_id':identity[0] if effect else None,'effect_sequence':identity[1] if effect else None},
                'SQL attempt exact signed input/effect linkage')
        if (a['stream_id'],a['sequence'])!=(d['stream_id'],d['sequence']) or d['epoch']<last_epoch:_fail('attempt identity/policy order')
        last_epoch=d['epoch']
        if d['decision']=='HISTORICAL_REPLAY' and a['outcome'] not in ('REPLAY','BLOCKED'):_fail('historical approval created new transport effect')
        if a['outcome']=='COMMITTED' and links[(a['stream_id'],a['sequence'])]['decision_id']!=d['id']:_fail('committed attempt original decision')


def _financial(case,root):
    result=_json(_path(root,case['financial']).read_bytes())
    reference=load_contract()['financial_reference']
    if result.get('rule_version')!='stage2-v2':_fail('financial rule')
    for asset,ref in reference.items():
        ledger=result['ledgers'][asset]
        if ledger['investor_balances']!={'I1':ref['I1'],'I2':ref['I2']} or ledger['liability']!=ref['liability'] or ledger['custody_rollforward']!={'platform':ref['platform'],'external':ref['external']}:_fail('literal financial roll-forward')
    saved=case['sql_final']['runs']
    if len(saved)!=1 or saved[0]['id']!=result['run_id'] or {**_json(saved[0]['payload'].encode()),'run_id':saved[0]['id']}!=result:_fail('financial report differs from saved run')
    if _hash(_canonical(_json(saved[0]['payload'].encode())))!=saved[0]['id']:_fail('saved financial run identity')
    if saved[0]['balance_at']!='2026-11-10T23:59:59.000000Z' or saved[0]['knowledge_at']!='2026-11-11T01:00:00.000000Z':_fail('financial cut')
    reports=[_json(r['raw'].encode())['record'] for r in case['sql_final']['receipts']]
    custody=[r for r in reports if r['kind']=='report' and r['source']=='C1' and r['asset']=='ASSET_A' and r['stream']=='external_custody']
    if len(custody)!=1 or custody[0]['amount']!=('8' if case['id']=='wrong_custody' else '9'):_fail('signed custody input amount')
    findings=result['findings']
    identities={(r['asset'],r['comparison'],r['scope']) for r in findings}
    required={(a,c,s) for a in ('ASSET_A','ASSET_B') for c,s in (('A','I1'),('A','I2'),('B','customer_liability'))}
    if len(findings)!=6 or identities!=required:_fail('financial finding scope')
    wrong=case['id']=='wrong_custody'
    for row in findings:
        mismatch=wrong and row['asset']=='ASSET_A' and row['comparison']=='B'
        expected=reference[row['asset']]['liability' if row['comparison']=='B' else row['scope']]
        if row['expected']!=expected or row['reported']!=('10' if mismatch else expected):_fail('literal expected/reported quantities')
        if row['data_state']!='COMPLETE' or row['reconciliation_state']!=('MISMATCH' if mismatch else 'MATCHED') or row['difference']!=('1' if mismatch else '0'):_fail('literal signed financial outcome')
    return result


def derive_controls(case,root):
    """Observed values only; expected values live exclusively in the fixed scope."""
    cid=case['id'];state=case.get('sql_final',{});ops=case.get('operations',[])
    receipts=len(state.get('receipts',[]));out={'receipts':receipts}
    if cid in ('valid_publishers','wrong_custody'):
        r=_financial(case,root);out['financial']='MISMATCH' if any(x['reconciliation_state']=='MISMATCH' for x in r['findings']) else 'MATCHED'
        if cid=='wrong_custody':
            out['custody_difference']=next(x['difference'] for x in r['findings'] if x['comparison']=='B' and x['asset']=='ASSET_A')
            out['investors']='MATCHED' if all(x['reconciliation_state']=='MATCHED' for x in r['findings'] if x['comparison']=='A') else 'MISMATCH'
        else:
            a=_path(root,case['financial']);b=_path(root,case['legacy_financial'])
            out['paired_financial_identity']=(a.read_bytes()==b.read_bytes() and a.with_suffix('.md').read_bytes()==b.with_suffix('.md').read_bytes()
                and all(_same(_typed_index(case['sql_final'][table],_SQL_KEYS[table],table),_typed_index(case['legacy_sql'][table],_SQL_KEYS[table],table)) for table in ('records','receipts','runs')))
    elif cid=='invalid_amount':
        out.update(status=ops[0]['result']['status'],core_status=state['receipts'][0]['status'])
    elif cid=='unsigned_paths':
        out.update({k:v.get('status') for k,v in case['unsigned'].items()});out['legacy_receipts']=len(case['legacy_sql']['receipts'])
    elif cid=='normal_replay':
        responses=ops[-1]['result']['responses'];out['outcome']=responses[0]['outcome']
        out['same_receipts']=[r['core_receipt_row_id'] for r in responses]==[r['core_receipt_row_id'] for r in ops[0]['result']['responses']]
    elif cid in ('lost_ack','precommit_kill','policy_race'):
        p=case['process'];out.update(barrier=next(o['point'] for o in p['observations'] if o['type']=='BARRIER'),exit=p['exit'])
        if cid=='policy_race':out.update(status=ops[0]['result']['status'],active_epoch=case['auth_status']['active_policy']['epoch'])
        else:
            out['before_retry_receipts']=len(case['interrupted']['after']['receipts'])
            if cid=='precommit_kill':out['before_retry_decisions']=len(case['interrupted']['after']['auth_decisions'])
            else:out['retry_outcome']=ops[-1]['result']['responses'][0]['outcome']
    elif cid=='revoked_replay':
        response=ops[-1]['result']['responses'][0];auth=response['authorization']
        out.update(prefix_receipts=len(ops[0]['after']['receipts']),replayed=auth['decision'],currently_authorized=auth['currently_authorized'],suffix=ops[-1]['result']['status'])
    elif cid=='new_key_resume':
        links=sorted(state['auth_delivery_links'],key=lambda r:(r['stream_id'],r['sequence']));decisions={d['id']:d for d in state['auth_decisions']}
        out.update(old_epoch=decisions[links[0]['decision_id']]['epoch'],new_epoch=decisions[links[1]['decision_id']]['epoch'],
                   old_evidence_preserved=all(row in state[table] for table in ('receipts','auth_decisions','auth_endorsements','auth_delivery_links') for row in ops[0]['after'][table]))
    elif cid=='stale_policy':out.update(rejected=case['stale_update']['rejected'],active_epoch=case['auth_status']['active_policy']['epoch'])
    elif cid=='authorized_plan_conflict':
        out.update(outcome=ops[1]['result']['responses'][0]['outcome'],replay=ops[2]['result']['responses'][0]['outcome'],
                   original_readable=_same(_index(ops[0]['after']['receipts'],'id'),_index(state['receipts'],'id')))
    elif cid=='verifier_mutations':out=case['mutations']
    else:
        op=ops[-1];before=op['before'];after=op['after']
        blocking=lambda s:len([a for a in s['delivery_attempts'] if a['outcome'] in ('PLAN_CONFLICT','TRANSPORT_CONFLICT','BLOCKED')])
        out={'status':op['result']['status'],'new_receipts':len(after['receipts'])-len(before['receipts']),
             'new_effects':len(after['delivery_effects'])-len(before['delivery_effects']),
             'new_owners':len(after['auth_streams'])-len(before['auth_streams']),
             'new_blocking_attempts':blocking(after)-blocking(before)}
    return out


def rehash(root):
    root=Path(root)
    members={str(p.relative_to(root)):{'sha256':_hash(p.read_bytes()),'bytes':p.stat().st_size}
             for p in sorted(root.rglob('*')) if p.is_file() and p.name!='manifest.json' and p.suffix not in ('.sqlite3','.db') and not p.name.endswith(('-journal','-wal','-shm'))}
    (root/'manifest.json').write_text(json.dumps({'format':'source-auth-file-manifest-v1','files':members},sort_keys=True,indent=2)+'\n')


def _verify(root,anchor,mutation_phase=False):
    root=Path(root).resolve()
    contract=load_contract();report=_json(_path(root,'report.json').read_bytes())
    if report.get('format')!='source-auth-experiment-v1' or report.get('seed')!=19 or report.get('status')!='PASSED':_fail('experiment header')
    if not _same(report.get('operator_anchor'),anchor):_fail('operator anchor mismatch')
    manifest=_json(_path(root,'manifest.json').read_bytes())
    for name,row in manifest['files'].items():
        data=_path(root,name).read_bytes()
        if row!={'sha256':_hash(data),'bytes':len(data)}:_fail('file bytes differ')
    cases=report.get('cases')
    if type(cases) is not list:_fail('case inventory')
    case_map={c['id']:c for c in cases}
    if len(case_map)!=len(cases):_fail('duplicate case')
    for spec in contract['scenarios']:
        cid=spec['id']
        if cid not in case_map:_fail('missing required scenario '+cid)
        if mutation_phase and cid=='verifier_mutations':continue
        case=case_map[cid]
        for field in spec['required_evidence']:
            if field not in case:_fail('required evidence '+field)
        actual=derive_controls(case,root)
        for name,expected in spec['required_controls'].items():
            ctrl=case.get('controls',{}).get(name)
            if not ctrl or not _same(ctrl.get('expected'),expected) or not _same(ctrl.get('actual'),actual.get(name)) or not _same(actual.get(name),expected) or ctrl.get('passed') is not True:_fail('semantic control '+cid+'/'+name)
        if cid=='verifier_mutations':
            if set(case['mutations'])<set(contract['required_mutations']):_fail('mutation coverage')
            continue
        if not _same(_normalized_policy(case['initial_policy']),_expected_policy(cid)):_fail('operator case setup policy differs')
        claims=[];operation_claims=[]
        for op in case['operations']:
            data=_path(root,op['snapshot']).read_bytes();envelope=_path(root,op['envelope']).read_bytes()
            _denial_input_condition(case,op,data,envelope,anchor)
            claim=None
            try:claim=_verified_claim(data,envelope,anchor)
            except Exception:
                if op['result']['status']!='DENIED':_fail('non-denial for independently invalid claim')
            else:
                claims.append(claim)
                if op['result']['status'] not in ('COMPLETE','INCOMPLETE','DENIED','BLOCKED'):_fail('operation status')
            _denial_policy_and_audit(op,data,envelope,claim)
            operation_claims.append(claim)
        if 'interrupted' in case:
            item=case['interrupted'];claims.append(_verified_claim(_path(root,item['snapshot']).read_bytes(),_path(root,item['envelope']).read_bytes(),anchor))
        _check_sql(case['sql_final'],claims,anchor,cid)
        _check_history(case)
        for index,(op,claim) in enumerate(zip(case['operations'],operation_claims)):
            _check_sql(op['before'],claims,anchor,cid)
            _check_sql(op['after'],claims,anchor,cid)
            _check_operation(op,cid,index,claim)
        if 'process' in case:
            p=case['process'];obs=p['observations']
            if type(p['pid']) is not int or p['pid']<=0 or p['joined'] is not True or any(o['pid']!=p['pid'] for o in obs):_fail('process identity/join')
            if [o['type'] for o in obs[:2]]!=['READY','BARRIER'] or obs[1]['point']!=p['requested_barrier']:_fail('named process barrier')
            if cid!='policy_race' and (p['signal']!='SIGKILL' or p['exit']!=-9 or p['sender']!='UNKNOWN' or any(o['type']=='RESULT' for o in obs)):_fail('process kill/unknown response')
            if cid=='policy_race' and (p['signal'] is not None or p['exit']!=0 or len([o for o in obs if o['type']=='RESULT'])!=1):_fail('policy race response')
            if cid=='policy_race' and not _same(next(o['result'] for o in obs if o['type']=='RESULT'),case['operations'][0]['result']):_fail('worker RESULT differs from operation')
            _check_sql(case['interrupted']['before'],claims,anchor,cid)
            _check_sql(case['interrupted']['after'],claims,anchor,cid)
    return {'format':'source-auth-verification-v1','status':'PASSED','families':len(contract['families']),
            'scenarios':len(contract['scenarios']),'scope_sha256':SCOPE_SHA256,
            'anchor':'explicit operator-selected TEST-ONLY fixture','integrity_is_source_certification':False}


def verify_bundle(bundle_path,operator_anchor=None):
    from .fixtures import operator_anchor as fixed_anchor
    anchor=fixed_anchor() if operator_anchor is None else operator_anchor
    try:return _verify(Path(bundle_path).resolve(),anchor)
    except (KeyError,TypeError,IndexError,UnicodeError,json.JSONDecodeError) as exc:
        _fail('malformed required evidence: '+type(exc).__name__)


def mutation_checks(root):
    """Actual semantic rejection runs, each with a newly consistent byte manifest."""
    from .fixtures import operator_anchor,TEST_KEYS
    from .crypto import sign_statement
    root=Path(root);out={}
    def change(path,name):
        report=json.loads((path/'report.json').read_text());cases={c['id']:c for c in report['cases']}
        if name=='missing_family':report['cases']=[c for c in report['cases'] if c['id']!='wrong_custody']
        elif name=='missing_decision_and_reference':
            case=cases['valid_publishers']
            for state in [case['sql_final']]+[x['after'] for x in case['operations']]:
                if state['auth_decisions']:
                    did=state['auth_decisions'][0]['id'];state['auth_decisions']=[r for r in state['auth_decisions'] if r['id']!=did]
                    state['auth_delivery_links']=[r for r in state['auth_delivery_links'] if r['decision_id']!=did]
                    state['auth_attempt_links']=[r for r in state['auth_attempt_links'] if r['decision_id']!=did]
            for op in case['operations']:
                for r in op['result']['responses']:
                    if r.get('authorization',{}).get('decision_id')==1:r.pop('authorization')
        elif name=='same_count_scope':
            target=path/cases['valid_publishers']['operations'][0]['envelope'];env=json.loads(target.read_text());s=json.loads(base64.b64decode(env['payload']))
            s['capabilities'][0]={'source':'P1','platform':'P1','asset':'ASSET_A','kind':'correction','channel':'none'}
            target.write_bytes(sign_statement(s,bytes.fromhex(TEST_KEYS['P1-old'][0]),'P1-old'))
        elif name=='wrong_key_source_receipt':cases['valid_publishers']['sql_final']['auth_delivery_links'][0]['core_receipt_id']=2
        elif name=='false_pass':cases['bad_signature']['controls']['status'].update(actual='COMMITTED',passed=True)
        elif name=='false_financial_match':
            target=path/cases['wrong_custody']['financial'];value=json.loads(target.read_text())
            for row in value['findings']:
                if row['asset']=='ASSET_A' and row['comparison']=='B':row['reconciliation_state']='MATCHED';row['difference']='0'
            target.write_text(json.dumps(value))
        elif name=='extra_information':report['extra:operator_note']='Harmless explanatory information.'
        (path/'report.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n');rehash(path)
    for name in load_contract()['required_mutations']:
        with tempfile.TemporaryDirectory(prefix='source-auth-mutation-') as temp:
            target=Path(temp)/'bundle'
            shutil.copytree(root,target,ignore=shutil.ignore_patterns('*.sqlite3','*-journal'))
            change(target,name)
            try:_verify(target,operator_anchor(),mutation_phase=True)
            except (ValueError,KeyError,TypeError,IndexError):out[name]='REJECTED'
            else:out[name]='ACCEPTED'
    return out
