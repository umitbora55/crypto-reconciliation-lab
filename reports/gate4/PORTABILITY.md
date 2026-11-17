# Gate 4 — portability and recorded evidence

**The WAL candidate is `CANDIDATE_NOT_ACCEPTED`; the current compatibility
invariants require `NO_CHANGE`.** The existing financial review exporter rejects
a WAL database even after a successful checkpoint and a clean close with no
sidecars. This is an observed incompatibility, independent of untested device or
power-loss guarantees. Production code and defaults remain unchanged.

The preregistered catalog is
[`contracts/gate4-portability-catalog.json`](../../contracts/gate4-portability-catalog.json),
SHA-256 `bd987071330cd53cd47f0dfa3989f535be9afa60eae82e9a5332e763c0aadc2d`.
The research runner is
[`validation_lab/gate4_portability.py`](../../validation_lab/gate4_portability.py).
All inputs are synthetic; the signing seeds are explicitly public LAB fixtures.
They do not establish external institutional authority.

## Executed witnesses

Authoritative corrected evidence:
`/workspace/validation-gate4-evidence/portability/run-002/`.
The outer command, actual exit, stdout and stderr are retained in sibling
`run-002-controller/`; each method also has its own command transcript.
The outer invocation exited 0 after 2.323 seconds; baseline and WAL children
exited 0 after 1.119 and 1.070 seconds. These are functional witness durations,
not performance estimates. A witness PASS means the expected positive or
negative behavior was observed; it does not mean the candidate passed its
compatibility gate.

| Witness | DELETE/FULL | WAL/FULL |
| --- | --- | --- |
| Protected unsigned `ingest` and `ingest_delivery` | Rejected | Rejected |
| Original first receipt at epoch 1; revoked-key historical replay; unseen suffix denial; new-key continuation at epoch 2 | Preserved | Preserved |
| All 30 exact physical receipts, original auth links and stored earlier execution context | Preserved | Preserved |
| Truncated, aborted, corrupted, bad-type and oversized-line protected inputs | Five explicit `AUTH_SNAPSHOT` denials, no new core receipts, audits retained | Same |
| Stored execution read and exact five-file export | Success | Success |
| Native original offline replay, 30 eligible receipts, default 30-second deadline | `REPRODUCED` | `REPRODUCED` |
| Wrong external execution ID and truncated replay context | Error | Error |
| Existing export/replay output, database/sidecar descendants and dangling output link | Rejected without overwrite | Rejected without overwrite |
| Online SQLite backup and quiescent DB plus sidecars copy | Exact logical equality | Exact logical equality |
| Uncheckpointed database-file-only copy | 30 receipts | **0 receipts although 30 were committed** |
| Schema 5 → 6; injected precommit migration failure; restore to a new schema-5 file; repeat migration | Preserved/rolled back/restored/idempotent | Same |
| Existing closed financial review export | `COMPLETE`, header bytes `[1,1]` | **`SNAPSHOT_UNSUPPORTED`, header bytes `[2,2]`** |

The header-only WAL witness performs `wal_checkpoint(TRUNCATE)`, observes
`[0,0,0]`, closes the connection, records an absent WAL/SHM/journal namespace,
and then invokes the unchanged review exporter. Its exact error is:

> SNAPSHOT_UNSUPPORTED: WAL or unknown database header mode is not supported
> [source=synthetic, run=None]

The live WAL witness separately observes the existing sidecar rejection. Neither
failure changes the source bytes. No sidecars are manually deleted and the
candidate source is never converted back to DELETE to make this check pass.

## Exact financial and provenance equality

The two methods produce identical all-table application snapshots, schema
objects, original receipt identities/order, auth acceptance links, financial
payload, recorded execution identity and all five export files. BLOB-bearing
auth/context tables use the existing `application_snapshot` encoding; equality
does not depend on physical SQLite layout hashes. Independently specified
literal balances are checked: A investors `7,4`, liability `11`, custody `2,9`;
B investors `0.3,0.2`, liability `0.5`, custody `0.05,0.45`.

- Financial run ID:
  `9398d22daaecec10202ed8eb5cd6a65f01976e0b73878ed5db3dad32ceaf2e5b`.
- Recorded execution ID:
  `815efd07ebbb950f3cb2d632fa7b27067b7266b7b4dacd5f7a88388ff4919fa7`.

