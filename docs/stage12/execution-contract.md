# Recorded execution contract

This stage introduces package 0.10.0 and additive schema 6. Financial rule
stage2-v2, canonical financial payloads/run IDs and historical reference files
remain unchanged. This is a local observation of recorded input admission, not
permission for an actor to run reconciliation.

## Identities and canonical bytes

- `run_id`: unchanged SHA-256 of the canonical financial result without run_id.
- `request_id`: ASCII identifier [A-Za-z0-9][A-Za-z0-9_.:-]{0,127}, unique in
  this database's append-only recorded_executions registry. A filesystem path
  is never an identity; moving the database preserves retries. Independent
  database copies have no distributed exactly-once guarantee.
- Stable request parameters: format, literal database scope
  `local-request-registry`, UTC-normalized balance_at/knowledge_at, configuration
  digest, financial rule and profile `all-known-receipts-v1`. SHA-256 of their
  canonical JSON is request_fingerprint. Input rows, policy head, observation
  time and presentation paths are excluded.
- Context format: `recorded-execution-v1`. Canonical JSON uses sorted keys,
  compact separators, ASCII escaping and no NaN/Infinity. It is stored as its
  exact BLOB bytes. context_hash is SHA-256 of those bytes.
- execution_id is SHA-256 of canonical format/request_id/request_fingerprint/
  run_id/run_payload_sha256/context_hash bindings. It is deterministic and
  database-scoped, not a global identity. Different requests can reference the
  same run. The context includes its request identity, so separate requests
  remain distinct even when financial results agree.
- Raw run payload SHA-256 hashes the actual stored SQL TEXT encoded as UTF-8,
  not its canonicalized representation. A valid pre-existing alternate JSON
  serialization remains bound to its actual stored bytes.

Hashes detect local inconsistency; they are not an external trust root or a
proof against an owner who replaces a complete, self-consistent database.

## Input and admission scope

The writer owns BEGIN IMMEDIATE before reading configuration or financial
inputs. Configuration is reread and validated inside that transaction;
Store.config is not an observation source. All physical receipts satisfying
received_at <= knowledge_at OR received_at IS NULL are captured, including
invalid/quarantined receipts, raw envelope TEXT, status/error and nullable
record_id. Every referenced normalized record is captured with original
payload TEXT and its content identity. Future receipts are excluded.

All physical candidates with the same receipt hash remain separate integer
rows. No first/last/minimum ID is declared the historical source chosen by the
hash-deduplicating financial engine. The context separately maps selected
financial evidence IDs to eligible physical receipt IDs and record IDs. An
explicit complete empty inventory is valid; it is not missing capture.
Derived correction groups map to both correction and target record identities
and their eligible physical receipt candidates; they are not physical receipts.

For eligible physical receipts, capture their delivery effects, associated
streams, all attempts at each selected (stream,sequence) position, delivery
auth links, attempt auth links, referenced decisions and endorsements. Preserve
original COMMITTED and replay relationships. Capture the protected
configuration, the complete bounded activation chain observed in this
transaction, its policy snapshots and persistent public-key registry. This
includes the observed policy head and the referenced original acceptance
epochs, which are different facts. Unrelated positions, receipt-free frame
rejections and the database-wide auth rejection history are excluded. This is
not the entire database's acceptance history.

SQL integer identities remain exact JSON integers through Python/SQLite; there
is no browser/JavaScript transport in this feature. BLOB columns are losslessly
hex-encoded with an explicit encoding declaration. Original SQL TEXT remains
text. Dynamic context never leaks into the financial payload.

Claims are separate: context_state=RECORDED; admission_mode=PROTECTED or LEGACY;
source_signature_verification=NOT_PERFORMED; run_actor_authorization=NOT_DEFINED.
Legacy admission is labelled UNSIGNED. Previously saved ordinary runs remain
NOT_RECORDED until a new recorded computation is explicitly requested; that
new execution does not describe the old run's original creation.

## Storage and transaction ownership

Schema 6 adds execution_contexts(context_hash,format,payload) and
recorded_executions(execution_id,request_id,request_fingerprint,request_payload,
run_id,run_payload_sha256,context_hash), with PK/FK/unique/type constraints,
append-only UPDATE/DELETE guards and a run lookup index. context_hash is unique
per execution. The request record is the execution row; there is no redundant
mutable request table or failed-attempt journal.

