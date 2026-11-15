# Offline execution replay contract

Package 0.11.0 adds `execution-replay-report-v1`. The financial rule remains
`stage2-v2`, schema remains 6, and all earlier formats/anchors remain unchanged.
This contract is written before the implementation. The accepted starting main
is `9db7fd80dcd32d7bada9ff7e4054eb083254da8e`, tree
`7b69077a9db6127b2f381a4df2b80c6996f1e6d7`.

## Claim and explicit inputs

The supported claim is: recorded inputs bound to an externally selected execution
identity reproduce the complete saved financial result using the supported rule
and the engine actually running now. This is same-engine reproducibility, not a
second financial algorithm, proof of assets, actor authorization, signature
verification, external proof of complete original database capture or compliance.
The original executable identity was not recorded by Stage12.

Public API:

```python
verify_execution_replay(context_path, run_path, expected_execution_id,
                        *, output=None, timeout_seconds=30)
```

It returns a structured report, including controlled input/operation errors.
CLI `verify-execution-replay` accepts only `--context`, `--run`, required
`--expected-execution-id`, optional `--output` and `--timeout-seconds`.
The expected ID must be exactly 64 lowercase hexadecimal characters and is
never obtained from a supplied file. There is no DB/URL/module/SQL/model input.

Only the two explicit files are read and verified. `execution.json`,
`summary.json`, `summary.md`, unrelated files and enclosing-directory membership
are outside the verification claim. The five-file recorded export is unchanged.
Both authoritative files can be relocated without the original source database.

## Read, identity and structure

Read each supplied regular file once through a no-follow file descriptor with a
finite byte ceiling. Reject final-component symlinks, missing/nonregular files,
an observed identity/size change during the read, and byte overflow. Parent
directory aliases are canonicalized; no remote filesystem identity is inferred.
The exact read bytes, rather than a reread or reserialized surrogate, enter the
child and the recorded input hash/size proof.

Closed support set: `recorded-execution-v1`, schema6,
`all-known-receipts-v1`, `stage2-v2`. The child checks exact fields and types,
configuration, normalized cuts, request ID, request digest/profile/rule,
canonical context bytes, raw run hash, canonical saved run identity and existing
execution `binding()` against the external ID. Raw run serialization may differ
in whitespace/key order while its bound raw hash remains correct.

All required tables and fixed columns, SQL types/nullability, exact 64-bit integer
identities, unique keys, eligible physical receipt coverage, complete reference
relations and actual row counts are checked. Bool is never an integer identity.
All captured rows remain available, including duplicates, quarantine, old report
versions and valid unselected rows. Explicit complete empty tables are supported;
missing tables, missing links and false counts are errors. Existing stored
inventory, selected-evidence, observed policy head and original COMMITTED
acceptance-epoch semantics remain authoritative. CURRENT/HISTORICAL replay
decisions do not become new original admissions. Wrong old epoch summaries fail
integrity; correct historical context bytes/identities remain valid.

Reuse existing pure parsing/hash/configuration/inventory checks. Do not call the
DB reader or exporter during verification, invent SQL mirrors, restore admission
prefixes, invoke ingest/migration/auth crypto, or repair raw/payload SQL TEXT.
Before any review validator creates a derived asset/investor Cartesian set,
compare actual finding count with `len(assets) * (len(investors) + 1)` using
bounded integer arithmetic. Similar derived scopes must be checked against
their actual lists before allocating expansion sets.

## Input-only calculation

The adapter constructor accepts only configuration, recorded cuts, and captured
records/receipts. It creates two fixed tables in a private `:memory:` SQLite
connection and inserts using fixed columns and bound parameters. Original IDs,
TEXT, NULL, time, status/error and same-hash physical candidates are preserved.
After loading, `PRAGMA query_only=ON` prevents writes. `known()` delegates to the
unchanged `Store.known`; engine receipt/raw and MIN(received_at) queries read
those captured inputs. `save_run()` only returns a digest of the newly computed
result and that result; it persists nothing. The adapter never receives saved
run/findings/ledgers/trace/evidence, and never selects input by selected_evidence.

After validation the unchanged engine is called exactly once. No recorded
same-request cache/retry path is involved. Rule implementation/module selection
is fixed in code. Canonical complete payload and canonical run IDs are compared,
including configuration/cuts, ledgers, traces, correction groups/effects,
findings, provisional values, issues and evidence. Diagnostic truncation never
short-circuits the actual comparison. Typed differences use sorted JSON Pointer
paths, with JSON types and bounded value previews; order in arrays matters.

## Report and exit semantics

