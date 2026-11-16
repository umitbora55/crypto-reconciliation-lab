# Preliminary contract and claim review

This is a source-backed pre-review at accepted commit `b48021273405128c67e2969fd4b46f8d7e876a99`, package 0.11.1, rule `stage2-v2`, physical SQLite schema 6. It does not certify financial institutions or substitute static inspection for executed validation. The attached user request dated 16 November 2026 authorizes a new independent validation program; historical task-specific no-rerun notes are not a claim that this new program has already passed.

## Observed baseline and immutable scope

The main HTTPS Git read resolves to the accepted SHA. Static `scripts.release_test_scope.validate_test_files` passed: all **875 expected IDs and 94 protected files** exactly match the pinned 0.11.1 contract, including its composed historical fixture exceptions. This is byte/scope evidence, not execution of 875 tests. The new research tests must stay outside the protected `tests/` inventory.

The 70,721-byte historical financial reference has SHA-256 `4abda380a19acd4cdfed97a46b6fb15528f32b8ef308c6931815c5b03641275e`; its complete identity and declared 325 matrix + 12 Stage 1 + 36 Stage 2 = **373 report files** passed the existing static validator. The old reference binds 69 cases, 162 matrix evaluations, seeds 11/29/47, 100 events and six investors. These are reference settings, not newly observed performance results.

Evidence is outside Git under `/workspace/validation-evidence/inventory/`: `test-scope-preflight.json`, `financial-reference-preflight.json`, `inventory-summary.json`, `format-token-inventory.json`, and the inventory generator. Current-run release results belong to the separately executed source/installed gate, not this pre-review.

## Claims and executable boundaries

| Area | Source-backed contract | Implication for this validation |
|---|---|---|
| Financial arithmetic | Exact Decimal with fresh precision-64 trapped context; canonical text amounts; no production SQL SUM/REAL conversion. A compares ledger-derived investor quantities; B compares ledger liabilities with customer custody. | Independent baselines must use integer units/literal truth. A SQL integer SUM baseline is research code only and has narrower overflow/semantics constraints. |
| Input quantities | Nonnegative ASCII decimal text, events strictly positive; <=64 characters; magnitude <10^40; precision 0–18. | Rejection at a declared numerical boundary can be success; silently rounded arithmetic cannot. |
| Economic and knowledge time | `opening_at < occurred_at <= balance_at`; an eligible receipt is known by `knowledge_at`; report selection uses highest numeric version known at the exact balance cut. | Permutation equivalence applies only where ordering is semantically irrelevant. Late/backdated imports can change a fresh query but not saved snapshots. |
| Completeness | Counts plus required scopes; duplicate/quarantined records do not fill shortfalls. Manifests are source assertions. | **Same-count substitution is explicitly not detectable by count-only financial manifests**. Treat this as a documented limitation, not invented ground truth or an unqualified new defect. |
| Verdicts | `CONFLICT > INCOMPLETE > STALE > COMPLETE`; only COMPLETE permits MATCHED/MISMATCH. Missing values are null, never zero. | A correct reproduced MISMATCH or INCOMPLETE can have a successful replay; operational and financial success must remain separate. |
| Corrections | Full VOID and amount-only REPLACE; atomic groups with dependencies/competition; original event delivery count and historical rows stay unchanged. | A simple additive baseline is not semantically equivalent for all workloads. |
| Persistence | Local SQLite append-only application guards and content hashes. Database owners can replace a complete self-consistent database. | Neither trigger checks nor hash consistency proves authenticity against a privileged owner. |
| Recorded execution | One owned BEGIN IMMEDIATE transaction binds all eligible physical receipts and observed policy context. Request identity is local to one database. | Same-request replay is not a new financial calculation or distributed exactly-once. ACK loss after commit leaves a durable effect. |
| Provenance | Historical capture-v1 is schema 5 only; recorded execution is schema 6. | Do not relabel a schema-6 database as an old provenance capture or infer past run creation from later evidence. |
| Offline replay | Exactly context.json + run.json plus a caller-selected external pin; current unchanged engine computes once; full payload and run ID comparison. | Same-engine reproducibility is not an independent financial algorithm, original executable proof, original signature verification, or institutional authentication. |
| Stage 13.1 repairs | Auth decision/attempt links must share `(stream_id, sequence)`; output canonicalization failures preserve completed comparison details. | Coherently rehashed structural contradictions must reject; output errors must not erase a completed divergence. |
| AI | Historical fixed model showed no advantage over frozen rules; ranking does not change balances or verdicts. | Frozen generation/training/holdout is excluded. New validation cannot claim a new AI improvement. |

Sources: `docs/model_contract.md`, `docs/correction_semantics.md`, `docs/stage12/execution-contract.md`, `docs/stage13/replay-contract.md`, `docs/stage13_1/repair-contract.md`, `scripts/release_test_scope.py`, `scripts/release_financial_scope.py`, and their linked source modules.

## Separate finite execution paths

