# Stage 9.1 decisions

1. **Safe diagnostics without changing the wire.** Duplicate JSON keys remain
   rejected. Their diagnostic representation uses safe escapes; original payload
   bytes, hashes and first terminal results remain unchanged. Core normalization,
   financial arithmetic and the delivery transaction are untouched.
2. **Explicit recovery-contract evolution.** Version 0.7.1 uses recovery scope,
   schedule and report v2. The v1 admission delivery protocol and financial/review/
   triage formats are unchanged. Old recovery v1 records remain historical and do
   not silently satisfy the v2 gate. Physical schema remains 4; no migration runs.
3. **One pinned scope, usable from a wheel.** The reviewed contract file and packaged
   JSON resource have identical bytes and a separately pinned SHA-256 and length.
   Runtime loading verifies the resource. Release loading verifies both copies.
   The standalone release helper loads the stdlib-only scope module by file path,
   so an isolated source build needs no editable or installed application package.
4. **Independent expectations, bounded dynamic links.** Per-case work, input byte
   identities, financial literals, control names, phase expectations and evidence
   relationships are declared once. Ordinary execution never rewrites them. The
   one-time authoring record uses literal requirements and fixed synthetic input
   bytes, never calculator results or a candidate report to define required scope.
   PID, time, physical receipt and run identities are validated through type and
   equality relationships rather than invented fixed values.
5. **Semantic completeness instead of a control counter.** Required control names
   are unique and exhaustive; observations and responses must support their claims.
   Phase prefixes disambiguate repeated initial/interrupted/final checks. Additional
   `extra:` controls are permitted only when unique and consistent, and never fill
   a missing required slot. The 802 current controls are not a numeric pass target.
6. **Record the actual connection.** Parent writer operations and child READY,
   BARRIER and RESULT messages include their own journal/synchronous observations.
   The independent read-only connection is identified separately. Required parent
   operation inventories and PID relationships prevent a generic observation from
   substituting for the connection that did the work. No durability settings change.
7. **Fixture exception stays local.** The previous seven release tests retain their
   methods and assertions. Only `report_fixture` loads a labeled complete synthetic
   v2 input. Synthetic process IDs, paths and timings are explicit; this fixture is
   never a claim of real crash execution. Real process tests and release recovery
   run separately. A pinned named-function exception verifies the surrounding old
   file bytes and assertion preservation; it is not permission for arbitrary edits.
8. **Preserve evidence and limits.** New source, distributions and outputs use new
   task paths. The failed development literal and initial provenance counterexamples
   remain available. Full verification uses the established release runner once per
   required environment. The main model experiment, final holdout, historical heavy
   benchmarks and 100,000-event stress are not run. This remains application-process
   interruption on a local initialized SQLite database, not power-loss durability,
   distributed delivery or cryptographic report authenticity.

9. **Unknown contention observations remain unknown.** The first no-AI gate exposed
   an overstrict check of a legitimate bounded-writer intermediate busy response.
   Preserve the existing non-ACK/non-durable/null-attempt semantics, retain its
   explicit UNKNOWN observation, and accept paired null cursor/block only under
   that narrow condition. Require complete final readback after bounded retries.
   The fixed scope revision and two new RED→GREEN tests are explicit; prior failed
   release evidence and distribution identities remain untouched. Financial source
   bytes did not change, so the already completed local matrix can be linked to
   the revised candidate while final exact-head CI performs its normal matrix.
