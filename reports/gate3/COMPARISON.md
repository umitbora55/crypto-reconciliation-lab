# Gate 3 independent comparison review

**The restricted common-task comparison is reproduced from all 45 original
completed measurements, across 15 matched blocks. Full-service throughput or
cost superiority remains unproven.** This audit computes statistics from retained
trial and metric records; it does not rerun or reinterpret Gate 2 timings as a
production improvement.

All observations in this report are **FULLY_SYNTHETIC**. Gate 1 and Gate 2 use
different persistence/output contracts. Their timing difference is not a
before/after optimization result. No production code changed for this review.

## Independent calculation and retained evidence

[`audit_gate3_comparison.py`](../../scripts/validation/audit_gate3_comparison.py)
imports only Python standard-library modules. It does not call either benchmark
implementation, production arithmetic, its normalization, or its report writer.
The caller selects the retained evidence directory; the script fixes the expected
100/1,000/10,000 event profiles, five seeds, 45 ordered trial identities and 15
input byte/hash pairs independently of the candidate result object. Each worker
has `events + 17` physical receipts; events and physical receipts are not
interchangeable throughput units.

The final successful audit is retained at
`comparison/audit-003/audit.json` under the Gate 3 evidence root. The earlier
successful audits remain in `audit-001` and `audit-002`; later iterations add
an exact historical source-name roster, retained Git command stdout and
explicit runtime-versus-later-commit time semantics. It verifies:

- All 45 actual zero exits, command arguments, original stdout/stderr, metrics,
  parent/child elapsed bounds, phase totals and throughput denominators.
- All 15 original input files against fixed byte counts and SHA-256 values;
  independent integer-cent receipt folding and exact `E0..E(n-1)` identities.
- All 94 historical source bindings against Git blobs at
  `6876b384030a7cdab1d35445f66bf874768dcfce`.
- Identical input, SQLite settings, projected arithmetic and artifact proofs
  across each of the 15 matched blocks.
- The retained input DB, common result DB and JSON export for every measured
  100-event trial: 117 receipts, 117 records, zero rich runs, and the same
  independently calculated financial projection.
- Every reported p50, empirical p95, resource summary, paired difference, ratio
  and declared 2,000-resample interval against the completed trial records.

The original measurement ran with Git HEAD
`f3dff8dd00837ac7ce6e9bb687dd4861f790cbac` and separately frozen working-source
bindings. Those exact source bytes were subsequently committed in `6876b384`.
The audit's `source_head` is explicitly a **POSTEXECUTION_COMMIT_BINDING**;
it is not a claim that the original timed processes ran after that commit.

The separate intake audit at `intake-audit/attempt-003/audit-result.json`
compares all 11,837 archived evidence files to their retained originals,
including these common-task inputs, command logs, metric files and result.
Thus the source corpus is also bound to the unchanged Gate 2 review ZIP;
the current comparison candidate did not choose replacement raw inputs.

The 1,000/10,000-event databases were intentionally omitted by the original
bounded retention policy after hashing; a new readback of those bytes is
**NOT_RUN**. Their recorded hashes are not a substitute for retained bytes.
Three warmups remain separate and excluded. This review adds no performance
observations and does not change the original sample sizes.

## Same common workload: all completed measurements

Each cell is the median of five completed trials, except empirical p95, which
is the observed maximum at n=5. RSS is the worker process peak, not isolated
arithmetic allocation. Disk is the logical input DB + result DB + JSON export
size, not physical-device traffic or a billing quantity.

| Events | Method | n | Wall p50 s | Empirical p95 s | CPU p50 s | Peak RSS p50 KiB | Logical disk p50 bytes |
|---:|---|---:|---:|---:|---:|---:|---:|
|100|stdlib integer|5|0.245444|0.304031|0.079007|15,744|381,218|
|100|SQLite integer|5|0.261568|0.275893|0.076129|16,128|381,218|
|100|production common projection|5|0.271918|0.451904|0.083665|16,000|381,218|
|1,000|stdlib integer|5|1.696121|1.767151|0.473324|19,520|1,413,410|
|1,000|SQLite integer|5|1.759677|1.863284|0.491776|19,520|1,413,410|
|1,000|production common projection|5|1.691206|2.248351|0.526567|23,796|1,413,410|
|10,000|stdlib integer|5|14.235903|15.067140|4.386445|53,272|12,013,858|
|10,000|SQLite integer|5|15.254905|19.396436|4.732588|53,272|12,013,858|
|10,000|production common projection|5|15.332059|16.641628|5.131466|96,840|12,013,858|

