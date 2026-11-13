"""Independent small recovery oracle: direct SQL observations and literal quantities.

No admission runtime, financial normalization, engine, or cursor helper is imported.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3


def _proof_value(value):
    def safe(item):
        if isinstance(item, bytes):
            return {'binary_bytes': len(item), 'sha256': hashlib.sha256(item).hexdigest()}
        if isinstance(item, dict):
            return {k: safe(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [safe(v) for v in item]
        return item
    value = safe(value)
    data = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
    if len(data) > 4096:
        return {'representation': 'canonical JSON check value', 'bytes': len(data),
                'sha256': hashlib.sha256(data).hexdigest()}
    return value


def check(name, actual, expected):
    return {'name': name, 'passed': actual == expected,
            'expected': _proof_value(expected), 'actual': _proof_value(actual)}


def observed(path):
    """Read a closed, already recovered database; never invoke Store or migrate."""
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        streams = [dict(r) for r in db.execute('SELECT * FROM admission_streams ORDER BY stream_id')]
        effects = [dict(r) for r in db.execute('SELECT * FROM delivery_effects ORDER BY stream_id,sequence')]
        attempts = [dict(r) for r in db.execute('SELECT * FROM delivery_attempts ORDER BY id')]
        receipts = [dict(r) for r in db.execute('SELECT * FROM receipts ORDER BY id')]
        records = [dict(r) for r in db.execute('SELECT * FROM records ORDER BY id')]
        runs = {r['id']: r['payload'] for r in db.execute('SELECT id,payload FROM runs ORDER BY id')}
        run_tables = {}
        for table in ('runs', 'findings', 'evidence', 'correction_groups', 'correction_effects'):
            rows = [list(r) for r in db.execute('SELECT * FROM ' + table)]
            run_tables[table] = sorted(rows, key=lambda r: json.dumps(r, sort_keys=True))
        return {'streams': streams, 'effects': effects, 'attempts': attempts,
                'receipts': receipts, 'records': records, 'runs': runs, 'run_tables': run_tables,
                'integrity_check': db.execute('PRAGMA integrity_check').fetchone()[0],
                'foreign_key_check': [list(r) for r in db.execute('PRAGMA foreign_key_check')],
                'journal_mode': db.execute('PRAGMA journal_mode').fetchone()[0],
                'synchronous': db.execute('PRAGMA synchronous').fetchone()[0]}
    finally:
        db.close()


def delivery_checks(actual, expected_streams, *, receipt_count, record_count,
                    core_statuses, blocked=(), attempt_counts=None):
    """Expected streams map to the literal first byte payloads, not runtime results."""
    checks = [check('exact_immutable_stream_inventory', sorted(r['stream_id'] for r in actual['streams']), sorted(expected_streams)),
              check('sqlite_integrity', actual['integrity_check'], 'ok'),
              check('sqlite_foreign_keys', actual['foreign_key_check'], []),
              check('rollback_journal', actual['journal_mode'], 'delete'),
              check('full_synchronous', actual['synchronous'], 2),
              check('physical_core_receipts', len(actual['receipts']), receipt_count),
              check('unique_normalized_records', len(actual['records']), record_count),
              check('core_receipt_status_counts', dict(Counter(r['status'] for r in actual['receipts'])), core_statuses)]
    receipts = {r['id']: r for r in actual['receipts']}
    effects = {(r['stream_id'], r['sequence']): r for r in actual['effects']}
    wanted = {(stream, i): payload for stream, payloads in expected_streams.items()
              for i, payload in enumerate(payloads, 1)}
    checks.append(check('exact_effect_identity_inventory', sorted(effects), sorted(wanted)))
    links_ok = True
    contents_ok = True
    for key, payload in wanted.items():
        effect = effects.get(key)
        if effect is None:
            links_ok = contents_ok = False
            continue
        contents_ok &= (effect['payload'] == payload and
                        effect['payload_sha256'] == hashlib.sha256(payload).hexdigest())
        if effect['disposition'] == 'REJECTED_FRAME':
            links_ok &= effect['core_receipt_id'] is None and effect['core_result'] is None
            continue
        receipt = receipts.get(effect['core_receipt_id'])
        if not receipt:
            links_ok = False
            continue
        result = json.loads(effect['core_result'])
        links_ok &= (receipt['receipt_hash'] == effect['core_receipt_hash'] == result['receipt_id']
                     and receipt['status'] == effect['disposition'] == result['status']
                     and receipt['record_id'] == result['record_id'] and receipt['error'] == result['error']
                     and json.loads(receipt['raw']) == json.loads(payload))
    checks += [check('first_payload_exact_bytes_and_hash', bool(contents_ok), True),
               check('effect_core_receipt_result_links', bool(links_ok), True),
               check('one_distinct_core_row_per_effect',
                     len({r['core_receipt_id'] for r in actual['effects'] if r['core_receipt_id'] is not None}),
                     sum(r['core_receipt_id'] is not None for r in actual['effects']))]
    for stream, payloads in expected_streams.items():
        sequences = sorted(r['sequence'] for r in actual['effects'] if r['stream_id'] == stream)
        prefix = 0
        for n in sequences:
            if n != prefix + 1:
                break
            prefix = n
        checks += [check('sequence_set:' + stream, sequences, list(range(1, len(payloads) + 1))),
                   check('contiguous_prefix:' + stream, prefix, len(payloads))]
    actual_blocked = sorted({r['stream_id'] for r in actual['attempts']
                             if r['outcome'] in ('TRANSPORT_CONFLICT', 'PLAN_CONFLICT')})
    checks.append(check('blocked_stream_inventory', actual_blocked, sorted(blocked)))
    attempt_links = all((r['effect_stream_id'] is None and r['effect_sequence'] is None) or
                        (r['effect_stream_id'], r['effect_sequence']) in effects
                        for r in actual['attempts'])
    checks += [check('attempt_effect_links', attempt_links, True),
               check('attempt_exact_byte_hashes', all(hashlib.sha256(r['payload']).hexdigest() == r['payload_sha256']
                                                     for r in actual['attempts']), True)]
    if attempt_counts is not None:
        checks.append(check('attempt_outcome_counts', dict(Counter(r['outcome'] for r in actual['attempts'])), attempt_counts))
    return checks


def financial_checks(result, variant='clean'):
    """Hand-calculated references, independent of both transport and financial code."""
    expected = {
        'ASSET_A': {'investor_balances': {'I1': '7', 'I2': '4'}, 'liability': '11',
                    'custody_rollforward': {'platform': '2', 'external': '9'}, 'data_state': 'COMPLETE'},
        'ASSET_B': {'investor_balances': {'I1': '0.3', 'I2': '0.2'}, 'liability': '0.5',
                    'custody_rollforward': {'platform': '0.05', 'external': '0.45'}, 'data_state': 'COMPLETE'}}
    differences = ['0', '0', '0', '0', '0', '0']
    if variant == 'custody_difference':
        differences[2] = '1'
    elif variant == 'economic_conflict':
        expected['ASSET_A'] = {'investor_balances': {'I1': '5', 'I2': '4'}, 'liability': '9',
                               'custody_rollforward': {'platform': '2', 'external': '7'}, 'data_state': 'CONFLICT'}
        differences[:3] = ['-2', '0', '-2']
    elif variant == 'invalid_payload':
        expected['ASSET_A']['data_state'] = 'INCOMPLETE'
    elif variant == 'corrected':
        expected['ASSET_A'] = {'investor_balances': {'I1': '8', 'I2': '4'}, 'liability': '12',
                               'custody_rollforward': {'platform': '2', 'external': '10'}, 'data_state': 'COMPLETE'}
    elif variant != 'clean':
        raise ValueError('unknown literal financial reference')
    checks = []
    for asset, reference in expected.items():
        checks.append(check('literal_ledger:' + asset, {k: result['ledgers'][asset][k] for k in reference}, reference))
    findings = result['findings']
    wanted_keys = [(a, c, s) for a in ('ASSET_A', 'ASSET_B') for c, s in
                   (('A', 'I1'), ('A', 'I2'), ('B', 'customer_liability'))]
    checks.append(check('financial_finding_inventory', [(r['asset'], r['comparison'], r['scope']) for r in findings], wanted_keys))
    for i, key in enumerate(wanted_keys):
        rows = [r for r in findings if (r['asset'], r['comparison'], r['scope']) == key]
        data_state = expected[key[0]]['data_state']
        reconciliation = ('NOT_EVALUATED' if data_state != 'COMPLETE' else
                          'MATCHED' if differences[i] == '0' else 'MISMATCH')
        value = {k: rows[0][k] for k in ('data_state', 'reconciliation_state', 'difference')} if len(rows) == 1 else None
        checks.append(check('literal_finding:' + ':'.join(key), value,
                            {'data_state': data_state, 'reconciliation_state': reconciliation, 'difference': differences[i]}))
    return checks


def negative_control():
    """A test double promises a committed prefix while storing no effects/receipts."""
    empty = {'streams': [], 'effects': [], 'attempts': [], 'receipts': [], 'records': [],
             'integrity_check': 'ok', 'foreign_key_check': [], 'journal_mode': 'delete', 'synchronous': 2}
    checks = delivery_checks(empty, {'broken': [b'{"record":{},"received_at":"synthetic"}\n']},
                             receipt_count=1, record_count=1, core_statuses={'ACCEPTED': 1})
    rejected = [c['name'] for c in checks if not c['passed']]
    required = {'exact_effect_identity_inventory', 'physical_core_receipts',
                'unique_normalized_records', 'contiguous_prefix:broken', 'effect_core_receipt_result_links'}
    return {'status': 'EXPECTED_FAILURE' if required <= set(rejected) else 'FAILED',
            'model': 'test double: early ACK / cursor 1 with no durable effect or receipt',
            'claimed_ack': True, 'claimed_cursor': 1, 'rejected_checks': rejected, 'checks': checks,
            'models': [{'name': name, 'observed_status': 'FAIL' if required <= set(rejected) else 'PASS',
                        'rejected_checks': rejected}
                       for name in ('premature_ack', 'empty_cursor')]}


def record_inventory_checks(actual, variant='clean'):
    """Literal economic input coverage; no call to normalize or the calculator."""
    records = [json.loads(r['payload']) for r in actual['records']]
    if variant in ('prefix1', 'prefix8'):
        kinds = {'opening': 1 if variant == 'prefix1' else 8}
        events = []
    else:
        kinds = {'opening': 8, 'event': 4, 'report': 8, 'manifest': 10}
        events = [
            ['ASSET_A', 'A1', 'transfer', 'I1', 'I2', None, '1'],
            ['ASSET_A', 'A2', 'deposit', None, 'I1', 'external', '2'],
            ['ASSET_A', 'A3', 'withdrawal', 'I2', None, 'external', '1'],
            ['ASSET_B', 'B1', 'deposit', None, 'I1', 'external', '0.2']]
        if variant == 'economic_conflict':
            kinds['event'] = 5
            events.append(['ASSET_A', 'A2', 'deposit', None, 'I1', 'external', '3'])
        if variant == 'corrected':
            kinds.update(report=10, correction=1, correction_manifest=1)
    facts = [[r[k] for k in ('asset', 'ref', 'type', 'from_investor', 'to_investor', 'custody', 'amount')]
             for r in records if r['kind'] == 'event']
    order = lambda row: json.dumps(row, sort_keys=True)
    ids = {r['id'] for r in actual['records']}
    hashes_ok = all(hashlib.sha256(json.dumps(json.loads(r['payload']), sort_keys=True,
        separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()).hexdigest() == r['id']
        for r in actual['records'])
    return [check('literal_record_kind_inventory', dict(Counter(r['kind'] for r in records)), kinds),
            check('literal_economic_event_inventory', sorted(facts, key=order), sorted(events, key=order)),
            check('normalized_record_content_ids', hashes_ok, True),
            check('core_receipt_record_inventory_links', all(r['record_id'] is None or r['record_id'] in ids
                                                            for r in actual['receipts']), True)]
