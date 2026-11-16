# Reproduce the finite validation program

For the dated Gate2 work, use [GATE2_REPRODUCE.md](GATE2_REPRODUCE.md).
The workflow below remains the original Gate1 research program; its catalogs,
baseline populations and historical limitations are not silently relabelled.

Use the existing checkout, Python 3.12 or newer and a fresh output directory outside the checkout. Runtime research checks use the standard library. Read `AGENTS.md`; the 16 November 2026 validation request authorizes this separate research tree. Do not create a worktree just for a cloud task, overwrite earlier evidence, run the frozen ML experiment, or treat a synthetic case as a real institution record.

## Two-command quick smoke

From the project root:

```sh
python3 -B -m unittest discover -s validation_tests -v
NO_NETWORK=1 python3 -B scripts/validation/run_validation.py --mode smoke --no-network --output /tmp/crl-smoke-NEW
```

Replace `NEW` with an unused name. The smoke runs all research acceptance tests, 88 property cases (one seed and four factor cells), 33 bounded resilience probes, and five paired 100-event trials for each of three methods. A smoke is not the three-seed population, large-scale verification or a complete release gate. The outer runner rejects missing/substituted case rosters and PARTIAL child summaries even when a child returns zero. Exact commands, stdout, stderr, exits, protocol and file manifest are retained below the output path.

## Full bounded research program

```sh
NO_NETWORK=1 python3 -B scripts/validation/run_validation.py --mode full --no-network --output /tmp/crl-research-NEW
```

This schedules 264 property cases, 33 resilience probes and five paired repetitions at 100, 1,000, 10,000 and, only within the budget, 100,000 events. It does not run the 875-test application release suite. A benchmark stops larger profiles after a failed smaller profile; censored/time-limited trials remain PARTIAL/NOT_RUN. The benchmark has one active worker, a 360-second total budget, 60-second per-child wall/CPU limits, 1 GiB child address-space budget and 1 GiB retained-data budget. The outer run monitors a 5 GiB logical output budget. Temporary-file accounting is sampled, not a filesystem quota. Run timing trials without other task workloads; OS caches are not flushed. Do not interpret these runs as cold-disk, monetary or institutional measurements.

## Optional public acquisition

Network fetch is deliberately separate from tests and disabled in the default research workflow:

```sh
python3 -B scripts/validation/fetch_public_data.py --fetch --output /tmp/crl-public-NEW
python3 -B scripts/validation/fetch_public_data.py --no-network --output /tmp/crl-public-NEW
python3 -B -m validation_lab.public_data --source-root /tmp/crl-public-NEW --output /tmp/crl-public-validation-NEW.json
```

The explicit catalog contains 19 official requests: documentation/policy pages, fixed Treasury periods, two SEC half-month ZIP candidates and two BIS reference pages. Maximum response 32 MiB, total 512 MiB, bounded timeout, no automatic retry, TLS verification on. Review successful official documentation, schema and usage terms before approving an economic field mapping or redistribution. Download success and hash equality are not financial validation. Public data not obtained or not semantically mapped remains `REAL_DATA_UNVERIFIED`.

The initial historical acquisition comprised a 17-request financial catalog plus a two-request references catalog. To verify those retained attempts, pass `--scope financial` or `--scope references` respectively to both acquisition verification and the offline validator. The verifier never infers the expected inventory from an untrusted result file. `--only` further narrows a caller-selected scope explicitly. `NO_NETWORK=1` prevents direct fetching before filesystem/network effects.

Raw official data is excluded from Git unless its reuse permission has been independently confirmed. The committed `data/sources/source-register.json` reports acquisition status and limitations, not invented hashes for missing bytes. Calendar gaps are not automatically missing deliveries; FTD balances are not new daily fails or individual error labels.

## Existing source/installed release gates

Keep research tests outside the protected `tests/` roster. Use a separate environment with the repository's exact optional pins:

```sh
python3 -m venv .venv-validation
.venv-validation/bin/python -m pip install -r requirements-build.txt -r requirements-auth.txt -r docs/stage5/ai_constraints.txt
.venv-validation/bin/python -B scripts/verify_release.py --profile full --financial --output /tmp/crl-release-NEW
```

The release verifier builds an allowlisted sdist, a wheel from that sdist, then validates source and isolated installed imports and exactly 875 original IDs. `--financial` runs the 69-case/162-evaluation matrix and compares the fixed 373-file reference. Package installation requires allowed package-network access, so `--with-release` cannot be combined with the research runner's `--no-network` flag. Small profile checks use `--profile core` and `--profile auth-only` and report the full suite as NOT_RUN. Reuse a validated `--source EXTRACTED_SDIST --wheel WHEEL` pair when only changing the profile.

When an earlier source suite fails, `scripts/validation/check_installed_suite.py --source EXTRACTED_SDIST --python ISOLATED_ENV/bin/python --output NEW` executes the unchanged strict installed-suite checks independently. It does not convert the earlier failed full gate into PASS. Preserve every failed attempt and the exact test identities; a passing focused repetition is not a repair of a race.

## Evidence and interpretation

The final `evidence/manifest.json` identifies the evidence archive layout and hashes. `reports/DECISION.json` separates correctness, real data, detection, runtime, cost, resilience, institutional impact and external-review readiness. The known count-manifest substitution false negatives must remain in detection denominators. Only the declared canonical property run contributes to final totals; earlier runs document harness changes and are not extra independent samples.

Some exploratory audit scripts in the external command directory originally used fixed output names. Their overwritten historical observations and reconstructed-before-fix proofs are explicitly disclosed; use the retained same-test RED/GREEN evidence and final pinned outer-gate controls. No self-signed manifest is an external trust authority.

Not performed unless a later report explicitly proves otherwise: private institutional validation, one million events, months-long soak, macOS arm64, physical disk/power failure, production penetration testing, live advisory vulnerability scan, frozen ML regeneration/training/holdout, paid infrastructure, main merge or release publication.