The writer rejects an existing caller transaction before touching it. It owns
one existing migrations.transaction boundary (BEGIN IMMEDIATE, one commit,
rollback on failure); the generic nested-transaction rejection remains intact.
A narrow Store._save_run_in_transaction persistence body is shared with the old
save_run wrapper. A private transaction-owned facade supplies that body to the
unchanged financial engine. No financial formula/selection/correction change
is required.

Inside the owned transaction: read configuration, form stable request, lookup
request, then capture inputs/admission and compute only on a cache miss. Validate
any pre-existing financial run and exact findings/evidence/correction mirrors
before reuse. Never repair inconsistent historical rows via INSERT OR IGNORE.
Bind context to the actual saved run bytes; write context/execution/request
binding; commit once. All new rows roll back on precommit failure; any
pre-existing valid financial run survives.

Same request/fingerprint returns the original execution and context without
new capture or financial computation. A changed stable request is
EXECUTION_REQUEST_CONFLICT. A new request creates a separate execution.
Corrupt stored bindings, orphan contexts, invalid hashes or missing mirrors
are EXECUTION_INTEGRITY, never a successful retry.

busy_timeout_ms is bounded 0..5000 (default 250), restored afterward; there is
no automatic retry loop or journal/durability pragma change. SQLITE_BUSY is
EXECUTION_BUSY. No success is returned before commit. After commit, ACK/stdout
or export I/O failure cannot undo the durable request; retry reads it.

Resource ceilings: 10,000 eligible receipts; 50,000 total captured rows;
256 policy epochs; 4 MiB per SQL value; 16 MiB canonical context; 16 MiB saved
run; 16 KiB stable request. Exceeding a ceiling aborts the new execution entirely.
No truncation is labelled RECORDED. Reader limits match writer limits.

## API, CLI and readable export

Python APIs: reconcile_recorded(store,balance_at,knowledge_at,request_id,
*,busy_timeout_ms=250,configuration_digest=None,rule_version=RULE_VERSION,
profile=PROFILE,_fault=None); read_execution(db_path,execution_id=None,
*,run_id=None); export_execution(db_path,execution_id,output).
Public result keys include status, replayed, request_id, execution_id, run_id,
context_hash, run_payload_sha256, request, context and financial_result.

CLI: reconcile-recorded --db --balance-at --knowledge-at --request-id
[--busy-timeout-ms]; show-execution --db (--execution-id|--run-id);
export-execution --db --execution-id --output; demo-execution-context --output
[--profile legacy|protected]. Successful reconcile follows financial CLI policy:
exit 0 for matched evaluation, 1 for observed non-matched financial outcome;
operational/input/conflict/integrity errors exit 2 with explicit reason_code.
Show/export succeed with exit 0 independently of MATCHED/MISMATCH. Demo exits
0 only when every independently specified expected case/reason was observed.

Read/export opens an existing regular DB with SQLite mode=ro and a read
transaction, never Store, migration, reconciliation or admission. Schema 6
reads the stored inventory; no later live receipt/policy enrichment occurs.
Run-only lookup returns NOT_RECORDED for a legacy run, or lists all execution
IDs without choosing when there are several. Export publishes a fresh directory
atomically with exact context.json and run.json bytes, execution.json and a
small summary.json/summary.md. Existing targets and DB/sidecar namespace overlap
are rejected; failures do not leave a successful partial publication.

## Compatibility and validation boundary

New Store defaults to real schema 6; explicit target_schema=5 initializes real
historical DDL through the original migrations. Existing guarded financial-save,
feed-admission and source-auth paths use a closed {5,6} validator; direct legacy
Store.ingest retains its historical guards. Recorded execution requires 6.
Historical schema validators validate their complete required DDL and guards
without hiding future execution objects or rejecting unrelated user extensions.
Opening an older database never migrates. Explicit migration preserves backup,
rollback, restore and idempotency for supported 0/2/3/4/5 inputs.

Provenance capture-v1 remains real schema 5 only, with exact historical
validation and unchanged v1/5 metadata. Schema 6 gets a clear version rejection,
not a relabelled capture or downgrade. The existing financial review path gains
only the explicit schema-6/stage2-v2 support entry. Old test IDs/assertions
remain; permitted schema/version and true legacy-5 setup edits are documented.

Tests use private Python fault callbacks, never a production CLI/environment
fault endpoint. Exact child barriers cover after financial persistence, after
context before commit and after commit before CLI ACK; both fresh/pre-existing
run variants. Separate processes perform real admission/policy races and
same-request contention. SIGKILL evidence covers process interruption, not
power loss, disk corruption or distributed durability.

