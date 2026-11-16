# Gate 2: observability, LAB identity references and bounded fuzz evidence

This is a dated Gate 2 addition to the preserved original [error-detection report](../ERROR_DETECTION.md). No original truth label, financial implementation, historical test, original report or canonical 264-case evidence was changed.

## Three separate populations

| Population | Observations | TP | FP | TN | FN | Interpretation |
|---|---:|---:|---:|---:|---:|---|
| Preserved baseline | 264 | 132 | 0 | 120 | 12 | Original FULLY_SYNTHETIC population; historical result, not rerun here |
| Additional LAB reference: paired clean/substitution cases | 24 | 12 | 0 | 12 | 0 | Twelve old clean inputs and twelve old substitution inputs, now supplied additional oracle-generated signed reference facts |
| New production-helper fuzz | 102 | — | — | — | — | Syntax/encoding/time/correction-normalization contract checks, not natural-error classification |

The broader identity-contract experiment contains **240 controls**, including those 24 paired observations. It is not a 240-observation confusion matrix. All 240 controls and 102 fuzz checks met their separately registered expected outcomes. Ten new unit tests passed. The full finite experiment took 0.738 seconds in this local environment; this is a bounded execution observation, not a performance comparison or SLA.

## Why the original twelve false negatives remain

Every original same-count reference substitution remains **NOT_IDENTIFIABLE_WITH_GIVEN_INPUTS**. Changing an observed event reference is visible as a different identifier, but the count-only manifest and matching amounts do not say which identifier the publisher intended. A legitimate-source history and an unauthorized-substitution history can produce the same received candidate and count/amount facts while having different identity-validity labels. A downstream verifier needs an additional independently trusted fact to distinguish those histories.

The enhanced experiment supplies such extra facts only as **LAB emulation**. Its test publisher, expected digest, key policy and original reference all come from this research generator. They are out-of-band relative to the candidate being checked, but are not institutionally independent. The original TP=132/FP=0/TN=120/FN=12 is unchanged. The enhanced 24-case matrix cannot be pooled with it or described as the financial application acquiring 100% recall. The production financial engine was not changed and was not rerun for these identity comparisons.

## Optional contract and trust boundary

The reviewed [identity-reference research contract](../../contracts/identity-reference-research-v1.json) binds publisher, dataset, partition, event day, balance cut and record kind. A manifest carries a complete ordered list of exact string event IDs and SHA-256 digests of each canonical full economic event record. Position, revision and key epoch are bounded positive integer strings. IDs larger than JavaScript’s exact integer range retain string identity; no float conversion occurs. Received-at timestamps belong to consumer knowledge and are deliberately excluded from the publisher economic-record digest.

The research signer uses the existing pinned cryptography 50.0.2 library for Ed25519. The signature covers a domain prefix plus the entire canonical manifest, including scope, order, revisions and epoch. SHA-256 collision resistance and Ed25519 security are assumptions of these standard primitives; finite tests do not prove them. Exactly one signature is allowed. Conflicting multi-signature envelopes are rejected rather than resolved by choosing a convenient signature.

The verifier requires caller-selected scope, current revision, predecessor digest, current manifest digest, active public key and epoch. These must not be selected from the candidate envelope. Same-revision conflicting content, stale revisions, retired keys and revoked keys are rejected under the supplied current context. A prior accepted decision is retained as historical bytes while a new check is refused after revocation; this case does not establish a durable concurrent registry or a real external revocation service.

All keys here are publicly reproducible test keys. Every successful result explicitly says `authority=LAB_TEST_ONLY`, `institutional_trust=NOT_PROVEN`, and `financial_reconciliation=NOT_PERFORMED`. The API rejects a context explicitly labelled self-issued; the `LAB_TEST_ONLY` marker itself cannot authenticate real provenance. A caller that fabricates both reference and supposed trust context has not established independent authority, regardless of matching hashes or valid test signatures. There is **no independently authenticated institutional event-reference source** in this experiment. Treasury/SEC aggregates do not supply native customer-custody event identities or publisher key authority.

