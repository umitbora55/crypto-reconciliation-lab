# Captured decision and attempt position consistency

S13-F1 concerns internal consistency of the portable captured inventory. It is
not a financial calculation error, signature failure or bypass of the original
external execution selector. Modified input remains rejected with that original
selector. Renewed negative-fixture selectors are explicitly TEST-ONLY identities.

The genuine 0.10.1 `after-current-replay` capture has attempt 31 linked to decision
31. Both identify `(test-custodian:initial, 1)`; the attempt is `REPLAY`, the
decision is `CURRENT` at epoch 2, and the original acceptance epochs remain `[1]`.
The independent review changes only decision 31's stream to `nonexistent-stream`.
The context hash and TEST-ONLY selector are coherently rebound. The raw financial
run, receipts, records, counts and original acceptance epochs remain unchanged.

The existing historical fixture is byte-identical to the independent positive
pair. Applying that single change with independent standard-library JSON/SHA-256
fixture operations yields the exact independent negative context and pin:

| Input | SHA-256 |
| --- | --- |
| Original context | `818205dca3fbb63676d5af9e0d4db37d8431b22f14b925a71b16c8891a02c1d6` |
| Wrong-stream context | `17f2d06188a55da57ff2bf49c91e64b57353152e05acdbd6c89c7fb13a3ccb86` |
| Unchanged raw run | `14c675e3bdb3106451c069915db22095e9cacf26c1ab9e674b64d04754738dd0` |

The original selector is
`f9514f8cba20a5000b9fdbd1f299159f409e0e491662d9526aa6f243bcabd436`;
the negative TEST-ONLY selector is
`16719ee4fa9e6b061e76e133852ca76ccebc9e2c02994819525522abc8f097be`.

The repair belongs solely in `replay/validation.py`. After the existing capture
helper has checked row identities and reference existence, every captured
`auth_attempt_links` row resolves its decision and attempt. Their `stream_id`
and `sequence` must both match. A mismatch is `ERROR / REPLAY_INTEGRITY / 2`
before financial computation. No signature verification, re-admission, current
policy authorization, prefix reconstruction or database restore is introduced.

The finite new test file also changes decision 31 to sequence 2 in the same real
stream. That position already exists, so a mere target-existence check cannot
pass the regression. The stream and sequence rejection tests observe zero actual
engine calls; the original selector rejection remains. Three unchanged genuine
captures cover CURRENT replay, HISTORICAL replay and new delivery, preserving
literal acceptance epochs `[1]`, `[1]`, `[1, 2]` respectively with one real engine
call each. Existing numeric and trace-only DIVERGED tests remain unchanged.

Actual same-file RED/GREEN commands, interpreter/import origins, exits and hashes
are retained outside Git under `stage13_1-output/f1`. Independent review results
remain separate from these new executions. The repaired module does not change
the adapter, comparison, captured source bytes, auth runtime or financial rules.
