# Process recovery experiment

Run from a clean source checkout or an installed 0.7.0 wheel, using a new directory:

```sh
python3 -m crypto_reconciliation_lab demo-recovery --output recovery-output-new --seed 19
```

The command writes `schedule.json` before admitting any source, then
`delivery-summary.json`, `report.md`, bounded per-case process/readback logs and
task-owned databases. The schedule binds all original and deliberately changed
input bytes. Databases are experiment outputs, not distribution/review ZIP members.
The command refuses an existing output directory. The fixed scenario roster is
also pinned separately in `contracts/admission-recovery-scope-v1.json` for release
verification; empty, partial or skipped evidence cannot satisfy that gate.

| Required behavior | Explicit case IDs |
|---|---|
| Complete files, including expected financial mismatch | clean, custody_difference |
| Same transport replay / new economic duplicate | transport_replay, economic_duplicate |
| Economic conflict / transport conflict | economic_conflict, transport_conflict |
| Missing sequence then retry / quarantined payload | gap_recovery, invalid_payload |
| Record before receipt, receipt before disposition, disposition before commit | crash_after_record, crash_after_receipt, crash_after_disposition |
| Commit before ACK / acknowledged restart | lost_ack, ack_restart |
| Two writers, same and separate streams; bounded lock retry | writers_same_stream, writers_separate_stream, busy_retry |
| Atomic saved-run interruption | save_run_crash |
| Changed prefix / shortened file / malformed JSON | changed_prefix, truncated_file, rejected_json |
| Equal quantities with different receipt evidence | new_receipt_economic_parity |

Five cases require an observed, named child barrier followed by actual SIGKILL
(`-9`) and join. The three precommit cases must retain the complete prior core and
transport state with none of the interrupted transaction. Lost ACK must retain the
first effect and return its original physical receipt and result on retry. The
save-run case checks all five run-related tables, the old run payload, and the
complete later correction result after a successful retry. Writer cases use
distinct process IDs; any bounded retries happen before final financial evaluation.
No financial run is created for a blocked stream.

Independent SQL readback checks exact sequences and first payload bytes, plan
identity, normalized record/receipt links and inventory, quarantine/conflicts,
attempt links, old runs, integrity and foreign keys. Plan expectations are computed
from the predeclared input bytes with an independent standard-library path, not
from `snapshot_feed` or the runtime cursor. Financial expectations use hand-written
values: ASSET_A I1=7, I2=4, liability=11, platform custody=2 and external=9; ASSET_B
I1=0.3, I2=0.2 and liability=0.5. In custody_difference the external report is 8:
A remains MATCHED, B is COMPLETE/MISMATCH with expected minus reported = +1.

## Observed development verification

On 2026-11-13, Python 3.14.7 / SQLite 3.53.4 / macOS 26.6.2 arm64,
the original 400-test suite passed once from a frozen 0.6.1 source copy. Focused
admission, schema, recovery and coverage tests were then run during implementation.
An early recovery run retained six evidence-serialization errors; the subsequent
21-case run passed after correcting the harness representation. Independent review
then strengthened plan/record inventory checks before the final release gates.

Independent review also reproduced two new admission boundary defects: a FIFO
could block at open, and an exclusive database lock could replace a retriable
delivery response with a status-query exception. Three regression assertions first
failed (one failure and two errors), then the same 24-test admission file passed
after bounded regular-file opening and explicit busy/UNKNOWN status handling.
These were new-feature boundary defects, not historical financial calculation bugs.

The explicit 3-to-4 migration experiment preserved four historical runs and all
old rows/objects, rehearsed rollback, verified idempotence and restored the backup
to a separate schema-3 target. Read-only schema-4 export preserved saved payloads.

Final source/installed suite identities, final 21-case execution records, the
373-file financial parity gate, distributions and exact commit/CI binding are
retained in the separate Stage 9 delivery evidence. This document does not label a
development run as a final installed or CI run. The existing release runner executes
the fixed recovery gate in full source/installed and core installed profiles.

## Interpretation

Rollback journal (`delete`) and synchronous `2` are recorded actual settings.
This experiment covers initialized application-process crash and bounded writer
contention. It does not test power loss, kernel failure, hardware durability,
Byzantine sources or all production concurrency. Seed identifies the fixed schedule;
OS/disk timing is not deterministic. Measured durations are observations, not SLA
or RTO guarantees. ACK, file EOF and financial completeness remain separate.
No frozen main model generation, training, final holdout, old A/B experiment or
100,000-event stress run is part of this task.
