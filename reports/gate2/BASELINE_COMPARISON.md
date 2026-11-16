# Gate 2 baseline comparison

**Common lane: COMPLETE / EQUIVALENT_COMMON_ARITHMETIC. Capacity triage: PARTIAL.**

Full evidence/history comparison remains **NOT_IMPLEMENTED / NARROWER_SCOPE / INCONCLUSIVE**. Institutional cost savings and risk reduction remain **NOT_PROVEN**. All observations below are FULLY_SYNTHETIC; no institution transaction workload or natural-error labels are introduced.

The earlier canonical report and measurements remain historical evidence: 10,000-event medians of 21.035740 s production, 13.567914 s stdlib and 12.854782 s SQLite; the earlier 100,000-event attempt timed out at60.065 s with final POSIX exit unrecorded. Gate2 uses a different, deliberately shared output/persistence contract and is not a before/after product-speed experiment.

## Contract and scope

| Lane | Input/validation | Output/persistence | Decision |
|---|---|---|---|
| Common arithmetic | Same exact finite static-cycle input bytes, common finite gate and public Store ingestion | Same integer projection, common SQLite result schema/commit, JSON bytes and independent reread verification | EQUIVALENT_COMMON_ARITHMETIC |
| Full evidence/history | References lack full corrections, recorded context, historical policy and signatures | References lack the complete evidence/history/export service | NOT_IMPLEMENTED; NARROWER_SCOPE |

The three recomputations are independent stdlib signed additions, independent SQLite integer-string parsing/UNION/SUM, and the unchanged production reconciliation engine with a test-owned save_run output adapter. The adapter prevents rich-result persistence in this common lane. The production engine still builds traces/evidence in memory; that internal overhead is included. This measures the restricted common task, not the full public application service.

Shared normalization/admission, deterministic generation and common persistence are intentional dependencies. Arithmetic references and closed-form oracle do not call the production financial calculation. The finite gate accepts only the declared generated schedules; its ability to reject a substituted reference is synthetic workload conformance, not a repair of count-only production manifests. **The prior12 false negatives remain unchanged.**

Equivalence checks require exactly three distinct successful methods per size/repetition, matching input path/hash/bytes, code bindings, SQLite settings, common result, input database bytes, result database bytes and JSON export bytes. Empty/omitted/duplicate/substituted populations, nonzero PASS, missing actual child exit, altered input/source binding and false COMPLETE are rejected. The consistency checker is not cryptographic timing attestation or an institutional trust anchor.

Protocol: [benchmark-gate2-protocol.json](../../contracts/benchmark-gate2-protocol.json). Inspectable figures: [benchmark-gate2-summary.json](../../evidence/gate2/benchmark-gate2-summary.json). Full source paths/checksums, original commands/stdout/stderr and retention inventories are bound there.

## Common-task measurements

| Events | Method | Completed n | Wall p50 s | Empirical p95 s | CPU p50 s | Throughput p50 events/s | Peak RSS p50 MiB | Logical DB+export p50 MiB |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
|100|stdlib_integer|5|0.245444|0.304031|0.079007|407.424882|15.375000|0.363558|
|100|sqlite_integer|5|0.261568|0.275893|0.076129|382.309852|15.750000|0.363558|
|100|production|5|0.271918|0.451904|0.083665|367.758103|15.625000|0.363558|
|1000|stdlib_integer|5|1.696121|1.767151|0.473324|589.580617|19.062500|1.347933|
|1000|sqlite_integer|5|1.759677|1.863284|0.491776|568.286083|19.062500|1.347933|
|1000|production|5|1.691206|2.248351|0.526567|591.293953|23.238281|1.347933|
|10000|stdlib_integer|5|14.235903|15.067140|4.386445|702.449278|52.023438|11.457308|
|10000|sqlite_integer|5|15.254905|19.396436|4.732588|655.526865|52.023438|11.457308|
|10000|production|5|15.332059|16.641628|5.131466|652.228098|94.570312|11.457308|

All five seeds were preregistered (11,29,47,71,97). Method order was seeded/interleaved and reversed on alternate repetitions. Fresh interpreters/databases were used without clearing OS page cache. These are not cold-disk measurements. At n5 the nearest-rank empirical p95 is the maximum, not a stable population-tail estimate. No completed outlier was removed or replaced.

