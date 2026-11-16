"""Gate2 finite identity-reference research; no institutional authority claim.

An optional independent-input channel is emulated with publicly reproducible LAB
Ed25519 keys. The channel is not independent of this test generator. This code
never changes the financial engine, its baseline labels or historical evidence.
"""
from __future__ import annotations
import argparse
import base64
import copy
import hashlib
import json
import math
import platform
import random
import re
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'contracts/identity-reference-research-v1.json'
CONTRACT_SHA256 = 'afcfb98aaed43130ce6bdb3ce899c96a8799a55d1a88e44107a0fc7418cfeae6'
DOMAIN = b'identity-reference-research-v1\x00'
MAX_BYTES = 131072
MAX_ENTRIES = 128
MAX_INTEGER = 2**63 - 1
SCOPE_FIELDS = {'publisher','dataset','partition','event_day','balance_cut','record_kind'}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')


class ReferenceError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ReferenceError(message)


def strict_reference_json(raw):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, 'REFERENCE_SIZE')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'DUPLICATE_KEY')
            result[key] = value
        return result
    def invalid(_):
        raise ReferenceError('NONFINITE_NUMBER')
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ReferenceError('REFERENCE_JSON') from exc
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        require(depth <= 16, 'REFERENCE_DEPTH')
        if isinstance(item, str):
            require(not any(0xD800 <= ord(c) <= 0xDFFF for c in item), 'REFERENCE_UNICODE')
        elif type(item) is dict:
            stack.extend((child, depth+1) for pair in item.items() for child in pair)
        elif type(item) is list:
            stack.extend((child, depth+1) for child in item)
        elif type(item) is float:
            require(math.isfinite(item), 'NONFINITE_NUMBER')
    return value


def uint_text(value):
    require(type(value) is str and re.fullmatch(r'[1-9][0-9]{0,18}', value) is not None, 'INTEGER_TEXT')
    require(int(value) <= MAX_INTEGER, 'INTEGER_BOUND')
    return int(value)


