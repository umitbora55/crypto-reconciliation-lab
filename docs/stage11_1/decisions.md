# Stage 11.1 decisions

1. **Repair only the two reviewed defects.** S11-F1 is selected-effect causality
   in the independent provenance verifier. S11-F2 is lossless SQL identity in the
   derived offline view. Neither requires financial, admission, policy, crypto,
   schema or authoritative-format changes.
2. **Use durable relationships, not clocks or array order.** Append-only attempt
   IDs express the relevant original-effect-before-replay ordering. Earlier
   attempts without an effect remain valid; the reader does not invent a past
   run-creation authorization cut.
3. **Preserve raw JSON and encode the derived view exactly.** SQLite's supported
   integer domain is larger than JavaScript Number's exact range. Encode the
   relevant identities before parsing in the browser, and derive the same view
   independently in the verifier. No new runtime dependency is needed.
4. **Keep fixed-asset verification strict.** Old lossy 0.9.0 assets may be rejected
   as `PRESENTATION_INTEGRITY`. Explain this compatibility boundary and require a
   fresh export from available source material instead of an in-place upgrade.
5. **Preserve the reviewed 641-test source separately.** Add a pinned 0.9.0
   ancestor to the new 0.9.1 test inventory without moving the existing historical
   anchors. Record the exact reversible current-release/UI-fixture exceptions;
   all other old test bytes and their behavior assertions remain protected.
6. **Keep evidence outside Git.** Real commands, RED/GREEN, source/installed
   gates, browser observation, distributions and CI artifacts belong in the
   task output. Source documentation describes stable behavior and links to the
   delivery record without a final-CI documentation commit cycle.
7. **Do not repeat the independent baseline suite.** Its original review records
   remain distinct from our own focused reproductions. Run final source and
   installed checks on the sealed 0.9.1 sdist/wheel; rerun only when a real failure
   or source change requires it. Never regenerate or train the frozen experiment.
