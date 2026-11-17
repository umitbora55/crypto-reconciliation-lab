# Gate 4: transaction cost under unchanged receipt commits

This is a research harness around the unchanged `Store`, reconciliation, run
persistence and full canonical JSON result export. The baseline observes SQLite
DELETE/FULL (`synchronous=2`); the candidate requests WAL/FULL in owned databases.
Every receipt still has one transaction and returns only after COMMIT. Foreign
keys, append-only triggers, schema 6 and product defaults are unchanged.

The fixed synthetic inputs are the original Gate 3 10,000-event/seed-11 and
25,000-event/seed-29 files, each with 17 auxiliary receipts. They are not Treasury
or SEC data. An independent standard-library input reader verified every event,
ordered receipt identity and integer-cent balance before the first timed worker.
The two input SHA-256 values are pinned in the original benchmark protocol.
The measured interpreter was Python 3.12.14 with SQLite 3.53.1 on Linux 6.18.57,
overlayfs and CPU affinity 0–4. Initial load averages were
0.0088/0.0347/0.0151; every trial retains before/after load observations.
Every completed benchmark child and reopen observed FULL=2, foreign_keys=1, schema=6, page_size=4096
and wal_autocheckpoint=1000, with its declared DELETE or WAL journal mode.

The primary endpoint is complete child wall time observed by the controller:
startup, input validation, ingestion, full saved run/evidence, canonical export,
ordered receipt and logical-table verification, explicit final checkpoint,
close, reopen and complete persisted readback. Both methods do the same work.
The logical equivalence gate compares all tables and schema objects, ordered
receipt identities, financial projection, run ID, selected evidence and exact
canonical export. Physical DELETE/WAL database bytes are intentionally not an
equality criterion.

There are seven fixed matched pairs at each profile, with alternating method
order and reversed order between profiles. Fresh databases are used throughout.
The preregistered threshold is at least 15% median paired wall-time gain at both
profiles and a 95% paired-bootstrap lower bound greater than 5%, with all seven
pairs complete and equivalent. Bootstrap uses 10,000 resamples, seed 424271,
indices 250/9749. Empirical p95 at n=7 is the sample maximum. No trial is excluded
because of load, no missing primary pair is refilled and no threshold is tuned.

## Retained bootstrap failure and separate continuation

The original sealed `run-001` first warmup exited **1** before any database or
performance result existed: a controller hard address-space limit of 1 GiB was
inherited by a child trying to set its preregistered 1.5 GiB ceiling. The controller
owned and waited for that child. Its ledger remains **1 ERROR + 33 NOT_RUN**;
all 28 primary comparison cells were unattempted. Exact failed source, command,
stderr, exit and source snapshot remain available.

The separately sealed continuation keeps the controller effective soft limit at
1 GiB and permits the child's fixed 1.5 GiB ceiling through an inherited hard
limit of 1.5 GiB. ALRM/INT/TERM are masked across process creation and assignment;
the child unblocks them after exec. Meaningful small tests cover real isolated
worker startup and all three injected handoff signals, with owned child kill and
wait. No production behavior changes.

The original protocol is immutable. The continuation uses the same input bytes,
34-cell roster, pair order, threshold and bootstrap method. It has 1,799 seconds
wall and 899 CPU seconds, reserving one second of each for the original attempt
inside the original 1,800/900 limits. The 6 GiB logical disk cap counts the whole
owned benchmark tree, including the failed attempt. The warmup retry is an
explicit additional attempt; the original program is never described as 34/34
PASS. Continuation statistics do not remove that protocol deviation.

## Executed continuation comparison

All 28 primary trials completed, forming seven exact logical/evidence-equivalent
pairs at each profile. The continuation has 34 PASS observations; together with
run-001 there are 68 attempt/cell observations and 35 actually started workers,
including the original failed warmup. The original protocol deviation remains.

| Events | Baseline p50 s | WAL/FULL p50 s | Median paired reduction s (95% bootstrap) | Median paired gain (95% bootstrap) | Empirical p95 baseline / WAL s |
|---:|---:|---:|---:|---:|---:|
| 10,000 | 15.576 | 6.369 | 9.220 [8.910, 9.805] | 59.5% [57.9%, 62.9%] | 17.276 / 6.767 |
| 25,000 | 39.989 | 17.961 | 22.811 [21.311, 23.908] | 55.9% [54.7%, 57.8%] | 43.710 / 19.802 |

The continuation meets the fixed descriptive speed threshold at both profiles.
That is not global protocol acceptance: the original warmup failed, the existing
financial review exporter rejects WAL, and read-only show creates WAL sidecars.
**Overall NO_CHANGE.**

