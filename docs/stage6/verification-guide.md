# Portable verification

Scripts locate the source root from their own file, not the caller's cwd. Use
Python >=3.12 and new owned output paths. Actual commands, cwd, interpreter/import
origins, durations, exits and hashes are recorded. Nothing publishes remotely.

```sh
python3 scripts/reproduce_review.py --output review-output-new
python3 scripts/reproduce_review.py --mode installed --python VENV_PYTHON --output installed-review-new
```

Source mode explicitly imports the source package. Installed children use an
outside cwd, `-I`, no PYTHONPATH and a checked site-packages origin; their version
must match the source/sdist. Venv interpreter symlinks are not resolved to the
base interpreter. Both modes produce nine demos, 24 evaluations, a second export
and a declared model-ranking subset. DB hashes and absent sidecars are checked.

The small example preserves T-only observations, raw findings, history/current
snapshots and a fixed JSON model. Its manifest lists origin hashes, selected IDs
and packaging-only path changes. A negative copy changes source time to H while
summary stays T: exit 2 and no queue are required. The subset is never sent to
full freeze/evaluation; no new metric is inferred.

## Distribution gates

```sh
python3 -m venv .venv-release
.venv-release/bin/python -m pip install -r requirements-build.txt
.venv-release/bin/python scripts/build_release.py --output build-new
.venv-release/bin/python scripts/verify_release.py --profile full --financial --output full-check-new --source EXTRACTED_SDIST --wheel WHEEL
.venv-release/bin/python scripts/verify_release.py --profile core --output core-check-new --source EXTRACTED_SDIST --wheel WHEEL
```

Substitute literal `source_root` and `wheel` values from `build-new/release.json`.
Omitting both inputs makes each verifier build its own sdist→wheel chain. Local
validation may reuse one proven pair. The full profile uses pinned AI dependencies
and unchanged tests from the sdist against the clean installed wheel; source mode
is checked separately. Empty discovery, unexpected skips, wrong imports, package
drift, missing coverage or subprocess failures fail the gate. `--financial` adds
one 69-case/162-evaluation matrix and compares financial reports and 6+18 demos
to included reference hashes. No heavy benchmark or main ML experiment runs.

Core uses a separate `--no-deps` wheel environment with no sklearn/NumPy/SciPy,
checks their absence and import inventory during CLI/review/rank, and does not
claim skipped training tests passed. Expected MISMATCH/INCOMPLETE findings are
distinct from application failures.

`verification.json`, `verification.md` and logs describe actual results. Failed
attempts keep separate outputs; choose a new directory for retry. Current release
records accompany the separate review evidence. Static source/sdist documents
describe the protocol without embedding self-referential distribution hashes.
