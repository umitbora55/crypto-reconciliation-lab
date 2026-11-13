# Restartable finite admission contract

Stage 9; package 0.7.0; physical schema 4; financial rule `stage2-v2`.
These are prototype design assumptions for a local synthetic reference project.
The existing core already commits each normalized record and receipt atomically,
and saves each financial evaluation atomically. This extension adds a transport
disposition and restart protocol, not another financial normalizer.

## Boundary and identities

A stream has a caller-chosen ASCII identifier matching
`[A-Za-z0-9][A-Za-z0-9._:-]{0,127}` and positive, contiguous sequence numbers
starting at one. A transport payload is the exact UTF-8 JSONL line **including
its final LF byte**. Hashes do not replace byte equality. Financial normalization,
economic business keys, trusted synthetic `received_at` and knowledge cuts remain
unchanged. A new sequence can legitimately produce a core DUPLICATE or CONFLICT.
Operational `observed_at` is a local UTC observation, never a financial clock or
authenticated source timestamp.

The file is bounded to 16 MiB, 10,000 lines and 65,536 bytes per line, including LF.
Only regular, nonsymlink finite files are read. The complete bounded snapshot is
read before admission; size/stat and digest checks detect observed read changes.
This is not adversarial filesystem authentication. Empty files, blank lines,
CRLF/CR, BOM, missing final LF and resource-limit violations reject the file before
any admission. Each LF-delimited line is decoded strictly as UTF-8 JSON; duplicate
object keys, NaN/Infinity, non-object envelopes and envelope keys other than exactly
`record` and `received_at` produce a terminal `REJECTED_FRAME` disposition with
retained exact bytes and reason, without fabricating a core receipt. A syntactically
valid envelope with invalid financial content goes through the existing core and
retains its INVALID receipt and quarantine semantics.

An `admission-plan-v1` contains `input_sha256`, `input_bytes`, `planned_lines` and
`framing=utf8-lf-jsonl-v1`. The first accepted sequence binds that plan to the stream
inside the same transaction as its disposition. Its immutable database row also
stores the canonical plan hash. Restart recomputes the whole snapshot identity and
compares it with this original binding; it cannot replace the plan. Changed content,
changed committed prefix or a shortened file is a durable PLAN_CONFLICT and blocks
further acceptance. The file command replays **every preceding line**, without
seeking over previously committed content. Direct API callers must supply a valid
declared plan; this local assertion is not a source signature or proof of membership.

## Atomic persistence and response

`BEGIN IMMEDIATE -> identity/sequence checks -> shared core ingest body if needed
-> delivery effect and attempt -> COMMIT -> response` is one transaction in one
SQLite database. There is no sidecar cursor. Existing public `Store.ingest` keeps
its signature, return shape and one physical receipt per call. Only its transaction
body is shared privately; operational replay never calls it again.

Schema 4 adds immutable `admission_streams`, `delivery_effects` and
`delivery_attempts`. Effects have primary key `(stream_id,sequence)`, exact BLOB
bytes/hash, original core result, physical core receipt row ID and stable receipt
hash. A unique receipt-row foreign key prevents assigning one core invocation to
two effects. `REJECTED_FRAME` has no receipt. Attempts retain bytes/hash, plan hash,
outcome, observation and reason, with an optional composite foreign key to the
existing effect. An attempt's stream text has no mandatory stream foreign key:
a gap before sequence one must be recordable without binding an unaccepted plan.
Append-only triggers protect all three tables from accidental UPDATE/DELETE.
Effect insertion enforces strict-next sequence, planned limit, an unblocked stream
and receipt linkage. These are application safeguards, not owner-resistant tamper
proofing. Existing tables, records, triggers and financial payloads remain intact.

The cursor is the contiguous committed effect prefix, including terminal INVALID
and REJECTED_FRAME dispositions. The reader checks that sequences equal `1..N`;
only under this invariant is `max(sequence)=N` meaningful. Plan count minus this
prefix describes pending transport deliveries, not missing economic events.

| Outcome | Durable attempt | ACK | Effect / cursor |
|---|---|---|---|
| COMMITTED | yes | yes | one new terminal disposition |
| REPLAY, identical stream/sequence/bytes | yes | yes | original result/receipt reused |
| TRANSPORT_CONFLICT, changed bytes at same identity | yes | no | first effect retained; permanently BLOCKED |
| PLAN_CONFLICT, changed stream plan | yes | no | no new effect; permanently BLOCKED |
| BLOCKED | yes | no | no new economic effect |
| GAP / OUT_OF_RANGE | yes when DB writable | no | no effect or prefix advance |
| RETRYABLE_BUSY | no | no | no claimed durable attempt or advance |

ACK means the terminal delivery result is committed. It does not mean financial
validity, completeness, source authenticity or MATCHED. A core INVALID or CONFLICT
is also a terminal delivery result. Conflict/blocked state is derived from immutable
attempts, with no automatic reset. Once blocked, even a replay is returned BLOCKED;
the original result remains inspectable through status/history. The SQLite busy
timeout is bounded (default 250 ms, maximum 5,000 ms); the caller may retry the exact
identity and bytes. The finite feed command stops on the first non-ACK and reports
INCOMPLETE/BLOCKED, rather than silently dropping or retrying without a limit.

If the process exits before a response, the sender knows only UNKNOWN. Commit may
have occurred. Retry is the resolution protocol, not an assumption of rollback.
General `ingest-feed` and `feed-status` never create a financial evaluation.
EOF proves only this snapshot ended. Financial delivery manifests and scope checks
are separate. `demo-recovery` joins all writers and verifies planned transport scope
before financial evaluation; blocked scenarios do not create a new run. No new
financial status or stage2-v2 reason code is invented for transport policy.

## Recovery experiment and equality

Experiments start with successfully initialized task-owned databases. Fixed opt-in
Python fault callbacks coordinate actual subprocess barriers: `ingest_before_receipt`,
`delivery_after_receipt`, `delivery_before_commit`, `delivery_after_commit`, and a
save-run barrier. The supervisor observes the named barrier, kills the child and
joins it before reopening; a sleep duration is never proof of a reached stage.
Hooks are absent in default CLI operation. The fixed scenario schedule declares
all subcases, including each precommit barrier, both writer arrangements, malformed
input and changed/shortened snapshots. Independent literal transport expectations
and SQL readback check prefix, rows, receipt links, history, integrity and foreign
keys. A deliberately broken test double must fail the same acceptance oracle.

Three equalities remain separate: (1) the unchanged 373 legacy financial files
equal the frozen reference; (2) exact transport replay adds no core receipt and
therefore reproduces the same financial payload/run ID; (3) new core receipts may
preserve economic quantities while changing evidence and run identity. The demo
records which comparison is appropriate. Timing is an observation, not an SLA/RTO.

The fault model covers application-process termination and bounded SQLite writer
contention, not initialization crashes, power loss, kernel failure, disk corruption,
network partitions, distributed consensus or Byzantine sources. Keep rollback
journaling and synchronous settings; no automatic WAL or reduced durability.

## Compatibility

New databases explicitly follow 0 -> 2 -> 3 -> 4. Existing opens never migrate;
explicit migration requires verified backup, rollback rehearsal, preservation,
idempotency and restoration into a separate new target. The read-only review
adapter accepts schema 4 saved financial runs without operational enrichment.
Old scope/reference documents remain historical. A separate fixed 0.7.0 roster
retains all 400 previous test identities plus declared additions and narrow
metadata-fixture changes. No training or final holdout of the frozen main experiment
is part of this task.
