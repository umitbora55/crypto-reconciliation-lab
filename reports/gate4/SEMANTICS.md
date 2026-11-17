# Gate 4 semantic witnesses

The semantic component passed **20 matched cases / 40 method executions** on
Python 3.12.14 and SQLite 3.53.1. This component result does not accept the WAL
candidate: the final decision also requires the separate performance, process
crash, authentication and portability gates. No production source, financial
rule, historical fixture, old test or default was edited.

The preregistration is `contracts/gate4-semantics-catalog.json` (13,905 bytes,
SHA-256 `eefe1a7d6654afe005c73e415e491c7b933b71fcb1f5e5519f57bd098112ef7d`).
Its literal expected values and fixed 20-case inventory existed before the first
candidate execution. `validation_lab/gate4_semantics.py` materialized and hashed
all input fixture files before running candidates. Each pair starts from copies
of one closed, initialized database, with the copied initial bytes independently
SHA-256 checked. Input bytes and initial database identities are in each result.
The catalog and input manifest are retained with the execution.

| Cases | Independently specified expectation | Result |
| --- | --- | --- |
| Clean, direct redelivery, normalized duplicate | A: I1=7, I2=4, liability=11, custody=2+9; B: 0.3, 0.2, 0.5, 0.05+0.45; physical duplicate receipts retain their identities and ordering | 3 pairs PASS |
| Same-key conflicting payload, invalid quarantine | Explicit CONFLICT/INVALID receipts, no definite financial outcome for the affected incomplete/conflicting cut, unchanged earlier saved result | 2 pairs PASS |
| Deposit VOID, deposit REPLACE | VOID gives A balances 5/4, liability 9, external 7; REPLACE gives 8/4, liability 12, external 10; one/two correction effects and target/correction/group evidence links | 2 pairs PASS |
| Late arrival and historical cuts | Missing withdrawal gives A 7/5, liability 12, external 10 and INCOMPLETE; later delivery gives 7/4, 11, 9; earlier run remains byte-identical | 1 pair PASS |
| One asset, cross-asset isolation | Exactly the selected asset set; opposing custody differences +1 and −1 remain two separate MISMATCH findings | 2 pairs PASS |
| Exact transport replay, duplicate sequence, economic conflict | Original replay receipt/result reused; new sequences produce new receipts; economic conflict is an explicit committed terminal disposition | 3 pairs PASS |
| Invalid types and oversized financial value, corrupt frames | Five INVALID receipts without accepted records; five REJECTED_FRAME effects without core receipts; durable terminal rejection remains explicit | 2 pairs PASS |
| Same transport identity with changed bytes | TRANSPORT_CONFLICT then BLOCKED; neither response ACKs | 1 pair PASS |
| Aborted input prefix | Deliberate exception after second receipt insertion rolls the entire second transaction back; only first receipt remains; replay and retry restore the 30-record clean result | 1 pair PASS |
| Shortened file with an intact committed prefix | A different snapshot plan produces PLAN_CONFLICT, no ACK, and the original second sequence remains pending | 1 pair PASS |
| Malformed/partial/oversized files | Eight explicit snapshot errors, including incomplete final JSON, missing LF, CRLF, BOM, blank lines and an oversized line; zero durable admission changes | 1 pair PASS |
| Bad protocol types and oversized payload | Seven explicit errors for malformed stream, boolean/zero sequence, non-bytes/oversized payload, excessive timeout and boolean line count; zero durable changes | 1 pair PASS |

Every successful pair compares full logical rows from **all tables**, schema
objects, BLOB bytes, integer physical receipt order, receipt status, independently
hashed raw request identity, delivery payload SHA-256 and core-receipt foreign-key
bindings. It compares complete saved run payloads, run IDs, persisted findings,
selected evidence links and canonical saved-run JSON bytes. All of those logical
snapshots remain exact after close/reopen. Both methods pass SQLite integrity and
foreign-key checks. Database layout bytes are not required to match after the
journal-mode change.

Actual PRAGMA readbacks are retained for all 20 initial connections and all 80
method open/reopen connections. The baseline observes DELETE/FULL2; the research
candidate observes WAL/FULL2. Foreign keys remain enabled. No transaction body,
commit boundary or acknowledgment policy is replaced. Successful method calls
return outside a transaction. WAL/shm presence and logical bytes are recorded
before and after close; these correctness runs are not performance measurements
and do not measure physical I/O.

