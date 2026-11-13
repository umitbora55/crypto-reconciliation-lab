# Observed Stage 3.3 results and interpretation

This interpretation uses the sole completed A/B experiment and the separate single populated-database migration experiment. It does not launch or repeat measurements. All 18 normal trials and both P2 cProfile diagnostics completed with PASSED correctness. The normal statistics contain exactly three observations per profile and variant, including the first runs and all slow observations.

## Completion and provenance

The strict outer execution proof in `ab_execution.json` records exit code 0, `complete_claim_verified=true`, and unchanged original application/tool/test files and both installed application copies. The finalization receipt binds the exact retained JSON and Markdown hashes, confirms the shared deadline, and records completed cleanup. Shared elapsed is **976.416924 s**, including supervised copy, final publication and cleanup; the earlier `ab.json` snapshot is **976.211242 s**. The 1,200-second budget was not reset. The controller process observed externally took 984.763191 s. Source-read preflight (7.889931 s) and the post-run provenance audit (11.846144 s) are separately recorded and are outside the experiment clock.

A fingerprint: `2f072d3d1d8f0ec08d411dea5fd35e61fd56ef83ebfff9b39e0ce0bbe5d9293b`. B fingerprint: `1ea830d55559efc33ffd56c5ed12184ce47358f9e913439b0d49b18449d0327d`. A is isolated 0.3.2/schema 2; B is isolated 0.3.3/schema 3. Both retain financial rule `stage2-v2`, Python 3.14.7, SQLite 3.53.4 and the same durability settings. Each profile's input/configuration, full financial JSON and Markdown hashes, run ID, table counts and trace/evidence counts agree across all six normal trials. The separately recorded 69-case/162-evaluation source and installed correctness gates passed before measurement.

## Financial phases: gains and costs

Cells below are normal medians in seconds. CPU is process CPU measured for that phase; wall includes waiting within the phase. Percentage changes are ratios of the two medians, not paired estimates. Raw values, minima/maxima and all paired differences remain in `performance_comparison.json`. The financial total is computed within each trial before taking its median; it is not the sum of phase medians.

| Profile | Phase | A wall | B wall | Wall change | A CPU | B CPU |
|---|---|---:|---:|---:|---:|---:|
| P1 | `db_setup_seconds` | 0.006663 | 0.006173 | -7.35% | 0.004551 | 0.004694 |
| P1 | `ingest_jsonl_seconds` | 0.462183 | 0.485108 | +4.96% | 0.328526 | 0.371119 |
| P1 | `reconcile_and_persist_seconds` | 0.175975 | 0.089495 | -49.14% | 0.108314 | 0.087190 |
| P1 | `export_seconds` | 0.024666 | 0.024902 | +0.96% | 0.024264 | 0.024265 |
| P1 | `reopen_readback_seconds` | 0.015536 | 0.016341 | +5.18% | 0.015517 | 0.016339 |
| P1 | `financial_total` | 0.669577 | 0.659165 | -1.55% | 0.478336 | 0.504766 |
| P3 | `db_setup_seconds` | 0.005549 | 0.005550 | +0.03% | 0.004824 | 0.004873 |
| P3 | `ingest_jsonl_seconds` | 0.615470 | 0.691075 | +12.28% | 0.477437 | 0.534715 |
| P3 | `reconcile_and_persist_seconds` | 0.373166 | 0.374138 | +0.26% | 0.337224 | 0.324639 |
| P3 | `export_seconds` | 0.077293 | 0.082909 | +7.27% | 0.073514 | 0.076420 |
| P3 | `reopen_readback_seconds` | 0.045952 | 0.048834 | +6.27% | 0.045941 | 0.048194 |
| P3 | `financial_total` | 1.116141 | 1.210814 | +8.48% | 0.937099 | 1.001533 |
| P2 | `db_setup_seconds` | 0.005577 | 0.006032 | +8.16% | 0.004357 | 0.005115 |
| P2 | `ingest_jsonl_seconds` | 4.709168 | 4.955826 | +5.24% | 3.114805 | 3.568885 |
| P2 | `reconcile_and_persist_seconds` | 4.725224 | 1.052749 | -77.72% | 4.583041 | 0.945711 |
| P2 | `export_seconds` | 0.501764 | 0.427923 | -14.72% | 0.282932 | 0.273946 |
| P2 | `reopen_readback_seconds` | 0.150404 | 0.149332 | -0.71% | 0.149733 | 0.149295 |
| P2 | `financial_total` | 9.989786 | 6.587654 | -34.06% | 8.112117 | 4.916678 |

