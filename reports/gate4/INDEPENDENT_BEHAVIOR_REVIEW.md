# Gate 4 — independent raw semantic and crash review

**PASS within the recorded research scope:** a separate stdlib-only reader
verified all 40 semantic method executions and all 20 process-crash cells from
their original inputs and raw SQLite evidence. This review does not accept the
WAL candidate; the separate financial-review export incompatibility remains.

The reviewer did not author either producer harness and imports neither
production nor producer code. Its exact source is retained at
`/workspace/validation-gate4-evidence/independent-behavior/verify_semantics_crash.py`
and copied into `audit-001/reader-source.py`: 35,888 bytes, SHA-256
`5a00acf6dd2016172c577acfe8560b4ff77ae2b8488990d6c7624603d0bc788c`.
Execution began after the benchmark QUIET period ended. The actual command,
stdout, stderr, owned PID and real exit are in `command-001/`; it exited 0 in
1.218 seconds with empty stderr. `audit-001/result.json` records the verdict.

The reader independently checked:

- Exact catalog hashes and fixed rosters: 20 semantic cases × 2 methods, plus
  2 methods × 2 admission APIs × 5 crash boundaries. Empty, duplicate, missing
  or substituted cells cannot satisfy those rosters.
- Both source closures, catalog copies, materialized input bytes, matching
  initial database bytes, actual commands and their recorded exits.
- Every semantic final SQLite table, schema object, receipt insertion order,
  exact raw request and its hash/status; original delivery effects, attempts,
  response/ACK bindings and persisted selected-evidence mirrors.
- Canonical financial payload bytes and run IDs, initial and later literal
  economic values, VOID/REPLACE effects and evidence links, quarantine/conflict
  classifications, and independent asset mismatches. The later normalized
  duplicate and direct redelivery quantities are explicitly checked against
  the unchanged literal economic expectation.
- Every crash PID and exact barrier prefix, real `-9` exit and reaping,
  transaction/COMMIT state, FULL/foreign-key settings, and absence of an external
  ACK before the after-ACK boundary. Recorded ACK responses are also bound to
  the original physical core receipt and exact request bytes.
- Independently recovered raw post-kill database/journal/WAL/SHM copies,
  producer recovery copies, retry databases, and saved recovery/retry financial
  evaluations. Ordinary postcommit redelivery produces a duplicate physical
  receipt; restartable delivery reuses the original receipt and adds a replay
  attempt. Original saved runs remain exact.

The reader opened **141 fresh audit-owned SQLite copies** and bound **636
original input/source/evidence files**. It never opened an original evidence
database through SQLite. Original files were rehashed after the audit and were
unchanged. The full input inventory and copy/recovery/PRAGMA log are retained as
`audit-001/read-input-manifest.json` and `database-read-log.json`. Reviewer
connections are read-only after any recovery of their owned copy; their settings
are recorded separately from the production writer evidence.

Five same-reader rejection controls passed: empty PASS roster, duplicate
same-count PASS roster, substituted same-count case, same-count raw receipt
substitution with a recomputed receipt hash, and an invented precommit ACK.
Each corresponding positive witness was first accepted. The substituted raw
receipt bytes and unchanged external expected inputs are retained in
`negative-receipt-witness.json`; outcomes are in `negative-controls.json`.
No failed audit attempt needed replacement.

The semantic command's broad recorder noted changes to other agents' research
harnesses during that earlier run. The narrower semantic execution closure is
separately bound by matching before/after source inventories and was independently
rehashed here; this report does not claim the entire working tree was frozen.

This is an independent evidence reader with literal economic checks, not a
second implementation of every financial rule, external authentication of the
research machine, or representative institutional validation. It does not rerun
the original 875 tests or 373 financial references, and SIGKILL evidence does
not establish host power-loss, device-cache, RTO/RPO or compliance guarantees.
