# Gate 4 independent evidence review

Gate 4 retains the accepted Gate 3 source and historical decisions. This reader
imports only the Python standard library. It does not call an application or
benchmark parser, normalization function, arithmetic oracle, projection helper,
or statistics helper. Its scope is consistency of retained evidence, not a
trusted timing attestation or institutional financial truth.

## Before measurement

The independent input audit passed before the first worker launch. Its exact
executed source, original scope contract, actual command, exit 0, stdout/stderr,
and output are retained in `independent/input-001/`. Later reader extensions do
not stand in for that earlier source snapshot.

The fixed historical input byte pins are:

| Events | Seed | Bytes | SHA-256 |
|---:|---:|---:|---|
| 10,000 | 11 | 4,596,911 | `c246c488a9845ad11e9628fd647cb1fb826ec6bc797bd3684781f247801926c2` |
| 25,000 | 29 | 11,516,911 | `8f8902a3e4970478da5d397d2141f7d534d2e097751d727578af38bbfb556a3f` |

For both profiles every ordered raw row is checked: event references `E0` through
`E(n-1)`, six openings, six reports and five manifests. There are **10,017 and
25,017 physical receipts**, not 10,000 and 25,000. Independently encoded receipt
IDs, normalized record IDs and logical keys are retained for every row. Integer
cents parsed directly from decimal characters establish final investor I1
balances of 10,045 and 10,022 cents, respectively; the other three investors each
hold 10,000 cents, platform custody is zero, external custody/customer liability
is 40,045 or 40,022 cents. All five expected findings are MATCHED. These are fixed
synthetic expectations, not externally authenticated institutional balances.

## Original failure and explicit continuation

The original 34-cell program did **not** satisfy its no-retry/all-cells-PASS
criterion. Its first warmup exited 1 before database creation: the controller's
inherited 1 GiB hard address-space limit prevented the worker from requesting
1.5 GiB. The original ledger remains **1 ERROR plus 33 NOT_RUN**. It contains no
10,000/25,000-event timing result.

A separately pinned continuation preserves the same inputs, 28 primary cells,
seven pair repetitions, order, thresholds, and trial limits. It reserves the
first attempt's wall/CPU expenditure within the original 1,800-second wall,
900-second CPU and 6 GiB owned-disk caps. The effective controller soft bound
remains 1 GiB; only the inherited ceiling and spawn/signal ownership harness were
repaired. The additional warmup attempt is an explicit protocol deviation,
not an original successful trial or a primary trial selected by speed. Combined
rosters use `(attempt, cell ID)`; the original ERROR/NOT_RUN observations cannot
be replaced by continuation PASS observations.

The continuation completed **34 PASS observations**, including 28 primary
measurements. Independent reread `independent/comparison-001/audit-result.json`
passed (actual exit 0; 132.215 seconds wall / 131.700 seconds CPU). It reread all
34 raw metric/command populations, 97 source files, and 32 full primary/control
databases containing **530,544 physical receipts**. The two warmups received
hash/metric review; they were excluded from the two registered input financial
oracles and primary statistics. All 14 primary pairs retained exact logical
results, receipt order, evidence links, run IDs and canonical exports.

Successful continuation timing cannot make the original program satisfy its
failed criterion, nor accept the current WAL candidate. The combined population
is **68 scheduled attempt observations: 34 PASS, 1 ERROR and 33 NOT_RUN**; 35
workers actually started, of which 28 were primary timed workers.

| Synthetic events | DELETE/FULL parent median (s) | WAL/FULL parent median (s) | Median paired saving (s), bootstrap 95% | Median paired gain, bootstrap 95% |
|---:|---:|---:|---:|---:|
| 10,000 | 15.575882 | 6.369255 | 9.220241 [8.909526, 9.805084] | 59.5116% [57.9364%, 62.8603%] |
| 25,000 | 39.988716 | 17.961398 | 22.811378 [21.311328, 23.907902] | 55.9476% [54.6965%, 57.7565%] |

These are independently recalculated from actual retained parent durations,
not copied from the reported summary. The difference of the two marginal medians
is 9.206627 / 22.027318 seconds; it is a different statistic from the median
paired saving shown above. Both continuation profiles exceed the fixed numerical
speed threshold. Nearest-rank p95 is the observed maximum: DELETE/WAL 17.276011 /
6.767473 seconds at 10k and 43.710087 / 19.802186 seconds at 25k.

The separate `independent/control-supplement-001/` audit also passed. It verifies
four raw control metric files and **40,080** actual CSV transaction boundaries
against the recorded count and duration buckets. At 10k, Recorder-on minus
Recorder-off parent elapsed was +0.336850 seconds (+2.0461%) for DELETE/FULL and
+1.014187 seconds (+16.1509%) for WAL/FULL. Each is **one off/on pair**, not a
stable overhead estimate or evidence for correcting primary durations. Both
primary methods use the same common diagnostics and their primary measurements
have the extra Recorder disabled.

