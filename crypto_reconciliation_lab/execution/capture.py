"""Bounded physical input inventory in an already-owned SQLite transaction."""
from ..model import digest, normalize, timestamp
from .common import PROFILE, canonical, parse, require, sha256

MAX_RECEIPTS = 10000
MAX_ROWS = 50000
MAX_EPOCHS = 256
MAX_VALUE_BYTES = 4 * 1024 * 1024
MAX_CONTEXT_BYTES = 16 * 1024 * 1024
COLUMNS = {
    'records': 'id logical_key kind payload',
    'receipts': 'id receipt_hash record_id received_at raw error status',
    'admission_streams': 'stream_id input_sha256 input_bytes planned_lines framing plan_hash observed_at',
    'delivery_effects': 'stream_id sequence payload payload_sha256 core_receipt_id core_receipt_hash core_result disposition reason observed_at',
    'delivery_attempts': 'id stream_id sequence payload payload_sha256 plan_hash outcome effect_stream_id effect_sequence observed_at reason',
    'auth_configuration': 'id receiver configuration_digest initial_policy_hash',
    'auth_policy_snapshots': 'policy_hash payload',
    'auth_policy_activations': 'epoch policy_hash previous_epoch previous_hash observed_at',
    'auth_keys': 'key_id source public_key fingerprint first_epoch',
    'auth_streams': 'stream_id source receiver configuration_digest plan_hash',
    'auth_endorsements': 'id payload envelope source key_id fingerprint statement_hash snapshot_hash plan_hash',
    'auth_decisions': 'id epoch endorsement_id stream_id sequence decision current_key_status policy_hash observed_at',
    'auth_delivery_links': 'stream_id sequence decision_id core_receipt_id',
    'auth_attempt_links': 'attempt_id decision_id',
}
KEYS = {name: cols.split()[:1] for name, cols in COLUMNS.items()}
for _name in ('delivery_effects', 'auth_delivery_links'):
    KEYS[_name] = ['stream_id', 'sequence']
BLOBS = {'delivery_effects': {'payload'}, 'delivery_attempts': {'payload'},
         'auth_keys': {'public_key'}, 'auth_endorsements': {'payload', 'envelope'}}
SCOPE = {'profile': PROFILE, 'complete': True,
         'predicate': 'received_at <= knowledge_at OR received_at IS NULL',
         'excluded': ['future_receipts', 'receipt_free_positions', 'unrelated_attempts', 'auth_rejections']}


class Rows:
    """Inspect value lengths before fetching; closed SQL identifiers only."""
    def __init__(self, db):
        self.db, self.count, self.bytes = db, 0, 0

    def read(self, table, columns, where='', args=(), order='', cap=MAX_ROWS):
        columns = columns.split()
        suffix = (' WHERE ' + where if where else '') + (' ORDER BY ' + order if order else '')
        query = 'SELECT ' + ','.join('typeof(' + c + '),length(CAST(' + c + ' AS BLOB))' for c in columns)
        lengths = self.db.execute(query + ' FROM ' + table + suffix + ' LIMIT ?', (*args, cap + 1))
        count = 0
        for row in lengths:
            count += 1
            require(count <= cap and self.count + count <= MAX_ROWS, 'row limit exceeded', 'EXECUTION_LIMIT')
            for i in range(0, len(row), 2):
                require(row[i] in ('null', 'text', 'blob', 'integer'), 'unsupported SQL value type')
                require(row[i + 1] is None or row[i + 1] <= MAX_VALUE_BYTES, 'SQL value limit exceeded', 'EXECUTION_LIMIT')
        result = []
        for raw in self.db.execute('SELECT ' + ','.join(columns) + ' FROM ' + table + suffix + ' LIMIT ?', (*args, cap + 1)):
            item = dict(zip(columns, raw))
            for key, value in item.items():
                if type(value) is bytes:
                    require(key in BLOBS.get(table, set()), 'unexpected SQL BLOB')
                    item[key] = value.hex()
                elif key in BLOBS.get(table, set()):
                    require(False, 'required SQL BLOB missing')
            self.bytes += len(canonical(item))
            require(self.bytes <= MAX_CONTEXT_BYTES, 'inventory byte limit exceeded', 'EXECUTION_LIMIT')
            result.append(item)
        require(len(result) == count, 'inventory changed inside transaction')
        self.count += count
        return result


