# Stage 10.2 decisions

1. Derive persistent key coverage from the union of activated policy snapshots in
   epoch order, after their existing independent fixture/anchor checks. Keep each
   key's immutable source/public-key/fingerprint and first observed activation
   epoch. Neither a candidate key list nor an unactivated snapshot defines scope.
   Rotation changes policy status without rewriting historical first_epoch.
2. Require every endorsement's key in the same SQL cut, with matching source and
   fingerprint. Keep existing signed-claim diagnostics before this relation check.
3. Require identical stream ID sets across admission_streams, auth_streams and
   committed delivery_effects. Existing original CURRENT decision/endorsement
   checks then bind every owner and admission plan; orphan rows cannot bypass the
   effect traversal. Later conflicting plans and replacement signing keys do not
   replace the original owner/plan.
4. Compare new operation stream/owner IDs with new COMMITTED effect stream IDs
   minus the before-cut stream IDs. Preserve append-only relationships, real
   interrupted SQL cuts and UNKNOWN sender responses. Do not invent a response.
5. Keep all 564 old IDs and assertions. Three current-release metadata expressions
   in two old tests are the only exceptions. Retain BASELINE 0.7.1, PREVIOUS 0.8.0
   and a separately pinned 0.8.1 binding; additions remain relative to 472 tests.
6. Preserve previous failure evidence, distributions, contracts and source docs.
   Final execution/CI/archive proof is external to Git. No new runtime, dependency,
   schema, scope version or general database replay engine is introduced.

## Exclusions

The separately observed audit-ID boolean, policy-race sender label and historical
year-0001 timestamp overflow are not part of S10-F2. No repair is applied to them.
The synthetic finite experiment is not institutional identity or financial-truth
certification. The frozen main experiment is not regenerated, trained or evaluated
on holdout; its historical model-minus-rules results remain 0 percentage points on
test and −2.083 percentage points on challenge.
