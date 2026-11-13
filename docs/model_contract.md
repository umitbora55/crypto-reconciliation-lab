# Model contract: Stages 1 and 2

Current rule version: `stage2-v2`. Existing stored evaluations retain `stage1-v1` or `stage2-v1` and are never rewritten. Unless explicitly listed as source-verified in `problem_evidence.md`, every rule below is a **prototype design assumption**, implementing the requested synthetic experiment.

## Entities and persistence

One immutable configuration per SQLite database defines platform, custodian, investor roster, asset precision and `opening_at`. The supplied demo uses P1, C1, I1, I2, ASSET_A (8 places) and ASSET_B (2 places). Configuration values must be preserved when reopening a database.

`records` stores canonical normalized JSON, a SHA-256 content ID, kind and logical key. Every quantity inside that JSON is a canonical **text** value, never JSON numeric, SQLite REAL or a SQL aggregate. `receipts` appends every received envelope, its hash, original raw JSON, normalized `received_at`, validation error and intake status. The input's original decimal spelling survives in the receipt. Canonical values strip fractional trailing zeros and normalize zero. A repeated identical receipt still has another physical row; evidence refers to its stable hash.

`runs` stores a content-addressed evaluation snapshot. `findings` and `evidence` store that run's findings and complete referenced payloads. SQL triggers prevent UPDATE/DELETE on these tables and on configuration, records and receipts. These guards prevent accidental application mutations; they are not adversarial tamper protection against a database owner. No SQL quantity SUM, REAL coercion, floating-point arithmetic or implicit zero fill is used.

## JSONL input

One JSON object per line: `{"received_at": "timezone-aware ISO timestamp", "record": {...}}`. Unexpected fields, duplicate JSON keys and non-finite JSON constants are rejected. Record fields are exact, not open-ended; scenario labels cannot enter accepted engine data.

Common fields: `kind`, `source`, `platform`, `asset`.

| Kind | Additional required fields |
|---|---|
| opening | scope, balance_at, amount |
| event | business_day, ref, occurred_at, sequence, type, from_investor, to_investor, custody, amount |
| report | stream, scope, balance_at, version, amount |
| manifest | stream, coverage_from, coverage_to, expected_count |

`scope` is an investor ID, `platform` or `external`. Report streams are `investor`, `platform_custody`, `external_custody`. Manifest streams additionally include `opening` and `event`. P1 supplies events, investor reports, platform customer-custody reports and the opening snapshot. C1 supplies external-custody reports and their manifests. The opening snapshot's external amount is a synthetic initial condition supplied with the platform's complete starting state; subsequent C1 reports are separate evidence.

Deposits require `from_investor=null`, a known `to_investor` and a custody location. Withdrawals require the reverse participant arrangement and a custody location. Transfers require two distinct known investors and `custody=null`. `custody=platform` always means assets held **for customers**, not proprietary assets. Only completed events are represented. Inline correction/reversal event types remain invalid. Stage 2 supports separate immutable correction envelopes; see `correction_semantics.md`.

## Exact quantities

Input amount grammar is signed plain ASCII decimal text; scientific notation, whitespace, separators, empty/missing amounts, NaN, Infinity and numeric JSON values are invalid. Amounts must be nonnegative, and events strictly positive. Input scale must not exceed the asset limit, even for trailing zeros. Input length <=64 characters and magnitude <10^40 are resource and arithmetic bounds, not regulations. Asset precision is 0-18; configured demo precision is 8 and 2.

Calculations use a fresh local Decimal context: precision 64, Emin=-64, Emax=64, **all signals trapped**, including Rounded, Inexact, Overflow and FloatOperation. No silent rounding is permitted. Canonicalization formats without quantization. Large aggregate overflow or precision loss terminates evaluation with an application error rather than storing a misleading successful run.

## Identity and bitemporal selection

Event logical key: `(kind, source, platform, business_day, ref)`. `business_day` is the UTC calendar date of normalized `occurred_at`; asset is deliberately not part of the key, so reusing a reference with a different asset conflicts. Full economic content includes asset, type, participants, custody location, amount, economic timestamp and sequence. `received_at` is outside it. Decimal spelling and equivalent timezone offsets normalize before hashing.

