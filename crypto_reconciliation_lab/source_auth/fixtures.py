"""Explicit TEST-ONLY inputs and public anchors, never production credentials."""
import copy
import hashlib
import json
from ..model import config_validate, digest

# Public RFC 8032 section 7.1 test vectors. Every private seed here is PUBLIC.
TEST_KEYS = {
    'P1-old': ('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60', 'd75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a', 'P1'),
    'P1-new': ('4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb', '3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c', 'P1'),
    'C1-key': ('c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7', 'fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025', 'C1'),
}
RECEIVER = 'TEST-ONLY:local-receiver'
BALANCE_AT = '2026-11-10T23:59:59.000000Z'
KNOWLEDGE_AT = '2026-11-11T01:00:00.000000Z'
CONFIG = config_validate({'platform':'P1','custodian':'C1','investors':['I1','I2'],
                         'assets':{'ASSET_A':8,'ASSET_B':2},'opening_at':'2026-11-10T00:00:00Z'})
REFERENCE = {'ASSET_A':{'I1':'7','I2':'4','liability':'11','platform':'2','external':'9'},
             'ASSET_B':{'I1':'0.3','I2':'0.2','liability':'0.5','platform':'0.05','external':'0.45'}}


def operator_anchor():
    """Public, explicit local operator selection; never loaded from a report."""
    return {'format':'source-auth-test-anchor-v1','receiver':RECEIVER,
            'configuration_digest':digest(CONFIG),
            'keys':{kid:{'source':v[2],'public_key':v[1],
                        'fingerprint':hashlib.sha256(bytes.fromhex(v[1])).hexdigest()}
                    for kid,v in TEST_KEYS.items()},
            'namespaces':{'P1':'platform-demo:','C1':'custodian-demo:'}}


def capability(source, asset, kind, channel='none'):
    return {'source':source,'platform':'P1','asset':asset,'kind':kind,'channel':channel}


def policy(rotated=False):
    """Literal grant combinations, not independent lists or inferred file scope."""
    grants = {'P1':[], 'C1':[]}
    for asset in ('ASSET_A','ASSET_B'):
        for kind, channel in (('opening','none'),('event','none'),('correction','none'),
                              ('correction_manifest','none'),('report','investor'),
                              ('report','platform_custody'),('manifest','opening'),
                              ('manifest','event'),('manifest','investor'),('manifest','platform_custody')):
            grants['P1'].append(capability('P1',asset,kind,channel))
        for kind in ('report','manifest'):
            grants['C1'].append(capability('C1',asset,kind,'external_custody'))
    anchor=operator_anchor()
    return {'format':'source-auth-policy-v1','receiver':RECEIVER,
            'configuration_digest':digest(CONFIG),
            'sources':[{'source':s,'namespace':anchor['namespaces'][s],'capabilities':grants[s]} for s in ('P1','C1')],
            'keys':[{'key_id':kid,**v,'status':'revoked' if rotated and kid=='P1-old' else 'active'}
                    for kid,v in anchor['keys'].items()]}


def financial_records(wrong_custody=False):
    """Independent hand-authored quantities; returns separate publisher feeds."""
    feeds={'P1':[], 'C1':[]}
    def add(kind,asset,source='P1',received=KNOWLEDGE_AT,**fields):
        feeds[source].append({'record':{'kind':kind,'asset':asset,'source':source,'platform':'P1',**fields},'received_at':received})
    for asset, values in (('ASSET_A',('6','4','2','8')),('ASSET_B',('0.10','0.20','0.05','0.25'))):
        for scope,amount in zip(('I1','I2','platform','external'),values):
            add('opening',asset,received=CONFIG['opening_at'],scope=scope,balance_at=CONFIG['opening_at'],amount=amount)
    events=(('ASSET_A','A1','transfer','I1','I2',None,'1',1),
            ('ASSET_A','A2','deposit',None,'I1','external','2',2),
            ('ASSET_A','A3','withdrawal','I2',None,'external','1',3),
            ('ASSET_B','B1','deposit',None,'I1','external','0.20',2))
    for asset,ref,kind,sender,recipient,custody,amount,hour in events:
        occurred=f'2026-11-10T{hour:02d}:00:00.000000Z'
        add('event',asset,received=occurred,business_day='2026-11-10',ref=ref,occurred_at=occurred,
            sequence=1,type=kind,from_investor=sender,to_investor=recipient,custody=custody,amount=amount)
    for asset in ('ASSET_A','ASSET_B'):
        for stream,scope,amount in (('investor','I1',REFERENCE[asset]['I1']),('investor','I2',REFERENCE[asset]['I2']),
                                    ('platform_custody','platform',REFERENCE[asset]['platform']),
                                    ('external_custody','external','8' if wrong_custody and asset=='ASSET_A' else REFERENCE[asset]['external'])):
            add('report',asset,'C1' if stream=='external_custody' else 'P1',stream=stream,scope=scope,balance_at=BALANCE_AT,version=1,amount=amount)
        for stream,count in (('opening',4),('event',3 if asset=='ASSET_A' else 1),('investor',2),('platform_custody',1),('external_custody',1)):
            add('manifest',asset,'C1' if stream=='external_custody' else 'P1',stream=stream,
                coverage_from=CONFIG['opening_at'] if stream in ('opening','event') else BALANCE_AT,
                coverage_to=CONFIG['opening_at'] if stream=='opening' else BALANCE_AT,expected_count=count)
    return feeds


def small_records():
    return copy.deepcopy(financial_records()['P1'][:2])


def snapshot(records):
    return b''.join(json.dumps(r,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()+b'\n' for r in records)


def signed(data, stream='platform-demo:sample', key_id='P1-old', **statement_changes):
    from .crypto import sign_statement
    from .scope import capabilities, snapshot_bytes
    snap=snapshot_bytes(data)
    statement={'format':'source-admission-statement-v1','source':TEST_KEYS[key_id][2],
               'receiver':RECEIVER,'configuration_digest':digest(CONFIG),'stream_id':stream,
               'plan':snap.plan,'capabilities':capabilities(snap,CONFIG)}
    statement.update(statement_changes)
    return sign_statement(statement,bytes.fromhex(TEST_KEYS[key_id][0]),key_id)
