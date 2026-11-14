# Stage 10 source handoff

## Implemented scope

Package 0.8.0 adds optional DSSE/Ed25519 admission to a newly protected local
database, with exact file/capability binding, per-transaction policy epochs,
append-only decisions, revoked-key historical replay and same-source key rotation.
Each protected receipt/effect and its authorization links share one commit.
Unsigned public Store, module and CLI paths reject protected writes. Admission
does not run reconciliation or certify financial truth.

Schema 5 is additive (0→2→3→4→5). Existing opens remain read-only; explicit migration
uses verified backup, rollback rehearsal, preservation, idempotency and separate
restore. Populated historical databases remain legacy. The financial rule stays
stage2-v2; financial/review/triage v1 payloads and recovery v2 bytes/reader remain.
The previous handoff is preserved at `docs/stage9_1/HANDOFF.md`.

## Observed before sealing the source

- Starting remote main: c49f1a1752caf3083bedc8aa797e77023c3db7d4, package 0.7.1,
  schema 4. Its 175-file source snapshot matched the accepted tree.
- Actual immutable baseline suite: 472 discovered/executed unique identities,
  zero failures/errors/skips. Command duration 45.2465 seconds.
- Final candidate source integration: 540 discovered/executed unique identities
  (472 preserved + 68 additions), 51 declared test/fixture files, zero failures,
  errors, skips, expected failures or unexpected successes. Actual unittest
  duration 61.073 seconds; launcher exit 0, duration 61.6444 seconds.
- The fixed 0.8.0 scope is 80,521 bytes, SHA-256
  `7dc06a3a89c2756f1574479cd288cec1bef65fe13925bfa5703a3be829311ec5`.
  Five old files have exact reversible metadata/setup exceptions documented in
  `fixture-changes.md`; no old identity or financial assertion was removed.
- Focused crypto/runtime checks: 25 tests passed. New migration/guard checks:
  8 passed; real operator/signed/unsigned CLI checks: 2 passed.
- Auth experiment: 18 fixed families / 33 scenarios, two real SIGKILL barriers,
  one process policy race, six semantic mutations rejected and extra information
  accepted. Signed wrong custody remains COMPLETE/MISMATCH, difference +1.
  Thirty identical legacy/protected financial records produce identical core rows,
  run IDs, JSON and Markdown. The final experiment-focused suite passed 25 tests.
- A populated genuine schema-4 copy migrated to 5 with all 12 prior tables and
  objects preserved; separate restored backup matched its original snapshot.
- Actual environment: Python 3.14.7, macOS 26.6.2 arm64, SQLite 3.53.4. Optional auth
  installed cryptography 50.0.2, cffi 2.1.1 and pycparser 3.12; auth-only environment
  had no numpy/scipy/sklearn. Actionlint 1.7.12 passed locally with verified download.

## Failures retained and repaired

The first 539-test integration failed three current-schema metadata expectations.
Only the authorized current-version and future-version fixtures changed; the future
fixture now uses 6 while current is 5. The second integration passed all 540 tests.

An internal adversarial check exposed a verifier false positive: a valid trusted
signature substituted for the bad-signature scenario could still pass a reported
DENIED result. The same new regression first failed all 20 subcases and then
passed after the reader independently checked each denial stimulus, policy and
audit input binding. Repeating the preserved independent mutation now rejects it
specifically for an unexercised denial condition; the real original bundle passes.
This was an evidence-reader gap, not an accepted unauthorized financial write.
Early fixture/reader development failures and their actual logs remain outside Git.

## Commands and final delivery boundary

The actual task-local source launcher was `full-env/bin/python -B
run_source_integration_2.py`; it invokes the fixed identity runner from
`scripts/verify_release.py`. Exact absolute argv/cwd, interpreter/import origin,
stdout/stderr, exits and durations are retained under
`stage10-output/release-commands/source-integration-2` and `source-integration-2`.
The initial auth installation's elapsed time was not captured and is explicitly
null, rather than inferred; later timed installations are separate observations.

After this source handoff, final distribution gates run from the sealed source:

```sh
python -B -I scripts/build_release.py --output NEW_BUILD
python -B -I scripts/verify_release.py --profile full --financial --source EXTRACTED_SDIST --wheel BUILT_WHEEL --output NEW_FULL
python -B -I scripts/verify_release.py --profile core --source EXTRACTED_SDIST --wheel BUILT_WHEEL --output NEW_CORE
python -B -I scripts/verify_release.py --profile auth-only --source EXTRACTED_SDIST --wheel BUILT_WHEEL --output NEW_AUTH
```

Their actual outcomes, the 373-file financial comparison, isolated installed tests,
final commit, draft PR, CI jobs/artifacts, distribution hashes and clean archive
check belong in the external `stage10-output/HANDOFF.md` and verification JSONs.
This source document does not predeclare those later results as PASS, and the final
CI result is not committed back into a new CI cycle. CI retains full Python 3.12
and 3.14 plus core and auth-only jobs; only full 3.14 requests the financial matrix.

No frozen main generation/training/holdout evaluation, heavy benchmark, real
customer data, institutional connection, tag/release/PyPI publication or main merge
is part of this task. The historical model-minus-rules result remains 0 percentage
points on test and −2.083 on challenge. Public test-vector seeds are TEST-ONLY.
The local operator, Python process and database owner are trusted; no institutional
identity, trusted-clock, disk/power-loss or malicious-owner guarantee is claimed.
