#!/usr/bin/env python3
"""Bounded offline orchestration; never turns absent real data into a PASS."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
DISK_BUDGET = 5 * 1024**3
ROSTER_SHA256 = 'd11dc754571ceac5a4ab8f6aa1f1ae473380228dcae29e5cc462a0997dc9fe25'


def accepted_summary(output, name, result, argv):
    """Check complete finite inventories, not a child's self-reported PASS alone."""
    if result.get('status') not in ('PASS', 'COMPLETE'):
        return False
    folder = output/name
    roster_bytes = (ROOT/'contracts/validation-runner-roster-v1.json').read_bytes()
    if hashlib.sha256(roster_bytes).hexdigest() != ROSTER_SHA256:
        return False
    roster = json.loads(roster_bytes)
    if name == 'properties':
        protocol = json.loads((folder/'preregistered.json').read_text())
        rows = [json.loads(line) for line in (folder/'cases.jsonl').read_text().splitlines()]
        seeds = [11] if '--smoke' in argv else [11, 29, 47]
        if (protocol['seeds'] != seeds or protocol['families'] != roster['property_families']
                or protocol['factor_cells'] != roster['property_factors']):
            return False
        expected = {f's{s}-f{f}-{family}' for s in seeds for f in range(4) for family in protocol['families']}
        observed = [r['case_id'] for r in rows]
        return (len(expected) == len(rows) == len(set(observed)) == result['cases'] == result['passed']
                and set(observed) == expected and result['failed'] == result['skipped'] == 0
                and all(r['status'] == 'PASS' for r in rows))
    if name == 'resilience':
        protocol = json.loads((folder/'protocol.json').read_text())
        expected = protocol['expected_case_ids']
        if expected != roster['resilience_ids']:
            return False
        rows = result['cases']
        observed = [r['case_id'] for r in rows]
        return (len(expected) == len(set(expected)) == len(rows) == len(set(observed)) == result['case_count'] == 33
                and set(observed) == set(expected)
                and all(r['passed'] is True and r['expected'] == r['actual'] for r in rows))
    if name == 'benchmark':
        index = argv.index('--profiles')
        profiles = [int(x) for x in argv[index+1:]]
        expected = {f'n{n}-r{r}-{m}' for n in profiles for r in range(5)
                    for m in ('stdlib_integer', 'sqlite_integer', 'production')}
        rows = result['cases']
        observed = [r['case_id'] for r in rows]
        return (len(expected) == len(rows) == len(set(observed)) == result['executed_trials'] == result['passed_trials']
                and set(observed) == expected and all(r['status'] == 'PASS' for r in rows))
    return False


def tree_bytes(root):
    total = 0
    for path in root.rglob('*'):
        try:
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        except FileNotFoundError:
            pass  # A task-owned temporary file was removed during enumeration.
    return total


