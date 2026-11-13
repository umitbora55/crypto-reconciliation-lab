"""Launch the single gated A/B experiment and preserve its external execution proof."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs/stage3_3'
OUT = ROOT / 'stage3_3-output/ab'
PROOF = DOCS / 'ab_execution.json'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def complete_binding(execution, report_hash, markdown_hash):
    """A provisional report or receipt alone cannot establish completion."""
    terminal = execution.get('terminal_outcome') or {}
    receipt = execution.get('finalization_receipt') or {}
    valid_hashes = all(isinstance(value, str) and len(value) == 64
        and all(c in '0123456789abcdef' for c in value) for value in (report_hash, markdown_hash))
    return (valid_hashes and execution.get('exit_code') == 0
        and execution.get('source_and_installed_preserved') is True
        and terminal.get('status') == 'COMPLETED'
        and terminal.get('correctness') == 'PASSED'
        and terminal.get('completion_state') == 'COMPLETED'
        and terminal.get('shared_deadline_met') is True
        and receipt.get('status') == 'COMPLETED'
        and receipt.get('verified') is True
        and receipt.get('shared_deadline_met') is True
        and receipt.get('report_sha256') == report_hash
        and receipt.get('markdown_sha256') == markdown_hash)


def origin_manifest(verification):
    paths = set((ROOT / 'crypto_reconciliation_lab').rglob('*.py'))
    paths.update((ROOT / 'tests').glob('*.py'))
    paths.update((ROOT / 'scripts').glob('*stage3_3.py'))
    paths.update(ROOT / name for name in (
        'stage3_3-output/baseline/matrix/correctness.json',
        'stage3_3-output/verification/installed-matrix/correctness.json'))
    for info in (verification['installed_import'], load(DOCS / 'baseline.json')['installed_import']):
        paths.update(Path(info['file']).parent.rglob('*.py'))
    def entry(path):
        return str(path.relative_to(ROOT)), dict(bytes=path.stat().st_size, sha256=sha(path))
    with ThreadPoolExecutor(max_workers=128) as pool:
        return dict(pool.map(entry, sorted(paths)))


def main():
    if PROOF.exists() or OUT.exists():
        raise ValueError('preserve the existing experiment/proof; no automatic retry')
    record = dict(status='PREFLIGHT', experiment_started=False, commands=[],
        invocation=[sys.executable, *getattr(sys, 'orig_argv', [sys.executable])[1:]],
        invocation_cwd=str(Path.cwd().resolve()), ab_experiment_repeated=False)
    def save():
        PROOF.write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    save()
    try:
        verification = load(DOCS / 'verification.json')
        baseline = load(DOCS / 'baseline.json')
        assert verification['status'] == baseline['status'] == 'PASS'
        migration = load(DOCS / 'migration_verification.json')
        assert migration['status'] == 'COMPLETED' and migration['verified'] is True
        assert migration['build_fingerprint'] == verification['frozen_build_fingerprint']
        record.update(baseline_fingerprint=baseline['matrix']['build_fingerprint'],
            candidate_fingerprint=verification['frozen_build_fingerprint'])
        started = time.monotonic()
        record['before_manifest'] = origin_manifest(verification)
        record['source_read_preflight_seconds'] = time.monotonic() - started
        record['preflight_scope'] = 'Read-only source/tool/installed-source and both correctness-gate report hydration/hashes; outside the performance deadline. No cold-cache claim.'
        cache = ROOT / 'work/stage3_3/ab-runtime-cache'
        assert not cache.exists(), 'the explicit no-bytecode prefix must be new'
        command = [str(ROOT / '.venv-stage3_3/bin/python'), '-I', '-B', '-X', 'pycache_prefix=' + str(cache),
            str(ROOT / 'scripts/run_ab_stage3_3.py'),
            '--baseline-python', str(ROOT / '.venv-stage3_3-baseline/bin/python'),
            '--candidate-python', str(ROOT / '.venv-stage3_3/bin/python'),
            '--baseline-correctness', str(ROOT / 'stage3_3-output/baseline/matrix/correctness.json'),
            '--candidate-correctness', str(ROOT / 'stage3_3-output/verification/installed-matrix/correctness.json'),
            '--pycache-prefix', str(cache), '--output', str(OUT)]
        env = os.environ.copy(); env.pop('PYTHONPATH', None)
        with tempfile.TemporaryDirectory(prefix='stage3-3-launch-external-') as directory:
            cwd = Path(directory).resolve()
            record.update(status='RUNNING', experiment_started=True, command=command,
                          cwd=str(cwd), PYTHONPATH_removed=True)
            save(); started = time.monotonic()
            result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
            record.update(exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr,
                          controller_process_wall_seconds=time.monotonic() - started)
            save()
        terminals = []
        for line in result.stdout.splitlines():
            try:
                value = json.loads(line)
                if isinstance(value, dict) and value.get('version') == 'stage3.3-terminal-v1':
                    terminals.append(value)
            except ValueError:
                pass
        record['terminal_outcome'] = terminals[0] if len(terminals) == 1 else None
        record['observed_correctness_failure'] = (result.returncode == 3
            or (record['terminal_outcome'] or {}).get('correctness') == 'FAILED')
        save()
        record['finalization_receipt'] = load(OUT / 'finalization.json') if (OUT / 'finalization.json').exists() else None
        record['report_sha256'] = sha(OUT / 'ab.json') if (OUT / 'ab.json').exists() else None
        record['markdown_sha256'] = sha(OUT / 'ab.md') if (OUT / 'ab.md').exists() else None
        report = load(OUT / 'ab.json') if (OUT / 'ab.json').exists() else {}
        record['observed_correctness_failure'] |= report.get('correctness') == 'FAILED'
        save()
        started = time.monotonic(); record['after_manifest'] = origin_manifest(verification)
        record['post_run_provenance_audit_seconds'] = time.monotonic() - started
        record['source_and_installed_preserved'] = record['before_manifest'] == record['after_manifest']
        terminal = record['terminal_outcome'] or {}
        known_failure = record['observed_correctness_failure']
        if not record['source_and_installed_preserved']:
            known_failure = True
        record['complete_claim_verified'] = not known_failure and complete_binding(record, record['report_sha256'], record['markdown_sha256'])
        if known_failure:
            record.update(status='CORRECTNESS_FAILED', correctness='FAILED', completion_state=terminal.get('completion_state', 'ERROR'))
        elif record['complete_claim_verified']:
            record.update(status='COMPLETED', correctness='PASSED', completion_state='COMPLETED')
        else:
            state = terminal.get('completion_state', 'ERROR')
            if state == 'COMPLETED': state = 'ERROR'
            record.update(status=state, correctness=terminal.get('correctness', 'UNKNOWN'), completion_state=state)
        record['timing_scope'] = 'Controller wall includes gates/import/preparation and the shared-deadline experiment. Pre/post origin audits are separate proof work and never reset or extend that deadline.'
        save()
        print(json.dumps({k: record[k] for k in ('status', 'correctness', 'completion_state', 'exit_code', 'complete_claim_verified')}))
        return 0 if record['status'] == 'COMPLETED' else 3 if record['correctness'] == 'FAILED' else 4 if record['status'] == 'PARTIAL_BUDGET' else 2
    except Exception as exc:
        failed = (record.get('observed_correctness_failure') or record.get('exit_code') == 3
            or record.get('correctness') == 'FAILED' or record.get('source_and_installed_preserved') is False)
        record.update(status='CORRECTNESS_FAILED' if failed else 'ERROR',
            correctness='FAILED' if failed else record.get('correctness', 'UNKNOWN'),
            completion_state='ERROR', complete_claim_verified=False,
            error=repr(exc), traceback=traceback.format_exc()); save()
        raise


if __name__ == '__main__':
    raise SystemExit(main())