def capture_inputs(db, knowledge_at):
    require(db.in_transaction, 'capture requires owned transaction')
    reader = Rows(db)
    def rows(name, where='', args=(), cap=MAX_ROWS):
        return reader.read(name, COLUMNS[name], where, args, ','.join(KEYS[name]), cap)
    tables = {name: [] for name in COLUMNS}
    tables['receipts'] = rows('receipts', 'received_at<=? OR received_at IS NULL', (knowledge_at,), MAX_RECEIPTS)
    for rid in sorted({r['record_id'] for r in tables['receipts'] if r['record_id'] is not None}):
        tables['records'].extend(rows('records', 'id=?', (rid,)))
    for receipt in tables['receipts']:
        tables['delivery_effects'].extend(rows('delivery_effects', 'core_receipt_id=?', (receipt['id'],)))
    for sid in sorted({r['stream_id'] for r in tables['delivery_effects']}):
        tables['admission_streams'].extend(rows('admission_streams', 'stream_id=?', (sid,)))
        tables['auth_streams'].extend(rows('auth_streams', 'stream_id=?', (sid,)))
    for effect in tables['delivery_effects']:
        key = effect['stream_id'], effect['sequence']
        tables['delivery_attempts'].extend(rows('delivery_attempts', 'stream_id=? AND sequence=?', key))
        tables['auth_delivery_links'].extend(rows('auth_delivery_links', 'stream_id=? AND sequence=?', key))
    for attempt in tables['delivery_attempts']:
        tables['auth_attempt_links'].extend(rows('auth_attempt_links', 'attempt_id=?', (attempt['id'],)))
    for did in sorted({r['decision_id'] for name in ('auth_delivery_links', 'auth_attempt_links') for r in tables[name]}):
        tables['auth_decisions'].extend(rows('auth_decisions', 'id=?', (did,)))
    for eid in sorted({r['endorsement_id'] for r in tables['auth_decisions']}):
        tables['auth_endorsements'].extend(rows('auth_endorsements', 'id=?', (eid,)))
    tables['auth_configuration'] = rows('auth_configuration')
    tables['auth_policy_activations'] = rows('auth_policy_activations', cap=MAX_EPOCHS)
    tables['auth_keys'] = rows('auth_keys')
    for policy in sorted({r['policy_hash'] for r in tables['auth_policy_activations']}):
        tables['auth_policy_snapshots'].extend(rows('auth_policy_snapshots', 'policy_hash=?', (policy,)))
    for name in tables:
        tables[name].sort(key=lambda r: tuple(r[k] for k in KEYS[name]))
    return tables


def evidence_mapping(tables, run):
    records = {r['id']: r for r in tables['records']}
    by_hash = {}
    for row in tables['receipts']:
        by_hash.setdefault(row['receipt_hash'], []).append(row)
    result = {}
    for eid, entry in run['evidence'].items():
        record_ids, hashes = [], []
        if 'record' in entry:
            require(eid in records and parse(records[eid]['payload'].encode(), MAX_VALUE_BYTES) == entry['record']
                    and records[eid]['logical_key'] == entry['logical_key'], 'selected record absent or changed')
            record_ids, hashes = [eid], entry['receipt_ids']
        elif 'receipt' in entry:
            hashes = [eid]
            require(digest(entry['receipt']) == eid, 'selected receipt identity differs')
        elif 'quarantined_receipt' in entry:
            hashes = [eid]
        elif 'derived_correction_group' in entry:
            group = entry['derived_correction_group']
            record_ids = sorted({group['correction_record_id'], group['target_record_id']})
            require(all(rid in records for rid in record_ids), 'derived correction input is absent')
            hashes = sorted({r['receipt_hash'] for r in tables['receipts'] if r['record_id'] in record_ids})
        require(all(h in by_hash for h in hashes), 'selected receipt is outside recorded inputs')
        physical = [r for h in hashes for r in by_hash[h]]
        if 'record' in entry:
            require(all(r['record_id'] == eid for r in physical), 'selected record/receipt binding differs')
        result[eid] = {'record_ids': record_ids, 'receipt_ids': sorted({r['id'] for r in physical})}
    return result


