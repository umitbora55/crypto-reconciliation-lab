# Technical validation

This program validates finite laboratory behavior of `crypto-reconciliation-lab` at accepted application commit `b48021273405128c67e2969fd4b46f8d7e876a99`. Package **0.11.1**, financial rule **stage2-v2** and SQLite schema **6** are unchanged. New research code, tests and reports are separate from the protected production package and its 875-test release contract. The source branch is `validation/real-world-evidence-v1`; exact final publication identity belongs to the external handoff and evidence manifest.

## Evidence status at integration

| Gate | Actual observed result | Evidence directory under `/workspace/validation-evidence/` |
|---|---|---|
| Protected source scope | PASS: all 875 expected IDs and 94 protected files match their pinned hashes | `inventory/test-scope-preflight.json` |
| Historical financial reference | PASS: exact 70,721-byte reference hash and complete 373-file declared scope | `inventory/financial-reference-preflight.json` |
| Python 3.12.14 full source suite | PASS: expected = discovered = executed unique IDs = 875; zero failures, errors, skips, expected failures or unexpected successes | `release-full-py312/source_tests.json` |
| Python 3.12.14 isolated installed suite | PASS: expected = discovered = executed unique IDs = 875; zero failures, errors, skips, expected failures or unexpected successes | `release-full-py312/installed_tests.json` |
| Python 3.12 full release gate | PASS, exit 0; sdist-to-wheel build, source/installed origins, profile checks and recorded demonstrations completed | `release-full-py312/verification.json` |
| Python 3.12 financial matrix | PASS: 69 cases / 162 evaluations; all 325 matrix reports equal the fixed reference; Stage 1/2 reproduction checks cover the other 12 + 36 files | `release-full-py312/verification.json` |
| Python 3.14.10 full source suite | **FAILED**: 875 executed, one assertion failure, zero errors/skips/xfails; a protected test observation-barrier race was diagnosed | `release-full-py314/source_tests.json` |
| Python 3.14 original full gate | ERROR, exit 1 after source failure; its subsequent installed/full operations were not executed by that gate | `release-full-py314/verification.json` |
| Python 3.14 supplemental isolated installed suite | PASS: 875 unique installed identities; 346.670 seconds in the supplemental gate, separate from the failed source gate | `installed-py314/verification.json` |
| Python 3.14 core profile | PASS, exit 0; optional AI/auth absent, installed finite checks completed; full suite and financial matrix NOT_RUN in this profile | `core-py314/verification.json` |
| Python 3.14 auth-only profile | PASS, exit 0; pinned auth available and AI absent; full suite and financial matrix NOT_RUN in this profile | `auth-py314/verification.json` |
| Canonical finite properties | PASS: 264 cases / 12 seed-factor groups / 22 families; zero contract disagreements/skips | `properties/run-004/summary.json` |
| Supplementary resilience | PASS: 33 explicitly inventoried checks | `resilience/run-001/summary.json` |
| Official real-source acquisition | DATA_UNAVAILABLE: 19 bounded requests failed at the proxy tunnel; zero real financial equalities verified | `public-data/attempt-01/`, `public-data/bis-attempt-01/` |
| Remote historical/current GitHub CI | UNVERIFIED_REMOTE: GitHub API denied; local results do not establish remote CI | `inventory/*ci.command.json` and stderr |
| Comparative timing | PARTIAL:45 completed trials at100/1k/10k passed;100k production timed out at60.065s; remaining100k NOT_RUN | `benchmark/`; final figures belong in `BASELINE_COMPARISON.md` |

A passing Python 3.12 run does not erase the failed Python 3.14 source run. A later diagnostic or installed run is a separate observation, not a retroactive conversion of failure to PASS. Research-harness case counts, protected unittest identities, profile CLI cases and matrix evaluations are different denominators and must not be added into one inflated test total.

## Environment and reproducible commands

The measured host is Linux x86-64, kernel `6.18.57`, glibc 2.41, with five reported logical CPUs. The primary runtime is Python 3.12.14 and SQLite 3.53.1; the additional runtime is Python 3.14.10. Pinned build requirements are in `requirements-build.txt`; full AI and auth constraints remain the unchanged repository files. Import origins and exact dependency inventories are captured in each gate. The core runtime has no third-party dependency requirement.

The program's declared temporary disk ceiling is 5 GiB. The benchmark uses one worker at a time, explicit child CPU/address-space limits and bounded timeouts. This is an execution budget, not a claimed production capacity. Host/storage contention and unknown physical disk type remain measurement limitations; do not interpret these results as isolated dedicated-machine SLA measurements.

Executed full commands, from the repository root:

```sh
.venv-validation/bin/python -B scripts/verify_release.py --profile full --financial --output /workspace/validation-evidence/release-full-py312
.venv-validation314/bin/python -B scripts/verify_release.py --profile full --output /workspace/validation-evidence/release-full-py314
```

The exact interpreter paths, argv and cwd recorded in each `verification.json` are authoritative if a local alias differs. The Python-3.14 supplemental installed check has its own command evidence and is not a continuation that hides the original failure. Core/auth-only checks use the existing verifier with `--profile core` and `--profile auth-only`, fresh output directories, and the previously built matching sdist/wheel. The external setup logs retain their actual invocations and exits.

Research entry points are:

