"""Stored-export integrity checks, deliberately not a financial resolver."""
from datetime import datetime, timezone
import hashlib
import json
import re

RULE_SCHEMAS = {0: frozenset({'stage1-v1'}), 2: frozenset({'stage1-v1', 'stage2-v1', 'stage2-v2'}), 3: frozenset({'stage1-v1', 'stage2-v1', 'stage2-v2'})}
AMOUNT = re.compile(r'-?[0-9]+(?:\.[0-9]+)?\Z')
UTC_TIME = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)\Z')


class ReviewError(ValueError):
    """A controlled export failure with a source/run and preservation audit."""
    def __init__(self, code, message, *, alias=None, run_id=None, audit=None):
        self.code, self.message = code, message
        self.alias, self.run_id, self.audit = alias, run_id, audit
        super().__init__(f'{code}: {message}' + (f' [source={alias}, run={run_id}]' if alias or run_id else ''))

    def as_dict(self):
        return {'code': self.code, 'message': self.message, 'source_alias': self.alias,
                'run_id': self.run_id, 'audit': self.audit}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def digest(value):
    """The existing content-ID contract, with no injected run_id wrapper."""
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f'duplicate JSON member: {key}')
        result[key] = value
    return result


def strict_json(text):
    return json.loads(text, object_pairs_hook=_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON constant: ' + value)))


def utc_key(value):
    if not isinstance(value, str) or not UTC_TIME.fullmatch(value):
        raise ValueError('stored UTC ISO timestamp required')
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value, name):
    _require(isinstance(value, str) and bool(value), name + ' must be a nonempty string')


def _quantity(value, name):
    _require(value is None or isinstance(value, str) and AMOUNT.fullmatch(value), name + ' must be decimal text or null')


def _amount_map(value, name):
    _require(isinstance(value, dict), name + ' must be an object')
    for key, amount in value.items():
        _text(key, name + ' scope'); _quantity(amount, name + '.' + key)


def _refs(value, name, evidence, kinds=None):
    _require(isinstance(value, list) and all(isinstance(x, str) for x in value), name + ' must be a string list')
    for key in value:
        _require(key in evidence, name + ' references absent run evidence: ' + key)
        if kinds is not None:
            _require(next(iter(evidence[key])) in kinds or ('record' in evidence[key] and 'record' in kinds), name + ' references the wrong evidence kind: ' + key)


def _record_refs(refs, name, evidence, kind, asset=None):
    _refs(refs, name, evidence, {'record'})
    for key in refs:
        record = evidence[key]['record']
        _require(record.get('kind') == kind, name + ' references the wrong saved record kind')
        if asset is not None:
            _require(record.get('asset') == asset, name + ' references the wrong saved asset')


def _issues(issues, evidence):
    _require(isinstance(issues, list), 'issues must be a list')
    for issue in issues:
        _require(isinstance(issue, dict), 'issue must be an object')
        _text(issue.get('code'), 'issue code'); _text(issue.get('state'), 'issue state')
        if 'evidence_ids' in issue:
            _refs(issue['evidence_ids'], 'issue.evidence_ids', evidence)
        if 'observations' in issue:
            _require(isinstance(issue['observations'], list), 'observations must be a list')
            for observation in issue['observations']:
                _require(isinstance(observation, dict), 'observation must be an object')
                if 'event_id' in observation:
                    _refs([observation['event_id']], 'observation.event_id', evidence, {'record'})


def _group(group, evidence):
    _require(isinstance(group, dict), 'correction group must be an object')
    for name in ('id', 'correction_record_id', 'target_record_id'):
        _text(group.get(name), 'group.' + name)
        _refs([group[name]], 'group.' + name, evidence)
    _record_refs([group['target_record_id']], 'group.target_record_id', evidence, 'event')
    _record_refs([group['correction_record_id']], 'group.correction_record_id', evidence, 'correction')
    _require('derived_correction_group' in evidence[group['id']], 'group ID must reference derived group evidence')
    _require(canonical(evidence[group['id']]['derived_correction_group']) == canonical(group), 'ledger/evidence correction group mismatch')
    _refs(group.get('manifest_ids'), 'group.manifest_ids', evidence, {'record'})
    utc_key(group.get('occurred_at')); utc_key(group.get('first_known_at'))
    for name in ('original_amount', 'effective_amount'):
        _quantity(group.get(name), 'group.' + name)
    _text(group.get('mode'), 'group.mode')
    _require(isinstance(group.get('effects'), list), 'group.effects must be a list')
    for effect in [group.get('original_effect'), group.get('net_effect'), *group['effects']]:
        _require(isinstance(effect, dict), 'group effect must be an object')
        _amount_map(effect.get('investor_deltas'), 'effect.investor_deltas')
        _quantity(effect.get('custody_delta'), 'effect.custody_delta')


