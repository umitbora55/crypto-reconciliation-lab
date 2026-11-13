"""Sequential, correctness-gated Stage 3.2 diagnostic profiling experiment."""
import argparse
import json
from dataclasses import asdict
import os
from pathlib import Path
import shutil
import statistics
import sys
import tempfile
import time
from .benchmark import correctness_gate, statistics_for
from .common import build_fingerprint, digest_bytes, fresh, load, save
from .outcomes import normalize_outcome
from .watchdog import Budgets, directory_bytes, supervise

PROFILES = (('P1', 1000, 20), ('P3', 1000, 100), ('P2', 10000, 20))
MODES = ('normal', 'normal', 'normal', 'cprofile', 'tracemalloc')


def not_attempted(state, reason, mode):
    return dict(status=state, completion_state=state, correctness='UNKNOWN',
                reason=reason, measurement_mode=mode, exit_code=None)


def financial_signature(worker):
    return tuple(worker[key] for key in ('input_sha256', 'config_sha256', 'run_id')) + (
        worker['files']['report.json']['sha256'], worker['files']['report.md']['sha256'],
        json.dumps(worker['pragmas'], sort_keys=True))


def normal_statistics(trials):
    normal = [trial for trial in trials if trial.get('measurement_mode') == 'normal']
    if len(normal) != 3:
        return None
    result = statistics_for(normal)
    if result is not None and len({financial_signature(t['worker']) for t in normal}) != 1:
        raise ValueError('normal financial/evidence or config mismatch')
    if result is not None:
        for name in ('db_setup_seconds', 'ingest_jsonl_seconds', 'reconcile_and_persist_seconds', 'export_seconds', 'reopen_readback_seconds'):
            values = [t['worker']['process_cpu_seconds'][name] for t in normal]
            result['cpu_' + name] = dict(raw=values, min=min(values), median=statistics.median(values), max=max(values))
    return result


def completion_for(states):
    if states == {'COMPLETED'}:
        return 'COMPLETED'
    if states & {'ERROR', 'NOT_ATTEMPTED_ERROR'}:
        return 'ERROR'
    if states & {'RESOURCE_LIMIT', 'TIMED_OUT', 'NOT_ATTEMPTED_BUDGET', 'PARTIAL_BUDGET'}:
        return 'PARTIAL_BUDGET'
    if states & {'NOT_ATTEMPTED_CORRECTNESS', 'STOPPED_CORRECTNESS'}:
        return 'STOPPED_CORRECTNESS'
    return 'STOPPED_EARLY'


def markdown(report):
    lines = ['# Stage 3.2 diagnostic profiling measurements', '',
        f"Gate={report['gate_status']}; correctness={report['correctness']}; completion={report['completion_state']}.", '',
        'Normal runs alone form three-trial statistics. Each profiler run is one diagnostic observation, not a speedup, percentile or production-capacity estimate.', '',
        '| Profile | Events / investors | Normal completed | Median ingest / reconcile / export seconds | Profile modes |',
        '|---|---|---|---|---|']
    for profile in report['profiles']:
        stats = profile.get('statistics')
        medians = ' / '.join(f'{stats[k]["median"]:.6f}' for k in ('ingest_jsonl_seconds', 'reconcile_and_persist_seconds', 'export_seconds')) if stats else 'unavailable'
        completed = sum(t.get('status') == 'COMPLETED' and t['measurement_mode'] == 'normal' for t in profile['trials'])
        modes = '; '.join(t['measurement_mode'] + ':' + t['status'] for t in profile['trials'][3:])
        lines.append(f"| {profile['profile']} | {profile['events']} / {profile['investors']} | {completed}/3 | {medians} | {modes} |")
    lines += ['', 'Raw measurements, min/median/max, source fingerprint, per-worker counts, phase CPU/wall times, profiler records, artifact hashes and skipped-worker reasons are in profiling.json.',
        'RSS is whole-worker sampled/getrusage memory including oracle; tracemalloc is Python allocation tracing only. Snapshot changes are net live allocations. Cumulative profiler times overlap and must not be summed.',
        'No optimization, transaction/PRAGMA change, evidence reduction or cache was implemented.']
    return '\n'.join(lines) + '\n'


