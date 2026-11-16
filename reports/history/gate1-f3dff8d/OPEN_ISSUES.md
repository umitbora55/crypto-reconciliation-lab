# Open issues, repairs and unexecuted scope

No P0/P1 production financial defect was demonstrated by the executed finite checks. That statement is not proof that all critical defects are absent. The new validation harness did contain false-success and evidence-inventory defects; their observed paths were repaired and rechecked. One historical test synchronization defect remains open. Real-source acquisition and remote CI evidence remain blocked.

## Open confirmed defect

### VAL-P2-TEST-BARRIER-RACE — protected historical test synchronization

**Priority P2; status OPEN_PROTECTED_TEST_UNCHANGED.** The first Python-3.14 source suite executed 875 protected identities and failed `test_lab_contract_validation.ProtocolValidationTests.test_seen_failure_survives_later_truncated_result`. It expected FAILED while the watchdog reported UNKNOWN. No false PASSED financial result was demonstrated.

The test's RSS callback reads a child failure and releases a truncation barrier. That callback is a separate observer from the watchdog's correctness sampler. Depending on scheduling, the child truncates before the sampler has read the failure. A deterministic two-schedule diagnostic confirmed UNKNOWN when only the RSS observer read it, and FAILED when the actual correctness sampler read it. Three exact unchanged-test reruns passed; these do not fix the race or erase the first failed suite.

The test and production watchdog/outcome modules remain byte-identical to the accepted source. A future narrow repair should acknowledge the actual watchdog read before releasing truncation, preserve the intended regression, and prove RED/GREEN on the same revised witness. Serializing workloads may reduce exposure but does not repair this synchronization contract. The Python-3.14 supplemental installed suite subsequently passed 875 identities; it is a separate result, not a replacement source-suite rerun.

Evidence: `release-full-py314/source_tests.json`, its stderr, and `resilience/py314-diagnosis/{diagnosis.json,exact-repetitions.json,reproduce_test_barrier_race.py,deterministic-schedules/summary.json}` under the external evidence root.

## Repaired new research-harness defects

Priorities below describe trust in this research program's evidence, not institutional exploitability. Production financial source and protected historical tests were unchanged.

| Finding | Priority | Original failure | Narrow repair and actual evidence |
|---|---|---|---|
| Coverage failure identity | P1 | Python 3.14 already includes the method in its qualified unittest failure identity; appending it again made one failed row appear PASS while aggregate failures stayed 1. | Bind both unittest identity formats to the exact executed roster and reject unknown failures. Same witness RED exit 1 → GREEN exit 0; final ledger has 3,796 PASS and 1 FAIL. Two regressions and combined 67-test run passed. `audit/coverage-repair/`. |
| Acquisition inventory omission | P1 | Empty/truncated registry passed when only supplied hashes were checked. | Require nonempty unique exact request/source IDs and identity fields against the caller-selected code catalog, plus byte/size checks. Same 34-test file: nine RED failures → zero GREEN failures. Independent genuine 17-request protocol with empty results now rejects SOURCE_SCOPE. `public-data/repair-01/`; `audit/public-inventory-green.json`. |
| Property scope omission/duplication | P1 | Empty family roster produced PASS with zero cases; duplicate families produced 8 rows but 4 unique IDs and overwrote input paths. | Pin reviewed family/factor roster, reject empty/duplicate/partial scope, require exact expected/executed unique IDs. Same 10-test file: seven failing RED subcases → all GREEN. Final canonical 264-case run passed. `properties/acceptance-repair-*.log`, `properties/run-003/source-properties.py`, `properties/run-004/`. |
| Mutation baseline acceptance | P1 | An invalid unmutated control could be counted as a killed mutant. | Require all four named baseline controls to pass; INVALID_CONTROL cannot count as killed and fails acceptance. Covered by the same property repair tests. The genuinely masked quarantine mutant remains a survivor in the fixed 3/4 result. |
| Partial benchmark orchestration | P1 | PARTIAL benchmark could exit 0 and be labelled PASS by the outer command wrapper. | Benchmark now exits 3 for PARTIAL; outer runner reads typed child status and retains PARTIAL, missing summary and incomplete coverage distinctly. Dedicated runner and benchmark regression tests passed. `setup/runner-tests-final2.log`, benchmark preflight logs. |
| Same-count outer-gate substitution | P1 | 22 invented property families or 33 invented resilience IDs satisfied count-only validation; contradictory expected/actual rows could retain passed=True. | SHA-pinned `validation-runner-roster-v1.json`, exact families/factors/IDs and expected==actual. Both unchanged independent probes now reject; genuine canonical property/resilience summaries still accept. `audit/runner-review-01/`. See provenance limitation below. |
| Benchmark event-count metadata | P2 | A 112-event input with metadata events 100 / seed 79 preserved the expected balance and passed while reporting 100 events. | Check actual event count and seed domain in shared worker loading and narrow validation. Exact 112/100/79 witness now rejects. `audit/findings.json`, `audit/followup-green.json`, benchmark preflight regression logs. |
| Empty/duplicate benchmark profiles | P2 | Programmatic empty or duplicate profile selection lacked a valid declared workload denominator. | Reject empty/duplicate profiles; retain exact finite profiles and five-repeat protocol. Covered in benchmark preflight tests; do not infer that any missing timing profile completed. |
| Direct offline acquisition guard | P2 | Direct fetch did not honor NO_NETWORK independently of the outer runner. | Direct fetch now rejects NO_NETWORK=1 before creating output or opening network access. Verified by public-data regression controls. |

