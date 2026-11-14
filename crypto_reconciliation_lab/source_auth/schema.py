"""Additive schema-5 authority audit; no optional crypto import."""

AUTH_TABLES = {
    "auth_configuration": """CREATE TABLE auth_configuration (
        id INTEGER PRIMARY KEY CHECK(id=1), receiver TEXT NOT NULL,
        configuration_digest TEXT NOT NULL, initial_policy_hash TEXT NOT NULL)""",
    "auth_policy_snapshots": """CREATE TABLE auth_policy_snapshots (
        policy_hash TEXT PRIMARY KEY, payload TEXT NOT NULL)""",
    "auth_policy_activations": """CREATE TABLE auth_policy_activations (
        epoch INTEGER PRIMARY KEY CHECK(epoch>0),
        policy_hash TEXT NOT NULL REFERENCES auth_policy_snapshots(policy_hash),
        previous_epoch INTEGER, previous_hash TEXT, observed_at TEXT NOT NULL)""",
    "auth_keys": """CREATE TABLE auth_keys (
        key_id TEXT PRIMARY KEY, source TEXT NOT NULL, public_key BLOB NOT NULL,
        fingerprint TEXT NOT NULL UNIQUE,
        first_epoch INTEGER NOT NULL REFERENCES auth_policy_activations(epoch))""",
    "auth_streams": """CREATE TABLE auth_streams (
        stream_id TEXT PRIMARY KEY REFERENCES admission_streams(stream_id),
        source TEXT NOT NULL, receiver TEXT NOT NULL,
        configuration_digest TEXT NOT NULL, plan_hash TEXT NOT NULL)""",
    "auth_endorsements": """CREATE TABLE auth_endorsements (
        id TEXT PRIMARY KEY, payload BLOB NOT NULL, envelope BLOB NOT NULL,
        source TEXT NOT NULL, key_id TEXT NOT NULL REFERENCES auth_keys(key_id),
        fingerprint TEXT NOT NULL, statement_hash TEXT NOT NULL,
        snapshot_hash TEXT NOT NULL, plan_hash TEXT NOT NULL)""",
    "auth_decisions": """CREATE TABLE auth_decisions (
        id INTEGER PRIMARY KEY, epoch INTEGER NOT NULL REFERENCES auth_policy_activations(epoch),
        endorsement_id TEXT NOT NULL REFERENCES auth_endorsements(id),
        stream_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK(sequence>0),
        decision TEXT NOT NULL, current_key_status TEXT NOT NULL,
        policy_hash TEXT NOT NULL REFERENCES auth_policy_snapshots(policy_hash), observed_at TEXT NOT NULL)""",
    "auth_delivery_links": """CREATE TABLE auth_delivery_links (
        stream_id TEXT NOT NULL, sequence INTEGER NOT NULL,
        decision_id INTEGER NOT NULL UNIQUE REFERENCES auth_decisions(id),
        core_receipt_id INTEGER REFERENCES receipts(id), PRIMARY KEY(stream_id,sequence),
        FOREIGN KEY(stream_id,sequence) REFERENCES delivery_effects(stream_id,sequence))""",
    "auth_attempt_links": """CREATE TABLE auth_attempt_links (
        attempt_id INTEGER PRIMARY KEY REFERENCES delivery_attempts(id),
        decision_id INTEGER NOT NULL REFERENCES auth_decisions(id))""",
    "auth_rejections": """CREATE TABLE auth_rejections (
        id INTEGER PRIMARY KEY, request_hash TEXT NOT NULL, code TEXT NOT NULL,
        reason TEXT NOT NULL, observed_at TEXT NOT NULL)""",
}

AUTH_TRIGGERS = {}
for _table in AUTH_TABLES:
    for _action in ("UPDATE", "DELETE"):
        _name = f"immutable_{_table}_{_action}"
        AUTH_TRIGGERS[_name] = (f"CREATE TRIGGER {_name} BEFORE {_action} ON {_table} "
                                "BEGIN SELECT RAISE(ABORT, 'append-only table'); END")


def reject_unsigned(db):
    """Check under the caller's write transaction, including before stream binding."""
    if not db.in_transaction:
        raise ValueError("unsigned guard requires an owned transaction")
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='auth_configuration'").fetchone()
    if exists and db.execute("SELECT 1 FROM auth_configuration").fetchone():
        raise ValueError("SOURCE_AUTH_REQUIRED: protected database refuses unsigned admission")


def validate_auth_schema(db):
    for kind, definitions in (("table", AUTH_TABLES), ("trigger", AUTH_TRIGGERS)):
        for name, expected in definitions.items():
            row = db.execute("SELECT type,sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
            if row is None or row[0] != kind or row[1] is None or " ".join(row[1].split()) != " ".join(expected.split()):
                raise ValueError("SCHEMA_INVALID: authority schema object differs: " + name)
