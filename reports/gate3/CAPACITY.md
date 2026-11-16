# Gate3 bounded capacity evidence

Capacity remains **PARTIAL**: the original 60-second profile completed 25k events and timed out at 50k and 100k. Separate extended diagnostics completed 50k in 65.443 seconds and 100k in 128.971 seconds. These are single finite observations under 120/180-second caps, not 60-second SLA passes. Production code, stage2-v2 strict finance and per-receipt commits are unchanged.

All inputs are **FULLY_SYNTHETIC**. Event counts exclude 17 opening/report/manifest receipts. The unchanged Gate2 common lane suppresses rich run persistence and exports the common financial projection; the distinct full-persistence diagnostic actually invokes unchanged Store.save_run and retains every run/finding/evidence row. Neither lane implements an independent full-service comparator.

## Actual trials

Elapsed below is actual parent-observed subprocess wall time, including startup, completion and polling. CPU covers the completed worker body. RSS is the process high-water mark reported at body completion, including startup, not incremental body-only memory; killed-worker final values remain NOT_MEASURED. No missing duration is replaced by a cap. Disk is actual retained input/result SQLite, journal when present, and restricted export bytes; CSV/source/log overhead is included separately in the cumulative owned-disk budget.

The warmup's sampled peak RSS was 17,292 KiB while its reported getrusage high-water mark was 215,308 KiB. The latter can include a fork/pre-exec watermark, and periodic sampling can miss peaks. These distinct observations remain unchanged; neither establishes isolated incremental worker-body memory usage.

| Attempt / lane | Events / seed | Cap s | Status / exit | Parent wall s | Worker-body CPU s | Reported peak RSS KiB | Direct committed receipts | Financial DB/export MiB |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| run-001/warmup-common-100 | 100 / 11 | 30 | PASS / 0 | 0.402978 | 0.065288 | 215308 | 117 | 0.364 |
| run-001/reproduce-100000-60 | 100000 / 11 | 60 | TIMEOUT / -9 | 60.059041 | NOT_MEASURED | NOT_MEASURED | 34987 | 39.692 |
| run-001/reproduce-25000-60 | 25000 / 11 | 60 | PASS / 0 | 38.705676 | 12.103771 | 221484 | 25017 | 28.332 |
| run-001/reproduce-50000-60 | 50000 / 11 | 60 | TIMEOUT / -9 | 60.103472 | NOT_MEASURED | NOT_MEASURED | 45744 | 51.864 |
| run-001/extended-50000-120 | 50000 / 11 | 120 | ERROR / NOT_OBSERVED | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | 26316 | 29.844 |
| run-002/full-10000-control | 10000 / 11 | 90 | PASS / 0 | 15.242376 | 6.044844 | 225156 | 10017 | 67.688 |
| run-002/full-10000-instrumented | 10000 / 11 | 90 | PASS / 0 | 15.564305 | 6.278476 | 225280 | 10017 | 67.688 |
| run-002/full-25000-instrumented | 25000 / 29 | 180 | PASS / 0 | 39.979541 | 16.660717 | 508388 | 25017 | 169.095 |
| run-002/extended-50000-120 | 50000 / 11 | 120 | PASS / 0 | 65.443014 | 22.601081 | 425672 | 50017 | 56.637 |
| run-002/extended-100000-180 | 100000 / 11 | 180 | PASS / 0 | 128.970663 | 45.373419 | 833936 | 100017 | 113.164 |

Original periodic counts at the 100k/50k deadlines were 34,000/45,000; separate SQLite recovery-copy reads found 34,987/45,744 committed receipts. The failed first extended-50k attempt last reported 26,000, while direct readback found 26,316. These are local abrupt-stop database facts, not operational RPO. Original database/journal bytes were hashed before and after recovery of a separate copy and remained unchanged. Killed workers retain observed CPU/RSS samples separately from unknown final usage.

## Measured phases and transactions

| Full-persistence phase, wall seconds | 10k control | 10k instrumented | 25k seed29 instrumented |
|---|---:|---:|---:|
| close | 0.000679 | 0.000417 | 0.001482 |
| ingest | 12.929613 | 13.422130 | 33.708579 |
| initialize | 0.027724 | 0.027678 | 0.028286 |
| input_content_hash | 0.002905 | 0.002703 | 0.006554 |
| input_read | 0.014754 | 0.004171 | 0.004360 |
| json_parse | 0.066213 | 0.022403 | 0.056953 |
| recompute_including_run_persistence | 1.208169 | 1.154277 | 3.842867 |
| reread_verify | 0.514284 | 0.470727 | 1.293317 |
| restricted_export_json_serialization | 0.186201 | 0.169436 | 0.512109 |
| restricted_export_write | 0.007148 | 0.005902 | 0.031681 |
| run_persistence | 0.773138 | 0.692021 | 2.001224 |
| validate_common_contract | 0.058778 | 0.044304 | 0.116606 |

