# Stage13.1 verification

The new tests are `test_execution_replay_link_repair.py` (five finite relation
controls), `test_execution_replay_output_repair.py` (eight output-boundary
controls), and `test_replay_maintenance_scope.py` (four preservation controls).
They add 17 identities to the unchanged 858-ID roster. Only the six authorized
current metadata literals change in old tests; see `fixture-changes.md`.

The first two test files run on unchanged 0.11.0 before either repair and run
again byte-identically after repair. Link negatives use exact independent review
bytes and a finite existing-sequence mismatch. The two output RuntimeError seams
are test-owned and intercept only output-parent resolution after real worker
completion. They are not labelled as actual Python3.12 filesystem executions.
Four real self-loop API/CLI methods run without skips on both supported CI minors.

The small release gate consumes genuine historical pairs without admission,
training or fresh capture. From an isolated installed interpreter, outside source:

```sh
venv/bin/python -I -B source/scripts/release_replay_maintenance.py \
  --tests source/tests --output new-repair-evidence
```

It runs eight real CLI operations: protected positive, stream and sequence
contradictions, original-pin rejection, clean and financial-divergence positives,
and both positives with real symlink-loop output parents. It records complete
JSON/stdout/stderr, command/cwd/interpreter, input identities and completed
comparison preservation. Full/core/auth-only profiles retain this evidence. The
core environment has neither AI nor crypto dependencies. Existing seven replay
demo cases and all earlier profile controls remain in the release gate.

Build and release commands keep the existing interface:

```sh
python scripts/build_release.py --output new-build
python scripts/verify_release.py --profile full --financial \
  --source extracted-source --wheel built-wheel --output new-full
python scripts/verify_release.py --profile core \
  --source extracted-source --wheel built-wheel --output new-core
python scripts/verify_release.py --profile auth-only \
  --source extracted-source --wheel built-wheel --output new-auth
```

The source and isolated installed full suites must match exact expected,
discovered and executed unique IDs with zero skips/xfails/errors/failures. The
fixed financial reference remains 69 cases / 162 evaluations / 373 files. Only
the full Python3.14 CI cell runs the financial matrix; other cells report it
NOT_RUN. Core/auth-only do not claim full suites. Existing action and dependency
pins are unchanged, and remote execution follows a normal task-branch push.

Actual timings, failures, imports, hashes, final SHA, five CI jobs and four original
artifact ZIPs belong in the external HANDOFF, not a second documentation commit.
The final review archive is member/hash checked and installed in a fresh core
environment for the eight CLI controls. No second full suite is required for
identical final bytes. Historical large experiments and frozen holdout remain
NOT_RUN; no merge or release publication is part of this maintenance task.
