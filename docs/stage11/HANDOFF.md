# Stage 11 implementation handoff

Package 0.9.0 adds a bounded saved-run provenance bundle, independent offline verifier, and local review page. It does not alter financial evaluation or record an authorization cut retroactively.

## Accepted starting point and preservation

Work started from main `6cb02dee2c2b36bd53d79c2a80dbc7ed6ae90b3f`, tree `dd8822b4b49d044d83bbbc7ed8b8c7d1140adbac`, on `stage11/run-provenance`. Main push CI `43623705822` was checked; the accepted 575-test suite was not rerun as a baseline. The existing checkout was clean and was reused without resetting work. The preceding task branch remains intact.

Financial rule `stage2-v2`, schema 5, prior v1 contracts/recovery v2, financial/runtime/policy/crypto code, historical scope anchors, and the 373-file reference remain unchanged. The only old-test edits are the two current release-metadata expressions documented in [fixture-changes.md](fixture-changes.md). All 575 old IDs and behavioral assertions are preserved; the new scope discovers 641 IDs, including 66 new tests. The frozen main experiment, training and holdout are not run.

## Implemented behavior

- `export-provenance` preserves exact saved UTF-8 run bytes and one closed read-only database observation, includes every physical candidate for listed receipt hashes, and publishes a new directory without replacement. It rejects schema changes, live sidecars, source changes and output/source-sidecar collisions.
- `verify-provenance` independently traverses saved evidence and verifies external run/configuration/capture/profile/policy expectations, complete activated policy history, available original relationships, signatures, and full signed files. Exporter-generated metadata is not the verifier's expected inventory.
- The fixed offline page supports finding, saved report, receipt, original decision, signature/policy and exact-source-line navigation and downloads. It displays CREATED / source verification NOT_PERFORMED; successful CLI verification does not rewrite the bundle.
- `demo-provenance` runs ten operational groups and 24 actual CLI cases with independent literal amounts and fixed outcomes. Its keys and operator expectations are explicitly TEST-ONLY.

Read [provenance-contract.md](provenance-contract.md) for exact formats and [five-minute-review.md](five-minute-review.md) for the walkthrough. Exit 0 means VERIFIED_FOR_CAPTURE, 3 means partial (missing full signed material, genuine legacy or ambiguous physical candidates), and 2 means invalid input or known inconsistency. Known invalidity takes precedence over missing information.

## Focused validation and retained failures

The exporter has 17 passing focused tests, verifier 27, demo/UI 11, and release integration 11. Actual runs and logs are external under `outputs/stage11-output`; this source document does not assert a future final gate or CI result. The final 641-ID source/installed suites, supplied-sdist wheel gates, profile-specific checks, financial matrix and CI results are recorded in that directory's final HANDOFF and machine records.

Development regressions are attributed to this unreleased feature, not to accepted 0.8.2:

- Missing full snapshots initially hid available-line capability or signed-byte inconsistencies behind partial. Recorded RED tests now pass with inconsistency exit 2.
- Output equal to a database sidecar initially published CREATED. Isolated RED regressions cover all three sidecar names and descendants; preflight now rejects them before creating directories. The same tests pass.
- Real Chrome file-page QA at 390 pixels exposed long finding-ID overflow (scroll width 489). A narrow wrapping fix produces client/scroll/viewport width 390. Original and corrected observations are retained.

Failed tooling attempts (outside-source import context, a mistyped interpreter path, a macOS path-alias fixture assertion), an initial conservative source-metadata-change refusal, and their successful retries are retained. They are not counted as successful application checks or defects in accepted baseline code. The browser plugin cannot navigate file URLs; native Safari and Chrome are used for actual offline validation.

## Boundaries and delivery

`run_creation_authorization_cut` remains NOT_RECORDED and `financial_recomputation` remains NOT_PERFORMED. The external capture digest pins an operator observation; a database hash alone does not prove its SQL projection. A later physical candidate is not declared the original source of an earlier saved run. Source signatures do not prove financial quantities correct. Missing full files are not reconstructed from a prefix. The v1 projection audits listed evidence and related delivery positions, not the entire database or every stream prefix.

Only task-branch normal commits/pushes and a new draft PR are authorized. No merge, branch deletion, force push, tag, release, PyPI publication, workflow dispatch, frozen experiment or heavy benchmark. Final command/exit/import, CI/artifact, browser/member hashes and archive-extraction evidence stay outside Git, avoiding a commit loop merely to document CI.
