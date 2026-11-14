# Reproduce signed admission locally

From the Stage 10 checkout (package 0.8.0), use Python 3.12 or later and a new
output directory. While its PR is draft, these additions are on the task branch:

```sh
python3 -m venv .venv-auth
.venv-auth/bin/python -m pip install '.[auth]'
.venv-auth/bin/python -m crypto_reconciliation_lab demo-source-auth --output auth-demo-new --seed 19
.venv-auth/bin/python -m crypto_reconciliation_lab verify-source-auth --bundle auth-demo-new --anchor demo-test-only
```

The explicit `demo-test-only` anchor uses public RFC test-vector keys and fixed
synthetic publisher identities. The verifier does not select its trust root from
the report. Do not use these public seeds for any real identity. Alternatively,
pass a separately selected local JSON file describing this test anchor. The
verifier covers the fixed experiment, not arbitrary institutional deployments.

The demo includes separate platform and custodian feeds, original signed bytes,
policy snapshots, SQL readback, real subprocess barriers and explicit financial
evaluations. A valid signature on the wrong custody amount still produces a
financial MISMATCH. Admission does not certify amounts or source-provided clocks.

For individual operations, first initialize an empty database with the existing
`init --db PATH --config CONFIG.json`, then select a local policy:

```sh
python -m crypto_reconciliation_lab auth-enable --db new.db --receiver TEST-ONLY:local-receiver --policy policy.json
python -m crypto_reconciliation_lab ingest-signed --db new.db --input platform.jsonl --envelope platform.dsse.json
python -m crypto_reconciliation_lab auth-status --db new.db
python -m crypto_reconciliation_lab auth-activate-policy --db new.db --policy policy-2.json --expected-epoch 1 --expected-hash PREVIOUS_POLICY_SHA256
```

The policy and envelope formats are defined in [signing](signing.md) and
[policy/replay](policy-replay.md). An activation must name the current epoch/hash;
stale updates fail. A protected database cannot be downgraded to unsigned mode.
An existing populated database remains legacy after explicit backed-up migration.

`ingest-signed` exits 0 after the complete authorized transport scope, 1 for a
denied/incomplete transport result and 2 for an application/configuration failure.
Its response preserves INVALID/CONFLICT core dispositions separately; transport
completion is not financial correctness. Run the existing explicit `reconcile`
command when a financial evaluation is wanted. Demo and verifier exit 0 only when
their required controls pass, otherwise 2. Without the auth extra, auth execution
fails with `AUTH_DEPENDENCY` before creating the demo output or opening a database.

Full release verification uses the existing gate with a fresh output per command:

```sh
python scripts/verify_release.py --profile full --financial --output release-full-new
python scripts/verify_release.py --profile core --output release-core-new
python scripts/verify_release.py --profile auth-only --output release-auth-new
```

Only the full Python 3.14 CI cell requests the 69-case financial matrix. Other
cells retain their explicit NOT_RUN matrix state. None of these commands trains
or evaluates the frozen main AI experiment.