| Path | Declared limits and relevant caveat |
|---|---|
| Direct Store ingestion / ordinary reconciliation | No 100k capacity guarantee follows from a successful small test. Exact arithmetic, memory, validation and result size can still constrain a workload. Measure separately from bounded feed and replay. |
| Finite JSONL feed | 16 MiB file, 10,000 lines, 65,536 bytes per line; fixed framing and scope. `crypto_reconciliation_lab/admission/feed.py`. |
| Recorded execution | 10,000 eligible receipts; 50,000 captured rows; 256 epochs; 4 MiB per SQL value; 16 MiB context; 16 MiB saved run; 16 KiB request. Breach aborts new execution, never truncated RECORDED. |
| Offline replay | 16 MiB per authoritative file, 32 MiB combined; same receipt/row/epoch bounds; depth 1,024; 16,777,216 parsed nodes; 4 MiB result; 100 retained differences/financial details; preview 256 characters. Default 30 seconds, valid integer domain 1–60. No portable hard-memory guarantee. |
| Review export | Finite source/run/selection constraints plus 128 MiB produced HTML. It displays saved values and does not recompute truth. |
| Schema-5 provenance | Separate ceilings: run 8 MiB, capture 32 MiB, data 64 MiB, DB 256 MiB, total 128 MiB, 1,024 files, 100,000 rows, depth 32, 200,000 nodes, 1,024 epochs. These are not the replay limits. |

A controlled `LIMIT`, `ERROR` or `TIMEOUT` above a supported bound is an expected negative control, not throughput success. A 100k direct-ingest test must not be labelled a 100k offline-replay pass.

## Physical data and evidence inventory

| Layer | Authoritative input / persisted object | Derived or limited evidence |
|---|---|---|
| Financial input | Exact JSONL receipt envelopes; closed configuration; normalized records and physical receipt rows in SQLite. Corrections have separate envelopes/manifests. | Intake diagnostics do not replace reevaluation at the requested cuts. |
| Financial result | Stored canonical run payload, findings/evidence/correction mirrors; explicit rule/cuts and content identity. | Markdown report is presentation; run hash alone is not an external trust root. |
| Review | `review-selection-v1` identifies saved runs; `review-bundle-v1` captures exact selected payloads and evidence. | HTML controls/downloads display saved answers; no independent recomputation. |
| Admission | Fixed JSONL framing, `admission-plan-v1`, stream/position/effect/attempt rows. `delivery-response-v1`, `feed-status-v1`, `feed-admission-v1`. | `admission-recovery-v2` and schedule are finite experiment records, not production durability certification. |
| Source authentication | DSSE payload type `application/vnd.crypto-reconciliation.source-admission.v1+json`; `source-admission-statement-v1`, `source-auth-policy-v1`, key/epoch/decision/link tables. | `source-auth-status-v1`, admission/verification/file-manifest/experiment reports describe bounded local-policy acceptance. Test anchors are not institutional trust. |
| Historical provenance | `run-provenance-capture-v1` (schema 5), report and `run-provenance-bundle-v1`; external expectations/trust input. | `run-provenance-verification-v1` and offline UI have no signature/financial claims beyond their explicit profile. |
| Recorded execution | `recorded-execution-v1` exact context BLOB; request/execution binding; exact SQL TEXT run bytes; schema-6 context and execution tables. | Five-file export contains authoritative context.json/run.json plus execution.json, summary.json and summary.md. Old ordinary runs remain NOT_RECORDED. |
| Replay | Only the two explicit authoritative files and separately supplied external execution ID. | `execution-replay-report-v1` includes current executable identity and comparison; original executable remains NOT_RECORDED. Demo catalog/summary cannot substitute input or pin authority. |
| Lab oracle | Independent integer-world generator and controlled-fault plans; closed lab contract and literal truth. | Benchmark/profile logs are finite observed runs, not institutional capacity. |
| Frozen triage | `triage-experiment-v1`, split/episode/truth/feature/model/label/queue/metric formats. | Data/model/holdout are frozen historical artifacts; subset JSON scoring is not retraining or a new holdout score. |
| Release | Pinned `release-test-scope-v1` lineage and `financial-reference-v1` identities. | Build/verification reports describe their exact commit, command, profile, source/installed origins and execution scope. |

The raw source-token inventory lists **50 versioned format/rule tokens** and every source occurrence. Some are test/demo diagnostics, so 50 is not a count of independent authoritative contracts.

## CI identity and evidence distinction

README attributes five successful jobs to historical main run [43741674664](https://github.com/umitbora55/crypto-reconciliation-lab/actions/runs/43741674664), commit `b2df4f13eb7e2fc6b048f17eaaa24f02bf0bd29e`, on 15 November 2026: source and installed full suites for Python 3.12 and 3.14 (875 IDs each), a Python-3.14 financial matrix, and core/auth-only profile checks. This is a **historical repository claim**, not a new execution or independently downloaded CI record in this task.

The native read-only `gh api` request to `api.github.com` was denied (`Forbidden`, exit 1). The baseline-SHA workflow query was also denied. Exact argv, cwd, timestamps, stdout/stderr and exits are retained in the inventory directory. Thus remote CI run/job/artifact identities are **UNVERIFIED_REMOTE** until allowed access succeeds. Successful HTTPS Git read is narrower evidence than GitHub API access.

The full current-run gate and any later exact-commit CI must be reported separately. Linux/Python-3.12 results cannot establish Python 3.14 or macOS arm64 behavior; absent platform execution is NOT_RUN.

## Publication-time CI observation

A later public-web fallback retrieved historical run [43741674664](https://github.com/umitbora55/crypto-reconciliation-lab/actions/runs/43741674664): the GitHub page shows Success for `b2df4f1`, 11m29s and four artifacts. Artifact bytes and authenticated job logs remain unverified. The initial research commit `f8fe98a` was pushed normally; its public workflow run43925469151 was In progress at this observation. API/GraphQL requests still return Forbidden, so draft PR creation failed. Final later observations belong to the external `VALIDATION_HANDOFF.md`, not a claim that the earlier API requests succeeded. Raw page bytes and hashes: `inventory/web-ci-observations.json`.
