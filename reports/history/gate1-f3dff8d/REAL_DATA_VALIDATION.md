# Public real-data validation

**Result: REAL_DATA_UNVERIFIED.** No Treasury or SEC financial record was
downloaded. Nineteen bounded official-source requests failed at the proxy tunnel
with `Tunnel connection failed: 403 Forbidden`; no origin HTTP response or body
was received. This is an access limitation, not evidence of a source defect.
Actual retrieval timestamps, exact URLs, request durations and error strings are
in [the source register](../data/sources/source-register.json).

The source register contains no invented checksum for an absent payload. The
request protocols and error records have real SHA-256/byte evidence outside Git.
No raw public data or hypothetical real-world result was committed. The fetcher
exit code 0 means that all request outcomes were recorded; it does **not** mean
that any dataset downloaded or any financial equality passed.

## Fixed intended coverage and observed access

| Source | Frozen period / scope | Requests | Real rows | Equality / quality result |
|---|---|---:|---|---|
| Treasury operating cash balance + deposits/withdrawals | January 2019 | 2 | DATA_UNAVAILABLE | NOT_RUN |
| Treasury operating cash balance + deposits/withdrawals | April 2022 | 2 | DATA_UNAVAILABLE | NOT_RUN |
| Treasury operating cash balance + deposits/withdrawals | January 2024 | 2 | DATA_UNAVAILABLE | NOT_RUN |
| Treasury operating cash balance + deposits/withdrawals | January 2025 | 2 | DATA_UNAVAILABLE | NOT_RUN |
| Treasury operating cash balance + deposits/withdrawals | 1–12 November 2026 | 2 | DATA_UNAVAILABLE | NOT_RUN |
| SEC FTD ZIP files | January 2024 first half; January 2025 first half | 2 | DATA_UNAVAILABLE | NOT_RUN |
| Treasury documentation, API description, usage policy | Official pages | 3 | Not applicable | Inaccessible |
| SEC FTD explanation and website policy | Official pages | 2 | Not applicable | Inaccessible |
| BIS PFMI and supplied BCBS 239 publication | Official pages | 2 | Not applicable | Inaccessible |

The SEC file names are explicit planned official download URLs, not links
confirmed against the inaccessible landing page. Their existence and period
coverage remain unverified. API queries freeze one page with a maximum of
10,000 rows; a returned `total-count`/`total-pages` inconsistent with the received
records is rejected, never accepted as a complete month. Calendar gaps are not
classified as missing deliveries. Revisions, schema changes, account populations,
null rates and actual business-day coverage remain unknown.

## Independent checks implemented and executed

`validation_lab/public_data.py` contains isolated, offline research adapters. It
imports no production financial arithmetic or normalization helpers. Python
integer arithmetic and an independently expressed SQLite integer expression both
evaluate `opening + deposits - withdrawals = closing`. Parsing is shared between
these two expressions, so their agreement is not independent validation of the
source interpretation. SQL promotion to floating point at overflow is explicitly
refused. The declared range is nonnegative signed-64-bit values and in-range
intermediate sums; this is narrower than arbitrary-precision production amounts.

Thirty-four **FULLY_SYNTHETIC** unit tests executed after the acquisition-evidence
repair, with zero failures, errors or skips. The initial 24 adapter tests cover
positive, negative and boundary cases for arithmetic, exact
zero, absent values, noninteger inputs, rounding-policy requirements, integer
overflow, dates, unknown fields, duplicate source grain, null deprecated balance,
pagination, duplicate JSON keys, SEC field layout/date/CUSIP/quantity/price,
duplicate date/CUSIP warnings, cached-file tampering and unavailable-source status.
These are adapter contract tests, not evidence of public-data integration.

Independent review found that the initial offline evidence verifier accepted an
empty or truncated acquisition inventory: checking only the supplied hashes did
not prove that every intended request had an outcome. Ten additional controls
were added; the exact same 34-test file failed nine checks before the narrow
research-harness repair and passed all 34 afterward. The repaired verifier
requires nonempty, unique, exact IDs and unchanged URL/table/period identity in
both protocol and results against the code-declared request catalog. Consistently
rehashing a truncated or substituted protocol does not satisfy this external
expected inventory. A subset must be explicitly selected by the caller rather
than inferred from the evidence. Cached-data validation uses the same gate.

