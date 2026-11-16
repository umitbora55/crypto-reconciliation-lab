# Resilience and security evidence

The supplementary Linux run passed **33 finite checks**. This is evidence about
the named boundaries and SQLite operations, not a production security certificate,
distributed exactly-once claim, power-loss guarantee or institutional risk reduction.
All supplementary inputs are **FULLY_SYNTHETIC**.

## Executed supplementary checks

Command, from the project root:

```sh
.venv-validation/bin/python -B -m validation_lab.resilience \
  --output /workspace/validation-evidence/resilience/run-001
.venv-validation/bin/python -B -m unittest discover \
  -s validation_tests -p test_resilience.py -v
```

The first command executed 33 checks with exit 0. The second executed four
evidence-gate tests with zero failures, errors or skips. Each probe's literal
expected and observed outcome is in `resilience/run-001/results.json`; its
pre-registered, exact case-ID inventory is in `protocol.json`. The gate rejects
empty, missing, duplicate or contradictory result rows rather than trusting a
positive aggregate count. The JSON summary has the same results.

| Boundary / operation | Executed conditions | Observed result | Scope |
|---|---|---|---|
| Regular input byte ceiling | 16 MiB−1, 16 MiB, 16 MiB+1 | First two bounded reads accepted; overflow `REPLAY_LIMIT` | Reader component; exact-size bytes are not asserted to be a valid context |
| Oversized public replay input | 16 MiB+1 context | Public API `ERROR / REPLAY_LIMIT`, exit 2 | Public API; calculation not completed |
| Input type | Final symlink; FIFO opened nonblocking | Both `REPLAY_INPUT` | Actual local filesystem objects; removed after recording observations |
| JSON nesting | 1,023; 1,024; 1,025 | First two pre-parser checks accepted; 1,025 `REPLAY_LIMIT` | Depth guard, not full financial validation |
| Integer identities | 2^53+1; 2^63−1; 2^63; bool; zero | First two accepted exactly; remaining three rejected | SQLite identity validator, no JavaScript rendering claim |
| Receipt inventory count | 9,999; 10,000; 10,001 | First two typed inventories accepted; 10,001 `REPLAY_LIMIT` | Typed inventory component, not complete replay |
| Total captured row count | 49,999; 50,000; 50,001 | First two typed inventories accepted; 50,001 `REPLAY_LIMIT` | Typed inventory component, not complete replay |
| Timeout input domain | Default inspected; 0, 61, bool supplied | Default 30 seconds; all three invalid values `REPLAY_INPUT` | Public argument checks; not three long waits |
| Owned database quota | `max_page_count` with a larger attempted BLOB | Actual `SQLITE_FULL`; transaction rollback preserved anchor | SQLite page-quota simulation, **not physical disk exhaustion** |
| Quota recovery | Raise owned quota and retry | One subsequent row committed, expected count 2 | SQLite microprobe |
| Backup and restore | SQLite backup, separate restored file | Exact logical rows retained, `integrity_check=ok`, restored count 2 | Owned synthetic database, not a production disaster recovery exercise |
| Lock contention | Two connections; first holds `BEGIN IMMEDIATE` | `SQLITE_BUSY`; retry after release commits once, count 3 | SQLite microprobe; 50 ms configured wait |

The replay limit probes deliberately distinguish **controlled refusal** from
throughput. Accepting 50,000 typed rows does not demonstrate a semantically valid
50,000-row capture, successful replay at that size, or unlimited scale.

## Application crash, concurrency, signatures and publication

The current full release gate, recorded separately in
[TECHNICAL_VALIDATION.md](TECHNICAL_VALIDATION.md), owns the source and installed
execution of the protected historical tests. This supplementary module does not
claim those tests were independently executed again. Relevant unchanged tests
include:

- `test_admission_recovery.py`: real `SIGKILL` before receipt/disposition commit,
  post-commit ACK loss and retry, two writers, retryable busy and saved-run crash.
- `test_execution_replay_process.py`: real blocked child killed and reaped,
  malformed/missing/oversized child results, atomic publication, no overwrite.
- `test_review_output_paths.py`: direct and descendant `-wal`, `-shm`, `-journal`
  destinations, symlink parents and canonical paths, source byte preservation.
- `test_source_auth_crypto.py`, `test_source_auth_runtime.py`,
  `test_source_auth_consistency.py`: published cryptographic vectors, invalid
  signatures, revocation/rotation, historical acceptance, scope and same-count
  substitutions, contradictory source/SQL evidence.

