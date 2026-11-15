# Stage12.1 maintenance decisions

The reviewed 0.10.0 candidate is commit 43708e4e1d94bc18412ba53b1706fa45018e320a.
Package 0.10.1 repairs S12-F1 through S12-F4; stage2-v2, schema 6 and existing v1
format names remain unchanged. The earlier Stage12 contract is a historical
record. These notes clarify its intended original-admission and input-error
semantics without rewriting old artifacts.

1. Export canonicalizes the parent before any filesystem publication, checks
   the final name for existing/dangling links, then uses one resolved destination
   for source/SQLite sidecar guards and atomic publication. No cleanup deletes
   source-adjacent names and no SQLite setting changes. See [F1/F3](f1-f3.md).
2. Original acceptance epochs come from stored delivery links joined to their
   effect, unique COMMITTED attempt, attempt authorization and original decision.
   A CURRENT or HISTORICAL_REPLAY label alone does not identify an original
   admission. Detailed replay decisions remain present; observed head stays
   separate. Correct 0.10.0 contexts retain exact raw bytes/hash/identity. A wrong
   historical summary contradicting its own stored original links is an explicit
   EXECUTION_INTEGRITY error on read/export/retry, without rewriting or migration.
   See [F2 and historical compatibility](f2.md).
3. Only OverflowError at the new recorded-input timestamp boundary becomes
   EXECUTION_INPUT. CLI input failures remain exit 2; valid financial non-match
   remains exit 1. The shared financial timestamp helper is unchanged.
4. Process evidence binds recorded paths lexically against absolute recorded
   POSIX cwd, roles, request cuts/IDs and actual ACK arguments/results. It never
   stats a remote CI path or adds paths to runtime fingerprints. Rewritten,
   internally consistent evidence is not externally authenticated. See [F4](f4.md).
5. The new release scope retains the byte-pinned 0.10.0 anchor and 729 prior IDs.
   The synthetic two-helper exception is separately pinned; no old test method
   or behavior assertion changes. Other current metadata edits are exact and
   reversible. See [fixture preservation](fixture-changes.md).
6. The full source/installed suites already execute the 49 new tests. Their
   actual maintenance CLI observations are retained in CI artifacts. Core runs
   a fixed 14-test F1/F3 subset without auth/AI; auth-only runs three F2 controls
   without AI. These are finite checks, not additional full suites. The existing
   real process suite runs only inside normal full gates; transcript negatives
   do not launch new SIGKILL or competing-writer experiments.

New execution, unsuccessful attempts, release gates, hashes, final commit/CI
results and HANDOFF stay outside Git under stage12_1-output. The original
independent review is attributed separately from locally executed RED/GREEN.
No baseline full-suite repetition, frozen experiment, training, holdout, schema
migration, main merge, force push, dispatch, release/tag or PyPI publication.
