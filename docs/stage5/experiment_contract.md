# Stage 5 experiment contract

Contract: **triage-experiment-v1**, design identity **triage-synthetic-2026-11-v1**.
This document is the first Stage 5 implementation artifact. Its byte hash, the
implementation/schema hashes, split roster, model/preprocessing and complete
holdout rankings must be frozen before final holdout truth is opened. Technical
repairs retain failed attempts and receive a different execution identity; results
never justify changing this design, labels, baselines or test membership.

## Question, unit and target

Does one regularized LogisticRegression rank unresolved-at-horizon units better
than FIFO and fixed rules in this synthetic experiment? Winning is not a delivery
gate. No institution distribution, SLA, financial loss, fraud, manual-intervention
requirement or calibrated real-world risk probability is asserted.

A unit is `(episode_id, asset, balance_at, as_of=T)`, with all original A/B finding
references for that asset. Counts stay separate by comparison; amounts never net
across comparisons or assets. All COMPLETE/MATCHED means NO_OPEN_FINDING, retained
with that exclusion reason. Every other valid state combination is OPEN. Low
scores never close, suppress or change a finding. One main T per episode is scored;
earlier observations are history only, not additional primary examples.

Common opening is 2026-11-10T00:00:00Z; balance_at is 2026-11-10T01:00:00Z;
T is 2026-11-11T00:00:00Z; H is 2026-11-12T00:00:00Z. H=T+24h is an experiment
assumption. Actual future received_at/resolution schedules extend beyond T, not a
reinterpretation of the old lab's one-to-four-hour cuts.

The independent evaluator assigns `unresolved_at_horizon`: 1 if any same-scope A/B
problem remains at H; 0 if all are COMPLETE/MATCHED; null if H is unobserved,
unidentifiable or out of scope. A resolved initial problem followed by a new
same-scope problem is 1. Null is never a negative. The finite scenario plan and
new integer accounting expectations supply labels; engine findings are separately
checked against those expectations and cannot supply the truth label.

## Frozen worlds, families and split

There are 120 base-world groups, indices 0..119, seeds 500000+index. Groups 0..71
are train (72), 72..95 validation (24), 96..119 final test (24). Challenge has 24
separate groups, indices 120..143, seeds 700000+(index-120). Every world has four
episodes, two assets (8 and 2 decimal places), `24+4*(index%5)` economic events and
`4+(index%3)` investors. Thus main scope is 144 groups, 576 episodes, 1152 visible
asset units before any explicit exclusion. Counts of OPEN/closed/positive/negative/
censored units are measured, never forced by dropping rows or resampling.

All variants, renamed identities, assets, A/B findings, twins and time cuts from
one world share one split. The public split roster contains neutral world/episode
join identifiers and membership, not truth. Identity strings are not features.
The generator varies affected asset, investor, target event position, positive
integer impact, and initial observation age independently of their textual names.
There is no fixed first-investor / ASSET_A / seven-unit fault template.

Base episodes per world are fixed:

1. Slots 0/1 are a LATE_EVENT twin pair: identical economic data and all <=T saved
   observations, but delivery arrives at T+2/8/16h in one and T+30h in the other.
   Their features and frozen-model scores must be identical.
2. Slot 2 rotates, by index%4, LATE_MANIFEST, REPORT_REVISION,
   CORRECTION_DEPENDENCY, CUSTODY_DIFFERENCE. `floor(index/4)%2` chooses whether the
   relevant delivery or independent report revision completes before or after H.
   Each family therefore includes resolved and unresolved examples. Corrections
   use existing immutable amount-only REPLACE/target dependency semantics; reports
   remain independent. No financial engine or old oracle changes are permitted.
3. Slot 3 cycles, by index%4, CLEAN, H_NOT_OBSERVED, OBSERVABILITY_LIMIT, CLEAN.
   H_NOT_OBSERVED is open at T but observed only through T+12h: null, still in the
   queue/capacity. OBSERVABILITY_LIMIT is a same-effect reference substitution,
   excluded from target interpretation; no fraud-detection success is credited.

