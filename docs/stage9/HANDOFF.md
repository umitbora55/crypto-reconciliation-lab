# Stage 9 source handoff

This source adds finite restartable JSONL admission to the existing financial core.
The public APIs are `Store.ingest_delivery` and `Store.feed_status`; CLI commands
are `ingest-feed`, `feed-status` and `demo-recovery`. Review the
[admission contract](admission-contract.md), [decisions](decisions.md),
[recovery experiment](recovery-report.md) and [fixture changes](fixture-changes.md).

Package 0.7.0 introduces additive physical schema 4. Financial rule `stage2-v2`,
v1 financial payloads, immutable historical test contracts and the fixed 373-file
financial reference are retained. Old database opens do not migrate. Explicit
migration performs backup, copy rehearsal, rollback, preservation and separate-target
restore. Legacy direct ingest still appends a receipt on every call; transport
replay reuses the original receipt. A changed transport identity or input plan
blocks new effects, without inventing a financial state or reason code.

All 400 earlier test identities remain declared in the new pinned release scope.
Only documented current-schema/release fixtures are adapted; financial assertions
are retained. New test files cover admission, migration, real process recovery and
fixed experiment coverage. The normal verifier never derives its expected roster
from candidate discovery. The unchanged financial reference remains authoritative.

The Stage 8 README presentation assets and their capture provenance are preserved.
The README's current package/schema line and a short admission entry identify this
new work; the old showcase remains dated 0.6.1 evidence.

Run `python3 -m crypto_reconciliation_lab demo-recovery --output NEW_DIRECTORY --seed 19`
for the bounded 21-case recovery experiment. For distribution validation, use the
existing `scripts/verify_release.py` full/core profiles; those commands now include
the pinned recovery coverage gate. The full financial profile performs the legacy
matrix and demo parity comparisons, so a second matrix script is unnecessary.

Final outside-Git `stage9-output/HANDOFF.md` and `verification.json` bind this source
to actual commands, environments, exits, distributions, task branch, draft PR and
exact-commit CI. Development observations in the recovery report are not substitutes
for those final records. Main is not automatically merged. Existing frozen main
model/data/results/freeze/lock files are outside this task's write/run scope.
