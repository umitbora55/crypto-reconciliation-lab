# Gate 4 research test runner review

The research runner requires exact static, discovered, started, successful and
completed test identities. Empty, duplicated, substituted or missing lifecycle
outcomes cannot satisfy PASS merely because no error was reported. This remains
a source-bound local test record, not an independent institutional trust root.

Nine regression methods exercise the actual `run()` and `TextTestRunner` paths
with finite synthetic suites. Only discovery and source inventory are replaced
by fixed fixtures; production code is unchanged. The witnesses cover normal
body execution, a substituted `TestCase.run` that calls start/stop without any
outcome, absent completion, duplicate success/completion, a same-count substituted
success identity, wrong historical scope, and malformed inventory metadata.

The initial lifecycle correction already existed when the runner was copied for
this review. No pre-correction lifecycle RED is claimed. The unchanged nine-method
witness then produced actual RED exit 1: three subtest failures because JSON
`true`, `1.0` and `445.0` compared equal to integer counts, plus one missing-field
KeyError. Explicit metadata field/type validation now rejects these cases with
the inventory error. The same witness passed on Python 3.12.14 and 3.14.10, both
actual exit 0. No test body or expectation changed between RED and GREEN.

Evidence is `/workspace/validation-gate4-evidence/crash/runner-review`:
the pre/post runner bytes, identical witness copy, actual stdout/stderr and
`red-green-proof.json` containing hashes, commands and observed exits. This is
research infrastructure validation; it does not rerun or reclassify the original
875 application tests.
