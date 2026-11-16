# Gate 2 public-source evidence — 16 November 2026

**Public-data integration is supported within a limited aggregate scope.**
The new environment downloaded original official bytes containing **14,226
Treasury rows and 89,285 SEC financial rows**. Of 92 Treasury dates, 60 have the
modern four-total layout: **39 exact cash equalities; 21 nonzero residuals of
one million USD**. The latter are consistent with the fixed rounding bound but
remain strict `MISMATCH`, never silently changed to exact. Thirty-two legacy
dates remain `NOT_RUN` for this four-total equation. No institutional readiness
or customer-level reconciliation truth follows from these results.

This is a new dated report. The original 19 tunnel failures, zero-row conclusion,
NOT_READY history and evidence-preservation limitations remain unchanged in the
original reports and `/workspace/validation-evidence/`.


The first Gate 2 computation, `analysis-01/`, is preserved but superseded as
canonical execution evidence because it lacked a pre-execution code binding.
No retrospective identity was invented. A fresh offline `analysis-02/` ran from
an isolated source snapshot captured before execution. Its `execution-start.json`
binds every application Python/JSON resource and the actual public-analysis
dependency closure, raw input/policy hashes, command, UTC time, Python executable
hash/version, platform and SQLite version. `execution-completion.json` records
exit 0, 9.12 seconds, empty stderr, observed imported-module origins, and unchanged
checkout code, snapshot, raw inputs, policy and bootstrap after execution.
The new canonical mathematical results remain unchanged. Unrelated benchmark and
identity research are explicitly outside this analysis's execution closure.

## Original captures and source interpretation

Fresh evidence is under `/workspace/validation-gate2-evidence/public-data/`:
`access-01/` contains seven requested documentation pages and two January 2019
API responses; `data-02/` contains eight remaining Treasury API responses and two
SEC ZIPs. Each has its complete request protocol, UTC acquisition timestamp,
status, URL, body SHA-256/bytes and original response bytes. Eighteen of 19 requests
succeeded with HTTP 200. The previous SEC website-policy URL returned HTTP 404;
its saved error page is not terms evidence. No TLS bypass or alternate credential
was used. The dataset files' publication revision/vintage is **UNKNOWN** where
the publisher does not supply it; download time is recorded separately.

