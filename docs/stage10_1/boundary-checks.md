# Independent relational boundary checks

The additional `test_source_auth_sql_consistency.py` file uses the unchanged real
auth demo, or the preserved independently reviewed 0.8.0 bundle when the explicit
`SOURCE_AUTH_CONSISTENCY_BASELINE` environment variable is supplied. It edits
report evidence only and independently updates each manifest member hash and
size. It does not call a runtime or verifier helper to derive an expected result.

Five test identities cover sixteen rejection subcases:

- JSON boolean values in integer SQL primary/composite identities and foreign
  references, including decision epoch and attempt effect sequence.
- Missing auth-status tables/protection and an active-policy identity that
  contradicts retained SQL.
- An effect and response jointly changing an error while the physical receipt
  retains the original error.
- A fresh case importing an older rejection or an unreferenced normalized record.
- The lost-ACK boundary claiming a replay, different input bytes or plan, or an
  extra unreferenced normalized record instead of the actual single committed
  input effect. No sender response is invented for this interrupted transaction.

The final test-file SHA-256 is
`7cee6fadc50e9d9836e1b3d555909274d742e0799b02f3b4b07386285af5a07b`.
Its preserved 0.8.0 run produced sixteen rejection-expectation failures and zero
setup/import errors. The exact matching-file GREEN record belongs outside Git
with the final execution evidence.

The separate outside-Git `audit_extra_probes.py` drives actual CLI calls against
the same independent positive bundle. Its two positive checks retain the original
bundle or reorder nonsemantic SQL inventories; nineteen negative checks vary
identities, required fields, historical cuts, core errors and worker responses.
Each command records its own exit code and output. The orchestration script's exit
code is not substituted for an individual negative verifier result.

Intermediate attempts are retained. An early test-authoring attempt reused a
fixture directory for two fields of the same SQL table; it reported one setup
error and is not presented as semantic RED evidence. The directory names were
made field-specific before the final same-file RED/GREEN pair. An early patched
reader rejected reordered policy-epoch inventory; sorting the epoch relation
removed that accidental list-order constraint. A later independent CLI probe
showed that an extra normalized record could survive the lost-ACK boundary; the
bounded interrupted-transition inventory now requires exactly the records and
endorsements explained by its single committed receipt and decision.

These are evidence-reader checks. Financial normalization, source admission,
cryptography, policy activation, schema 5, producer/worker behavior and historical
experiment results are unchanged. The separately reported historical timestamp
UTC-underflow observation remains outside this repair.
