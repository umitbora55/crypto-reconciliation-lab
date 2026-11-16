# Public-data validation — Gate 2 revision, 16 November 2026

**LIMITED support from actual official records:** 14,226 Treasury rows and
89,285 SEC financial records were downloaded and independently audited. These
are original JSON/ZIP bytes, not copied page examples. Eighteen of 19 requests
succeeded; the SEC policy URL returned a retained 404.

| Population | Observed result | Boundary |
|---|---|---|
| REAL_PUBLIC_DIRECT: modern Treasury | 60 daily equations: 39 exact, 21 strict nonzero residuals (±1 million USD); 120 cross-table totals exact | Fixed ±2-million rounding diagnostic is separate from zero-tolerance equality; rounding is not proven as the cause |
| Legacy Treasury | 32 dates retained | Four-total equality NOT_RUN; no unsupported sum of hierarchical details |
| SEC outstanding FTD balances | 89,285 rows, 980 missing prices, no duplicate date/CUSIP keys; 18 documented symbol-length warnings | No trade-level custody truth, daily new-fail count, duration, fraud label or natural-error recall |
| REAL_PUBLIC_ADAPTED | 60 native-engine/persisted-result cases: 39 MATCHED and 21 expected MISMATCH | Authored holder/times/manifests; both reported sides reuse one public closing balance |
| REAL_PLUS_SYNTHETIC_INJECTION | 360 observations: TP120/FP0/TN180/FN60, derived from 30 distinct SEC source rows | Six families repeat controls; schema-valid identity/quantity replacements lack independent truth |

The supplied November 12 page preview remains separately labelled and contributes
zero acquired rows. The actual API file independently supports that day's same
arithmetic. Publication revision/vintage is UNKNOWN where absent; retrieval UTC
is recorded separately. Treasury numeric-data reuse is supported by its official
licensing statement. SEC ZIPs and site documents stay local with exact hashes.

See the [complete source/mapping report](gate2/REAL_DATA_VALIDATION.md),
[independent raw/engine audit](gate2/INDEPENDENT_PUBLIC_AUDIT.md),
[separate scorecards](gate2/scorecards/), and
[offline reproduction guide](../docs/validation/GATE2_REPRODUCE.md).

The [original Gate1 report](history/gate1-f3dff8d/REAL_DATA_VALIDATION.md) is
byte-preserved. Its 19 proxy failures, zero acquired rows and REAL_DATA_UNVERIFIED
conclusion remain historical facts. New evidence does not erase them or establish
institutional deployment, compliance, cost savings or operational-risk reduction.
