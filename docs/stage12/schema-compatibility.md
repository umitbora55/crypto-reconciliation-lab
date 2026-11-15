# Schema 6 and historical compatibility

Package 0.10.0 introduces two additive tables: `execution_contexts` and
`recorded_executions`. Their primary keys, local request uniqueness, context
uniqueness, foreign keys, bounded BLOBs and append-only guards are explicit
SQLite definitions. `recorded_executions_run` indexes run/execution lookup.
No financial table, index, rule, amount representation or saved-run payload
definition changes. Migration 6 adds only these objects and its metadata row.

`validate_schema(connection, version)` checks the requested physical version,
the historical financial/correction definitions and guards, and each applicable
admission/auth/execution layer. Validation only reads SQLite metadata. It does
not repair missing guards, hide tables, migrate, or accept future versions.
Unrelated extension objects remain permitted and preserved. Known execution
object names are rejected under a historical version so a relabelled schema-6
database cannot become a schema-5 provenance source.

Existing guarded financial-save, feed-admission and source-auth operations use
`validate_runtime`, whose supported set is exactly `{5, 6}`. Direct legacy
`Store.ingest` retains its historical guard behavior. New recorded
execution uses exact schema 6. `Store(..., target_schema=5)` initializes a new
database through the real 0 → 2 → 3 → 4 → 5 steps and stops before migration 6.
The default new database completes migration 6. Existing databases are opened
without migration, and an explicit incompatible target is rejected. This
initializer never drops future tables or lowers `PRAGMA user_version`.

The provenance-v1 exporter continues to require physical schema 5 and invokes
the complete explicit historical validator. Its capture version remains 5.
Schema 6 receives `PROVENANCE_SCHEMA`; no new provenance format is implied.
Its producer and relevant test setups explicitly request genuine schema 5.
The financial review adapter adds a closed schema-6 entry and retains older
rule payloads that may have survived a real additive migration.

Explicit migration still takes a verified SQLite backup, rehearses rollback
and successful migration on a copy, verifies idempotency, restores the backup
to another new copy, and preserves every existing table/object/column/row.
Source opening and read/export operations never trigger this procedure.
Failure points before execution DDL, after its tables, after version 6 and
before commit prove atomic rollback of the additive step. The generic
transaction helper still rejects nesting without taking over a caller's
transaction.

Focused tests cover populated schema-5 migration, physical 5/6 distinctions,
all guard layers, altered old table definitions, retained extensions, hidden
future objects, SQL constraints, caller-owned transactions, unchanged ordinary
financial calculation, fixed provenance-v1 rejection and schema-6 financial
review. Real command results are retained outside Git; no historical baseline
suite or frozen experiment is rerun for this compatibility work.