The finite methods share exact input bytes, production `Store.ingest`, per-row
commits, normalization/admission and common persistence. The production engine
still builds its internal traces/evidence in memory. Its test-owned
`CommonStore.save_run` adapter returns the result without rich persistence;
each method then saves the same common SQLite result and JSON export. These
differences explain why this is a restricted service comparison.

## Matched effects and uncertainty

Pairs use the same event count, repetition, seed and input SHA. Method order is
the original seeded permutation on even repetitions and reverse of the prior
order on odd repetitions. The machine-readable roster retains every original
position and original command/metric file proof. Fresh interpreters/databases
were used without an OS page-cache flush; the measurements are not cold-disk
latencies. Shared-host interference remains possible.

| Events | Reference | Paired n | Median production−reference s | Exploratory 95% bootstrap interval s | Median production/reference |
|---:|---|---:|---:|---|---:|
|100|stdlib|5|0.026241|[−0.005422, 0.147873]|1.112749|
|100|SQLite|5|0.002092|[−0.010424, 0.190336]|1.008567|
|1,000|stdlib|5|−0.010824|[−0.248182, 0.691910]|0.993875|
|1,000|SQLite|5|−0.068471|[−0.415345, 0.505224]|0.961089|
|10,000|stdlib|5|0.897949|[0.264919, 3.092514]|1.063076|
|10,000|SQLite|5|−0.121052|[−4.064377, 2.928074]|0.992065|

These are medians of paired effects, not differences of unpaired medians.
Intervals reproduce the declared 2,000 paired-block resamples, seed 9281.
They describe only this finite host/workload/cache-policy observation and are
unstable with five blocks. The empirical p95 is not a reliable population-tail
estimate. In particular, the 10,000-event record does not show a general
production advantage.

## Why a full-service comparator is unavailable

| Required service | Restricted references actually implement | Missing evidence for equivalent service |
|---|---|---|
|Accounting|Single-asset static deposit/transfer/withdrawal cycle and exact balance projection|General supported financial scope and invalid/incomplete states|
|Temporal eligibility|One authored economic/knowledge cut|Multiple cuts, late receipts, historical eligibility/policy selection|
|Receipt evidence|Same physical Store ingestion and input DB|Equivalent end-to-end lineage across revision/correction histories|
|Corrections|No revisions or corrections in finite input|Replacement/effect/ordering and contradictory-delivery semantics|
|Saved results|One common projection row and JSON bytes|Rich run, ledger, findings, trace, correction groups/effects persistence|
|Audit/capture context|Common output reread|Recorded execution identity, immutable captured input context, original acceptance epochs, authority/capture linkage|
|Source authenticity|Authored count manifests for generated schedules|Independent trust roots, source signatures, policy/key lifecycle|
|Offline replay|Not exercised|Two-file replay validation, externally expected execution identity, eligible-receipt limits, isolated computation and complete comparison|

Implementing these absent services would create a substantial reference system
and require its own independent correctness validation. No dummy baseline was
created within this bounded investigation.
**FULL_EVIDENCE_HISTORY_SUPERIORITY = INCONCLUSIVE;
COMPARATOR_NOT_AVAILABLE.**

The original common program observed 268.451592 wall seconds, 84.101737 worker
CPU seconds and 1.869570 controller CPU seconds, including generation, warmup
and control work. No comparable provider price, institutional infrastructure
or operating-cost basis was supplied. **COST_SAVINGS = NOT_PROVEN.** RAM-seconds
and physical-device IO remain unmeasured. This report invents no monetary cost,
RTO, RPO or institutional deployment claim.

## Reproduction and limits

```sh
python -B scripts/validation/audit_gate3_comparison.py \
  --evidence-root /path/to/original/common-full \
  --source-root /path/to/repository \
  --output /path/to/new-comparison-audit
```

Original command/input paths are part of the captured evidence and are checked
exactly. Use the documented original layout or restore it in an isolated
workspace; do not silently rewrite captured paths to make copied records pass.
The referenced historical Git commit must be present. A missing raw input
fails the audit, and a missing original DB stays **NOT_RUN**.

The audit shares the immutable observation bytes, standard-library runtime and
declared randomization/bootstrap protocol with the original experiment. Its
parsing, receipt fold, inventory and summary calculations are separate. The
same standard-library bootstrap algorithm is a reproducibility check, not an
independent statistical model. Self-consistent logs/hashes are not external
timing attestation, real-world authenticity or an institutional trust root.
