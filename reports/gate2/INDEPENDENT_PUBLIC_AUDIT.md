# Gate 2 independent public-source audit

Audit date: 2026-11-16 UTC. **SUPPORTED, with explicit scope limits:** the retained official-source bytes contain 14,226 Treasury rows and 89,285 SEC financial records. This replaces neither the preserved Gate 1 zero-row result nor the overall gate decision. Of 60 modern Treasury daily equations, **39 are exactly equal and 21 have a nonzero residual of one published million USD**. All 120 separately selected Table I/Table II deposit/withdrawal comparisons are exact. The 32 legacy dates have no established four-total mapping and remain `NOT_RUN` for this equation.

This reviewer separately read the saved official documentation and original JSON/ZIP bytes, checked capture-manifest hashes and sizes, and implemented an independent parser/arithmetic program outside the repository. No project financial or research parsing helper is imported. No download was repeated. This verifies the retained capture and its recorded origin metadata; it does not claim that the auditor independently observed the network transfer, acquired a second institutional source, or established original publication-vintage authenticity.

## Inspectable evidence

Evidence root: `/workspace/validation-gate2-evidence/independent-public-audit/`.

- `audit_public.py`: independent raw-artifact audit. SHA-256 `409a330770e6707344e3e8af4c3a70bb468b571ff2cf6f3bcacd628d5d373b91`.
- `summary.json`, `stdout.txt`, `stderr.txt`: actual execution and counts; stderr is empty.
- `verified-artifacts.json`: exact paths, SHA-256, byte counts, capture-register identities, official URLs and retrieval timestamps for 18 successful artifacts. The separately retained SEC policy 404 is not a successful policy source.
- `treasury-daily-checks.json`: all 60 dates, six exact selected source rows per day (four Table I rows plus two Table II controls), zero-based raw indices, fields, source identities, integers, independent Decimal residual and separate rounding diagnostic.
- `treasury-profiles.json`: all periods, raw row counts, account populations, null closing columns and all 77 signed negative Table II components retained.
- `treasury-legacy-not-run.json`: all 32 untested legacy dates and their selected Table I row locations.
- `sec-independent-profile.json`: original ZIP/member hashes, exact trailer checks, date counts, missing-price counts, duplicate-grain checks and each documented-layout warning.

Captured source roots are `/workspace/validation-gate2-evidence/public-data/access-01/` and `data-02/`. The audit records repository HEAD `f3dff8dd00837ac7ce6e9bb687dd4861f790cbac`; other agents' uncommitted work is not represented by that SHA. The independent audit imports no such code. Raw bytes remain outside Git.

## Treasury field and date audit

Official source: <https://fiscaldata.treasury.gov/datasets/daily-treasury-statement/operating-cash-balance>. Saved documentation explicitly states:

- Figures are rounded to the nearest million; `record_date` is the date data was published.
- From 2021-10-01, Federal Reserve Account references became Treasury General Account (TGA).
- From 2022-04-18, `close_today_bal` is null; select the TGA Closing Balance account row from the opening-balance columns.

The actual 2019 data have three Table I account rows per date. April 2022 has 11 three-row dates before the transition and 10 four-row dates after it. The independent auditor's modern selection uses the exact four account labels and verifies `table_nbr=I`, `sub_table_name=Cash Balance Details`, source lines 1–4, and `open_today_bal`. All actual selected rows pass these checks. At the inspected harness revision, `direct_day` selects labels/table/subtable but does not itself reject incorrect `src_line_nbr`; no source-line-mismatch regression was found in its focused test file. Thus observed source-line validity is independently established for this capture, while generalized source-line rejection is not claimed. It does not convert null closing columns to zero or use `open_month_bal`, `open_fiscal_year_bal`, month-to-date or fiscal-year-to-date flows. Table II controls select the named Total Deposits/Total Withdrawals account rows and `transaction_today_amt`; they do not sum details together with totals. Withdrawal totals are nonnegative magnitudes subtracted once. Negative detailed components remain signed and are not passed through `abs()`.