def run_profiling(correctness, output, budgets=None, profiles=None):
    gate = correctness_gate(correctness)
    budgets = budgets or Budgets()
    root = fresh(output)
    profiles = PROFILES if profiles is None else tuple(profiles)
    if not profiles or len({p[0] for p in profiles}) != len(profiles):
        raise ValueError('profiling requires a nonempty unique profile roster')
    start = time.monotonic()
    deadline = start + budgets.total_seconds
    report = dict(status='RUNNING', completion_state='RUNNING', correctness='UNKNOWN', gate_status='PASS',
        profiling_version='stage3.2-v1', build_fingerprint=gate['build_fingerprint'],
        correctness_report_sha256=digest_bytes(Path(correctness).read_bytes()), budgets=asdict(budgets),
        profile_order=[p[0] for p in profiles], modes=list(MODES), seed=11, profiles=[],
        shared_deadline=True, interpretation='Diagnostic measurements; no optimization performed.')
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    flags = ['-I'] if sys.flags.isolated else []
    blocked, halt = [], None

    def checkpoint():
        report['elapsed_seconds'] = time.monotonic() - start
        save(root / 'profiling.json', report)
        (root / 'profiling.md').write_text(markdown(report))

    def launch(job, temp, trial, module):
        jobfile = temp / (trial.parent.name + '-' + trial.name + '-job.json')
        save(jobfile, job)
        result = supervise([sys.executable, *flags, '-m', module, '--job', jobfile],
            Path.cwd(), trial, root, budgets, deadline, env)
        return normalize_outcome(result, 'generate' if job['mode'] == 'generate' else 'trial')

    def retain(trial, destination, outcome, case=None):
        destination.mkdir(parents=True, exist_ok=True)
        if not trial.exists():
            return
        # The live watchdog already charged generation, profiler files and hashing to
        # the same deadline/tree. Parent retention time also consumes that deadline.
        started = time.monotonic()
        worker = outcome.get('worker') or {}
        inventory = dict(worker.get('files', {}))
        for path in sorted(trial.iterdir()):
            if not path.is_file():
                continue
            if path.name not in inventory:
                inventory[path.name] = dict(bytes=path.stat().st_size, sha256=digest_bytes(path.read_bytes()))
            keep = (path.name in ('stdout.txt', 'stderr.txt', 'result.json', 'phase.json')
                    or path.suffix in ('.pstats', '.snapshot') or '-functions.' in path.name)
            if outcome['correctness'] == 'FAILED' and path.name.startswith('report.'):
                keep = True
            if keep:
                shutil.copy2(path, destination / path.name)
        outcome['retained_artifact_inventory'] = inventory
        outcome['parent_retention_seconds'] = time.monotonic() - started
        if outcome['correctness'] == 'FAILED' and case is not None:
            shutil.copytree(case, destination / 'counterexample-input')
        save(destination / 'artifact-manifest.json', dict(files=inventory,
            omitted=['trial.sqlite3 and sidecars', 'successful full report.json/report.md'],
            reproduction=outcome.get('reproduction'), correctness=outcome['correctness'],
            completion_before_retention_budget_check=outcome['completion_state'],
            outcome_record='Final parent completion is in profiling.json; worker result.json remains the raw child report.'))
        # Inventory and correctness are durable before deleting only our owned trial.
        checkpoint()
        # Observe the complete retained tree after counterexample/manifest writes.
        violation = None
        if time.monotonic() >= deadline:
            violation = ('TIMED_OUT', 'shared deadline exceeded during parent retention')
        elif directory_bytes(root) > budgets.temporary_bytes:
            violation = ('RESOURCE_LIMIT', 'experiment tree exceeded budget during parent retention')
        if violation:
            completion, reason = violation
            outcome['completion_state'] = completion
            outcome['status'] = 'CORRECTNESS_FAILED' if outcome['correctness'] == 'FAILED' else completion
            outcome['reason'] = reason
            outcome.setdefault('violations', []).append(dict(status=completion, reason=reason, method='parent-post-retention'))
        checkpoint()
        shutil.rmtree(trial)

    checkpoint()
    with tempfile.TemporaryDirectory(prefix='temporary-owned-', dir=root) as directory:
        temp = Path(directory).resolve()
        (temp / 'STAGE3_2_OWNED').write_text('Only this temporary experiment tree may be removed.\n')
        for name, events, investors in profiles:
            profile = dict(profile=name, events=events, investors=investors, assets=2,
                status='RUNNING', completion_state='RUNNING', correctness='UNKNOWN', trials=[], statistics=None)
            report['profiles'].append(profile)
            reason = halt
            state = 'NOT_ATTEMPTED_CORRECTNESS' if halt == 'known correctness failure' else 'NOT_ATTEMPTED_ERROR'
            if not reason and time.monotonic() >= deadline:
                reason, state = 'shared experiment deadline exhausted', 'NOT_ATTEMPTED_BUDGET'
            if not reason and any(events >= e and investors >= i for e, i in blocked):
                reason, state = 'larger related workload blocked by prior budget', 'NOT_ATTEMPTED_BUDGET'
            if reason:
                profile.update(status=state, completion_state=state, reason=reason)
                profile['trials'] = [not_attempted(state, reason, mode) for mode in MODES]
                checkpoint()
                continue
            folder = temp / name
            folder.mkdir()
            bundle, gen_trial = folder / 'bundle', folder / 'generation'
            generation = launch(dict(mode='generate', trial=str(gen_trial), bundle=str(bundle),
                seed=11, events=events, investors=investors), temp, gen_trial, 'crypto_reconciliation_lab.lab.worker')
            profile['generation'] = generation
            retain(gen_trial, root / name / 'generation', generation)
            if generation['status'] != 'COMPLETED':
                if generation['status'] in ('TIMED_OUT', 'RESOURCE_LIMIT', 'NOT_ATTEMPTED_BUDGET'):
                    blocked.append((events, investors)); state = 'NOT_ATTEMPTED_BUDGET'
                else:
                    halt = 'generation application failure'; state = 'NOT_ATTEMPTED_ERROR'
                profile.update(status=generation['status'], completion_state=generation['completion_state'],
                    reason='generation did not complete')
                profile['trials'] = [not_attempted(state, 'generation did not complete', mode) for mode in MODES]
                profile['partial_generation_files'] = {str(p.relative_to(folder)): dict(bytes=p.stat().st_size, sha256=digest_bytes(p.read_bytes()))
                    for p in folder.rglob('*') if p.is_file()}
                checkpoint()
                continue
            case = bundle / 'seed-11/CLEAN'
            profile['input_sha256'] = digest_bytes((case / 'input.jsonl').read_bytes())
            profile['config_sha256'] = digest_bytes((case / 'config.json').read_bytes())
            profile['generation_seconds'] = generation['worker']['timings']['generation_seconds']
            profile['input_inventory'] = {str(p.relative_to(bundle)): dict(bytes=p.stat().st_size, sha256=digest_bytes(p.read_bytes()))
                for p in bundle.rglob('*') if p.is_file()}
            reproduction = ['python3', '-m', 'crypto_reconciliation_lab', 'lab-generate', '--seed', '11',
                '--events', str(events), '--investors', str(investors), '--scenario', 'CLEAN', '--output', 'fresh-input']
            profile['reproduction'] = dict(generate=reproduction,
                experiment=['python3', '-m', 'crypto_reconciliation_lab.lab.profiling', '--correctness', str(correctness), '--output', 'fresh-profiling'])
            signature, stop_profile = None, None
            for number, mode in enumerate(MODES, 1):
                if halt or stop_profile or time.monotonic() >= deadline:
                    state = 'NOT_ATTEMPTED_CORRECTNESS' if halt == 'known correctness failure' else 'NOT_ATTEMPTED_ERROR' if halt else 'NOT_ATTEMPTED_BUDGET'
                    profile['trials'].append(not_attempted(state, halt or stop_profile or 'shared deadline exhausted', mode))
                    checkpoint()
                    continue
                trial = folder / (str(number) + '-' + mode)
                job = dict(mode=mode, trial=str(trial), case=str(case), seed=11, events=events,
                    investors=investors, generation_seconds=profile['generation_seconds'])
                measured = launch(job, temp, trial, 'crypto_reconciliation_lab.lab.profile_worker')
                measured.update(measurement_mode=mode, reproduction=profile['reproduction'])
                profile['trials'].append(measured)
                worker = measured.get('worker') or {}
                if measured['status'] == 'COMPLETED':
                    try:
                        current = financial_signature(worker)
                        if worker['input_sha256'] != profile['input_sha256'] or worker['config_sha256'] != profile['config_sha256']:
                            raise ValueError('worker input/config differs from generated profile')
                        if signature is not None and current != signature:
                            raise ValueError('financial/evidence/run parity differs between profiling modes')
                        if worker['build_fingerprint'] != report['build_fingerprint']:
                            raise ValueError('source fingerprint changed')
                        signature = current
                    except (KeyError, TypeError, ValueError) as exc:
                        measured.update(status='CORRECTNESS_FAILED', correctness='FAILED', reason=str(exc))
                        measured['parity_failed'] = True
                retain(trial, root / name / trial.name, measured, case)
                if measured['correctness'] == 'FAILED':
                    halt = 'known correctness failure'
                elif measured['status'] == 'ERROR':
                    halt = 'worker application failure'
                elif measured['status'] != 'COMPLETED':
                    blocked.append((events, investors)); stop_profile = 'prior worker budget stopped profile'
                checkpoint()
            states = {t['completion_state'] for t in profile['trials']}
            profile['correctness'] = 'FAILED' if any(t['correctness'] == 'FAILED' for t in profile['trials']) else 'PASSED' if all(t['correctness'] == 'PASSED' for t in profile['trials']) else 'UNKNOWN'
            profile['completion_state'] = completion_for(states)
            profile['status'] = 'CORRECTNESS_FAILED' if profile['correctness'] == 'FAILED' else profile['completion_state']
            try:
                profile['statistics'] = normal_statistics(profile['trials'])
                if profile['statistics'] is None and all(t['status'] == 'COMPLETED' for t in profile['trials'][:3]):
                    raise ValueError('three completed normals lack compatible verified statistics')
            except (ValueError, KeyError, TypeError) as exc:
                profile.update(status='ERROR', completion_state='ERROR', reason='invalid normal statistics: ' + str(exc))
                halt = 'invalid normal statistics'
            profile['all_modes_financial_evidence_parity'] = all(t['status'] == 'COMPLETED' for t in profile['trials'])
            checkpoint()
            shutil.rmtree(folder)
    report['correctness'] = 'FAILED' if any(p['correctness'] == 'FAILED' for p in report['profiles']) else 'PASSED' if all(p['correctness'] == 'PASSED' for p in report['profiles']) else 'UNKNOWN'
    states = {p['completion_state'] for p in report['profiles']}
    report['completion_state'] = completion_for(states)
    report['status'] = 'CORRECTNESS_FAILED' if report['correctness'] == 'FAILED' else report['completion_state']
    checkpoint()
    report['final_build_fingerprint'] = build_fingerprint()
    report['source_unchanged'] = report['final_build_fingerprint'] == report['build_fingerprint']
    if not report['source_unchanged']:
        report.update(correctness='FAILED', status='CORRECTNESS_FAILED', reason='source fingerprint changed during experiment')
    final_size = directory_bytes(root)
    report['final_budget_observation'] = dict(elapsed_seconds=time.monotonic()-start, experiment_tree_bytes=final_size,
        method='post-retention and report serialization; sampled, not a hard cap')
    if time.monotonic() >= deadline or final_size > budgets.temporary_bytes:
        report['completion_state'] = 'PARTIAL_BUDGET'
        report['status'] = 'CORRECTNESS_FAILED' if report['correctness'] == 'FAILED' else 'PARTIAL_BUDGET'
        report['final_budget_observation']['exceeded'] = True
    checkpoint()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--correctness', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        result = run_profiling(args.correctness, args.output)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print('status=' + result['status'] + ' correctness=' + result['correctness'] + ' completion=' + result['completion_state'])
    return 0 if result['status'] == 'COMPLETED' else 3 if result['correctness'] == 'FAILED' else 4 if result['status'] == 'PARTIAL_BUDGET' else 2


if __name__ == '__main__':
    raise SystemExit(main())
