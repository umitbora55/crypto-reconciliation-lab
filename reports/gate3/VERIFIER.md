# Gate 3 finite evidence verifier

**Executed result: 24/24 fixed witnesses pass after the new research guard.** The unchanged baseline accepted nine of 19 externally forbidden corpus/context mutations; ten negative witnesses were already rejected. Five positive controls, including the original modern `close_today_bal = "null"`, pass before and after. This is finite evidence-review hardening; it does not change financial production behavior or establish institutional source authenticity.

## Preregistration and exact negative witnesses

The [catalog](../../contracts/gate3-adversarial-catalog.json) was written and sealed before witness execution: SHA-256 `4266f42676548b7ecfdf8c13680e06a309c6e96db9683cfa4bdbbe381ecf3121`, 6,152 bytes. It fixes the 24 identities, transformations, expected outcomes, original corpus hashes, November 12 row pointers `/data/28` through `/data/31`, four exact account labels/source lines and the literal 912134 + 316534 − 295541 = 933127 equation. SEC uses the original January 2024 first-half ZIP and the exact link in the retained official landing page. Benchmark review uses the original 45 records and retained command/metric/input artifacts.

The same runner SHA-256 `d62a101bfd146a656c14aa4b45f2c3ae9834f4e446be9219455e907401dc7898` and the same 24 candidate digests executed before and after. All original public and LAB fixture hashes also match across the runs. Original helper imports and their hashes are recorded. No historical capture or helper was edited.

Canonical baseline-003: actual child/controller exit 1, 5.994015 s. Canonical hardened-003: actual child/controller exit 0, 3.292891 s. Both had a 180 s wall cap, 120 s CPU cap and 1 GiB address-space cap; neither timed out. The baseline failure is retained, not replaced by the passing result.

| Fixed witness | Expected | Before | After | Interpretation |
|---|---|---|---|---|
| treasury_deleted | REJECT | REJECT | REJECT | ALREADY_REJECTED |
| treasury_duplicated | REJECT | REJECT | REJECT | ALREADY_REJECTED |
| treasury_altered | REJECT | ACCEPT | REJECT | REPAIRED_ABSENT_GUARD |
| treasury_source_line | REJECT | ACCEPT | REJECT | REPAIRED_ABSENT_GUARD |
| treasury_account_label | REJECT | REJECT | REJECT | ALREADY_REJECTED |
| treasury_null_control | ACCEPT | ACCEPT | ACCEPT | POSITIVE_CONTROL |
| treasury_wrong_transition | REJECT | ACCEPT | REJECT | REPAIRED_ABSENT_GUARD |
| treasury_stale_vintage | REJECT | ACCEPT | REJECT | REPAIRED_ABSENT_GUARD |
| treasury_missing_raw | REJECT | ACCEPT | REJECT | REPAIRED_ABSENT_GUARD |
| treasury_changed_raw | REJECT | ACCEPT | REJECT | REPAIRED_ABSENT_GUARD |
| sec_changed_link | REJECT | REJECT | REJECT | ALREADY_REJECTED |
| sec_trailer | REJECT | REJECT | REJECT | ALREADY_REJECTED |
| sec_symbol_bound | REJECT | ACCEPT | REJECT | REPAIRED_ABSENT_GUARD |
| sec_duplicate | REJECT | REJECT | REJECT | ALREADY_REJECTED |
| sec_security_identity | REJECT | ACCEPT | REJECT | REPAIRED_ABSENT_GUARD |
| identity_forged_context | REJECT | ACCEPT | REJECT | REPAIRED_ABSENT_GUARD |
| benchmark_omitted | REJECT | REJECT | REJECT | ALREADY_REJECTED |
| benchmark_duplicated | REJECT | REJECT | REJECT | ALREADY_REJECTED |
| benchmark_p50 | REJECT | REJECT | REJECT | ALREADY_REJECTED |
| benchmark_timing | REJECT | REJECT | REJECT | ALREADY_REJECTED |
| treasury_original | ACCEPT | ACCEPT | ACCEPT | POSITIVE_CONTROL |
| sec_original | ACCEPT | ACCEPT | ACCEPT | POSITIVE_CONTROL |
| identity_original | ACCEPT | ACCEPT | ACCEPT | POSITIVE_CONTROL |
| benchmark_original | ACCEPT | ACCEPT | ACCEPT | POSITIVE_CONTROL |

