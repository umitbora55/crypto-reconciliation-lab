"""Small installed CLI gate for S13-F1/F2; consumes retained synthetic pairs."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def identity(path):
    raw = Path(path).read_bytes()
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def require(value, message):
    if not value:
        raise ValueError('REPLAY_MAINTENANCE: ' + message)


def validate_report(report, *, code, state, reason):
    require((report['status'], report['exit_code'], report['reason_code'], report['replay_state'])
            == ('ERROR' if code == 2 else state, code, reason, state), 'CLI status differs')
    require(report['operation_state'] == ('ERROR' if code == 2 else 'COMPLETE'), 'operation state differs')
    completed = state != 'NOT_EVALUATED'
    require(report['completion'] == dict.fromkeys(('validation', 'calculation', 'comparison'),
            'COMPLETED' if completed else 'NOT_COMPLETED'), 'completion flags differ')
    require(report['comparison']['state'] == {'REPRODUCED': 'EQUAL', 'DIVERGED': 'DIFFERENT',
            'NOT_EVALUATED': 'NOT_EVALUATED'}[state], 'comparison state differs')
    if state == 'DIVERGED':
        require(report['comparison']['total_differences'] > 0 and report['comparison']['differences'],
                'completed financial differences were lost')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tests', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    # Import the installed application before exposing only the test-helper path.
    import crypto_reconciliation_lab as package
    origin = Path(package.__file__).resolve()
    require(sys.flags.isolated and 'site-packages' in origin.parts, 'requires isolated installed package')
    root = args.output.absolute()
    root.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(args.tests.resolve()))
    from replay_link_repair_fixtures import link_pairs, ORIGINAL_PIN
    from stage13_1_output_fixture import write_pair
    protected, stream, sequence = link_pairs(root / 'inputs' / 'links')
    clean = write_pair(root / 'inputs' / 'clean', 'clean')
    divergent = write_pair(root / 'inputs' / 'divergent', 'divergent')
    pair = lambda row: (row['context_path'], row['run_path'], row['expected'])
    cases = [
        ('protected-positive', pair(protected), 0, 'REPRODUCED', 'REPLAY_REPRODUCED', False),
        ('stream-mismatch', pair(stream), 2, 'NOT_EVALUATED', 'REPLAY_INTEGRITY', False),
        ('sequence-mismatch', pair(sequence), 2, 'NOT_EVALUATED', 'REPLAY_INTEGRITY', False),
        ('old-pin', (stream['context_path'], stream['run_path'], ORIGINAL_PIN), 2, 'NOT_EVALUATED', 'REPLAY_INTEGRITY', False),
        ('clean-positive', clean, 0, 'REPRODUCED', 'REPLAY_REPRODUCED', False),
        ('clean-loop', clean, 2, 'REPRODUCED', 'REPLAY_OUTPUT', True),
        ('divergent-positive', divergent, 1, 'DIVERGED', 'REPLAY_DIVERGED', False),
        ('divergent-loop', divergent, 2, 'DIVERGED', 'REPLAY_OUTPUT', True),
    ]
    before = {p.relative_to(root).as_posix(): identity(p) for p in (root/'inputs').rglob('*.json')}
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
    results = []
    for name, (context, run, pin), code, state, reason, loop in cases:
        folder = root / 'commands' / name
        folder.mkdir(parents=True)
        if loop:
            (folder / 'loop').symlink_to('loop', target_is_directory=True)
        output = folder / 'loop' / 'report' if loop else folder / 'report'
        command = [sys.executable, '-I', '-B', '-m', 'crypto_reconciliation_lab',
                   'verify-execution-replay', '--context', str(context), '--run', str(run),
                   '--expected-execution-id', pin, '--output', str(output)]
        started = time.monotonic()
        done = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=60)
        (folder/'stdout.txt').write_bytes(done.stdout)
        (folder/'stderr.txt').write_bytes(done.stderr)
        row = {'id': name, 'argv': command, 'cwd': str(root), 'exit_code': done.returncode,
               'expected_exit': code, 'seconds': time.monotonic()-started,
               'stdout': identity(folder/'stdout.txt'), 'stderr': identity(folder/'stderr.txt')}
        (folder/'command.json').write_text(json.dumps(row, indent=2)+'\n')
        require(done.returncode == code and done.stderr == b'', name + ': CLI exit/stderr differs')
        report = json.loads(done.stdout)
        validate_report(report, code=code, state=state, reason=reason)
        require(report['inputs'] == {'context': identity(context), 'run': identity(run)}, name + ': input identity differs')
        if state != 'NOT_EVALUATED':
            worker_path = Path(report['runtime']['modules']['replay.worker']['path'])
            require(worker_path == origin.parent/'replay'/'worker.py', name + ': worker import differs')
        if loop:
            require(sorted(p.name for p in folder.iterdir()) == ['command.json', 'loop', 'stderr.txt', 'stdout.txt'],
                    name + ': partial publication')
            require((folder/'loop').is_symlink() and os.readlink(folder/'loop') == 'loop', name + ': loop changed')
        else:
            require(json.loads((output/'report.json').read_bytes()) == report and (output/'report.md').is_file(),
                    name + ': published report differs')
        results.append({**row, 'status': 'PASS', 'reason_code': reason, 'replay_state': state,
                        'completion': report['completion'], 'comparison': report['comparison']})
    after = {p.relative_to(root).as_posix(): identity(p) for p in (root/'inputs').rglob('*.json')}
    require(before == after, 'authoritative inputs changed')
    for prefix in ('clean', 'divergent'):
        normal = json.loads((root/'commands'/f'{prefix}-positive'/'stdout.txt').read_bytes())
        failed = json.loads((root/'commands'/f'{prefix}-loop'/'stdout.txt').read_bytes())
        for field in ('replay_state', 'completion', 'comparison', 'financial_summary'):
            require(normal[field] == failed[field], prefix + ': completed report changed at output failure')
    result = {'status': 'PASS', 'package_version': package.__version__, 'python': sys.version,
              'executable': sys.executable, 'origin': str(origin), 'isolated': bool(sys.flags.isolated),
              'cwd': str(Path.cwd()), 'case_count': len(results), 'cases': results,
              'inputs_unchanged': before, 'optional_available': {name: importlib.util.find_spec(name) is not None
                for name in ('cryptography', 'sklearn', 'numpy', 'scipy')},
              'scope': 'Retained synthetic inputs; renewed negative pins are TEST-ONLY; no signature validation.',
              'full_suite': 'NOT_RUN'}
    (root/'summary.json').write_text(json.dumps(result, indent=2, sort_keys=True)+'\n')
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
