# Gate 2 independent final cross-review

Review date: 2026-11-16 UTC. This review checks finite evidence gates and claim consistency; it is not a security scan, a new benchmark, or a rerun of the full regression suites. It does not authorize a READY verdict. Final full-gate, exact-commit CI and archive-seal results remain the parent gate's responsibility.

Evidence root: `/workspace/validation-gate2-evidence/independent-final-review/`. The files below preserve the reviewed identities and actual bounded observations. Working-tree review HEAD was `f3dff8dd00837ac7ce6e9bb687dd4861f790cbac`; the Gate 2 files were not yet committed. Their explicit hashes, not that older HEAD alone, identify what was inspected.

## Substantive evidence-gate findings

1. **Derived benchmark statistics could contradict the trial ledger and still render.** The reviewer constructed a clearly labelled audit fixture with the exact 45 expected trial identities, all `NOT_RUN`, then changed only the stored derived summary to claim five completed repetitions and wall p50 `0.000001` seconds. `validate_record_inventory` returned `PASS`, and the report renderer emitted `|100|stdlib_integer|5|0.000001|0.000002|...|`. This is a reproducible consistency failure, not a claim that the real benchmark ran or had these timings. The renderer trusted `summary` and `comparisons` after validating the separate ledger. Fix requires recomputing or checking all derived summaries, pair counts/effects/intervals and parity annotations against the raw trials. Evidence: `summary-mismatch-candidate.json`, `summary-mismatch-observed.json`, `summary-mismatch-rendered.md`; both reviewed code files were copied before repair. **Status: REPAIRED for the retained witness.** The unchanged candidate now rejects specifically with `derived summaries disagree with actual PASS trials`, while a valid all-NOT_RUN control with recomputed absent measurements passes as PARTIAL. `summary-mismatch-green.json` binds the repaired helper and exact original candidate. Original caller-selected bindings were used so the rejection did not merely depend on the changed code hash.

2. **Missing benchmark identities could satisfy the equivalence checker.** The scope auditor independently retained a 15-row witness with `input=None`, empty artifact proofs and empty SQLite settings that received PASS/equivalence. That exact witness is at `audit/benchmark-missing-proof-002/`; `001` was an earlier, correctly rejected incomplete-phase attempt and must not be described as the successful witness. This reviewer confirmed the code path compared equal placeholder values and artifact key names without requiring complete identity values. **Status: REPAIRED for the retained witness.** The scope auditor replayed the unchanged candidate and original bindings. Without an external evidence root it rejects the missing root; with the actual root it specifically rejects `missing input path/hash/bytes`. This reviewer read `audit/benchmark-missing-proof-green-001/explicit-root-probe.json` and `stdout.txt`, confirming candidate SHA-256 `4b51b9dfe50a20d8a04f1f66de750a40199edc9f221a46f3c22ef326c8c9646c` and repaired helper SHA-256 `31af948175127c687891f62e69d065b4b3d03d09db38b8c584dab4612d0485f7`.

The repaired validator also checks retained input bytes against the finite contract, actual command/output linkage, observed SQLite settings, successful stdout, canonical export hashes and the retention inventory. These controls strengthen the evidence path; the closed witnesses are not a proof against every possible corrupted record.

Neither issue proves the normal worker produced false output. They invalidate a claim that the standalone acceptance/report path rejects these malformed or contradictory records. The captured witnesses remain even after a later successful repair. Hash consistency is separately limited: a self-issued manifest is never timing attestation or institutional authority.

## Benchmark contract labels

The current documentation correctly restricts `EQUIVALENT_COMMON_ARITHMETIC` to one finite static-cycle workload, common public Store ingestion, canonical integer projections and identical common SQLite/JSON persistence. The production method uses a research `save_run` adapter; it still builds rich evidence in memory but does not persist the full product result. Shared admission/normalization and workload generation are disclosed. This supports a restricted common-output comparison if its actual three-method matched repetitions and identity checks pass; it cannot establish equivalence for arbitrary financial histories.