P2 has a consistent local reconciliation/persistence improvement: all three paired reductions are 3.55–3.76 s, with B/A ratios 0.219–0.228. Ingest is slower in all nine pairs across the three profiles; P2 median ingest CPU increases from 3.114805 to 3.568885 s. Maintaining the additional index is a plausible explanation for the ingest cost, supported by the unchanged ingest call count and higher SQLite execute time in the diagnostic, but the single diagnostic does not isolate every write cost. P2 financial-phase total improves in all three pairs after including setup, ingest, export and restart readback.

P1 financial-phase total is nearly unchanged in median and one pair is slower. P3 total increases in two of three pairs and its median rises 8.48%; its reconcile wall median is essentially unchanged (+0.26%). The index is therefore a workload-dependent tradeoff, not a universal speedup. Setup measurements are tiny and noisy: P1 B includes a 0.038149 s observation; no setup saving is claimed. Export and readback are retained in every total and have no source-level optimization in this change.

## All nine paired observations

Each cell gives **B−A seconds / B÷A**. Pair orders are fixed AB, BA, AB. These values preserve pairing rather than comparing independently selected fastest observations.

| Profile | Pair/order | Ingest | Reconcile + persist | Financial total | Supervisor elapsed |
|---|---|---:|---:|---:|---:|
| P1 | 1/AB | +0.049475 / 1.113656 | -0.062521 / 0.666623 | -0.010411 / 0.984451 | +0.000762 / 1.000453 |
| P1 | 2/BA | +0.022925 / 1.049601 | -0.035153 / 0.717981 | +0.018739 / 1.029610 | +0.000048 / 1.000033 |
| P1 | 3/AB | +0.070647 / 1.136689 | -0.089657 / 0.490513 | -0.021864 / 0.970563 | +0.011856 / 1.007081 |
| P3 | 1/AB | +0.018754 / 1.028011 | -0.026918 / 0.935930 | -0.001360 / 0.998889 | -0.834644 / 0.867189 |
| P3 | 2/BA | +0.080491 / 1.131827 | +0.003639 / 1.009823 | +0.089929 / 1.081016 | -0.003521 / 0.999353 |
| P3 | 3/AB | +0.098550 / 1.160121 | -0.015094 / 0.959551 | +0.094673 / 1.084821 | +0.214538 / 1.039396 |
| P2 | 1/AB | +1.130407 / 1.261798 | -3.756558 / 0.218898 | -2.542158 / 0.736317 | +46.747418 / 1.512747 |
| P2 | 2/BA | +0.246659 / 1.052378 | -3.649298 / 0.227698 | -3.504484 / 0.652751 | -78.104337 / 0.420925 |
| P2 | 3/AB | +0.094626 / 1.019984 | -3.554419 / 0.224743 | -3.546563 / 0.644981 | -24.054489 / 0.810159 |

## Oracle, auxiliary work and full-process gaps

The independent oracle is outside the five financial timers. Its normal median wall/CPU seconds are P1 A 0.540589/0.538853 and B 0.562849/0.562549; P3 A 3.986551/3.985494 and B 3.870326/3.869510; P2 A 50.809541/48.976164 and B 49.390971/49.360305. P2 A pair 1 has oracle wall 80.689116 s versus CPU 48.829723 s. This waiting is retained; it is not attributed to financial reconciliation.

