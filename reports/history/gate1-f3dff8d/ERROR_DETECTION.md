# Error detection and finite property evidence

All records and error labels in this report are **FULLY_SYNTHETIC**. They are not Treasury or SEC observations, and none measure real institutional precision or recall. The public-data report is separate.

## Observed result

The final finite run completed **264 contract cases in 25.58 seconds**, with zero contract disagreements and zero skips. Ten new harness tests passed. The 264 cases are an experiment inventory, not 264 additional unittest identities and not a replacement for the protected 875-test suite.

Cases cover seeds 11, 29 and 47, each in all four precision/custody cells: precision 0 or 2 and platform or external customer custody. A separate asset at precision 8 includes a one-unit balance and zero openings. The two-factor design covers its four possible pairs completely; it makes no claim to cover all application combinations. Generated amounts are integer units with bounded positive deposits, withdrawals and transfers. Labels and expectations are never passed to Store.ingest or reconcile.

An independent integer formula supplies investor balances and custody roll-forward. It does not import application Decimal, canonicalization, normalization, demo, or oracle helpers. Explicit contract expectations check A investor verdicts and B customer-liability verdicts. The engine is exercised through real SQLite stores and real reconciliation. The harness does reuse its own independent integer world generator across input and oracle construction; it is not an independently sourced institutional ground truth.

## Classification universe and denominators

An alert is any initial COIN B outcome other than MATCHED. A positive label is a deliberately injected data-integrity, missingness or quantity discrepancy. Exact redelivery, order changes, a repaired higher report version and boundary-preserving transformations are negative labels. Later correction states and immutable-history checks are correctness checks, not extra confusion-matrix rows. The hidden same-count event-reference substitution preserves economics and count but is labelled an identity-integrity anomaly. Its non-detection is an explicit known model boundary.

| Scope | TP | FP | TN | FN | Precision | Recall | Specificity | FPR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 264 distinct initial case observations | 132 | 0 | 120 | 12 | 100% | 91.67% | 100% | 0% |

The twelve false negatives are all same-count reference substitutions. They do not change the financial balance, so the observed MATCHED verdict is not an arithmetic error. They show that count manifests cannot authenticate which events should have been delivered. No false arithmetic MATCHED or false financial MISMATCH was observed within the registered cases. There is no demonstrated detection rate for natural failures or for unknown SEC/Treasury errors.

## Family results

An injected family below is compared with the same twelve existing clean controls. Those shared controls were not rerun or added to the global 264 observations. Consequently these family rows must not be summed. A dash means the metric denominator is zero.

| Family | New cases | Shared clean controls | TP | FP | TN | FN | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| clean | 12 | 0 | 0 | 0 | 12 | 0 | — | — |
| cross_asset_error | 12 | 12 | 12 | 0 | 12 | 0 | 100.00% | 100.00% |
| delivery_permutation | 12 | 0 | 0 | 0 | 12 | 0 | — | — |
| exact_redelivery | 12 | 0 | 0 | 0 | 12 | 0 | — | — |
| future_exclusion | 12 | 0 | 0 | 0 | 12 | 0 | — | — |
| invalid_negative | 12 | 12 | 12 | 0 | 12 | 0 | 100.00% | 100.00% |
| invalid_precision | 12 | 12 | 12 | 0 | 12 | 0 | 100.00% | 100.00% |
| invalid_unknown_asset | 12 | 12 | 12 | 0 | 12 | 0 | 100.00% | 100.00% |
| invalid_zero | 12 | 12 | 12 | 0 | 12 | 0 | 100.00% | 100.00% |
| late_state_machine | 12 | 12 | 12 | 0 | 12 | 0 | 100.00% | 100.00% |
| missing_custody | 12 | 12 | 12 | 0 | 12 | 0 | 100.00% | 100.00% |
| missing_event | 12 | 12 | 12 | 0 | 12 | 0 | 100.00% | 100.00% |
| newer_revision | 12 | 0 | 0 | 0 | 12 | 0 | — | — |
| offset_equivalence | 12 | 0 | 0 | 0 | 12 | 0 | — | — |
| reciprocal_transfer | 12 | 0 | 0 | 0 | 12 | 0 | — | — |
| replace_state_machine | 12 | 0 | 0 | 0 | 12 | 0 | — | — |
| same_count_substitution | 12 | 12 | 0 | 0 | 12 | 12 | — | 0.00% |
| same_version_conflict | 12 | 12 | 12 | 0 | 12 | 0 | 100.00% | 100.00% |
| split_merge | 12 | 0 | 0 | 0 | 12 | 0 | — | — |
| stale_report | 12 | 12 | 12 | 0 | 12 | 0 | 100.00% | 100.00% |
| void_state_machine | 12 | 0 | 0 | 0 | 12 | 0 | — | — |
| wrong_amount | 12 | 12 | 12 | 0 | 12 | 0 | 100.00% | 100.00% |

Every family has retained exact input files, SHA-256, seed/factor, intake counts, expected/observed result, duration and run identity. The final run retains all 264 initial and 36 later full financial payloads; their SHA-256, byte counts and run identities were checked against the case ledger. Evidence coverage for these registered case inputs is 100%; that is file coverage, not universal behavior coverage. Initial execution latency includes ingestion and evaluation. Detection latency as a separate operational metric was **NOT_MEASURED**. There is no clock or processing-SLA inference.

## Uncertainty and dependencies

