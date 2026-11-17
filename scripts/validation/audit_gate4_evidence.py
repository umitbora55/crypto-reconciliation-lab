"""Independent Gate 4 input, raw-record and statistical review (stdlib only).

No application or research parser, normalization, arithmetic or statistics helper
is imported. The finite two-input contract is chosen before timed measurement.
This is consistency evidence, not institutional truth or a clock attestation.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import re
import resource
import sqlite3
import statistics
import subprocess
import sys
import time
import traceback

HEAD = 'c08114e847b8b0ab58f28d41917ba386878fa873'
METHODS = ('BASELINE', 'CANDIDATE_WAL_FULL')
INPUTS = {
    (10000, 11): (4596911, 'c246c488a9845ad11e9628fd647cb1fb826ec6bc797bd3684781f247801926c2',
                  'b54dab4b82461e339d7f898a2ffad66a0c9e59ec618bdbbf8dc6497fab08b160', 45),
    (25000, 29): (11516911, '8f8902a3e4970478da5d397d2141f7d534d2e097751d727578af38bbfb556a3f',
                  '736346fc7ed1f8cec3821b619082749844e962881dcd5a73627ccdbfd751bc8b', 22),
}
OPEN = '2026-01-02T00:00:00Z'
CUT = '2026-01-02T23:00:00Z'
KNOWN = '2026-01-03T00:00:00Z'
CONFIG = {'platform': 'P', 'custodian': 'C', 'investors': ['I0', 'I1', 'I2', 'I3'],
          'assets': {'UNIT': 2}, 'opening_at': OPEN}


def need(condition, message):
    if not condition:
        raise ValueError('GATE4_INDEPENDENT: ' + message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def proof(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def parse_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, 'duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON: ' + x)))


def load(path):
    return parse_json(Path(path).read_bytes())


def cents(text):
    need(type(text) is str and re.fullmatch(r'(?:0|[1-9][0-9]*)\.[0-9]{2}', text), 'integer cents syntax')
    whole, fractional = text.split('.')
    return int(whole) * 100 + int(fractional)


def money(value):
    return str(value // 100) + '.' + str(value % 100).zfill(2)


def expected_shape(events, seed):
    """Finite external schedule and explicitly stipulated final balances."""
    need((events, seed) in INPUTS, 'unregistered input identity')
    residual = INPUTS[events, seed][3]
    ending = {'I0': 10000, 'I1': 10000 + residual, 'I2': 10000, 'I3': 10000,
              'platform': 0, 'external': 40000 + residual}
    rows = []
    common = {'platform': 'P', 'source': 'P', 'asset': 'UNIT'}
    for scope in ('I0', 'I1', 'I2', 'I3', 'platform', 'external'):
        amount = 10000 if scope.startswith('I') else (0 if scope == 'platform' else 40000)
        rows.append({'received_at': OPEN, 'record': {**common, 'kind': 'opening',
                     'scope': scope, 'balance_at': OPEN, 'amount': money(amount)}})
    for seq in range(events):
        cycle, part = divmod(seq, 3)
        sender, recipient = f'I{cycle % 4}', f'I{(cycle + 1) % 4}'
        event_type = ('deposit', 'transfer', 'withdrawal')[part]
        rows.append({'received_at': KNOWN, 'record': {**common, 'kind': 'event',
            'business_day': '2026-01-02', 'occurred_at': '2026-01-02T12:00:00Z',
            'ref': f'E{seq}', 'sequence': seq, 'type': event_type,
            'amount': money((cycle * 17 + seed) % 99 + 1),
            'from_investor': None if part == 0 else sender if part == 1 else recipient,
            'to_investor': sender if part == 0 else recipient if part == 1 else None,
            'custody': None if part == 1 else 'external'}})
    for scope, value in ending.items():
        stream = 'investor' if scope.startswith('I') else f'{scope}_custody'
        rows.append({'received_at': KNOWN, 'record': {**common, 'kind': 'report',
            'source': 'C' if scope == 'external' else 'P', 'scope': scope, 'stream': stream,
            'balance_at': CUT, 'version': 1, 'amount': money(value)}})
    for stream, count, start, end in [('opening', 6, OPEN, OPEN), ('event', events, OPEN, CUT),
            ('investor', 4, CUT, CUT), ('platform_custody', 1, CUT, CUT), ('external_custody', 1, CUT, CUT)]:
        rows.append({'received_at': KNOWN, 'record': {**common, 'kind': 'manifest',
            'source': 'C' if stream == 'external_custody' else 'P', 'stream': stream,
            'coverage_from': start, 'coverage_to': end, 'expected_count': count}})
    return rows


def independent_fold(rows, events):
    balances, custody, reports, seen = {}, {}, {}, []
    for envelope in rows:
        row = envelope['record']
        kind = row['kind']
        if kind == 'manifest':
            continue
        amount = cents(row['amount'])
        if kind == 'opening':
            target = custody if row['scope'] in ('platform', 'external') else balances
            need(row['scope'] not in target, 'duplicate opening')
            target[row['scope']] = amount
        elif kind == 'event':
            seen.append(row['ref'])
            if row['from_investor'] is not None:
                balances[row['from_investor']] -= amount
            if row['to_investor'] is not None:
                balances[row['to_investor']] += amount
            if row['type'] == 'deposit':
                custody[row['custody']] += amount
            elif row['type'] == 'withdrawal':
                custody[row['custody']] -= amount
            else:
                need(row['type'] == 'transfer', 'unexpected movement type')
        elif kind == 'report':
            need(row['scope'] not in reports, 'duplicate report')
            reports[row['scope']] = amount
        else:
            raise ValueError('GATE4_INDEPENDENT: unexpected financial row')
    need(seen == [f'E{i}' for i in range(events)], 'event identity/order substitution')
    need(reports == {**balances, **custody}, 'reported balance differs from integer fold')
    liability = sum(balances.values())
    need(liability == sum(custody.values()), 'liability/custody imbalance')
    differences = {**{k: 0 for k in balances}, 'customer_liability': 0}
    return {'balances': balances, 'custody': custody, 'liability': liability,
            'differences': differences, 'outcomes': {k: 'MATCHED' for k in differences}}


def receipt_index(rows):
    """Encode this fixed wire contract independently, without general normalizer."""
    result = []
    for ordinal, envelope in enumerate(rows, 1):
        row = dict(envelope['record'])
        for key in ('balance_at', 'occurred_at', 'coverage_from', 'coverage_to'):
            if key in row:
                need(re.fullmatch(r'2026-01-02T[0-9]{2}:00:00Z', row[key]), 'finite timestamp scope')
                row[key] = row[key][:-1] + '.000000Z'
        if 'amount' in row:
            row['amount'] = row['amount'].rstrip('0').rstrip('.')
        kind = row['kind']
        key = [kind, row['source'], row['platform']]
        if kind == 'event':
            key += [row['business_day'], row['ref']]
        elif kind == 'manifest':
            key += [row['stream'], row['asset'], row['coverage_from'], row['coverage_to']]
        else:
            key += [row.get('stream', kind), row['asset'], row['scope'], row['balance_at']]
            if kind == 'report':
                key.append(row['version'])
        result.append({'ordinal': ordinal, 'receipt_id': digest(envelope), 'record_id': digest(row),
                       'logical_key': canonical(key).decode(), 'status': 'ACCEPTED', 'kind': kind})
    return result


def audit_input(path, events, seed):
    raw = Path(path).read_bytes()
    size, sha, ordered_pin, residual = INPUTS[events, seed]
    need(proof(raw) == {'bytes': size, 'sha256': sha}, 'input raw-byte pin')
    data = load(path)
    need(set(data) == {'balance_at', 'config', 'data_class', 'events', 'knowledge_at', 'rows', 'seed'},
         'input field inventory')
    need((data['events'], data['seed'], data['balance_at'], data['knowledge_at'], data['config'], data['data_class'])
         == (events, seed, CUT, KNOWN, CONFIG, 'FULLY_SYNTHETIC'), 'input scope metadata')
    rows = data['rows']
    need(rows == expected_shape(events, seed), 'exact auxiliary/event identity and order')
    financial = independent_fold(rows, events)
    need(financial['balances'] == {'I0': 10000, 'I1': 10000 + residual, 'I2': 10000, 'I3': 10000}
         and financial['liability'] == 40000 + residual, 'stipulated independent final quantities')
    index = receipt_index(rows)
    need(digest([r['receipt_id'] for r in index]) == ordered_pin, 'ordered receipt identity pin')
    need(len({r['receipt_id'] for r in index}) == len({r['record_id'] for r in index}) == events + 17,
         'duplicate receipt/normalized identity')
    return {'status': 'PASS', 'events': events, 'seed': seed, 'input': {'path': str(Path(path).resolve()), **proof(raw)},
            'physical_receipts': events + 17, 'auxiliary_receipts': 17,
            'kind_counts': dict(Counter(r['kind'] for r in index)), 'ordered_receipt_ids_sha256': ordered_pin,
            'receipt_index_sha256': digest(index), 'financial_projection': financial,
            'receipt_index': index}


def oracle_inputs(input_root, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    records = []
    for events, seed in INPUTS:
        row = audit_input(Path(input_root) / f'events{events}-seed{seed}.json', events, seed)
        index = row.pop('receipt_index')
        path = output / f'events{events}-seed{seed}-receipt-index.jsonl'
        path.write_bytes(b''.join(canonical(r) + b'\n' for r in index))
        row['receipt_index_file'] = {'path': str(path), **proof(path.read_bytes())}
        records.append(row)
    source = Path(__file__).resolve()
    imported = sorted({node.names[0].name.split('.')[0] for node in ast.walk(ast.parse(source.read_text()))
                       if isinstance(node, ast.Import)} | {node.module.split('.')[0] for node in ast.walk(ast.parse(source.read_text()))
                       if isinstance(node, ast.ImportFrom) and node.module})
    need(all(n in sys.stdlib_module_names or n == '__future__' for n in imported), 'nonstdlib oracle import')
    result = {'format': 'gate4-input-oracle-v1', 'status': 'PASS', 'source_head_reference': HEAD,
              'created_utc': datetime.now(timezone.utc).isoformat(), 'argv': sys.argv,
              'interpreter': sys.executable, 'python': sys.version,
              'source': {'path': str(source), **proof(source.read_bytes())}, 'imports': imported,
              'input_audits': records, 'wall_seconds': time.perf_counter() - started,
              'scope': 'Two fixed synthetic inputs; integer-cent arithmetic, exact identities and order; no institutional truth claim',
              'historical_count_only_false_negatives': 12, 'source_signature_authority': 'LAB_NOT_INSTITUTION'}
    (output / 'input-oracle.json').write_bytes(canonical(result) + b'\n')
    return result


def paired_specs():
    result = []
    for pair in range(1, 8):
        for events, seed in INPUTS:
            order = list(METHODS)
            if (pair % 2 == 0) != (events == 25000):
                order.reverse()
            for method in order:
                result.append({'id': f'events{events}-pair{pair:02d}-{method.lower()}',
                    'events': events, 'seed': seed, 'pair': pair, 'method': method,
                    'role': 'paired', 'instrumented': False, 'wall_cap': 90 if events == 10000 else 150})
    return result


def verify_trial_population(trials):
    need(type(trials) is list, 'missing raw trial list')
    keys = tuple(paired_specs()[0])
    actual = [{key: row.get(key) for key in keys} for row in trials]
    need(actual == paired_specs(), 'empty/duplicate/substituted/reordered trial population')
    need(all(row.get('status') == 'PASS' and type(row.get('exit_code')) is int and row['exit_code'] == 0
             and all(type(row[k]) is int for k in ('events', 'seed', 'pair', 'wall_cap'))
             and row['instrumented'] is False for row in trials),
         'complete paired population requires actual PASS exits')


def synthetic_trial_fixture():
    """Test-only fixture, never mixed with measured observations."""
    return [{**row, 'status': 'PASS', 'exit_code': 0,
             'parent_wall_seconds': (10 if row['method'] == 'BASELINE' else 6) + row['pair'] / 10}
            for row in paired_specs()]


def finite_positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def distribution(values):
    need(values and all(finite_positive(v) for v in values), 'nonpositive/nonfinite raw timing')
    ordered = sorted(values)
    return {'p50': statistics.median(ordered), 'p95_nearest_rank': ordered[math.ceil(len(ordered) * .95) - 1],
            'min': min(ordered), 'max': max(ordered)}


def bootstrap95(values):
    rng = random.Random(424271)
    samples = sorted(statistics.median(rng.choices(values, k=len(values))) for _ in range(10000))
    return [samples[250], samples[9749]]


def statistics_from_trials(trials):
    verify_trial_population(trials)
    by_id = {(t['events'], t['pair'], t['method']): t for t in trials}
    profiles = []
    for events, seed in INPUTS:
        pairs = []
        for pair in range(1, 8):
            baseline, candidate = (by_id[events, pair, m]['parent_wall_seconds'] for m in METHODS)
            need(finite_positive(baseline) and finite_positive(candidate), 'nonpositive/nonfinite raw timing')
            pairs.append({'pair': pair, 'baseline_seconds': baseline, 'candidate_seconds': candidate,
                          'difference_seconds': baseline - candidate,
                          'gain_fraction': (baseline - candidate) / baseline})
        gains = [p['gain_fraction'] for p in pairs]
        differences = [p['difference_seconds'] for p in pairs]
        lower = bootstrap95(gains)
        profiles.append({'events': events, 'seed': seed, 'n_pairs': 7, 'pairs': pairs,
            'baseline_parent_wall_seconds': distribution([p['baseline_seconds'] for p in pairs]),
            'candidate_parent_wall_seconds': distribution([p['candidate_seconds'] for p in pairs]),
            'median_paired_difference_seconds': statistics.median(differences),
            'median_paired_gain_fraction': statistics.median(gains),
            'paired_difference_bootstrap95': bootstrap95(differences), 'paired_gain_bootstrap95': lower,
            'speed_threshold_met': statistics.median(gains) >= .15 and lower[0] > .05})
    return {'format': 'gate4-independent-statistics-v1', 'profiles': profiles,
            'performance_gate': 'MATERIAL_GAIN' if all(p['speed_threshold_met'] for p in profiles) else 'NO_CHANGE',
            'p95_qualification': 'n7 nearest-rank p95 is the observed sample maximum; not a stable population tail.'}


def verify_reported_statistics(trials, reported):
    calculated = statistics_from_trials(trials)
    if reported.get('format') == 'gate4-independent-statistics-v1':
        need(reported == calculated, 'reported summary differs from actual raw timings')
        return calculated
    need(reported.get('format') == 'gate4-benchmark-summary-v1', 'unknown reported summary format')
    profiles = reported.get('profiles', [])
    need(len(profiles) == 2, 'reported summary profile inventory')
    for expected, actual in zip(calculated['profiles'], profiles):
        need(actual.get('events') == expected['events'] and actual.get('expected_pairs') == actual.get('complete_equivalent_pairs') == 7,
             'reported summary pair population')
        for key in ('pairs', 'median_paired_difference_seconds', 'median_paired_gain_fraction',
                    'paired_difference_bootstrap95', 'paired_gain_bootstrap95', 'speed_threshold_met'):
            need(actual.get(key) == expected[key], 'reported summary ' + key)
        for method in ('baseline', 'candidate'):
            dist = expected[method + '_parent_wall_seconds']
            need(actual.get(method + '_median_seconds') == dist['p50'] and
                 actual.get(method + '_empirical_p95_equals_observed_max_seconds') == dist['max'],
                 'reported summary median/p95')
    need(reported.get('performance_gate') == calculated['performance_gate'], 'reported summary performance gate')
    return calculated

def file_proof(path):
    path = Path(path)
    h = hashlib.sha256()
    size = 0
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
            size += len(block)
    return {'bytes': size, 'sha256': h.hexdigest()}


def independently_read_tables(db):
    tables = {}
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        identifier = '"' + name.replace('"', '""') + '"'
        columns = [row[1] for row in db.execute('PRAGMA table_info(' + identifier + ')')]
        order = ','.join(f'{i} COLLATE BINARY' for i in range(1, len(columns) + 1))
        h = hashlib.sha256()
        count = 0
        for row in db.execute('SELECT * FROM ' + identifier + ' ORDER BY ' + order):
            cells = [{'sqlite_blob_hex': v.hex()} if type(v) is bytes else v for v in row]
            h.update(canonical(cells) + b'\n')
            count += 1
        tables[name] = {'columns': columns, 'rows': count, 'sha256': h.hexdigest()}
    ordered = hashlib.sha256()
    for row in db.execute('SELECT id,receipt_hash,record_id,received_at,status,error,raw FROM receipts ORDER BY id'):
        ordered.update(canonical(list(row)) + b'\n')
    return {'tables': tables, 'schema_objects': [list(r) for r in db.execute(
        'SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name')],
        'ordered_receipts_sha256': ordered.hexdigest(), 'user_version': db.execute('PRAGMA user_version').fetchone()[0]}


def canonical_cents(text):
    need(type(text) is str and re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.[0-9]{1,2})?', text), 'export decimal syntax')
    return cents(text + '.00' if '.' not in text else text + '0' if len(text.split('.')[1]) == 1 else text)


def verify_saved_economics(saved, oracle, index):
    """Read saved financial values and every evidence link without projection helpers."""
    need(saved['rule_version'] == 'stage2-v2' and saved['balance_at'] == CUT[:-1] + '.000000Z'
         and saved['knowledge_at'] == KNOWN[:-1] + '.000000Z', 'saved result scope')
    run_id = saved['run_id']
    need(digest({k: v for k, v in saved.items() if k != 'run_id'}) == run_id, 'saved run content identity')
    need(set(saved['ledgers']) == {'UNIT'}, 'ledger asset inventory')
    ledger = saved['ledgers']['UNIT']
    need(saved['configuration'] == {**CONFIG, 'opening_at': OPEN[:-1] + '.000000Z'}, 'saved normalized configuration')
    need({k: canonical_cents(v) for k, v in ledger['investor_balances'].items()} == oracle['balances']
         and canonical_cents(ledger['liability']) == oracle['liability'], 'saved investor/liability arithmetic')
    need(ledger['data_state'] == 'COMPLETE' and ledger['correction_groups'] == [], 'ledger completeness')
    need({k: canonical_cents(v) for k, v in ledger['custody_rollforward'].items()} == oracle['custody'], 'custody arithmetic')
    need(len(saved['findings']) == 5, 'finding count')
    findings = {row['scope']: row for row in saved['findings']}
    need(set(findings) == set(oracle['outcomes']), 'finding identity population')
    for name, row in findings.items():
        wanted = oracle['liability'] if name == 'customer_liability' else oracle['balances'][name]
        need(row['data_state'] == 'COMPLETE' and row['reconciliation_state'] == 'MATCHED'
             and row['difference'] == '0' and row['provisional'] is False
             and canonical_cents(row['expected']) == canonical_cents(row['reported']) == wanted,
             'independent financial classification/balance')
        need(all(eid in saved['evidence'] for eid in row['evidence_ids']), 'dangling finding evidence link')
    wanted_evidence = {r['receipt_id'] for r in index} | {r['record_id'] for r in index}
    need(set(saved['evidence']) == wanted_evidence, 'missing/extra evidence identity')
    for expected in index:
        receipt = saved['evidence'][expected['receipt_id']]
        record = saved['evidence'][expected['record_id']]
        need(set(receipt) == {'receipt'} and digest(receipt['receipt']) == expected['receipt_id'], 'evidence receipt content')
        need(record['receipt_ids'] == [expected['receipt_id']] and record['logical_key'] == expected['logical_key']
             and digest(record['record']) == expected['record_id'], 'record evidence/provenance linkage')
    return run_id


def verify_database(folder, metrics, audited):
    before = file_proof(folder / 'input.sqlite3')
    need(before == metrics['artifacts']['input.sqlite3'], 'retained DB bytes changed')
    # Closed checkpointed successful trial only; immutable avoids WAL reader writes.
    need(not Path(str(folder / 'input.sqlite3') + '-wal').exists(), 'successful DB still has WAL sidecar')
    rows = audited['receipt_index']
    with sqlite3.connect((folder / 'input.sqlite3').resolve().as_uri() + '?mode=ro&immutable=1', uri=True) as db:
        need(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok' and not db.execute('PRAGMA foreign_key_check').fetchall(),
             'independent SQL integrity')
        logical = independently_read_tables(db)
        need(logical == metrics['logical_snapshot'] == load(folder / 'logical-snapshot.json'), 'actual SQL logical snapshot')
        physical = db.execute('SELECT id,receipt_hash,record_id,received_at,status,error,raw FROM receipts ORDER BY id')
        observed = 0
        for actual, expected in zip(physical, rows):
            ordinal, receipt_id, record_id, received, status, error, raw = actual
            envelope = parse_json(raw)
            need((ordinal, receipt_id, record_id, status, error) == (expected['ordinal'], expected['receipt_id'], expected['record_id'], 'ACCEPTED', None),
                 'physical receipt order/ID/status')
            need(digest(envelope) == receipt_id and received == envelope['received_at'][:-1] + '.000000Z', 'physical receipt envelope/time')
            observed += 1
        need(observed == len(rows) == logical['tables']['receipts']['rows'], 'physical receipt count')
        record_by_id = {r['record_id']: r for r in rows}
        for rid, key, kind, payload in db.execute('SELECT id,logical_key,kind,payload FROM records'):
            expected = record_by_id[rid]
            need(key == expected['logical_key'] and kind == expected['kind'] and digest(parse_json(payload)) == rid,
                 'normalized SQL record content')
        runs = db.execute('SELECT id,payload FROM runs').fetchall()
        need(len(runs) == 1, 'exact saved run count')
        saved = parse_json(runs[0][1])
        # Store's runs payload excludes run_id; the read API attaches it.
        saved = {'run_id': runs[0][0], **saved}
        need(verify_saved_economics(saved, audited['financial_projection'], rows) == metrics['run_id'], 'saved run identity')
        export = load(folder / 'export.json')
        need(export == saved and (folder / 'export.json').read_bytes() == canonical(saved) + b'\n', 'canonical export vs stored result')
        finding_rows = db.execute('SELECT ordinal,payload FROM findings ORDER BY ordinal').fetchall()
        need([parse_json(r[1]) for r in finding_rows] == saved['findings'], 'finding table vs saved run')
        evidence_rows = db.execute('SELECT evidence_id,payload FROM evidence ORDER BY evidence_id')
        need({rid: parse_json(text) for rid, text in evidence_rows} == saved['evidence'], 'evidence table vs saved run')
    need(file_proof(folder / 'input.sqlite3') == before, 'independent read mutated database')
    responses = [parse_json(line) for line in (folder / 'receipts.jsonl').read_text().splitlines()]
    need(len(responses) == len(rows), 'response log count')
    for response, expected in zip(responses, rows):
        need(response == {'ordinal': expected['ordinal'], 'receipt_id': expected['receipt_id'],
             'record_id': expected['record_id'], 'status': 'ACCEPTED', 'error': None, 'reason_code': None},
             'actual receipt response log identity')
    return {'status': 'PASS', 'physical_receipts': len(rows), 'run_id': metrics['run_id'],
            'logical_snapshot_sha256': digest(logical), 'export': file_proof(folder / 'export.json')}



def audit_initial_failure(root, protocol):
    root = Path(root)
    ledger = load(root / 'ledger.json')
    fields = tuple(protocol['roster'][0])
    trials = ledger['trials']
    need(ledger['status'] == 'PARTIAL' and ledger['protocol'] == protocol, 'original failed attempt lineage')
    need([{key: t.get(key) for key in fields} for t in trials] == protocol['roster'], 'original full scheduled roster')
    need(trials[0]['id'] == 'warmup-baseline' and trials[0]['status'] == 'ERROR' and trials[0]['exit_code'] == 1,
         'preserve actual first warmup error')
    need(all(t['status'] == 'NOT_RUN' and t['exit_code'] is None for t in trials[1:]), 'preserve original 33 NOT_RUN')
    stderr = root / 'warmup-baseline.stderr.txt'
    need(file_proof(stderr) == trials[0]['stderr'] and 'ValueError: not allowed to raise maximum limit' in stderr.read_text()
         and 'resource.setrlimit(resource.RLIMIT_AS' in stderr.read_text(), 'original actual failure cause')
    need(not list(root.rglob('input.sqlite3')) and not (root / 'warmup-baseline' / 'metrics.json').exists(),
         'original pre-DB failure scope')
    for name, pin in ledger['source_bindings'].items():
        need(file_proof(root / 'source' / name) == pin, 'original executed source bytes')
    return {'status': 'PRESERVED_FAILED_ATTEMPT', 'ledger': file_proof(root / 'ledger.json'),
            'counts': {'ERROR': 1, 'NOT_RUN': 33}, 'actual_exit_code': 1,
            'started_primary_trials': 0, 'resource_summary': ledger['resource_summary'],
            'reason': 'Inherited hard AS limit rejected child before Store/DB creation; not a timed primary outcome.'}


def audit_instrumentation_controls(root, prior_result_path=None):
    root = Path(root)
    ledger = load(root / 'ledger.json')
    if prior_result_path is not None:
        prior = load(prior_result_path)
        need(prior['status'] == 'PASS' and prior['ledger'] == file_proof(root / 'ledger.json'), 'control supplement prior full raw review binding')
    trials = [t for t in ledger['trials'] if t['role'] == 'instrumentation_control']
    need([t['id'] for t in trials] == ['control-baseline-off', 'control-baseline-on',
         'control-candidate_wal_full-on', 'control-candidate_wal_full-off'], 'fixed four-control identity/order')
    need(all(t['status'] == 'PASS' and type(t['exit_code']) is int and t['exit_code'] == 0
         and t['events'] == 10000 and t['seed'] == 11 for t in trials), 'control status/input identity')
    expected, boundaries = [], []
    for method in METHODS:
        rows = [t for t in trials if t['method'] == method]
        off = next(t for t in rows if t['instrumented'] is False)
        on = next(t for t in rows if t['instrumented'] is True)
        for trial in (off, on):
            metric_path = root / trial['id'] / 'metrics.json'
            need(load(metric_path) == trial['metrics'] and file_proof(metric_path) == trial['metrics_proof'], 'control raw metric file')
        for key in ('input', 'physical_receipts', 'logical_snapshot', 'financial_projection', 'run_id', 'export_sha256', 'ordered_receipts_sha256'):
            need(off['metrics'][key] == on['metrics'][key], 'instrumentation control changed logical result')
        elapsed_off, elapsed_on = off['parent_wall_seconds'], on['parent_wall_seconds']
        need(finite_positive(elapsed_off) and finite_positive(elapsed_on), 'actual control duration')
        expected.append({'method': method, 'n_pairs': 1, 'status': 'PASS', 'equivalent': True,
            'off_parent_seconds': elapsed_off, 'on_parent_seconds': elapsed_on,
            'incremental_seconds': elapsed_on - elapsed_off, 'incremental_fraction': elapsed_on / elapsed_off - 1})
        transaction_file = root / on['id'] / 'transactions.csv'
        sums = {}
        with transaction_file.open(newline='') as stream:
            reader = csv.DictReader(stream)
            need(reader.fieldnames == ['phase', 'ordinal', 'boundary', 'wall_seconds', 'cpu_seconds'], 'transaction CSV fields')
            count = 0
            for count, row in enumerate(reader, 1):
                need(row['ordinal'] == str(count) and row['boundary'] in ('sql_begin', 'sql_commit', 'sql_rollback'), 'transaction ordinal/boundary')
                key = row['phase'] + ':' + row['boundary']
                aggregate = sums.setdefault(key, {'calls': 0, 'wall_seconds': 0.0, 'cpu_seconds': 0.0})
                aggregate['calls'] += 1
                for name in ('wall_seconds', 'cpu_seconds'):
                    value = float(row[name])
                    need(math.isfinite(value) and value >= 0, 'transaction raw duration')
                    aggregate[name] += value
        bucket_subset = {key: value for key, value in on['metrics']['buckets'].items()
                         if key.rsplit(':', 1)[-1] in ('sql_begin', 'sql_commit', 'sql_rollback')}
        need(sums == bucket_subset and sums['ingest:sql_commit']['calls'] == sums['ingest:sql_begin']['calls'] == 10017,
             'transaction raw CSV vs bucket counts and sums')
        ingest_wall = on['metrics']['phases']['ingest']['wall_seconds']
        boundaries.append({'method': method, 'csv': file_proof(transaction_file), 'rows': count,
                           'raw_boundary_sums': sums, 'ingest_commit_wall_share': sums['ingest:sql_commit']['wall_seconds'] / ingest_wall})
    need(load(root / 'summary.json')['instrumentation_controls'] == expected, 'reported instrumentation control summary')
    return {'status': 'PASS', 'ledger': file_proof(root / 'ledger.json'), 'controls': expected, 'transactions': boundaries,
            'qualification': 'One off/on control per method; observed incremental Recorder overhead, no stable population estimate. Off includes common phase, receipt and readback diagnostics. COMMIT may include implicit checkpoint work; nested bucket times are not additive.'}


def audit_benchmark(root, protocol_path):
    root = Path(root).resolve()
    protocol_raw = Path(protocol_path).read_bytes()
    original_pin = {'bytes': 11275, 'sha256': '3b1ec65cde995cf95f12498f5a614448d45c96884e2fed14aac806a9484134b2'}
    continuation_pin = {'bytes': 13922, 'sha256': '12ad614d1ae6992fa91c5222cee2d5fbca0b3180d2a8029dfd0f9c818fe4afca'}
    need(proof(protocol_raw) in (original_pin, continuation_pin), 'fixed premeasurement benchmark protocol')
    protocol = load(protocol_path)
    original_path = root / 'source' / 'contracts' / 'gate4-benchmark-protocol.json'
    need(file_proof(original_path) == original_pin, 'immutable original protocol source')
    original_protocol = load(original_path)
    if 'continuation' in protocol:
        need(proof(protocol_raw) == continuation_pin, 'continuation external pin')
        rebuilt = json.loads(json.dumps(protocol))
        prior = rebuilt.pop('continuation')
        rebuilt['budgets']['total_wall_seconds'] += 1
        rebuilt['budgets']['total_cpu_seconds'] += 1
        need(rebuilt == original_protocol, 'continuation changed original roster/thresholds/workload')
        for name, pin in prior['prior_file_proofs'].items():
            need(file_proof(name) == pin, 'original failed attempt bytes changed')
    ledger = load(root / 'ledger.json')
    preregistered = load(root / 'preregistration.json')
    need(ledger['protocol'] == preregistered['protocol'] == protocol and ledger['protocol_proof'] == proof(protocol_raw), 'protocol execution binding')
    need(ledger['status'] == 'PASS', 'benchmark population incomplete')
    trials = ledger['trials']
    fields = tuple(protocol['roster'][0])
    need([{k: t.get(k) for k in fields} for t in trials] == protocol['roster'], 'full 34-cell population/order')
    need(all(t['status'] == 'PASS' and t['exit_code'] == 0 for t in trials), 'all scheduled actual exits required')
    paired = [t for t in trials if t['role'] == 'paired']
    verify_trial_population(paired)
    independent = load(root / 'independent-input-audit.json')
    need(independent['status'] == 'PASS' and file_proof(root / 'independent-input-audit.json') ==
         {k: ledger['independent_input_audit'][k] for k in ('bytes', 'sha256')}, 'prior input oracle binding')
    audited = {(n, s): audit_input(root / 'inputs' / f'events{n}-seed{s}.json', n, s) for n, s in INPUTS}
    original_failure = audit_initial_failure(root.parent / 'run-001', original_protocol) if root.name != 'run-001' else None
    source = ledger['source_bindings']
    need(source == preregistered['source_bindings'] and len(source) > 90, 'nonempty fixed source closure')
    for name, pin in source.items():
        need(not Path(name).is_absolute() and '..' not in Path(name).parts and file_proof(root / 'source' / name) == pin, 'source snapshot byte binding')
    reviews = []
    for trial in trials:
        folder = root / trial['id']
        metric = load(folder / 'metrics.json')
        need(metric == trial['metrics'] and file_proof(folder / 'metrics.json') == trial['metrics_proof'], 'raw metrics vs ledger')
        need(metric['input'] == file_proof(trial['input']['path']), 'actual input bytes')
        need(metric['method'] == trial['method'] and metric['events'] == trial['events'] and metric['seed'] == trial['seed']
             and metric['instrumented'] == trial['instrumented'], 'worker identity')
        need(0 < metric['wall_seconds'] <= trial['parent_wall_seconds'] < trial['wall_cap'], 'parent/worker wall scope')
        need(finite_positive(metric['cpu_seconds']) and metric['cpu_seconds'] <= trial['wall_cap'], 'CPU scope')
        need(metric['physical_receipts'] == trial['events'] + 17, 'physical vs business denominator')
        need(metric['checkpoint_result'][0] == 0 and metric['integrity_check'] == 'ok', 'checkpoint/integrity result')
        for name in ('pragmas_initial', 'pragmas_reopen'):
            settings = metric[name]
            need(settings['journal_mode'] == ('delete' if trial['method'] == 'BASELINE' else 'wal')
                 and settings['synchronous'] == 2 and settings['foreign_keys'] == 1 and settings['user_version'] == 6,
                 'journal FULL/FK/schema observations')
        need(set(metric['artifacts']) == {'input.sqlite3', 'export.json', 'receipts.jsonl', 'logical-snapshot.json'}, 'exact artifact inventory')
        for name, pin in metric['artifacts'].items():
            need(Path(name).name == name and file_proof(folder / name) == pin, 'artifact bytes ' + name)
        phase_names = {'input_read', 'json_parse', 'validate_fixed_synthetic_contract', 'initialize_including_journal_conversion',
                       'ingest', 'run_persistence', 'reconcile_including_run_persistence', 'canonical_export_serialization',
                       'canonical_export_write', 'reread_financial_and_receipt_verification', 'logical_table_verification',
                       'logical_snapshot_write', 'explicit_final_checkpoint', 'close', 'reopen',
                       'reopen_logical_and_integrity_verification', 'final_close'}
        need(set(metric['phases']) == phase_names, 'exact phase inventory')
        for measurement in ('wall_seconds', 'cpu_seconds'):
            need(all(type(p[measurement]) in (float, int) and math.isfinite(p[measurement]) and p[measurement] >= 0
                     for p in metric['phases'].values()), 'invalid phase duration')
            need(sum(p[measurement] for name, p in metric['phases'].items() if name != 'run_persistence') <= metric[measurement],
                 'disjoint phase total exceeds worker body')
            need(metric['phases']['run_persistence'][measurement] <= metric['phases']['reconcile_including_run_persistence'][measurement],
                 'nested persistence exceeds reconciliation')
        for stream in ('stdout', 'stderr'):
            need(file_proof(root / (trial['id'] + '.' + stream + '.txt')) == trial[stream], 'actual stdout/stderr linkage')
        need((root / (trial['id'] + '.stderr.txt')).read_bytes() == b'', 'successful worker stderr')
        worker = load(root / (trial['id'] + '.worker-start.json'))
        need(worker == trial['worker_start'] and worker['source_bindings'] == source, 'worker source/import identity')
        need(all(Path(path).is_relative_to(root / 'source') for path in worker['import_origins'].values()), 'worker loaded outside isolated snapshot')
        need(trial['cwd'] == str(root / 'source') and trial['argv'][1:4] == ['-I', '-B', '-c']
             and trial['argv'][5] == str(root / 'source') and '--worker' in trial['argv'], 'isolated command binding')
        sample_times = [s['elapsed_seconds'] for s in trial['samples']]
        need(sample_times == sorted(sample_times) and sample_times[-1] <= trial['parent_wall_seconds'], 'resource sample chronology')
        for name in ('explicit_final_checkpoint', 'close', 'reopen', 'final_close', 'ingest', 'run_persistence'):
            need(name in metric['phases'] and all(type(v) in (float, int) and math.isfinite(v) and v >= 0
                 for v in metric['phases'][name].values()), 'required timed phase ' + name)
        if trial['role'] != 'warmup':
            expected = audited[trial['events'], trial['seed']]
            need(metric['financial_projection'] == expected['financial_projection'], 'independent integer economics')
            review = verify_database(folder, metric, expected)
        else:
            review = {'status': 'HASH_AND_METRIC_REVIEW_ONLY', 'reason': 'warmup not a primary registered independent-input population'}
        reviews.append({'id': trial['id'], 'role': trial['role'], 'status': 'PASS', 'database_review': review})
    for events, seed in INPUTS:
        population = [t for t in trials if t['events'] == events]
        first = population[0]['metrics']
        for trial in population[1:]:
            for key in ('logical_snapshot', 'ordered_receipts_sha256', 'run_id', 'export_sha256', 'financial_projection'):
                need(trial['metrics'][key] == first[key], 'exact cross-method/repeat logical equivalence ' + key)
    statistics_result = verify_reported_statistics(paired, load(root / 'summary.json'))
    resources = ledger['resource_summary']
    prior_resources = original_failure['resource_summary'] if original_failure else {'elapsed_seconds': 0, 'controller_cpu_seconds': 0, 'waited_child_cpu_seconds': 0}
    need(resources['elapsed_seconds'] + prior_resources['elapsed_seconds'] <= 1800, 'cumulative wall budget')
    need(sum(r[k] for r in (resources, prior_resources) for k in ('controller_cpu_seconds', 'waited_child_cpu_seconds')) <= 900,
         'cumulative actual CPU budget')
    need(resources['peak_sampled_owned_disk_bytes'] <= 6 * 1024**3 and resources['final_owned_disk_bytes'] <= 6 * 1024**3,
         'cumulative owned disk sampled/final budget')
    return {'format': 'gate4-independent-benchmark-review-v1', 'status': 'PASS', 'ledger': file_proof(root / 'ledger.json'),
            'trials': reviews, 'source_files': len(source), 'statistics': statistics_result,
            'instrumentation_review': audit_instrumentation_controls(root),
            'original_failed_attempt': original_failure,
            'original_preregistered_all_trials_pass': original_failure is None,
            'continuation_protocol_deviation': original_failure is not None,
            'candidate_acceptance': 'CANDIDATE_NOT_ACCEPTED',
            'decision': 'NO_CHANGE',
            'combined_roster': ([{'attempt': 'run-001', 'id': spec['id'], 'status': 'ERROR' if i == 0 else 'NOT_RUN'}
                                for i, spec in enumerate(protocol['roster'])] if original_failure else []) +
                               [{'attempt': root.name, 'id': t['id'], 'status': t['status'], 'exit_code': t['exit_code']} for t in trials],
            'qualification': 'Retained byte/record/financial/statistical consistency, not trusted-clock attestation, power-loss evidence or candidate acceptance.'}


def verify_test_manifest(inventory_path, summary_path, stderr_path, source_root):
    """Independent static-ID, executed-ID, log and source-byte test-scope review."""
    inventory, summary = load(inventory_path), load(summary_path)
    need(inventory.get('format') == 'gate4-test-inventory-v1' and inventory.get('historical_base') == HEAD
         and type(inventory.get('historical_files')) is int and inventory['historical_files'] == 445, 'test inventory historical scope')
    source_root = Path(source_root)
    historical = subprocess.run(['git', 'ls-tree', '-rz', HEAD], cwd=source_root,
                                check=True, capture_output=True, timeout=15).stdout
    expected_files = set()
    for entry in historical.split(b'\0'):
        if not entry:
            continue
        metadata, raw_name = entry.split(b'\t', 1)
        mode, kind, blob = metadata.decode().split()
        name = raw_name.decode()
        need(mode in ('100644', '100755') and kind == 'blob', 'historical source regular-file scope')
        path = source_root / name
        raw = path.read_bytes()
        actual_blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        need(not path.is_symlink() and actual_blob == blob, 'historical Git bytes changed: ' + name)
        expected_files.add(name)
    need(len(expected_files) == 445, 'exact 445 historical Git files')
    for pattern in ('validation_gate4_tests/*.py', 'validation_lab/gate4*.py',
                    'scripts/validation/*gate4*.py', 'contracts/gate4*.json'):
        for path in source_root.glob(pattern):
            need(path.is_file() and not path.is_symlink(), 'research regular-file scope')
            expected_files.add(path.relative_to(source_root).as_posix())
    need(set(inventory['source_files']) == expected_files, 'incomplete/substituted source closure')
    for name in sorted(expected_files):
        need(file_proof(source_root / name) == inventory['source_files'][name], 'test execution source changed: ' + name)
    static = []
    # Derive population from actual directory, never from the supplied manifest.
    for path in sorted((source_root / 'validation_gate4_tests').glob('test_*.py')):
        for node in ast.parse(path.read_bytes()).body:
            if isinstance(node, ast.ClassDef):
                static.extend(f'{path.stem}.{node.name}.{method.name}' for method in node.body
                              if isinstance(method, ast.FunctionDef) and method.name.startswith('test_'))
    expected = sorted(static)
    need(expected and len(expected) == len(set(expected)) and inventory['expected_ids'] == expected
         and type(inventory['expected_count']) is int and inventory['expected_count'] == len(expected), 'empty/duplicate/substituted test inventory')
    need(summary['status'] == 'PASS' and summary['source_unchanged'] is True
         and summary['inventory_sha256'] == file_proof(inventory_path)['sha256'], 'test result inventory identity')
    need(summary['scope'] == 'NEW_GATE4_RESEARCH_ONLY' and summary['historical_875'] == 'NOT_RUN_BY_THIS_COMMAND',
         'historical test relabelling')
    need(set(summary['counters']) == {'failures', 'errors', 'skips', 'expected_failures', 'unexpected_successes'}
         and all(type(v) is int and v == 0 for v in summary['counters'].values()), 'test nonpass counter')
    for key in ('expected_ids', 'discovered_ids', 'executed_ids', 'successful_ids', 'completed_ids'):
        need(sorted(summary[key]) == expected and len(summary[key]) == len(set(summary[key])), 'test ID ' + key)
    need(all(type(summary[k]) is int and summary[k] == len(expected) for k in ('expected', 'discovered', 'executed')), 'test denominator')
    log = Path(stderr_path).read_text()
    log_ids = re.findall(r'^test_[A-Za-z0-9_]+ \(([^\n()]+)\) \.\.\. ok$', log, re.MULTILINE)
    need(sorted(log_ids) == expected and len(log_ids) == len(set(log_ids)), 'actual unittest log population')
    need(re.search(r'^Ran ' + str(len(expected)) + r' tests in [0-9.]+s$', log, re.MULTILINE)
         and log.rstrip().endswith('OK'), 'actual unittest completion')
    return {'status': 'PASS', 'inventory': file_proof(inventory_path), 'summary': file_proof(summary_path),
            'stderr': file_proof(stderr_path), 'tests': len(expected), 'source_files': len(inventory['source_files']),
            'scope': 'NEW_GATE4_RESEARCH_ONLY', 'historical_875': 'NOT_RUN_BY_THIS_COMMAND'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--inputs', type=Path)
    parser.add_argument('--benchmark', type=Path)
    parser.add_argument('--protocol', type=Path)
    parser.add_argument('--controls', type=Path)
    parser.add_argument('--prior-review', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (300, 300))
    need(sum(x is not None for x in (args.inputs, args.benchmark, args.controls)) == 1, 'select exactly one audit')
    if args.inputs is not None:
        result = oracle_inputs(args.inputs, args.output)
    else:
        need((args.benchmark is not None and args.protocol is not None) or
             (args.controls is not None and args.prior_review is not None), 'explicit fixed protocol or prior review required')
        args.output.mkdir(parents=True, exist_ok=False)
        begin, cpu = time.perf_counter(), time.process_time()
        try:
            result = (audit_benchmark(args.benchmark, args.protocol) if args.benchmark is not None
                      else audit_instrumentation_controls(args.controls, args.prior_review))
        except Exception as exc:
            result = {'status': 'FAIL', 'error': repr(exc), 'traceback': traceback.format_exc()}
        result.update(argv=sys.argv, cwd=str(Path.cwd()), interpreter=sys.executable,
                      source=file_proof(__file__), wall_seconds=time.perf_counter()-begin,
                      cpu_seconds=time.process_time()-cpu,
                      memory_limit_bytes=1024**3, cpu_limit_seconds=300)
        (args.output / 'audit-result.json').write_bytes(canonical(result) + b'\n')
    print(json.dumps({'status': result['status'], 'output': str(args.output)}))
    if result['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