An actually observed source timeout witness exists at
`release-full-py312/process-evidence-replay-source/test_real_blocked_child_hits_deadline_is_killed_and_reaped/observation.json`:
the test-owned blocked worker was terminated with return code **−9** after a
configured **1-second** deadline. This is a finite deadline/child cleanup witness,
not a production workload latency or RTO measurement. The final release report
determines whether all remaining gate operations completed.

Application recovery measurements and their process barriers must be taken from
the current release gate's raw recovery records. We do not convert an observed
local rollback into a zero-RPO guarantee for storage failure. No institution's
incident rate, annual loss, recovery SLA or production cost was observed.

## Source and dependency triage

`resilience/run-001/source-triage.json` records a bounded, locations-only scan of
**329 tracked UTF-8 files** of at most 2 MiB each. Four patterns (private-key
headers, GitHub-token shapes, AWS-key shapes, email shapes) produced **zero
candidates** in this run. This is not proof that the repository contains no
personal data, credentials or other sensitive information. Binary files, larger
files and untracked inputs were outside this scan; matching values are never
printed or retained.

The AST inventory found **229 SQL call sites** and records query-expression type
and whether a separate parameter argument is present. Dynamic SQL expressions
include internal schema identifiers and bounded PRAGMA values; the existence of
an f-string is not by itself an injection finding. This inventory is **TRIAGE_ONLY**,
not a complete source-to-sink audit. No external institution was probed.

`installed-sbom.json` lists the actual distribution names and versions of the
interpreter used for this run. It is an installed-package inventory, not an
independently signed SBOM or CVE clearance. A dependency advisory database scan
was **NOT_RUN**.

## Explicit untested boundaries

Physical disk exhaustion, power loss, a 16,777,216-node parsed JSON allocation,
valid end-to-end maximum-size replay, million-event workloads, months-long soak,
distributed recovery, macOS arm64 and real institutional RTO/RPO are **NOT_RUN**.
Linux success is not assigned to other operating systems. No new P0/P1 defect
was demonstrated by these 33 checks; that finite result does not establish that
all critical defects are absent. Institutional risk reduction remains **NOT_PROVEN**.

## P2: historical test observation barrier is racy

The first current Python 3.14 full source gate executed all 875 test identities
and failed `test_lab_contract_validation.ProtocolValidationTests.test_seen_failure_survives_later_truncated_result`:
the watchdog returned `UNKNOWN` where the test expected `FAILED`. The failed
run remains evidence; a subsequent successful run does not erase it.

The protected test supplies an RSS callback that independently reads the child's
`result.json`. On seeing `CORRECTNESS_FAILED`, this callback releases the child
to truncate that file. The real watchdog loop calls its own `read_child()`
**before** calling the RSS callback. A failure written between these operations
can therefore be observed only by the test callback, which releases the child
before the watchdog has observed the failure. The next watchdog read sees
truncated JSON. The test's marker says “parent sampled readable failure”, but
does not establish that the watchdog's correctness sampler observed it.

Three repetitions of the exact unchanged test under isolated Python 3.14 each
passed. Their wall times were approximately 0.388, 0.335 and 0.314 seconds. A
separate deterministic, test-owned two-schedule witness then established:

| Schedule | Actual watchdog observation | Observed correctness | Completion |
|---|---|---|---|
| Only test RSS callback reads failure before truncation | No readable failure object; subsequent JSON parse error | `UNKNOWN` | `TIMED_OUT` |
| Watchdog `load()` reads failure before truncation | Readable failure object retained; subsequent JSON parse error | `FAILED` | `TIMED_OUT` |

This is a **P2 test synchronization defect**, not demonstrated loss of an
already-observed financial failure or a false `PASSED` result. It remains
unrepaired to preserve the protected historical test bytes. A future narrow
test repair should acknowledge the real watchdog read rather than an unrelated
RSS read. Serial execution can reduce the scheduling exposure but cannot fix
the handshake contract.

Exact commands, exits and logs are in
`resilience/py314-diagnosis/exact-repetitions.json`; the standalone reproducible
witness is `resilience/py314-diagnosis/reproduce_test_barrier_race.py`, with
results at `deterministic-schedules/summary.json`. Instrumented schedules are
explicitly separate from the three unchanged-test executions. Production files
and protected tests were not modified during diagnosis.
