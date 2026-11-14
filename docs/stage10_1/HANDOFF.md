# Stage 10.1 source handoff

Package 0.8.1 repairs S10-F1 in the independent auth evidence reader. The starting
worktree was clean at b8507b205c42df4dc6e6e1b241ddce235be51b21 on
`stage10/source-auth`; draft PR #2 targeted unchanged main
c49f1a1752caf3083bedc8aa797e77023c3db7d4. The attached independent archive was
verified separately: 3,162,015 bytes, SHA-256
16ae1c0055daa74fd9af300ae59fa6ed970e7cca507af34e869e05790a25ae40,
with all 251 manifest payloads matched. Its execution claims are not our runs.

## Implemented maintenance

Required ordered response coverage is tied to verified input and SQL transitions.
Response, attempt, decision, original effect and physical receipt must agree with
exact types. SQL primary/unique keys, append-only boundaries, auth status and real
worker RESULT bodies are checked. Unordered SQL inventories are compared by key.
The fixed positive 0.8.0 bundle, ACK-loss UNKNOWN, historical replay, new-key resume,
permanent BLOCKED and signed custody MISMATCH retain their meanings.

The financial engine, admission/source-auth runtime, crypto, policy, scope extractor,
producer/worker, schema 5, stage2-v2, v1 formats, auth scope and recovery v2 remain
unchanged. The 540 previous test identities and assertions are retained; the two
permitted current-release test metadata edits have reversible diffs in
[release-metadata.md](release-metadata.md). New tests and the independent negative
catalogue are described in [regressions.md](regressions.md).

## Actual RED and intermediate evidence

The six named rejection regressions ran against unchanged 0.8.0: the real positive
bundle passed, and all six negatives failed only because no rejection was raised
(7 tests, 6 failures, 0 errors, exit 1). The frozen regression file is identical
through GREEN. A separate real installed 0.8.0 CLI campaign also reproduced all
six false acceptances; its orchestration success is not a verifier rejection.

The first repaired focused run rejected all negatives but exposed a valid SQL-row
ordering case. That run remains recorded as exit 1; row comparison was corrected
without editing the producer or the frozen regression test. Exact argv, imports,
versions, stdout/stderr and subsequent results live outside Git.

The first full distribution gate ran all 564 source tests and found nine existing
error-message assertions masked by the new append-only check. The old assertions
were retained. The reader now validates each final SQL relation before the history
transition so its established diagnostic remains available. The failed gate and
its distributions are intermediate artifacts; the final source is rebuilt and all
profiles rerun. Installed tests and the matrix in that failed attempt are NOT_RUN.

## Sealed-source delivery procedure

```sh
python -B -I scripts/build_release.py --output NEW_BUILD
python -B -I scripts/verify_release.py --profile full --financial --source EXTRACTED_SDIST --wheel BUILT_WHEEL --output NEW_FULL
python -B -I scripts/verify_release.py --profile core --source EXTRACTED_SDIST --wheel BUILT_WHEEL --output NEW_CORE
python -B -I scripts/verify_release.py --profile auth-only --source EXTRACTED_SDIST --wheel BUILT_WHEEL --output NEW_AUTH
```

Final expected/discovered/executed identity equality, clean installed provenance,
69-case/162-evaluation matrix, 373-file comparison, source/installed CLI negatives,
distribution/archive hashes, actual final commit and all five CI jobs belong in
`stage10_1-output/HANDOFF.md` and its linked execution records. This source handoff
does not predeclare those later gates as PASS or create a final-CI commit loop.

No frozen main experiment, training/holdout, timestamp repair, new runtime behavior,
main merge, force push, tag/release or PyPI upload is authorized. The model history
remains 0 percentage points on test and −2.083 on challenge. The historical
`model.timestamp` year-0001 overflow is retained as a separate observation.