## Registered identity control inventory

Each family executes once for each of twelve retained seed/factor groups (seeds 11,29,47; factors 0–3). Exact clean and substituted inputs are read from the original canonical artifacts and checked against pinned baseline summary/ledger hashes and individual input digests. These are finite correlated test groups, not independent draws from natural institutional errors.

| Named family | Cases | Expected outcome |
|---|---:|---|
| clean | 12 | MATCH |
| same_count_substitution | 12 | REFERENCE_MISMATCH |
| content_substitution | 12 | REFERENCE_MISMATCH |
| reordered_events | 12 | REFERENCE_MISMATCH |
| duplicate_candidate_id | 12 | ERROR |
| scope_hijack | 12 | ERROR |
| unknown_signing_key | 12 | ERROR |
| tampered_signature | 12 | ERROR |
| conflicting_signatures | 12 | ERROR |
| same_revision_conflict | 12 | ERROR |
| revision_upgrade | 12 | MATCH |
| stale_revision_replay | 12 | ERROR |
| key_rotation | 12 | MATCH |
| retired_key_new_request | 12 | ERROR |
| revoked_key_new_request | 12 | ERROR |
| unverified_self_issued_pin | 12 | ERROR |
| large_string_id_boundary | 12 | MATCH |
| large_adjacent_id_substitution | 12 | REFERENCE_MISMATCH |
| empty_reference | 12 | ERROR |
| previous_decision_after_revocation | 12 | HISTORICAL_DECISION_UNCHANGED |

## Additional data and operational cost

The paired clean/substitution checks each require an extra **896-byte signed manifest** for three events, plus the separately supplied public-key/scope/revision/epoch context. This size is an observation for these tiny test records; it is not a capacity estimate. Deployment would also need an authorized publisher, authenticated distribution of current snapshot and predecessor hashes, complete event enumeration, protected signing operations, rotation/revocation facts, durable acceptance history, and race-safe policy updates. Those data sources and operations do not exist merely because this research verifier accepts a test signature. Their financial cost and real operational burden are **NOT_MEASURED**.

## New bounded production-helper fuzz

The 102 invocations contain 34 named cases per seed and **58 distinct raw byte inputs**. Twelve grammar-generated JSON objects per seed vary bounded nested data and Unicode strings; 22 fixed boundaries repeat across seeds. Repeated fixed bytes are disclosed and are not additional independent robustness samples. Actual production helpers are called: `source_auth.crypto.strict_json`, `model.timestamp`, and `correction_model.normalize_correction`.

Controls include duplicate and escaped-duplicate JSON keys, invalid UTF-8, lone surrogates, NaN and overflowing exponent notation, empty/truncated JSON, nesting depths 32/33, 20,000/20,001 nodes, 65,536/65,537-byte limits, an exact 64-bit integer, timezone-equivalent UTC values, missing timezone and UTC underflow, valid original-event correction targets, self-reference and a correction-cycle edge. The signature/reference controls above provide separate conflict, revision and key-lifecycle coverage.

UTC underflow directly raised `OverflowError: date value out of range`; the declared direct-helper oracle expected rejection. This observation does not claim that every public CLI translates the exception into a particular structured error. Normalization rejects a correction-to-correction edge before graph traversal; no arbitrary graph or recursion-safety proof is claimed. This module adds no process-crash, multiwriter, SQL restore or distributed-registry experiment. Protected existing tests for those areas belong to the separately executed final regression evidence, not this 102-case scorecard.

Every exact input, hash, oracle and observed acceptance/rejection is retained. No unexpected fuzz outcome was observed, so automated shrinking was not run. Original bounded witnesses remain available. The zero disagreements describe this finite distribution only; no natural-error recall, population confidence interval, universal correctness or deployment readiness follows.