Direct fetch also rejects `NO_NETWORK=1` before making a directory or opening a
network connection. These changes affect only the new research harness; no
production source or protected test was changed. A valid evidence inventory
proves acquisition-record completeness and byte integrity, not that a download
occurred or that public financial data is correct. The mutable code catalog is
a declared scope anchor, not a digital signature or independent attestation of
the network history. Evidence remains unavailable after the repair.

The default rounding tolerance is zero. A nonzero tolerance (at most two
published million-dollar units, the conservative bound for four independently
rounded terms) requires an explicit reviewed policy reference. That bound is a
mathematical assumption, **not** a verified Treasury rounding rule. No actual
Treasury residual, rounding exception or pass rate was measured. The supplied
example `912134 + 316534 - 295541 = 933127` was not independently retrieved and
is not counted as a verified real equality.

Treasury row and field mapping is explicit and fails closed unless the caller
provides a reviewed documentation reference. No default old/new schema mapping
was invented. This prevents treating `close_today_bal = null` as zero or silently
choosing a month/fiscal-year balance instead of a daily closing-account row.
Even a future valid mapping would be a narrow cash-flow adapter, not evidence
that Treasury aggregates implement the project's investor/custodian model.

FTD checks preserve every malformed row and record its issue. Duplicate
date/CUSIP keys are grain warnings requiring source review, not inferred financial
failures. Empty or dot prices remain missing. The adapter never differences
successive balances into new fail counts or estimates fail age. No real labelled
precision/recall, settlement root cause or illegal-short-sale conclusion exists.

## Reproduction and evidence

From the project root, the executed commands and actual exits are retained in
`/workspace/validation-evidence/public-data/commands.json`. Raw attempt evidence:

- `attempt-01/{protocol.json,source-register.json}`: 17 Treasury/SEC attempts.
- `bis-attempt-01/{protocol.json,source-register.json}`: two new BIS attempts.
- `tests-01.log`: 24 synthetic tests.
- `validation-01.json`: `REAL_DATA_UNVERIFIED`, zero real equalities.
- `repair-01/{RED.log,GREEN.log,summary.json}`: unchanged-test nine-failure to
  zero-failure repair evidence; current suite contains 34 tests.

The opt-in fetch command is:

```sh
.venv/bin/python -B scripts/validation/fetch_public_data.py --fetch --output /absolute/new/public-attempt
```

The default does not fetch. Existing evidence can be integrity-checked offline:

```sh
.venv/bin/python -B scripts/validation/fetch_public_data.py --no-network --output /absolute/existing/public-attempt
.venv/bin/python -B -m unittest discover -s validation_tests -p test_public_data.py -v
```

The default expects the complete current 19-request catalog. Use explicit
`--scope financial` for the retained initial 17-request Treasury/SEC attempt and
`--scope references` for the retained two-request BIS attempt. Those predefined
subsets come from code, never from the inspected JSON. `validation_lab.public_data`
accepts the same `--scope` option.

Each response is capped at 32 MiB, all responses at 512 MiB, with a 12-second
request timeout, no retries, explicit host restrictions and normal TLS
verification. New output paths preserve failed attempts. There are no live
API-dependent tests, credentials or paid requests.

## What remains unknown

Official field dictionaries, terms of use, licenses, source publication dates,
dataset vintage/revision policy and row-level provenance could not be checked.
Public accessibility is not treated as redistribution permission. Raw data must
remain outside Git until rights are verified. `fiscaldata.treasury.gov`,
`api.fiscaldata.treasury.gov`, `www.sec.gov` and `www.bis.org` are the exact
required official domains; a successful allowlist update must be followed by
new downloads and source review before changing these conclusions.

Customer-level two-sided transaction ground truth is
`NO_PUBLIC_TRANSACTION_GROUND_TRUTH`. Treasury totals and SEC outstanding fail
balances do not establish customer custody obligations, institution-level
matching truth, AML performance, production costs, SLA, operational losses or
the cause of individual failures. Public, adapted, injected and wholly synthetic
evidence must retain separate labels. Real-data integration is **not passed**.