def run_stage(output, name, argv, timeout, environment):
    folder = output / 'commands' / name
    folder.mkdir(parents=True)
    record = {'stage': name, 'argv': list(map(str, argv)), 'cwd': str(ROOT),
              'started_at': datetime.now(timezone.utc).isoformat(),
              'timeout_seconds': timeout, 'status': 'RUNNING'}
    (folder / 'command.json').write_text(json.dumps(record, indent=2) + '\n')
    started = time.monotonic()
    with (folder / 'stdout.txt').open('w') as stdout, (folder / 'stderr.txt').open('w') as stderr:
        child = subprocess.Popen(record['argv'], cwd=ROOT, env=environment, stdout=stdout,
                                 stderr=stderr, start_new_session=True)
        next_disk_check = started
        stop = None
        while child.poll() is None:
            now = time.monotonic()
            if now - started > timeout:
                stop = 'TIMEOUT'
            if now >= next_disk_check:
                if tree_bytes(output) > DISK_BUDGET:
                    stop = 'DISK_BUDGET'
                next_disk_check = now + 5
            if stop:
                os.killpg(child.pid, signal.SIGKILL)
                break
            time.sleep(0.1)
        code = child.wait()
    record.update(exit_code=code, seconds=time.monotonic() - started,
                  status=stop or ('PASS' if code == 0 else 'FAILED'))
    if code == 0 and name == 'research-tests':
        match = re.search(r'Ran (\d+) tests?', (folder/'stderr.txt').read_text())
        record['executed_tests'] = int(match.group(1)) if match else 0
        if not record['executed_tests']:
            record['status'] = 'FAILED_EMPTY_TEST_RUN'
    if code in (0, 3) and name in {'properties', 'resilience', 'benchmark'}:
        report = output/name/'summary.json'
        if not report.is_file():
            record['status'] = 'FAILED_MISSING_SUMMARY'
        else:
            result = json.loads(report.read_text())
            record['observed_result_status'] = result.get('status')
            if result.get('status') == 'PARTIAL':
                record['status'] = 'PARTIAL'
            elif not accepted_summary(output, name, result, record['argv']):
                record['status'] = 'FAILED_SUMMARY_SCOPE'
    if code == 0 and name == 'fetch-public':
        sources = json.loads((output/'public-data/source-register.json').read_text())['sources']
        record['downloaded_sources'] = sum(s.get('status') == 'DOWNLOADED' for s in sources)
        if not sources or any(s.get('status') != 'DOWNLOADED' for s in sources):
            record['status'] = 'PARTIAL'
    if code == 0 and name == 'public-data-validation':
        result = json.loads((output/'public-validation').read_text())
        record['observed_result_status'] = result.get('status')
        if result.get('status') != 'REAL_DATA_VALIDATED' or result.get('real_financial_equalities_verified', 0) < 1:
            record['status'] = 'PARTIAL'
    (folder / 'command.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['smoke', 'full'], default='smoke')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--no-network', action='store_true')
    parser.add_argument('--fetch-public', action='store_true')
    parser.add_argument('--with-release', action='store_true', help='one source/installed full gate; requires pinned build/AI/auth packages')
    args = parser.parse_args()
    if args.fetch_public and (args.no_network or os.environ.get('NO_NETWORK') == '1'):
        parser.error('NO_NETWORK forbids --fetch-public')
    if args.with_release and (args.no_network or os.environ.get('NO_NETWORK') == '1'):
        parser.error('NO_NETWORK forbids --with-release because its isolated installer downloads packages')
    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        parser.error('raw evidence must be outside the checkout')
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1')
    if not args.fetch_public and not args.with_release:
        env['NO_NETWORK'] = '1'
    py = sys.executable
    stages = [('research-tests', [py, '-B', '-m', 'unittest', 'discover', '-s', 'validation_tests', '-v'], 180),
              ('properties', [py, '-B', '-m', 'validation_lab.properties', '--output', output/'properties'] + (['--smoke'] if args.mode == 'smoke' else []), 180),
              ('resilience', [py, '-B', '-m', 'validation_lab.resilience', '--output', output/'resilience'], 180),
              ('benchmark', [py, '-B', '-m', 'validation_lab.benchmark', '--output', output/'benchmark', '--profiles'] + (['100'] if args.mode == 'smoke' else ['100', '1000', '10000', '100000']), 420)]
    if args.fetch_public:
        stages.insert(0, ('fetch-public', [py, '-B', 'scripts/validation/fetch_public_data.py', '--fetch', '--output', output/'public-data'], 300))
        stages.insert(1, ('public-data-validation', [py, '-B', '-m', 'validation_lab.public_data', '--source-root', output/'public-data', '--output', output/'public-validation'], 60))
    if args.with_release:
        stages.append(('release-full', [py, '-B', 'scripts/verify_release.py', '--profile', 'full', '--financial', '--output', output/'release'], 1200))
    protocol = {'format': 'validation-run-v1', 'mode': args.mode, 'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'no_network_for_research': not args.fetch_public, 'release_install_requires_package_network': args.with_release,
                'disk_budget_bytes': DISK_BUDGET, 'stages': [{'name': n, 'argv': list(map(str, a)), 'timeout_seconds': t} for n,a,t in stages],
                'note': 'PASS means scheduled local commands succeeded, never a global reliability or real-data claim.'}
    (output/'protocol.json').write_text(json.dumps(protocol, indent=2)+'\n')
    results = []
    for name, argv, timeout in stages:
        if tree_bytes(output) > DISK_BUDGET:
            results.append({'stage': name, 'status': 'NOT_RUN', 'reason': 'DISK_BUDGET'})
            continue
        result = run_stage(output, name, argv, timeout, env)
        results.append(result)
        print(f'{name}: {result["status"]}', flush=True)
    status = 'PASS' if results and all(r['status'] == 'PASS' for r in results) else 'PARTIAL'
    (output/'summary.json').write_text(json.dumps({'status': status, 'stages': results,
        'public_real_data': 'SEE_PUBLIC_VALIDATION' if args.fetch_public else 'NOT_RUN',
        'full_release': 'SEE_RELEASE' if args.with_release else 'NOT_RUN',
        'institutional_cost_savings': 'NOT_PROVEN', 'institutional_risk_reduction': 'NOT_PROVEN'}, indent=2)+'\n')
    entries = []
    for path in sorted(output.rglob('*')):
        if path.is_file() and not path.is_symlink():
            data = path.read_bytes()
            entries.append({'path': str(path.relative_to(output)), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    (output/'manifest.json').write_text(json.dumps({'excludes': ['manifest.json (self-reference)'], 'files': entries}, indent=2)+'\n')
    return 0 if status == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