Run persistence is nested inside recomputation; inclusive buckets must not be added. Store digest includes its own serialization, while the separately wrapped store dumps calls measure other serialization call sites. SQL execute excludes later cursor fetch. Initial index construction is observed through before-statement trace intervals within the unchanged schema script; index maintenance stays included in INSERT and cannot be separately attributed here. JSON parse and input content hash are separately timed.

| Per-receipt / transaction observation | 10k instrumented | 25k seed29 instrumented |
|---|---:|---:|
| Physical receipts / BEGIN / COMMIT count | 10017.000000 | 25017.000000 |
| Receipt mean ms | 1.334919 | 1.342243 |
| Receipt p50 ms | 1.245693 | 1.247297 |
| Receipt within-run p95 ms | 1.846566 | 1.909547 |
| Receipt maximum ms | 23.384524 | 21.982533 |
| COMMIT total seconds | 11.005255 | 27.915796 |
| COMMIT mean ms | 1.098658 | 1.115873 |

COMMIT consumed 81.99% / 82.82% of ingestion wall time. Ingestion consumed 87.56% / 85.10% of the full worker body. This measured durable transaction boundary dominates these workloads; financial recomputation, normalization and content hashing are smaller observed costs. The SQLite settings remained journal_mode=delete, synchronous=2, page_size=4096. No physical-device throughput or billing is inferred from overlayfs process counters.

| Inclusive observed call bucket | 10k calls / wall s | 25k calls / wall s |
|---|---:|---:|
| ingest:digest | 20034 / 0.150270 | 50034 / 0.374999 |
| ingest:normalize | 10017 / 0.254338 | 25017 / 0.616886 |
| ingest:dumps | 20034 / 0.179219 | 50034 / 0.439714 |
| ingest:sql_begin | 10017 / 0.139453 | 25017 / 0.353623 |
| ingest:sql_commit | 10017 / 11.005255 | 25017 / 27.915796 |
| ingest:sql_insert | 20034 / 0.863811 | 50034 / 1.925305 |
| ingest:sql_select | 30051 / 0.115740 | 75051 / 0.296595 |
| initialize:sql_create_index_trace_interval | 2 / 0.002078 | 2 / 0.002023 |
| initialize:sql_create_index | 3 / 0.000080 | 3 / 0.000081 |

The two traced index statements are the initial financial indexes; three separately executed index statements belong to additive schema initialization. Their short per-call CPU counters can round to zero; zero is not evidence of free work. Index update cost remains included in INSERT. These nested buckets are attribution observations and must not be summed into a total.

No production optimization was attempted. A bounded follow-up could compare journal configurations while preserving one acknowledged durable transaction per receipt, then independently verify interruption/retry, duplicate/conflict, correction and temporal semantics plus the unchanged historical tests. Bulk batching that removes per-receipt crash boundaries is outside this evidence. The present measurement alone is insufficient to justify a durable-store behavior change.

## Instrumentation and result equivalence

At 10k, control and instrumented input DB and full exported result bytes were exactly equal; run_id, financial projection, counts and SQLite settings also matched. Both retained 10,017 receipts, one run, five findings and 20,034 evidence rows. The 25k seed29 sample retained 25,017 receipts, one run, five findings and 50,034 evidence rows. Independent CSV aggregation checks every receipt ordinal/status and every ingest BEGIN/COMMIT count, and sums the exact recorded commit timings. Financial checking within the runner uses the preserved Gate1/Gate2 closed-form oracle; this shared research dependency is not an independent institutional ledger.

The single off/on pair observed +0.306836 seconds worker-body wall (+2.04%) and +0.233632 seconds CPU. Both configurations already include phase/receipt clock calls and a CSV header; this difference covers incremental wrappers and per-receipt/transaction logging, not all measurement overhead. One pair cannot separate instrumentation cost from order, OS-cache and host noise. Fresh interpreter/database per trial; no OS page-cache flush. The 100-event common-lane warmup is retained separately. Host affinity/load/cgroup settings and 0.1-second process samples are retained.

Worker-start identity was first observed within approximately 0.103–0.105 seconds for the continuation, with 0.1-second polling. Parent elapsed minus worker-body time additionally includes imports, identity/hash/metric writes and polling/scheduling; it is not a pure interpreter-startup measurement.

## Failed attempt, repair and budgets

Original run-001 controller exited 1 after 176.089712 seconds. A SQLite DELETE journal disappeared between is_file and stat in the disk sampler. Four completed rows, all inputs/source snapshots, the traceback and the first extended-50k partial database remain unchanged. That worker outlived the failed controller; its exact owned PID was identified and SIGKILL sent, followed by observed zombie state. Its wait exit was not observed because the original parent was gone. It remains ERROR, never retroactively PASS or an inferred -9.