def digest_text(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


@dataclass(frozen=True)
class TrustContext:
    origin: str
    scope: dict
    revision: str
    previous_sha256: str | None
    manifest_sha256: str
    epoch: str
    key_id: str
    public_key_hex: str
    revoked_key_ids: tuple[str, ...] = ()


def lab_private_key(number):
    """Public, deterministic test material; NEVER a production secret or authority."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return Ed25519PrivateKey.from_private_bytes(sha(f'PUBLIC_LAB_ONLY_IDENTITY_KEY_{number}'.encode()).encode()[:32])


def public_hex(number):
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    return lab_private_key(number).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


def make_manifest(events, scope, revision='1', previous=None, epoch='1'):
    return {'format': 'identity-reference-research-v1', 'scope': copy.deepcopy(scope),
            'revision': revision, 'previous_sha256': previous, 'key_epoch': epoch,
            'entries': [{'position': str(i), 'event_id': event['event_id'],
                         'content_sha256': sha(event['content'])} for i, event in enumerate(events, 1)]}


def sign_manifest(manifest, key_number=1, key_id='LAB-KEY-1'):
    signature = lab_private_key(key_number).sign(DOMAIN + canonical(manifest))
    return canonical({'manifest': manifest, 'signatures': [{'key_id': key_id,
                       'signature': base64.b64encode(signature).decode('ascii')}]})


def context_for(manifest, key_number=1, key_id='LAB-KEY-1'):
    return TrustContext('LAB_TEST_ONLY', copy.deepcopy(manifest['scope']), manifest['revision'],
                        manifest['previous_sha256'], sha(canonical(manifest)), manifest['key_epoch'],
                        key_id, public_hex(key_number))


def verify_reference(envelope, events, context):
    """Verify against supplied out-of-band LAB facts, never candidate-issued pins.

    MATCH is identity/content/order correspondence under these particular facts;
    it does not mean financial correctness, authentic institutional publisher or
    admission authorization. No persistent epoch registry is implemented here.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
    require(isinstance(context, TrustContext) and context.origin == 'LAB_TEST_ONLY', 'UNVERIFIED_ANCHOR')
    require(type(context.scope) is dict and set(context.scope)==SCOPE_FIELDS
            and all(type(v) is str and 0 < len(v) <= 256 for v in context.scope.values()), 'CONTEXT_SCOPE')
    require(context.scope['record_kind']=='event', 'CONTEXT_RECORD_KIND')
    require(type(context.key_id) is str and re.fullmatch('[A-Za-z0-9_-]{1,80}',context.key_id) is not None, 'CONTEXT_KEY')
    require(type(context.public_key_hex) is str and re.fullmatch('[0-9a-f]{64}',context.public_key_hex) is not None, 'CONTEXT_PUBLIC_KEY')
    uint_text(context.revision); uint_text(context.epoch)
    require(digest_text(context.manifest_sha256), 'CONTEXT_PIN')
    obj = strict_reference_json(envelope)
    require(type(obj) is dict and set(obj) == {'manifest','signatures'}, 'ENVELOPE_FIELDS')
    signatures = obj['signatures']
    require(type(signatures) is list and len(signatures) == 1, 'SIGNATURE_COUNT')
    item = signatures[0]
    require(type(item) is dict and set(item) == {'key_id','signature'}, 'SIGNATURE_FIELDS')
    require(item['key_id'] == context.key_id and item['key_id'] not in context.revoked_key_ids, 'KEY_NOT_ACTIVE')
    manifest = obj['manifest']
    required = {'format','scope','revision','previous_sha256','key_epoch','entries'}
    require(type(manifest) is dict and set(manifest) == required, 'MANIFEST_FIELDS')
    require(manifest['format'] == 'identity-reference-research-v1', 'MANIFEST_VERSION')
    require(type(manifest['scope']) is dict and manifest['scope'] == context.scope, 'SCOPE_MISMATCH')
    require(uint_text(manifest['revision']) == uint_text(context.revision), 'REVISION_MISMATCH')
    require(uint_text(manifest['key_epoch']) == uint_text(context.epoch), 'EPOCH_MISMATCH')
    require(manifest['previous_sha256'] == context.previous_sha256, 'PREDECESSOR_MISMATCH')
    require((manifest['revision']=='1' and manifest['previous_sha256'] is None) or
            (manifest['revision']!='1' and digest_text(manifest['previous_sha256'])), 'PREDECESSOR_FORMAT')
    encoded = canonical(manifest)
    require(sha(encoded) == context.manifest_sha256, 'SELECTED_SNAPSHOT_MISMATCH')
    try:
        signature = base64.b64decode(item['signature'], validate=True)
        require(len(signature) == 64 and base64.b64encode(signature).decode('ascii') == item['signature'], 'SIGNATURE_ENCODING')
        key = bytes.fromhex(context.public_key_hex)
        require(len(key) == 32, 'PUBLIC_KEY_LENGTH')
        Ed25519PublicKey.from_public_bytes(key).verify(signature, DOMAIN+encoded)
    except (InvalidSignature, TypeError, ValueError) as exc:
        raise ReferenceError('SIGNATURE_INVALID') from exc
    entries = manifest['entries']
    require(type(entries) is list and 1 <= len(entries) <= MAX_ENTRIES, 'ENTRY_COUNT')
    ids = []
    for position, entry in enumerate(entries, 1):
        require(type(entry) is dict and set(entry) == {'position','event_id','content_sha256'}, 'ENTRY_FIELDS')
        require(uint_text(entry['position']) == position, 'ENTRY_ORDER')
        require(type(entry['event_id']) is str and 0 < len(entry['event_id']) <= 256, 'EVENT_ID_TEXT')
        require(digest_text(entry['content_sha256']), 'CONTENT_DIGEST')
        ids.append(entry['event_id'])
    require(len(ids) == len(set(ids)), 'DUPLICATE_REFERENCE_ID')
    require(type(events) is list and len(events) <= MAX_ENTRIES, 'CANDIDATE_COUNT')
    candidate_ids = []
    for event in events:
        require(type(event) is dict and set(event) == {'event_id','content'}, 'CANDIDATE_FIELDS')
        require(type(event['event_id']) is str and 0 < len(event['event_id']) <= 256, 'CANDIDATE_ID')
        require(type(event['content']) is bytes and 0 < len(event['content']) <= 65536, 'CANDIDATE_CONTENT')
        candidate_ids.append(event['event_id'])
    require(len(candidate_ids) == len(set(candidate_ids)), 'DUPLICATE_CANDIDATE_ID')
    actual = [(event['event_id'],sha(event['content'])) for event in events]
    expected = [(entry['event_id'],entry['content_sha256']) for entry in entries]
    return {'outcome': 'MATCH' if actual == expected else 'REFERENCE_MISMATCH',
            'manifest_sha256': context.manifest_sha256, 'authority': 'LAB_TEST_ONLY',
            'institutional_trust': 'NOT_PROVEN', 'financial_reconciliation': 'NOT_PERFORMED',
            'candidate_count':len(events), 'reference_count':len(entries)}


def events_from_input(data):
    records = [row['record'] for row in data['rows'] if row['record'].get('kind') == 'event' and row['record'].get('asset') == 'COIN']
    records.sort(key=lambda row:(row['occurred_at'],row['sequence'],row['source'],row['business_day'],row['ref']))
    return [{'event_id': canonical([row[k] for k in ('source','platform','business_day','ref')]).decode('ascii'),
             'content': canonical(row)} for row in records]


def baseline_inputs(base, contract):
    base = Path(base)
    for name, expected in contract['baseline_evidence_pins'].items():
        require(sha((base/name).read_bytes())==expected, 'BASELINE_EVIDENCE_PIN')
    summary=json.loads((base/'summary.json').read_text())
    require(summary['cases']==264 and {k:summary['metrics'][k] for k in ('TP','FP','TN','FN')}=={'TP':132,'FP':0,'TN':120,'FN':12},'BASELINE_COUNTS')
    rows=[json.loads(line) for line in (base/'cases.jsonl').read_text().splitlines()]
    require(len(rows)==len({row['case_id'] for row in rows})==264,'BASELINE_ROSTER')
    by_id={row['case_id']:row for row in rows}
    result={}
    for seed in contract['seeds']:
        for factor in contract['factors']:
            group=f's{seed}-f{factor}'
            inputs={}
            for family in ('clean','same_count_substitution'):
                record=by_id[group+'-'+family]
                raw=(base/record['input']).read_bytes()
                require(sha(raw)==record['input_sha256'],'BASELINE_INPUT_DIGEST')
                inputs[family]={'events':events_from_input(json.loads(raw)),'input_sha256':sha(raw),'path':str(base/record['input'])}
            result[group]=inputs
    return result


def identity_case(group, family, original, substituted):
    scope={'publisher':'LAB-PUBLISHER','dataset':'synthetic-native-events','partition':group,
           'event_day':'2026-01-05','balance_cut':'2026-01-05T23:59:59.000000Z','record_kind':'event'}
    reference=make_manifest(original,scope)
    candidate=copy.deepcopy(original)
    context=context_for(reference)
    envelope=sign_manifest(reference)
    historical=None
    if family=='same_count_substitution': candidate=copy.deepcopy(substituted)
    elif family=='content_substitution': candidate[0]['content']+=b' '
    elif family=='reordered_events': candidate=list(reversed(candidate))
    elif family=='duplicate_candidate_id': candidate[1]['event_id']=candidate[0]['event_id']
    elif family=='scope_hijack':
        reference['scope']['publisher']='OTHER'; envelope=sign_manifest(reference)
    elif family=='unknown_signing_key': envelope=sign_manifest(reference,9,'UNTRUSTED-KEY')
    elif family=='tampered_signature':
        obj=json.loads(envelope); obj['signatures'][0]['signature']=base64.b64encode(b'X'*64).decode(); envelope=canonical(obj)
    elif family=='conflicting_signatures':
        obj=json.loads(envelope); obj['signatures'].append(json.loads(sign_manifest(reference,2,'LAB-KEY-2'))['signatures'][0]);envelope=canonical(obj)
    elif family=='same_revision_conflict':
        reference['entries'][0]['content_sha256']='0'*64; envelope=sign_manifest(reference)
    elif family in ('revision_upgrade','stale_revision_replay'):
        new=make_manifest(original,scope,'2',context.manifest_sha256)
        context=context_for(new)
        if family=='revision_upgrade': envelope=sign_manifest(new)
    elif family in ('key_rotation','retired_key_new_request','revoked_key_new_request'):
        reference=make_manifest(original,scope,'2',context.manifest_sha256,'2')
        context=context_for(reference,2,'LAB-KEY-2')
        envelope=sign_manifest(reference,2,'LAB-KEY-2')
        if family=='retired_key_new_request': envelope=sign_manifest(reference,1,'LAB-KEY-1')
        if family=='revoked_key_new_request':context=replace(context,revoked_key_ids=('LAB-KEY-2',))
    elif family=='unverified_self_issued_pin':context=replace(context,origin='SELF_ISSUED_FROM_CANDIDATE')
    elif family in ('large_string_id_boundary','large_adjacent_id_substitution'):
        candidate=copy.deepcopy(original); candidate[0]['event_id']=str(2**63-1)
        reference=make_manifest(candidate,scope); context=context_for(reference);envelope=sign_manifest(reference)
        if family=='large_adjacent_id_substitution':candidate[0]['event_id']=str(2**63-2)
    elif family=='empty_reference':
        reference=make_manifest([],scope);context=context_for(reference);envelope=sign_manifest(reference)
    elif family=='previous_decision_after_revocation':
        historical=verify_reference(envelope,candidate,context)
        historical=canonical(historical)
        context=replace(context,revoked_key_ids=('LAB-KEY-1',))
    elif family!='clean': raise ValueError('unknown identity family')
    return candidate,envelope,context,historical


def production_fuzz_cases(seed):
    """Independent grammar generation plus explicit syntax/encoding boundaries."""
    rng=random.Random(seed)
    values=[None,True,False,0,2**63-1,'çığ😀',[],{}]
    for index in range(12):
        value={'label':f's{seed}-{index}','a':[rng.choice(values),rng.randrange(-100000,100000)],'s':chr(rng.randint(65,90))*rng.randint(0,20)}
        yield {'name':f'grammar_{index:02d}','target':'strict_json','raw':canonical(value),'expected':'ACCEPT','value':value}
    literals=[('duplicate_key',b'{"x":1,"x":2}','REJECT'),('escaped_duplicate_key',b'{"x":1,"\\u0078":2}','REJECT'),
              ('lone_surrogate',b'"\\ud800"','REJECT'),('utf8_surrogate',b'"\xed\xa0\x80"','REJECT'),('invalid_utf8',b'"\xff"','REJECT'),
              ('nonfinite_nan',b'NaN','REJECT'),('overflow_number',b'1e9999','REJECT'),('empty',b'','REJECT'),
              ('truncated_object',b'{"a":','REJECT'),('depth_32',b'['*32+b'0'+b']'*32,'ACCEPT'),
              ('depth_33',b'['*33+b'0'+b']'*33,'REJECT'),('nodes_20000',b'['+b','.join([b'0']*19999)+b']','ACCEPT'),
              ('nodes_20001',b'['+b','.join([b'0']*20000)+b']','REJECT'),('bytes_65536',b'0'+b' '*65535,'ACCEPT'),
              ('bytes_65537',b'0'+b' '*65536,'REJECT'),('exact_int64',str(2**63-1).encode(),'ACCEPT')]
    nested_zero=0
    for _ in range(32):
        nested_zero=[nested_zero]
    literal_values={'depth_32':nested_zero,'nodes_20000':[0]*19999,
                    'bytes_65536':0,'exact_int64':2**63-1}
    for name,raw,expected in literals:
        yield {'name':name,'target':'strict_json','raw':raw,'expected':expected,
               **({'value':literal_values[name]} if expected=='ACCEPT' else {})}
    for name,value,expected,result in (
        ('utc_offset','2026-01-05T04:00:00+03:00','ACCEPT','2026-01-05T01:00:00.000000Z'),
        ('missing_timezone','2026-01-05T04:00:00','REJECT',None),
        ('utc_underflow','0001-01-01T00:00:00+01:00','REJECT',None)):
        yield {'name':name,'target':'timestamp','raw':value.encode(),'expected':expected,'value':result}
    # Minimal, real normalization path witnesses: cycle/self-reference cannot be
    # traversed because correction targets must be original events.
    cfg={'platform':'P','custodian':'C','investors':['I1','I2'],'assets':{'COIN':2},'opening_at':'2026-01-05T00:00:00Z'}
    corr={'kind':'correction','source':'P','platform':'P','asset':'COIN','batch_id':'B','correction_id':'C1','mode':'VOID',
          'target':{'kind':'event','source':'P','platform':'P','business_day':'2026-01-05','ref':'D'},
          'target_occurred_at':'2026-01-05T01:00:00Z','source_ref':'SRC','reason':'LAB normalization boundary'}
    for name,change,expected in [('correction_original_event',None,'ACCEPT'),('correction_self',{'kind':'correction','correction_id':'C1'},'REJECT'),
                                 ('correction_cycle_edge',{'kind':'correction','correction_id':'C2'},'REJECT')]:
        value=copy.deepcopy(corr)
        if change:value['target']=change
        expected_value=copy.deepcopy(corr)
        expected_value['target_occurred_at']='2026-01-05T01:00:00.000000Z'
        yield {'name':name,'target':'normalize_correction','raw':canonical(value),'expected':expected,'config':cfg,
               **({'value':(expected_value,'["correction","P","P","C1"]'),
                   'return_shape':'tuple[normalized record, logical key]'} if expected=='ACCEPT' else {})}


def run_production_fuzz(case):
    from crypto_reconciliation_lab.source_auth.crypto import strict_json
    from crypto_reconciliation_lab.model import timestamp, config_validate
    from crypto_reconciliation_lab.correction_model import normalize_correction
    require(case['expected']!='ACCEPT' or 'value' in case,'MISSING_INDEPENDENT_VALUE_ORACLE')
    try:
        if case['target']=='strict_json': value=strict_json(case['raw'])
        elif case['target']=='timestamp':value=timestamp(case['raw'].decode())
        elif case['target']=='normalize_correction':value=normalize_correction(json.loads(case['raw']),config_validate(case['config']))
        else:raise AssertionError('unregistered fuzz target')
        checked=case['expected']=='ACCEPT'
        return {'outcome':'ACCEPT','value_equal':value==case['value'] if checked else None,
                'value_check':'CHECKED' if checked else 'NOT_PERFORMED_EXPECTED_REJECTION'}
    except (ValueError,UnicodeError,OverflowError,RecursionError) as exc:
        return {'outcome':'REJECT','exception_type':type(exc).__name__,'reason':str(exc),
                'value_equal':None,'value_check':'NOT_APPLICABLE_REJECTED'}


def count_matrix(rows):
    counts=Counter({'TP':0,'FP':0,'TN':0,'FN':0})
    for row in rows:
        positive=row['family']=='same_count_substitution'
        alert=row['actual']['outcome']!='MATCH'
        counts[('T' if positive==alert else 'F')+('P' if alert else 'N')]+=1
    return dict(counts)


def run(output, baseline, smoke=False):
    started=time.monotonic()
    require(sha(CONTRACT.read_bytes())==CONTRACT_SHA256,'CONTRACT_PIN')
    contract=json.loads(CONTRACT.read_text())
    groups=baseline_inputs(baseline,contract)
    seeds=contract['seeds'][:1] if smoke else contract['seeds']
    families=contract['identity_families']
    require(seeds and len(seeds)==len(set(seeds)) and len(families)==20,'EMPTY_OR_DUPLICATE_SCOPE')
    fuzz_catalog={seed:list(production_fuzz_cases(seed)) for seed in seeds}
    require(all(len(cases)==len(contract['fuzz']['expected_names']) and
                {case['name'] for case in cases}==set(contract['fuzz']['expected_names'])
                for cases in fuzz_catalog.values()), 'FUZZ_ROSTER')
    expected_ids=[f's{seed}-f{factor}-{family}' for seed in seeds for factor in contract['factors'] for family in families]
    expected_fuzz=[f's{seed}-{case["name"]}' for seed in seeds for case in fuzz_catalog[seed]]
    require(len(expected_ids)==len(set(expected_ids)) and len(expected_fuzz)==len(set(expected_fuzz)) and expected_fuzz,'DUPLICATE_OR_EMPTY_CASES')
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    write_json(output/'protocol.json',{'contract_sha256':CONTRACT_SHA256,'expected_identity_ids':expected_ids,
                                     'expected_fuzz_ids':expected_fuzz,'seeds':seeds,'registered_before_execution':True,
                                     'source_sha256':sha(Path(__file__).read_bytes()),'authority':'LAB_TEST_ONLY'})
    (output/'source-identity_reference.py').write_bytes(Path(__file__).read_bytes())
    protocol_sha=sha((output/'protocol.json').read_bytes())
    source_sha=sha(Path(__file__).read_bytes())
    identity=[]; fuzz=[]
    for seed in seeds:
        for factor in contract['factors']:
            group=f's{seed}-f{factor}'
            original=groups[group]['clean']['events'];substituted=groups[group]['same_count_substitution']['events']
            for family,expected in families.items():
                require(time.monotonic()-started<280,'EXPERIMENT_BUDGET')
                candidate,envelope,context,historical=identity_case(group,family,original,substituted)
                cid=group+'-'+family;folder=output/'identity'/cid;folder.mkdir(parents=True)
                (folder/'envelope.json').write_bytes(envelope)
                write_json(folder/'candidate.json',[{'event_id':event['event_id'],'content_base64':base64.b64encode(event['content']).decode()} for event in candidate])
                write_json(folder/'context.json',asdict(context))
                before=time.perf_counter()
                try:actual=verify_reference(envelope,candidate,context)
                except ReferenceError as exc:actual={'outcome':'ERROR','reason':str(exc)}
                elapsed=time.perf_counter()-before
                if historical is not None:
                    write_json(folder/'historical-decision.json',json.loads(historical))
                    actual={'outcome':'HISTORICAL_DECISION_UNCHANGED' if actual['outcome']=='ERROR' and canonical(json.loads(historical))==historical else 'FAIL',
                            'new_request_rejection':actual,'historical_sha256':sha(historical)}
                evidence={p.name:{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in folder.iterdir()}
                row={'case_id':cid,'group':group,'seed':seed,'factor':factor,'family':family,'expected':expected,'actual':actual,
                     'status':'PASS' if actual['outcome']==expected else 'FAIL','seconds':elapsed,'data_class':'FULLY_SYNTHETIC_WITH_LAB_REFERENCE',
                     'authority':'LAB_TEST_ONLY','institutional_anchor':'UNAVAILABLE','extra_reference_bytes':len(envelope),
                     'evidence_dir':str(folder.relative_to(output)),'files':evidence,
                     'baseline_inputs':{k:{q:v[q] for q in ('path','input_sha256')} for k,v in groups[group].items()}}
                identity.append(row)
                with (output/'identity-cases.jsonl').open('a') as handle:handle.write(json.dumps(row,sort_keys=True)+'\n')
    for seed in seeds:
        for case in fuzz_catalog[seed]:
            cid=f's{seed}-{case["name"]}';folder=output/'fuzz'/cid;folder.mkdir(parents=True)
            (folder/'input.bin').write_bytes(case['raw'])
            write_json(folder/'oracle.json',{k:v for k,v in case.items() if k!='raw'})
            before=time.perf_counter();actual=run_production_fuzz(case);elapsed=time.perf_counter()-before
            verified=(actual['outcome']==case['expected'] and
                      (case['expected']=='REJECT' or actual['value_equal'] is True))
            row={'case_id':cid,'seed':seed,'group':f's{seed}','family':case['name'],'target':case['target'],
                 'expected':case['expected'],'actual':actual,'status':'PASS' if verified else 'FAIL',
                 'seconds':elapsed,'data_class':'FULLY_SYNTHETIC','input_sha256':sha(case['raw']),'input_bytes':len(case['raw']),
                 'evidence_dir':str(folder.relative_to(output)),'shrink':'NOT_RUN_NO_UNEXPECTED_OUTCOME' if verified else 'NOT_RUN_ORIGINAL_BOUNDED_WITNESS_RETAINED'}
            fuzz.append(row)
            with (output/'fuzz-cases.jsonl').open('a') as handle:handle.write(json.dumps(row,sort_keys=True)+'\n')
    valid=(len(identity)==len({r['case_id'] for r in identity})==len(expected_ids) and {r['case_id'] for r in identity}==set(expected_ids)
           and len(fuzz)==len({r['case_id'] for r in fuzz})==len(expected_fuzz) and {r['case_id'] for r in fuzz}==set(expected_fuzz)
           and all(r['status']=='PASS' for r in identity+fuzz) and sha((output/'protocol.json').read_bytes())==protocol_sha
           and sha(CONTRACT.read_bytes())==CONTRACT_SHA256 and sha(Path(__file__).read_bytes())==source_sha)
    enhanced=[r for r in identity if r['family'] in contract['enhanced_confusion_matrix_families']]
    scorecards={'baseline_preserved':{**contract['baseline_detection'],'source':'reviewed historical run; NOT_RERUN','data_class':'FULLY_SYNTHETIC'},
                'enhanced_lab_reference':{'cases':len(enhanced),**count_matrix(enhanced),'authority':'LAB_TEST_ONLY',
                   'natural_error_rate':'NOT_MEASURED','institutional_trust':'NOT_PROVEN','scope':'Only paired clean/substitution inputs with additional oracle-generated signed references; cannot be pooled with baseline.'},
                'new_fuzz':{'cases':len(fuzz),'passed':sum(r['status']=='PASS' for r in fuzz),'failed':sum(r['status']!='PASS' for r in fuzz),
                   'scope':'Finite production parser/timestamp/correction-normalization cases; no reliability population inference.'}}
    write_json(output/'scorecards.json',scorecards)
    summary={'format':'identity-reference-research-result-v1','status':'PASS' if valid else 'FAIL',
             'identity_cases':len(identity),'fuzz_cases':len(fuzz),'cases':len(identity)+len(fuzz),'passed':sum(r['status']=='PASS' for r in identity+fuzz),
             'failed':sum(r['status']!='PASS' for r in identity+fuzz),'skipped':0,'exact_scope':valid,
             'scorecards':scorecards,'authority':'LAB_TEST_ONLY','institutional_anchor':'UNAVAILABLE',
             'identity_cases_ledger':'identity-cases.jsonl','fuzz_cases_ledger':'fuzz-cases.jsonl','protocol':'protocol.json',
             'protocol_sha256':protocol_sha,'contract_sha256':CONTRACT_SHA256,
             'extra_reference_bytes':{'min':min(r['extra_reference_bytes'] for r in identity),'max':max(r['extra_reference_bytes'] for r in identity),'sum':sum(r['extra_reference_bytes'] for r in identity)},
             'elapsed_seconds':time.monotonic()-started,'command':[sys.executable,*sys.argv],
             'environment':{'python':sys.version,'platform':platform.platform()},
             'not_run':['Persistent concurrent reference registry','Natural institutional error labels','Independently authenticated institutional event reference','New process-crash or multiwriter experiment in this module'],
             'limitation':'The experiment proves distinguishability given added LAB facts. It does not supply real external identity, change original 12 FNs, or authorize deployment.'}
    write_json(output/'summary.json',summary)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--baseline',type=Path,default=Path('/workspace/validation-evidence/properties/run-004'))
    parser.add_argument('--smoke',action='store_true')
    args=parser.parse_args();summary=run(args.output,args.baseline,args.smoke)
    print(json.dumps({k:summary[k] for k in ('status','identity_cases','fuzz_cases','passed','failed','scorecards','elapsed_seconds')},indent=2))
    return 0 if summary['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
