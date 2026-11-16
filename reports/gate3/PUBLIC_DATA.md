# Gate3 independent public-data audit

The retained original bytes pass the independently implemented, finite Gate3 audit.
No additional public feed was fetched. This does not establish institutional truth
or natural-error detection performance.

The external scope was selected before auditor implementation and execution in
`contracts/gate3-public-corpus.json` (10,860 bytes,
SHA-256 `db6467497e31244fcd7b679485cb457257a6dfd4567ae4277bcf6d33c6b4f575`).
It fixes all ten Treasury API bodies, two SEC ZIP bodies, four original official
HTML bodies, two historical comparison outputs, ordered record-identity digests,
and literal expected counts. The independent program is
`scripts/validation/audit_gate3_public.py` (SHA-256
`8a0e93b5470579989f145758afcc770f4347ff734ca9b121830902f0c83a63d1`).
It imports only the Python standard library, never production or research
parsers, normalizers, source catalogs, arithmetic helpers or the new verifier.
Dependency overlap remains the Python standard library, the same captured
publisher bytes and the explicitly selected comparison population. It is not an
independent publisher capture or third-party attestation.

| Population | Independently checked observation | Limit |
| --- | --- | --- |
| REAL_PUBLIC_DIRECT: Treasury | 14,226 rows: Table I 336, Table II 13,890; 92 dates; 60 modern equations, 39 exact, 21 residuals of +/-1 million; 120 exact Table I/II named-flow controls | 32 legacy equations NOT_RUN; no natural loss labels |
| REAL_PUBLIC_DIRECT: SEC | 89,285 financial rows across two original ZIPs; both trailers match counts and quantity sums; no duplicate date/CUSIP keys; 980 dot-price rows; 18 symbol-bound warnings | Outstanding aggregate balance; no daily-new-fails, fail-age or abuse inference |
| REAL_PUBLIC_ADAPTED | Historical 60-case single-source construction remains 39 MATCHED / 21 expected MISMATCH; Treasury totals were assigned authored holder, source and time fields | Zero independent counterparties; this audit did not rerun the adapted production engine |
| REAL_PLUS_SYNTHETIC_INJECTION | All 360 historical inputs and original-row links independently checked and reclassified: TP120 / FP0 / TN180 / FN60, from 30 distinct SEC source rows | Six paired families reuse controls; 180 positives = 120 detectable + 60 undetectable. Natural precision/recall NOT_MEASURABLE |
| FULLY_SYNTHETIC | Gate1's historical 264-case TP132 / FP0 / TN120 / FN12 remains unchanged | Separate historical population; not added to SEC or Treasury observations |

The SEC files contain 44,986 and 44,299 financial rows. Their two trailer quantity
sums are 932,349,891 and 2,032,216,720 shares respectively. These are checks of
file-level aggregation, not measures of daily new fails. All 18 observed symbol
warnings concern the 11-character `F105SPINOFF` value, beyond the documented
10-character bound. They are a finite format discrepancy, not ground-truth
financial losses. Missing prices remain missing, not zero.

Original official documentation was re-read directly from pinned `.body` bytes.
The audit extracts HTML text itself and requires these verbatim passages:

- Treasury: “All figures are rounded to the nearest million.”
- Treasury: “the closing balance today column values will be null from April 18,
  2022 onwards”; “Please reference the TGA Closing Balance value within the Type
  of Account column to find the closing balance values within the opening
  balance columns.”
- Treasury rights: “The data on this site is available to copy, adapt,
  redistribute, or otherwise use for non-commercial and commercial purposes.”
- SEC: “The values of total fails-to-deliver shares represent the aggregate net
  balance of shares that failed to be delivered as of a particular settlement
  date.” The source also explicitly says the figure is not a daily amount and
  that the age of fails cannot be determined from these numbers.

The SEC ZIP URLs are checked against exact anchor hrefs in the original official
landing HTML, not guessed from filename patterns. The pins verify retained byte
identity; they cannot authenticate a publisher or retroactively establish
original publication vintage. Publication vintage remains UNKNOWN, distinct
from the historical retrieval timestamp. Treasury's numerical-data reuse grant
does not establish SEC/site-document redistribution rights.

The residual sign here is `opening + deposits - withdrawals - closing`.
Observed residual counts are -1: 8, 0: 39, +1: 13. Rounding is compatible with
these residuals; it is not proved to be their cause. Strict equality still uses
zero tolerance. A separately labelled research-only +/-2 diagnostic is not an
approved operational tolerance and changes no stage2-v2 behavior.

