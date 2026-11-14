# S10-F2 regression record

The new `tests/test_source_auth_inventory.py` contains eleven fixed test identities
and twenty-eight evidence-only negative cases. Its expected accept/reject results
are literal; its mutation and manifest rebuilding helpers do not call the reader,
admission, financial normalizer or signer to derive an answer. Ordinary suites
produce the unchanged real auth demo once. For preserved input replay,
`SOURCE_AUTH_INVENTORY_BASELINE` selects the supplied independently reviewed bundle.

## Exact minimal witnesses

W1 removes only `P1-old` from the persistent `auth_keys` inventories in
`normal_replay`, keeping endorsement/policy/signature/receipt evidence intact.
W2 adds the correctly shaped `platform-demo:orphan` stream/owner pair after the
first operation, with no attempt, decision, effect, receipt or response for it.
Both mutations update the existing auth-status mirror and rebuild the byte manifest.

Our W1 and W2 report **and** manifest bytes exactly match the supplied independent
minimal overlays. In each case all 156 other bundle files remain byte-identical.
`stage10_2-output/red/independent-witness-binding.json` records this comparison;
independent-review claims and our own commands remain separate evidence.

## Same-file RED/GREEN boundary

Before any verifier or version change, actual source package 0.8.1 ran the three
selected tests: the real positive passed; W1 and W2 each failed solely because
`ValueError` was not raised. Actual result: **3 tests, 2 failures, 0 errors, exit 1**.
The verifier SHA was
`b899a51608614c384b3eab921e105d5816dbde0853dcdaeb0a65297d54235b82`.

The unchanged new test file is 9,642 bytes, SHA-256
`bf814f1cfc99cc9c5a46eaf7f0a5f683b3a9411c0f1473976ffc01b04e1c5fd9`.
The full eleven-test run on an immutable 0.8.1 source snapshot produced nine
rejection-expectation subcase failures and zero errors. Nineteen neighboring
mutations were already rejected. A separate real isolated installed 0.8.1 CLI
confirmed the same nine false acceptances and nineteen rejections; the positive
passed. The orchestration PASS there means successful reproduction of the known
false acceptances, not approval of the old verifier.

The same file and minimal command must pass after repair. Exact RED and final
GREEN argv/cwd/import paths, versions, hashes, stdout/stderr, individual CLI exits
and final source/installed byte comparisons are external under `stage10_2-output`.
This source document does not predeclare later package or CI gates as successful.

## Bounded neighboring cases

The catalogue covers missing referenced, unused-but-policy-required and all keys;
first-activation epoch retention through rotation/resume; persistent key identity;
correctly shaped orphan streams and wrong source/receiver/configuration/plan;
missing stream/owner tables; and isolated before/after/final/interrupted/status
cuts. Valid SQL row permutations and harmless extra explanatory information pass.
Positive complete demo coverage preserves partial/resume, historical revoked replay,
permanent BLOCKED, policy-race denial, invalid amount and signed custody MISMATCH.

Previous R1–R6, the 109-case catalogue, sixteen SQL boundary subcases, and the
existing denial-stimulus tests are retained unchanged. No test repairs the separate
observed audit-bool, sender-label or historical timestamp behavior in this task.

## Reproduction tooling

`run_inventory_regressions.py` records the same test file before/after and aborts
an unchanged-source claim if its verifier changes during a run.
`run_inventory_cli.py` drives the public mutation catalogue through real source or
isolated installed CLI processes, recording each application exit and semantic
rejection reason, not only the orchestration process exit. Both task-owned helpers
are included with the external review evidence; neither is application runtime code.
