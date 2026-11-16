# Gate 2 scope composition and independent audit

16 November 2026. This appendix preserves the original validation results and
their NOT_READY decision. It records finite checks, not institutional assurance.
External evidence paths below are relative to
`/workspace/validation-gate2-evidence/`.

## Protected population and the explicit fixture exception

The historical population remains **875 test identities in 94 files**. All
thirteen release inventory/contract files, including the 375-ID independent
anchor and the complete 0.11.1 contract, remain byte-identical. The financial
reference remains byte-identical. No financial engine file changed.

The corrected synchronization fixture admits exactly the correctness sampler's
successful read before releasing the child truncation barrier. Its 31 assertion
ASTs, twelve local test identities, expected FAILED verdict, worker payload and
budgets are unchanged. Its complete file changes from 13,038 bytes / SHA-256
`6fae4f3eed3bd16356bf71c15630b155daf8d6b6747c62509e0be6e0e92ecd17` to
13,062 bytes / SHA-256
`56d0ced238d9bc657a7d4308c14c72faac6022735906e776a1bfbdc1c11daaa1`.

Two preservation tests directly compared every historical file with its old
hash. Consequently, the authorized synchronization repair initially produced
two additional, genuine scope assertion failures. The retained focused runs
executed eight tests: six passed and two failed. Evidence:
`audit/historical-scope-conflict-001/`. Those failures were not hidden by changing
hash semantics or refreshing old expected contracts.

The reviewed ancillary change explicitly projects an admitted current file back
to its pre-Gate-2 bytes before those historical comparisons:

```python
self.assertEqual(
    scope.byte_identity(scope.restore_gate2_fixture_source(ROOT, name, (ROOT / name).read_bytes())),
    expected,
)
```

This changes one comparison-input expression in each of
`test_execution_replay_scope.py` and `test_replay_maintenance_scope.py`. The latter
also explicitly projects its `raw` setup input before its unchanged
`methods(restored) == methods(raw)` assertion. The first implementation exposed
that necessary AST-comparison cascade; its genuine intermediate failure and
source snapshot remain in `audit/scope-composition-intermediate-001/`.

**The two scope tests' assertion ASTs are not claimed identical.** Their assertion
operations and old expected values remain unchanged; the explicit input
projection is the declared exception. Removing only the two/one admitted
projection calls recovers each original complete AST. The synchronization test's
assertion ASTs are identical. Every changed file reverses byte-for-byte to its
independently retained original from commit
`f3dff8dd00837ac7ce6e9bb687dd4861f790cbac`.

The separate [exception contract](../../contracts/validation-gate2-test-exception.json)
has exactly three paths, 7,360 bytes and SHA-256
`c4cef1efe054561daf139a272e75e97455f15d91dc6c57cac7f8c9b1b62dbddc`.
`release_test_scope.py` hardcodes that size/hash and fixed path roster. Validation
does not generate or refresh them from candidate files. The current preflight
requires all three corrected file hashes, exact reversals, unchanged test
identities and declared assertion proofs. `byte_identity` still returns the real
length and SHA-256 of its input.

Historical metadata restoration first reverses an admitted Gate-2 change, then
uses the unchanged historical restoration rules. The helper resolves its own
source distribution's contract; it does not reach back into the checkout. The
new contract is included through one explicit path in each release build
allowlist. The historical `scope_identity` remains unchanged, and the preflight
reports `gate2_fixture_exception_identity` separately.

## Executed scope checks

| Population | Executed | Failures / errors / skips | Result |
|---|---:|---|---|
| Historical `test_*scope*.py`, Python 3.12 | 78 | 0 / 0 / 0 | PASS |
| Same historical scope modules, Python 3.14 | 78 | 0 / 0 / 0 | PASS |
| New Gate-2 scope regressions, Python 3.12 | 10 | 0 / 0 / 0 | PASS |
| Same new scope regressions, Python 3.14 | 10 | 0 / 0 / 0 | PASS |
| Complete file/ID preflight | 94 files / 875 expected IDs | No omitted, extra or unreviewed file | PASS |

The ten new checks reject changed bytes in each admitted file, substitution of
old bytes for the corrected fixture, consistently rehashed candidate claims,
missing/empty/substituted exception contracts, omitted/extra files,
empty/duplicate/omitted/substituted IDs and caller-controlled scope changes.
A copied-source control corrupts only that copy's contract and confirms that
historical restoration cannot borrow the valid checkout contract.

The first Python-3.14 release preflight rejected the new assertion proof before
executing tests. Python 3.14's default `ast.dump` omits empty lists such as
`keywords=[]`, whereas Python 3.12 includes them. This was a new scope-harness
portability defect, not an application regression. The repair explicitly renders
empty fields on newer Python versions; all previously reviewed assertion hashes
remain unchanged. The three current assertion lists match byte-for-byte across
both runtimes under that explicit rendering. The original failed preflight
remains in `release-full-py314/verification.json`, and the direct representation
comparison is in `audit/ast-version-difference-001/`.