All ten API files contain the full raw field roster. Each response's `meta.count`, `meta.total-count`, received row count and one-page metadata agree; each `links.next` is null. Selected dates are inside requested bounds and the two tables share their date populations. No calendar gap is called a missing delivery. This proves completeness of these returned query pages, not source-system completeness or absence of later revisions. The capture is the downloaded 2026-11-16 snapshot; an independent historical as-of publication vintage was not established.

| Period | Table I rows | Table II rows | Dates | Modern equations | Exact | Nonzero ±1 |
|---|---:|---:|---:|---:|---:|---:|
| 2019-01 | 63 | 1,247 | 21 | 0 | 0 | 0 |
| 2022-04 | 73 | 3,559 | 21 | 10 | 7 | 3 |
| 2024-01 | 84 | 3,801 | 21 | 21 | 11 | 10 |
| 2025-01 | 84 | 3,843 | 21 | 21 | 13 | 8 |
| 2026-11-01 through 2026-11-12 | 32 | 1,440 | 8 | 8 | 8 | 0 |

The independent integer expression is `opening + deposits - withdrawals - closing`. A separate Decimal expression parses the original text and compares `(deposits - withdrawals) - (closing - opening)`. Both agree on every residual. Their common dependence on the same raw source rows and Python's JSON decoder is disclosed; expression agreement is not independent truth about Treasury's books. The production engine is not used to derive this oracle.

Exact equality uses **zero tolerance**. The frozen policy's ±2 million diagnostic follows from four independently nearest-million-rounded terms, each with at most 0.5 million quantization error. It is compatible with all observed residuals, but does not prove rounding caused them. The 21 nonzero residuals remain non-exact; they are not erased, adjusted, reclassified as exact or asserted to be natural financial errors. No precision below the published unit is invented.

The actual downloaded 2026-11-12 rows independently support `912134 + 316534 - 295541 = 933127` million USD. This is now backed by the API raw file and exact field mapping, separately from the earlier `PUBLIC_PAGE_PREVIEW_ARITHMETIC_CHECK` observation.

## SEC raw-record audit

Official source: <https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data>. Both actual ZIP URLs appear in the saved official landing-page links. Each ZIP has one ASCII member with the documented six pipe-separated fields; its CRC passes. The auditor separately split the lines without the research CSV parser. The two trailer lines were classified as control records, not financial rows, and checked against both actual record count and the integer quantity sum.

| Member | Financial rows | Distinct dates | Dot/missing prices | Duplicate date/CUSIP keys | Documented symbol-length warnings |
|---|---:|---:|---:|---:|---:|
| `cnsfails202401a` | 44,986 | 9 | 486 | 0 | 9 |
| `cnsfails202501a` | 44,299 | 9 | 494 | 0 | 9 |

The independently verified trailer quantity sums are 932,349,891 and 2,032,216,720. These are file-control sums across outstanding balances; summing repeated daily balances is **not** a count of new fails or unique shares.

An independently found limitation is retained: 18 rows use `F105SPINOFF`, an 11-character symbol, while the official layout states maximum 10. All concern CUSIP `34638F105`, one row on each observed date in each file. They remain intact in the original source and issue evidence. This is a documentation/domain discrepancy, not proof of fraud, a reconciliation failure, or an independent natural-error label. The `SEC_invalid_rows` counter in the independent machine summary counts these stricter schema warnings; no quantity/date/CUSIP/price parsing defect or duplicate key was found under the declared checks. The original research parser's narrower checks did not include symbol length, so its clean result alone would not establish full documented-layout conformance.

Official documentation says FTD quantities are aggregate outstanding net balances across NSCC members at a settlement date. They include previous unsettled fails, new fails and settlements; they are not daily new fail counts or individual trades. Price is the prior day's closing price when available, and `.` preserves missing price. The source does not guarantee data/price accuracy. Neither duration, cause, abuse, customer custody mismatch nor natural-error precision/recall is identified from these files. The price dot is never replaced with zero.

The saved SEC website-policy request returned HTTP 404 and its body explicitly says Page Not Found. It does not verify SEC usage rights. SEC raw-data rights remain `NOT_VERIFIED`.