A transport ACK means the terminal disposition committed. An INVALID quarantine
or REJECTED_FRAME may therefore ACK under the unchanged product contract; it is
not a claim that an economic record was accepted. The runner explicitly rejects
any substitution of ACCEPTED for those negative dispositions. A controlled
Python exception is the aborted-prefix witness, not a SIGKILL or power-loss
experiment. The separately owned crash lane supplies process interruption cuts.

## Evidence and reproduction

Raw output is `/workspace/validation-gate4-evidence/semantics/run-001/`, with
per-case/per-method `started.json`, `result.json`, complete logical snapshots,
owned databases, canonical run payloads and negative file inputs. `pair.json`
records exact equality. The source closure includes 88 files and is unchanged
before/after execution. Source fixture constructors (`demo.fixtures`,
`correction_demo.correction` and `correction_manifest`) supply inputs only; they
share product timestamp/canonicalization helpers. The new catalog supplies the
literal economic oracle, and a separate standard-library JSON/SHA implementation
checks receipt bindings. This is independent expected-value checking of these
synthetic examples, not an independent implementation of all financial rules or
external institutional truth.

Actual command (from the repository root):

```sh
.venv-validation/bin/python /workspace/validation-gate4-evidence/control/run_command.py \
  --record /workspace/validation-gate4-evidence/semantics/commands/run-001 --timeout 250 \
  -- .venv-validation/bin/python -m validation_lab.gate4_semantics \
  --output /workspace/validation-gate4-evidence/semantics/run-001
```

This command exited **0** in **2.424994 seconds**; runner body was 2.308933 seconds.
The initial retained evidence count was 36,329,677 logical bytes. Limits were one
worker, 240 seconds wall, 180 seconds CPU, 1 GiB address space, 64 MiB per file and 256 MiB
owned disk. The disk guard runs between cases; per-file/address-space/CPU limits
are enforced by the operating system and wall time by an alarm plus the outer
recorder. The outer recorder also records argv, cwd, interpreter, stdout/stderr
hashes and exit. It observed concurrently edited sibling benchmark/crash files;
the 88-file semantic execution closure itself remained unchanged.

Four new checker controls in `validation_gate4_tests/test_semantics.py` passed
with exact recorded command/exit under
`semantics/commands/checker-tests-001/`: substituted same-count receipt identity,
opposite asset amounts, unexpected asset, and changed canonical saved export.
Each negative control must raise; unchanged positive controls pass where
applicable. These small checker controls are separate from the final evidence
verifier's event-substitution and benchmark-summary falsification witnesses.

A supplementary standard-library reread at `semantics/independent-later-cut.json`
checks the captured normalized-duplicate **later** cut against the same literal
clean balances for both methods: six COMPLETE/MATCHED findings with zero
difference, 31 physical receipts, one normalized A1 record identity and separate
ACCEPTED/DUPLICATE receipt identities. It binds exact raw-result, canonical-payload
and checker-script bytes and does not rerun the product. This closes a narrower
runner assertion: that case applied the literal oracle explicitly at the earlier
cut while capturing and pairing the later cut.

For reproduction choose a **new output path**: the runner refuses overwrite.
The recorded `run-001` directory must not be reused or replaced.

## Boundaries

The canonical exports above are the exact saved-run payload bytes, not a claim
that the existing product five-file or provenance exporters accept WAL. Product
show/export, provenance capture, protected source authentication, policy rotation,
recorded-context replay, migrations, backup/restore and namespace behavior are
covered by the separate portability component. No empty authentication/history
rows here are counted as successful tests of those features. Any missing or
failed required candidate invariant there still prevents candidate acceptance.

Python 3.14, the 875-ID source/installed suites and 69/162/373 reference gates were
not rerun by this component: this is a research-only harness and there is no
production patch. Gate 3's exact historical results remain historical. No abrupt
power-loss guarantee, production durability certification, two-party institutional
data, natural-error labels, cost saving, RTO/RPO or compliance follows from these
finite synthetic witnesses.