The [Treasury DTS page](https://fiscaldata.treasury.gov/datasets/daily-treasury-statement/operating-cash-balance)
states that figures are rounded to the nearest million and documents two changes:
Federal Reserve Account was renamed Treasury General Account on 1 October 2021;
from **18 April 2022**, `close_today_bal` is null and the TGA Closing Balance row
holds closing values in the opening-balance columns. The actual API dictionaries,
account types, table/subtable identifiers and source-line numbers were inspected.
The adapter uses only **daily** `open_today_bal` and `transaction_today_amt`, never
month-to-date or fiscal-year amounts. Ten API responses each have one complete
page; the received row counts match `meta.total-count` and `meta.total-pages=1`.
Absent calendar dates are not classified as missing deliveries.

The [SEC FTD page](https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data)
was saved before its actual hyperlinks to `cnsfails202401a.zip` and
`cnsfails202501a.zip` were followed. ZIPs were not accepted based on guessed file
names. The page defines aggregate outstanding net fail balances, not daily new
fails, ages, individual trades or proof of abusive short selling. It states that
the price is the previous day's closing price when available and greater than
one penny; `.` denotes unavailable or sub-penny price. Accuracy and publication
timing are not guaranteed. Those limitations remain part of this analysis.

## Direct Treasury checks

| Period | Table I rows | Table II rows | Dates | Exact days | Nonzero within fixed rounding bound | Legacy direct NOT_RUN |
|---|---:|---:|---:|---:|---:|---:|
| 2019-01 | 63 | 1,247 | 21 | 0 | 0 | 21 |
| 2022-04 | 73 | 3,559 | 21 | 7 | 3 | 11 |
| 2024-01 | 84 | 3,801 | 21 | 11 | 10 | 0 |
| 2025-01 | 84 | 3,843 | 21 | 13 | 8 | 0 |
| 2026-11-01 through 2026-11-12 | 32 | 1,440 | 8 | 8 | 0 | 0 |
| **Total** | **336** | **13,890** | **92** | **39** | **21** | **32** |

For each modern day, four exact account labels select opening, deposits,
withdrawals and closing from Table I. Python integer arithmetic, a separately
expressed Decimal calculation and a SQLite integer expression agree. All three
share the selected source text, so this is expression-level independence, not
three independent interpretations of source semantics. Every day retains complete
selected rows, JSON pointers, raw source-file hashes, normalized amounts, result,
residual and rounding diagnostic in `analysis-02/results/direct-days.json`.

The strict equation is `opening + deposits − withdrawals − closing = 0`.
The independent nearest-million rounding bound was fixed at **±2 million USD**
before the per-day arithmetic run; it was not tuned to observed discrepancies.
Eight days have residual −1 and thirteen have +1. None exceeds that fixed bound.
The two aggregate daily flows also agree exactly with the separately named Table
II total rows in all **120 comparisons**.

Table II contains 77 signed negative daily component values across the selected
periods and hierarchical subtotal/total rows. They remain present in profiling;
the adapter neither applies `abs()` nor sums every category into a false total.
Negative total magnitudes are rejected explicitly. Legacy Table I does not
contain the two daily flow totals needed by this direct mapping; the 32 earlier
days are retained with their raw rows and explicit NOT_RUN reason. No unsupported
component-sum reconstruction was substituted.

The supplied preview `912134 + 316534 − 295541 = 933127` is recorded separately
as `PUBLIC_PAGE_PREVIEW_ARITHMETIC_CHECK` in `preview-arithmetic.json`. That
user-supplied page observation contributes **zero** downloaded real rows and
zero real-equality counts. The November API capture is separately verified through
its original bytes and exact row mapping.

## Adapted public-data engine exercise

Sixty independently checked modern-day totals were transformed into the native
engine's input shape and executed with SQLite persistence/readback. This separate
population is **REAL_PUBLIC_ADAPTED**: one authored aggregate holder, an authored
external-custody allocation, arbitrary within-day event times and authored count
manifests. The asset is `MILLION_USD` at precision zero; no fictitious cents are
introduced. Each derived input record retains its source amount role and explicitly
lists the invented structural semantics.

All 60 cases matched their independently specified residual: **39 MATCHED day
pairs and 21 expected MISMATCH day pairs**. There are two findings per day, but
both reported sides reuse the same public closing balance. They are **not two
independent reporting parties**, and authored manifests do not establish external
completeness. Inputs, SQLite files, exact saved results and run IDs remain under
`analysis-02/results/adapted/`; the inventory is `adapted-cases.json`.

## SEC quality and controlled injections

| Official file | Financial rows | Observed settlement dates | Distinct CUSIPs | Missing/dot prices | Duplicate date/CUSIP keys | Documented-length warnings |
|---|---:|---:|---:|---:|---:|---:|
| January 2024 first half | 44,986 | 9 (2–12 January) | 10,933 | 486 | 0 | 9 |
| January 2025 first half | 44,299 | 9 (2–14 January) | 11,148 | 494 | 0 | 9 |

Both original ZIPs contain one ASCII member and two explicit trailer lines. The
record counts and quantity sums are checked against all parsed financial rows:
44,986 / 932,349,891 and 44,299 / 2,032,216,720 respectively. Trailer lines are
not financial records. Their across-date quantity sums are file control totals,
not newly failed transactions. Date/CUSIP lexical format, nonnegative integral
quantity, price-domain, exact header and duplicate-grain checks found no invalid
financial rows within those checks.

There is a real documentation discrepancy: **18 rows use the 11-character symbol
`F105SPINOFF` although the official layout says maximum 10**. The original values
remain intact and are recorded as documentation-domain warnings, not fraud or
financial-error truth. CUSIP checks establish lexical format only, not checksum
validity, registry membership or an authenticated security identity.

The separate injection exercise uses seeds **11, 29 and 47**, five selected rows
per seed/file: **30 distinct public rows**, six transformations and paired clean
controls produce 360 observations. The known label is whether research changed
the record, not whether the original financial claim is true. The class is
**REAL_PLUS_SYNTHETIC_INJECTION**, separate from the original 264 wholly synthetic
observations and their preserved 12 false negatives.

| Injected family | TP | FP | TN | FN | Meaning |
|---|---:|---:|---:|---:|---|
| Negative quantity | 30 | 0 | 30 | 0 | Domain violation detected |
| Invalid date | 30 | 0 | 30 | 0 | Impossible date detected |
| Invalid CUSIP lexical format | 30 | 0 | 30 | 0 | Format violation detected |
| Duplicate date/CUSIP | 30 | 0 | 30 | 0 | Duplicate-grain warning detected |
| Format-valid CUSIP substitution | 0 | 0 | 30 | 30 | No authoritative identity reference supplied |
| Valid positive quantity change | 0 | 0 | 30 | 30 | Schema checks cannot establish amount truth |
| **Total** | **120** | **0** | **180** | **60** | **Precision 1; recall 2/3; specificity 1; FPR 0 in this constructed universe** |

The repeatedly reused rows and curated families are not independent natural-error
samples. No population confidence interval, natural-error recall or institution
failure-detection claim is inferred. Every original row, transformed text,
SHA-256, seed, oracle label and actual quality output is retained in
`analysis-02/results/ftd-injections.json`.

## Rights, regulatory references and packaging

The saved [Treasury About / Licensing page](https://fiscaldata.treasury.gov/about-us/)
explicitly permits copying, adapting, redistributing and otherwise using the data
for noncommercial and commercial purposes. This supports redistribution of the
numeric Treasury data; it does not automatically license every HTML asset.
Treasury numeric raw data may be included in an outside-Git review archive with
attribution and original hashes. Raw data remain outside Git in this task.

No explicit SEC raw-data redistribution license was verified; SEC ZIP/text and
site HTML should remain local unless that right is established. A review archive
can carry URLs, exact hashes, metadata, synthetic controls and the manual-import
recipe instead. The SEC official page describes programmatic processing and
important accuracy limits; this is not silently converted into a broader license.

The saved [BIS PFMI overview](https://www.bis.org/committees/cpmi/pfmi/overview)
identifies the principles published on **16 April 2012**. The saved
[BCBS 239 newsletter](https://www.bis.org/publications/implementation-principles-effective-risk-data-aggregation-and-risk-reporting-bcbs-239-principles)
is dated **6 January 2026** and expressly says it is informational, not new
supervisory guidance or expectations. These are background references only;
they do not establish product compliance, institutional use or accreditation.

## Reproduce, import and inspect

The deterministic full public-data analysis is offline and refuses an existing
output path. From the project root:

```sh
NO_NETWORK=1 .venv/bin/python -B scripts/validation/run_gate2_public_data.py \
  --access-root /workspace/validation-gate2-evidence/public-data/access-01 \
  --data-root /workspace/validation-gate2-evidence/public-data/data-02 \
  --policy /workspace/validation-gate2-evidence/public-data/policy-frozen.json \
  --output /absolute/new/public-analysis
```

Raw-file hashes and full expected request inventories are verified first. The
original `policy-frozen.json` discloses that schema and representative rows were
inspected before policy freeze; this was not a blinded experiment. Fresh online
acquisition uses the existing controlled fetcher. SEC requests now require
`--sec-landing-file` and `--sec-landing-sha256`, binding the requested ZIP URLs to
actual hyperlinks in retained official landing bytes before opening the network.

For an authorized manual/browser fallback, visit the official URLs above, save
the original API JSON or ZIP rather than copied page text, retain the actual
URL/download time and original file, and record publication vintage as UNKNOWN
when absent. For SEC, first save the official landing page and confirm its actual
ZIP href; do not reconstruct filenames. Keep the saved raw files in a private
local input directory. Create a manifest conforming to
[`official-import-v1.schema.json`](../../data/sources/official-import-v1.schema.json),
using each original file's real `sha256sum` and byte length, then run:

```sh
NO_NETWORK=1 .venv/bin/python -B scripts/validation/import_official_files.py \
  --manifest /absolute/manual-manifest.json \
  --input-root /absolute/manual-downloads \
  --output /absolute/new/manual-import
```

The importer is tested offline on synthetic fixtures. It checks nonempty unique
inventory, paths/symlinks, HTTPS official host, UTC timestamp, kind, exact hashes
and sizes, bounded JSON pagination or ZIP trailers, and no overwrite. It labels
origin **USER_ATTESTED**, never independently authenticates it or automatically
increments verified real-equality counts. A manual import does not silently
become the automated acquisition record format. The data mapping still requires
explicit source review and row-level validation.

The final relevant checks are 35 existing public-adapter methods, 13 Gate 2
methods and eight offline-import methods: **56 passed**. Narrow new-harness
repair evidence retains an unchanged 13-test file with four RED failures before
SEC trailer handling and all GREEN afterward; the unchanged 35-test file has
one RED failure before enforcing the SEC-link prerequisite and all GREEN after.
No protected historical test or production financial module was changed here.

Independent review recomputed the raw arithmetic and file profiles without
project helpers, then checked all adapted SQLite payloads and injection hashes.
Its artifacts are in `/workspace/validation-gate2-evidence/independent-public-audit/`.
The source acquisition, source semantics, 39 exact equations, 21 rounded residuals,
adapted engine behavior and injection detection each remain distinct claims.
