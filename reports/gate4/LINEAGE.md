# Gate 4 source, archive and environment intake

The Gate 4 research branch starts from accepted Gate 3 commit
`c08114e847b8b0ab58f28d41917ba386878fa873`, tree
`f049ed4f2c35e2e8bf95b58611047837af01b1d7`. The independently recorded
`git ls-remote` still resolved main to
`b48021273405128c67e2969fd4b46f8d7e876a99`, the validation branch and PR #7
head to the accepted Gate 3 commit. The retained actual API response identifies
PR #7 as open, draft and unmerged. Its two exact-head release runs,
[43962299524](https://github.com/umitbora55/crypto-reconciliation-lab/actions/runs/43962299524)
and [43962304946](https://github.com/umitbora55/crypto-reconciliation-lab/actions/runs/43962304946),
are completed/success in the newly retained API response. These are historical
Gate 3 CI observations, not Gate 4 final-head acceptance.

The canonical new inventory is
`/workspace/validation-gate4-evidence/intake-audit/inventory-002/audit-result.json`.
It compares every one of the 445 prior files against its immutable Git blob,
records Git mode/blob/SHA-256/size, and retains all Git command outputs. The
current branch at intake was `research/gate4-transaction-durability`. All 445
original working files matched before and after each recorded intake command.
Package/rule/schema remain **0.11.1 / stage2-v2 / 6**.

The stdlib-only inventory imports no application, financial engine, generator,
release-scope helper or evidence-verification helper. Static AST enumeration
matches all 875 original test identities across the protected 94-file scope.
Exactly the three historical Gate 2 exceptions reverse to their declared
original hashes and original Git blobs; the other 91 files match directly.
The financial reference remains 70,721 bytes, SHA-256
`4abda380a19acd4cdfed97a46b6fb15528f32b8ef308c6931815c5b03641275e`, declaring
373 files. This is a byte/static inventory, not a new execution of the 875 tests
or financial reference suite.

## Actual Gate 3 archive and omissions

The original archive was accessible and was reread at
`/workspace/validation-gate3-delivery/review/crypto-reconciliation-validation-gate3.zip`.
The new command exited 0 in 20.541740 seconds; its result is
`intake-audit/archive-audit-001/audit-result.json` under the Gate 4 evidence root.
The auditor is an exact retained copy of the previously independent stdlib/Git
auditor, SHA-256
`cac714f9b1e2ab0b0fd029c76ca97de892ed7616091939dc5e6a40943da3e06e`.
It does not import the project archive helper. Reusing this audit implementation
is disclosed; the check is a fresh byte reread, not an independent implementation
of the previous archive auditor.

| Check | Actual result |
| --- | --- |
| External archive identity | 102,474,747 bytes; SHA-256 `73949a1325de7b99c8b09a226b4deadf408c46a72c1cd6d9f3b4b1de814a7aa7` |
| ZIP contents | 13,053 unique regular members; 720,081,936 expanded bytes; safe names, modes, encryption flags, CRC and finite size limits passed |
| Internal manifest | All 13,052 nonself member hashes and sizes matched |
| Source identity | All 445 source members equal the complete selected Git tree and immutable blobs |
| Included evidence | 12,606 staged files checked; 12,605 included originals independently reread and compared with archived bytes |
| Omission ledger | 688 entries: all 671 hashed original omitted files reread; 17 subtree/sensitive entries not expanded |
| Ledger identity | 5,317,551 bytes; SHA-256 `576c1f1fb841ec0aa62661d4b46462b89acc7dc2d496328b5edbca284e02d963` |

The archive was streamed and checked against original/staged files; no new
extracted-tree audit is claimed. Omitted SEC/site bodies, large databases,
environments and raw account metadata remain omissions. Local availability and
successful rehashing do not establish redistribution rights. Hashes establish
byte identity, not publisher authority, timing attestation, economic truth or
institutional authenticity.

## Historical decisions and input definitions

The inventory pins 64 historical documents, including all report files,
Gate 3 reproduction instructions, capacity contracts, the failed original
harness, later continuation evidence and the external terminal decision. The
request's `reports/gate3/NOT_RUN.md` is absent; the actual preserved inventory
is [NOT_RUN.json](../gate3/NOT_RUN.json).

The committed Gate 3 decision remains **NOT_READY** at its source-seal time,
pending exact-head CI/archive checks. The later original external decision
remains **GATE3_EVIDENCE_READY**. Neither observation is rewritten or substituted
for the other. Gate 1/2 decisions and original failed attempts retain their
original bytes and temporal meaning.

Historical capacity remains: 25k **38.705676 seconds** under 60 seconds;
50k and 100k **TIMEOUT** under 60 seconds. The separate extended restricted
common-lane results are **65.443014 / 128.970663 seconds**. They do not establish
a 60-second SLA, rich-history capacity or offline replay throughput. The failed
controller and orphan's **wait exit NOT_OBSERVED** remain failed evidence.
The original COMMIT attribution of about 82% covers inclusive SQLite COMMIT
call time at 10k/25k with one transaction per receipt, DELETE and synchronous=2.
It is a host/workload observation and optimization hypothesis, not a measured
speedup or physical-device latency measurement.

The unchanged original capacity protocol is SHA-256
`6bd2974a943d0caab627dfe01cb1e98448a16648e3da96a624236de28c7054e6`;
the failed original harness is
`c87bcd91f9b9a83d5d61b0ec5e855ade4452a7ae09ea7504a5cf10158db7098c`.
The separate continuation contract is
`c352a4206b98612818893132ec013d501cbb9099a3ddc5fe77bc6e87efc2affe`
and its repaired harness is
`eee9ae110eb87a950f4052ef61269c091d2cb384d403e306a7d559da3de7bae3`.
The full 445-file manifest also pins the original Gate 1/2 benchmark definitions.

All four selected continuation inputs remain present and match both their
preregistered hashes and original run-001 bytes. No reconstruction was needed:

| Synthetic case | Bytes | SHA-256 |
| --- | ---: | --- |
| 10,000 events, seed 11 | 4,596,911 | `c246c488a9845ad11e9628fd647cb1fb826ec6bc797bd3684781f247801926c2` |
| 25,000 events, seed 29 | 11,516,911 | `8f8902a3e4970478da5d397d2141f7d534d2e097751d727578af38bbfb556a3f` |
| 50,000 events, seed 11 | 23,050,240 | `36aad48c8f3776a43da1591948e2fa7675a54f5248749e469888c5b55c35a145` |
| 100,000 events, seed 11 | 46,116,913 | `85c78c20590d2b7162b6ea076dd0abdb10ed9f9b318b985f45c5f938a0f85e88` |

Presence of optional larger inputs does not authorize extra trials. Gate 4's
independent receipt/order/economic-oracle checks and new measurements are
separate evidence, not assertions established by this byte inventory. Five
original continuation metric files record DELETE / synchronous=2 / 4096-byte
pages. Their retained hashes and actual field names distinguish full-persistence
`physical_receipts` from restricted-common `rows`.

The original synthetic 264-case ledger retains TP132/FP0/TN120/FN12. The 24 LAB
reference cases add laboratory-signed inputs and do not erase those twelve
count-only false negatives. Treasury/SEC evidence remains separate from these
synthetic benchmarks. Independent institutional counterparties remain zero;
natural-error precision/recall and institutional cost, RTO/RPO, risk or
compliance conclusions remain unsupported.

## Current runtime observations

Fresh small runtime probes, not product or performance trials, ran on both
interpreters with actual imports and installed package versions recorded in
`runtime-py312-001/runtime.json` and `runtime-py314-001/runtime.json`.

| Item | Observed at intake |
| --- | --- |
| Python / SQLite | Python 3.12.14 and 3.14.10; SQLite 3.53.1 on both |
| Kernel / architecture | Linux 6.18.57, x86_64; build `#1 SMP Tue Oct 20 21:56:04 UTC 2026` |
| Visible CPU | AMD EPYC 9V74 80-Core Processor model; 5 visible CPUs, affinity 0–4; KVM |
| Cgroup limits | `cpu.max=400000 100000` (4 CPU equivalents); `memory.max=34359738368` (32 GiB); effective cpuset 0–4 |
| Filesystem | `/workspace` overlayfs, 4096-byte blocks; exact mount options and mountinfo retained |
| Available logical disk | 57,647,202,304 bytes at the inventory observation |
| Load observations | Inventory 1/5/15-minute load 0.083984 / 0.062012 / 0.019531; probes 0.118164 / 0.067871 / 0.021484 |
| Empty sqlite3 defaults | DELETE, synchronous=2, page_size=4096, wal_autocheckpoint=1000, busy_timeout=5000 |

Empty sqlite3 defaults are not product Store settings: notably the raw probe's
foreign_keys=0 is not an observation of the application's configured connection.
Connection-local PRAGMAs cannot be established retrospectively by reopening an
old database. Each Gate 4 worker must separately record its actual configured
PRAGMAs. The probes retain SQLite source ID, compile options, resource limits,
package versions and import origins. Host configuration/load may change before
or during the experiment; these are timestamped intake observations, not a
claim of exclusive hardware or physical I/O visibility.

## Actual commands and retained failure

The archive, source inventory and runtime probes all have separate fresh command
directories, exact argv/cwd/UTC/owned PID/actual wait exit, stdout/stderr hashes,
script pins and 445-file before/after proofs. The successful inventory executed
460 recorded Git/system commands and exited 0 in 2.222700 seconds; both runtime
probes exited 0 in about 0.165 seconds. No suite or benchmark was rerun here.

`inventory-001` is retained with exit 1: the new inventory reader initially
looked for the full-persistence `physical_receipts` field in a historical
restricted-common metric that uses `rows`. Its exact failed script is preserved
as `inventory-attempt-001.py`. The corrected reader explicitly distinguishes
the two existing schemas; `inventory-002` passed without changing old evidence.
This is an inventory-reader correction, not a production fix or reclassification
of a historical failure.
