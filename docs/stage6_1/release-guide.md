# Reproduce and verify package 0.6.1

Use Python >=3.12. Core financial reconciliation, offline review and JSON scoring use the standard library. Build tools and optional AI dependencies keep their existing pins. Initial installation/build may download packages; installed core execution requires no network or credentials.

From a clean source release or extracted sdist:

```sh
python3 scripts/reproduce_review.py --output review-output-new
python3 -m venv .venv-release
.venv-release/bin/python -m pip install -r requirements-build.txt
.venv-release/bin/python scripts/verify_release.py --profile full --financial --output release-check-new
.venv-release/bin/python scripts/verify_release.py --profile core --output core-check-new
```

Every output must be new. The full command builds the sdist, safely extracts it, builds the wheel from that extraction and installs it non-editably in a clean AI environment. Source and isolated installed suites must satisfy the explicit [scope contract](scope-contract.md); a missing test module or changed reference fails before expensive release work. Installed tests use an external cwd, `-I`, and no PYTHONPATH.

The core command uses a separate no-dependency installation and proves sklearn/NumPy/SciPy absent and unimported. It runs nine scenarios / 24 saved evaluations, read-only export and fixed-model subset ranking, plus the expected H/T negative CLI exit 2 with no queue. Expected synthetic MISMATCH/INCOMPLETE findings do not mean application failure. A nonzero release command means validation failed; inspect its verification.json and logs.

To reuse an already built pair, provide both `--source EXTRACTED_SDIST --wheel WHEEL` to the verifier. These paths still receive the mandatory test and complete financial-reference preflight. Build-only usage remains `python scripts/build_release.py --output build-new` with the pinned build environment.

The [original small review guide](../stage6/five-minute-review.md), [example provenance](../../examples/triage-review/selection-manifest.json) and [historical evidence guide](../stage6/historical-evidence.md) remain preserved. The fixed main model is never trained or final-evaluated by these commands. Its historical test/challenge difference versus rules remains 0 / -2.083 percentage points.

Actual local commands, test identities, comparison inventories, artifact hashes and unexecuted support cells accompany the separate Stage 6.1 review delivery. Prior Stage 6 records remain immutable. Prepared GitHub jobs are NOT_RUN until an independently authorized remote execution occurs; no publication is part of this maintenance release.
