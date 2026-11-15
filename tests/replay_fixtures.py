"""Independent fixture construction and controlled TEST-ONLY byte rebinding."""
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path

from crypto_reconciliation_lab import Store
from crypto_reconciliation_lab.execution import reconcile_recorded, export_execution
from crypto_reconciliation_lab.execution.demo import CONFIG, BALANCE_AT, KNOWLEDGE_AT, financial_records


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',', ':'),ensure_ascii=True,allow_nan=False).encode()


def hashed(raw):
    return hashlib.sha256(raw).hexdigest()


def export_pair(root, *, rows=None, config=None, balance_at=BALANCE_AT,
                knowledge_at=KNOWLEDGE_AT, request_id='replay-fixture'):
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    config=copy.deepcopy(CONFIG if config is None else config)
    if rows is None:
        rows=[row for feed in financial_records().values() for row in feed]
    database=root/'source.sqlite3'
    with closing(Store(database,config)) as store:
        for row in rows:
            store.ingest(row['record'],row['received_at'])
        result=reconcile_recorded(store,balance_at,knowledge_at,request_id)
    folder=root/'pair'
    export_execution(database,result['execution_id'],folder)
    return load_pair(folder,result['execution_id'],database=database)


def load_pair(folder,expected, *, database=None):
    folder=Path(folder)
    return {'context_path':folder/'context.json','run_path':folder/'run.json',
            'expected':expected,'context':json.loads((folder/'context.json').read_bytes()),
            'run':json.loads((folder/'run.json').read_bytes()),'database':database}


def write_historical(root,entry):
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    (root/'context.json').write_bytes(bytes.fromhex(entry['context_hex']))
    (root/'run.json').write_bytes(bytes.fromhex(entry['run_hex']))
    expected=entry.get('execution_id',entry.get('row',{}).get('execution_id'))
    return load_pair(root,expected)


def rebound(pair,root, *, mutate_context=None,mutate_run=None,raw_run=None):
    """Rebind controlled test material, not an external authentication claim.

    Inputs/evidence mapping remain untouched unless the test explicitly changes
    them. All identity changes are independent SHA-256/stdlib JSON operations.
    """
    context=copy.deepcopy(pair['context']);run=copy.deepcopy(pair['run'])
    if mutate_run:
        mutate_run(run)
    if mutate_context:
        mutate_context(context)
    run_bytes=encoded(run) if raw_run is None else raw_run
    run=json.loads(run_bytes)
    context['run_id']=hashed(encoded(run))
    context['run_payload_sha256']=hashed(run_bytes)
    context['request_fingerprint']=hashed(encoded(context['request']))
    context_bytes=encoded(context)
    binding={'format':'recorded-execution-v1',**{key:context[key] for key in (
        'request_id','request_fingerprint','run_id','run_payload_sha256')},
        'context_hash':hashed(context_bytes)}
    expected=hashed(encoded(binding))
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    (root/'context.json').write_bytes(context_bytes);(root/'run.json').write_bytes(run_bytes)
    return load_pair(root,expected)


def verify(pair, **kwargs):
    from crypto_reconciliation_lab.replay import verify_execution_replay
    return verify_execution_replay(pair['context_path'],pair['run_path'],pair['expected'],**kwargs)


def all_rows():
    return copy.deepcopy([row for feed in financial_records().values() for row in feed])


def assert_reproduced(case,result):
    case.assertEqual((result['status'],result['exit_code'],result['reason_code']),
                     ('REPRODUCED',0,'REPLAY_REPRODUCED'),result)
    case.assertEqual(result['replay_state'],'REPRODUCED')
    case.assertEqual(result['comparison']['state'],'EQUAL')
    case.assertTrue(result['comparison']['equal'])
    case.assertEqual(result['comparison']['total_differences'],0)
    case.assertEqual(result['completion'],{'validation':'COMPLETED','calculation':'COMPLETED','comparison':'COMPLETED'})


def assert_error(case,result,reason):
    case.assertEqual((result['status'],result['exit_code'],result['reason_code']),('ERROR',2,reason),result)


def literal_finances(case,pair,i1='7',i2='4',liability='11',external='9'):
    ledger=pair['run']['ledgers']['ASSET_A']
    case.assertEqual(ledger['investor_balances'],{'I1':i1,'I2':i2})
    case.assertEqual(ledger['liability'],liability)
    case.assertEqual(ledger['custody_rollforward'],{'platform':'2','external':external})
    other=pair['run']['ledgers']['ASSET_B']
    case.assertEqual(other['investor_balances'],{'I1':'0.3','I2':'0.2'})
    case.assertEqual(other['liability'],'0.5')
