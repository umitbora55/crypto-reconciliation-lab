# Technical validation — Gate 2 revision, 16 November 2026

**Local release and research gates passed.** Final exact-head remote CI is a
separate delivery requirement. The historical Gate1 results and original failure
remain in [their preserved report](history/gate1-f3dff8d/TECHNICAL_VALIDATION.md).

| Actual population | Python 3.12.14 | Python 3.14.10 |
|---|---:|---:|
| Source historical tests |875/875 PASS|875/875 PASS|
| Isolated installed historical tests |875/875 PASS|875/875 PASS|
| Financial matrix |69 cases / 162 evaluations PASS|69 cases / 162 evaluations PASS|
| Unique fixed financial reference files |373/373 equal|373/373 equal|
| Separate research methods |134/134 PASS|134/134 PASS|

All test populations have zero failures, errors, skips, expected failures and
unexpected successes. Expected, discovered and executed historical IDs match
exactly, with each ID executed once per mode. Installed imports come from their
isolated wheel environments; source imports come from the extracted sdist.
Core and auth-only Python 3.14 profiles separately passed; they intentionally do
not execute the 875-test population.

The 373 unique financial reference files comprise 325 matrix files and 48 small
Stage1/Stage2 demo files (12+36). The source and installed demo runs each compare
those same 48 references; they are not counted twice as unique references.
Comparisons preserve full financial JSON/Markdown bytes and run identities.
No financial runtime, watchdog behavior, immutable reference or frozen ML
experiment changed. The 331-file release build manifests bind the executed
source distribution; the final Git commit is separately verified against them.

Canonical full runs are `/workspace/validation-gate2-evidence/release-full-py312-v2/`
and `release-full-py314-v2/`. Core/auth runs use the same validated 3.14
sdist/wheel. Exact command records and original logs are under `commands/`;
research source hashes/expected rosters and outputs are under `research/`.
The [compact local gate index](../evidence/gate2/local-validation-summary.json)
contains exact verification-report identities.

An earlier 3.14 Gate2 preflight failed because default AST rendering differs
between Python versions; it executed zero tests. The simultaneous earlier 3.12
attempt was explicitly stopped with actual exit -15. Both remain preserved.
Explicit empty-field rendering repaired this new validation-tool defect without
changing the reviewed fixture/contract pins; the fresh v2 runs above are the
acceptance population.

The race fixture keeps its original ID and 31assertion ASTs. Two preservation
checks use explicitly pinned historical-input restoration; those two assertion
input ASTs are disclosed as changed. See the [three-file scope proof](gate2/SCOPE_AND_AUDIT.md)
and [same-witness race repair](gate2/RACE_REPAIR.md). No test file is rewritten
at runtime and no hashing helper pretends changed bytes are original bytes.

The [independent final review](gate2/FINAL_INDEPENDENT_REVIEW.md) records bounded
research acceptance defects and same-witness repairs. Public source observations,
identity-reference experiments and benchmarks retain separate source/input
snapshots and denominators. Their finite success does not establish every
possible behavior or institutional deployment readiness.