Every challenge episode belongs exclusively to COMBINED_REOPEN, absent from
train/validation/test base families. Slots 0/1 share a T prefix: the missing event
arrives before H in both, but an independent later custody report opens a new
problem in one after the initial problem has closed. Slots 2/3 cover a remaining
late-event plus custody problem versus both resolved. Intermediate closure is
checked by the final truth evaluator. Challenge is reported separately, never
pooled into the primary new-world test or used to tune the model.

Each episode has one earlier compatible observation and T. Observed age is varied
over 3/6/12/18 hours. The first-problem observation is measured from these stored
payloads, not from private schedule metadata. Complete history compatibility means
same episode/configuration/rule/balance_at and knowledge_at<=T.

## Information boundary and feature schema

The extractor receives only selected saved payloads and their compatible <=T
history, through the unchanged read-only review adapter in small per-episode
batches. It never reads current Store/records/receipts, intake, wire row totals,
source size, private plans or labels. Future payloads are rejected. Source hashes
and neutral join IDs may occur in provenance, never in the feature vector.

The ordered allowlist is:

```
a_open_count, b_open_count,
a_incomplete_count, b_incomplete_count,
a_conflict_count, b_conflict_count,
a_stale_count, b_stale_count,
a_mismatch_count, b_mismatch_count,
a_not_evaluated_count, b_not_evaluated_count,
missing_manifest_count, missing_report_count, pending_correction_count,
observed_age_hours, observation_count, open_observation_count,
a_relative_difference_max, b_relative_difference,
a_ratio_undefined_count, b_ratio_undefined_count
```

Counts are nonnegative integers (bool rejected). Age and ratios are finite decimal
text or explicit null. Relative difference is abs(saved difference)/abs(saved
expected), within one asset and comparison. A uses the maximum of defined investor
ratios; B has one liability finding. A zero/unknown denominator yields null and an
undefined count, never epsilon. Derived feature divisions use Decimal, explicitly
rounded half-even to 18 fractional places; original financial strings/null never
change. Model conversion to float occurs only at the model boundary. Every feature
records type/null policy, actual run IDs, JSON pointers, actual evidence IDs, and
latest used knowledge time. Aggregates retain the complete contributing source set.
Missing-manifest/report and pending-correction signals count matching saved issue
entries, not unseen deliveries or guesses. The implementation freezes exact code
allowlists before the experiment; they cannot be tuned on holdout results.

Feature documents are `triage-features-v1` with `units`: neutral unit/world/episode
IDs, split, asset, balance_at, as_of, first_seen_at, status OPEN/NO_OPEN_FINDING,
features, feature_provenance, and original finding references. Financial payloads
are separately preserved verbatim. Labels/private plans are separate files.
No seed, scenario/fault/family, path, alias semantics, run/hash, expectation or H
outcome is permitted as a model feature. Metadata enables joins only.

## Policies, model and explanation

FIFO sorts OPEN units by first observed open time (oldest first), then neutral
unit_id ascending. Rules sort lexicographically by: any CONFLICT first; then any
pending correction; then any COMPLETE/MISMATCH; then missing report; then missing
manifest; then other INCOMPLETE; then STALE; then remaining OPEN. Within priority:
older observed age first, greater max defined A/B dimensionless relative difference
first (undefined last), then neutral unit_id. These are synthetic review rules,
not institutional policy. There is no weak-baseline search or rule retuning.

One LogisticRegression: scikit-learn **1.9.1**, C=1.0, l1_ratio=0.0 (L2),
solver=lbfgs, tol=1e-4, max_iter=1000, fit_intercept=True, class_weight=None,
random_state=20261111. No grid search, class rebalancing or second model. The
official 1.9.1 API deprecates penalty in favor of l1_ratio/C; use that actual API.
Source: https://scikit-learn.org/1.9/modules/generated/sklearn.linear_model.LogisticRegression.html
and https://pypi.org/project/scikit-learn/1.9.1/ (checked 2026-11-12).
Installation/API compatibility and transitive dependency versions must be recorded
from the real optional-ai environment before any experiment claims.