`status` is REPRODUCED (exit0), DIVERGED (exit1), or ERROR (exit2).
Successful reasons are REPLAY_REPRODUCED / REPLAY_DIVERGED. Controlled error
reasons are REPLAY_INPUT, REPLAY_UNSUPPORTED, REPLAY_INTEGRITY, REPLAY_LIMIT,
REPLAY_TIMEOUT, REPLAY_COMPUTATION and REPLAY_OUTPUT. An unknown/incomplete child
result is never a successful comparison: REPLAY_LIMIT/exit2.

`replay_state` preserves REPRODUCED/DIVERGED once comparison completes, even if
later report publication fails and top status becomes ERROR/REPLAY_OUTPUT.
`operation_state` is COMPLETE or ERROR. `completion` separately records
validation, calculation and comparison as COMPLETED or NOT_COMPLETED.
`comparison` carries state EQUAL/DIFFERENT/NOT_EVALUATED, equal bool/null,
total_differences, retained differences and truncation. Financial states are
separate summaries: a faithfully reproduced financial MISMATCH, INCOMPLETE or
CONFLICT returns REPRODUCED/exit0.

Reports include expected/derived execution IDs, actual input sizes/hashes,
context hash, saved raw run hash, saved/recomputed canonical run IDs, captured
input counts, completion and financial state summaries. Financial summary
details are bounded independently of the full comparison; total counts and
truncation are explicit. Runtime identity records actual package, Python,
SQLite, rule and hashes/origins of relevant imported engine/replay modules.
`original_executable_identity=NOT_RECORDED`,
`source_signature_verification=NOT_PERFORMED`,
`run_actor_authorization=NOT_DEFINED`, and
`independent_financial_algorithm=NOT_PERFORMED` remain explicit. The external
expected ID supplies a caller-selected pin, not institutional authentication.

## Finite work and publication

| Limit | Numeric ceiling |
| --- | ---: |
| Each context / saved raw run | 16 MiB |
| Combined authoritative input | 32 MiB |
| Canonical request | 16 KiB |
| SQL value | 4 MiB |
| Eligible receipts / all captured rows / epochs | 10,000 / 50,000 / 256 |
| JSON nesting / aggregate parsed nodes | 1,024 / 16,777,216 |
| Canonical recomputed financial payload | 16 MiB |
| Serialized replay report / child output | 4 MiB |
| Retained diff entries / value-preview characters | 100 / 256 |
| Retained financial-detail entries | 100 (complete summary counts retained) |
| Child deadline | default30s; integer1..60s |

Depth/node limits are explicit additional limits; the child uses a finite4096
recursion setting so a lower interpreter default does not silently replace the
declared depth boundary. There is no portable hard-memory guarantee.

A command-specific subprocess handles all data-dependent JSON parsing,
structural validation, computation and comparison after the finite input read.
The parent enforces the deadline, terminates and reaps an unfinished child, and
requires one complete bounded result. There is no production fault flag/env
endpoint or hidden retry. Deterministic timeout tests use test-owned workers.
No network, source DB, AI or crypto dependency is needed for consuming either
legacy or previously recorded protected inputs.

Optional publication uses one canonical destination, with final-link/existing
target checks before mkdir, protection against either authoritative input path
and no-overwrite atomic directory publication. It writes `report.json` and
`report.md`; failure leaves original inputs/targets intact and no successful
partial report. A completed divergence is preserved in the returned report if
publication fails. Stdout always contains the structured operation result.

## Acceptance inventory

New separate tests cover literal clean7/4/11 and custody+1, financial incomplete
and conflict, old/new cuts and report versions, VOID/REPLACE/correction-before-
target/competition, full physical input loading, protected original epochs,
real old0.10.0/0.10.1 contexts, IDs above2^53, alternate raw serialization,
escaped Unicode quarantine, complete empty input, binding/relationship negatives,
two rehashed structurally valid semantic divergences, honestly rebound changed
inputs/output, relocated files with source unavailable, deterministic worker
failure/deadline, publication preservation and source/installed dependency bounds.
Expected values are literal or independent fixture facts. A missing old command
is not a baseline financial bug. Test-only hash-only/answer-fed mutants are
labelled as comparator sensitivity checks, not historical product findings.

A fixed small `demo-execution-replay` catalog includes clean, custody+1, old cut
with unavailable source, wrong external ID, numeric divergence, trace divergence
and pre-recorded protected consumption. Its coverage/results/CLI exit evidence
are independently pinned by release checks; deleting catalog/cases cannot PASS.
No new large experiment, UI, main merge or frozen model run is part of Stage13.
