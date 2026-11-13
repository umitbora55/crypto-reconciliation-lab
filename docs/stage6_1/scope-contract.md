# Stage 6.1 release scope contract

Package 0.6.1 repairs two release-verifier coverage gaps. The financial application, stage2-v2, schema 3, v1 formats, pinned dependencies and locked main experiment are unchanged.

## Expected, discovered and executed tests

The independent 0.6.0 inventory contains 375 test identities and 31 Python test/fixture files. Its exact bytes are retained in [the baseline contract](../../contracts/release-tests-baseline-0.6.0.json). Local baseline discovery, file hashes and a real complete execution are checked against that prior inventory before repair.

[The 0.6.1 scope contract](../../contracts/release-test-scope-0.6.1.json) explicitly declares the preserved baseline, the single authorized version-fixture edit and each added regression file/identity. Its byte identity is pinned outside the JSON in the validation helper. Contract authoring is a separate reviewed maintenance operation: ordinary build and verification never regenerate expected files or identities from the candidate.

The release preflight verifies the exact test/fixture file set and hashes. The runner captures discovery identities before unittest may clear its suite, then separately captures each actual test start. Every expected identity must be discovered and executed exactly once. Omissions, extra or substituted identities, duplicates, discovery/execution disagreement, import errors, skips, expected failures and unexpected successes close the gate. A common source/installed count is insufficient.

The build checks the copied test scope after document-link validation and before external build commands. Both ordinary and supplied-source/wheel verifier paths enforce scope before environment creation and application work. The existing-output refusal remains first. No CLI option disables these checks.

## Fixed financial reference

The unchanged [financial reference](../stage6/financial-reference.json) is 70,721 bytes, SHA-256 `4abda380a19acd4cdfed97a46b6fb15528f32b8ef308c6931815c5b03641275e`. The new helper pins that identity outside the reference. This detects accidental baseline alteration; it is not third-party source authentication or a compliance certificate.

Preflight checks `financial-reference-v1`, baseline package 0.5.1, stage2-v2, schema 3, real JSON types, safe paths and the complete name/hash/size inventory. Required groups are matrix 325, Stage 1 12 and Stage 2 36, totaling 373. Matrix settings remain 69 cases, 162 evaluations, seeds 11/29/47, 100 events, six investors and the ten explicitly named zero counters.

Core also validates the entire reference. It compares every one of the 12+36 demo files, while matrix execution remains NOT_RUN unless the full profile requests `--financial`. Full financial execution additionally compares all 325 matrix files. Each parity report binds its scope/reference identity, expected and compared counts, and the actual file inventory. Empty references cannot report successful equality. Missing output or any byte difference fails. Known producer configuration and summary files are explicitly separate from the reconciliation-report scope and are never counted among the 373 comparisons.

The generic byte-comparison helper still supports an explicitly nonempty small map; the official release gate adds mandatory complete-group validation. This preserves the earlier one-file regression while closing vacuous success.

## Evidence and limits

The separate Stage 6.1 review archive contains local RED/GREEN commands and logs, the original 375-test baseline, current source/installed identities, no-AI evidence, exact financial comparisons and final preservation proofs. These execution records are not inputs to the portable package. The attached Linux/Python 3.12 Stage 6 review is independent historical evidence, not a new local run or a GitHub result. GitHub execution remains NOT_RUN.