Code inspection explains why oracle work can remain substantial after the database lookup becomes faster. `lab/scoring.py:score` invokes full `validate_evidence`; `lab/evidence_contract.py` independently replays linked traces and checks every finding/evidence link and the final content identity. Its finding loop reconstructs `set(types.values())` for each evidence reference, and source-reference checks use membership in the finding evidence list. Repeated whole-inventory construction and list scans are observable in the code and can scale poorly with evidence and investor counts. They are a plausible contributor to the CPU-heavy scorer, not a measured function-level attribution: this experiment profiled only ingest and reconcile/persistence, not the oracle. No oracle check was removed or optimized.

Index inventory, three unforced query-plan probes and artifact hashing have separate wall/CPU timers. For normal P2, query-plan median wall falls from 0.002087 to 0.000182 s; index inventory rises from 0.000056 to 0.000071 s. Artifact-inventory medians are A 0.256619 s wall / 0.109527 CPU and B 0.260761 / 0.111558. Generation is separately recorded once per profile: P1 0.056989 s, P3 0.140079 s, P2 0.643552 s. Neither diagnostics nor these auxiliary tasks are silently included in a financial phase.

The following P2 accounting makes large unexplained elapsed gaps visible. Inside-worker residual is recorded worker elapsed minus all recorded phase walls; outside-worker gap is supervisor elapsed minus recorded worker elapsed. They include uninstrumented imports/input loads/checkpoints/final output, process startup/exit and supervision as applicable; this experiment does not identify which operation caused each delay.

| Variant/pair | Sum of all timed phases | Inside-worker residual | Recorded worker elapsed | Outside-worker gap | Supervisor elapsed |
|---|---:|---:|---:|---:|---:|
| A/1 | 90.613615 | 0.180567 | 90.794182 | 0.376334 | 91.170516 |
| B/1 | 56.341629 | 21.450027 | 77.791655 | 60.126279 | 137.917935 |
| A/2 | 59.298895 | 58.142438 | 117.441333 | 17.436397 | 134.877730 |
| B/2 | 56.349755 | 0.201494 | 56.551249 | 0.222145 | 56.773393 |
| A/3 | 61.058036 | 20.405115 | 81.463151 | 45.245377 | 126.708528 |
| B/3 | 56.111915 | 20.438356 | 76.550271 | 26.103768 | 102.654039 |

P2 supervisor medians are A 126.708528 and B 102.654039 s, but pair 1 is 46.747418 s slower for B while pairs 2/3 are faster. The P2 B diagnostic similarly has 74.929405 s recorded worker elapsed and 147.907208 s supervisor elapsed. File Provider delays were observed elsewhere in this workspace; they are a possible explanation for some waiting here, not established per-trial causation. The narrow phase improvement is supported; a dependable end-to-end speedup is not established. These are fresh-process observations, not controlled cold-cache measurements.

## P2 cProfile and query-plan evidence

One A and one B diagnostic were run after all normal trials; neither enters normal medians. Ingest has 1,269,222 total calls (1,269,202 primitive) in both variants, including 10,150 `Store.ingest` calls and 50,750 SQLite `execute` calls. Ingest SQLite execute self time is 4.104162 s A and 4.319630 s B; its transaction caller contributes 20,300 calls and its ingest caller contributes 30,450 calls in both variants. Profiled reconcile/persistence has 1,494,114 calls A versus 1,494,135 B.

`Snapshot.remember` is called **10,098 times in each variant**: 10,000 from events, 10 from manifests, 44 from openings and 44 from reports. Its cumulative time falls from **3.863177 to 0.110977 s**, while self time is 0.026782 versus 0.020867 s. The direct `remember` → SQLite `execute` edge has the same **10,098 calls**, with self/cumulative edge time **3.780812 → 0.042715 s**. The query text remains `SELECT raw FROM receipts WHERE receipt_hash=? LIMIT 1`; the call-count equality excludes an omitted-lookup or cached-evidence explanation.

