# Five-minute recorded execution review

## 1. Start with the limits

This is a local, synthetic execution record. It preserves eligible physical inputs
and their existing admission relationships while computing one financial result.
It is not a new financial rule, actor-authorization system, timestamp attestation,
independent cryptographic verifier or distributed exactly-once service. The
financial rule remains stage2-v2. Package 0.10.0 adds SQLite schema 6; existing
v1 provenance remains an actual schema-5 format.

## 2. Run the small examples

Use Python 3.12 or later and a fresh output path. Core execution needs only the
standard library:

```sh
python3 -m crypto_reconciliation_lab demo-execution-context --profile legacy --output execution-legacy-new
```

The nine cases cover an ordinary saved run without recorded context, explicit
recording, retry, conflicting parameters, a new request sharing the financial
run, ambiguous run-only lookup, readback, exact export and no-clobber refusal.
With the optional pinned auth extra, run the seventeen-case example:

```sh
python3 -m venv .venv-execution
.venv-execution/bin/python -m pip install '.[auth]'
.venv-execution/bin/python -m crypto_reconciliation_lab demo-execution-context --profile protected --output execution-protected-new
```

Open `summary.md` and `summary.json`. Every case links its actual command,
interpreter, working directory, exit code, stdout/stderr identities and JSON
result under `commands/`. Expected financial values are literal references,
independent of the production calculator: ASSET_A I1=7, I2=4, liability=11,
platform customer custody=2 and external custody=9; ASSET_B I1=0.3, I2=0.2,
liability=0.5, platform=0.05 and external=0.45.

## 3. Follow one request across later changes

`protected_recorded` stores 30 physical receipts with observed policy head 1.
A later real admission supplies an identical economic message through a new
stream, and policy epoch 2 revokes the original platform key. The original
request's retry returns its unchanged execution/context. A new request sees
31 physical receipts and head 2; the original acceptance decisions still refer
to epoch 1. Both candidate physical rows survive; no minimum/first/last row is
invented as the historic financial engine's chosen source.

The two requests share a financial run but have different execution/context
identities. Run-only lookup returns `MULTIPLE_EXECUTIONS` and all IDs, without
arbitrarily selecting one. The separate signed mismatch keeps financial
liability 11 against reported custody 10, difference +1. Its recorded context
does not turn `MISMATCH` into `MATCHED`.

## 4. Inspect immutable readback

Use an execution ID from `summary.json` with the ordinary CLI:

```sh
python3 -m crypto_reconciliation_lab show-execution --db PATH --execution-id ID
python3 -m crypto_reconciliation_lab export-execution --db PATH --execution-id ID --output execution-export-new
```

The reader opens SQLite read-only and does not migrate, admit, recalculate or
augment saved history. Exports contain exact stored `context.json` BLOB bytes
and `run.json` TEXT bytes, plus `execution.json`, `summary.json` and `summary.md`.
Existing directories and database/sidecar output collisions are rejected.

`reconcile-recorded` exits 0 for a matched financial evaluation, 1 for an
observed non-matched financial result and 2 for operational/input/integrity
failure. `show-execution` and `export-execution` exit 0 on successful read/export
independently of financial MATCHED/MISMATCH. The finite demo exits 0 only if all
its expected outcomes, including deliberate exit-1/exit-2 cases, are observed.

## 5. Read process evidence separately

The demo deliberately performs no crash or race experiment. Full source and
isolated installed suites retain eight fixed process-test records: six SIGKILL
variants (three barriers, each fresh and pre-existing financial run), four
ordered admission/policy races and same-request contention. There are 27 child
process observations. READY records bind PID, import origin, interpreter,
isolation, SQLite version and observed writer settings. SIGKILL records preserve
barrier transaction state, actual -9 exit and UNKNOWN sender outcome; retry and
separate-connection snapshots distinguish rollback from durable commit before
the first CLI ACK. Busy writer responses are not commits.

The release gate independently checks the fixed 9/17 demo inventory, literal
financial outputs, actual CLI logs, physical/context counts and the complete
process-evidence roster. Full profiles run source and installed demonstrations;
auth-only runs the installed protected example; core runs the installed legacy
example and explicit protected dependency refusal. Core/auth-only full suites
and process experiments are NOT_RUN, as are financial matrices in cells without
`--financial`. Do not translate those omissions into success claims.

Recorded context has `source_signature_verification=NOT_PERFORMED` and
`run_actor_authorization=NOT_DEFINED`. An old ordinary run remains NOT_RECORDED
until a new explicitly requested execution is created; that does not establish
what was visible when the old run was originally created. SIGKILL evidence is
about process interruption, not power failure, disk corruption or storage
rollback. Actual command outcomes and final CI evidence belong outside Git in
the Stage 12 handoff, rather than a commit-dependent success badge here.
