# Baseline comparison

**Measured program: PARTIAL. 45 completed timed trials passed their independent output check, from 46 total timed attempts; 3 warmups are excluded from timing summaries.**

**COMPARATIVE_SPEED_ADVANTAGE = INCONCLUSIVE.** Both references are `NARROWER_SCOPE`. They are alternatives for a finite common arithmetic task, not equivalent implementations of the complete application. All workloads are `FULLY_SYNTHETIC`; no bank, custodian, CSD or public-source transaction workload was measured. Runtime differences cannot establish institutional savings or risk reduction.

The preregistered contract is [benchmark-protocol-v1.json](../contracts/benchmark-protocol-v1.json). The inspectable compact figures and full-result checksum are in [benchmark-summary.json](../evidence/benchmark-summary.json). Original commands, exit codes, stdout/stderr, input hashes, phase measurements and artifact retention inventories remain in the external canonical evidence directory recorded there.

## Workload and equivalence boundary

Each profile uses four investors, one asset, integer cents, one static economic/knowledge cut and complete count manifests. Repeated deposit → transfer → withdrawal triples cancel. The final one/two-event suffix gives a closed-form independent expected balance. All three methods read the same bytes for each matched repetition. The profiles use five predetermined seeds: 11,29,47,71,97.

| Property | Integer stdlib / SQLite references | Production application | Parity |
|---|---|---|---|
| Input rows, cut, amounts and selected manifest counts | Same bytes; strict finite-domain checks | Same bytes through public Store.ingest | Within declared profiles |
| Computed balances, liability, custody and findings | Python signed additions / SQLite INTEGER UNION-SUM | Decimal production engine projected into integer cents | Checked against independent analytic oracle for every completed trial |
| Transactions | One SQLite transaction per input row; small result table | Public transaction-owned ingestion and result persistence | Both durable local transactions, different schemas and work |
| Validation, intermediate states, corrections and report versions | Narrow validators; SQL baseline has no general intermediate-negative-state engine | Full application semantics and historical behavior | NARROWER_SCOPE |
| Persisted/exported result | Common balances and findings only | Full ledger traces, receipt evidence and result payload | NARROWER_SCOPE |
| Independence | Different Python and SQL arithmetic, shared reference input parser/persistence | No production helper in either reference or closed-form oracle | Shared reference parser is an explicit dependency |

## Observed local execution

Wall time is child work from input read through verification. It includes fresh database initialization, ingestion, reconciliation, result persistence, export and instrumentation. Interpreter startup and child artifact hashing are additionally available as subprocess wall times. Production reconciliation time is split using a test-owned Store subclass around the unmodified save_run method; its inclusive duration must not be added again to the exclusive compute/persist durations.

| Events | Method | Completed repeats | Wall p50 s | Empirical p95 s | Throughput p50 events/s | CPU p50 s | Peak RSS p50 MiB | DB + export p50 MiB | Export bytes p50 |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | stdlib_integer | 5 | 0.168534 | 0.176250 | 593.350629 | 0.042765 | 14.585938 | 0.047275 | 419 |
| 100 | sqlite_integer | 5 | 0.149411 | 0.164217 | 669.294294 | 0.038965 | 14.585938 | 0.047275 | 419 |
| 100 | production | 5 | 0.260669 | 0.308583 | 383.627938 | 0.098421 | 17.328125 | 1.059875 | 288064 |
| 1000 | stdlib_integer | 5 | 1.610432 | 2.040108 | 620.951489 | 0.397979 | 18.312500 | 0.316806 | 419 |
| 1000 | sqlite_integer | 5 | 1.245237 | 1.360007 | 803.059753 | 0.354586 | 18.312500 | 0.316806 | 419 |
| 1000 | production | 5 | 2.177266 | 2.536581 | 459.291712 | 0.810720 | 38.582031 | 7.675447 | 2641569 |
| 10000 | stdlib_integer | 5 | 13.567914 | 17.576037 | 737.032954 | 3.256402 | 50.316406 | 3.031650 | 419 |
| 10000 | sqlite_integer | 5 | 12.854782 | 14.409393 | 777.920597 | 2.934575 | 50.316406 | 3.031650 | 419 |
| 10000 | production | 5 | 21.035740 | 25.000893 | 475.381417 | 8.046392 | 223.476562 | 74.437294 | 26230579 |
| 100000 | stdlib_integer | 0 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| 100000 | sqlite_integer | 0 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| 100000 | production | 0 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |

