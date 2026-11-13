"""Lossless text plus narrowly typed display fields for the offline UI."""
from datetime import datetime, timezone
import re
from .validation import canonical, digest, utc_key

RECEIVED = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)\Z')


def _display(value):
    if value is None or isinstance(value, str): return value
    return canonical(value)


def _pairs(value):
    return [{'scope': scope, 'amount': amount} for scope, amount in value.items()]


def _issue(value):
    return {'code': value['code'], 'state': value['state'], 'raw_text': canonical(value),
            'evidence_ids': list(value.get('evidence_ids', []))}


def _effect(value):
    result = {'investor_deltas': _pairs(value['investor_deltas']),
              'custody_location': value.get('custody_location'), 'custody_delta': value['custody_delta'],
              'raw_text': canonical(value)}
    if 'role' in value: result['role'] = value['role']
    return result


def _received(body):
    if 'received_at' not in body: return None, None
    raw = body['received_at']; original = canonical(raw)
    if not isinstance(raw, str) or not RECEIVED.fullmatch(raw): return None, original
    try:
        value = datetime.fromisoformat(raw.replace('Z', '+00:00')).astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
        return value, original
    except ValueError:
        return None, original


def _evidence(eid, value, raw_text):
    kind = 'record' if 'record' in value else next(iter(value))
    body = value[kind]
    received, received_raw = _received(body) if kind in {'receipt', 'quarantined_receipt'} else (None, None)
    result = {'id': eid, 'kind': kind, 'raw_text': raw_text,
              'fields': [{'name': name, 'value': _display(item)} for name, item in body.items()],
              'receipt_ids': list(value.get('receipt_ids', [])),
              'received_at': received, 'received_at_raw_text': received_raw}
    if kind == 'record': result['record_id'] = eid
    return result


def _ledger(value):
    result = {'opening_amounts': _pairs(value['opening_amounts']),
              'opening_record_ids': list(value['opening_record_ids']),
              'event_ids': list(value['event_ids']),
              'investor_balances': _pairs(value['investor_balances']),
              'liability': value['liability'], 'custody_rollforward': _pairs(value['custody_rollforward']),
              'data_state': value['data_state'], 'issues': [_issue(x) for x in value['issues']], 'trace': []}
    for row in value['trace']:
        trace = {'event_id': row['event_id'], 'occurred_at': row['occurred_at'],
                 'sequence': str(row['sequence']), 'investor_deltas': _pairs(row['investor_deltas']),
                 'balances_after': _pairs(row['balances_after']), 'custody_location': row.get('custody_location'),
                 'custody_delta': row['custody_delta'], 'raw_text': canonical(row)}
        if 'correction_group_id' in row: trace['correction_group_id'] = row['correction_group_id']
        result['trace'].append(trace)
    if 'correction_groups' in value:
        result['groups'] = []
        for group in value['correction_groups']:
            item = {key: group[key] for key in ('id', 'mode', 'target_record_id', 'correction_record_id', 'occurred_at', 'first_known_at', 'original_amount', 'effective_amount')}
            item.update(manifest_ids=list(group['manifest_ids']), effects=[_effect(x) for x in group['effects']],
                        original_effect=_effect(group['original_effect']), net_effect=_effect(group['net_effect']), raw_text=canonical(group))
            result['groups'].append(item)
    if 'correction_deliveries' in value:
        result['deliveries'] = [{'raw_text': canonical(x), 'manifest_ids': list(x['manifest_ids']),
                                'applied_correction_ids': list(x['applied_correction_ids']),
                                'issues': [_issue(i) for i in x['issues']]} for x in value['correction_deliveries']]
    return result


def build_run_view(saved):
    """No arbitrary raw objects/numbers cross into JSON.parse in the browser."""
    payload = saved.payload
    result = {'source_alias': saved.source_alias, 'source_label': saved.source_label,
              'run_id': saved.run_id, 'run_label': saved.run_label, 'schema_version': saved.schema_version,
              'rule_version': payload['rule_version'], 'balance_at': payload['balance_at'],
              'knowledge_at': payload['knowledge_at'], 'balance_sort_key': utc_key(payload['balance_at']),
              'knowledge_sort_key': utc_key(payload['knowledge_at']),
              'configuration_id': digest(payload['configuration']), 'configuration_text': canonical(payload['configuration']),
              'raw_payload': saved.payload_text, 'payload_sha256': saved.payload_sha256,
              'identity_validated': True, 'findings': [],
              'ledgers': {asset: _ledger(ledger) for asset, ledger in payload['ledgers'].items()},
              'evidence': {eid: _evidence(eid, value, saved.evidence_texts[eid]) for eid, value in payload['evidence'].items()}}
    fields = ('comparison', 'asset', 'scope', 'platform', 'data_state', 'reconciliation_state',
              'provisional', 'expected', 'reported', 'difference', 'difference_direction')
    for index, finding in enumerate(payload['findings']):
        item = {name: finding[name] for name in fields}
        item.update(key='finding-' + str(index), ordinal=index,
                    match_key=canonical([finding['comparison'], finding['asset'], finding['scope']]),
                    issues=[_issue(x) for x in finding['issues']])
        for name in ('event_ids', 'report_ids', 'evidence_ids', 'correction_ids'):
            if name in finding: item[name] = list(finding[name])
        result['findings'].append(item)
    return result
