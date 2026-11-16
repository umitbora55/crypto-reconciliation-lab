# Comparative performance — Gate 2 revision, 16 November 2026

**45/45 paired common-task trials completed.** All 15 matched seed/size groups
have identical input, input SQLite DB, result DB and exported JSON bytes under
the declared finite contract. This supports EQUIVALENT_COMMON_ARITHMETIC only.
The full evidence/history references remain NOT_IMPLEMENTED / NARROWER_SCOPE;
full-product superiority is INCONCLUSIVE.

| Method, 10,000 events | Repeats | Wall p50 seconds | Empirical nearest-rank p95 seconds |
|---|---:|---:|---:|
|stdlib_integer|5|14.235903|15.067140|
|sqlite_integer|5|15.254905|19.396436|
|production|5|15.332059|16.641628|

With five observations the reported p95 is the sample maximum, not an estimated
production tail guarantee. Paired production-minus-stdlib median difference is
+0.897949s (exploratory 95% interval +0.264919 to +3.092514); production-minus-SQLite
is −0.121052s (−4.064377 to +2.928074). No production speed superiority is established.
Source/input validation, actual retained artifact reread and raw-derived
statistics were independently checked. Hash consistency is not external runtime
attestation.

The common program used 269.297194s outer process wall time. Separate capacity
triage used 161.508347s and retained PARTIAL/exit 3: 100k TIMEOUT at 60.066280s with
actual child exit −9; 25k PASS at34.955961s; 50k TIMEOUT at 60.063045s with actual−9.
Each child kept the 60-second maximum. 25k is one completed observation, not a
maximum-capacity or production-SLA guarantee. Last observed committed counts
before timeout are lower bounds, not final DB readback or recovery-point claims.
Timed-out per-attempt final CPU/RSS metrics are NOT_MEASURED.

The production adapter suppresses rich result persistence for this explicitly
common-output lane, while unchanged reconciliation still constructs its in-memory
results. All methods share strict finite-workload validation, public Store ingestion,
common persistence/export and independent integer oracle checks. This is not a
runtime optimization or a before/after speedup comparison with Gate1's different
workload requirements.

See the [complete protocol, phase/resource results and limitations](gate2/BASELINE_COMPARISON.md),
[compact measured summary](../evidence/gate2/benchmark-gate2-summary.json), and
[byte-preserved Gate1 report](history/gate1-f3dff8d/BASELINE_COMPARISON.md).
The original 100k 60.065s timeout and absent POSIX-exit record remain historical.
Monetary/institutional cost savings and operational-risk reduction are NOT_PROVEN.
