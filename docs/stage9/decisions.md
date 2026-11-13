# Stage 9 decisions

1. **A delivery layer around the existing transaction body.** `Store.ingest` already
   made record/receipt writes atomic. A private body returns its public result and
   physical receipt row to the transaction owner; legacy callers retain their
   result shape and per-call receipt behavior. Financial normalization stays in one
   place. Operational metadata never enters a financial result or knowledge cut.
2. **Three additive tables, one SQLite transaction.** Stream metadata is immutable;
   effects retain the first bytes and receipt; attempts retain retry, gap and block
   history. A stream/outcome index supports blocked/history queries, while effect
   identity uses its composite primary key. Strict-next and receipt-link triggers
   complement application validation. There is no mutable cursor or sidecar commit.
3. **Finite snapshots and strict framing.** Read the entire bounded regular file,
   then replay from sequence one on every restart. LF and exact bytes avoid newline
   ambiguity. Syntax rejection has its own retained disposition; financially invalid
   JSON envelopes use existing core quarantine. The limits are resource policy,
   not regulatory limits. Plan hashes are local integrity assertions, not signatures.
4. **Permanent transport block, bounded contention.** Changed identity/plan creates
   an immutable blocking attempt. No automatic recovery from a transport conflict
   is offered. Busy returns a retriable, explicitly non-durable response; retry is
   caller-controlled. ACK and financial success remain different concepts.
5. **Schema 4, package 0.7.0.** Opening an old database never migrates it. Explicit
   migration extends the existing backup/rehearsal/preservation workflow. Only
   supported-schema mappings change in the offline reader. Historical scope and
   financial reference files remain immutable; current test metadata adaptations
   are listed in `fixture-changes.md`.
6. **Real process barriers, independent readback.** A child reports the exact hook
   and waits; the supervisor then sends SIGKILL and joins it. Precommit checkpoints
   test all atomic layers, including the previously ambiguous record/receipt split.
   Postcommit response loss tests UNKNOWN followed by exact replay. Direct SQL and
   literal quantities are separate from runtime cursor/financial calculations.
7. **Evidence kept bounded and separate.** The small fixed schedule covers all
   declared subcases; incomplete coverage cannot pass. Final release validation
   uses the existing runner for source, wheel, matrix and no-AI gates. It does not
   repeat the frozen main model experiment or historical performance experiments.

## Source context and limits

Accessed 2026-11-13: [SQLite Atomic Commit](https://www.sqlite.org/atomiccommit.html)
describes atomic commit in rollback mode and its storage assumptions. This task
tests application-process termination only; it does not validate power-loss or
hardware durability claims. [Apache Kafka 4.4 design](https://kafka.apache.org/44/design/design/)
discusses delivery semantics and coordinating processing with position. It is
background for the local design, not a Kafka integration or equivalent guarantee.
The exact protocol above is this prototype's design decision. No PFMI/BCBS
conformance, institution deficiency or production resilience claim is made.

## Command behavior

Initialize or explicitly migrate a task-owned database before admission:

```sh
python3 -m crypto_reconciliation_lab init --db admission.sqlite3 --config config.json
python3 -m crypto_reconciliation_lab ingest-feed --db admission.sqlite3 --input input.jsonl --stream-id example-1
python3 -m crypto_reconciliation_lab feed-status --db admission.sqlite3 --stream-id example-1
python3 -m crypto_reconciliation_lab demo-recovery --output recovery-output-new --seed 19
```

`ingest-feed` exits 0 for a complete transport file without core INVALID/CONFLICT
or framing rejections; exit 1 reports incomplete/blocked or terminal invalid input.
These are not financial MATCHED claims. Configuration, file framing or unexpected
application errors exit 2. `feed-status` exits 0 when the history query succeeds,
even when its JSON describes BLOCKED. `demo-recovery` exits 0 only when every fixed
scenario and the expected negative harness control pass; an expected financial
MISMATCH can therefore belong to a passing demo. It refuses existing output paths.
Both general feed commands leave financial evaluation to an explicit later call.
