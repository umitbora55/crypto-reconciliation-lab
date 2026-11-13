# Historical reporting-data corrections (Stage 2)

Rule version: `stage2-v2`; package 0.2.1; SQLite schema 2. Every envelope, batch, atomicity and time rule below is a **prototype design assumption**. MKK Article 20 distinguishes transaction and report correction concepts; it does not specify this wire format or certify this implementation. Regulatory submission-window conformance is not claimed.

## Four separate concepts

1. **Original target:** an immutable, structurally valid completed deposit, withdrawal or investor transfer after the configured opening snapshot. Its full event key is source/platform/UTC business day/reference, with `kind=event`.
2. **Correction and signed effects:** an immutable source record describing full VOID or amount-only REPLACE. Its reversal is derived from the original, not supplied by the sender. It applies at the original economic position.
3. **Independent reports:** investor and custody reports change only when their own new valid versions are known. A correction never edits or synthesizes them.
4. **Knowledge time:** correction, target and required delivery evidence must be visible at the evaluation cutoff. Prior saved evaluations and their evidence never change.

A real refund, withdrawal or deposit that occurs today is a **new event with today's occurred_at**. It must not be disguised as a historical reporting correction.

## Wire contract

The existing JSONL outer envelope remains `record` plus `received_at`. Receipt hashes and physical receipt row IDs are outside normalized correction content. The correction key is `(correction, source, platform, correction_id)`. Example record:

```json
{
  "kind": "correction",
  "source": "P1",
  "platform": "P1",
  "asset": "ASSET_A",
  "batch_id": "BATCH1",
  "correction_id": "COR1",
  "target": {
    "kind": "event",
    "source": "P1",
    "platform": "P1",
    "business_day": "2026-11-10",
    "ref": "A2"
  },
  "target_occurred_at": "2026-11-10T02:00:00Z",
  "mode": "REPLACE",
  "replacement_amount": "3",
  "source_ref": "REVIEW-COR1",
  "reason": "Synthetic historical reporting error"
}
```

`target_occurred_at` is a required assertion, checked against the actual target. It permits temporal scoping while a target is missing; it cannot change the target's economic time. The target cannot supply alternative parties, asset, event type, sequence or custody location. All are inherited from the original.

VOID **omits** replacement_amount, even null. REPLACE requires a positive plain decimal string within the asset's existing precision and magnitude bounds. Extra fields are rejected. Source and target identifiers must match the configured platform. A reason and source reference are required. `batch_id` is an immutable source-declared membership field, not a physical receipt ID; moving a correction between batches changes the declared source content and conflicts. Delivery timestamps, hash IDs and physical receipt IDs never participate in correction identity/content comparison.

Identical normalized content is economically idempotent. Different content under one correction ID conflicts. Receipt traces remain separate, and first_known_at is the earliest eligible receipt time, unaffected by later retries. Two distinct correction IDs targeting the same original conflict, including across batches. Neither first nor last arrival wins. A correction targeting another correction is rejected before graph traversal, so correction chains and cycles cannot become executable graphs.

## Correction delivery

New records use `kind=correction_manifest` with source, platform, asset, batch_id, coverage_from, coverage_to and expected_count. Identity is `(correction_manifest, source, platform, asset, batch_id)`; content cannot be revised under that identity. Economic coverage is `(coverage_from, coverage_to]` and must contain each asserted target time. Multiple batches are allowed; originals and their Stage 1 manifests are unchanged.

A source correction envelope counts once, regardless of whether its group has one reversal effect (VOID) or reversal plus replacement effects (REPLACE). Exact retries do not count twice. Invalid, conflicting and unresolved-target corrections do not complete the count. A voided original remains in its original event delivery count. Counts and coverage are source assertions, not signatures, authenticity proofs or detection of same-count substitutions.

A batch known through a correction or a manifest is checked. No correction manifest means INCOMPLETE, never assumed complete. A manifest with missing members establishes a count shortfall. Old Stage 1 data with neither correction nor correction manifest has no correction channel requirement. Batches whose coverage begins before the evaluated balance can conservatively block completeness even if some targets are later; future target events never gain an economic effect before their own occurred_at.

A group applies only if its own batch is complete and the required original opening/event deliveries are complete. An incomplete or conflicted batch leaves original effects in the provisional replay; it never partly applies a correction. Independently complete batches for other targets can still apply, but unresolved asset inputs prevent a definitive financial verdict. ASSET_A problems do not block independent ASSET_B results when asset scope is known.

## Dependency and validation outcomes

Intake `ACCEPTED` means schema-valid source record, not economically applied. Dependency resolution is evaluated and persisted in correction_deliveries/issue evidence for each knowledge cut. TARGET_PENDING is a retained unresolved dependency, not permanent intake rejection. Once its valid original and delivery evidence arrive, a new evaluation can apply it.

