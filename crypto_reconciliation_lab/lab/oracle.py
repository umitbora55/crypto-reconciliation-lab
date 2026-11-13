"""Independent integer-unit accounting for a valid world, not a second validator."""
import re


def units(text,scale):
    if type(scale) is not int or not 0<=scale<=18:
        raise ValueError('scale must be an integer in 0..18')
    if not isinstance(text,str) or re.fullmatch(r'-?[0-9]+(?:\.[0-9]+)?',text) is None:
        raise ValueError('finite decimal text is required; null is not zero')
    negative=text.startswith('-');parts=text.lstrip('-').split('.')
    tail=parts[1] if len(parts)==2 else ''
    if len(tail)>scale: raise ValueError('excess precision; rounding is forbidden')
    value=int(parts[0])*10**scale+int((tail+'0'*scale)[:scale] or '0')
    return -value if negative else value


def decimal_text(value,scale):
    if type(value) is not int or type(scale) is not int or not 0<=scale<=18:
        raise ValueError('integer units and integer scale required')
    sign='-' if value<0 else '';whole,tail=divmod(abs(value),10**scale)
    fraction=(str(tail).zfill(scale).rstrip('0') if scale else '')
    return sign+str(whole)+('.'+fraction if fraction else '')


def balances(world,cut,corrections=(),exclude=()):
    """Apply valid net quantities at original positions; exclude only explicit plan IDs."""
    corrections=list(corrections);by_target={c['target']:c for c in corrections}
    if len(by_target)!=len(corrections): raise ValueError('oracle accepts one valid correction per target')
    known={e['ref'] for e in world['events']}
    if not set(by_target)<=known: raise ValueError('unknown oracle correction target')
    ledgers={a:{'investors':dict(v['investors']),'custody':dict(v['custody'])} for a,v in world['opening'].items()}
    for event in sorted(world['events'],key=lambda e:(e['at'],e['sequence'],e['ref'])):
        if event['at']>cut or event['ref'] in exclude: continue
        q=event['units'];c=by_target.get(event['ref'])
        if c:
            if c['mode']=='VOID':q=0
            elif c['mode']=='REPLACE':q=c['units']
            else:raise ValueError('unsupported oracle correction')
        if type(q) is not int or q<0 or (q==0 and not c):raise ValueError('invalid economic quantity')
        if c and c['mode']=='REPLACE' and q<=0:raise ValueError('replacement must be positive')
        ledger=ledgers[event['asset']]
        if event['sender'] is not None:ledger['investors'][event['sender']]-=q
        if event['recipient'] is not None:ledger['investors'][event['recipient']]+=q
        if event['kind'] in ('deposit','withdrawal'):
            ledger['custody'][event['custody']]+=q if event['kind']=='deposit' else -q
        elif event['kind']!='transfer':raise ValueError('unknown economic event')
        if min(ledger['investors'].values())<0 or min(ledger['custody'].values())<0:
            raise ValueError('world has insufficient economic balances; never clip to zero')
    for ledger in ledgers.values():ledger['liability']=sum(ledger['investors'].values())
    return ledgers


def financial_text(world,ledger):
    return {a:{'investor_balances':{i:decimal_text(q,world['assets'][a]) for i,q in v['investors'].items()},
               'liability':decimal_text(v['liability'],world['assets'][a]),
               'custody_rollforward':{k:decimal_text(q,world['assets'][a]) for k,q in v['custody'].items()}} for a,v in ledger.items()}


def expectations(world,cut,knowledge,available,reported,states=None,reasons=None):
    """Finite scenario table: state overrides are explicit experiment claims."""
    states=states or {};reasons=reasons or {};rows=[]
    for asset in sorted(world['assets']):
        scale=world['assets'][asset]
        for comparison,scope in [('A',i) for i in world['investors']]+[('B','customer_liability')]:
            expected=available[asset]['investors'][scope] if comparison=='A' else available[asset]['liability']
            if comparison=='A':observed=reported[asset]['investors'][scope]
            else:
                custody=list(reported[asset]['custody'].values())
                observed=None if any(q is None for q in custody) else sum(custody)
            difference=None if expected is None or observed is None else expected-observed
            data=states.get((asset,comparison,scope),states.get((asset,comparison),states.get(asset,'COMPLETE')))
            outcome='NOT_EVALUATED' if data!='COMPLETE' else ('MATCHED' if difference==0 else 'MISMATCH')
            rows.append(dict(asset=asset,comparison=comparison,scope=scope,balance_at=cut,knowledge_at=knowledge,
                             data_state=data,reconciliation_state=outcome,provisional=data!='COMPLETE',
                             expected=None if expected is None else decimal_text(expected,scale),
                             reported=None if observed is None else decimal_text(observed,scale),
                             difference=None if difference is None else decimal_text(difference,scale),
                             required_codes=reasons.get((asset,comparison),reasons.get(asset,[]))))
    return rows