Fit only known-label OPEN train rows. List all excluded train rows/reasons. Per
feature, train-only median imputation; an all-train-null column uses explicit zero
imputation with an all_missing flag. Append a missing indicator for every feature.
Fit StandardScaler on this fixed 2F train matrix only (constant scale=1). Preserve
original feature nulls. Export strict finite JSON: format triage-model-v1, target,
24h horizon, feature order, medians/all_missing/means/scales, coefficients/intercept,
classes [0,1], train/split/contract hashes, versions and content-derived model ID.
Unknown fields, bad dimensions/types, NaN/Infinity, or contract/feature/horizon
mismatch fail visibly. No pickle/joblib or executable model loading is supported.

The standard-library scorer must match library scores on literal fixtures and
actual generated data with absolute error <=1e-12. Only actual checks can claim
that tolerance. Rank by score rounded half-even to 12 fractional decimal places,
descending, then neutral unit_id. Same-score twins remain indistinguishable.
Scores are model outputs, not calibrated financial risk probabilities. Model errors
or metadata mismatches abort rather than silently substituting a successful model
result. No fallback policy is planned: fallback_count must be reported as zero;
unscorable units remain explicit in an error inventory, never silently dropped.

queue.json/queue.md preserve every unit, original state axes/provisional values,
finding/run/evidence links, observed features, FIFO/rule/model ranks and model ID.
NO_OPEN_FINDING has no rank and an explicit reason. Explanations are templates of
observations and verified linear-score contributions, not causality or root cause.

## Freeze, evaluation and metrics

Private H expectations and engine verification for train/validation may run during
development. For final test/challenge they may run only in the final evaluator
after the feature schema/code, split, rules/metrics contract, trained model and
complete unlabelled rankings are hash-frozen. A one-shot evaluation marker refuses
a second final evaluation. Original T source DBs stay immutable: H evaluation uses
owned copies, never adds future runs to the feature sources. Any truth/engine,
leakage, split or scorer mismatch halts later training/evaluation, not a model win
or loss. Features/rank accept no truth-file argument. Labels must cover the exact
unit roster, including closed/out-of-scope/censored inventory.

Primary test is one common-T queue; challenge is another. For each policy N is the
same count of all OPEN units before labels, including censored units. K=ceil(N/5)
if N>0, else 0. Rank first, join labels later, never refill unknown top-K positions.
P is all known positive OPEN units. Top-K counts TP, FP, U must satisfy TP+FP+U=K.
Recall_known@K=TP/P (P=0: null); Precision_labeled@K=TP/(TP+FP) (zero: null).
If U>0 exact Precision@K is null, with bounds [TP/K,(TP+U)/K] and coverage
(TP+FP)/K. K=0 makes all top-K ratios null. If U=0 normal precision is TP/K.
Unknown labels never count as negative; complete recall is unknown when censored.

Report N,K,K/N, known positive/negative/censored denominators, found/missed known
positives, rules-model deltas and world/family/asset attribution to the same global
top-K. Group tables do not rerank or invent new capacity. Retain several missed/
misprioritized examples with saved evidence links. No independence/confidence claim
is made from dependent units. If recall gain over rules is <=0, report that this
synthetic experiment did not demonstrate additional benefit. No institution claim.

## Resource and execution scope

One shared 900-second monotonic budget and 2 GiB combined temporary+retained
experiment-file budget cover the two-world feasibility smoke, main generation,
training, final evaluation, report generation and verified experiment retention.
Dependency installation, development/unit tests and old financial regression gates
are outside this experiment budget and recorded separately. The smoke uses seeds
900001/900002; archive training smoke uses different seeds 910001/910002 and never
reruns the locked main holdout. Main seed/scope cannot shrink after a limit/error.
Bounded checks occur between episodes/phases and before publication; budget failure
leaves an explicit incomplete/error record and no COMPLETE claim.

Use owned local temporary runtime storage to avoid managed-folder hydration during
the measured experiment. Retention hashes and byte counts are part of the same
budget. No heavy A/B, profiler, 100,000-event stress, GPU, paid service, LLM, cloud,
live data, automatic correction, payment, remote publication or later-stage code.
Existing 271 tests, financial code/oracle/schema, S4-F1 repair and UI remain intact.