def claims(tables):
    protected = bool(tables['auth_configuration'])
    return {'context_state': 'RECORDED', 'admission_mode': 'PROTECTED' if protected else 'LEGACY',
            'legacy_signature_status': 'NOT_APPLICABLE' if protected else 'UNSIGNED',
            'source_signature_verification': 'NOT_PERFORMED', 'run_actor_authorization': 'NOT_DEFINED'}


def validate_inventory(tables, configuration, knowledge_at):
    """Internal references only; never enrich old context from current SQL."""
    require(type(tables) is dict and set(tables) == set(COLUMNS), 'incomplete table inventory')
    require(sum(len(v) for v in tables.values()) <= MAX_ROWS and len(tables['receipts']) <= MAX_RECEIPTS
            and len(tables['auth_policy_activations']) <= MAX_EPOCHS, 'inventory row limit', 'EXECUTION_LIMIT')
    indexes = {}
    for name, rows in tables.items():
        require(type(rows) is list, 'table inventory must be a list')
        keys = []
        for row in rows:
            require(type(row) is dict and set(row) == set(COLUMNS[name].split()), 'SQL row field coverage differs')
            for key, value in row.items():
                require(value is None or type(value) in (str, int), 'unsupported captured SQL type')
                if type(value) is str:
                    if key in BLOBS.get(name, set()):
                        require(len(value) <= MAX_VALUE_BYTES * 2, 'BLOB limit exceeded', 'EXECUTION_LIMIT')
                        require(bytes.fromhex(value).hex() == value, 'noncanonical BLOB encoding')
                    else:
                        require(len(value.encode()) <= MAX_VALUE_BYTES, 'TEXT limit exceeded', 'EXECUTION_LIMIT')
            keys.append(tuple(row[k] for k in KEYS[name]))
        require(keys == sorted(set(keys)), 'duplicate or unordered SQL identities')
        indexes[name] = dict(zip(keys, rows))
    records = {r['id']: r for r in tables['records']}
    receipts = {r['id']: r for r in tables['receipts']}
    require(set(records) == {r['record_id'] for r in receipts.values() if r['record_id'] is not None}, 'record coverage differs')
    for row in records.values():
        normalized = parse(row['payload'].encode(), MAX_VALUE_BYTES)
        value, key = normalize(normalized, configuration)
        require(digest(value) == row['id'] and value == normalized and key == row['logical_key']
                and value['kind'] == row['kind'], 'normalized record identity differs')
    for row in receipts.values():
        require(type(row['id']) is int and row['id'] > 0, 'invalid physical receipt identity')
        raw = parse(row['raw'].encode(), MAX_VALUE_BYTES)
        require(type(raw) is dict and set(raw) == {'record', 'received_at'} and digest(raw) == row['receipt_hash'], 'receipt content identity differs')
        require(row['received_at'] is None or (timestamp(row['received_at']) == row['received_at']
                and row['received_at'] <= knowledge_at and timestamp(raw['received_at']) == row['received_at']), 'receipt outside knowledge cut')
        require(row['status'] in ('ACCEPTED', 'DUPLICATE', 'CONFLICT', 'INVALID'), 'unknown receipt status')
        if row['record_id'] is not None:
            norm, _ = normalize(raw['record'], configuration)
            require(digest(norm) == row['record_id'] and row['status'] != 'INVALID' and row['error'] is None, 'receipt/record mismatch')
        else:
            require(row['status'] == 'INVALID' and isinstance(row['error'], str), 'invalid receipt lacks error')
    effects = indexes['delivery_effects']
    require({r['stream_id'] for r in tables['admission_streams']} == {k[0] for k in effects}, 'stream coverage differs')
    for key, effect in effects.items():
        receipt = receipts.get(effect['core_receipt_id'])
        require(receipt is not None and receipt['receipt_hash'] == effect['core_receipt_hash'], 'effect receipt link missing')
        require(sha256(bytes.fromhex(effect['payload'])) == effect['payload_sha256'], 'effect bytes differ')
        attempts = [r for r in tables['delivery_attempts'] if (r['stream_id'], r['sequence']) == key and r['outcome'] == 'COMMITTED']
        require(len(attempts) == 1 and attempts[0]['payload'] == effect['payload'] and
                (attempts[0]['effect_stream_id'], attempts[0]['effect_sequence']) == key, 'original COMMITTED effect missing')
    for attempt in tables['delivery_attempts']:
        key = attempt['stream_id'], attempt['sequence']
        require(type(attempt['id']) is int and attempt['id'] > 0 and key in effects, 'attempt outside captured positions')
        require(sha256(bytes.fromhex(attempt['payload'])) == attempt['payload_sha256'], 'attempt bytes differ')
        if attempt['outcome'] in ('COMMITTED', 'REPLAY'):
            require((attempt['effect_stream_id'], attempt['effect_sequence']) == key and attempt['payload'] == effects[key]['payload'], 'replay effect differs')
    decisions = {r['id']: r for r in tables['auth_decisions']}
    endorsements = {r['id']: r for r in tables['auth_endorsements']}
    links = tables['auth_delivery_links'] + tables['auth_attempt_links']
    require(set(decisions) == {r['decision_id'] for r in links}, 'decision coverage differs')
    require(set(endorsements) == {r['endorsement_id'] for r in decisions.values()}, 'endorsement coverage differs')
    for link in tables['auth_delivery_links']:
        effect = effects.get((link['stream_id'], link['sequence']))
        require(effect is not None and effect['core_receipt_id'] == link['core_receipt_id'], 'auth delivery effect differs')
    for link in tables['auth_attempt_links']:
        require((link['attempt_id'],) in indexes['delivery_attempts'], 'auth attempt link missing')
    activations = tables['auth_policy_activations']
    policies = {r['policy_hash']: r for r in tables['auth_policy_snapshots']}
    require(set(policies) == {r['policy_hash'] for r in activations}, 'policy coverage differs')
    for policy in policies.values():
        require(digest(parse(policy['payload'].encode(), MAX_VALUE_BYTES)) == policy['policy_hash'], 'policy bytes differ')
    previous = None
    for epoch in activations:
        require(type(epoch['epoch']) is int and epoch['epoch'] == (1 if previous is None else previous['epoch'] + 1)
                and epoch['previous_epoch'] == (None if previous is None else previous['epoch'])
                and epoch['previous_hash'] == (None if previous is None else previous['policy_hash']), 'policy activation chain differs')
        previous = epoch
    if tables['auth_configuration']:
        require(len(tables['auth_configuration']) == 1 and activations, 'protected configuration lacks activation')
        config = tables['auth_configuration'][0]
        require(config['configuration_digest'] == digest(configuration) and config['initial_policy_hash'] == activations[0]['policy_hash'], 'protected configuration differs')
        require(set(indexes['auth_streams']) == set(indexes['admission_streams']), 'protected stream coverage differs')
        require(set(indexes['auth_delivery_links']) == set(effects), 'protected effect decision missing')
        require(set(indexes['auth_attempt_links']) == set(indexes['delivery_attempts']), 'protected attempt decision missing')
        for decision in decisions.values():
            require((decision['epoch'],) in indexes['auth_policy_activations'] and
                    decision['policy_hash'] == indexes['auth_policy_activations'][(decision['epoch'],)]['policy_hash'], 'acceptance epoch missing')
        for endorsement in endorsements.values():
            key = indexes['auth_keys'].get((endorsement['key_id'],))
            require(key is not None and key['source'] == endorsement['source'] and key['fingerprint'] == endorsement['fingerprint'], 'endorsement key missing')
    else:
        require(not any(tables[name] for name in tables if name.startswith('auth_')), 'legacy inventory contains protected rows')