Final commands and stdout/stderr are in
`audit/scope-final-002/{py312,py314}/`; the earlier successful 3.12-only checks
remain in `audit/scope-final-001/`. These are repeated checks, not distinct new
test identities. The authoring originals and earlier candidate contracts
remain in `audit/scope-exception-authoring-001/`. These finite controls are
separate from the required full source/installed gates; their final results
belong in the Gate-2 handoff and release records.

A second reviewer independently checked the final helper/contract hashes,
reversed all three files to the Git-pinned originals, confirmed the other 91
historical files were unchanged and statically enumerated exactly 875 unique
historical IDs. That static cross-check is separate from actual execution:
`independent-final-review/scope-independent.json`.

## New race-evidence helper false-success finding

The first Gate-2 race helper accepted an exact-named method decorated
`unittest.expectedFailure` whose assertion failed: it reported PASS and exit 0.
`unittest.wasSuccessful()` permits expected failures, and the helper did not
record that counter or independently admit source bytes. This was a research
evidence-gate defect, not a financial engine defect. The actual protected-file
stress runs contained no expected-failure decorator and remain distinct evidence.

The unchanged synthetic counterexample is retained at
`audit/race-expected-failure-001/`. The repaired v2 helper admits only the two
reviewed complete original/corrected test-file identities, records actual
executed IDs and all failure classes, and requires actual sampler observations
for scheduled success. The exact counterexample then rejected before import
with `ERROR / TEST_SOURCE_IDENTITY`, executed 0, exit 2. Fresh evidence:
`audit/race-expected-failure-002-green/`. Source admission is the rejecting control
in that independent GREEN probe; it is not presented as a separate observation
of the expected-failure counter branch.

## Benchmark evidence omission finding

The new benchmark's first archive consistency gate accepted a complete
15-trial synthetic audit record with `input=null`, empty artifact proof objects
and empty SQLite settings. Consistently equal omissions across three methods
were enough for its equivalence calculation. This did not represent actual
measurements and was explicitly labelled as a synthetic audit record.

The immutable candidate, original selected source bindings and exact original
validator bytes are retained in `audit/benchmark-missing-proof-002/`. The durable
probe reproduced the acceptance against those original bytes at
`audit/benchmark-missing-proof-red-repeat-001/` with exit 1. The earlier `-001`
exploration correctly rejected missing phase measurements; it is not counted
as a false-success finding.

The repaired validator requires an independently selected evidence root,
nonempty valid path/hash/size proofs, retained input bytes and exact finite input
semantics, command/time/stdout/stderr linkage, artifact retention proofs and
valid SQLite settings. Retained 100-event databases/exports are checked against
their recorded hashes and reread. Larger intentionally omitted artifacts remain
observed hash/size records, not independently recoverable byte evidence.

The unchanged probe and original candidate now reject. Supplying the original
candidate directory explicitly still rejects its missing input path/hash/bytes;
the original selected source bindings were retained so source revision mismatch
was not the rejecting shortcut. Evidence:
`audit/benchmark-missing-proof-green-002-final/` contains the final frozen helper
snapshot and both checks; `-green-001/` retains the earlier repaired version.
Structural consistency and retained
byte verification are not cryptographic attestations that timings occurred;
the validator keeps `measurement_authenticity=NOT_ATTESTED`.

## Fuzz value-oracle strengthening

Four accepted fuzz boundary families initially lacked an independently stated
returned-value oracle. `case.get('value', value)` compared the parser's output
with itself, making `value_equal=true` uninformative for those cases. Their
ACCEPT classification expectations were valid; the additional value-equality
claim was not established.

A finite test-owned parser mutant returned `{"not_the_parsed_value": true}` for
the unchanged depth-32 JSON input. The old helper still reported equality and
would mark that case PASS. The original helper snapshot and raw input remain in
`audit/identity-fuzz-self-oracle-001/`; the durable unchanged probe's RED replay is
`audit/identity-fuzz-self-oracle-red-repeat-001/`.

The repaired helper uses explicit expected values for depth-32, 20,000-node,
65,536-byte and valid-correction boundaries. The unchanged mutant probe now
reports `value_equal=false / value_check=CHECKED`, exit 0:
`audit/identity-fuzz-self-oracle-green-001/`. Rejected inputs separately record
value comparison as not applicable. This is new research-oracle strengthening,
not an observed financial engine defect. The fresh canonical identity/fuzz run
is `identity/run-002/`; its 240 identity cases and 102 fuzz cases are not pooled
with the superseded run or the original 264-case detection population. The
original twelve false negatives remain unchanged.

No historical RED file was overwritten during this Gate-2 audit. The previous
program's two disclosed overwrite incidents remain limitations of that
historical evidence and are not repaired retroactively by these new checks.