A normal zero-test unittest discovery on this runtime exited 5 and the original wrapper returned FAILED. That specific probe did **not** reproduce false success; do not add it to the defect count. An explicit empty-run guard was nevertheless added to the outer runner.

## Evidence preservation error and qualified replacement

**VAL-P2-AUDIT-PROVENANCE; status DISCLOSED_LIMITATION.** An independent probe wrote to a fixed `runner-scope-red.json` name. Re-executing it after repair overwrote the original on-disk RED with GREEN. The overwritten GREEN bytes were retained, and the misleading filename removed. The initial observation survives in earlier tool output/messages, but no untouched raw RED JSON file is claimed.

A replacement proof uses an external copy of the final runner with only the latest roster-guard patch reversed. The exact unchanged probe reproduces false acceptance there and rejects under the actual final runner. This is labelled RECONSTRUCTED_BEFORE_GUARD, with a complete reversal diff, command/cwd/exit/stdout/stderr and source/probe hashes. It is not presented as a pristine historical source snapshot. `audit/runner-review-01/manifest.final.json` covers the retained proof.

An earlier properties follow-up audit file was likewise overwritten and its original observed text restored from captured tool stdout. It is a transcript reconstruction. Primary properties repair evidence instead comes from the separately retained unchanged regression test file, original harness source snapshot and RED/GREEN logs. Both provenance errors are recorded in `audit/provenance-errors.json`. These limitations are part of the delivered evidence and must remain visible in later summaries.

## Access blockers and incomplete required evidence

| Item | Observed status | Required next action / limit |
|---|---|---|
| Treasury and SEC real records | DATA_UNAVAILABLE; all planned financial/documentation requests failed at proxy tunnel; zero real equalities | Apply official-domain access, rerun into fresh directories, review actual field dictionaries/terms, then validate direct cash arithmetic. Until then PUBLIC_REAL_DATA_INTEGRATION cannot pass. |
| BIS source review | DATA_UNAVAILABLE for both official pages | Obtain permitted access and verify actual publication content/date before using regulatory context. |
| GitHub historical/current CI | UNVERIFIED_REMOTE; API Forbidden despite working Git read | Enable authorized api.github.com access; retrieve exact run/job/artifact identities. Do not infer remote CI from local test success. |
| Comparative measurements | PARTIAL:45 completed trials at100/1k/10k;100k production TIMEOUT | Remaining100k not run. Full semantic superiority remains INCONCLUSIVE because baselines are narrower. The timeout POSIX exit was not captured; completed trial exits are0. |
| Protected Python-3.14 source gate | FAILED once; test race diagnosed and left open | Retain failure. A narrow synchronization repair and corresponding release-scope update remain necessary; this program preserves the protected test bytes. |

## NOT_RUN / not evaluable inventory

- No verified real Treasury equality, real SEC file-quality population or injection experiment over real rows.
- No real institutional transaction/custody ground truth, natural-error precision/recall, cost savings, incident reduction, SLA or compliance certification.
- No macOS arm64 execution, million-event benchmark, months-long soak, physical power failure or physical filesystem exhaustion.
- No valid end-to-end maximum-size replay or allocation of the complete 16,777,216-node parsed JSON boundary; component ceilings were tested separately.
- No dependency-advisory/CVE clearance or exhaustive secret/PII/source-to-sink security review. Bounded source triage is not a certificate.
- No frozen ML experiment generation, training or final holdout re-evaluation.
- No unmeasured p99 claim, banking savings percentage, annual loss model, paid API or paid infrastructure experiment.

The program's final decision must preserve these independent outcomes. Passing finite local checks does not close the real-data or remote-verification gaps, and no open P0/P1 false-success defect may be hidden behind an overall readiness label.

## Publication-time CI observation

A later public-web fallback retrieved historical run [43741674664](https://github.com/umitbora55/crypto-reconciliation-lab/actions/runs/43741674664): the GitHub page shows Success for `b2df4f1`, 11m29s and four artifacts. Artifact bytes and authenticated job logs remain unverified. The initial research commit `f8fe98a` was pushed normally; its public workflow run43925469151 was In progress at this observation. API/GraphQL requests still return Forbidden, so draft PR creation failed. Final later observations belong to the external `VALIDATION_HANDOFF.md`, not a claim that the earlier API requests succeeded. Raw page bytes and hashes: `inventory/web-ci-observations.json`.
