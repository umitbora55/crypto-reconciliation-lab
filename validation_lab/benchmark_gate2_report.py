"""Render Gate 2's separately qualified common-task and capacity evidence."""
import argparse
import json
from pathlib import Path
import statistics

from validation_lab.benchmark import file_proof
from validation_lab.benchmark_gate2 import bindings, validate_record_inventory


def render(common_path, triage_path, report_path, summary_path):
    common_path, report_path, summary_path = map(Path,(common_path,report_path,summary_path))
    common=json.loads(common_path.read_text())
    common_check=validate_record_inventory(common,'full',bindings(),common_path.parent)
    triage=json.loads(Path(triage_path).read_text()) if triage_path else None
    if triage:
        validate_record_inventory(triage,'triage',bindings(),Path(triage_path).parent)
    compact={'format':'benchmark-gate2-report-v1','data_class':'FULLY_SYNTHETIC',
        'common':{key:common[key] for key in ('status','comparative_status','host','bindings','summary','comparisons','parity','generation','program_cost','max_postprocess_disk_bytes','started_utc','completed_utc','git_head_at_start')},
        'common_source':{'path':str(common_path),**file_proof(common_path)},'inventory_validation':common_check,
        'equal_evidence_history_lane':common['equal_evidence_history_lane'],
        'institutional_cost_savings':'NOT_PROVEN','institutional_risk_reduction':'NOT_PROVEN',
        'triage':{key:triage[key] for key in ('status','comparative_status','trials','generation','program_cost','started_utc','completed_utc')} if triage else {'status':'NOT_RUN'}}
    if triage:
        compact['triage_source']={'path':str(triage_path),**file_proof(triage_path)}
    summary_path.parent.mkdir(parents=True,exist_ok=True)
    summary_path.write_text(json.dumps(compact,indent=2,sort_keys=True)+'\n')
    lines=['# Gate 2 baseline comparison','',
        f"**Common lane: {common['status']} / {common['comparative_status']}. Capacity triage: {triage['status'] if triage else 'NOT_RUN'}.**",'',
        'Full evidence/history comparison remains **NOT_IMPLEMENTED / NARROWER_SCOPE / INCONCLUSIVE**. Institutional cost savings and risk reduction remain **NOT_PROVEN**. All observations below are FULLY_SYNTHETIC; no institution transaction workload or natural-error labels are introduced.','',
        'The earlier canonical report and measurements remain historical evidence: 10,000-event medians of 21.035740 s production, 13.567914 s stdlib and 12.854782 s SQLite; the earlier 100,000-event attempt timed out at60.065 s with final POSIX exit unrecorded. Gate2 uses a different, deliberately shared output/persistence contract and is not a before/after product-speed experiment.','',
        '## Contract and scope','',
        '| Lane | Input/validation | Output/persistence | Decision |',
        '|---|---|---|---|',
        '| Common arithmetic | Same exact finite static-cycle input bytes, common finite gate and public Store ingestion | Same integer projection, common SQLite result schema/commit, JSON bytes and independent reread verification | '+common['comparative_status']+' |',
        '| Full evidence/history | References lack full corrections, recorded context, historical policy and signatures | References lack the complete evidence/history/export service | NOT_IMPLEMENTED; NARROWER_SCOPE |','',
        'The three recomputations are independent stdlib signed additions, independent SQLite integer-string parsing/UNION/SUM, and the unchanged production reconciliation engine with a test-owned save_run output adapter. The adapter prevents rich-result persistence in this common lane. The production engine still builds traces/evidence in memory; that internal overhead is included. This measures the restricted common task, not the full public application service.','',
        'Shared normalization/admission, deterministic generation and common persistence are intentional dependencies. Arithmetic references and closed-form oracle do not call the production financial calculation. The finite gate accepts only the declared generated schedules; its ability to reject a substituted reference is synthetic workload conformance, not a repair of count-only production manifests. **The prior12 false negatives remain unchanged.**','',
        'Equivalence checks require exactly three distinct successful methods per size/repetition, matching input path/hash/bytes, code bindings, SQLite settings, common result, input database bytes, result database bytes and JSON export bytes. Empty/omitted/duplicate/substituted populations, nonzero PASS, missing actual child exit, altered input/source binding and false COMPLETE are rejected. The consistency checker is not cryptographic timing attestation or an institutional trust anchor.','',
        'Protocol: [benchmark-gate2-protocol.json](../../contracts/benchmark-gate2-protocol.json). Inspectable figures: [benchmark-gate2-summary.json](../../evidence/gate2/benchmark-gate2-summary.json). Full source paths/checksums, original commands/stdout/stderr and retention inventories are bound there.','',
        '## Common-task measurements','',
        '| Events | Method | Completed n | Wall p50 s | Empirical p95 s | CPU p50 s | Throughput p50 events/s | Peak RSS p50 MiB | Logical DB+export p50 MiB |',
        '|---:|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in common['summary']:
        def metric(key,stat='p50',divisor=1):
            return f"{row[key][stat]/divisor:.6f}" if row[key] else 'NOT_RUN'
        lines.append(f"|{row['events']}|{row['method']}|{row['completed_repeats']}|{metric('wall_seconds')}|{metric('wall_seconds','p95_nearest_rank')}|{metric('cpu_seconds')}|{metric('throughput_events_per_second')}|{metric('peak_rss_kib',divisor=1024)}|{metric('disk_bytes',divisor=1024**2)}|")
    lines += ['', 'All five seeds were preregistered (11,29,47,71,97). Method order was seeded/interleaved and reversed on alternate repetitions. Fresh interpreters/databases were used without clearing OS page cache. These are not cold-disk measurements. At n5 the nearest-rank empirical p95 is the maximum, not a stable population-tail estimate. No completed outlier was removed or replaced.','',
        '## Paired effects, conditional uncertainty','',
        '| Events | Reference | Paired n | Production−reference median s | Exploratory95% bootstrap interval s | Median production/reference ratio | Exploratory95% ratio interval |',
        '|---:|---|---:|---:|---|---:|---|']
    for row in common['comparisons']:
        def value(key): return f"{row[key]:.6f}" if row[key] is not None else 'NOT_RUN'
        def interval(key): return '['+', '.join(f'{x:.6f}' for x in row[key])+']' if row[key] else 'NOT_RUN'
        lines.append(f"|{row['events']}|{row['baseline']}|{row['n']}|{value('median_difference_seconds')}|{interval('difference_bootstrap95')}|{value('median_ratio')}|{interval('ratio_bootstrap95')}|")
    lines += ['', 'Intervals use2,000 seeded paired-block resamples of the five matched input/repetition groups. They are exploratory, conditional on this finite workload, host and cache policy, and unstable at this n. A common-task difference does not establish full-product, institution, SLA or monetary superiority.','',
        '## Generation and named phases','',
        '| Events | Distinct generated inputs | Generation wall p50 s | Generation CPU p50 s |','|---:|---:|---:|---:|']
    for n in sorted({r['events'] for r in common['generation']}):
        rows=[r for r in common['generation'] if r['events']==n]
        lines.append(f"|{n}|{len(rows)}|{statistics.median(r['wall_seconds'] for r in rows):.6f}|{statistics.median(r['cpu_seconds'] for r in rows):.6f}|")
    lines += ['', 'Each shared input was generated once per seed, outside child timing and explicitly measured above. It is not charged three times. The largest completed profile phase breakdown follows; every smaller-profile wall/CPU phase remains in raw metrics.','',
        '| Events | Method | Phase | Wall p50 s | CPU p50 s |','|---:|---|---|---:|---:|']
    completed=[t for t in common['trials'] if t['status']=='PASS']
    if completed:
        largest=max(t['events'] for t in completed)
        for method in ('stdlib_integer','sqlite_integer','production'):
            group=[t['metrics'] for t in completed if t['events']==largest and t['method']==method]
            if not group: continue
            for phase in ('read_input','validate_common_contract','initialize','ingest','recompute','persist','evidence_export','reread_verify'):
                lines.append(f"|{largest}|{method}|{phase}|{statistics.median(m['phases'][phase]['wall_seconds'] for m in group):.6f}|{statistics.median(m['phases'][phase]['cpu_seconds'] for m in group):.6f}|")
    lines += ['', 'Child end-to-end time includes read/validation/initialization/ingestion/recompute/common persistence/export/close/reread and progress instrumentation. Parent subprocess wall additionally includes interpreter startup and artifact hashing. Phase medians need not sum to end-to-end medians. Peak RSS includes the whole child interpreter/runtime, not only arithmetic.','',
        '## Capacity triage and actual exits','',
        'The100,000-event target is attempted first with the original60-second end-to-end cap. Separate25,000/50,000 attempts then localize the observed completion boundary. The triage program has180 seconds total; any smaller remaining-budget cap is recorded. Each attempt is a single production-common-task observation, not a five-repeat comparison or a full-history benchmark.','',
        '| Events | Status | Actual POSIX exit | Effective cap s | Subprocess wall s | Last retained phase/state | Last committed receipt count |',
        '|---:|---|---:|---:|---:|---|---:|']
    if triage:
        for row in triage['trials']:
            progress=row.get('last_progress',{})
            lines.append(f"|{row['events']}|{row['status']}|{row.get('exit_code','NOT_RUN')}|{row.get('timeout_seconds','NOT_RUN')}|{row.get('subprocess_wall_seconds','NOT_RUN')}|{progress.get('phase','NOT_RUN')} / {progress.get('state','NOT_RUN')}|{progress.get('committed_receipts','NOT_RUN')}|")
    else:
        lines += ['|100000 /25000 /50000|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|']
    lines += ['', 'For a new timeout, the controller kills the child if still running, then waits and records the actual POSIX returncode and original stdout/stderr. A recorded negative code is an observed signal termination, not an inferred substitute for historical null. Timeout is controller censoring, not an application LIMIT response. Partial progress does not establish successful recomputation/export/reread; no100k comparative latency is manufactured from an incomplete attempt.','',
        '## Resource costs and unmeasured quantities','']
    for label,data in [('common',common),('triage',triage)]:
        if not data: continue
        cost=data['program_cost']
        lines.append(f"{label}: elapsed **{cost['wall_seconds']:.3f}s**, worker CPU **{cost['worker_cpu_seconds']:.3f}s**, controller CPU **{cost['controller_cpu_seconds']:.3f}s**. These are measured local resources including generation/warmup/control work; no price assumption or institutional savings model is attached.")
        lines.append('')
    lines += ['Each child had60 wall seconds,60 CPU seconds,1GiB address space and384MiB/file limits; one active child; owned benchmark disk budget1GiB. Common program budget420s and separate triage180s were preregistered. Logical sizes are measured, not physical write traffic. `/proc/self/io` counters (where readable) are process accounting on overlayfs, not independent physical-device observations or billing; actual physical-device IO and RAM-seconds remain unmeasured.','',
        f"Host: {common['host']['platform']}; Python {common['host']['python'].splitlines()[0]}; SQLite {common['host']['sqlite']}. CPU affinity/cgroup limits and load observations are retained in evidence. Shared-host background interference cannot be excluded even with no other intentional validation job during the quiet window.",'',
        'No claim is made for million-event scale, months-long soak, distributed exactly-once, power-loss safety, frozen ML improvement or institutional deployment. Original count-only substitution errors and missing real data are separate gates; arithmetic timings cannot resolve them.','',
        '## Reproduce offline','', '```sh',
        'python -B -m validation_lab.benchmark_gate2 --mode full --output /path/to/new-common',
        'python -B -m validation_lab.benchmark_gate2 --mode triage --output /path/to/new-triage',
        'python -B -m validation_lab.benchmark_gate2_report --common /path/to/new-common/results.json --triage /path/to/new-triage/results.json --report /path/to/BASELINE_COMPARISON.md --summary /path/to/benchmark-gate2-summary.json',
        '```','',
        'Run sequentially in a quiet window. Exit0 means COMPLETE and exit3 preserves PARTIAL. Reporting checks the caller-selected full/triage population against the reviewed current source bindings; copying or inventing a self-issued pin is not measurement authentication. New output directories are required. Retention inventories distinguish hashed-but-omitted large DB/export files from retained100-event artifacts and all original inputs/commands/metrics/progress.','']
    report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text('\n'.join(lines))
    return compact


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--common',required=True,type=Path)
    parser.add_argument('--triage',type=Path)
    parser.add_argument('--report',required=True,type=Path)
    parser.add_argument('--summary',required=True,type=Path)
    args=parser.parse_args()
    result=render(args.common,args.triage,args.report,args.summary)
    print(json.dumps({'common':result['common']['status'],'triage':result['triage']['status'],'report':str(args.report)}))


if __name__=='__main__': main()
