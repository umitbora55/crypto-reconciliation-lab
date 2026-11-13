# Stage 5.1 maintenance verification scope

The genuine starting package is 0.5.0, financial rule stage2-v2, SQLite schema 3 and the original v1 review/triage formats. This maintenance release does not relabel the historical Stage 5 implementation or alter its experiment contract, model, data, labels, queues, metrics, freeze or one-shot lock.

## Baseline and bounded inventory

`preservation_before.json` captures 3,973 actual workspace paths, including 115 source/test/tool/fixture/contract files, the explicit previous preservation roster, all Stage 5 documents, old review ZIPs and the entire bounded experiment-001 tree. Its 3,527 experiment files include all 3,525 original retention entries plus the retention manifest and a pre-existing Finder `.DS_Store`; the original retention entries all match. No old environment or unrelated historical output tree was recursively scanned.

The original macOS COW/FileProvider reader took 278.662 seconds to complete this capture. A stop requested after an observed stall raced the completed capture and the first baseline test start. The parent exited 143; that test attempt has no verified completion and is not counted as passed. The original running record and interrupted attempt are preserved in `baseline_attempts`. The completed inventory and byte-verified source were reused, without repeating the full initial audit.

The technical retry used the literal existing virtual-environment interpreter, never a resolved symlink to base Python. It passed all 319 original tests in 30.571 seconds, exit 0 and zero skips. Python was 3.14.7, SQLite 3.53.4 and scikit-learn 1.9.1, with the recorded pinned dependency versions. All 373 existing genuine 0.5.0 financial output files were rehashed. The prior HANDOFF is preserved exactly at `docs/handoffs/stage5.md`.

Subsequent maintenance audit reads use direct read-only bytes with pre/post path and open-descriptor identity, size and mtime checks. This changes only new verification-tool I/O; no application I/O, SQLite connection, schema, financial calculation or old helper was changed. It is not a financial performance experiment.

## Completed release gates

`verification.json` records exact commands, cwd, interpreter/import origins, dependency versions, stdout/stderr, exits and durations. Separate text logs are under `logs`.

| Gate | Actual result |
|---|---|
| Full 0.5.1 source suite | 355 tests, 53.563 seconds, exit 0, no skips |
| Clean isolated installed suite | 355 tests, 31.865 seconds, exit 0, no skips |
| Financial matrices, each mode | 69 cases / 162 evaluations; ten zero counters |
| Demos, each mode | Six Stage 1 + eighteen Stage 2 evaluations |
| Financial byte parity | All 373 complete JSON/Markdown/evidence/run-ID files equal genuine 0.5.0 |
| Current validators on archived scope | 1,152 feature units and 384 final labels accepted read-only |
| Frozen test/challenge JSON rank | Source/installed files byte-identical to original queues, preserving findings and quantized scores |
| Valid / future-source-invalid rank CLI | Exit 0 / exit 2 with no invalid output, in source and installed modes |
| Clean no-AI installation | Core import, help, valid/invalid JSON rank passed; sklearn, NumPy and SciPy absent and not imported |

The installed suite uses `-I`, an absolute tests path, an external cwd and no PYTHONPATH. The clean AI and core environments are distinct. The 0.5.1 runtime fingerprint is `a4a37da6239c7f080b6e12c7566ef604e2fdbae74b9f60276e238a5c448d37d7`; the historical 0.5.0 fingerprint remains `f24b4293fbfc7c8c439077261b0907ca285f92aee93d1b0ef876821b36008553`.

The four already-produced replay files were copied with owned-destination readback to `stage5_1-output/rank-replay` (22,349,735 bytes). `rank-replay-retention.json` binds their original commands, hashes and maintenance identity. This retention did not rerun scoring.

## Independent read-only historical checks

The supplied independent metrics probe performed 13,723 field/identity/count comparisons. This number is not a unittest count. The historical truth/protocol probe inspected 794 recorded files, 117,504 provenance references, 216 known OPEN train fit rows, old freeze/lock bindings and archived H proofs. Neither probe fitted a model or called the financial engine, main generator or final evaluator.

The historical implementation-hash check ran against the genuine captured 0.5.0 tree. The original probe sources and external evidence ZIP hash are recorded. A separate truth-probe copy changes only its fixed global log destination to a new task-owned output path; all computations and assertions remain unchanged. These read-only probes supplement the new red/green regression tests and do not replace them. The recorded model-minus-rules recall differences remain 0 on test and -0.0208333333333333 on challenge.

## Preservation and fixture exceptions

The final focused audit checked the same 3,973 paths. All 3,961 protected paths and all 3,527 experiment files remained byte-identical; the twelve possible exceptions are explicitly listed. Eleven had changed when this audit ran; current HANDOFF publication is the remaining authorized documentation change. Old Stage 5 documents/ZIPs, all sixteen original-271 test files and every other non-excepted Stage 5 test file remained unchanged.

`fixture-changes.md`, `.json` and `.diff` document the four authorized synthetic setup exceptions. All existing assertion calls in the three affected test methods are AST-identical. The values/labels/literal_model/reidentify helpers remain source-identical, and every other pre-existing function in those files is AST-identical. No original test was removed, skipped or given a looser tolerance.

Archive extraction results are recorded separately after final packaging. No main training, main generation, main final evaluation, heavy benchmark/profiler, live integration, UI change or Stage 6 implementation was performed.
