# Five-minute saved-run provenance review

This is a local synthetic explanation of a saved result. It has no live
institutional connection, training step or final holdout evaluation. Use Python
3.12 or later, install the existing optional `auth` extra, and choose a new output
directory:

```sh
python3 -m venv .venv-provenance
.venv-provenance/bin/python -m pip install '.[auth]'
.venv-provenance/bin/python -m crypto_reconciliation_lab demo-provenance --output provenance-demo-new
```

1. **Read the result.** Open `provenance-demo-new/summary.md`, then
   `cases/clean/bundle/index.html` under that output directory. The first view
   shows the selected saved run, economic and knowledge cuts and financial
   findings. Follow a finding to its recorded report/event, raw input line and
   physical receipt candidates. All assets are local; no server is required.
2. **Separate export from verification.** A newly exported page is a capture
   view. It does not certify itself. Run the independent command below, which
   uses the TEST-ONLY fixture observation outside the bundle. A verifier result
   can be imported into the page as a separate record only when its manifest
   identity agrees. The sealed bundle is not edited to add a verified badge.
3. **Follow original authority.** Inspect the original committed effect,
   admission decision, endorsement, exact signed snapshot and policy epoch.
   The rotation example has more than three epochs. Original admission and the
   key's capture-head state are separate facts. Revocation does not rewrite a
   historical admission.
4. **Inspect the limits.** `signed_mismatch` preserves custody difference `+1`
   even with verified source evidence. `ambiguous` exposes all physical
   candidates, including a later delivery; `missing_snapshot` does not invent
   full signed bytes from a prefix; `legacy` remains unsigned. All successful
   cases still display run-creation authorization `NOT_RECORDED` and financial
   recomputation `NOT_PERFORMED`.
5. **Check a semantic rejection.** Verify `broken_protected_link` with its own
   external fixture expectations. It exits 2 for `PROTECTED_LINK` despite a
   coherent file manifest. The positive `clean` case must exit 0 in the same
   environment. Review actual per-case commands, exits and reason codes rather
   than treating a scenario name as an oracle.

```sh
.venv-provenance/bin/python -m crypto_reconciliation_lab verify-provenance --bundle provenance-demo-new/cases/clean/bundle --expectations provenance-demo-new/cases/clean/expectations.json
.venv-provenance/bin/python -m crypto_reconciliation_lab verify-provenance --bundle provenance-demo-new/cases/broken_protected_link/bundle --expectations provenance-demo-new/cases/broken_protected_link/expectations.json
```

`verify-provenance` exits 0 for `VERIFIED_FOR_CAPTURE`, 3 for `PARTIAL` and 2 for
`FAILED` or a controlled input/dependency error. An inconsistent protected link
has priority over missing material or ambiguous candidates. The demonstration
command exits 0 only when every declared small scenario has its expected result;
its intentionally partial/rejected examples are not application failures.

For an existing closed schema-5 database, export a single saved run without
mutation or migration:

```sh
.venv-provenance/bin/python -m crypto_reconciliation_lab export-provenance --db closed-copy.sqlite --run-id SAVED_RUN_ID --materials source-materials --output run-bundle-new
.venv-provenance/bin/python -m crypto_reconciliation_lab verify-provenance --bundle run-bundle-new --expectations operator-expectations.json
```

`source-materials/snapshots/<sha256>.jsonl` supplies original complete signed
files. Envelopes and policy bytes come from the captured database. Missing
snapshots remain missing. The operator expectations must come from a separately
trusted observation, not be generated from an untrusted bundle to make it pass.
The TEST-ONLY demonstration observer is not a general trust generator.

See the [contract](provenance-contract.md) for exact identities, finite limits and
scope; [trust and sources](trust-and-sources.md) explains which assurances the
model deliberately does not claim. Earlier financial and source-auth contracts
are unchanged.