```sh
python -B -m unittest discover -s validation_tests -v
python -B -m validation_lab.properties --output /absolute/new/properties
python -B -m validation_lab.properties --quarantine-followup --output /absolute/new/quarantine-followup
python -B -m validation_lab.resilience --output /absolute/new/resilience
python -B scripts/validation/run_validation.py --mode smoke --no-network --output /absolute/new/smoke
```

The new research tests are separate from the packaged protected `tests/` directory. The integration smoke executed 65 research tests. After the final coverage-report repair, a separate combined run executed 67 methods: public-data 34, properties 10, benchmark 10, resilience 4, runner 7 and coverage 2; all passed. The smoke's 88-case one-seed property smoke, 33 resilience probes and 15 timed 100-event benchmark trials also passed. This separate smoke is excluded from canonical benchmark estimates and the 264-case detection denominator. Evidence: integration-smoke/summary.json and commands/.

## Correctness, detection and mutation boundaries

The canonical property experiment uses seeds 11, 29 and 47, crossed with two precisions and two custody locations. It checks real Store ingestion/reconciliation against independent integer balances and explicit status expectations. A second asset has eight-place precision and a one-unit boundary. Inputs, 264 initial financial payloads and 36 later state-machine payloads are retained and hashed. Financial assertions do not invoke the production calculation as their expected-value oracle.

Initial B-finding classifications give TP 132, FP 0, TN 120 and FN 12. All twelve missed injections are same-count reference substitutions that preserve arithmetic. The detection recall is 91.67% for this deliberately constructed universe, not a natural-error or institutional population estimate. Correct arithmetic and detection completeness are distinct. Detailed denominators, shared controls and degenerate group-bootstrap intervals are in [ERROR_DETECTION.md](ERROR_DETECTION.md).

Four fixed in-memory production-path mutants had passing baseline controls: three were killed and one quarantine mutant survived because a separate missing-count guard masked it. The fixed result remains 3/4. A separately preregistered witness subsequently killed the surviving mutant; it does not rewrite the original denominator or establish a production defect. No frozen ML generation, training or final holdout evaluation was performed.

## Python 3.14 failure and diagnosis

The exact failed identity is `test_lab_contract_validation.ProtocolValidationTests.test_seen_failure_survives_later_truncated_result`. Its separate RSS callback can read a child failure and release truncation before the watchdog's correctness sampler has observed that failure. The test then expects FAILED although the sampler can truthfully report UNKNOWN. It did not demonstrate a false financial PASSED result.

Three exact unchanged-test reruns passed. Two deterministic test-owned schedules separately confirmed the distinction between an RSS-only read and a watchdog correctness read. This is recorded as **VAL-P2-TEST-BARRIER-RACE**, open because protected historical test bytes remain unchanged. A successful rerun is diagnostic evidence, not a repair. See [RESILIENCE_AND_SECURITY.md](RESILIENCE_AND_SECURITY.md) and `resilience/py314-diagnosis/` for exact controls, commands, outputs and file-preservation hashes.

## Evidence acceptance repairs

Independent review found and repaired defects in the new research harness: missing acquisition inventories, empty/duplicate property scopes, invalid mutation baselines counted as kills, benchmark event-count metadata mismatches, PARTIAL results treated as successful commands, and same-count substituted outer-gate case rosters. Repairs affect only new research code and tests. The outer gate now pins the reviewed roster bytes and checks unique complete identities rather than a child's PASS string or count alone.

One independent audit probe used a fixed output name and was rerun against repaired code, overwriting its initial on-disk RED file. The overwritten GREEN was preserved; the original raw RED file is unavailable. A clearly labelled external reconstruction reverses only the roster-guard patch, then executes the exact unchanged probe against the reconstructed and final code. It is **RECONSTRUCTED_BEFORE_GUARD**, not an untouched historical RED. A properties follow-up audit transcript was also restored from captured tool output after a fixed-name overwrite; use the properties agent's independently retained same-test RED/GREEN and source snapshots as primary evidence. `audit/provenance-errors.json` and `audit/runner-review-01/manifest.final.json` disclose these limitations.

## Untested scope and CI distinction

macOS arm64, real institutional transactions, physical power loss, physical filesystem exhaustion, million-event workloads, months-long soak, independent dependency-advisory clearance and valid end-to-end maximum-size replay were NOT_RUN. Component checks accepting 10,000 typed receipt rows or 50,000 typed captured rows are not equivalent to a complete valid replay at those sizes. Default 30-second timeout inspection is distinct from the executed one-second blocked-child termination witness.

README references historical main CI run 43741674664 and commit `b2df4f13eb7e2fc6b048f17eaaa24f02bf0bd29e`. Its provenance remains a repository claim because this task's direct API retrieval was denied. Current local gate reports bind their actual bytes/imports and commands; they are not a new GitHub CI result. Formal final decisions must remain separate for correctness, real data, detection, comparisons, resilience and institutional impact.

## Publication-time CI observation

A later public-web fallback retrieved historical run [43741674664](https://github.com/umitbora55/crypto-reconciliation-lab/actions/runs/43741674664): the GitHub page shows Success for `b2df4f1`, 11m29s and four artifacts. Artifact bytes and authenticated job logs remain unverified. The initial research commit `f8fe98a` was pushed normally; its public workflow run43925469151 was In progress at this observation. API/GraphQL requests still return Forbidden, so draft PR creation failed. Final later observations belong to the external `VALIDATION_HANDOFF.md`, not a claim that the earlier API requests succeeded. Raw page bytes and hashes: `inventory/web-ci-observations.json`.