Identical normalized content has one economic effect. Changed content under the same key creates a visible conflict; all disputed variants remain stored and are excluded from the valid-event count. Intake status is diagnostic; evaluation derives conflicts afresh from only the receipts known at its cutoff, so later conflicts never leak backward. Events are eligible only when `opening_at < occurred_at <= balance_at` and some receipt has `received_at <= knowledge_at`.

Economic replay order is `(occurred_at, sequence, source, business_day, ref)`. Sequence is a nonnegative bounded integer. The lexical reference tiebreak is deterministic, not a claim about real exchange sequencing. A source must supply meaningful sequence values when simultaneous ordering matters. Negative investor balances at any step of a **complete** economic ledger cause `CONFLICT/NOT_EVALUATED` with `NEGATIVE_ECONOMIC_BALANCE`. In incomplete data, the observation is provisional and never permanently rejects the event at intake.

Report identity: `(kind, source, platform, stream, asset, scope, balance_at, version)`. Version is a positive source revision number. Select the highest numeric version known at `knowledge_at` for the exact target `balance_at`. A late retransmission of an older version does not roll back a newer one. Same-version differing content conflicts; a later unambiguous higher version supersedes the conflicted older version. Old rows stay stored. A schema-invalid newer receipt remains a blocking taint; there is no silent successful fallback or quarantine-resolution workflow in Stage 1.

Older report times can establish STALE but never supply the target amount. Future report times are not substituted. Missing target reports yield null compared values, never zero. Every timestamp requires an explicit timezone and second-level ISO syntax, permits up to 6 fractional digits, and normalizes to fixed-width UTC microseconds for ordering.

`balance_at` and `knowledge_at` are explicit evaluator arguments; the evaluator can represent early partial knowledge. The demo requires knowledge at or after balance. No real wall-clock time participates in deterministic results. `received_at` is trusted as synthetic input, not a signed ingestion timestamp. Backdated imports can change a fresh query for a previous knowledge cut, but never modify an already saved run. Production ingestion clocks/authorization are out of scope.

## Delivery completeness

Manifests are immutable by `(source, platform, stream, asset, coverage_from, coverage_to)`; contradictory expected counts conflict. Stage 1 has no manifest revisions or merging of overlapping deliveries.

Required exact coverage:

- Opening: `[opening_at, opening_at]`, four unique scope records in the demo.
- Events: `(opening_at, balance_at]`, unique valid economic events only.
- Each report stream: `[balance_at, balance_at]`, selected unique scopes only; report versions and retries do not increase counts.

Counts and required roster/scope checks are both necessary. Absent manifests mean completeness unknown, without asserting a missing-event count. A count shortfall is observable incompleteness; excess unique valid records contradict the declared delivery and cause CONFLICT. Duplicate and quarantined records cannot cover a shortfall. Manifests are assertions from synthetic sources, not independent proof that no event was omitted; same-count substitution cannot be detected without a stronger delivery identity scheme.

A malformed receipt blocks its identifiable asset/stream/time scope. Unknown asset or missing/invalid time/scope broadens the block conservatively. An unparseable receive time is always blocking because its knowledge applicability is unknown; the raw envelope is retained. An invalid report for one custody stream does not affect A. For simplicity, the complete opening snapshot and the full investor-report manifest are atomic per asset: a missing opening custody component also blocks the ledger, and a deficient investor delivery blocks A for all investors in that asset. This conservative scope is intentional.

## Equations and status axes

For investor i, asset a and cutoff t:

`L(i,a,t) = opening(i,a) + deposits - withdrawals + transfers_in - transfers_out`.

`customer_liability(a,t) = sum over configured investors of L(i,a,t)`.

A: `difference(i,a) = L(i,a,t) - reported_investor(i,a,t)`.

B: `difference(a) = customer_liability(a,t) - (reported_platform_customer_custody(a,t) + reported_external_customer_custody(a,t))`.

B never substitutes reported investor balances for ledger-derived liability. Each asset stands alone with zero tolerance. Internal transfers affect investor allocation only. Deposits/withdrawals alter the selected customer custody location as well as investor balances. Custody roll-forward is an explanatory trace in Stage 1; A and B are the two formal comparisons, not an additional certified custody-location control.

