# Five-minute review: offline execution replay

## 1. What I wanted to check

A recorded context tells me which inputs were observed with a saved run. I also
wanted to answer a narrower computational question: if I have those exact input
bytes and the expected execution identity, can the preserved financial engine
produce the complete saved answer without the original database?

The feature uses `recorded-execution-v1`, `all-known-receipts-v1`, `stage2-v2` and
schema6. It adds no migration or runtime dependency. It does not obtain an
expected ID from the bundle it is checking.

## 2. Run a small demonstration on another machine

Use Python3.12 or later and the supplied wheel in a new directory. Replace the
wheel path below with the actual downloaded file; no editable install is used.

```sh
python3 -m venv replay-core
replay-core/bin/python -m pip install /absolute/path/crypto_reconciliation_lab-0.11.0-py3-none-any.whl
replay-core/bin/python -I -m crypto_reconciliation_lab demo-execution-replay --output replay-demo-new
```

The fixed seven cases include clean7/4/11, an actual +1 custody difference,
an old knowledge cut after its source database becomes unavailable, a wrong
external pin, a wrong numeric result, a wrong trace and a genuine protected
0.10.1 pair. The last case consumes previously recorded inputs; it does not
re-authorize or verify signatures and does not need cryptography installed.

Inspect `replay-demo-new/summary.md`, `catalog.json`, the two authoritative files
under each `cases/<id>/`, and actual command/stdout/stderr/result evidence under
`commands/<id>/`. Demo pins are explicitly TEST-ONLY observations from a real
recorded call or independently identified historical fixture. A false answer's
locally recomputed pin is never labelled an institutional trust root.

For an independent exported pair and separately selected execution identity:

```sh
replay-core/bin/python -I -m crypto_reconciliation_lab verify-execution-replay \
  --context /absolute/path/context.json --run /absolute/path/run.json \
  --expected-execution-id EXTERNALLY_SELECTED_64_LOWERCASE_HEX_ID \
  --timeout-seconds 30 --output independent-replay-new
```

The output must be fresh. Context/run can be moved to another directory. No DB,
SQL script, model, downloaded module or URL can be supplied. Existing targets
and authoritative inputs are never overwritten.

## 3. Follow the calculation

The supervisor reads each finite regular input once and gives those same bytes
to one child. The child validates canonical context, the raw saved-run hash,
canonical financial ID, request identity, external execution binding, full SQL
inventory and recorded original acceptance epochs. It validates actual rows
and references instead of trusting a completeness flag or selected-evidence
subset. Raw SQL TEXT, physical IDs above2^53, duplicates and quarantine survive.

Only configuration, cuts and captured records/receipts enter the adapter. Its
two fixed tables become query-only. It delegates to unchanged `Store.known`
and calls unchanged `engine.reconcile` once. The saved answer enters only the
comparison after calculation. A complete empty inventory can therefore replay
its genuine INCOMPLETE result.

The entire parse, validation, computation and comparison share the child
deadline. Limits and preflight growth checks are explicit in the
[contract](replay-contract.md). This is not a portable hard-memory guarantee.

## 4. Read the verdict correctly

| Replay result | CLI exit | Meaning |
| --- | ---: | --- |
| REPRODUCED | 0 | Full canonical financial answer and ID match |
| DIVERGED | 1 | Valid bound recorded inputs produced a different complete answer |
| ERROR | 2 | Input, supported-scope, limit, deadline, computation or publication failure |

Financial states are separate. A recorded custody deficit of +1 can be correctly
reproduced. The verifier reports stable typed JSON Pointer differences; capped
diagnostics do not cap full equality or the total difference count. Completed
comparison evidence is retained if later report publication fails.

The report hashes the engine/replay modules actually imported now. It says
`original_executable_identity=NOT_RECORDED`,
`source_signature_verification=NOT_PERFORMED`,
`run_actor_authorization=NOT_DEFINED` and
`independent_financial_algorithm=NOT_PERFORMED`. Reproduction does not prove
original database completeness, asset existence, a second financial algorithm
or compliance. The independent integer oracle remains a separate release check.

## 5. Inspect verification and distribution

New tests live in separate `test_execution_replay*.py` files. They include
genuine old producer bytes, financial/correction/time cases, every physical input,
structurally valid rehashed numeric/trace negatives, deterministic test-owned
worker interruption, publication conflicts and isolated CLI consumption.
Test-only comparator mutants demonstrate sensitivity; they are not claims
that the previously released version contained a replay bug.

The [fixture record](fixture-changes.md) explains the only three current-version
metadata substitutions in old tests. Their assertions,778 historical IDs and
old contracts remain anchored. The normal release gate builds a wheel from the
extracted sdist and compares expected, discovered and executed unique test IDs
in source and clean installed runs. Its financial gate compares69 cases,
162 evaluations and373 fixed reference files. Core/auth-only keep their small
profiles; their full suites are not claimed as executed.

See the Git-external Stage13 HANDOFF and command records for actual counts,
failures, artifact hashes, final commit and CI results. Final CI evidence is not
committed back into this source, avoiding a new verification commit loop. The
frozen AI experiment, training and final holdout are not run by this feature.