The evidence/history lane remains `NOT_IMPLEMENTED / NARROWER_SCOPE / INCONCLUSIVE`. No general production speed superiority, SLA, institutional savings or risk reduction follows from the common lane. The exact synthetic input gate's ability to spot a substituted event reference does not repair the count-only manifest's original 12 false negatives.

At this review point, `BASELINE_COMPARISON.md` correctly states canonical Gate 2 timing runs are `NOT_RUN`; the quiet-window measurements were pending. Historical 10k figures and the censored 100k attempt remain separately dated. A future report must preserve partial/time-limited trials, actual post-wait process exits and five-repetition sample sizes; empirical p95 at n=5 is the observed maximum, not a reliable population tail.

## Protected scope and three-file projection

The independent `scope-independent.json` check did not invoke the project scope verifier to derive its reversal result. It:

- Read the exact hardcoded exception and historical contract byte/hash pins from the helper and compared actual files.
- Verified the 254,949-byte 0.11.1 historical contract remained identical to Git `f3dff8dd00837ac7ce6e9bb687dd4861f790cbac`.
- Checked all 94 protected files; 91 retain their historical current hashes.
- Reversed exactly the declared edits in the three exceptions and compared complete restored bytes both with the unchanged contract and `git show` at the independently named base commit.
- Independently parsed the source files and found exactly 875 unique static test identities matching the historical roster, with no omission, duplicate or substitution.
- Verified no tracked production-runtime file differs from that base commit.

The separate exception is 7,360 bytes, SHA-256 `c4cef1efe054561daf139a272e75e97455f15d91dc6c57cac7f8c9b1b62dbddc`. Reviewed helper SHA-256 is `5ad2dc398c207fb0513652f955f390c20aaf2b8effc08afa06e7f5a07e1eed38`.

The synchronization fixture preserves its assertion ASTs. The two scope tests explicitly project admitted bytes before historical hashing; their assertion-input expressions therefore change and are not claimed AST-identical. `byte_identity` still hashes actual input bytes, and the helper restores real pinned old bytes rather than inventing an old hash. Its historical cascade reads the helper-local contract. No hidden broad refresh of historical expected pins was found. Static roster/byte proof does not replace actual expected/discovered/executed runtime rosters from each required interpreter and installed profile.

## Populations and denominators

`population-independent.json` records the original inspected ledgers. The final `population-independent-v2.json` checks canonical identity run 002 after the value-oracle repair: exact 240/102 rosters, 54 accepted explicit value checks, 48 expected rejections with value checks correctly marked not applicable, unchanged scorecards and 58 distinct raw fuzz inputs. Its retained harness snapshot matches the inspected current source hash. Superseded run 001 is preserved and is not counted as additional samples.

| Population | Actual denominator | Proper interpretation |
|---|---:|---|
| Preserved original error-detection baseline | 264; TP132/FP0/TN120/FN12 | Historical fully synthetic result, not rerun or relabelled |
| Identity-reference controls | 240 | Twenty LAB control families over twelve groups |
| Enhanced clean/substitution confusion matrix | 24 of those 240; TP12/FP0/TN12/FN0 | Additional generator-authored signed facts, not independent institution authority |
| Production-helper fuzz | 102 invocations / 58 distinct byte inputs | Finite parser/time/normalization checks; not a natural-error matrix |
| Treasury raw rows | 14,226 | Raw acquisition/structural denominator across ten API files |
| SEC raw financial rows | 89,285 | Outstanding-balance rows; trailers are not financial records |
| Modern direct Treasury equations | 60 dates: 39 exact, 21 nonzero ±1 million | Zero-tolerance equality and separate rounding compatibility |
| Legacy direct equations | 32 dates NOT_RUN | No silently invented flow-total mapping |
| Adapted engine execution | 60 cases / 120 findings | Authored participants/manifests; both report roles reuse one closing source |
| Public-plus-injected format controls | 360 observations from 30 distinct rows; TP120/FP0/TN180/FN60 | Curated transformations with paired controls; not natural financial-error recall |

