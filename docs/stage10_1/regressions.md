# S10-F1 regression evidence

The independent review supplied an authentic positive 0.8.0 bundle and six
separately rehashed counterexamples. Its recordings describe the reviewer's
execution, not this maintenance task's execution. The attachment archive and all
251 payloads were independently checked before use. The review archive SHA-256 is
`16ae1c0055daa74fd9af300ae59fa6ed970e7cca507af34e869e05790a25ae40`.

`tests/test_source_auth_consistency.py` converts the six counterexamples into
rejection assertions and adds neighboring relationship checks. The file was
frozen before the production verifier changed:

```
sha256 dbbf184e055d49ffe72843d806f6fd5fe7c51a8b08cb69007cda3a3358661b61
```

Its 19 test identities cover 109 distinct negative mutations and positive
compatibility. Every mutation preserves signed input files and the operator
anchor. Its helper recalculates the byte inventory independently with hashlib;
it does not use the verifier's rehash helper or calculate an expected result with
the financial engine. Negative assertions require a `SOURCE_AUTH_EVIDENCE`
ValueError rather than accepting an arbitrary setup exception.
The six locally reconstructed R1–R6 report JSON files are byte-identical to the
review attachment's six changed reports; all six SHA-256 comparisons are retained
in `red/independent-counterexample-binding.json`.

| Review case | Evidence-only change | Required result |
| --- | --- | --- |
| R1 | Remove every successful response authorization | Reject |
| R2 | Substitute another existing physical receipt | Reject |
| R3 | Contradict stream, sequence, outcome and ACK | Reject |
| R4 | Empty both successful publisher response lists | Reject |
| R5 | Contradict the policy-race worker RESULT | Reject |
| R6 | Repeat effect/link composite SQL keys | Reject |

The additional cases isolate each R3 field; require response and authorization
fields and their exact types; bind receipt result fields; reject equal-count
substitutions and response reordering; check current versus original decisions;
cover partial, replay and permanent BLOCKED responses; reject identical and
contradictory composite-key duplicates and duplicates in other SQL tables; detect
intermediate history changes; and contradict worker or operation evidence one
side at a time. Nonsemantic SQL row order and extra explanatory information remain
positive cases. The unchanged demo also retains real lost-ACK and precommit-kill
semantics: a killed sender does not acquire an invented response.

## Actual RED execution

The dedicated seven-test run used the preserved independent bundle, Python
3.14.7 and cryptography 50.0.2. It imported version 0.8.0 from the task source tree.
The production verifier was byte-identical to reviewed commit
`b8507b205c42df4dc6e6e1b241ddce235be51b21`, with SHA-256
`52b8c24c46c57158702a3744f158b03d6374e22ab2751ba01251f70ccf0fdd67`.

The positive test passed. R1–R6 each failed with `ValueError not raised`: seven
executed tests, six failures, zero errors, exit 1. Thus the RED result shows actual
false acceptance, not an unavailable dependency or malformed fixture. Exact argv,
cwd, import origins, stdout, stderr and hashes are in the external evidence
`red/provenance.json` and `red/r1-r6-command.json`, with adjacent raw logs.

A second run used an extracted immutable 0.8.0 source snapshot while the complete
same test file remained unchanged. It ran all 19 test identities: 65 negative
subcases failed because the old verifier accepted them. A separate positive
SQL-row-reordering subcase raised an error because the historical reader compared
paired financial SQL inventories in list order. That error is distinguished from
the six clean RED regressions and is retained in `red/all-regressions.stderr`.
Nonsemantic inventory ordering is explicitly part of the maintenance contract.

The first repair check, `commands/focused-green-01`, ran the same 19 identities
with zero negative-regression failures and one error in the positive SQL-order
case. That failed intermediate run is retained. The reader was then corrected to
compare SQL identities independently of row-list order; response and process
observation order remain semantic. Final GREEN execution is recorded separately.

## Reproduction and final readback

Ordinary source and installed suites create the existing real demo once per test
class. To replay the retained review bundle, set the explicit test fixture variable
`SOURCE_AUTH_CONSISTENCY_BASELINE` to its directory. This changes only the test
input; it does not change the operator anchor or bypass signature validation.

Run the new test file from the source root with the pinned auth dependencies:

```sh
python -B -m unittest discover -s tests -p test_source_auth_consistency.py -v
```

The external `run_consistency_cli.py` helper uses the same frozen mutation
catalogue, writes coherent manifests, and runs every case with an actual installed
interpreter and `-B -I` outside the repository. It records each verifier's exit,
stdout, stderr, semantic-rejection reason, import provenance and input hashes.
Its own orchestration exit is separate from the individual verifier exits.

The final external HANDOFF and GREEN command records bind the unchanged test hash
to the repaired verifier and built wheel. Failed intermediate checks remain in
the evidence package. The source documents do not invent a final commit or remote
CI result before those runs exist.