| Events | Method | CPU p50 s | Peak sampled RSS MiB | Initial / checkpoint / reopen p50 s | DB+sidecars before / after checkpoint MiB |
|---:|---|---:|---:|---:|---:|
| 10,000 | BASELINE | 6.909 | 271.6 | 0.0276 / 0.000053 / 0.0016 | 49.438 / 49.438 |
| 10,000 | CANDIDATE_WAL_FULL | 4.212 | 272.0 | 0.0288 / 0.001782 / 0.0015 | 88.728 / 49.531 |
| 25,000 | BASELINE | 17.698 | 612.9 | 0.0285 / 0.000042 / 0.0018 | 123.402 / 123.402 |
| 25,000 | CANDIDATE_WAL_FULL | 11.733 | 615.4 | 0.0314 / 0.004195 / 0.0016 | 221.166 / 123.621 |

Before/after checkpoint sizes include database, WAL, shm and journal. Final
artifacts also include the full export, ordered receipt log and logical-table
snapshot. All paths count toward the cumulative owned-disk guard. Readback and
integrity work is included in the primary endpoint but separate in phase data.
The controller's polled worker-start marker gives an upper bound, not exact
interpreter startup: median 0.205/0.106 s at 10k and 0.206/0.111 s at 25k
(baseline/WAL), with 0.1 s polling. Startup is included in every primary duration.

| Instrumentation control (n=1 pair each) | Off parent s | On parent s | Incremental s / relative |
|---|---:|---:|---:|
| BASELINE | 16.463 | 16.800 | +0.337 / +2.05% |
| CANDIDATE_WAL_FULL | 6.279 | 7.294 | +1.014 / +16.15% |

The controls have exact logical/result/export parity. These single-pair overhead
observations include order and host noise; they are not population estimates.

| Instrumented 10k control | Ingest s | Ingest COMMIT calls | COMMIT inclusive s | COMMIT share of ingest |
|---|---:|---:|---:|---:|
| BASELINE | 13.190 | 10,017 | 10.853 | 82.3% |
| CANDIDATE_WAL_FULL | 4.100 | 10,017 | 2.685 | 65.5% |

Cumulative actual outer wall is **613.934 s**,
program CPU **331.277 s** and peak sampled
owned disk **3.713 GiB**, within the
original 1,800 s / 900 CPU s / 6 GiB caps. There was one worker at a time.
Raw command/exit/source/import/PRAGMA/resource evidence, every trial duration
and the complete combined roster are retained under
`/workspace/validation-gate4-evidence/benchmark/`. The independent re-reader
checks those raw artifacts and recomputes statistics separately.

## Attribution and limits

Instrumentation controls are one separate off/on 10k pair per method, excluded
from the seven primary pairs. Their differences measure incremental observer
cost in the recorded order; they cannot establish a reliable population overhead.
Off trials retain common phase clocks, progress, receipt identity checks and
readback. Instrumented COMMIT execution time includes implicit SQLite
checkpoint work when triggered. Default `wal_autocheckpoint` is observed rather
than disabled. The explicit final checkpoint and close/reopen costs are timed
for both methods. Nested run-persistence time is already included in
reconciliation; inclusive buckets must not be summed.

Database, WAL, shm and journal logical sizes are observed before/after checkpoint
and sampled by the controller. Kernel process I/O counters on overlayfs do not
identify physical-device latency, fsync implementation, write amplification or
billing. Whole-child RSS is distinct from sampled RSS and from isolated
allocation. SIGKILL tests establish only their stated process-interruption
behavior, never abrupt power-loss durability, RPO or RTO.

These fuller Gate 4 checks add work to the Gate 3 timing definition, so Gate 3's
historic 25k 38.706 s under 60 s, 50k/100k timeouts and restricted extended
65.443/128.971 s remain unchanged and are not replaced by this comparison.

**Performance gain alone cannot accept the candidate.** The existing financial
review exporter rejects the WAL database header and live sidecars; even after
checkpoint/close the WAL header remains incompatible. Existing read-only show
returns the same result but creates WAL/shm sidecars, so its file non-mutation
invariant fails. Five-file recorded export and context/replay passed parity;
their successful witnesses remain separate from the financial review failure.
The tested candidate therefore remains **CANDIDATE_NOT_ACCEPTED** and the overall
research decision is **NO_CHANGE**. The full compatibility witnesses and exact
errors are in the separate portability evidence. No product setting is shipped.
Independent authenticated two-party institutional data and natural-error labels
remain unavailable; institutional superiority, savings, risk reduction and
compliance remain unproved.
