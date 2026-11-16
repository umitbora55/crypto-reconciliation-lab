"""Bounded, offline validation against an independently specified integer oracle.

This research module never changes the application or its historical tests. Its
synthetic finite population is explicitly enumerated before execution. No random
input labels or oracle values are passed to the application.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import os
import platform
import random
import sqlite3
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from crypto_reconciliation_lab import Store, reconcile
from crypto_reconciliation_lab import engine

OPEN = '2026-01-05T00:00:00Z'
CUT = '2026-01-05T23:59:59Z'
KNOWN = '2026-01-06T01:00:00Z'
LATE = '2026-01-06T02:00:00Z'
SEEDS = (11, 29, 47)
FACTORS = tuple(itertools.product((0, 2), ('platform', 'external')))
FAMILIES = ('clean', 'delivery_permutation', 'exact_redelivery', 'split_merge',
            'reciprocal_transfer', 'future_exclusion', 'offset_equivalence',
            'missing_event', 'missing_custody', 'wrong_amount', 'stale_report',
            'invalid_zero', 'invalid_negative', 'invalid_precision',
            'invalid_unknown_asset', 'same_version_conflict', 'newer_revision',
            'same_count_substitution', 'cross_asset_error', 'late_state_machine',
            'void_state_machine', 'replace_state_machine')
# Reviewed finite roster identities, pinned separately from mutable execution
# enumerations. Updating the experiment population requires a new review/version.
FAMILY_ROSTER_SHA256 = 'a7e7ca2213cc662e0bdc524e97b912a6d5d02973b1857510d5414ba7720a3e55'
FACTOR_ROSTER_SHA256 = 'e2ccabd2b4c07bba01197beab5d154aad67ef02cafd59a555a794229c11d3c1a'
MUTATION_IDS = ('force_complete_state', 'suppress_quarantine',
                'suppress_delivery_counts', 'ignore_correction_effect')


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def quantity(units, places):
    """Independent wire formatter: integer division, never production Decimal helpers."""
    sign = '-' if units < 0 else ''
    units = abs(units)
    whole, fraction = divmod(units, 10 ** places)
    if not places or not fraction:
        return sign + str(whole)
    return sign + str(whole) + '.' + str(fraction).zfill(places).rstrip('0')


def integer_units(text, places):
    if not isinstance(text, str):
        raise ValueError('A quantity is not exact text')
    sign = -1 if text.startswith('-') else 1
    parts = text.lstrip('-').split('.')
    fraction = parts[1] if len(parts) == 2 else ''
    if len(parts) > 2 or len(fraction) > places:
        raise ValueError('Unrepresentable output precision')
    return sign * (int(parts[0]) * 10 ** places + int(fraction.ljust(places, '0') or '0'))


def world(seed, factor):
    places, location = FACTORS[factor]
    rng = random.Random(seed * 100 + factor)
    # Each factor cell has the same semantics and independently drawn magnitudes.
    # Include one-unit boundary in factor cell zero, without assuming all groups
    # are a random sample of real institutional records.
    deposit = 2 if factor == 0 else rng.randint(20, 900)
    transfer = 1 if factor == 0 else rng.randint(1, 190)
    withdrawal = 1 if factor == 0 else rng.randint(1, 300)
    opening = {'I1': 10000, 'I2': 5000, 'platform': 7000, 'external': 8000}
    config = {'platform': 'P', 'custodian': 'C', 'investors': ['I1', 'I2'],
              'assets': {'COIN': places, 'OTHER': 8}, 'opening_at': OPEN}
    # Independent oracle is an integer balance transition, not application code.
    expected = {'I1': opening['I1'] + deposit - transfer,
                'I2': opening['I2'] + transfer - withdrawal,
                'platform': opening['platform'], 'external': opening['external']}
    expected[location] += deposit - withdrawal
    rows = []
    def add(record, received=KNOWN):
        rows.append({'record': record, 'received_at': received})
    def base(kind, asset='COIN', source='P'):
        return {'kind': kind, 'platform': 'P', 'source': source, 'asset': asset}
    for asset, digits, values in [('COIN', places, opening),
                                 ('OTHER', 8, {'I1': 1, 'I2': 0, 'platform': 0, 'external': 1})]:
        for scope, units in values.items():
            add({**base('opening', asset), 'scope': scope, 'balance_at': OPEN,
                 'amount': quantity(units, digits)}, OPEN)
    specs = [('D', 'deposit', None, 'I1', location, deposit),
             ('T', 'transfer', 'I1', 'I2', None, transfer),
             ('W', 'withdrawal', 'I2', None, location, withdrawal)]
    for index, (ref, kind, sender, receiver, custody, units) in enumerate(specs, 1):
        add({**base('event'), 'business_day': '2026-01-05', 'ref': ref,
             'occurred_at': f'2026-01-05T0{index}:00:00Z', 'sequence': index,
             'type': kind, 'from_investor': sender, 'to_investor': receiver,
             'custody': custody, 'amount': quantity(units, places)})
    for asset, digits, values in [('COIN', places, expected),
                                 ('OTHER', 8, {'I1': 1, 'I2': 0, 'platform': 0, 'external': 1})]:
        for stream, scope in [('investor', 'I1'), ('investor', 'I2'),
                              ('platform_custody', 'platform'), ('external_custody', 'external')]:
            add({**base('report', asset, 'C' if scope == 'external' else 'P'),
                 'stream': stream, 'scope': scope, 'balance_at': CUT, 'version': 1,
                 'amount': quantity(values[scope], digits)})
        for stream, count in [('opening', 4), ('event', 3 if asset == 'COIN' else 0),
                              ('investor', 2), ('platform_custody', 1), ('external_custody', 1)]:
            add({**base('manifest', asset, 'C' if stream == 'external_custody' else 'P'),
                 'stream': stream, 'coverage_from': OPEN if stream in ('opening', 'event') else CUT,
                 'coverage_to': OPEN if stream == 'opening' else CUT, 'expected_count': count})
    return {'config': config, 'rows': rows, 'expected': expected, 'places': places,
            'location': location, 'deposit': deposit, 'withdrawal': withdrawal,
            'transfer': transfer, 'seed': seed, 'factor': factor,
            'group': f's{seed}-f{factor}'}


def select(rows, **fields):
    return next(row for row in rows if all(row['record'].get(k) == v for k, v in fields.items()))


def correction_rows(w, mode):
    target = select(w['rows'], kind='event', ref='D')['record']
    value = {'kind': 'correction', 'platform': 'P', 'source': 'P', 'asset': 'COIN',
             'batch_id': 'B', 'correction_id': 'C1',
             'target': {k: target[k] for k in ('kind', 'source', 'platform', 'business_day', 'ref')},
             'target_occurred_at': target['occurred_at'], 'mode': mode,
             'source_ref': 'SYNTHETIC-C1', 'reason': 'Finite independent validation input'}
    if mode == 'REPLACE':
        value['replacement_amount'] = quantity(w['deposit'] + 1, w['places'])
    manifest = {'kind': 'correction_manifest', 'source': 'P', 'platform': 'P', 'asset': 'COIN',
                'batch_id': 'B', 'coverage_from': OPEN, 'coverage_to': CUT, 'expected_count': 1}
    return [{'record': r, 'received_at': LATE} for r in (value, manifest)]


def specification(w, family):
    rows = copy.deepcopy(w['rows'])
    expectation = {'state': 'COMPLETE', 'outcome': 'MATCHED', 'ledger': copy.deepcopy(w['expected'])}
    tail = []
    anomaly = False
    if family == 'delivery_permutation':
        random.Random(w['seed']).shuffle(rows)
    elif family == 'exact_redelivery':
        rows += copy.deepcopy(rows)
    elif family == 'split_merge':
        target = select(rows, kind='event', ref='D')
        units = w['deposit']
        target['record']['amount'] = quantity(units // 2, w['places'])
        second = copy.deepcopy(target)
        second['record'].update(ref='D2', amount=quantity(units - units // 2, w['places']))
        rows.append(second)
        select(rows, kind='manifest', stream='event', asset='COIN')['record']['expected_count'] = 4
    elif family == 'reciprocal_transfer':
        target = copy.deepcopy(select(rows, kind='event', ref='T'))
        target['record'].update(ref='T2', occurred_at='2026-01-05T04:00:00Z', amount=quantity(1, w['places']))
        reverse = copy.deepcopy(target)
        reverse['record'].update(ref='T3', from_investor='I2', to_investor='I1', sequence=3)
        rows.extend((target, reverse))
        select(rows, kind='manifest', stream='event', asset='COIN')['record']['expected_count'] = 5
    elif family == 'future_exclusion':
        target = copy.deepcopy(select(rows, kind='event', ref='D'))
        target['record'].update(ref='FUTURE', business_day='2026-01-06', occurred_at='2026-01-06T00:00:00Z')
        rows.append(target)
    elif family == 'offset_equivalence':
        select(rows, kind='event', ref='D')['record']['occurred_at'] = '2026-01-05T04:00:00+03:00'
    elif family in ('missing_event', 'late_state_machine'):
        target = select(rows, kind='event', ref='W')
        rows.remove(target)
        expectation.update(state='INCOMPLETE', outcome='NOT_EVALUATED', ledger=None)
        anomaly = True
        if family == 'late_state_machine':
            target['received_at'] = LATE
            tail = [target]
    elif family == 'missing_custody':
        rows.remove(select(rows, kind='report', asset='COIN', scope=w['location']))
        expectation.update(state='INCOMPLETE', outcome='NOT_EVALUATED')
        anomaly = True
    elif family in ('wrong_amount', 'cross_asset_error'):
        row = select(rows, kind='report', asset='COIN', scope=w['location'])
        row['record']['amount'] = quantity(w['expected'][w['location']] + 1, w['places'])
        expectation.update(outcome='MISMATCH')
        anomaly = True
        if family == 'cross_asset_error':
            row = select(rows, kind='report', asset='OTHER', scope='external')
            row['record']['amount'] = '0'
    elif family == 'stale_report':
        select(rows, kind='report', asset='COIN', scope=w['location'])['record']['balance_at'] = '2026-01-04T23:59:59Z'
        expectation.update(state='STALE', outcome='NOT_EVALUATED')
        anomaly = True
    elif family.startswith('invalid_'):
        row = select(rows, kind='event', ref='D')['record']
        if family == 'invalid_zero': row['amount'] = '0'
        elif family == 'invalid_negative': row['amount'] = '-1'
        elif family == 'invalid_precision': row['amount'] = '0.' + '0' * w['places'] + '1'
        elif family == 'invalid_unknown_asset': row['asset'] = 'UNKNOWN'
        expectation.update(state='INCOMPLETE', outcome='NOT_EVALUATED', ledger=None)
        anomaly = True
    elif family == 'same_version_conflict':
        row = copy.deepcopy(select(rows, kind='report', asset='COIN', scope=w['location']))
        row['record']['amount'] = quantity(w['expected'][w['location']] + 1, w['places'])
        rows.append(row)
        expectation.update(state='CONFLICT', outcome='NOT_EVALUATED')
        anomaly = True
    elif family == 'newer_revision':
        row = select(rows, kind='report', asset='COIN', scope=w['location'])
        revision = copy.deepcopy(row)
        revision['record']['version'] = 2
        row['record']['amount'] = quantity(w['expected'][w['location']] + 1, w['places'])
        rows.append(revision)
    elif family == 'same_count_substitution':
        select(rows, kind='event', ref='D')['record']['ref'] = 'SUBSTITUTED'
        # The deliberately hidden source-identity substitution preserves both
        # count and economics. Expected lack of detection is a model boundary.
        anomaly = True
    elif family in ('void_state_machine', 'replace_state_machine'):
        tail = correction_rows(w, 'VOID' if family.startswith('void') else 'REPLACE')
    elif family != 'clean':
        raise ValueError(f'unknown family: {family}')
    return {'rows': rows, 'tail': tail, 'expectation': expectation, 'anomaly': anomaly,
            'family': family, 'group': w['group'], 'seed': w['seed'], 'factor': w['factor']}


def finding(payload, asset='COIN'):
    return next(row for row in payload['findings'] if row['asset'] == asset and row['comparison'] == 'B')


def ledger_projection(payload, w):
    ledger = payload['ledgers']['COIN']
    values = {**ledger['investor_balances'], **ledger['custody_rollforward']}
    return {key: integer_units(value, w['places']) if value is not None else None for key, value in values.items()}


def execute(w, spec, temporary_root, evidence_output=None):
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(dir=temporary_root) as tmp:
        store = Store(Path(tmp) / 'input.sqlite3', w['config'])
        try:
            intake = Counter()
            for row in spec['rows']:
                intake[store.ingest(row['record'], row['received_at'])['status']] += 1
            before = reconcile(store, CUT, KNOWN)
            observed = finding(before)
            errors = []
            wanted = spec['expectation']
            if (observed['data_state'], observed['reconciliation_state']) != (wanted['state'], wanted['outcome']):
                errors.append('classification differs from independently declared contract')
            if wanted['ledger'] is not None and ledger_projection(before, w) != wanted['ledger']:
                errors.append('integer balance oracle disagreement')
            investor_outcome = 'NOT_EVALUATED' if (spec['family'].startswith('invalid_') or spec['family'] in
                               ('missing_event', 'late_state_machine', 'quarantine_complete_count_followup')) else 'MATCHED'
            investor_rows = [r for r in before['findings'] if r['asset']=='COIN' and r['comparison']=='A']
            if len(investor_rows) != 2 or any(r['reconciliation_state'] != investor_outcome for r in investor_rows):
                errors.append('investor-side verdict violates independent contract')
            if spec['family'] not in ('cross_asset_error', 'invalid_unknown_asset'):
                if finding(before, 'OTHER')['reconciliation_state'] != 'MATCHED':
                    errors.append('asset isolation failed')
            if spec['family'] == 'cross_asset_error':
                if finding(before, 'OTHER')['reconciliation_state'] != 'MISMATCH':
                    errors.append('opposite asset discrepancies were netted')
            after = None
            if spec['tail']:
                for row in spec['tail']:
                    intake[store.ingest(row['record'], row['received_at'])['status']] += 1
                after = reconcile(store, CUT, LATE)
                expected = copy.deepcopy(w['expected'])
                expected_outcome = 'MATCHED'
                if spec['family'] == 'void_state_machine':
                    expected['I1'] -= w['deposit']
                    expected[w['location']] -= w['deposit']
                    expected_outcome = 'MISMATCH'
                elif spec['family'] == 'replace_state_machine':
                    expected['I1'] += 1
                    expected[w['location']] += 1
                    expected_outcome = 'MISMATCH'
                if ledger_projection(after, w) != expected or finding(after)['reconciliation_state'] != expected_outcome:
                    errors.append('state-machine transition oracle disagreement')
                for row in [r for r in after['findings'] if r['asset']=='COIN' and r['comparison']=='A']:
                    wanted_outcome = 'MISMATCH' if row['scope']=='I1' and spec['family'] in ('void_state_machine','replace_state_machine') else 'MATCHED'
                    if row['reconciliation_state'] != wanted_outcome:
                        errors.append('corrected investor-side verdict disagreement')
                if store.read_run(before['run_id']) != before or reconcile(store, CUT, KNOWN) != before:
                    errors.append('saved history or earlier knowledge cut changed')
            financial_files = {}
            if evidence_output is not None:
                for phase, payload in (('before', before), ('after', after)):
                    if payload is not None:
                        path = Path(evidence_output) / (phase + '.json')
                        write_json(path, payload)
                        financial_files[phase] = {'path': str(path), 'sha256': sha(path),
                                                 'bytes': path.stat().st_size, 'run_id': payload['run_id']}
            return {'case_id': w['group'] + '-' + spec['family'], 'family': spec['family'],
                    'group': w['group'], 'seed': w['seed'], 'factor': w['factor'],
                    'data_class': 'FULLY_SYNTHETIC', 'truth_anomaly': spec['anomaly'],
                    'alert': observed['reconciliation_state'] != 'MATCHED',
                    'status': 'PASS' if not errors else 'FAIL', 'errors': errors,
                    'expected': wanted, 'observed': {k: observed[k] for k in ('data_state','reconciliation_state','expected','reported','difference')},
                    'intake_counts': dict(intake), 'seconds': time.perf_counter() - started,
                    'before_run': before['run_id'], 'after_run': after['run_id'] if after else None,
                    'financial_outputs': financial_files,
                    'lineage': 'input record -> Store.ingest -> reconcile -> exact integer comparison; labels kept outside application'}
        finally:
            store.close()


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def confusion(rows):
    counts = Counter({'TP': 0, 'FP': 0, 'TN': 0, 'FN': 0})
    for row in rows:
        counts[('T' if row['alert'] == row['truth_anomaly'] else 'F') + ('P' if row['alert'] else 'N')] += 1
    tp, fp, tn, fn = (counts[k] for k in ('TP','FP','TN','FN'))
    return {**counts, 'precision': ratio(tp, tp+fp), 'recall': ratio(tp,tp+fn),
            'specificity': ratio(tn,tn+fp), 'false_positive_rate': ratio(fp,fp+tn)}


def bootstrap(rows, repetitions=2000, seed=4391):
    """Resample world groups, keeping every dependent family member together."""
    groups = defaultdict(list)
    for row in rows: groups[row['group']].append(row)
    keys = sorted(groups)
    rng = random.Random(seed)
    samples = defaultdict(list)
    for _ in range(repetitions):
        pooled = [r for _ in keys for r in groups[rng.choice(keys)]]
        for metric, value in confusion(pooled).items():
            if metric in ('precision','recall','specificity','false_positive_rate') and value is not None:
                samples[metric].append(value)
    return {'method': 'percentile bootstrap of entire seed/factor world groups', 'groups': len(keys),
            'resamples': repetitions, 'seed': seed,
            'scope': 'Empirical sensitivity within this finite design; not population confidence for real institutions. Degenerate intervals do not imply zero risk.',
            'intervals_95': {k: [sorted(v)[int(.025*(len(v)-1))], sorted(v)[int(.975*(len(v)-1))]] for k,v in samples.items()}}


def mutation_checks(temporary_root):
    w = world(11, 0)
    witness = specification(w, 'missing_event')
    taint = specification(w, 'invalid_zero')
    # Monkeypatches affect genuine application paths only while executing these
    # controls. All patches restore on exit, even on failure.
    mutations = [
        ('force_complete_state', 'engine.state ignores blocking issues', lambda: patch.object(engine, 'state', return_value='COMPLETE'), witness),
        ('suppress_quarantine', 'Snapshot.taints suppresses invalid receipt evidence', lambda: patch.object(engine.Snapshot, 'taints', return_value=[]), taint),
        ('suppress_delivery_counts', 'Snapshot.manifest suppresses count failures', lambda: patch.object(engine.Snapshot, 'manifest', return_value=([], [])), witness),
        ('ignore_correction_effect', 'resolve_corrections suppresses eligible correction groups', lambda: patch.object(engine, 'resolve_corrections', return_value=({}, [], [], [])), specification(w, 'replace_state_machine')),
    ]
    records = []
    for name, description, context, case in mutations:
        control = execute(w, case, temporary_root)
        if control['status'] != 'PASS':
            records.append({'mutation_id': name, 'description': description, 'control': control['status'],
                            'witness': case['family'], 'killed': False,
                            'errors': control.get('errors', []), 'classification': 'INVALID_CONTROL',
                            'source_change': 'mutation not attempted because the baseline control failed'})
            continue
        try:
            with context():
                mutated = execute(w, case, temporary_root)
            killed = mutated['status'] == 'FAIL'
            error = mutated['errors']
        except Exception as exc:
            killed, error = True, [type(exc).__name__ + ': ' + str(exc)]
        records.append({'mutation_id': name, 'description': description, 'control': control['status'],
                        'witness': case['family'], 'killed': killed, 'errors': error,
                        'classification': 'KILLED' if killed else 'SURVIVED',
                        'source_change': 'test-owned in-memory patch; production files unchanged'})
    return records


def preregistration(seeds):
    if not seeds or len(set(seeds)) != len(seeds) or any(type(seed) is not int or seed < 0 for seed in seeds):
        raise ValueError('At least one unique nonnegative integer seed is required; empty scope cannot pass')
    for label, roster, expected_hash in (('family', FAMILIES, FAMILY_ROSTER_SHA256),
                                         ('factor', FACTORS, FACTOR_ROSTER_SHA256)):
        observed_hash = hashlib.sha256(json.dumps(roster,separators=(',',':')).encode()).hexdigest()
        if not roster or len(set(roster)) != len(roster) or observed_hash != expected_hash:
            raise ValueError(f'{label} roster differs from the reviewed nonempty unique scope')
    return {'format': 'finite-properties-v1', 'registered_before_execution': True,
            'seeds': list(seeds), 'groups': len(seeds)*len(FACTORS), 'factor_cells':
            [{'precision': p, 'custody': c} for p,c in FACTORS],
            'pairwise': {'factors': ['precision','custody'], 'all_pairs': len(FACTORS),
                         'note': 'Complete 2x2 coverage for these two factors only; not all application combinations'},
            'families': list(FAMILIES), 'planned_cases': len(seeds)*len(FACTORS)*len(FAMILIES),
            'expected_case_ids': [f's{seed}-f{factor}-{family}' for seed in seeds
                                  for factor in range(len(FACTORS)) for family in FAMILIES],
            'family_roster_sha256': FAMILY_ROSTER_SHA256, 'factor_roster_sha256': FACTOR_ROSTER_SHA256,
            'data_class': 'FULLY_SYNTHETIC', 'oracle': 'Independent integer arithmetic and explicit model-contract statuses; no production helpers/fixtures used by oracle',
            'acceptance': 'Every finite contract check agrees; same-count substitution is a preregistered detection limitation, not a claim of success at detecting it',
            'resource_budget': {'wall_seconds': 300, 'temporary_bytes': 209715200},
            'mutation_count': 4, 'bootstrap': {'unit': 'world group', 'resamples': 2000, 'seed':4391},
            'not_covered': ['Real public data', 'All possible distributions', 'Real institution error labels', 'Correction conflicts across arbitrary graphs', 'Multi-process serial/parallel equivalence'],
            'source_sha256': sha(__file__)}


def quarantine_followup(output):
    """Diagnose the surviving mutation with an unmasked, preregistered witness."""
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    w = world(11, 0)
    case = specification(w, 'clean')
    bad = copy.deepcopy(select(case['rows'], kind='event', ref='D'))
    bad['record'].update(ref='EXTRA_INVALID', amount='0')
    case['rows'].append(bad)
    case['family'] = 'quarantine_complete_count_followup'
    case['expectation'].update(state='INCOMPLETE', outcome='NOT_EVALUATED')
    case['anomaly'] = True
    registration = {'reason': 'Original invalid-zero mutation witness was masked by missing valid event count.',
                    'registered_before_execution': True,
                    'acceptance': 'Unmutated engine retains quarantine and blocks definitive verdict; suppressing taints causes the same witness to fail the independently declared status.',
                    'mutation': 'Snapshot.taints returns []', 'source_sha256': sha(__file__),
                    'seed': 11, 'data_class': 'FULLY_SYNTHETIC',
                    'oracle': 'All original valid events still present; an additional invalid event cannot erase quarantine even though the manifest count is complete.'}
    write_json(output/'preregistered.json', registration)
    write_json(output/'input.json', {'config': w['config'], **case})
    control = execute(w, case, output)
    with patch.object(engine.Snapshot, 'taints', return_value=[]):
        mutant = execute(w, case, output)
    result = {'status': 'PASS' if control['status']=='PASS' and mutant['status']=='FAIL' else 'FAIL',
              'case_id': 'quarantine-complete-count-followup', 'control': control,
              'mutant': mutant, 'killed': mutant['status']=='FAIL',
              'initial_mutation_result': 'SURVIVED; preserved in run-001/mutations.json',
              'claim': 'The improved witness kills this one mutation; no production bug was fixed and no general mutation coverage is claimed.'}
    write_json(output/'summary.json', result)
    return result


def run(output, seeds=SEEDS):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    temp = output / 'temporary'
    temp.mkdir()
    contract = preregistration(seeds)
    write_json(output/'preregistered.json', contract)
    (output/'source-properties.py').write_bytes(Path(__file__).read_bytes())
    contract_hash = sha(output/'preregistered.json')
    start = time.monotonic()
    records = []
    for seed in seeds:
        for factor in range(len(FACTORS)):
            w = world(seed, factor)
            for family in FAMILIES:
                if time.monotonic() - start > 280:
                    raise TimeoutError('Finite experiment budget exhausted; completed records retained')
                spec = specification(w, family)
                path = output / 'inputs' / f'{w["group"]}-{family}.json'
                write_json(path, {'config': w['config'], **spec})
                result = execute(w, spec, temp, output / 'financial-outputs' / f'{w["group"]}-{family}')
                result['input'] = str(path.relative_to(output))
                result['input_sha256'] = sha(path)
                records.append(result)
                with (output/'cases.jsonl').open('a') as handle:
                    handle.write(json.dumps(result, sort_keys=True)+'\n')
                if result['status'] == 'FAIL':
                    # All cases already have small (<=31 distinct records) exact
                    # witnesses. No unsupported claim that automated shrinking ran.
                    write_json(output/'failures'/f'{result["case_id"]}.json', {'result': result,'input': spec,'shrink':'NOT_RUN; bounded original witness retained'})
    mutations = mutation_checks(temp)
    write_json(output/'mutations.json', mutations)
    metrics = confusion(records)
    families = {}
    controls = [r for r in records if r['family'] == 'clean']
    for family in FAMILIES:
        rows = [r for r in records if r['family'] == family]
        # Shared baseline control results are referenced, not rerun or counted as
        # additional global observations. Family rows must not be summed.
        paired = rows + controls if rows[0]['truth_anomaly'] else rows
        families[family] = {'cases': len(rows), 'metrics': confusion(paired),
                            'shared_clean_controls': len(controls) if rows[0]['truth_anomaly'] else 0,
                            'elapsed_seconds': [r['seconds'] for r in rows],
                            'evidentiary_coverage': sum(bool(r['input_sha256']) for r in rows)/len(rows),
                            'detection_latency': 'NOT_MEASURED separately; elapsed_seconds includes intake and evaluation'}
    executed_ids = [r['case_id'] for r in records]
    scope_valid = (len(executed_ids)==len(set(executed_ids))==contract['planned_cases']
                   and set(executed_ids)==set(contract['expected_case_ids']))
    mutation_controls_valid = (len(mutations)==len(MUTATION_IDS)
                               and {r['mutation_id'] for r in mutations}==set(MUTATION_IDS)
                               and all(r['control']=='PASS' for r in mutations))
    summary = {'status': 'PASS' if scope_valid and mutation_controls_valid and all(r['status']=='PASS' for r in records) else 'FAIL',
               'scope_acceptance': {'exact_unique_case_roster': scope_valid,
                                    'expected_cases': contract['planned_cases'],
                                    'executed_unique_cases': len(set(executed_ids)),
                                    'mutation_controls_valid': mutation_controls_valid},
               'cases':len(records), 'groups':len(seeds)*len(FACTORS), 'passed':sum(r['status']=='PASS' for r in records),
               'failed':sum(r['status']!='PASS' for r in records), 'skipped':0,
               'metrics':metrics, 'by_family':families,'uncertainty':bootstrap(records),
               'undetected_injected_identity_anomalies': sum(r['truth_anomaly'] and r['observed']['reconciliation_state']=='MATCHED' for r in records),
               'undetected_injected_identity_anomalies_note': 'All same-count source-identity substitution controls are intentionally not detectable under count manifests; economics unchanged. These are known detection false negatives, not arithmetic false matches.',
               'false_financial_mismatches': 0 if all(r['status']=='PASS' for r in records) else None,
               'mutations': {'total':len(mutations), 'killed':sum(r['killed'] for r in mutations), 'survived':[r['mutation_id'] for r in mutations if not r['killed']]},
               'contract_sha256':contract_hash, 'contract_unchanged':sha(output/'preregistered.json')==contract_hash,
               'elapsed_seconds':time.monotonic()-start, 'command':sys.argv,
               'environment': {'python':sys.version,'sqlite':sqlite3.sqlite_version,'platform':platform.platform()},
               'claim': 'Finite synthetic contract checks only; no real-world detection rate, independence across derived rows or exhaustive reliability claim.',
               'lineage': ['seed + factor cell -> integer world', 'world -> exact JSON envelopes', 'envelopes -> application Store/reconcile', 'integer oracle + explicit contract -> validation', 'case labels + observed findings -> confusion metrics', 'world-group bootstrap -> finite-design uncertainty']}
    write_json(output/'summary.json',summary)
    temp.rmdir()
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--smoke', action='store_true', help='one seed, all four factor cells; no claim of full three-seed coverage')
    parser.add_argument('--quarantine-followup', action='store_true', help='the preregistered supplemental witness for the initially surviving quarantine mutation')
    args = parser.parse_args()
    if args.quarantine_followup:
        summary = quarantine_followup(args.output)
        print(json.dumps({'status': summary['status'], 'killed': summary['killed']}))
        return 0 if summary['status']=='PASS' else 1
    summary = run(args.output, (11,) if args.smoke else SEEDS)
    print(json.dumps({k: summary[k] for k in ('status','cases','passed','failed','metrics','mutations','elapsed_seconds')}, indent=2))
    return 0 if summary['status']=='PASS' else 1

if __name__ == '__main__':
    raise SystemExit(main())
