"""Append-only local evidence store; no SQL quantity arithmetic."""
import json
import sqlite3
from .migrations import SCHEMA_VERSION, inject, migrate_connection, transaction, validate_current, validate_open
from .model import config_validate, digest, dumps, normalize, timestamp

SCHEMA = """
CREATE TABLE IF NOT EXISTS configuration (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS records (
 id TEXT PRIMARY KEY, logical_key TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS receipts (
 id INTEGER PRIMARY KEY, receipt_hash TEXT NOT NULL, record_id TEXT REFERENCES records(id),
 received_at TEXT, raw TEXT NOT NULL, error TEXT, status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS receipts_time ON receipts(received_at);
CREATE INDEX IF NOT EXISTS records_key ON records(logical_key);
CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, balance_at TEXT NOT NULL, knowledge_at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS findings (run_id TEXT NOT NULL REFERENCES runs(id), ordinal INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(run_id, ordinal));
CREATE TABLE IF NOT EXISTS evidence (run_id TEXT NOT NULL REFERENCES runs(id), evidence_id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(run_id, evidence_id));
"""


class Store:
    def __init__(self, path, config=None, *, busy_timeout_ms=None):
        config = config_validate(config) if config is not None else None
        if busy_timeout_ms is not None and (type(busy_timeout_ms) is not int or not 0 <= busy_timeout_ms <= 5000):
            raise ValueError("DELIVERY_INPUT: busy timeout must be an integer between 0 and 5000 ms")
        self.db = sqlite3.connect(path, isolation_level=None,
                                  timeout=5.0 if busy_timeout_ms is None else busy_timeout_ms / 1000)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        try:
            existing = self.db.execute("SELECT name,type FROM sqlite_master").fetchall()
        except sqlite3.Error:
            self.close()
            raise
        if not existing and self.db.execute("PRAGMA user_version").fetchone()[0] != 0:
            self.close()
            raise ValueError("SCHEMA_INVALID: a versioned database cannot have an empty schema")
        if not existing:
            if config is None:
                self.close()
                raise ValueError("new database requires configuration")
            self.db.executescript(SCHEMA)
        elif not any(r[0] == "configuration" and r[1] == "table" for r in existing):
            self.close()
            raise ValueError("SCHEMA_INVALID: existing database has no configuration table")
        try:
            if existing:
                validate_open(self.db)
        except (ValueError, sqlite3.Error):
            self.close()
            raise
        try:
            saved = self.db.execute("SELECT payload FROM configuration WHERE id=1").fetchone()
        except sqlite3.Error:
            self.close()
            raise
        if saved:
            self.config = json.loads(saved[0])
            if config is not None and config != self.config:
                self.close()
                raise ValueError("database configuration is immutable; use a new database")
        elif existing:
            self.close()
            raise ValueError("SCHEMA_INVALID: existing database has no saved configuration")
        elif config is None:
            self.close()
            raise ValueError("new database requires configuration")
        else:
            self.config = config
            with transaction(self.db):
                self.db.execute("INSERT INTO configuration VALUES (1, ?)", (dumps(self.config),))
        if saved is None:
            migrate_connection(self.db)
        # Only a new database receives initialization DDL; opening history is read-only.
        if saved is None:
            for table in ("configuration", "records", "receipts", "runs", "findings", "evidence"):
                for action in ("UPDATE", "DELETE"):
                    self.db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'append-only table'); END")

    def close(self):
        self.db.close()

    def ingest(self, raw, received_at, *, fault=None):
        from .source_auth.schema import reject_unsigned
        with transaction(self.db):
            reject_unsigned(self.db)
            result, _ = self._ingest_in_transaction(raw, received_at, fault=fault)
        return result

    def _ingest_in_transaction(self, raw, received_at, *, fault=None):
        """Shared core body; the caller owns the single transaction and commit."""
        if not self.db.in_transaction:
            raise ValueError("core ingest requires an owned transaction")
        envelope = {"record": raw, "received_at": received_at}
        raw_text = dumps(envelope)
        receipt_hash = digest(envelope)
        normalized_time = None
        record_id = None
        error = None
        status = "INVALID"
        try:
            normalized_time = timestamp(received_at)
            record, key = normalize(raw, self.config)
            record_id = digest(record)
            variants = self.db.execute("SELECT id FROM records WHERE logical_key=?", (key,)).fetchall()
            status = "ACCEPTED" if not variants else ("DUPLICATE" if {x[0] for x in variants} == {record_id} else "CONFLICT")
            self.db.execute("INSERT OR IGNORE INTO records VALUES (?, ?, ?, ?)", (record_id, key, record["kind"], dumps(record)))
        except (ValueError, TypeError, KeyError) as exc:
            error = str(exc)
        inject(fault, "ingest_before_receipt")
        cursor = self.db.execute("INSERT INTO receipts(receipt_hash,record_id,received_at,raw,error,status) VALUES (?,?,?,?,?,?)",
                                (receipt_hash, record_id, normalized_time, raw_text, error, status))
        result = {"receipt_id": receipt_hash, "record_id": record_id, "status": status, "error": error, "reason_code": error.split(":", 1)[0] if error and ":" in error else None}
        return result, cursor.lastrowid

    def ingest_delivery(self, stream_id, sequence, payload, plan, *, observed_at=None,
                        busy_timeout_ms=250, fault=None):
        from .admission.runtime import ingest_delivery
        return ingest_delivery(self, stream_id, sequence, payload, plan,
                               observed_at=observed_at, busy_timeout_ms=busy_timeout_ms, fault=fault)

    def feed_status(self, stream_id):
        from .admission.runtime import feed_status
        return feed_status(self, stream_id)

    def known(self, knowledge_at):
        rows = self.db.execute("""SELECT p.*, r.logical_key, r.payload FROM receipts p
            LEFT JOIN records r ON p.record_id=r.id
            WHERE p.received_at<=? OR p.received_at IS NULL ORDER BY p.receipt_hash""", (knowledge_at,)).fetchall()
        records, receipts, invalid = {}, {}, []
        for row in rows:
            if row["record_id"]:
                rid = row["record_id"]
                records[rid] = {"id": rid, "key": row["logical_key"], **json.loads(row["payload"])}
                receipts.setdefault(rid, set()).add(row["receipt_hash"])
            else:
                invalid.append({"id": row["receipt_hash"], "error": row["error"], **json.loads(row["raw"])})
        return list(records.values()), receipts, list({r["id"]: r for r in invalid}.values())

    def save_run(self, result, *, fault=None):
        validate_current(self.db)
        rid = digest(result)
        with transaction(self.db):
            self.db.execute("INSERT OR IGNORE INTO runs VALUES (?,?,?,?)", (rid, result["balance_at"], result["knowledge_at"], dumps(result)))
            inject(fault, "save_after_run")
            for ledger in result["ledgers"].values():
                for group in ledger.get("correction_groups", []):
                    self.db.execute("INSERT OR IGNORE INTO correction_groups VALUES (?,?,?,?,?)", (rid, group["id"], group["correction_record_id"], group["target_record_id"], dumps(group)))
                    for ordinal, effect in enumerate(group["effects"]):
                        self.db.execute("INSERT OR IGNORE INTO correction_effects VALUES (?,?,?,?)", (rid, group["id"], ordinal, dumps(effect)))
                        if ordinal == 0:
                            inject(fault, "save_after_reversal")
            for i, finding in enumerate(result["findings"]):
                self.db.execute("INSERT OR IGNORE INTO findings VALUES (?,?,?)", (rid, i, dumps(finding)))
            for key, value in result["evidence"].items():
                self.db.execute("INSERT OR IGNORE INTO evidence VALUES (?,?,?)", (rid, key, dumps(value)))
            inject(fault, "save_before_commit")
        return {"run_id": rid, **result}

    def read_run(self, run_id):
        row = self.db.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("unknown run id")
        return {"run_id": run_id, **json.loads(row[0])}