**Treasury rights correction:** the actual saved Treasury `treasury-about.body` contains an explicit Licensing section: “The data on this site is available to copy, adapt, redistribute, or otherwise use for non-commercial and commercial purposes.” The auditor independently located that sentence in the original HTML bytes after the parent reviewer identified it. Treasury numeric dataset reuse/redistribution is therefore **SUPPORTED by the explicit official terms**, with source attribution and raw identities retained. This finding does not extend to HTML/site assets or SEC materials; those rights remain unverified. The initial claim that no grant was present was an auditor reading error, not missing source evidence. The earlier report is preserved as `INDEPENDENT_PUBLIC_AUDIT.pre-rights-correction.md`; `treasury-rights-correction.json` records its supersession and the exact original source hash/byte offset. Original acquisition registers' `license: NOT_VERIFIED` describe acquisition-time knowledge and are superseded for Treasury numeric data by this audited determination.

## Background and remaining scope

The retained BIS PFMI overview identifies the April 2012 international standards; the saved BCBS 239 newsletter is dated 6 January 2026 and explicitly says it is informational, not new supervisory guidance. They support regulatory background only, not institutional deployment, project endorsement, control effectiveness or compliance certification.

## Independent adapted and injected artifact audit

`audit_adapted_injected_v2.py` separately checked the actual `public-data/analysis-01` output artifacts without importing the project. Audit code SHA-256: `8db2fdf011cfdc5d4e41bd3bfd3570d3ab78060e214f52d4232035f6ba6f8c17`. The actual result is in `adapted-injected-summary.json`; detailed case-by-case proof is in `adapted-lineage-audit.json` and `injected-lineage-audit.json`. The summary binds exact output/harness-code hashes rather than treating the uncommitted working tree as identical to HEAD.

All **60 `REAL_PUBLIC_ADAPTED` cases / 120 findings** agree with the independent raw-source oracle. There are 39 MATCHED dates and 21 MISMATCH dates, each with two findings. Every imported opening/deposit/withdrawal/closing amount was traced to its exact official raw row. A read-only SQLite check verified the actual stored result for every run and the receipt count. This is artifact/readback validation, not a second run of the production engine.

The mapping creates one aggregate investor, external custody, a zero platform allocation, synthetic identifiers, ordering/time-of-day values and count manifests. Two report roles reuse the **same** Treasury closing balance; they are not independent institutional counterparties. The declaration of COMPLETE follows authored manifests and does not prove Treasury delivery completeness. `REAL_PUBLIC_ADAPTED` must remain separate from `REAL_PUBLIC_DIRECT` and from native customer/custodian records.

All **360 `REAL_PLUS_SYNTHETIC_INJECTION` observations** were independently traced to 30 distinct original SEC rows. The auditor reproduced the selections using seeds 11, 29 and 47, verified the original raw line location, input hashes, exact field transformations, independent detection decisions and confusion labels. Result: **TP=120, FP=0, TN=180, FN=60**. Four families each produce 30 TP/30 TN: negative quantity, invalid date, invalid CUSIP format and duplicate date/CUSIP. Two families each retain 30 FN/30 TN: lexically valid CUSIP replacement and valid quantity change. Lexical validity does not assert a valid CUSIP check digit, official membership or trusted institutional identity. The injected truth is the authored transformation relative to the retained row, not a natural financial error label. These observations are not pooled with the protected 264 fully synthetic baseline.

The first independent saved-output audit failed because its own assertion compared the SQLite `runs.payload` directly with the exported result. Schema and `Store.read_run` inspection showed that the primary-key column stores the run ID and readback adds it to the payload. The corrected audit checks the stored key and every payload field; it passes. The initial script and `adapted-injected.stderr.txt` are retained, with `audit-retry-note.json` documenting this auditor-check error. No application failure or earlier RED evidence was overwritten.

Full regressions, benchmarks, final commit identity and CI are outside this independent public-data audit. Overall readiness remains the parent gate's separate decision.