The prespecified bootstrap resamples twelve complete seed/factor groups 2,000 times using seed 4391, retaining all dependent family transformations together. The resulting empirical 95% percentile intervals are precision [100%,100%], recall [91.67%,91.67%], specificity [100%,100%] and FPR [0%,0%]. These intervals are degenerate because every group has the same deliberate error-family composition and outcomes. They do not establish zero risk or a population confidence interval. Some boundary values repeat across seeds; neither rows nor all groups are independent natural error draws. No institutional population inference is justified.

## Mutation experiment and follow-up

The fixed initial mutation experiment ran four test-owned in-memory changes in genuine production paths, with a passing unmutated control for each. It killed three and preserved one survivor; the fixed-suite mutation result remains **3/4 (75%)**. No production file was edited.

| Mutation | Original witness | Observed outcome |
|---|---|---|
| Force every data state to COMPLETE | Missing event with complete declared count | KILLED: classification contradiction |
| Suppress quarantine taints | Invalid zero replaces a valid event | SURVIVED: manifest shortfall independently blocks success |
| Suppress manifest checks | Missing event | KILLED: classification contradiction |
| Suppress correction resolution | REPLACE state-machine transition | KILLED: balance and verdict disagreement |

The survivor prompted a separately preregistered follow-up: retain all valid events and their complete count, then add one invalid zero-amount event. The unmodified engine returned INCOMPLETE/NOT_EVALUATED. Suppressing quarantine returned a definitive MATCHED and failed the independent status assertion. The new witness killed that mutation. This is a test-strength improvement and a diagnostic mutant RED/reference GREEN result, not a production bug repair. The original survivor is retained and is not retroactively reclassified.

## State-machine and metamorphic boundaries

The registered state machines observe late delivery, VOID, and REPLACE: earlier saved runs and earlier knowledge cuts stay unchanged; a late event resolves incompleteness; corrections change the ledger independently of old reports. Delivery permutation and exact replay preserve economics; split/merge updates the declared event count; reciprocal transfers preserve total custody; an explicitly future event is excluded; an equivalent timezone offset preserves meaning. Arbitrary event reorderings are not assumed valid. The extra asset tests asset isolation, including opposite custody discrepancies that must not net across assets.

Full arbitrary correction graphs, conflict state machines beyond the listed controls, signatures, multiprocess serial/parallel equivalence, JSON parser fuzzing, shrink search, unbounded distributions, real-world labels and operational detection latency remain outside this module. No automatic shrink was claimed. Every original witness is small and retained, including false negatives. Existing suites and other validation modules provide separate evidence where executed.

## Reproduction and evidence

From the repository root:

```sh
.venv/bin/python -B -m validation_lab.properties --output /workspace/validation-evidence/properties-new
.venv/bin/python -B -m validation_lab.properties --quarantine-followup --output /workspace/validation-evidence/quarantine-followup-new
.venv/bin/python -B -m unittest discover -s validation_tests -p test_properties.py -v
```

Outputs must not exist. `--smoke` uses only seed 11, with all four factor cells and all 22 families; it does not claim three-seed coverage. No network is used. Each full run has a 300-second declared budget with a 280-second loop guard; the final run retained 300 full financial JSON payloads plus 264 exact input files and temporary databases are deleted after each bounded case. An external process timeout is recommended for automation.

Canonical raw evidence is retained outside Git under `/workspace/validation-evidence/properties/run-004/`: `preregistered.json`, `source-properties.py` (hash-matched to the registration), `inputs/`, `financial-outputs/`, `cases.jsonl`, `mutations.json`, and `summary.json`. The additional witness is in `quarantine-followup-004/`. `acceptance-repair-green.log` contains ten executed tests. Earlier `run-001/`, `run-002/`, `run-003/` and their follow-ups remain retained. Run 002 strengthened investor-side assertions and empty-seed rejection. Run 003 added complete before/after financial payload retention. Final run 004 verified repairs to two independently discovered research-harness acceptance defects, described below. These superseded attempts are not independent replications and do not increase the sample size. Source hashes distinguish the attempts. Run 001 has a source hash but no full standalone source snapshot; runs 002–004 retain source snapshots. Runs 003 and 004 retain complete financial payloads; only run 004 is used for final totals.

No critical production defect was found by these cases. This report supports correctness only within the finite synthetic contract population and documents a known detection boundary. It provides no guarantee against every possible failure.

## Research-harness acceptance defects and exact regression evidence

Independent audit found that replacing the executed family roster with an empty tuple produced PASS with zero cases, while duplicate family names produced duplicate identities and overwritten input names. This was a false-success defect in the new validation harness, not the financial engine. The repair pins the reviewed 22-family/four-factor roster hashes, rejects empty, duplicate and partial family/factor rosters, and requires exact expected/executed unique case-ID equality before PASS. Final `scope_acceptance` records all 264 unique identities.

The audit also showed that a failed unmutated control could be miscounted as a mutation kill. Failed controls now produce INVALID_CONTROL, cannot count as killed, and make overall mutation-control acceptance fail. Four named baseline controls are required. The intentionally surviving, properly controlled quarantine mutant remains a survivor in the fixed mutation experiment.

The exact same regression file was executed before and after the repair: SHA-256 `5830382900962b1513e690c88000aa510e26093c7a9d3de7fc2740dd869b0661`. RED: ten test methods, seven failing subcases, exit 1 (`acceptance-repair-red.log`). GREEN: ten tests, zero failures/errors/skips, exit 0 (`acceptance-repair-green.log`). The prior harness source is retained in `run-003/source-properties.py`; repaired source and the final 264-case run are in `run-004/`. No historical test or production source was changed.
