# Gate 4 process interruption and receipt durability

The preregistered 20-cell process-crash matrix passed on Python 3.12.14: two
journal methods × two admission APIs × five exact interruption boundaries.
Every controller owned its child PID, observed the selected pipe barrier, sent
SIGKILL, and reaped an actual `-9` exit. This establishes the tested process
recovery behavior on this host. It does not establish abrupt host power-loss,
device-cache or filesystem guarantees and does not authorize a production change.

The catalog is `contracts/gate4-crash-catalog.json`, SHA-256
`34e6163e2120c114b25fc7a70796b5a3ed34884a0a9b3eaba31688e64afe5254`.
The executable source is `validation_lab/gate4_crash.py`, SHA-256
`c9bf8fa1b33f0b7a2f647204fcbf787b132c741065378b8221061dd252068187`.
Raw evidence is `/workspace/validation-gate4-evidence/crash/run-001`.
The complete controller took 2.069 seconds; the pre-summary retained-byte
observation was 47,154,606 bytes, below the preregistered 1 GiB disk cap.
There were no failed, timed-out or refilled matrix cells.

## Matched initial state and independent economic expectation

All cells copy the same 344,064-byte initial schema-6 database, SHA-256
`56d540bd5b30a4d26586dd1360af5a12249238c9cb75945af65a73318a5d39e3`.
It contains 29 accepted receipts and an already saved historical run. The single
missing A3 withdrawal has the same original 310-byte request in every cell,
SHA-256 `e91b9a452f97d42c58d6e76202b9dbffb6878e7168350105a8443027a3a40559`.
The starting DB/input bytes are shared across the modes; physical post-crash
DELETE and WAL layouts are not required to have the same hash.

The outside-engine literal oracle expects ASSET_A balances I1=7, I2=5,
liability=12 and custody=(platform=2, external=10) before the withdrawal;
afterward I1=7, I2=4, liability=11 and custody=(2,9). ASSET_B stays at
I1=0.3, I2=0.2, liability=0.5 and custody=(0.05,0.45). Missing A3 produces
three ASSET_A INCOMPLETE/NOT_EVALUATED findings; committed A3 produces six
COMPLETE/MATCHED findings across both assets. These literals are checked before
using the finite successful references to compare exact table hashes, receipt
order, result payloads, selected evidence and run IDs.

## Observed interruption and retry behavior

Each row below represents both DELETE/FULL and WAL/FULL. Counts include the 29
initial receipts. “ACK” is the external research client's fsynced response ledger.

| Exact SIGKILL boundary | Recovered receipts | External ACK count | Ordinary ingest retry | Restartable delivery retry |
|---|---:|---:|---|---|
| Before BEGIN | 29 | 0 | ACCEPTED; 30 receipts | COMMITTED; 30 receipts |
| After BEGIN | 29 | 0 | ACCEPTED; 30 receipts | COMMITTED; 30 receipts |
| After all INSERTs, before COMMIT | 29 | 0 | ACCEPTED; 30 receipts | COMMITTED; 30 receipts |
| After COMMIT, before ACK | 30 | 0 | DUPLICATE; 31 receipts | REPLAY; 30 receipts |
| After ACK | 30 | 1 | DUPLICATE; 31 receipts | REPLAY; 30 receipts |

The research connection subclass delegates the production SQL without altering
transaction scope. It is armed after opening the Store and blocks on a pipe at
the chosen boundary. No sleep defines a crash point. The ACK ledger is written
only after the API returns from one completed COMMIT; the file and its directory
are fsynced before the `after_ack` event. The after-COMMIT/before-ACK case therefore
retains committed data without falsely inventing an observed client ACK.

Ordinary `Store.ingest` intentionally appends a physical DUPLICATE receipt on
redelivery. Restartable `ingest_delivery` reuses the original core result and
receipt for the same immutable stream/sequence/payload, while appending a REPLAY
attempt. No universal exactly-once claim is made. These are unsigned restartable
admission witnesses; signed source-auth, rotation and export coverage belongs to
the separate Gate 4 portability catalog.

Every event and reopened Store read back the expected journal mode,
`synchronous=2`, `foreign_keys=1`, and schema 6. Immediately after each child died,
the DB plus any DELETE journal/WAL/shm were retained before recovery. Direct
reopen and recovery of a separate raw copy produced identical logical snapshots.
Preexisting saved run bytes remained unchanged. Recovery and retry evaluations
on separately backed-up copies preserved the expected financial payload, selected
evidence and saved run identity. All logical tables, including operational
delivery tables and schema objects, were compared with their expected state.

## Reproduction and limits

From the repository root, use a fresh output path:

```sh
.venv-validation/bin/python -B -m validation_lab.gate4_crash run --output /workspace/validation-gate4-evidence/crash/reproduction-new
.venv-validation/bin/python -B -m unittest validation_gate4_tests.test_crash -v
.venv-validation314/bin/python -B -m unittest validation_gate4_tests.test_crash -v
```

The controller has a 120-second deadline; each child has a five-second gate
deadline, five CPU seconds and 512 MiB address-space limit. Fresh output creation
refuses overwrite. Child argv, cwd, PID, request hash, limits, real exit and
stdout/stderr are in each cell's `command.json` and adjacent files. The top-level
`source-before.json` and `source-after.json` bind the harness, adapter, catalog
and production modules and matched exactly. External controller observations
record actual exits from the tool invocation separately from child exit records.

Six negative/lifecycle test methods passed on both Python 3.12.14 and 3.14.10.
They reject missing, premature, substituted-request and fabricated precommit
ACKs, check the finite roster, and force a controller exception after spawning a
real child to verify cleanup SIGKILL plus actual reaping. One unrelated post-run
metadata-print helper syntax error is retained in
`crash/metadata-helper-attempt-001.json`; it occurred before that helper executed
and is not a matrix failure or a replacement trial.

Power removal, torn writes, filesystem failure and physical storage flush
behavior were not tested. WAL checkpoint behavior during a crash with concurrent
readers or a large accumulated WAL is not established by this small one-writer
matrix. The process-crash results cannot by themselves make the candidate
durability-equivalent for deployment. Promising performance remains a proposal
subject to the separate semantics/portability gates and review of these missing
durability properties; any failed or unavailable required invariant means
`CANDIDATE_NOT_ACCEPTED`. No production defaults or source files were modified.
