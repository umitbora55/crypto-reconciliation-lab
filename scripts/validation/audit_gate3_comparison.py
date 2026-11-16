"""Independently audit the frozen Gate 2 common-task observations (stdlib only).

This is a byte/record/statistical consistency review, not a timing attestation.
It imports neither application code nor either benchmark implementation. Input
pins were selected from the retained Gate 2 corpus before this review's run.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import resource
import sqlite3
import statistics
import subprocess
import sys
import time

HEAD = "6876b384030a7cdab1d35445f66bf874768dcfce"
METHODS = ("stdlib_integer", "sqlite_integer", "production")
SEEDS = (11, 29, 47, 71, 97)
SIZES = (100, 1000, 10000)
PHASES = {"read_input", "validate_common_contract", "initialize", "ingest",
          "recompute", "persist", "evidence_export", "close", "reread_verify"}
INPUT_PINS = {
    (100, 11): (51307, '266a6716b7146025dae2bf7fd479eee47ef1f07f2e54cbd535382f5c099fe67a'),
    (100, 29): (51307, '8c06cb37641a121505fb713e6370c5a0e89f55c3bd28e55e4edfd5e8a04678a4'),
    (100, 47): (51307, '74e1b53f83d1eb1d4dcded42d33d1466ba9566f9b6c5d84bb10dfbe8e1db6f56'),
    (100, 71): (51307, '88dd87c4b4707181dbf945eb17f5efff66e4ac871e7cfd862cfaa0d9f4c21065'),
    (100, 97): (51307, 'bc5d32111bb53d409cfaf9b3329098fdf2ad2038d250a1c16e10135bd2b10858'),
    (1000, 11): (462909, '4b3a5ec36cb769d84672f6576eb589ae700e3a03cb6f0f349ceb23f44bc5c590'),
    (1000, 29): (462909, '9dd209bc78cc89d810355fba0816f913f9830e504593407ccf74897699aa6f93'),
    (1000, 47): (462909, '6d95b7c02991a86c8384c8be83f9143ead0eaffc3aa2911a32287917d6a7b7aa'),
    (1000, 71): (462909, '6e7579229816431eb6b39c3044e547f2bb4daf4685d363467e12bd0b672ec2a3'),
    (1000, 97): (462909, '163276fa53afd25f2e93d4c88b32c1ac16883d9ae921c83eec1f9c35d14fbc9d'),
    (10000, 11): (4596911, 'c246c488a9845ad11e9628fd647cb1fb826ec6bc797bd3684781f247801926c2'),
    (10000, 29): (4596911, '18b98a61385f52e66fbd4eb7c793f1cca44c10490cec3ed31cf7e3d8147a78aa'),
    (10000, 47): (4596911, '79bb5ef148e6fdd07eeff011dd98b0bcffb792ef13aa29b8629981d4f9a61535'),
    (10000, 71): (4596911, '422f39c3905d9ac9134c7c3ffcbce03727f08c8f7a3985f4b73eb3b04715686a'),
    (10000, 97): (4596911, 'ffb01c56ed527669e696f139ccfade7d935f74f6f5efc52d4596beed14e37dbc'),
}


def require(condition, message):
    if not condition:
        raise ValueError("COMPARISON_AUDIT: " + message)


def proof(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def load(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique)


def expected_order():
    result = []
    for size in SIZES:
        previous = list(METHODS)
        for repeat, seed in enumerate(SEEDS):
            order = (list(reversed(previous)) if repeat % 2
                     else random.Random(871 + size + repeat).sample(list(METHODS), 3))
            result.extend((size, repeat, seed, method) for method in order)
            previous = order
    return result


def verify_roster(trials):
    require(isinstance(trials, list), "missing trial roster")
    require([(t.get('events'), t.get('repeat'), t.get('seed'), t.get('method'))
             for t in trials] == expected_order(), "missing/duplicate/reordered/substituted trial")
    require(all(t.get('status') == 'PASS' and t.get('exit_code') == 0
                and t.get('timed_out') is False for t in trials),
            "frozen complete population requires 45 actual successful exits")


def independent_arithmetic(data):
    """Direct receipt fold, using decimal character parsing instead of helpers."""
    balances = {f'I{i}': 0 for i in range(4)}
    custody = {'platform': 0, 'external': 0}
    references = set()
    reports = {}
    for envelope in data['rows']:
        row = envelope['record']
        if row['kind'] == 'manifest':
            continue
        whole, fraction = row['amount'].split('.')
        require(whole.isdecimal() and len(fraction) == 2 and fraction.isdecimal(), 'amount format')
        value = int(whole) * 100 + int(fraction)
        if row['kind'] == 'opening':
            (balances if row['scope'] in balances else custody)[row['scope']] = value
        elif row['kind'] == 'event':
            require(row['ref'] not in references, 'duplicate event identity')
            references.add(row['ref'])
            sender, recipient = row['from_investor'], row['to_investor']
            if sender is not None:
                balances[sender] -= value
            if recipient is not None:
                balances[recipient] += value
            if row['type'] == 'deposit':
                custody[row['custody']] += value
            elif row['type'] == 'withdrawal':
                custody[row['custody']] -= value
            else:
                require(row['type'] == 'transfer', 'unknown event type')
        elif row['kind'] == 'report':
            reports[row['scope']] = value
        else:
            raise ValueError('COMPARISON_AUDIT: unexpected receipt kind')
    require(references == {f'E{i}' for i in range(data['events'])}, 'missing/substituted event IDs')
    require(all(reports[k] == v for k, v in {**balances, **custody}.items()), 'report vs independent fold')
    liability = sum(balances.values())
    require(liability == sum(custody.values()), 'liability vs custody')
    findings = {**{k: 0 for k in balances}, 'customer_liability': 0}
    return {'balances': balances, 'custody': custody, 'liability': liability,
            'differences': findings, 'outcomes': {k: 'MATCHED' for k in findings}}


def interval(values):
    # Reproduce the declared finite resampling protocol, without importing it.
    rng = random.Random(9281)
    draws = sorted(statistics.median(rng.choices(values, k=5)) for _ in range(2000))
    return [draws[49], draws[1949]]


def statistics_from_trials(trials):
    verify_roster(trials)
    summaries, comparisons = [], []
    by_identity = {(t['events'], t['repeat'], t['method']): t for t in trials}
    for size in SIZES:
        for method in METHODS:
            rows = [by_identity[size, r, method]['metrics'] for r in range(5)]
            summary = {'events': size, 'method': method, 'completed_repeats': 5, 'status': 'MEASURED'}
            for name in ('wall_seconds', 'cpu_seconds', 'peak_rss_kib', 'disk_bytes',
                         'throughput_events_per_second'):
                values = sorted(r[name] for r in rows)
                require(all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in values),
                        'invalid resource metric')
                summary[name] = {'p50': values[2], 'p95_nearest_rank': values[4],
                                 'min': values[0], 'max': values[4]}
            summary['export_bytes'] = statistics.median(r['artifacts']['export.json']['bytes'] for r in rows)
            summary['phase_wall_medians'] = {
                p: statistics.median(r['phases'][p]['wall_seconds'] for r in rows) for p in PHASES}
            summaries.append(summary)
        for baseline in METHODS[:2]:
            pairs = []
            for repeat in range(5):
                a = by_identity[size, repeat, baseline]['metrics']['wall_seconds']
                b = by_identity[size, repeat, 'production']['metrics']['wall_seconds']
                require(a > 0 and b > 0, 'nonpositive completed elapsed time')
                pairs.append({'repeat': repeat, 'production_minus_baseline_seconds': b-a,
                              'production_divided_by_baseline': b/a})
            differences = [p['production_minus_baseline_seconds'] for p in pairs]
            ratios = [p['production_divided_by_baseline'] for p in pairs]
            comparisons.append({'events': size, 'baseline': baseline, 'pairs': pairs, 'n': 5,
                                'median_difference_seconds': statistics.median(differences),
                                'median_ratio': statistics.median(ratios),
                                'difference_bootstrap95': interval(differences),
                                'ratio_bootstrap95': interval(ratios),
                                'semantic_parity': 'EQUIVALENT_COMMON_ARITHMETIC',
                                'speed_advantage': 'DESCRIPTIVE_COMMON_TASK_ONLY; FULL_PRODUCT_INCONCLUSIVE'})
    return summaries, comparisons


def audit(record, evidence_root, source_root=None):
    """Review an object against caller-selected retained evidence and fixed scope."""
    root = Path(evidence_root).resolve()
    verify_roster(record.get('trials'))
    require(record.get('status') == 'COMPLETE' and record.get('mode') == 'full'
            and record.get('data_class') == 'FULLY_SYNTHETIC', 'wrong comparison population')
    require(record.get('equal_evidence_history_lane', {}).get('status') == 'NOT_IMPLEMENTED',
            'unsupported full-history equivalence claim')
    bindings = record.get('bindings', {})
    require(len(bindings) == 94, 'source inventory length')
    git_commands = []
    if source_root is not None:
        argv = ['git', 'ls-tree', '-r', '--name-only', HEAD]
        listing = subprocess.run(argv, cwd=source_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        git_commands.append({'argv': argv, 'cwd': str(source_root), 'exit_code': listing.returncode,
                             'stdout': listing.stdout.decode(), 'stderr': listing.stderr.decode()})
        expected_names = {name for name in listing.stdout.decode().splitlines()
                          if name.startswith('crypto_reconciliation_lab/') and Path(name).suffix in ('.py', '.json')}
        expected_names.update({'validation_lab/benchmark.py', 'validation_lab/benchmark_gate2.py',
                               'validation_tests/test_gate2_benchmark.py', 'contracts/benchmark-gate2-protocol.json'})
        require(listing.returncode == 0 and set(bindings) == expected_names, 'exact historical source roster differs')
        for name, bound in sorted(bindings.items()):
            argv = ['git', 'show', HEAD + ':' + name]
            result = subprocess.run(argv, cwd=source_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            git_commands.append({'argv': argv, 'cwd': str(source_root), 'exit_code': result.returncode,
                                 'stdout': result.stdout.decode(), 'stdout_proof': proof(result.stdout),
                                 'stderr': result.stderr.decode()})
            require(result.returncode == 0 and proof(result.stdout) == bound, 'Git source differs: ' + name)
    inputs, readback, roster = {}, [], []
    for (size, seed), (byte_count, digest) in INPUT_PINS.items():
        path = root / 'inputs' / f'events{size}-seed{seed}.json'
        require(path.is_file() and not path.is_symlink(), 'missing raw-byte input')
        raw = path.read_bytes()
        require(proof(raw) == {'bytes': byte_count, 'sha256': digest}, 'externally fixed input corpus changed')
        data = load(path)
        require((data['events'], data['seed'], len(data['rows'])) == (size, seed, size+17), 'input scope')
        inputs[size, seed] = {'proof': {'path': str(path), **proof(raw)},
                              'output': independent_arithmetic(data)}
    for index, trial in enumerate(record['trials']):
        size, repeat, seed, method = (trial[k] for k in ('events', 'repeat', 'seed', 'method'))
        folder = root / 'trials' / f'n{size}-r{repeat}-{method}'
        require(load(folder / 'command.json') == trial, 'timing/trial differs from retained command log')
        metric = load(folder / 'metrics.json')
        require(metric == trial['metrics'], 'timing differs from retained metric log')
        expected_input = inputs[size, seed]['proof']
        require(trial['input'] == metric['input'] == expected_input, 'trial input linkage')
        require(metric['bindings'] == bindings, 'worker source differs')
        require(metric['common_output'] == inputs[size, seed]['output'], 'independent arithmetic disagreement')
        require((metric['events'], metric['seed'], metric['method'], metric['rows'])
                == (size, seed, method, size+17), 'worker metric identity')
        require(metric['sqlite_settings'] == {'journal_mode': 'delete', 'page_size': 4096, 'synchronous': 2},
                'SQLite settings changed')
        require(set(metric['phases']) == PHASES, 'phase inventory')
        require(0 < metric['wall_seconds'] <= trial['subprocess_wall_seconds'] < trial['timeout_seconds'],
                'child timing inconsistent with parent clock/limit')
        require(metric['throughput_events_per_second'] == size / metric['wall_seconds'], 'throughput denominator')
        require(sum(p['wall_seconds'] for p in metric['phases'].values()) <= metric['wall_seconds'],
                'phase wall exceeds total')
        require(sum(p['cpu_seconds'] for p in metric['phases'].values()) <= metric['cpu_seconds'],
                'phase CPU exceeds total')
        require(trial['command'][1:] == ['-B', '-m', 'validation_lab.benchmark_gate2', '--worker',
                method, '--input', expected_input['path'], '--output', str(folder)], 'command arguments')
        require(json.loads(trial['stdout']) == {'status': 'PASS', 'output': str(folder)}
                and trial['stderr'] == '', 'stdout/stderr status')
        start = datetime.strptime(trial['started_utc'], '%Y-%m-%dT%H:%M:%SZ')
        end = datetime.strptime(trial['completed_utc'], '%Y-%m-%dT%H:%M:%SZ')
        require(abs((end-start).total_seconds() - trial['subprocess_wall_seconds']) < 1.0,
                'parent elapsed disagrees with second-resolution UTC bounds')
        if size == 100:
            for name, bound in metric['artifacts'].items():
                require(proof((folder/name).read_bytes()) == bound, 'retained artifact changed')
            with sqlite3.connect(f'file:{folder}/input.sqlite3?mode=ro&immutable=1', uri=True) as db:
                counts = [db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                          for table in ('receipts', 'records', 'runs')]
            require(counts == [117, 117, 0], 'input DB receipts/records/runs')
            with sqlite3.connect(f'file:{folder}/result.sqlite3?mode=ro&immutable=1', uri=True) as db:
                result = db.execute('SELECT id,payload FROM common_result').fetchall()
            require(len(result) == 1 and result[0][0] == 1
                    and json.loads(result[0][1]) == inputs[size, seed]['output'], 'result DB arithmetic')
            require(load(folder/'export.json') == inputs[size, seed]['output'], 'export arithmetic')
            readback.append(folder.name)
        roster.append({'order': index, 'events': size, 'physical_receipts': size+17, 'repeat': repeat,
                       'seed': seed, 'method': method, 'status': 'PASS', 'exit_code': trial['exit_code'],
                       'input': expected_input, 'source_head': HEAD,
                       'source_head_role': 'POSTEXECUTION_COMMIT_BINDING',
                       'observed_git_head_at_measurement_start': record['git_head_at_start'],
                       'command': trial['command'],
                       'command_proof': proof((folder/'command.json').read_bytes()),
                       'metrics_proof': proof((folder/'metrics.json').read_bytes()),
                       'wall_seconds': metric['wall_seconds'], 'cpu_seconds': metric['cpu_seconds'],
                       'peak_rss_kib': metric['peak_rss_kib'], 'disk_bytes': metric['disk_bytes'],
                       'expected_actual': 'INDEPENDENT_ARITHMETIC_EQUAL'})
    for size in SIZES:
        for repeat in range(5):
            group = [t['metrics'] for t in record['trials'] if t['events'] == size and t['repeat'] == repeat]
            require(all(g[k] == group[0][k] for g in group for k in
                        ('input', 'common_output', 'sqlite_settings', 'artifacts', 'bindings')),
                    'matched-block parity disagreement')
    summaries, comparisons = statistics_from_trials(record['trials'])
    require(summaries == record.get('summary'), 'contradictory derived p50/p95/resource summary')
    require(comparisons == record.get('comparisons'), 'contradictory paired effect/interval')
    return {'format': 'gate3-independent-comparison-audit-v1', 'status': 'PASS',
            'data_class': 'FULLY_SYNTHETIC', 'source_head': HEAD,
            'source_head_role': 'POSTEXECUTION_COMMIT_BINDING',
            'observed_git_head_at_measurement_start': record['git_head_at_start'],
            'trial_count': 45,
            'matched_blocks': 15, 'input_count': 15, 'source_binding_count': 94,
            'source_git_verified': source_root is not None, 'git_commands': git_commands,
            'trial_roster': roster, 'summary': summaries, 'comparisons': comparisons,
            'retained_100_event_database_readbacks': readback,
            'larger_database_readbacks': 'NOT_RUN: intentionally omitted in Gate2 after hashing',
            'full_evidence_history_superiority': 'INCONCLUSIVE', 'comparator': 'COMPARATOR_NOT_AVAILABLE',
            'cost_savings': 'NOT_PROVEN', 'measurement_authenticity': 'NOT_ATTESTED',
            'dependency_overlap': ['Python standard library', 'same immutable observed command/metric/input bytes',
                                   'same declared randomization and bootstrap protocol; independent implementation'],
            'qualification': 'n=5; empirical p95 is observed maximum; no timing rerun or population-tail claim'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-root', required=True, type=Path)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    command = {'argv': [sys.executable, *sys.argv], 'cwd': str(Path.cwd()),
               'interpreter': sys.executable, 'python': sys.version, 'script_origin': str(Path(__file__).resolve()),
               'script_proof': proof(Path(__file__).read_bytes()),
               'input_proof': proof((args.evidence_root/'results.json').read_bytes()),
               'started_utc': datetime.now(timezone.utc).isoformat(),
               'effective_limits': {str(k): list(resource.getrlimit(k)) for k in
                                    (resource.RLIMIT_CPU, resource.RLIMIT_AS, resource.RLIMIT_FSIZE)},
               'no_application_or_research_imports': True}
    (args.output/'command-start.json').write_text(json.dumps(command, indent=2, sort_keys=True)+'\n')
    try:
        result = audit(load(args.evidence_root/'results.json'), args.evidence_root, args.source_root)
        (args.output/'audit.json').write_text(json.dumps(result, indent=2, sort_keys=True)+'\n')
        output = json.dumps({'status': result['status'], 'trials': result['trial_count'], 'matched_blocks': 15})+'\n'
        code, error = 0, ''
    except Exception as exc:
        output, code, error = '', 1, f'{type(exc).__name__}: {exc}\n'
    (args.output/'stdout.txt').write_text(output)
    (args.output/'stderr.txt').write_text(error)
    command.update({'exit_code': code, 'completed_utc': datetime.now(timezone.utc).isoformat(),
                    'wall_seconds': time.monotonic()-start, 'script_unchanged': command['script_proof'] == proof(Path(__file__).read_bytes())})
    (args.output/'command-completion.json').write_text(json.dumps(command, indent=2, sort_keys=True)+'\n')
    sys.stdout.write(output)
    sys.stderr.write(error)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
