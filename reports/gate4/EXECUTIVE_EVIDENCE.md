# Gate 4 evidence and decision

**NO_CHANGE. The current WAL/FULL candidate is CANDIDATE_NOT_ACCEPTED.**
It is faster on the fixed synthetic comparison, but the unchanged financial
review exporter rejects even a checkpointed, cleanly closed WAL database. The
product remains 0.11.1 / stage2-v2 / schema 6, with its existing DELETE/FULL
default. All 445 accepted Gate 3 files remain byte-identical.

The separate five-file recorded execution export, context and bounded replay
pass equality checks. They must not be confused with the financial review
exporter that rejects WAL. Recorded read-only show also creates WAL/shm files;
an uncheckpointed main-file-only copy omits 30 acknowledged receipts. Online
SQLite backup and a quiescent complete sidecar copy preserve them.

The one-page [Turkish explanation](TURKCE_OZET.md) gives the result, uncertainty,
durability limits and exactly one proposed next step. Machine-readable decision
and limitations are in [DECISION.json](DECISION.json) and
[NOT_RUN.json](NOT_RUN.json). [Reproduction instructions](../../docs/validation/GATE4_REPRODUCE.md)
identify the finite protocols and fresh output requirements.

## Measured outcome

The descriptive continuation has seven matched equivalent pairs per profile,
using the exact original Gate 3 synthetic files and 17 auxiliary receipts each.
It measures full persisted work, startup, verification, canonical export,
checkpoint and reopen. The independent reader recomputed the following from
raw trials and directly inspected all 32 primary/control databases:

| Events | DELETE/FULL p50 | WAL/FULL p50 | Median paired reduction, 95% bootstrap | Median paired gain, 95% bootstrap |
|---:|---:|---:|---:|---:|
| 10,000 | 15.576 s | 6.369 s | 9.220 s [8.910, 9.805] | 59.5% [57.9%, 62.9%] |
| 25,000 | 39.989 s | 17.961 s | 22.811 s [21.311, 23.908] | 55.9% [54.7%, 57.8%] |

The fixed 15% median/greater-than-5% lower-bound speed threshold is met. It does
not override a failed compatibility invariant. [COMPARISON.md](COMPARISON.md)
contains individual-pair interpretation, CPU/RSS/disk, sample-maximum p95,
checkpoint and instrumentation controls. The controls add about 2.05% baseline
and 16.15% WAL wall time in one off/on pair per method; neither is a population
overhead estimate. Both methods retain FULL/2, foreign keys, append-only
constraints, one original transaction per receipt and post-COMMIT returns.

The original first warmup failed before DB creation because of inherited
address-space limits. Its **1 ERROR + 33 NOT_RUN** remains. A narrowly repaired,
separately preregistered continuation completed **34 PASS**; no primary timing
existed before the repair. The combined ledger has 68 attempt/cell observations
and 35 started workers. Original all-roster-PASS/no-retry is false. Total actual
outer wall 613.934 seconds, program CPU 331.277 seconds and sampled peak owned
disk 3.713 GiB remain within the original 1,800/900/6 GiB budgets.

## Acceptance evidence and independent rereads

| Component | Observed result | Evidence under `/workspace/validation-gate4-evidence` |
|---|---|---|
| Original archive/source | Fixed Gate 3 archive seal and all 445 original Git blobs verified | `intake-audit/`; [LINEAGE.md](LINEAGE.md) |
| Outside-engine input oracle | All ordered 10,017/25,017 receipts and integer-cent expected balances verified before timing | `independent/input-001/` |
| Semantics | 20 paired cases / 40 executions PASS | `semantics/run-001/`; [SEMANTICS.md](SEMANTICS.md) |
| Process interruption | 20 actual owned/reaped SIGKILL cells, every child exit −9; commit/ACK/retry behavior preserved | `crash/run-001/`; [DURABILITY.md](DURABILITY.md) |
| Auth, history, exports, replay, backups and migration | Positive/negative witnesses executed; financial review compatibility FAIL for WAL | `portability/run-002/`; [PORTABILITY.md](PORTABILITY.md) |
| Independent semantics/crash reader | 40 + 20 cells, 141 copied/recovered SQLite files, 636 input files; five rejection controls PASS | `independent-behavior/audit-001/`; [review](INDEPENDENT_BEHAVIOR_REVIEW.md) |
| Independent portability reader | 145 raw files, 87 source bindings, 24 tables per method; exact successful five-file output and WAL rejection confirmed | `semantics/portability-independent-reader/review-001/` |
| Independent benchmark reader | 34 metadata records, 32 primary/control SQL databases, 97 source bindings; raw statistics PASS | `independent/comparison-001/`; [INDEPENDENT_REVIEW.md](INDEPENDENT_REVIEW.md) |
| New research tests | Exact 50 identities PASS on Python 3.12.14 and 3.14.10; no failures, errors or skips; all 466 frozen source bindings unchanged | `tests-final-001/` and `commands/tests-final-001-py312`, `-py314` |

Actual commands, source snapshots, timestamps, subprocess exits and logs remain
with each component. Same-count event substitution and a falsified timing
summary produced two RED assertions against a declared weak negative control,
then two GREEN passes against the strict reader, using identical witness bytes.
The separate test-runner metadata repair retains its actual RED/GREEN evidence;
it rejects missing, duplicate and substituted success/completion identities.

The original 875 source/installed suites and 69/162/373 financial matrix are
**not rerun locally** for this research-only work. Their accepted historical
Gate 3 executions and preserved bytes are not new Gate 4 passes. A normal push
and draft PR may trigger the unchanged automatic workflow; its exact-head jobs,
artifacts and actual new execution scope are separately recorded outside this
source commit. Final evidence readiness additionally requires that CI observation
and the independent archive seal; no later CI/archive result is claimed here.

## Scope and delivery

SIGKILL establishes only the finite tested process-crash behavior. It does not
remove host power or establish device-cache, torn-write, other-filesystem,
RTO/RPO or deployment guarantees. This workload has no independently authorized
institutional counterparties or representative natural-error labels. Public
Treasury/SEC records remain separate from synthetic LAB inputs. Gate 1's twelve
count-only false negatives and all Gate 1/2/3 decisions/failures remain intact.

The final external delivery manifest binds the clean Git revision, draft PR,
exact-head CI observations, archive SHA-256/size/member count and independent
archive audit. The archive contains source, complete trial/command/economic
records and exact selected inputs. Ordinary database/sidecar files are omitted
with hashes; the small explicitly named precheckpoint portability `.bin`
witnesses are included. Account metadata, credential paths and reinstallable
trees follow the disclosed omission policy. The origin ledger distinguishes
included originals, hashed omitted originals and unexpanded sensitive/pruned
paths. No missing raw blob is described as reread from the ZIP.

No production WAL patch, merge, main push, release, PyPI upload, environment
publication or later gate is performed. The only recommended next step is a
separate design review of a WAL-compatible snapshot/export boundary before
considering a production patch.