def validate_payload(text, run_id, schema_version, *, alias=None):
    """Check identity, structure and saved references; never recalculate amounts."""
    try:
        payload = strict_json(text)
        _require(isinstance(payload, dict), 'run payload must be an object')
        _require('run_id' not in payload, 'saved runs.payload must not contain a run_id wrapper')
        _require(digest(payload) == run_id, 'runs.id differs from digest(parsed saved payload)')
        _require(schema_version in RULE_SCHEMAS, 'unsupported physical schema')
        _require(payload.get('rule_version') in RULE_SCHEMAS[schema_version], 'unsupported rule/payload format for schema')
        _require(set(payload) == {'rule_version', 'configuration', 'balance_at', 'knowledge_at', 'ledgers', 'findings', 'evidence'}, 'unknown run payload fields or missing required fields')
        utc_key(payload['balance_at']); utc_key(payload['knowledge_at'])
        config = payload['configuration']
        _require(isinstance(config, dict) and set(config) == {'platform', 'custodian', 'investors', 'assets', 'opening_at'}, 'unsupported saved configuration structure')
        for name in ('platform', 'custodian'):
            _text(config[name], 'configuration.' + name)
        utc_key(config['opening_at'])
        investors, assets = config['investors'], config['assets']
        _require(isinstance(investors, list) and investors and all(isinstance(x, str) and x for x in investors) and len(investors) == len(set(investors)), 'invalid saved investor roster')
        _require(isinstance(assets, dict) and assets and all(isinstance(k, str) and k and type(v) is int and 0 <= v <= 18 for k, v in assets.items()), 'invalid saved asset precision map')
        evidence = payload['evidence']
        _require(isinstance(evidence, dict), 'evidence must be an object')
        for eid, entry in evidence.items():
            _text(eid, 'evidence ID'); _require(isinstance(entry, dict), 'evidence entry must be an object')
            if 'record' in entry:
                _require(set(entry) == {'record', 'logical_key', 'receipt_ids'}, 'unsupported record evidence structure')
                record = entry['record']; _require(isinstance(record, dict), 'saved normalized record must be an object')
                _text(record.get('kind'), 'record.kind'); _text(entry['logical_key'], 'logical_key')
                _require(record['kind'] in {'opening', 'event', 'report', 'manifest', 'correction', 'correction_manifest'}, 'unsupported saved normalized record kind')
                if record['kind'] in {'opening', 'event', 'report'}:
                    _require(isinstance(record.get('amount'), str), 'saved normalized amount must be decimal text'); _quantity(record['amount'], 'record.amount')
                if 'replacement_amount' in record:
                    _quantity(record['replacement_amount'], 'record.replacement_amount')
            else:
                _require(len(entry) == 1 and next(iter(entry)) in {'receipt', 'quarantined_receipt', 'derived_correction_group'}, 'unsupported evidence envelope')
                _require(isinstance(next(iter(entry.values())), dict), 'evidence envelope body must be an object')
        for entry in evidence.values():
            if 'record' in entry:
                _refs(entry['receipt_ids'], 'record.receipt_ids', evidence, {'receipt'})
        findings, ledgers = payload['findings'], payload['ledgers']
        _require(isinstance(findings, list), 'findings must be a list')
        _require(isinstance(ledgers, dict) and set(ledgers) == set(assets), 'ledger asset coverage differs from saved configuration')
        seen = set()
        for finding in findings:
            _require(isinstance(finding, dict), 'finding must be an object')
            comparison, asset, scope = finding.get('comparison'), finding.get('asset'), finding.get('scope')
            _require(comparison in ('A', 'B') and isinstance(asset, str) and asset in assets and isinstance(scope, str), 'invalid finding key')
            _require(scope in investors if comparison == 'A' else scope == 'customer_liability', 'finding scope differs from saved configuration')
            key = comparison, asset, scope
            _require(key not in seen, 'duplicate finding key'); seen.add(key)
            for name in ('data_state', 'reconciliation_state'):
                _text(finding.get(name), 'finding.' + name)
            _require(type(finding.get('provisional')) is bool, 'finding.provisional must be boolean')
            for name in ('expected', 'reported', 'difference'):
                _require(name in finding, 'finding lacks ' + name); _quantity(finding[name], 'finding.' + name)
            _require(finding.get('difference_direction') == 'expected_minus_reported', 'unsupported difference direction')
            for name in ('balance_at', 'knowledge_at', 'rule_version'):
                _require(finding.get(name) == payload[name], 'finding/run metadata mismatch: ' + name)
            _require(finding.get('platform') == config['platform'], 'finding platform differs from its saved configuration')
            for name in ('event_ids', 'report_ids', 'evidence_ids'):
                _refs(finding.get(name), 'finding.' + name, evidence)
            _record_refs(finding['event_ids'], 'finding.event_ids', evidence, 'event', asset)
            _record_refs(finding['report_ids'], 'finding.report_ids', evidence, 'report', asset)
            if payload['rule_version'] == 'stage1-v1':
                _require('correction_ids' not in finding, 'Stage 1 has no correction fields')
            else:
                _record_refs(finding.get('correction_ids'), 'finding.correction_ids', evidence, 'correction', asset)
            _require(set(finding['event_ids'] + finding['report_ids'] + finding.get('correction_ids', [])) <= set(finding['evidence_ids']), 'finding record references are absent from its evidence links')
            _issues(finding.get('issues'), evidence)
        expected_keys = {('A', a, i) for a in assets for i in investors} | {('B', a, 'customer_liability') for a in assets}
        _require(seen == expected_keys, 'finding coverage differs from saved configuration')
        for asset, ledger in ledgers.items():
            _require(isinstance(ledger, dict), 'ledger must be an object')
            _record_refs(ledger.get('opening_record_ids'), 'ledger.opening_record_ids', evidence, 'opening', asset)
            _record_refs(ledger.get('event_ids'), 'ledger.event_ids', evidence, 'event', asset)
            for name in ('opening_amounts', 'investor_balances', 'custody_rollforward'):
                _amount_map(ledger.get(name), 'ledger.' + name)
            _require(set(ledger['investor_balances']) == set(investors), 'ledger investor coverage differs from saved configuration')
            _text(ledger.get('data_state'), 'ledger.data_state')
            _quantity(ledger.get('liability'), 'ledger.liability'); _issues(ledger.get('issues'), evidence)
            _require(isinstance(ledger.get('trace'), list), 'ledger.trace must be a list')
            for row in ledger['trace']:
                _require(isinstance(row, dict), 'trace row must be an object')
                _record_refs([row.get('event_id')], 'trace.event_id', evidence, 'event', asset)
                utc_key(row.get('occurred_at'))
                _require(type(row.get('sequence')) is int and row['sequence'] >= 0, 'trace sequence must be a nonnegative integer')
                _amount_map(row.get('investor_deltas'), 'trace.investor_deltas'); _amount_map(row.get('balances_after'), 'trace.balances_after')
                _quantity(row.get('custody_delta'), 'trace.custody_delta')
                if payload['rule_version'] == 'stage1-v1':
                    _require('correction_group_id' not in row, 'Stage 1 has no correction trace field')
                if row.get('correction_group_id') is not None:
                    _refs([row['correction_group_id']], 'trace.correction_group_id', evidence, {'derived_correction_group'})
            _require([row['event_id'] for row in ledger['trace']] == ledger['event_ids'], 'trace rows and saved event order disagree')
            if payload['rule_version'] == 'stage1-v1':
                _require(not {'correction_groups', 'correction_deliveries'} & set(ledger), 'Stage 1 has no correction ledger fields')
            else:
                _require(isinstance(ledger.get('correction_groups'), list), 'correction_groups must be a list')
                _require(isinstance(ledger.get('correction_deliveries'), list), 'correction_deliveries must be a list')
                for group in ledger['correction_groups']:
                    _group(group, evidence)
                for delivery in ledger['correction_deliveries']:
                    _require(isinstance(delivery, dict), 'correction delivery must be an object')
                    for name in ('manifest_ids', 'applied_correction_ids'):
                        _refs(delivery.get(name), 'delivery.' + name, evidence, {'record'})
                    _issues(delivery.get('issues'), evidence)
        return payload
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        if isinstance(exc, ReviewError):
            raise
        raise ReviewError('RUN_INTEGRITY', str(exc), alias=alias, run_id=run_id) from exc


def object_member_texts(text):
    """Return exact JSON value slices, preserving original numeric/string spelling."""
    decoder = json.JSONDecoder(object_pairs_hook=_pairs)
    i = 0
    while i < len(text) and text[i].isspace(): i += 1
    if i == len(text) or text[i] != '{': raise ValueError('JSON object expected')
    i += 1; result = {}
    while True:
        while text[i].isspace(): i += 1
        if text[i] == '}': return result
        key, i = decoder.raw_decode(text, i)
        while text[i].isspace(): i += 1
        if text[i] != ':': raise ValueError('JSON member separator expected')
        i += 1
        while text[i].isspace(): i += 1
        start = i; _, i = decoder.raw_decode(text, i)
        result[key] = text[start:i]
        while text[i].isspace(): i += 1
        if text[i] == '}': return result
        if text[i] != ',': raise ValueError('JSON object separator expected')
        i += 1