The p95 column is the nearest-rank empirical percentile. With five repeats it is the observed maximum, not a reliable population-tail estimate. Peak RSS is Linux child ru_maxrss including interpreter/runtime; file sizes are logical bytes, not physical disk IO. Fresh interpreters/databases were used but the OS page cache was not cleared; these are not cold-disk measurements.

## Paired differences and uncertainty

| Events | Reference | Paired n | Production − reference median s | Exploratory bootstrap 95% interval s | Production/reference median ratio | Exploratory bootstrap 95% ratio interval |
|---:|---|---:|---:|---|---:|---|
| 100 | stdlib_integer | 5 | 0.089424 | [0.072682, 0.143315] | 1.522197 | [1.431258, 1.867172] |
| 100 | sqlite_integer | 5 | 0.114405 | [0.091805, 0.150646] | 1.804415 | [1.614446, 2.245729] |
| 1000 | stdlib_integer | 5 | 0.496473 | [0.370380, 0.941442] | 1.243356 | [1.224836, 1.739397] |
| 1000 | sqlite_integer | 5 | 0.861567 | [0.620805, 1.291344] | 1.654836 | [1.456472, 2.037026] |
| 10000 | stdlib_integer | 5 | 7.467826 | [3.822591, 12.409343] | 1.550403 | [1.263600, 1.985529] |
| 10000 | sqlite_integer | 5 | 9.312557 | [6.626347, 12.146111] | 1.724342 | [1.459863, 1.944871] |
| 100000 | stdlib_integer | 0 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| 100000 | sqlite_integer | 0 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |

Intervals use 2,000 seeded paired-block bootstrap resamples of the five matched workload/repetition groups. They are exploratory, conditional on this machine and generated population, and unstable at this n. Method order was seeded-random and reversed in alternate blocks. No completed outlier was removed or replaced. These ratios describe observed work with unequal evidence/persistence scope and must not be presented as equivalent-product speed superiority.

## Phase observations

| Events | Method | Read p50 s | Initialize p50 s | Ingest p50 s | Reconcile exclusive p50 s | Persist p50 s | Export p50 s | Verification p50 s |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 100 | stdlib_integer | 0.000537 | 0.004153 | 0.156729 | 0.001437 | 0.001372 | 0.000307 | 0.000227 |
| 100 | sqlite_integer | 0.000472 | 0.003435 | 0.137506 | 0.000669 | 0.001525 | 0.000275 | 0.000247 |
| 100 | production | 0.000539 | 0.038217 | 0.200104 | 0.005025 | 0.009315 | 0.009483 | 0.000232 |
| 1000 | stdlib_integer | 0.002944 | 0.004749 | 1.580571 | 0.010127 | 0.001764 | 0.000578 | 0.000473 |
| 1000 | sqlite_integer | 0.003044 | 0.003606 | 1.227919 | 0.002075 | 0.001324 | 0.000362 | 0.000399 |
| 1000 | production | 0.003048 | 0.043399 | 1.886094 | 0.036929 | 0.065482 | 0.085331 | 0.001042 |
| 10000 | stdlib_integer | 0.034719 | 0.004247 | 13.369744 | 0.086879 | 0.002378 | 0.000509 | 0.001874 |
| 10000 | sqlite_integer | 0.026471 | 0.004495 | 12.714915 | 0.023625 | 0.001370 | 0.000339 | 0.002169 |
| 10000 | production | 0.029654 | 0.038196 | 18.774518 | 0.652389 | 0.844652 | 0.818568 | 0.002733 |

