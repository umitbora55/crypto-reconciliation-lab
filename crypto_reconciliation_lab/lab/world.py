"""Deterministic valid integer economic world and contract-only wire generation."""
from datetime import datetime,timedelta,timezone
import random
import sys
from . import GENERATOR_VERSION
from .oracle import balances,decimal_text


def iso(value): return value.isoformat(timespec='microseconds').replace('+00:00','Z')


def generate(seed=11,events=100,investors=6):
    if type(seed) is not int or type(events) is not int or events<12 or type(investors) is not int or investors<2:
        raise ValueError('integer seed, at least 12 original events and 2 investors required')
    rng=random.Random(seed);start=datetime(2026,11,10,tzinfo=timezone.utc)
    names=[f'I{i:03}' for i in range(1,investors+1)];assets={'ASSET_A':8,'ASSET_B':2}
    opening={}
    # This bound funds even a worst-case uninterrupted sequence of withdrawals.
    per_investor=events*100+1000
    for a in assets:
        total=per_investor*investors
        opening[a]={'investors':{i:per_investor for i in names},'custody':{'platform':total//2,'external':total-total//2}}
    records=[]
    for n in range(events):
        kind=('deposit','withdrawal','transfer')[n%3];asset=('ASSET_A','ASSET_B')[n%2]
        sender,recipient=rng.sample(names,2);q=rng.randint(1,25)
        records.append(dict(ref=f'E{n+1:08}',asset=asset,kind=kind,units=q,at=iso(start+timedelta(seconds=n+1)),sequence=1,
                            sender=None if kind=='deposit' else sender,recipient=None if kind=='withdrawal' else recipient,
                            custody=None if kind=='transfer' else ('external','platform')[(n//3)%2]))
    end=start+timedelta(seconds=events)
    world=dict(seed=seed,generator_version=GENERATOR_VERSION,interpreter=sys.version,assets=assets,investors=names,
               opening_at=iso(start),opening=opening,events=records,
               cuts=[records[events//2-1]['at'],iso(end)],knowledge=[iso(end+timedelta(hours=h)) for h in (1,2,3,4)])
    # Independent valid-world precondition: every step and custody location stays funded.
    balances(world,world['cuts'][-1])
    return world


def config(world):
    return dict(platform='P1',custodian='C1',investors=world['investors'],assets=world['assets'],opening_at=world['opening_at'])


def base(kind,asset,source='P1'):return dict(kind=kind,asset=asset,source=source,platform='P1')


def envelope(record,time):return dict(record=record,received_at=time)


def report_rows(world,cut,knowledge,ledger,version=1,streams=None):
    rows=[]
    for asset in sorted(world['assets']):
        scale=world['assets'][asset]
        items=[('investor',i,q,'P1') for i,q in ledger[asset]['investors'].items()]
        items += [('platform_custody','platform',ledger[asset]['custody']['platform'],'P1'),('external_custody','external',ledger[asset]['custody']['external'],'C1')]
        for stream,scope,q,source in items:
            if streams is None or stream in streams:
                rows.append(envelope({**base('report',asset,source), 'stream':stream,'scope':scope,'balance_at':cut,'version':version,'amount':decimal_text(q,scale)},knowledge))
    return rows


def wire(world):
    rows=[];k=world['knowledge'][0]
    for asset in sorted(world['assets']):
        for scope,q in [*world['opening'][asset]['investors'].items(),*world['opening'][asset]['custody'].items()]:
            rows.append(envelope({**base('opening',asset),'scope':scope,'balance_at':world['opening_at'],'amount':decimal_text(q,world['assets'][asset])},world['opening_at']))
        rows.append(envelope({**base('manifest',asset),'stream':'opening','coverage_from':world['opening_at'],'coverage_to':world['opening_at'],'expected_count':len(world['investors'])+2},k))
    for e in world['events']:
        rows.append(envelope({**base('event',e['asset']),'business_day':e['at'][:10],'ref':e['ref'],'occurred_at':e['at'],'sequence':e['sequence'],
                              'type':e['kind'],'from_investor':e['sender'],'to_investor':e['recipient'],'custody':e['custody'],
                              'amount':decimal_text(e['units'],world['assets'][e['asset']])},e['at']))
    for cut in world['cuts']:
        ledger=balances(world,cut);rows+=report_rows(world,cut,k,ledger)
        for asset in sorted(world['assets']):
            for stream,count,source in [('event',sum(e['asset']==asset and e['at']<=cut for e in world['events']),'P1'),('investor',len(world['investors']),'P1'),('platform_custody',1,'P1'),('external_custody',1,'C1')]:
                rows.append(envelope({**base('manifest',asset,source),'stream':stream,'coverage_from':world['opening_at'] if stream=='event' else cut,'coverage_to':cut,'expected_count':count},k))
    return rows