## Reproduction and retained evidence

```sh
.venv-validation/bin/python -B -m validation_lab.identity_reference --output /workspace/validation-gate2-evidence/identity-new --baseline /workspace/validation-evidence/properties/run-004
.venv-validation/bin/python -B -m unittest discover -s validation_tests -p test_identity_reference.py -v
```

`--smoke` uses seed 11 only, for 80 identity controls and 34 fuzz invocations; it does not rerun the original 264 cases. The original baseline artifacts must be present and must match the pins in the contract. Missing or changed baseline artifacts refuse execution rather than regenerate a new baseline. Output directories must be fresh. No network is used. The protocol was saved before execution and contains exact expected case IDs, code hash and contract hash.

Canonical evidence: `/workspace/validation-gate2-evidence/identity/run-002/`. `protocol.json`, `source-identity_reference.py`, `identity-cases.jsonl`, `fuzz-cases.jsonl`, `scorecards.json`, `summary.json`, and all case inputs are retained. A separate readback verified 732 identity evidence files and 102 fuzz inputs, including exact byte counts/hashes, and confirmed 240/102 unique expected/executed identities and the final source snapshot. The evidence directory includes raw envelopes, candidate content bytes encoded as Base64, public trust contexts, and retained historical decision bytes; it contains no institutional secret key.

Named report scorecards are [unchanged baseline](scorecards/identity-baseline-unchanged.json), [enhanced LAB references](scorecards/identity-enhanced-lab.json), and [new production-helper fuzz](scorecards/identity-production-fuzz.json). `identity/acceptance-002.json` in the external Gate 2 evidence root provides integration pointers. Unit-test stdout/stderr is retained as `identity/unit-tests-003.log`; experiment stdout/stderr is `identity/run-002.log`.

Per-claim conclusions: the finite identity-contract and helper checks are **SUPPORTED within LAB scope**; detection with genuine independent publisher facts is **NOT_PROVEN**; original substitution detectability is **NOT_IDENTIFIABLE_WITH_GIVEN_INPUTS**; institutional trust and impact are **NOT_PROVEN**. This sub-experiment supplies no independent reason to change the overall NOT_READY decision.

## Independent audit and value-oracle repair

Independent audit found that the first research helper used the actual returned value as its fallback oracle for four accepted boundary families. Their acceptance classifications were meaningful, but their reported returned-value equality was tautological. A test-owned decoder mutant returning `{"not_the_parsed_value": true}` for the exact retained depth-32 input still produced `value_equal=true`. This was a defect in the new research harness, not evidence of a production parser defect.

The repair supplies independently specified nested-zero, 19,999-zero-element list, integer-zero and normalized-correction/key expectations for the four affected families. Every expected acceptance now requires an explicit value oracle. All 54 accepted invocations in final run 002 passed returned-value checks; the 48 expected rejections report `value_equal=null` and `value_check=NOT_APPLICABLE_REJECTED`, and are assessed only for their rejection outcome. No target result is used to manufacture its own expected value.

The same regression file SHA-256 `78aefb0fca2a26dad2846d4ff29769b9700e6b6316d3caeb5df18324658ea3df` ran RED before the helper repair (one method, four failing subcases, exit 1) and GREEN afterward (same method, exit 0); all ten new unit tests then passed. Logs are `identity/oracle-repair-red.log`, `identity/oracle-repair-green.log` and `identity/unit-tests-003.log`. The independent original witness is retained under `audit/identity-fuzz-self-oracle-001/`. The exact depth-32 input SHA-256 is `4e04cac422d9ecd4a5f6221653eeb4eaf29077cf3f588cd36bf6dc8ead76971f`.

Final canonical evidence is run 002. Run 001, its original source snapshot and the audit RED remain retained as superseded evidence; they are not extra observations or erased failures. The 240/102 finite populations, separate 24-case enhanced matrix, all baseline labels, historical reports and protected production files remain unchanged.
