# Stage 9.1 maintenance handoff

This maintenance release targets S9-F1 and S9-F2 in the reviewed Stage 9 commit
`16f54490635ee37bbb91eeece18a55f7316f13f2`. Package **0.7.1** keeps financial rule
`stage2-v2`, physical SQLite schema **4** and existing financial/review/triage v1
formats. No migration or financial recalculation rule changes are introduced.

The user-supplied independent review is starting evidence from a different
execution environment. This task's baseline, defect reproductions, RED/GREEN and
release records are labelled separately. The supplied original-version defect
demonstrator was also executed against the immutable 0.7.0 task baseline: both
findings reproduced, including two CLI exits 2 and four accepted invalid recovery
reports. Its exit 0 means the defects reproduced, not release acceptance.

## Repairs and contract boundary

- [S9-F1](S9-F1.md): duplicate-key diagnostics quote decoded key text using ASCII
  JSON escapes. Exact input bytes, hashes, plans, sequence identity, rejection
  disposition and core financial receipt semantics remain unchanged. A rejected
  frame has no fabricated core receipt. The real three-line/replay example must
  finish with prefix 3, two core receipts, three effects, six attempts and no
  financial run; both feed invocations intentionally exit 1 with structured output.
- [S9-F2](S9-F2.md): a separately pinned recovery v2 contract requires the work and
  evidence for each of the same 21 scenarios. Plans are checked before case work;
  controls are unique and complete, typed expected/actual values agree with their
  flags, financial phases are required or forbidden independently of the report,
  and crash/receipt/saved-run observations are linked. The runtime and release
  entry point use the same semantic acceptance rules.
- [Decisions](decisions.md): recovery report/schedule v2 is an explicit maintenance
  contract evolution. Historical v1 evidence is not relabelled or silently
  accepted through a compatibility fallback. Actual writer connection settings
  are observed separately from the readback connection; no PRAGMA is weakened.
- [Fixture changes](fixture-changes.md): all 451 previous test identities remain.
  Only the authorized named `report_fixture` function and necessary current
  metadata are adapted. Original/current hashes, exact differences and reversal
  checks bind the exceptions; old assertions and test intent are retained.

The new semantic contract is `contracts/admission-recovery-scope-v2.json`; its
packaged runtime copy must have identical bytes. Historical recovery v1 and
0.7.0 release-scope documents remain unchanged. The new fixed test roster is
`contracts/release-test-scope-0.7.1.json`. Ordinary verification loads these pins;
it never learns the expected scope from candidate output or test discovery.

## Reproduction and release verification

From a source checkout, use fresh output directories:

```sh
python3 -B -m crypto_reconciliation_lab demo-recovery --output recovery-new --seed 19
python3 -B scripts/verify_release.py --check-recovery recovery-new --output evidence-check-new
python3 -B scripts/verify_release.py --profile full --financial --output release-full-new
python3 -B scripts/verify_release.py --profile core --output release-core-new
```

The last two commands require the existing pinned build tools; the full profile
installs the existing pinned optional AI test dependencies into a fresh isolated
environment. The core profile uses no optional AI packages. The ordinary release
runner already executes the required recovery and financial checks; do not repeat
the expensive matrix in a second verification script. A supplied-source/wheel core
invocation can reuse the exact full-profile distributions, as recorded externally.

`--check-recovery` checks existing schedule/report completeness and consistency
through the actual release acceptance path. It does not rerun the application,
suite, build or matrix and labels those activities NOT_RUN. Incomplete or
contradictory evidence must produce a nonzero exit. It is not an authenticity or
signature verifier.

The immutable 0.7.0 baseline suite ran once: 451 expected, discovered and executed
unique IDs in 38 test/fixture files; all 400 earlier IDs retained; zero skips,
expected failures, failures or errors; exit 0. The baseline environment was macOS
26.6.2 arm64, Python 3.14.7 and SQLite 3.53.4. Its real prior 21-case recovery report
was reused only after binding all 160 source file hashes to the reviewed commit.
It remains historical recovery v1 evidence, not a new v2 run.

A separate task-owned copy of an actual 0.7.0 schema-4 database was opened/read
with 0.7.1 Store and the offline adapter. Saved payload text, all table/object
observations and original/copy database bytes remained equal. No migration or
new financial evaluation was performed in that check.

## Final execution and publication records

Final source and isolated installed suites, source/installed/no-AI recovery,
source/installed S9-F1 CLI observations, semantic release rejection controls,
sdist-to-wheel construction and all 373 financial file comparisons are recorded
in the external `stage9_1-output` directory. Its final `HANDOFF.md` and
`verification.json` contain the actual commands, exits, import origins, scopes,
distribution identities and final GitHub run/job/artifact bindings. They are
written after those observations; this source document does not preclaim them.

The same task branch `stage9/restartable-admission` and draft PR #1 are updated by
normal push. Main is not merged. Final commit/CI observations stay outside Git so
recording a completed run does not create another unverified commit.

The small review archive contains the tested source, fixed contracts, tests and
selected bounded proofs. Databases, virtual environments, caches, Git metadata,
credentials and historical output trees are excluded. An external manifest binds
its member identities and whole ZIP hash; a fresh extraction plus a small working
reproduction is recorded separately. Real wheel/sdist files are separate
deliverables. Unsuccessful development attempts remain distinguishable from final
acceptance records.

## Preserved history and limits

Financial core/normalization/corrections/Decimal rules, the independent integer
oracle, migrations, Store, review/triage logic, old contracts, docs/stage9 and
showcase assets are preserved. The fixed financial reference remains 325 matrix
files plus 12 Stage 1 and 36 Stage 2 files. Historical model deltas versus rules
remain test 0 and challenge −2.083 percentage points.

The frozen main experiment, generation, training, final holdout, old A/B benchmark
and 100,000-event stress are NOT_RUN. Existing small unit-test training remains
part of the inherited suite. No new dependency, service or live institution input
is introduced.

The fault model remains initialized local application-process SIGKILL and bounded
writer contention. It does not cover power loss, kernel or disk failure,
initialization crashes or distributed delivery. ACK is a durable transport
disposition, not financial validity or completeness. The evidence gate rejects
missing and contradictory required work; it cannot authenticate a completely
fabricated but internally consistent report. Main merge, force push, release/tag,
PyPI publication and workflow dispatch are outside this task.

Next step: independent acceptance review of the updated draft PR and bound proofs.