## Paired effects, conditional uncertainty

| Events | Reference | Paired n | Production−reference median s | Exploratory95% bootstrap interval s | Median production/reference ratio | Exploratory95% ratio interval |
|---:|---|---:|---:|---|---:|---|
|100|stdlib_integer|5|0.026241|[-0.005422, 0.147873]|1.112749|[0.980449, 1.486375]|
|100|sqlite_integer|5|0.002092|[-0.010424, 0.190336]|1.008567|[0.961307, 1.727672]|
|1000|stdlib_integer|5|-0.010824|[-0.248182, 0.691910]|0.993875|[0.853677, 1.444546]|
|1000|sqlite_integer|5|-0.068471|[-0.415345, 0.505224]|0.961089|[0.777090, 1.289838]|
|10000|stdlib_integer|5|0.897949|[0.264919, 3.092514]|1.063076|[1.017583, 1.228245]|
|10000|sqlite_integer|5|-0.121052|[-4.064377, 2.928074]|0.992065|[0.790458, 1.213517]|

Intervals use2,000 seeded paired-block resamples of the five matched input/repetition groups. They are exploratory, conditional on this finite workload, host and cache policy, and unstable at this n. A common-task difference does not establish full-product, institution, SLA or monetary superiority.

## Generation and named phases

| Events | Distinct generated inputs | Generation wall p50 s | Generation CPU p50 s |
|---:|---:|---:|---:|
|100|5|0.002412|0.002397|
|1000|5|0.012254|0.012239|
|10000|5|0.123966|0.123947|

Each shared input was generated once per seed, outside child timing and explicitly measured above. It is not charged three times. The largest completed profile phase breakdown follows; every smaller-profile wall/CPU phase remains in raw metrics.

| Events | Method | Phase | Wall p50 s | CPU p50 s |
|---:|---|---|---:|---:|
|10000|stdlib_integer|read_input|0.029685|0.027819|
|10000|stdlib_integer|validate_common_contract|0.059016|0.057472|
|10000|stdlib_integer|initialize|0.029509|0.012525|
|10000|stdlib_integer|ingest|14.017546|4.169229|
|10000|stdlib_integer|recompute|0.096217|0.095630|
|10000|stdlib_integer|persist|0.002951|0.001176|
|10000|stdlib_integer|evidence_export|0.000074|0.000092|
|10000|stdlib_integer|reread_verify|0.002382|0.000748|
|10000|sqlite_integer|read_input|0.033732|0.031984|
|10000|sqlite_integer|validate_common_contract|0.062158|0.061053|
|10000|sqlite_integer|initialize|0.038407|0.013368|
|10000|sqlite_integer|ingest|14.894889|4.418518|
|10000|sqlite_integer|recompute|0.090808|0.090647|
|10000|sqlite_integer|persist|0.003476|0.001207|
|10000|sqlite_integer|evidence_export|0.000065|0.000090|
|10000|sqlite_integer|reread_verify|0.002470|0.001704|
|10000|production|read_input|0.062125|0.059712|
|10000|production|validate_common_contract|0.064642|0.064518|
|10000|production|initialize|0.032632|0.013500|
|10000|production|ingest|14.540808|4.423135|
|10000|production|recompute|0.647019|0.646636|
|10000|production|persist|0.003002|0.001336|
|10000|production|evidence_export|0.000182|0.000154|
|10000|production|reread_verify|0.002825|0.001255|

Child end-to-end time includes read/validation/initialization/ingestion/recompute/common persistence/export/close/reread and progress instrumentation. Parent subprocess wall additionally includes interpreter startup and artifact hashing. Phase medians need not sum to end-to-end medians. Peak RSS includes the whole child interpreter/runtime, not only arithmetic.

## Capacity triage and actual exits

The100,000-event target is attempted first with the original60-second end-to-end cap. Separate25,000/50,000 attempts then localize the observed completion boundary. The triage program has180 seconds total; any smaller remaining-budget cap is recorded. Each attempt is a single production-common-task observation, not a five-repeat comparison or a full-history benchmark.