The five recorded-export files are exactly `context.json`, `run.json`,
`execution.json`, `summary.json`, and `summary.md`. SQLite's database, `-wal`
and `-shm` files are a separate persistence namespace, not extra members of
that five-file format. The context and run files equal the raw stored bytes.
The original pre-rotation execution remains unchanged after rotation,
historical replay, later admissions and rejection audits.

## Sidecars, checkpoint and reopen observations

For the 30-receipt protected fixture before checkpoint, the baseline database
occupies 614,400 logical bytes and has no sidecars. WAL occupies 233,472 database
bytes plus 2,690,392 WAL bytes and 32,768 SHM bytes: **2,956,632 total logical
bytes**. The explicit WAL checkpoint took 0.001570384 seconds in this single
functional witness, returned `[0,0,0]`, left a 614,400-byte database, zero-byte
WAL and 32,768-byte SHM; close removed the sidecars. The baseline no-op returned
`[0,-1,-1]` in 0.000018037 seconds. These results neither count physical device
writes nor measure a stable checkpoint cost distribution. TRUNCATE's returned
zero frame counters do not report all frames copied during the operation.

Original pre-checkpoint database/WAL/SHM bytes are retained under each method's
`pre-checkpoint-raw/` as `.bin` files, so later SQLite opens cannot mutate those
evidence copies. Online backup retains every table and receipt. The file-copy
positive witness has one quiescent writer and is explicitly not a recipe for
copying a concurrently changing database. The database-only negative proves
that merely copying the main file can omit acknowledged WAL transactions.

Ordinary unmodified `Store` reopens observe DELETE or WAL as appropriate,
`synchronous=2`, `foreign_keys=1`, page size 4096 and auto-checkpoint 1000.
Every instrumented SQLite connection records settings at connect and close in
`sqlite-connections.jsonl`; readonly/backup connections honestly record their
own foreign-key setting, including 0. The observer supplies a connection
subclass and only reads PRAGMAs; it does not change transaction boundaries.

One further behavior matters for portability: `read_execution` uses `mode=ro`
and preserves the main WAL database bytes and logical contents, but reading a
clean closed WAL database in this writable directory **creates a zero-byte WAL
and a 32,768-byte SHM**. Its before/after namespace is retained. Read-only SQL
therefore does not imply an unchanged filesystem namespace for this candidate.

The native replay API uses its unmodified 30-second child deadline. Its
ephemeral worker PRAGMAs/transcript are **not claimed as retained**. An additional
retained child invokes the same production `verify_bytes` computation on the
same original two files and observes its private in-memory connection settings;
its complete comparison equals the native result. That separate observation
does not retroactively instrument the native process. This is not a replay
capacity benchmark or a historical executable identity claim.

## Prior attempt, checks and limits

`run-001/` is retained with its original source, results and logs. It correctly
observed the sidecar rejection, but its purported closed-header setup was not
isolated: the preceding recorded readonly show had recreated sidecars. Thus it
does not prove a header-only rejection. The corrected `run-002/` adds an explicit
checkpoint/close immediately before that witness and retains the exact header
and absent-sidecar inventory. The first attempt's provisional decision framing
is historical; the confirmed incompatibility supports the `NO_CHANGE` result
above. No original result bytes were rewritten.

Four new comparator guard tests pass on both Python 3.12 and 3.14, with actual
transcripts in `tests-py312-001/` and `tests-py314-001/`. They reject an empty or
duplicate method roster, missing checks, one-side substituted logical evidence,
and a false assertion that review compatibility succeeded. These unit fixtures
are validator checks, not product records or an independent external oracle.
The original 875 tests and financial reference remain untouched.

Each method has a 180-second parent deadline, 120-second CPU hard limit,
768-MiB address-space hard limit and 64-MiB per-file hard limit. The predeclared
owned-disk budget is 256 MiB; the corrected run's retained logical-byte sample
was 12,718,342 bytes before its final manifests. Source-before/source-after
bindings match. All child PIDs are owned, observed and reaped; timeouts would be
retained rather than replaced. These small cases do not establish peak RSS or
the limits of any production workload.

Network filesystems, other devices and abrupt power loss are **NOT_RUN**. The
input rejection cases exercise `ingest_signed` byte inputs, not an interrupted
filesystem loader. No institution-owned two-party records or natural-error
labels are present. Those unknowns remain distinct from the concrete financial
review incompatibility. A future WAL-compatible snapshot/export design would
require separate review; this work makes no such production change.
