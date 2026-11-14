# Stage 10.1 reader decisions

1. Keep the auth v1 scope, operator anchor, producer, runtime and schema unchanged.
   S10-F1 is a readback consistency defect. Verification inspects the existing
   signed bytes and immutable rows; it never invokes admission or reconciliation.
2. Derive operation coverage from the fixed experiment operation kinds and verified
   snapshot lines, then require the exact ordered new-attempt inventory. A partial
   first operation, revoked-prefix replay and permanent block have separate rules.
   Actual post-commit ACK loss has one durable SQL attempt and no sender response.
3. Bind each response to its attempt, current decision, original effect decision,
   physical receipt and stored core result. Check exact JSON types, including bool
   versus integer IDs, plus the key/endorsement and effective policy links.
4. Validate primary and unique keys before indexing every retained SQL table.
   Compare SQL inventories by identity rather than row order; response sequence and
   process observation order remain semantic. Require append-only transitions and
   the fixed fresh-database boundaries, including policy rotation and saved runs.
5. Compare the real policy-race RESULT body with the represented operation. Keep
   SIGKILL/UNKNOWN semantics: a killed worker must not invent a RESULT.
6. Preserve the historical 0.7.1 test anchor. Bind 0.8.0 separately to retain all
   540 old IDs and old assertion ASTs. Two current-release metadata exceptions are
   reversible and documented. No dependency, format or scope version changes.
7. Keep execution records outside source. Preserve failed intermediate runs;
   include actual final CI artifact archives so extracted JSON can be byte-bound.

## Boundaries

This is a finite synthetic experiment reader, not certification of a publisher,
financial truth, clocks, malicious database owners or power-loss durability. The
independent review's historical year-0001 timestamp overflow remains out of scope;
`model.py` is unchanged. The frozen main experiment is not regenerated, trained or
holdout-evaluated. Its model-minus-rules history remains 0 percentage points on test
and −2.083 percentage points on challenge.
