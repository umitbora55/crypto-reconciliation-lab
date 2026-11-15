# Five-minute project review

I use this route to connect one financial discrepancy with its saved evidence,
then check whether recorded inputs reproduce a saved calculation. It covers the
completed 0.11.1 project; the viewer and replay have separate roles.

[Project overview](../../README.md) · [Türkçe anlatım](project-overview.tr.md)

## Prepare the two small outputs

From the project root, with Python 3.12 or later, run these existing commands.
Both target directories must be new; choose fresh names if either already exists.
Core operation requires neither AI packages nor auth cryptography. The five-minute
target concerns inspecting the outputs, not installation or CI duration.

```sh
python3 scripts/reproduce_review.py --output review-final-new
python3 -m crypto_reconciliation_lab demo-execution-replay --output replay-final-new
```

The first command produces nine synthetic scenarios and 24 saved evaluations,
the offline viewer, and a limited ranking with the existing JSON model. It does
not generate, train or evaluate the frozen main experiment or final holdout. Its
expected invalid ranking exits 2 without publishing a queue; the outer command
exits 0 only when its checks pass. The second command checks seven fixed replay
cases, including expected rejection and divergence. Those inner exits are part
of a successful demonstration, not failures of the outer command.

## Minute 1: understand the +1

Start with the preserved [ASSET_A diagram](../../README.md#example). Ledger-derived
balances are I1=7 and I2=4, so customer liability is 11. Investor reports agree:
comparison A matches. Customer custody is platform 2 plus external custodian 8,
so comparison B has expected 11, reported 10 and difference **+1**. Both inputs
are complete at this cut. The difference identifies something to investigate;
it does not establish a cause or a loss. An incomplete delivery instead prevents
a definitive verdict.

## Minute 2: follow the saved finding

Open `review-final-new/index.md`, then
`review-final-new/review/bundle/index.html` in a browser. No server is required.

1. In **Source / case**, select **Custody difference**.
2. In **Stored run**, select **Initial knowledge**; its label also includes a
   shortened run ID. These are the `custody_difference / initial` catalog entries.
3. Under **Filter findings**, set **Comparison** to **B** and **Asset** to
   **ASSET_A**. Click **Inspect** on `customer_liability`.
4. Read **Expected**, **Reported**, and **Difference · expected_minus_reported**.
   In **Reasons & links**, follow **Open evidence**. Inspect **Reports** and
   **Ledger trace**; **Open event evidence** leads to **Receipts & raw evidence**.

The page reads the original saved answer and its linked records. It does not
recalculate balances. **Run identity and original payload** exposes the saved
run ID and **Download original payload**. Its integrity check is distinct from
financial matching and source authentication.

## Minute 3: read the replay outcomes

Open `replay-final-new/summary.md`. The fixed expectations below distinguish a
financial finding from a computational replay result; actual calls and exits are
recorded under `replay-final-new/commands/<case>/`.

| Fixed case | Expected replay / exit | What to inspect |
| --- | --- | --- |
| `clean` | REPRODUCED / 0 | Complete saved answer equals recalculation. |
| `custody_difference` | REPRODUCED / 0 | The financial MISMATCH +1 is correctly reproduced. |
| `old_cut_offline` | REPRODUCED / 0 | The original cut survives later knowledge and unavailable source DBs. |
| `wrong_identity` | ERROR / 2 | REPLAY_INTEGRITY rejects the wrong external identity before comparison. |
| `numeric_divergence` | DIVERGED / 1 | Consistent hashes cannot hide the wrong saved liability of 12. |
| `trace_divergence` | DIVERGED / 1 | The wrong saved trace balance of 500 differs from recalculation. |
| `protected_recorded` | REPRODUCED / 0 | Genuine 0.10.1 protected inputs are consumed without re-verifying signatures. |

The demo removes its generated source databases before invoking replay. Read
`summary.json` for the recorded source lifecycle and independently fixed case
catalog. A financial MISMATCH is compatible with a successful replay; DIVERGED
means the complete calculated answer differs from the bound saved answer.

## Minute 4: inspect the two files and the separate pin

For the custody case, the authoritative input pair is:

- `replay-final-new/cases/custody_difference/context.json`
- `replay-final-new/cases/custody_difference/run.json`

Open `replay-final-new/commands/custody_difference/command.json` to see the actual
`--context`, `--run` and separately supplied `--expected-execution-id` arguments.
The verifier does not infer the expected identity from either input. The demo's
`summary.json` records each pin observation: ordinary pins come from the real
recorded call before export; numeric/trace counterexamples use explicitly
TEST-ONLY, consistently rebound pins. These are demonstrations, not institutional
trust anchors. An independent operator must select their expected identity
separately; copying an identity from an untrusted input does not make it trusted.

## Minute 5: read what the result establishes

In `replay-final-new/commands/custody_difference/result.json`, read `inputs`,
`comparison`, `financial_summary`, `runtime`, and `claims`. Replay recalculates
captured inputs with the current preserved financial engine and compares the full
saved payload. Only `context.json` and `run.json` are verified; surrounding export
or presentation files are outside this claim.

The result retains `original_executable_identity=NOT_RECORDED`,
`source_signature_verification=NOT_PERFORMED`,
`independent_financial_algorithm=NOT_PERFORMED`,
`external_database_capture_completeness=NOT_VERIFIED`, and
`expected_identity_trust=CALLER_SELECTED_PIN`. It does not independently prove
asset existence, the original database's external completeness, institutional
identity, or compliance. The viewer displays history; replay checks same-engine
reproducibility. Neither turns a reported amount into a verified real-world asset.

For the dated release evidence, see [Verification](../../README.md#verification).
For setup context, see [Run locally](../../README.md#run-locally). The
[replay contract](../stage13/replay-contract.md) and
[0.11.1 repair contract](repair-contract.md) define the exact computational and
output-error boundaries.
