"""Render the measured benchmark without converting narrower scope to advantage."""
import argparse
import hashlib
import json
from pathlib import Path


def render(source, report, summary, hardware=None):
    source, report, summary = map(Path, (source, report, summary))
    raw = source.read_bytes()
    data = json.loads(raw)
    if data.get("status") not in ("COMPLETE", "PARTIAL") or not data.get("summary"):
        raise ValueError("completed or explicitly partial measured evidence is required")
    compact = {key: data[key] for key in ("status", "protocol", "implementation", "host", "profiles", "repeats",
               "summary", "comparisons", "elapsed_seconds", "program_cost", "max_postprocess_disk_observation_bytes",
               "started_utc", "completed_utc", "comparative_speed_advantage")}
    compact["data_class"] = "FULLY_SYNTHETIC"
    compact["canonical_evidence"] = {"path": str(source), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    compact["trial_inventory"] = [{key: t.get(key) for key in ("events", "repeat", "method", "seed", "status", "exit_code", "reason", "subprocess_wall_seconds")} for t in data["trials"]]
    compact["censored_progress"] = []
    for trial in data["trials"]:
        if trial["status"] in ("TIMEOUT", "FAILED", "RESOURCE_LIMIT"):
            path = source.parent / "trials" / f"n{trial['events']}-r{trial['repeat']}-{trial['method']}" / "progress.json"
            if path.exists():
                compact["censored_progress"].append({"events": trial["events"], "repeat": trial["repeat"], "method": trial["method"], "last_recorded_progress": json.loads(path.read_text())})
    compact["warmup_count"] = len(data["warmups"])
    if hardware:
        hardware_bytes = Path(hardware).read_bytes()
        compact["hardware_observation"] = json.loads(hardware_bytes)
        compact["hardware_observation_proof"] = {"sha256": hashlib.sha256(hardware_bytes).hexdigest(), "bytes": len(hardware_bytes)}
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(json.dumps(compact, indent=2, sort_keys=True) + "\n")
    completed = sum(t["status"] == "PASS" for t in data["trials"])
    attempted = sum(t["method"] in ("stdlib_integer", "sqlite_integer", "production") for t in data["trials"])
    failed = [t for t in data["trials"] if t["status"] != "PASS"]
    lines = ["# Baseline comparison", "",
        f"**Measured program: {data['status']}. {completed} completed timed trials passed their independent output check, from {attempted} total timed attempts; {len(data['warmups'])} warmups are excluded from timing summaries.**",
        "",
        "**COMPARATIVE_SPEED_ADVANTAGE = INCONCLUSIVE.** Both references are `NARROWER_SCOPE`. They are alternatives for a finite common arithmetic task, not equivalent implementations of the complete application. All workloads are `FULLY_SYNTHETIC`; no bank, custodian, CSD or public-source transaction workload was measured. Runtime differences cannot establish institutional savings or risk reduction.",
        "",
        "The preregistered contract is [benchmark-protocol-v1.json](../contracts/benchmark-protocol-v1.json). The inspectable compact figures and full-result checksum are in [benchmark-summary.json](../evidence/benchmark-summary.json). Original commands, exit codes, stdout/stderr, input hashes, phase measurements and artifact retention inventories remain in the external canonical evidence directory recorded there.",
        "",
        "## Workload and equivalence boundary", "",
        "Each profile uses four investors, one asset, integer cents, one static economic/knowledge cut and complete count manifests. Repeated deposit → transfer → withdrawal triples cancel. The final one/two-event suffix gives a closed-form independent expected balance. All three methods read the same bytes for each matched repetition. The profiles use five predetermined seeds: 11,29,47,71,97.",
        "",
        "| Property | Integer stdlib / SQLite references | Production application | Parity |",
        "|---|---|---|---|",
        "| Input rows, cut, amounts and selected manifest counts | Same bytes; strict finite-domain checks | Same bytes through public Store.ingest | Within declared profiles |",
        "| Computed balances, liability, custody and findings | Python signed additions / SQLite INTEGER UNION-SUM | Decimal production engine projected into integer cents | Checked against independent analytic oracle for every completed trial |",
        "| Transactions | One SQLite transaction per input row; small result table | Public transaction-owned ingestion and result persistence | Both durable local transactions, different schemas and work |",
        "| Validation, intermediate states, corrections and report versions | Narrow validators; SQL baseline has no general intermediate-negative-state engine | Full application semantics and historical behavior | NARROWER_SCOPE |",
        "| Persisted/exported result | Common balances and findings only | Full ledger traces, receipt evidence and result payload | NARROWER_SCOPE |",
        "| Independence | Different Python and SQL arithmetic, shared reference input parser/persistence | No production helper in either reference or closed-form oracle | Shared reference parser is an explicit dependency |",
        "",
        "## Observed local execution", "",
        "Wall time is child work from input read through verification. It includes fresh database initialization, ingestion, reconciliation, result persistence, export and instrumentation. Interpreter startup and child artifact hashing are additionally available as subprocess wall times. Production reconciliation time is split using a test-owned Store subclass around the unmodified save_run method; its inclusive duration must not be added again to the exclusive compute/persist durations.",
        "",
        "| Events | Method | Completed repeats | Wall p50 s | Empirical p95 s | Throughput p50 events/s | CPU p50 s | Peak RSS p50 MiB | DB + export p50 MiB | Export bytes p50 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|"
    ]
    for row in data["summary"]:
        def metric(key, statistic="p50", factor=1):
            value = row.get(key)
            return f"{value[statistic] / factor:.6f}" if value else "NOT_RUN"
        lines.append(f"| {row['events']} | {row['method']} | {row['completed_repeats']} | {metric('wall_seconds')} | {metric('wall_seconds','p95_nearest_rank')} | {metric('throughput_events_per_second')} | {metric('cpu_seconds')} | {metric('peak_rss_kib',factor=1024)} | {metric('disk_bytes',factor=1024**2)} | {row['export_bytes'] if row['export_bytes'] is not None else 'NOT_RUN'} |")
    lines += ["", "The p95 column is the nearest-rank empirical percentile. With five repeats it is the observed maximum, not a reliable population-tail estimate. Peak RSS is Linux child ru_maxrss including interpreter/runtime; file sizes are logical bytes, not physical disk IO. Fresh interpreters/databases were used but the OS page cache was not cleared; these are not cold-disk measurements.", "",
        "## Paired differences and uncertainty", "",
        "| Events | Reference | Paired n | Production − reference median s | Exploratory bootstrap 95% interval s | Production/reference median ratio | Exploratory bootstrap 95% ratio interval |",
        "|---:|---|---:|---:|---|---:|---|"]
    for row in data["comparisons"]:
        def val(key):
            return f"{row[key]:.6f}" if row[key] is not None else "NOT_RUN"
        def interval(key):
            return "[" + ", ".join(f"{x:.6f}" for x in row[key]) + "]" if row[key] else "NOT_RUN"
        lines.append(f"| {row['events']} | {row['baseline']} | {row['n']} | {val('median_difference_seconds')} | {interval('difference_bootstrap95')} | {val('median_ratio')} | {interval('ratio_bootstrap95')} |")
    lines += ["", "Intervals use 2,000 seeded paired-block bootstrap resamples of the five matched workload/repetition groups. They are exploratory, conditional on this machine and generated population, and unstable at this n. Method order was seeded-random and reversed in alternate blocks. No completed outlier was removed or replaced. These ratios describe observed work with unequal evidence/persistence scope and must not be presented as equivalent-product speed superiority.", "",
        "## Phase observations", "",
        "| Events | Method | Read p50 s | Initialize p50 s | Ingest p50 s | Reconcile exclusive p50 s | Persist p50 s | Export p50 s | Verification p50 s |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in data["summary"]:
        if not row["completed_repeats"]:
            continue
        phases = row["phase_wall_medians"]
        vals = [f"{phases.get(k, 0):.6f}" for k in ("read_input", "initialize", "ingest", "reconcile", "persist_result", "export", "verification")]
        lines.append(f"| {row['events']} | {row['method']} | " + " | ".join(vals) + " |")
    cost = data["program_cost"]
    if hardware:
        obs = compact["hardware_observation"]
        lines += ["", f"Observed host: {', '.join(obs['cpu_models'])}; {obs['physical_ram_bytes_visible']/1024**3:.3f} GiB visible RAM; {obs['filesystem_type']} filesystem; physical disk model NOT_OBSERVABLE. CPU affinity and cgroup limits are retained in compact evidence. Python: {data['host']['python'].splitlines()[0]}; SQLite: {data['host']['sqlite']}."]
    lines += ["", "Phase medians need not sum to the median end-to-end time. Reference narrow validation, production import/projection, close and progress-log writes are additional measured work. Common arithmetic parity does not make these phase costs identical tasks.", "", "## Finite capacity and resource cost", "",
        f"The whole measured program used **{cost['elapsed_seconds_including_warmup_inputs_hashing_cleanup_statistics']:.3f} elapsed seconds**, **{cost['worker_cpu_seconds']:.3f} worker CPU seconds** and **{cost['controller_cpu_seconds']:.3f} controller CPU seconds** including warmups, input generation, hashing, cleanup and statistics. Post-process logical disk observations reached **{data['max_postprocess_disk_observation_bytes'] / 1024**2:.3f} MiB**; this is a sampled post-process maximum, not a continuously observed disk peak. Retained bytes before final summaries: **{cost['retained_bytes_before_final_summaries']}**.",
        "",
        "Single workers were bounded to 60 wall seconds, 60 CPU seconds, 1 GiB address space and 384 MiB per file; the program budget was 360 seconds with one worker. The benchmark owned-disk budget was 1 GiB. Physical IO, RAM-seconds and monetary cost were not measured/estimated. No provider price or institutional cost assumption is attached.", ""]
    if failed:
        lines += ["| Events | Repeat | Method | Observed status | Reason / exit |", "|---:|---:|---|---|---|"]
        for item in failed:
            detail = ("Controller deadline expired (subprocess.TimeoutExpired); POSIX exit status not captured"
                      if item["status"] == "TIMEOUT" else item.get("reason") or ("exit=" + str(item.get("exit_code"))))
            if item.get("stderr"):
                detail += "; " + item["stderr"].strip().splitlines()[-1]
            lines.append(f"| {item['events']} | {item['repeat']} | {item['method']} | {item['status']} | {detail.replace('|','/')} |")
        lines += ["", "A timeout/resource-limited trial is censored and retained, not a successful low-latency observation. The affected profile is partial; uncompleted repeats cannot support a five-pair claim. Every completed trial recorded its actual exit 0. For the TimeoutExpired case the controller retained elapsed time and progress but did not capture the final POSIX child exit status; null denotes that evidence limitation and must not be relabeled as an observed -9 or other exit."]
        for observation in compact["censored_progress"]:
            progress = observation["last_recorded_progress"]
            lines += ["", f"For {observation['events']} events / {observation['method']}, the last retained progress record was **{progress['phase']} / {progress['state']}**. The timeout was imposed by the experimental controller; it is not evidence of an application-level LIMIT response or successful completion of later phases."]
    else:
        lines += ["All declared profiles completed all five matched repetitions under these local budgets. This is a finite observation, not an unbounded capacity guarantee."]
    lines += ["", "This benchmark uses ordinary ingestion/reconciliation/export, not recorded-context export or offline replay. No result above 10,000 events is evidence that replay's eligible-receipt, captured-row, byte or timeout bounds were raised. One million events, months-long soak, macOS, distributed exactly-once and institutional transaction ground truth were NOT_RUN.",
        "", "## Reproduce", "", "Run from the repository root in the prepared Python environment, with a new output directory and a quiet local worker window:", "", "```sh",
        "python -B -m validation_lab.benchmark --mode full --output /path/to/new-benchmark",
        "python -B -m validation_lab.benchmark_report --input /path/to/new-benchmark/results.json --report /path/to/BASELINE_COMPARISON.md --summary /path/to/benchmark-summary.json",
        "```", "", "`--mode smoke` limits the profiles to 100 events while retaining five repetitions. Both modes are offline. Exit 0 means COMPLETE; exit 3 means explicitly PARTIAL. Preserve the typed JSON status rather than converting any generated report into PASS. Large databases/exports are omitted after hashes/sizes are recorded; all input JSON, per-trial metrics, commands and retention inventories are kept. Non-warmup 100-event DBs/exports are retained.",
        "", "## Harness review", "", "Independent review found that the first draft accepted declared event counts inconsistent with actual rows, accepted an empty profile list, and returned exit 0 for PARTIAL. These were repaired before timing. The retained 112-actual/100-declared/seed-79 witness changed from PASS to explicit rejection; regressions also cover empty/duplicate profiles and PARTIAL → exit 3. This is a repaired validation-harness defect, not a production financial defect. Ten final preflight tests passed; raw RED/GREEN evidence is retained under the external audit and benchmark/preflight directories.", ""]
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines))
    return compact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--hardware", type=Path)
    args = parser.parse_args()
    result = render(args.input, args.report, args.summary, args.hardware)
    print(json.dumps({"status": result["status"], "report": str(args.report), "summary": str(args.summary)}))


if __name__ == "__main__":
    main()
