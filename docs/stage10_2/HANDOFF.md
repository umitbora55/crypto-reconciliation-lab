# Stage 10.2 source handoff

## Verified starting point

The task-owned worktree was clean on stage10/source-auth at
f7a8cecd10e0658553249a5d2f4e1eae7edab477, package 0.8.1 / stage2-v2 / schema 5.
Draft PR #2 was open and unmerged; main remained
c49f1a1752caf3083bedc8aa797e77023c3db7d4. The 212-file source snapshot and actual
final build-02 0.8.1 distributions/scope/review identities were preserved before
changes. Intermediate 0.8.1 distributions are not the maintenance baseline.

The supplied independent archive was verified: 2,312,736 bytes, SHA-256
fdaefc5d8eddeb55a145335b1e794ec1c5f74b432d15aef0983030577c461354;
all 235 inner payload hashes/sizes matched. Reviewer executions remain separate
from our actual commands. One initial intake helper expected the prior manifest
key `files`; the new manifest uses `members`. That setup error is retained and
was corrected before extraction; it is not semantic RED evidence.

## Implemented maintenance

Package 0.8.2 closes S10-F2 only: exact persistent keys from activated policy
history, endorsement-to-key binding, stream/owner coverage from original committed
effects and exact operation additions. Existing SQL cut checks cover before,
after, final and interruption states; auth_status remains the existing final
mirror. Original receipt/decision links, BLOCKED priority and historical replay
semantics remain unchanged. See [decisions.md](decisions.md).

Financial core/Store, auth runtime/policy/crypto, schema 5, source scope/producer,
recovery v2, historical v1 contracts, workflow and pins are unchanged. All 564 old
IDs/assertions remain; [release-metadata.md](release-metadata.md) records the three
reversible current-release expressions. The fixed new scope contains 575 test IDs:
564 preserved + 11 new; its 103 additions are relative to the 472-test baseline.

## Actual focused verification before sealing

The unchanged 0.8.1 verifier accepted the real positive and both minimal negative
witnesses. The same new regression file first ran 3 tests with 2 rejection
assertion failures, 0 errors, exit 1. Its full 11-test baseline run recorded 9
failing rejection subcases and no setup/import errors; other boundary mutations
were already rejected. The W1/W2 report and manifest bytes exactly match the
independent overlays; all 156 other files remain unchanged.

After the narrow patch, all 11 new tests passed. All 25 original experiment tests,
including established assertRaisesRegex diagnostic expectations and denial
stimulus checks, passed without old-test edits. Exact argv, source hashes,
provenance, stdout/stderr and exits are retained in stage10_2-output. The frozen
same-file RED/GREEN and real CLI records are described in
[regressions.md](regressions.md).

## Sealed-source delivery

Build from the sealed source, extract the sdist and build the wheel from that
extraction. Run full with the financial matrix, plus core and auth-only gates.
Exact expected/discovered/executed IDs, clean `-I` installed provenance, old
109-negative and 16-boundary closure, genuine old positives, 373-file equality,
final Git/CI artifact identity and clean archive readback belong in the external
stage10_2-output/HANDOFF.md and JSON evidence. This source document does not
predeclare those later checks as PASS; no final-CI result is committed back.

The next step after delivery is independent review of draft PR #2. Main merge,
force push, tags/releases/PyPI, frozen main generation/training/holdout, heavy
benchmarks and separate audit-bool/sender/timestamp fixes are NOT_RUN. Historical
model-minus-rules results remain 0 percentage points on test and −2.083 on challenge.