The preselected exact example is 2026-11-12, Table I / Cash Balance Details,
source lines 1–4, original JSON pointers `/data/28` through `/data/31`:
`912134 + 316534 - 295541 = 933127` million USD. The four account labels are
checked literally. Their `close_today_bal` fields must be the documented string
`null`; the amounts come from `open_today_bal`. Missing/NULL amounts are never
converted to zero. Table II's selected totals on that date are source lines 80
and 182, not sums of hierarchical categories.

Seven literal research cases set closing values to 933127, 933126, 933128,
933125, 933129, 933124 and 933130, with expected residuals 0, +1, -1, +2, -2,
+3 and -3. Separate tests reject wrong row identities, deleted/duplicated rows,
wrong transition mapping, NULL amounts and signed-negative aggregate amounts.
The wrong-sign closing 1,524,209 gives the independently specified residual
-591,082. These authored boundary cases are separate from all historical
scorecards and carry no natural-error interpretation.

Actual canonical execution is retained at
`/workspace/validation-gate3-evidence/public-audit/raw-audit-002/`:
exit 0, wall 1.425149 seconds, 30-second parent cap, 20 CPU-second limit,
512 MiB address-space limit, 20 MiB output-file limit. The 112,546-byte result
has SHA-256 `9f05a51119a38a32841fa241e22d222fd3f78f8060e4d87e988bd7a973ca5854`.
It records input proofs, exact executable/version/import origins, all 60
arithmetic records, all 120 cross-table checks, selected injection source IDs,
document quotes and limits. Command argv, cwd, exit, stdout/stderr hashes and
UTC times are stored in `command.json`.

The separately preregistered full-command negative witnesses all behaved as
expected: a missing original exits 3 with NOT_RUN; a same-size source-date
substitution exits 1 for raw digest mismatch; a changed corpus contract exits
1 for external contract-digest mismatch. These are expected rejections, not
successful data audits. Original source bytes were never edited. Their evidence
is in `negative-cli-summary.json` and the three unique `cli-*-001` directories.

Eleven new research test methods pass on both Python 3.12 and 3.14 with zero
failures, errors, skips, expected failures or unexpected successes. They remain
outside the 875 protected historical inventory. The first 3.12 attempt had one
failure because a new test incorrectly counted `F105SPINOFF` as 10 characters;
it actually has 11. That failed source and log are retained in
`tests-py312-001`. The corrected test uses literal `ABCDEFGHIJ` (10) and
`F105SPINOFF` (11). This is disclosed as a test-oracle correction, not an
application fix or a claimed same-witness verifier repair. The first successful
raw audit predates explicit missing-original NOT_RUN handling; its exact source
was reconstructed by inverse patch and verified against its originally recorded
SHA, with that reconstruction labelled explicitly. Canonical audit-002 captures
the final source directly.

Public-data NOT_RUN/unknown inventory: 32 legacy four-total checks; new-source
acquisition; production rerun of the already preserved adapted 60 cases; natural
precision/recall (NOT_MEASURABLE); independent institutional counterparties
(NOT_AVAILABLE, zero); original publication vintage (UNKNOWN); operational
research-tolerance approval (NOT_AVAILABLE); SEC/site raw redistribution
(permission NOT_VERIFIED). These gaps are not filled with plausible records.

For exact replay, retain the original directory layout rooted at
`/workspace/validation-gate2-evidence/public-data`, including the two SEC ZIP
bodies, four original documentation HTML bodies and two historical comparison
JSON files. The corpus contract gives every relative path, exact size and hash.
SEC/site originals remain local and must be supplied lawfully as manual replay
prerequisites; a later HTTP fetch may have different bytes and is not an exact
substitute. A shared archive that omits them cannot independently rerun this
audit without those files. Run:

```sh
python -I scripts/validation/audit_gate3_public.py \
  --raw-root /workspace/validation-gate2-evidence/public-data \
  --contract contracts/gate3-public-corpus.json \
  --expected-contract-sha256 db6467497e31244fcd7b679485cb457257a6dfd4567ae4277bcf6d33c6b4f575 \
  --output /tmp/new-gate3-public-audit.json
```

Output must not already exist. Missing original bytes produce NOT_RUN and exit 3;
changed bytes or scope are rejected. A correct ZIP manifest establishes the
identity of included bytes only, not source semantics, authorization or external
authenticity.
