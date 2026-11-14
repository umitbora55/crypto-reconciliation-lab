# Source authorization experiment contract

This inventory was authored before the experiment implementation. It is a fixed
local synthetic design contract, independent of a candidate result. The canonical
contract is `contracts/source-auth-scope-v1.json`; an identical packaged resource
serves installed verification. Its 18 named families contain 33 fixed subcases.
Each required control has a typed literal expected value; extra descriptive
information cannot replace a required case, operation, decision or control.

## Inputs, trust and evidence

Two TEST-ONLY publishers independently sign finite files: platform P1 and
custodian C1. P1 owns all openings (including the external opening), events,
investor/platform reports and their manifests. C1 owns only external_custody
reports/manifests. The two files contain 26 and 4 financial records respectively.
Legacy and protected parity uses that same order and the same received_at values.
The literal expected balances are A: I1=7, I2=4, liability=11, platform=2, external=9;
B: I1=0.3, I2=0.2, liability=0.5, platform=0.05, external=0.45.
The deliberately false A custody report is 8; its COMPLETE/MISMATCH difference is
+1 while investor checks remain MATCHED. No production calculator supplies these
expectations. Signing does not certify a financial quantity or timestamp.

Each operation retains snapshot/envelope/policy bytes, its exact returned result,
and before/after SQL row readback. Every committed effect must link a receipt,
immutable authorization decision, historical key fingerprint, endorsement,
active policy epoch and source-owned immutable plan. Explicit reconciliation
outputs and paired legacy JSON/Markdown/run IDs are separate evidence.
The verifier starts with an operator-selected public-key/configuration anchor
from the fixed fixture; a candidate report cannot introduce a trusted key itself.
Signature verification consumes original payload bytes, scope is independently
extracted from the whole snapshot, and policy/receipt links are checked.

## Processes and mutation controls

The precommit and postcommit/ACK-loss cases launch a child process, observe its
named barrier and PID, send SIGKILL, join it and reopen SQLite before retry.
Precommit expects zero receipt/effect/decision; postcommit expects one intact
linked decision/receipt/effect and an UNKNOWN sender response, then exact replay.
A separate bounded policy race pauses after cryptographic preflight, activates
revocation through another connection, then releases the child. No stale-policy
receipt may appear. Timing is not evidence of reaching a barrier.

The semantic verifier must reject removal of a required family, removal of a
required decision together with its reference, same-count capability substitution,
wrong key/source/receipt linkage, DENIED expected with COMMITTED actual and PASS,
and a signed MISMATCH rewritten as MATCHED. Each mutation rehashes files. Harmless
extra information remains acceptable. Neither file hashes, control counts nor
passed=true flags establish these semantic properties.

The scope is process termination on one local SQLite database, not power loss,
disk failure, source certification, owner-resistant tamper proofing, distributed
consensus or a production PKI. The frozen main AI experiment is never invoked.

## Independent acceptance boundary

The reader uses its own bounded JSON parser, authority field/channel table and
literal DSSE PAE construction with the library public-key verifier. It does not
call admission, the policy normalizer, the financial normalizer or reconciliation.
Each case's initial policy is selected from the fixed operator fixture, including
its deliberately restricted grants; candidate policy text cannot authorize itself.
Every SQL effect has exactly one original CURRENT decision and receipt. Every
attempt has a decision, historical replay requires the older exact endorsement and
receipt plus a revoked current key, and decision epochs cannot go backwards.
Policy epoch 1 is tied to protected setup. Response decisions and original decisions
are checked separately against these immutable rows.

Financial files must equal saved SQL run payloads, run identities and explicit cuts.
Signed C1 custody source amounts 9/8 are checked in retained raw receipts. Six
finding identities, literal amounts and state axes remain independent expectations.
The clean paired comparison additionally checks exact core records, receipt order,
received_at values, saved runs, JSON and Markdown. Authorization IDs never enter
those financial bytes.

The same-count scope mutation is signed correctly and substitutes the known,
policy-granted ASSET_A correction tuple for one real tuple. It therefore tests
whole-file scope equality, rather than failing merely because an asset is unknown.

## Development verification

The actual focused command was `python -m unittest discover -s tests -p
 test_source_auth_experiment.py -v` using the task's isolated auth-only interpreter.
Its initial focused runs executed 24 tests with zero failures/errors/skips, exit 0.
The test-class fixture itself runs the bounded real three-worker experiment; its
negative cases rehash each modified bundle before independent verification.
Full source/installed, financial-reference and CI gates are separate release runs.

The first development run retained a verifier failure caused by using presentation
column names rather than physical SQL `core_receipt_id` / `payload_sha256` names.
The second retained a verifier failure caused by macOS temporary-path canonical
resolution (`/var` versus `/private/var`). Both were repaired in this new reader;
financial/runtime behavior and the fixed experiment inventory were not changed.
Later runs passed. Outside-Git `stage10-output/experiment/` retains these failures,
positive development reports, focused command logs and an execution journal.


## Independent denial-coverage repair

Independent follow-up review replaced the `bad_signature` input with an authentic,
authorized signature and kept the reported DENIED/empty SQL evidence. After
rehashing, the first reader incorrectly accepted that bundle. A denial response
alone did not establish that the required negative stimulus had been exercised.

One new regression preserves the previous 24 test methods and assertions. Its 20
subcases replace each malformed, unbound, unauthorized-scope or hijack request
with a valid authorized request while keeping the claimed denial. Before repair
all 20 failed (exit 1); the identical test then passed (exit 0). The reader now
independently proves each declared input defect, and authentic well-bound claims
can be denied only when their effective policy actually denies the key or exact
capability tuple. The denial audit must bind the exact bounded request identity.
Signer source must also equal every derived snapshot capability source.

A development attempt exposed that the new bounded audit identity had changed
from a bare digest to `{prefix_sha256, bytes}`; that failed attempt is retained.
After matching the current audit contract, all 25 experiment tests passed. Logs
are `denial-coverage-RED.log`, `denial-coverage-GREEN-01.log` (failed setup),
`denial-coverage-GREEN-02.log` and `focused-04.log` outside Git. This narrow
repair changes neither financial nor signed-admission runtime behavior.
