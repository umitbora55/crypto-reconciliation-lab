# Finite validation coverage matrix

Final execution binding: [coverage-results.json](../evidence/coverage-results.json) contains 3,797 individual records: 875 unchanged identities across four source/installed interpreter runs, 264 canonical properties and 33 supplementary resilience cases. Source/installed Python 3.12 and installed Python 3.14 passed; the original Python 3.14 source run has one diagnosed P2 test race. These are repeated executions of 875 unique old IDs, not 3,500 new tests. The final 67 new research unit tests passed in `setup/research-tests-final.log`; the earlier separate smoke passed in `integration-smoke/summary.json`. The prospective table below is retained as preregistration, not substituted for actual outcomes.

The independently pinned current release contains **875 test IDs across 94 protected files**. Static byte/scope preservation passed; this matrix does not claim those tests were executed by the inventory step. Exact IDs and prospective controls are in `contracts/validation-scope-v1.json`. New research tests live separately in `validation_tests/`.

The primary-family index below assigns each legacy ID exactly once for navigation. Tests often exercise several families; these counts are not assertion counts, percentages of all behavior, or proof that a family is complete. The mapping uses module ownership plus selected method-name cues; representative source contracts were inspected, but names alone do not prove oracle independence.

| Family | Primary legacy IDs | Positive control | Negative control | Boundary control | Initial execution status / remaining gap |
|---|---:|---|---|---|---|
| F01 Financial accounting | 20 | Literal balanced opening/deposit/withdrawal/transfer | One-unit report discrepancy | 18-place unit and cross-asset isolation | NOT_RUN_IN_INVENTORY; bind source/installed and independent property results. |
| F02 Temporal selection | 12 | Equivalent timezone representations | Late/future receipt excluded at old knowledge cut | Exact cut and same-time tie-break | NOT_RUN_IN_INVENTORY; DST/UTC tests are finite, not every timezone history. |
| F03 Corrections | 40 | Full VOID / amount-only REPLACE | Competing corrections | Target arrives after correction | NOT_RUN_IN_INVENTORY; no generalized/chained correction claim. |
| F04 Manifest/data quality | 53 | Correct count plus required scope | Missing/extra/invalid row | Same-count substitution limitation | NOT_RUN_IN_INVENTORY; count-only manifest cannot establish external completeness. |
| F05 Transaction/recovery | 112 | Commit and idempotent retry | Real SIGKILL before commit | Post-commit ACK loss; SQLITE_BUSY | NOT_RUN_IN_INVENTORY; no power-loss/distributed durability guarantee. |
| F06 Signature/authority | 95 | Valid signature and local scope | Wrong key/source/asset/kind | Rotation/revocation and original epoch | NOT_RUN_IN_INVENTORY; identity is a local operator trust decision. |
| F07 Provenance/context/replay | 198 | Exact two-file replay and external pin | Rehashed semantic answer/relationship corruption | >2^53 IDs; empty input; NOT_RECORDED | NOT_RUN_IN_INVENTORY; replay remains same-engine. |
| F08 Properties/mutation/protocol | 148 | Independent finite integer/literal oracle | Invariant-breaking mutant | Only semantically permissible permutation/split/merge | NOT_RUN_IN_INVENTORY; no unbounded fuzz completeness or new frozen ML results. |
| F09 Security/resources | 33 | Fresh paths and complete outputs | Symlink/sidecar collision | Receipt/row/byte/depth/deadline limit | NOT_RUN_IN_INVENTORY; finite resource limit is not scale success. |
| F10 Portability/package/gates | 164 | Wheel outside checkout with -I | Missing expected ID/file must fail | Core/full/auth and Python 3.12/3.14, OS separation | NOT_RUN_IN_INVENTORY; macOS arm64 unavailable; remote API denied. |
| **Total** | **875** | | | | **Static inventory only** |

Each prospective `Fxx-POSITIVE`, `Fxx-NEGATIVE`, `Fxx-BOUNDARY` slot carries feature, expected result, data class, seed, command, raw-evidence reference, repetition count, actual result, unexplained behavior and decision fields. The 30 slots are predeclared requirements, not 30 completed tests. Some requested compound behaviors require multiple concrete cases. Unfilled slots remain NOT_RUN/PARTIAL and must not be silently counted as passing.

## Cross-family representative IDs

- `test_reconciliation.ReconciliationTests.test_negative_balances_only_rejected_on_complete_economic_ledger`: financial verdict and completeness boundary.
- `test_reconciliation.ReconciliationTests.test_late_event_manifest_and_immutable_history`: knowledge cut, completeness and saved history.
- `test_corrections.CorrectionTests.test_atomic_net_avoids_half_group_negative`: correction atomicity and financial nonnegativity.
- `test_admission_recovery.RecoveryTests.test_three_precommit_real_kills_leave_no_half_effect`: finite process-interruption controls.
- `test_recorded_execution_processes.RecordedExecutionProcessTests.test_sigkill_after_commit_before_cli_ack_retries_durable_original`: durable effect versus response loss.
- `test_provenance_identity_transport.ProvenanceIdentityTransportTests.test_tampered_transport_identity_is_rejected_after_manifest_refresh`: exact identity beyond rehashed presentation.
- `test_execution_replay_comparison.ExecutionReplayComparisonTests.test_test_only_hash_only_comparison_mutant_is_killed`: comparator-sensitivity mutant, not a discovered production defect.
- `test_execution_replay_process.ExecutionReplayProcessTests.test_real_blocked_child_hits_deadline_is_killed_and_reaped`: child termination and cleanup.
- `test_release_packaging.ReleasePackagingTests.test_traversal_and_symlink_sdist_members_fail_before_extraction`: package extraction safety.

## Denominator and public-data boundaries

Legacy tests and new controlled generators are SYNTHETIC. Treasury direct aggregate identities, if downloaded and interpreted, are REAL_PUBLIC_DIRECT; adaptation to another model is REAL_PUBLIC_ADAPTED. Error-labelled changes to real rows are SEMI_SYNTHETIC_INJECTION. Unknown public financial events have no invented TP/FP label. SEC daily outstanding fails are not new daily failures or customer-custodian ground truth.

Public-data acquisition, baseline equivalence, detection, resilience and release gates have separate inventories and evidence files. A completed release suite cannot fill a missing Treasury equality, prove institutional cost savings, or make a narrower additive benchmark semantically equivalent to the full product. Financial reference equality, source test execution, installed test execution and historical CI are four distinct facts.

Required terminal exclusions: one million events NOT_RUN unless explicitly executed; month-scale soak NOT_RUN; inaccessible public files DATA_UNAVAILABLE; no real institutional transaction truth; no inferred compliance certification; no automatic superiority claim. See final report decisions and each run's exact evidence rather than treating this preregistration snapshot as a final overall PASS.