## Independent reread requirements

The reader binds the exact external protocol hashes, full 34-cell order, 28
primary identities, fresh source snapshot, worker import origins, actual
commands, exits, stdout/stderr and raw metric files. It checks actual SQL table
content hashes and schema objects; every physical receipt and normalized record;
complete persisted run, finding and evidence tables; every receipt/evidence link;
run content IDs; exact canonical exports; reopen/integrity observations and
FULL2/FK1 settings. Both methods must agree on complete logical content across
all pairs. WAL, shared-memory and checkpoint observations remain explicit.

Statistics come from retained parent wall durations. The primary endpoint
includes interpreter startup, unchanged full persistence and export, receipt
checks, two full logical scans, explicit final checkpoint, close/reopen and
process completion. It is not interchangeable with Gate 3's narrower wall
measurement. Run persistence is nested inside reconciliation; phase times are
not summed as disjoint buckets. Instrumented COMMIT time can include SQLite
implicit checkpoints. Kernel counters and sampled logical bytes do not establish
physical storage writes or physical-media fsync completion.

The fixed statistic uses seven paired differences and gains
`(baseline - candidate) / baseline`. The reader independently recalculates
medians, 10,000 bootstrap draws with seed 424271 (sorted indices 250/9749), and
nearest-rank p95, which at n=7 is the **observed maximum**. Material gain requires
median gain at least 15% and the bootstrap lower gain strictly above 5%, in both
profiles. This is a descriptive threshold, not a production or institutional SLA.

## Same-witness adversarial evidence

Two immutable attacks were executed against an explicitly weak count-only
negative control and the strict independent reader:

- Replace event `E0` with a different identity without changing row count.
- Falsify the reported benchmark median without changing the raw trial count.

The weak control produced **RED: 2 assertion failures, exit 1**; the strict reader
produced **GREEN: 2 passes, exit 0**. Exact witness bytes, both targets, commands,
PIDs/waits and stdout/stderr are retained in `independent/adversarial/`. The same
two attacks also passed against the final frozen reader source in
`green-final-source/`. This is a
controlled verifier experiment; the weak control is not labelled a historical
product version. The historical twelve count-only false negatives remain
unchanged. LAB signatures remain LAB authority, not institution authority.

Empty, duplicate, reordered or substituted PASS populations are rejected.
Independent final test-manifest review passed for **50 new research tests on
Python 3.12 and 50 on Python 3.14**, with 466 source-file bindings including all
445 immutable historical Git blobs. Static test identities come from the actual
test directory, independently of the supplied manifest. Expected, discovered,
started, successful and completed identity populations exactly match; actual
unittest stderr confirms each success and all five nonpass counters are integer
zero. Inventory SHA-256 is
`325d09b45643eaca349a807e234bb3e77edcc3065884f0632acd002ab354b256`.

The independent reader also rejected seven altered copies of those actual PASS
artifacts: empty identities, duplicate identity, substituted identity, omission
of an entire test file with consistently reduced logs/counts, floating-point
inventory count, floating-point executed count and boolean zero failure counter.
Original artifacts remain unchanged. Commands, actual exit 0, log/hash bindings
and rejection reasons are in `independent/test-manifests-001/`.

These are **NEW_GATE4_RESEARCH_ONLY** results; the historical 875 source/installed
tests and 373 financial reference files are not relabelled as rerun. Their
accepted Gate 3 evidence remains historical. Two earlier ten-test development
checks retain their actual exit/log observations in
`independent/DEVELOPMENT_OBSERVATIONS.json`; their intermediate full source was
not sealed, so they are excluded from final gate claims.

## Acceptance boundary

The current candidate remains **CANDIDATE_NOT_ACCEPTED / NO_CHANGE**. The existing financial review exporter (`review.adapter`) rejects the closed
WAL database header and WAL sidecars; this compatibility failure and the original
protocol failure prevent acceptance independently of timing. The separate
five-file recorded execution export passed byte parity (`context.json`, `run.json`,
`execution.json`, `summary.json`, `summary.md`). Recorded read/show also returns
the same result, but opening the closed WAL database creates a zero-byte WAL
and 32,768-byte shared-memory sidecar; result parity does not imply unchanged
read-side filesystem behavior. SIGKILL recovery can
establish process-crash behavior at tested transaction boundaries; it does not
establish power-loss or filesystem-failure durability. Missing institutional
counterparty records and natural error labels remain missing.