These populations cannot be summed into one recall, test count or independent sample size. The enhanced 24-case matrix is already a subset of the 240 controls. The 120 adapted findings do not double the number of real dates or establish two independent counterparties. Neither zero finite observed failures nor a valid LAB signature implies institutional deployment readiness.

## Source identity, packaging and remaining completion conditions

The public-source arithmetic/adapted/injected outputs were independently checked against original source bytes in [INDEPENDENT_PUBLIC_AUDIT.md](INDEPENDENT_PUBLIC_AUDIT.md). Treasury numeric reuse is supported by the actual saved Licensing text; the earlier auditor reading error and correction remain retained. SEC/site-asset rights remain unverified.

The first public `analysis-01` summary binds raw data and policy but lacks a preregistered execution-code snapshot/runtime record; it remains preserved with that limitation. Canonical **analysis-02** now supplies a fresh isolated execution from a pre-execution source snapshot. This reviewer independently verified all 94 source-snapshot file hashes, 24 raw/policy/input identities, the bootstrap, interpreter, start/completion records, 12 recorded imported module paths, original stdout/stderr and actual exit 0. No source/input changed during that run.

`public-source-bound-run-review.json` records the closure. All direct-day and injected-output JSON bytes are identical to the independently audited analysis-01 outputs; all 60 adapted input/result byte pairs and run IDs also agree, and every mathematical count is unchanged. This closes execution-source binding for analysis-02, not retroactively for analysis-01. The reviewer compared retained artifacts and did not rerun the engine.

The identity experiment retains its own preregistered harness snapshot and exact case protocol. Its production-helper source dependency is also constrained by the separately established unchanged production tree; this is not a new cryptographic execution attestation. Benchmark records bind working-tree files and a `git_head_at_start`; the latter alone does not identify uncommitted code.

The package sealer's inspected implementation requires a clean checkout, reads immutable Git blobs at the seal commit and separately preserves earlier run snapshots. This is the correct distinction: a later commit identifies delivered source, but does not retroactively prove that every earlier run executed that commit. Archive `BYTE_INTEGRITY_ONLY` PASS must not be promoted to scientific validity, complete testing or external trust.

Other independently documented research-harness repairs remain distinct from production defects:

- The race helper once accepted an expected-failure-decorated synthetic method. Its exact witness now rejects through pinned test-source admission, as retained under `audit/race-expected-failure-002-green/`. This does not erase the original Python 3.14 synchronization failure or infer that the expected-failure-counter branch was separately exercised by that source-rejection probe.
- The identity fuzz helper initially treated its own returned value as a fallback expected value. The retained depth-32 wrong-parser mutant incorrectly reported equality. The repaired helper now reports `value_equal=false`; the same witness, unchanged input hash and actual exit 0 are retained under `audit/identity-fuzz-self-oracle-green-001/`. Canonical run 002 uses explicit independent expectations for all 54 accepted invocations. Production parser behavior was not changed.
- The public harness's SEC trailer handling and official-landing-link prerequisite were repaired with retained RED/GREEN controls. The public report distinguishes the exact tested properties; the final source-bound run retains the same audited real arithmetic and row populations.
- The new scope helper initially failed Python 3.14 preflight due to AST-rendering differences. Explicit empty-field serialization fixes the helper while keeping the reviewed assertion pins unchanged; this was not a newly discovered financial runtime regression.

**No unresolved blocker remains in the specific public/source-binding, protected-scope, denominator and benchmark-witness invariants reviewed here.** That scoped conclusion is not an overall readiness verdict. Before a final readiness claim, inspect required final source/installed/profile/financial results and actual exact-head CI, and preserve all earlier failures and unrun cells. No heavy command, benchmark or full suite was run by this reviewer.
