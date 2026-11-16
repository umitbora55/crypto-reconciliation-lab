# Gate 2: correctness-sampler synchronization repair

The named historical test's synchronization fixture is repaired. Its test ID,
all four final behavioral assertions, the child payload, and watchdog budgets
are unchanged. No financial engine or watchdog implementation changed. Full
source/installed release acceptance and CI are separate gates; these focused
results alone do not establish overall readiness.

## Original failure and narrowly corrected behavior

The original fixture's RSS callback independently read `result.json` and
acknowledged the child's failure. The watchdog's loop samples correctness before
RSS. A failure published between those reads could therefore trigger truncation
without the actual correctness sampler ever reading the failure. The original
`UNKNOWN` result was not a false successful financial calculation; it exposed
a misleading test barrier.

The corrected fixture wraps the `load()` operation used by the watchdog. It
acknowledges a `CORRECTNESS_FAILED` object only when that actual sampler obtains
the parsed object, then returns that same object. The child's subsequent
truncation cannot change the already returned object. RSS remains a constant
test-owned 1,024-byte sample and no longer controls the observation barrier.

The unchanged final assertions require `correctness == FAILED`,
`completion_state == TIMED_OUT`, non-null `observed_correctness_failure`, and
non-null `result_parse_error`. None was replaced with `UNKNOWN`, skipped,
expected-failure marked or removed.

## Exact preservation evidence

File: `tests/test_lab_contract_validation.py`.

| Identity | Bytes | SHA-256 |
|---|---:|---|
| Original at accepted task head | 13,038 | `6fae4f3eed3bd16356bf71c15630b155daf8d6b6747c62509e0be6e0e92ecd17` |
| Corrected synchronization fixture | 13,062 | `56d0ced238d9bc657a7d4308c14c72faac6022735906e776a1bfbdc1c11daaa1` |

The literal new-block-to-old-block reversal recovers every original byte. All
**31 assertion-call ASTs in the file** and every test method identity are equal
before and after. This proof covers the race test file; separately composed
release-scope metadata projections are documented by their own exact exception.

Original raw bytes are retained outside Git in
`race/original/test_lab_contract_validation.py`; `fixture.patch` and
`fixture-preservation.json` retain the exact old/new replacement, counts, SHA,
size, AST and reversal results. The historical 875-ID population remains
distinct from new research tests.

## Same deterministic witness: RED and GREEN

The canonical `gate2-race-evidence-v2` witness executes the actual unchanged test
method and preserves its assertions. For scheduling evidence only, dependency
hooks arrange a readable failure before the first correctness read, or hold
that first read before publication and make the failure readable before RSS.
The latter uses a test-owned `FileNotFoundError` scheduling barrier. It models
the specific read/publication interleaving; it is not presented as an accidental
operating-system scheduling observation. Child input code is not rewritten.

The exact same v2 helper bytes were used for all original/corrected comparisons:

| Python | Test fixture | Failure before correctness read | Failure between correctness read and RSS |
|---|---|---|---|
| 3.12 | Original exact bytes | PASS | **RED: FAIL**, `UNKNOWN` vs expected `FAILED` |
| 3.14 | Original exact bytes | PASS | **RED: FAIL**, `UNKNOWN` vs expected `FAILED` |
| 3.12 | Corrected fixture | PASS | **GREEN: PASS**, failure retained after truncation |
| 3.14 | Corrected fixture | PASS | **GREEN: PASS**, failure retained after truncation |

Each schedule executes exactly one named test. The v2 records retain actual
executed IDs, error/failure/skip/expected-failure/unexpected-success counters,
sample events, complete watchdog results, command, runtime, source hash and
stdout/stderr. All processes have bounded deadlines. Instrumentation is absent
from the following stress and full release runs.

## Uninstrumented repeats and separate research tests

The corrected source test passed **20/20 uninstrumented executions on Python
3.12 and 20/20 on Python 3.14**, with zero errors, skips, expected failures or
unexpected successes. Each repetition retained the original behavioral
assertions; the v2 helper records the exact executed identity. These are focused
source executions using isolated interpreters, not substitutes for installed
or full-suite validation.

The new `validation_tests/test_gate2_race.py` separately exercises both schedules,
asserts that RSS cannot release the barrier before correctness sampling, and
rejects expected-failure/no-op/different-ID substitute sources before import.
It contains three research tests, separate from the historical 875 identities.

Canonical commands and logs are under
`/workspace/validation-gate2-evidence/race/v2-commands.json`,
`v2-research-commands.json`, `v2-red*`, `v2-green*` and `v2-stress*`.
The original test snapshot used for RED contains the exact original test bytes
and unchanged production modules. No protected test source was rewritten during
execution. Full logs from the earlier v1 helper executions, including its
earlier 20 repeats per interpreter, remain retained separately and are not
pooled into the canonical v2 counts.

## Independent rejection finding in the research helper

Independent audit found that the first helper version trusted
`unittest.wasSuccessful()` without explicitly rejecting expected failures and
without admitting exact source bytes. An arbitrary replacement source containing
an `@expectedFailure` method could therefore obtain a false helper PASS. This
was a **research evidence acceptance defect**, not an observed defect in the
protected historical test or financial engine. It was repaired before final
acceptance and is not omitted from the record.

V2 admits only the independently recorded original/corrected full-file SHA and
size pins, requires exactly the expected executed ID, requires zero failures,
errors, skips, expected failures and unexpected successes, and requires the
actual correctness-load observation for scheduled PASS. The exact auditor
substitute input that produced RED now receives `ERROR / TEST_SOURCE_IDENTITY`,
exit 2, with zero tests executed. That refusal is a rejection success, not a
successful run of the substituted test.

Auditor RED is retained in `audit/race-expected-failure-001`; unchanged-input
GREEN in `audit/race-expected-failure-002-green`. The original helper bytes are
retained in `race/harness-original/gate2_race.py`; the canonical helper snapshot
and its SHA bindings are `race/harness-v2.py` and `race/v2-commands.json`.

## Remaining acceptance boundaries

The repair addresses a finite synchronization defect. It does not prove that
arbitrary fleeting child output will always be sampled, nor change the watchdog
contract for unreadable/unobserved evidence. The original Gate 1 failure remains
historical evidence. Final release and CI results must be read from the Gate 2
technical handoff; institutional deployment readiness is not inferred here.