Data state precedence is `CONFLICT > INCOMPLETE > STALE > COMPLETE`. Every underlying issue is retained even when another state has precedence. A solely old report is STALE, including the corresponding target-delivery shortfall; a truly missing other required input can make the combined state INCOMPLETE.

Only COMPLETE inputs produce MATCHED (difference zero) or MISMATCH (nonzero). Otherwise reconciliation_state is NOT_EVALUATED. Visible partial differences are labeled provisional; missing compared components produce null differences. States are per comparison/asset; A has a finding for each investor and B one customer-liability finding.

Findings contain scope, asset, expected and compared quantities, signed difference (`expected_minus_reported`), event/report IDs, all evidence IDs, both cutoffs and rule version. Ledger traces include starting quantities, ordered movements, resulting investor balances and custody-location movements. Evidence includes manifests, conflicting candidates, quarantined receipts, chosen records and receipt payloads. No hidden injected-error label is used to infer any result.

## Reproducibility and exclusions

Canonical JSON hashes identify normalized records and evaluations. Report content is sorted deterministically; exact repeated input and policy cuts reproduce the same run ID. Newly learned equivalent receipts can add evidence without changing economics; they may therefore change a run ID. Historical snapshots are read directly and never recomputed in place.

Stage 2 adds full VOID and amount-only REPLACE via a separate correction envelope and correction manifest. No partial/chained corrections, opening replacement, manifest revision, quarantine remediation, source signatures, multi-platform netting, concurrent production ingest, performance guarantees, API integrations or legal conformance are implemented. No model output infers fraud, insolvency or a definitive root cause.

## Stage 2 extension

`correction_semantics.md` defines required correction and correction_manifest fields, reason codes, atomic net effects, dependency resolution, source record counts and additive schema migration. Original events and their manifests remain immutable and retain their delivery counts even after VOID. Reports keep the exact existing highest-known-numeric-version contract; corrections never generate reports. New derived groups/effects are linked to originals and persisted atomically with a new evaluation. Stage 1 formulas apply to effective event quantities after eligible atomic groups.

## Stage 2.1 quarantine scope (prototype design assumption)

Invalid receipts are evidence, never repaired records. Scope hints must be strings of the permitted domain before membership/indexing/key creation; arrays, objects, null, booleans and numbers are not coerced. A known configured asset narrows the affected asset; any other value blocks all configured assets for the relevant kind/time. Unknown or malformed kind blocks all streams for that asset and ignores every stream/time hint.

| Recognized kind | Permitted stream hint | Permitted economic time hint |
|---|---|---|
| event | Always event; ignore extra stream/scope | occurred_at in (opening_at, balance_at]; ignore extra balance_at |
| opening | Always opening; ignore extra stream | balance_at = opening_at |
| report | Valid investor/platform_custody/external_custody; otherwise all report streams | balance_at = evaluation balance_at |
| manifest | Valid configured stream; otherwise all five original streams | Valid ordered coverage pair matching the stream's required exact coverage |
| correction / correction_manifest | Dedicated correction resolver | Known target time first; assertion only while no target is visible; batch dependency rules below |

Missing or ill-typed time, and invalid/inverted coverage, cannot prove irrelevance and therefore block conservatively. Scope can narrow only when valid for that kind and stream; opening and investor delivery checks retain their atomic per-asset behavior. Recognized records with valid time outside the relevant cut do not block it. Unrecognized extra fields never change stream or time selection. In particular, an invalid external_custody report blocks B without blocking A; an invalid event blocks both A and B. Raw input and validation reason remain unchanged in receipt evidence.

Correction target lookup uses only well-typed event identity fields in the current knowledge snapshot. A known target's occurred_at takes precedence over target_occurred_at for selecting batches and quarantined correction dependencies. No later-learned target is consulted. An in-cut target with a false future assertion is audited, produces TARGET_TIME_MISMATCH, and leaves original quantities provisional; it cannot disappear behind a future manifest boundary. No schema or persisted historical payload is changed by this rule update.