The old Treasury parser has a specific arithmetic interface: it selects `open_today_bal` internally and does not accept a provenance/mapping-claim object. The wrong-transition and stale-vintage witnesses therefore demonstrate previously absent **evidence-claim checks**, not a claim that the old parser used the wrong financial field. Likewise, missing raw or whitespace-mutated raw acceptance exposes a missing finite corpus binding at this helper boundary; the Gate 2 outer fetch verifier already checked retained-source hashes. The signed-context witness deliberately supplies a newly self-consistent LAB context; its valid signature never implied an independent institutional trust root.

## Narrow implementation and overlap

The new [guard](../../validation_lab/gate3_verifier.py) requires externally selected raw hashes, exact decoded-row correspondence, independently specified row identities/amounts, the correct modern field and an honest UNKNOWN publication vintage. It retains original SEC symbol-length warnings rather than silently dropping those real source rows. It compares the supplied LAB trust context with the separately selected original context before signature verification. Benchmark checks call the independent [comparison auditor](../../scripts/validation/audit_gate3_comparison.py), including actual command/metric consistency, fixed trial order and recalculated statistics.

The wrapper intentionally reuses the old public parser/arithmetic and LAB cryptographic verifier. Those dependencies are not independent arithmetic evidence. Separate raw-data arithmetic is performed by the independent stdlib-only [public auditor](../../scripts/validation/audit_gate3_public.py); its results are reported in PUBLIC_DATA.md. The comparison auditor imports neither benchmark implementation nor production parsing/arithmetic. The wrapper is not packaged as a new runtime feature and leaves stage2-v2 strict tolerance, version 0.11.1 and schema 6 unchanged.

Six separately named new unit methods passed on Python 3.12 and 3.14, zero failures/errors/skips/expected failures/unexpected successes. The Python 3.14 stderr retains one ResourceWarning for an unclosed SQLite connection from the historical public arithmetic helper; it is not a suppressed or failing test. The 875 protected historical identities are not increased by these six methods or by the 24 witness observations. Root release evidence separately establishes the full historical source/installed and financial gates.

The original 001 pair remains intact. A second origin-audit pair (002) retained actual witness child exits 1/0, but its controller exited 97 because the expanded import collector included venv cryptography modules while the prehash list covered only repository source directories. This absent-prehash bookkeeping error was incorrectly called SOURCE_CHANGED. It is preserved in `audit-error-002.json` and both original directories. The corrected controller prebound all observed dependency imports; the final 003 pair validates all imported Python source hashes before/after. The exact candidate digests are unchanged across all three pairs. No historical helper or new research guard was changed to fix this recorder error.

## Evidence and replay prerequisites

All paths below are under external `/workspace/validation-gate3-evidence/verifier/`:

- `catalog-seal.json` and `preregister.py`: preregistration and literal roster.
- `witness_runner_v2.py`, `run_recorded_v3.py`: unchanged canonical witness generation, all actual repository/dependency Python import origins, bounded process launcher and imported-source pre/post checks.
- `baseline-003/` and `hardened-003/`: real argv, cwd, interpreter, limits, UTC times, actual exits, stdout/stderr, import/source/input hashes and individual expected/actual results.
- `red-green-comparison-003.json`: exact catalog/runner/input/candidate hash comparison, including unchanged witnesses relative to the original 001 pair, 9 newly guarded cases, 10 already rejected and five positive controls.
- `unit-py312-001/` and `unit-py314-001/`: six-method focused tests and their original output, exact source hashes and actual exits.

Canonical replay requires the original Gate 2 paths specified in the catalog, all common-task benchmark inputs and retained 100-event databases/exports, and the `identity/run-002/identity/s11-f0-clean/` context/candidate/envelope triplet. The SEC ZIP and original site documents remain local unless redistribution permission is verified. A missing required original is NOT_RUN; do not create plausible replacement records. Choose a new output directory; the runner refuses to overwrite evidence. The before mode remains available for reviewing unchanged historical helper behavior.

```sh
/workspace/crypto-reconciliation-lab/.venv-validation/bin/python -B /workspace/validation-gate3-evidence/verifier/witness_runner_v2.py --stage hardened --output /path/to/fresh-witness-output
```

External hashes establish correspondence to reviewed retained bytes, not publisher signatures, natural ground truth, timing attestation or operational authenticity. The caller must obtain corpus pins and LAB context independently of the candidate. Self-issued replacements cannot establish that independence. No natural-error recall, institutional counterparty coverage or SLA claim follows from the 24 finite witnesses.
