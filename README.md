# crypto-reconciliation-lab

A local, synthetic reference model for reconciling an event ledger, reported investor balances and assets held for customers. Findings retain immutable input and receipt references. Economic time and knowledge time remain separate, so late events and reporting corrections create new evaluations without rewriting old evidence.

**Package 0.6.1 · Python >=3.12 · financial rule stage2-v2 · SQLite schema 3.** Review and triage v1 contracts are unchanged. Core reconciliation, offline HTML review and fixed JSON-model scoring use only the Python standard library. Optional AI dependencies support the existing small training tests.

This is an engineering portfolio, not an official KVMKS client, production integration, compliance certificate or proof of a current institutional system deficiency. No real customer data, API key or paid service is needed.

## Run the small review

From an extracted source release or sdist, with Python 3.12 or later:

```sh
python3 scripts/reproduce_review.py --output review-output-new
```

Open `review-output-new/index.md`, then `review-output-new/review/bundle/index.html`. One command creates nine demos and 24 saved evaluations, exports a second read-only view, ranks a declared T-only subset with the existing JSON model, and verifies rejection of a contradictory future-source input. Use a **new output directory** each time. It never generates, trains or final-evaluates the frozen main experiment.

| Example | Expected observation |
|---|---|
| Clean ASSET_A | I1=7, I2=4, liability=11; both comparisons match |
| Custody difference | Investor comparison matches; custody difference is +1 |
| Late withdrawal | Initially INCOMPLETE / NOT_EVALUATED; later MATCHED |
| Deposit correction | Old evidence remains fixed; independent report revisions resolve A and B separately |

MISMATCH and INCOMPLETE can be expected synthetic findings. A missing output, incomplete demo roster or unexpected subprocess exit is an application failure. Reproduction exits 0 only after all checks pass; the invalid rank's expected exit 2 and absence of output are recorded separately. See the [five-minute review](docs/stage6/five-minute-review.md) and [example origin manifest](examples/triage-review/selection-manifest.json).

## Build and verify

```sh
python3 -m venv .venv-release
.venv-release/bin/python -m pip install -r requirements-build.txt
.venv-release/bin/python scripts/verify_release.py --profile full --financial --output release-check-new
```

This builds an allowlisted sdist, safely extracts it, builds a wheel **from that sdist**, and installs the wheel into a clean AI environment using the [unchanged pinned constraints](docs/stage5/ai_constraints.txt). Tests come from the sdist; installed imports use an outside cwd, `-I` and no PYTHONPATH. All 375 prior tests remain, with new tests limited to the two coverage repairs. A pinned independent contract binds the test files and expected identities to discovery and actual execution; missing, substituted or duplicate identities and unexpected skips fail the gate. The sole authorized old fixture edit derives its package version from the builder constant. The profile also checks source mode, package metadata/assets, small reproduction, the 69-case/162-evaluation financial matrix and 6+18 demos against historical financial hashes.

Run the distinct core/no-AI check:

```sh
.venv-release/bin/python scripts/verify_release.py --profile core --output core-check-new
```

It installs the wheel with `--no-deps`, proves sklearn/NumPy/SciPy absent and unimported during import/CLI/demo/export/JSON-rank, and makes no claim to execute AI training tests.

Build distributions without running application checks:

```sh
.venv-release/bin/python scripts/build_release.py --output build-new
```

`build-new/release.json` records actual sdist/wheel/extracted-source paths, commands, metadata, hashes and inclusion inventory. A prebuilt pair can be checked with `verify_release.py --source EXTRACTED_SDIST --wheel WHEEL ...`; installed reproduction uses `reproduce_review.py --mode installed --python VENV_PYTHON`. See the current [release guide](docs/stage6_1/release-guide.md), [scope contract](docs/stage6_1/scope-contract.md) and preserved [Stage 6 build design](docs/stage6/build-contract.md).

Before build/install/test/reproduction, both profiles validate the complete fixed 373-file financial reference and declared test-file scope. Demo parity compares exactly 12+36 reports; `--financial` additionally compares all 325 matrix reports. Empty or incomplete reference coverage cannot yield successful equality.

Initial installation and isolated builds may download dependencies, including pinned setuptools. Installed core operation needs no network or credentials. Financial reproducibility is checked; byte-identical results from two independent wheel builds are **not** a measured claim.

## Engineering evidence

- Exact Decimal quantities, independent assets, and separate data/reconciliation states. Incomplete data cannot become a definitive match or mismatch.
- Immutable results, versioned reports and VOID/amount-only REPLACE corrections selected by economic and knowledge cuts.
- An offline viewer that neither mutates sources nor recomputes historical balances.
- A measured receipt-hash index improvement, with ingest cost and small-sample limits; no general end-to-end speedup claim.
- One fixed model compared with FIFO and rules. Historical model-minus-rules recall is **0 percentage points on test** and **−2.083 on challenge**. No additional model benefit was demonstrated in that synthetic experiment.
- Retained S5-F1/F2/F3 regressions and repairs for Decimal context, contradictory provenance and incomplete experiment scope.

Read the [claim–evidence table](docs/stage6/claim-evidence.md), [Turkish technical presentation](docs/stage6/technical-presentation-tr.md), [model contract](docs/model_contract.md), [correction semantics](docs/correction_semantics.md) and [source register](docs/problem_evidence.md). The [selection manifest](docs/stage6/evidence/selection-manifest.json) identifies unaltered small historical copies. The [historical evidence guide](docs/stage6/historical-evidence.md) identifies separate full archives by filename/hash; no hosted URL is invented.

## CI status and limits

The [prepared workflow](.github/workflows/release.yml) targets Ubuntu Python 3.12/3.14, separate AI/core checks and one full financial gate. Official actions use verified full commit SHAs and `contents: read` permissions.

**GitHub execution: NOT_RUN.** No repository creation, push, dispatch, release/tag or PyPI upload occurred. Prepared targets are not passing CI results; there is no success badge. Actual local results accompany the separate Stage 6.1 review evidence and every portable verifier run. See [CI scope and references](docs/stage6/ci.md).

The common Python minimum is 3.12 because pinned NumPy/SciPy require it; this is not a tested-all-versions/OS claim. No new UI, live integration, automatic payment/correction, heavy benchmark or main holdout rerun is included.
