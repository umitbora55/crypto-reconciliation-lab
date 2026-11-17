# Gate 4: transaction cost and durability reproduction

Gate 4 is a fixed research experiment around unchanged application 0.11.1,
stage2-v2 and schema 6. Its accepted source is
`c08114e847b8b0ab58f28d41917ba386878fa873`. All 445 files at that commit remain
unchanged. The new scripts do not expose a product WAL setting or alter defaults.
Use the final Gate 4 decision and independent review together with raw records;
component PASS and performance MATERIAL_GAIN are not deployment approval.

## Inputs and preparation

Use Python 3.12 with the repository's existing pinned full dependencies; the
source-auth witnesses need the existing cryptography dependency. Python 3.14 is
also used for the separate exact new research test population. No new runtime
dependency, public-data acquisition or frozen model experiment is required.
Run commands from the repository root. Every output directory must be new and
outside the checkout. Existing output is rejected; preserve failed attempts.

The two original files are available under
`/workspace/validation-gate3-evidence/capacity/run-001/inputs` in the measured
workspace. They are entirely synthetic, not Treasury/SEC or institutional records.
Their fixed hashes and expected integer balances are in
`contracts/gate4-evidence-scope.json`. The benchmark cannot silently regenerate a
missing input. The delivered archive's origin ledger identifies exact included
copies and any intentionally omitted original files.

First validate the source/ZIP lineage described in
`reports/gate4/LINEAGE.md`. Then run the independent input oracle before timing:

```sh
.venv-validation/bin/python -B scripts/validation/audit_gate4_evidence.py \
  --inputs /workspace/validation-gate3-evidence/capacity/run-001/inputs \
  --output /workspace/gate4-reproduction/input-audit
```

The oracle uses only the standard library, fixed input bytes, every ordered
receipt identity and integer-cent arithmetic. Its PASS binds this finite
synthetic schedule. It is not an external financial authority.

## Correctness and recovery

Run the finite catalogs before performance measurements so their work does not
compete with benchmark workers:

```sh
.venv-validation/bin/python -B -m validation_lab.gate4_semantics \
  --output /workspace/gate4-reproduction/semantics
.venv-validation/bin/python -B -m validation_lab.gate4_crash run \
  --output /workspace/gate4-reproduction/crash
.venv-validation/bin/python -B -m validation_lab.gate4_portability run \
  --output /workspace/gate4-reproduction/portability
```

The crash harness controls and reaps real child processes at five transaction
boundaries, for both ordinary and restartable admission. Ordinary retry can add
a physical DUPLICATE receipt; restartable delivery preserves its original
idempotency contract. SIGKILL does not test host/device power loss. Portability
separately records expected failures, existing read-only review behavior,
five-file recorded exports, source authentication, policy history, original
bounded replay, migration and backup/restore. A successful witness run may
correctly report `CANDIDATE_NOT_ACCEPTED`.

## One preregistered performance program

The actual original run stopped at its first warmup before creating a database:
the worker could not raise its inherited hard address-space ceiling. All original
ERROR/NOT_RUN records remain. A narrowly repaired, separately sealed
`contracts/gate4-benchmark-continuation.json` keeps the original primary roster,
ordering, inputs and thresholds, and reserves the prior consumption within the
original total budget. No primary timing had been observed before repair.
Nevertheless, the original all-roster-PASS/no-retry criterion is false; the
continuation is an explicitly disclosed protocol deviation. It is not evidence
that the original program succeeded.

Read `contracts/gate4-benchmark-protocol.json` before executing. It fixes all
34 cells: two warmups, 28 primary trials (seven matched pairs at each size), and
four instrumentation controls. It fixes ordering, input hashes, fresh databases,
the endpoint, uncertainty procedure and the material-gain threshold. Do not
refill missing pairs, remove failed trials, repeat for a favorable result or
change the threshold after measuring.

```sh
.venv-validation/bin/python -B -m validation_lab.gate4_benchmark \
  --input-audit /workspace/gate4-reproduction/input-audit/input-oracle.json \
  --output /workspace/gate4-reproduction/benchmark
```

That command describes a fresh prospective reproduction using the original
fixed protocol and the repaired source. It does not rewrite either recorded
attempt. The actual continuation invocation additionally supplied
`--protocol contracts/gate4-benchmark-continuation.json`; that contract pins
the original failed attempt and its paths. Do not edit those historical pins
to run in another workspace: declare any new experiment separately. Audit the
retained continuation without rerunning performance using:

```sh
.venv-validation/bin/python -B scripts/validation/audit_gate4_evidence.py \
  --benchmark /workspace/validation-gate4-evidence/benchmark/run-002 \
  --protocol contracts/gate4-benchmark-continuation.json \
  --output /workspace/gate4-reproduction/independent-comparison
```

Keep other local compute and disk-intensive tasks idle. The program has one
worker, 1,800 seconds wall, 900 aggregate CPU seconds and 6 GiB owned logical
disk. Address-space limits are 1 GiB controller and 1.5 GiB worker; these do not
cap kernel cache or prove continuously observed RSS. Filesystem and process
samples have their recorded sampling limitations. The 50k extension is NOT_RUN.

Parent timing includes process startup, full ingestion/reconciliation/persisted
run and canonical JSON export, integrity/equivalence checks, final checkpoint,
close and reopen. COMMIT timing is inclusive of SQLite's implicit work; WAL
autocheckpoint remains enabled. Logical file sizes and process I/O counters do
not identify physical device fsync latency. Both methods preserve one original
transaction per receipt and return only after COMMIT.

The fixed speed gate requires median paired gain at least 15% at both sizes and
a paired bootstrap 95% lower bound greater than 5%. All scheduled primary pairs
must complete and match. Small-sample p95 is the observed maximum. Performance
is only one gate: every semantic, recovery and portability invariant must also
hold before accepting a candidate for review.

## Exact new research tests and evidence

Freeze the final test/source inventory before running either interpreter:

```sh
.venv-validation/bin/python -B scripts/validation/run_gate4_tests.py \
  --freeze /workspace/gate4-reproduction/tests/inventory.json
.venv-validation/bin/python -B scripts/validation/run_gate4_tests.py \
  --inventory /workspace/gate4-reproduction/tests/inventory.json \
  --output /workspace/gate4-reproduction/tests/py312
.venv-validation314/bin/python -B scripts/validation/run_gate4_tests.py \
  --inventory /workspace/gate4-reproduction/tests/inventory.json \
  --output /workspace/gate4-reproduction/tests/py314
```

The runner binds the unchanged historical files and new executable sources,
compares static/discovered/executed/successful/completed test identities, and rejects missing,
duplicate or substituted tests, skips and changed source. It does not run the
historical 875 application tests or relabel old test executions. Any future
production proposal requires the separately specified source/installed
3.12/3.14 populations and 69/162/373 financial reference gates.

Retain exact command argv/cwd, interpreter, source snapshots, UTC boundaries,
owned process IDs, observed exits, stdout/stderr, raw trial records and every
failure. Independently recompute statistics from those trial records and check
the negative same-count substitution and forged-summary witnesses. The final
archive has an external SHA-256/size/member seal; its internal hashes are byte
integrity evidence, not independent institutional trust. Historical twelve
count-only false negatives and LAB signature limits remain unchanged.