Reconcile SQLite execute totals are 30,341 calls / 4.202020 s A and 30,346 / 0.385780 s B. B includes explicit schema/index validation calls; the whole reconcile call graph is not claimed to be identical. `save_run` cumulative times are 0.772895 and 0.729273 s, so persistence remains material after receipt lookup improves. Caller/callee and self/cumulative values are retained in raw function JSON; cumulative times overlap and must never be summed. cProfile uses its elapsed profiler clock here; phase process-CPU measurements are separate and must not be confused with profiler self time.

For the real populated P2 tables, the unchanged query probes first, last and missing hashes. A plans report `SCAN receipts`; B plans report `SEARCH receipts USING INDEX receipts_hash_lookup (receipt_hash=?)`. First/last return a row and missing does not in both variants. The exact nonunique, nonpartial one-column BINARY ASC index inventory is captured before ingest and after population. Together with unchanged counts and financial hashes, the plan and caller evidence support the intended access-path explanation. An indexed plan by itself would not establish a net benefit.

## Storage, memory and separate migration cost

Normal DB sizes are invariant within each variant/profile. RSS is the whole-worker peak, including oracle; these medians are not reconciliation-only allocation measurements.

| Profile | A DB bytes | B DB bytes | Added bytes | A median RSS bytes | B median RSS bytes |
|---|---:|---:|---:|---:|---:|
| P1 | 10534912 | 10625024 | 90112 | 104022016 | 102301696 |
| P3 | 40112128 | 40243200 | 131072 | 265437184 | 264667136 |
| P2 | 98893824 | 99737600 | 843776 | 469336064 | 477986816 |

The largest normal worker peak is 520,568,832 bytes (P2 B pair 3). This run shows no reliable memory reduction; index growth and process/oracle effects coexist. The final A/B copy/finalization supervisors observed at most 201,584,815 combined runtime/destination bytes during those stages. Sampled process/tree limits do not prove that no shorter transient peak occurred.

The separately measured populated P2 schema-2 migration completed once and passed; see **`migration_cost.json` / `migration_cost.md`** for its authoritative timings and size bindings. `migration_verification.json` covers fixture migration preservation, not this P2 cost measurement. The operational migration phase is **8.491410 s wall / 6.353030 s CPU**. Within it, actual index creation is 0.003010 s; the full path also performs snapshots, verified backup, copy rollback/success/restore tests and preservation audits. These nested times are not additive independent workloads.

Whole migration worker elapsed is 13.067871 s; main observed externally is 13.586309 s. Preparation/import takes 85.249539 s, verified retention 2.630320 s, cleanup 0.198664 s, and total outer elapsed 101.666987 s under its separate 1,200-second deadline. Worker peak RSS is 700514304 bytes. The retained source and every old table/object/historical payload are unchanged; integrity, foreign keys, restore/rollback and idempotency checks pass.

The populated migration copy grows from **98,893,824 to 99,647,488 bytes**, adding **753,664 bytes (0.762%)**. This differs from fresh B ingestion, which ends at **99,737,600 bytes**, adding **843,776 bytes** over fresh A. Bulk index creation after population and incremental index maintenance are different construction paths; the observations are reported separately rather than forced to equal physical sizes. A specific page-layout cause was not measured.

An amortization horizon is not established. Comparing one migration operation with repeated local phase savings ignores workload mix, write overhead and the observed full-process waiting. The evidence supports retaining the index for this receipt-heavy P2 reconciliation path with its measured ingest/storage cost; it does not support production capacity, latency percentiles, statistical significance or a general investor-count scaling claim. No additional experiment, cache tuning, batching, PRAGMA change or financial/oracle optimization was performed.