| Code | Meaning / handling |
|---|---|
| TARGET_PENDING | No known target; INCOMPLETE / NOT_EVALUATED |
| INVALID_TARGET | A known invalid target receipt exists; distinct from absence; INCOMPLETE |
| TARGET_EVENT_CONFLICT | Original identity has conflicting contents; CONFLICT |
| CORRECTION_ID_CONFLICT | Same correction ID, different content; CONFLICT |
| MULTIPLE_TARGET_CORRECTIONS | Multiple correction IDs address one original; CONFLICT |
| TARGET_ASSET_MISMATCH / TARGET_TIME_MISMATCH | Known target differs from asserted scope/time; CONFLICT |
| TARGET_PLATFORM_MISMATCH / CORRECTION_PLATFORM_MISMATCH | Rejected cross-platform/source request |
| CORRECTION_MANIFEST_ABSENT / CORRECTION_MANIFEST_COUNT | No delivery proof or unique-valid count disagreement |
| CORRECTION_MANIFEST_CONFLICT / TARGET_OUTSIDE_CORRECTION_COVERAGE | Contradictory delivery declaration or coverage |
| INVALID_REPLACEMENT_AMOUNT / VOID_WITH_REPLACEMENT_AMOUNT | Rejected quantity contract; original not removed |
| UNSUPPORTED_PARTIAL_REVERSAL / UNSUPPORTED_CORRECTION_MODE | Only full VOID and full amount replacement supported |
| SELF_REFERENCE / UNSUPPORTED_CORRECTION_CHAIN | Self-target, another correction or any correction cycle is rejected |
| UNSUPPORTED_OPENING_HORIZON / UNSUPPORTED_OPENING_REVISION | No correction at/before the immutable opening, and no opening replacement |
| UNSUPPORTED_MANIFEST_REVISION / UNSUPPORTED_CORRECTION_FIELDS | No manifest revisions or party/type/asset replacement fields |

Schema-invalid receipts retain their reason code in the error text and return reason_code from ingestion. They block identified scope as INCOMPLETE; they do not disappear behind a successful result. A corrected valid envelope cannot silently remediate an old invalid receipt because general quarantine remediation is still unsupported.

## Atomic calculation and storage

For original signed effect E(q), VOID has original E(q) plus derived -E(q), net zero. REPLACE has original E(q), derived -E(q) and E(q_new), net E(q_new). Positive source quantities are separate from signed derived investor/custody effects.

The engine constructs a complete group before replay and applies only its net effect at `(occurred_at, sequence, source, business_day, ref)`. It does not insert a present-day reversal into economic order. Negative-balance checks occur after the net group at the original position; a temporary half-group negative is impossible. A negative balance in the complete corrected replay still invalidates the evaluation.

SQLite `correction_groups` links run, original record and correction record. `correction_effects` stores separately identified reversal/replacement legs with ordinals. Full derived groups also appear in immutable run evidence and Markdown/JSON reports. A single explicit SQL transaction commits the run, groups, all effects, findings and evidence. Source intake is a separate transaction, so an evaluation failure retains the already accepted audit input but stores no partial run/group.

Tests inject failures after deriving a reversal, after inserting the run, after inserting the reversal leg, before evaluation commit, during intake, and at two migration boundaries. Failed transactions roll back. No in-memory or durable half-correction is reused on retry.

## Schema upgrade and history

Stage 1 used user_version 0. Stage 2 adds schema_migrations, correction_groups and correction_effects and sets user_version=2 in the same explicit transaction. No old column, key, row or stored payload is rewritten. Python connections use isolation_level=None and explicit BEGIN IMMEDIATE / COMMIT / ROLLBACK; migration does not call executescript inside a transaction.

`migrate --db PATH --backup-dir DIR` uses Connection.backup for the real source. On a copy it proves controlled-failure rollback, successful upgrade, repeated upgrade and restoration from the old backup, comparing sorted logical rows and old schema. Only then is the real database upgraded. Old run payloads are read directly, not recalculated. An old database may be opened to read history without migration; new evaluation persistence requires explicit migration. Recovery writes a new destination from the verified backup, not destructive downgrading of a database with new history.

Limits retained: trusted synthetic source timestamps, no authenticity claim, no opening/manifest revision workflow, no partial or chained corrections, no quarantine remediation, no concurrent-production guarantee, no UI/AI/cloud/live integration. Fresh queries after backdated imports may gain data; previously persisted runs are immutable. Regulatory timing compliance remains outside scope.

## Stage 2.1 target-time precedence and invalid JSON

Batch selection first resolves the target identity among records visible at knowledge_at. If any known target variant is at or before balance_at, its batch is inspected even when the correction asserts a later target_occurred_at or its manifest starts in the future. A time mismatch remains CONFLICT/NOT_EVALUATED with TARGET_TIME_MISMATCH; the correction is not applied. The target, correction, manifest and their receipt references stay in evaluation evidence. Unapplied original balances are explicitly provisional. Existing batch-count, identity-conflict, opening-horizon and independent report rules still apply.

When no target is visible, the prior assertion/pending contract remains: an asserted future target may stay outside this cut; a relevant missing target is TARGET_PENDING. Targets learned after knowledge_at cannot participate in scope selection. An actual future target is never replayed early. A batch whose valid manifest overlaps the cut may still conservatively block it, as before.

Schema-invalid correction receipts use the same known-target precedence. They cannot hide a known in-cut target with a false future assertion; they remain blocking quarantine evidence with the original validation reason and no economic effect. A relevant correction also brings its manifest into inspection regardless of its declared future boundary. Invalid manifests cannot use unparseable or inverted intervals to prove irrelevance.

Raw target must be an object with string kind/source/platform/business_day/ref and kind=event before a lookup key is built. Asset must be a known string to narrow the block; malformed or unknown assets broaden it. Invalid batch IDs map only to an internal unknown dependency bucket, never a valid economic identity. No list/dict is stringified into an accepted identifier. This scope inspection does not strip extra fields, change raw receipts or accept invalid data. See model_contract.md for the kind-specific original-input table.
