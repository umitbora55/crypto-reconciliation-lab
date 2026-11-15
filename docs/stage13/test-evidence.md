# Replay test evidence and historical fixtures

The new tests are separate files. No existing behavior assertion is changed.
Expected financial quantities are hand-authored literals. Fixture construction
uses the existing admission/recorded-export implementation; replay validation
and computation are never used to manufacture those expected quantities.

| Required family | New focused coverage |
| --- | --- |
| 1. Literal financial outcomes | `ExecutionReplayFinancialTests`: clean A7/4/11 and B0.3/0.2/0.5; custody difference+1; real incomplete/conflict outputs all reproduce. |
| 2. Knowledge/report history | Late withdrawal before/after; custody report revisions; old file bytes remain unchanged and reproducible after new DB data. |
| 3. Corrections | VOID, amount replacement, correction before target and competing corrections; literal balances, complete payload comparison, group/effect/trace linkage and first-known timestamp. |
| 4. Complete captured inputs | All34 physical receipts and32 normalized records reach the query-only adapter unchanged, including duplicates, quarantine, superseded report and valid unselected event. A deliberately selected-evidence-only subset fails the independent full-inventory assertion. |
| 5. Protected history | Five actual historical producer phases have original epochs `[1]`, `[1]`, `[1]`, `[1]`, `[1,2]`, attempts30/30/34/60/61 and receipts30/30/30/30/31. |
| 6. Old producers | Exact0.10.0 and0.10.1 context/run bytes; correct old pairs pass and the known0.10.0 wrong original-epoch summaries fail integrity. |
| 7. Exact bytes and IDs | Physical IDs9007199254740993 and9223372036854775807; alternate raw run whitespace; genuine escaped lone-surrogate quarantine witness. |
| 8. Empty versus missing | A real empty capture has six incomplete findings and reproduces; missing table and fabricated zero-finding output fail. |
| 9. Binding and relations | Wrong pin, cross-execution input, raw byte change, rehashing under the old pin, missing/dangling/duplicate IDs, false counts and protected relation failures. |
| 10. Semantic differences | Numeric liability, trace-only balance and finding-only mutations keep captured inputs fixed and pass structural validation; real computation returns DIVERGED with exact JSON Pointer paths. |
| 11. Claim boundary | Independently constructed changed inputs with correct changed output and a newly selected pin reproduce; the tests explicitly reject interpreting this as first-database capture proof. |
| 12. Offline portability | Export two files, relocate them, remove the test source DB tree, invoke actual CLI and verify unchanged input hashes. |
| 13. Operational bounds | Closed formats/types; byte/depth/SQL limits; cardinality checks; real killed-and-reaped child; partial/missing/oversized child results; no-follow inputs; atomic output collision/symlink/dotdot preservation. Completed divergence survives publication, runtime-identity and report-size failures. |
| 14. Release boundaries | Source and isolated-installed suites run these same tests. The small fixed CLI demo/release validator additionally checks required positive, identity-negative, semantic-negative and pre-recorded protected cases. Core consumption requires no AI/auth packages. |

## Historical provenance

`tests/stage12_1_epoch_fixture.py` is an existing immutable fixture from the
real0.10.0 producer. It is reused without edits, including its two known wrong
epoch-summary captures. No Stage13 output is labelled as an old producer.

`tests/replay_historical_fixtures.py` embeds six exact0.10.1 capture pairs.
The focused producer ran against accepted source commit
`0aa26865d5a78d6c051e1c26ad6387bdc29c8abc`, whose accepted tree became the
Stage13 starting main tree. Its imported package was actually0.10.1. The
uncompressed records document is SHA-256
`1b451781c7daa60b7c36e905935239baa591a7352c6488d92b40a849220d4e0e`.
Five pairs cover real policy activation, CURRENT replay, HISTORICAL_REPLAY and a
new original delivery. The sixth is a real invalid-record quarantine containing
an escaped lone surrogate. Canonical outer transport is preserved without
rewriting the raw receipt or saved evidence string.

The producer command, interpreter/import origin, exact hashes, execution IDs,
actual admission results and raw files are retained outside Git under the
delivery's `historical-0101` directory. Only focused fixture construction ran;
no accepted baseline full suite, frozen experiment or holdout ran.

## Comparator sensitivity and development attempts

Two deliberately defective test-only mutants are executed against the same
semantic negative assertion. Feeding the saved answer through the computation
boundary would incorrectly report REPRODUCED; the assertion catches it.
Replacing the full comparison with an unconditional hash-binding-only EQUAL
result is also caught, including the canonical-ID consistency guard. These are
new-feature test sensitivity checks, not historical product RED findings.

The first focused development run executed49 tests and exposed two reason-code
assumptions in new tests: a schema bool is an unsupported schema, and changing
only the captured profile conflicts with the unchanged supported request. The
new fixtures were corrected to assert the explicit rejection and to change both
profile declarations for a genuine unsupported-profile case. No production
behavior was changed to satisfy those two assumptions. All failed logs remain
in the external evidence. Subsequent focused runs add the independent
cardinality/mutant and late-failure cases; actual final counts and commands are
reported in the delivery HANDOFF rather than projected here.

The deadline test uses a test-owned child script and private Python seam only.
It records a real PID, SIGKILL return code-9, elapsed time and reaped process
when `CRYPTO_EXECUTION_REPLAY_TEST_EVIDENCE` is set by the test supervisor.
Production reads no fault environment variable and exposes no fault CLI option.