| Events | Status | Actual POSIX exit | Effective cap s | Subprocess wall s | Last retained phase/state | Last committed receipt count |
|---:|---|---:|---:|---:|---|---:|
|100000|TIMEOUT|-9|60.0|60.06627988800028|ingest / RUNNING|34000|
|25000|PASS|0|60.0|34.95596076399988|reread_verify / COMPLETED|25017|
|50000|TIMEOUT|-9|60.0|60.063045402999705|ingest / RUNNING|40000|

For a new timeout, the controller kills the child if still running, then waits and records the actual POSIX returncode and original stdout/stderr. A recorded negative code is an observed signal termination, not an inferred substitute for historical null. Timeout is controller censoring, not an application LIMIT response. Partial progress does not establish successful recomputation/export/reread; no100k comparative latency is manufactured from an incomplete attempt.

## Resource costs and unmeasured quantities

common: elapsed **268.452s**, worker CPU **84.102s**, controller CPU **1.870s**. These are measured local resources including generation/warmup/control work; no price assumption or institutional savings model is attached.

triage: elapsed **158.970s**, worker CPU **49.048s**, controller CPU **3.872s**. These are measured local resources including generation/warmup/control work; no price assumption or institutional savings model is attached.

Each child had60 wall seconds,60 CPU seconds,1GiB address space and384MiB/file limits; one active child; owned benchmark disk budget1GiB. Common program budget420s and separate triage180s were preregistered. Logical sizes are measured, not physical write traffic. `/proc/self/io` counters (where readable) are process accounting on overlayfs, not independent physical-device observations or billing; actual physical-device IO and RAM-seconds remain unmeasured.

Host: Linux-6.18.57-x86_64-with-glibc2.41; Python 3.12.14 (main, Aug 25 2026, 14:00:49) [Clang 22.1.3 ]; SQLite 3.53.1. CPU affinity/cgroup limits and load observations are retained in evidence. Shared-host background interference cannot be excluded even with no other intentional validation job during the quiet window.

No claim is made for million-event scale, months-long soak, distributed exactly-once, power-loss safety, frozen ML improvement or institutional deployment. Original count-only substitution errors and missing real data are separate gates; arithmetic timings cannot resolve them.

## Reproduce offline

```sh
python -B -m validation_lab.benchmark_gate2 --mode full --output /path/to/new-common
python -B -m validation_lab.benchmark_gate2 --mode triage --output /path/to/new-triage
python -B -m validation_lab.benchmark_gate2_report --common /path/to/new-common/results.json --triage /path/to/new-triage/results.json --report /path/to/BASELINE_COMPARISON.md --summary /path/to/benchmark-gate2-summary.json
```

Run sequentially in a quiet window. Exit0 means COMPLETE and exit3 preserves PARTIAL. Reporting checks the caller-selected full/triage population against the reviewed current source bindings; copying or inventing a self-issued pin is not measurement authentication. New output directories are required. Retention inventories distinguish hashed-but-omitted large DB/export files from retained100-event artifacts and all original inputs/commands/metrics/progress.

## Measurement-boundary qualifications

The reported `program_cost` counters stop after post-trial aggregation, before final archive consistency revalidation and report rendering. The outer command records retain full process wall durations: common 269.297194 s (exit 0), triage 161.508347 s (exit 3). Rendering is a separate recorded command.

The phase named `evidence_export` writes the restricted common-result JSON; it is not full recorded-context, receipt-evidence or historical-policy export. Full evidence/history remains NOT_IMPLEMENTED for the references.

For the two timed-out attempts, final per-attempt CPU seconds, final peak RSS, final committed-row count and final database truth are **NOT_MEASURED**. Progress counters are periodic last-observed lower bounds after successful commits, not a post-kill database readback or RPO measurement. The recorded completed-phase times remain observations of those phases only. Whole-triage aggregate child CPU includes the killed workers but is not apportioned into invented per-attempt values. No recomputation/export/reread success is inferred from partial ingestion progress.

The retained-byte gate revalidated original input files and original command/stdout/stderr and metric records, rehashed/reread the retained100-event databases and exports, and recomputed summaries from actual completed trials. Larger omitted database/export bytes remain recorded hash observations; they were not independently reread after omission. This is evidence consistency, not external timing attestation.