Observed host: AMD EPYC 9V74 80-Core Processor; 33.289 GiB visible RAM; overlayfs filesystem; physical disk model NOT_OBSERVABLE. CPU affinity and cgroup limits are retained in compact evidence. Python: 3.12.14 (main, Aug 25 2026, 14:00:49) [Clang 22.1.3 ]; SQLite: 3.53.1.

Phase medians need not sum to the median end-to-end time. Reference narrow validation, production import/projection, close and progress-log writes are additional measured work. Common arithmetic parity does not make these phase costs identical tasks.

## Finite capacity and resource cost

The whole measured program used **334.824 elapsed seconds**, **104.393 worker CPU seconds** and **3.453 controller CPU seconds** including warmups, input generation, hashing, cleanup and statistics. Post-process logical disk observations reached **117.034 MiB**; this is a sampled post-process maximum, not a continuously observed disk peak. Retained bytes before final summaries: **78332840**.

Single workers were bounded to 60 wall seconds, 60 CPU seconds, 1 GiB address space and 384 MiB per file; the program budget was 360 seconds with one worker. The benchmark owned-disk budget was 1 GiB. Physical IO, RAM-seconds and monetary cost were not measured/estimated. No provider price or institutional cost assumption is attached.

| Events | Repeat | Method | Observed status | Reason / exit |
|---:|---:|---|---|---|
| 100000 | 0 | production | TIMEOUT | Controller deadline expired (subprocess.TimeoutExpired); POSIX exit status not captured |
| 100000 | 0 | ALL | NOT_RUN | remaining profile repetitions stopped after recorded failure/timeout |

A timeout/resource-limited trial is censored and retained, not a successful low-latency observation. The affected profile is partial; uncompleted repeats cannot support a five-pair claim. Every completed trial recorded its actual exit 0. For the TimeoutExpired case the controller retained elapsed time and progress but did not capture the final POSIX child exit status; null denotes that evidence limitation and must not be relabeled as an observed -9 or other exit.

For 100000 events / production, the last retained progress record was **ingest / STARTED**. The timeout was imposed by the experimental controller; it is not evidence of an application-level LIMIT response or successful completion of later phases.

This benchmark uses ordinary ingestion/reconciliation/export, not recorded-context export or offline replay. No result above 10,000 events is evidence that replay's eligible-receipt, captured-row, byte or timeout bounds were raised. One million events, months-long soak, macOS, distributed exactly-once and institutional transaction ground truth were NOT_RUN.

## Reproduce

Run from the repository root in the prepared Python environment, with a new output directory and a quiet local worker window:

```sh
python -B -m validation_lab.benchmark --mode full --output /path/to/new-benchmark
python -B -m validation_lab.benchmark_report --input /path/to/new-benchmark/results.json --report /path/to/BASELINE_COMPARISON.md --summary /path/to/benchmark-summary.json
```

`--mode smoke` limits the profiles to 100 events while retaining five repetitions. Both modes are offline. Exit 0 means COMPLETE; exit 3 means explicitly PARTIAL. Preserve the typed JSON status rather than converting any generated report into PASS. Large databases/exports are omitted after hashes/sizes are recorded; all input JSON, per-trial metrics, commands and retention inventories are kept. Non-warmup 100-event DBs/exports are retained.

## Harness review

Independent review found that the first draft accepted declared event counts inconsistent with actual rows, accepted an empty profile list, and returned exit 0 for PARTIAL. These were repaired before timing. The retained 112-actual/100-declared/seed-79 witness changed from PASS to explicit rejection; regressions also cover empty/duplicate profiles and PARTIAL → exit 3. This is a repaired validation-harness defect, not a production financial defect. Ten final preflight tests passed; raw RED/GREEN evidence is retained under the external audit and benchmark/preflight directories.