The research-only repair uses one stat with FileNotFoundError handling, kills and waits owned children on every controller exception and in final cleanup, and defers SIGALRM across Popen/ownership assignment. It refuses existing evidence directories and requires the selected continuation input bytes without historical fallback. The same two independent witnesses were RED on the frozen failed source and GREEN on the repaired source; the final targeted research set has ten methods. The original nine-row protocol was not rewritten. A separate reviewed continuation contract places the mandatory full-persistence 10k pair and 25k sample before optional extended diagnostics. Original four NOT_RUN cells remain in the combined roster and have distinct later continuation attempts.

The continuation used 270.281730 seconds of program wall, 7.861471 seconds controller CPU and 98.197528 seconds OS-waited child CPU; actual outer command wall was 270.393039 seconds. The original controller and killed-worker final CPU are NOT_MEASURED. The continuation preregistered 650-second wall / 180-second CPU budgets, reserving 20 seconds of each for cleanup; the reviewed prior active interval under 200 seconds has a conservative 400 CPU-second bound for the single-thread controller and sole single-thread worker. This is a structural bound, not a measured CPU total. Cumulative active wall / CPU bounds are 850 / 580 seconds, excluding idle repair/review time.

The controller and sole worker each cap address space at 1 GiB (2 GiB combined); kernel page cache is excluded. Child single-file cap is 384 MiB. The 1 GiB owned-disk budget includes preserved run-001, continuation files and recovery-copy headroom. Maximum sampled disk including recovery was 967,051,374 bytes; retained capacity bytes at completion were 848,490,655. Sampling and application guards are not a kernel filesystem quota or a certified worst-case scheduling bound. CPU/RAM/disk/time guards and exact argv/import origins are retained in every completed command/start record.

## Limits and replay prerequisites

The 60-second 50k and 100k results remain TIMEOUT. Extended 50k/100k are single successful restricted-common observations only. Full rich-history persistence at 50k/100k, natural-workload tails, sustained throughput, multiwriter contention, physical-device I/O, monetary costs, institutional RTO/RPO and service-level capacity are NOT_RUN or NOT_MEASURED. There was no production optimization or independent full-service baseline.

Recorded execution capture permits at most 10,000 eligible receipts (execution/capture.py:MAX_RECEIPTS), and replay API defaults to 30 seconds. Even this 10k-event input has 10,017 eligible receipts. None of these ordinary ingestion/reconciliation runs is an offline replay-capacity proof.

Raw evidence: capacity/run-001 and run-002, combined-roster.json, phase-analysis.json, repair-001, original/continuation contracts, and commands/capacity-run-001 and -002 under /workspace/validation-gate3-evidence. The machine roster retains all 14 attempt/planned cells: seven PASS, two TIMEOUT, one ERROR and four original NOT_RUN; ten attempts actually started including the warmup and orphan.

Large deterministic input JSON and SQLite/export artifacts may be omitted from the review ZIP under its explicit size policy. Their exact SHA/bytes remain recorded, and original local files are retained. Exact replay requires the original Gate2 seed11 captures and sealed Gate3 seed29 capture at the declared paths, or an explicitly separate manual reconstruction of these fully synthetic inputs whose canonical bytes match every preregistered SHA. Missing inputs are rejected. Reconstructed synthetic inputs do not replace missing real public raw bytes. The archive omission ledger is authoritative; a manifest verifies bytes, not external authenticity.

Exact continuation command (requires fresh output and the pinned original local evidence inputs; the historical attempt itself is never overwritten):

```sh
.venv-validation/bin/python -B -m validation_lab.gate3_capacity   --output /workspace/validation-gate3-evidence/capacity/run-NEW   --protocol /workspace/crypto-reconciliation-lab/contracts/gate3-capacity-continuation.json
```

The original failed harness source SHA is `c87bcd91f9b9a83d5d61b0ec5e855ade4452a7ae09ea7504a5cf10158db7098c`; the repaired continuation source is `eee9ae110eb87a950f4052ef61269c091d2cb384d403e306a7d559da3de7bae3`. The unchanged original protocol source SHA `6bd2974a943d0caab627dfe01cb1e98448a16648e3da96a624236de28c7054e6` names `run-001/source/contracts/gate3-capacity-protocol.json`, not the separately reserialized run protocol copy. The continuation contract is `c352a4206b98612818893132ec013d501cbb9099a3ddc5fe77bc6e87efc2affe`. All exact import origins and the 97-file continuation source closure are in worker-start records and the preregistration. Large raw artifact omissions limit independent replay from ZIP alone.
