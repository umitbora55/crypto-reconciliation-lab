"""Signed whole-file preflight and current-policy decisions at each commit boundary."""
import sqlite3
from ..admission.runtime import _effect, _ingest_delivery_in_transaction, validate_plan
from ..admission.feed import MAX_BYTES
from ..migrations import inject, transaction, validate_current
from ..model import digest
from .crypto import MAX_ENVELOPE, AuthError, canonical, parse_envelope, pae, PAYLOAD_TYPE, require_auth, sha256, strict_json, verify_signature
from .policy import active_policy, activate_policy, enable_protection, observed, protection
from .schema import AUTH_TABLES
from .scope import snapshot_bytes as take_snapshot, statement as validate_statement


def _busy(exc):
    return getattr(exc, "sqlite_errorcode", 0) & 255 in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)


def _preflight(store, data, envelope):
    protected = protection(store.db)
    if protected is None:
        raise AuthError("AUTH_SETUP", "database is not protected")
    snapshot = take_snapshot(data)
    payload, key_id, signature = parse_envelope(envelope)
    key = store.db.execute("SELECT * FROM auth_keys WHERE key_id=?", (key_id,)).fetchone()
    if key is None:
        raise AuthError("AUTH_KEY", "key ID is not in the local historical registry")
    verify_signature(bytes(key["public_key"]), pae(PAYLOAD_TYPE, payload), signature)
    value, caps = validate_statement(strict_json(payload), snapshot, store.config)
    if (value["receiver"] != protected["receiver"] or value["configuration_digest"] != protected["configuration_digest"]
            or value["configuration_digest"] != digest(store.config) or value["source"] != key["source"]):
        raise AuthError("AUTH_BINDING", "verified source, receiver or configuration binding differs")
    active = active_policy(store.db)
    source = next((item for item in active["payload"]["sources"] if item["source"] == value["source"]), None)
    if source is None or not value["stream_id"].startswith(source["namespace"]):
        raise AuthError("AUTH_NAMESPACE", "stream is outside the publisher's immutable namespace")
    return {"snapshot": snapshot, "payload": payload, "envelope": envelope, "key": dict(key),
            "statement": value, "capabilities": caps, "plan_hash": validate_plan(snapshot.plan),
            "statement_hash": sha256(payload),
            "endorsement_id": sha256(canonical({"payload_sha256": sha256(payload), "signature": signature.hex(),
                                                 "fingerprint": key["fingerprint"], "key_id": key_id}))}


def _current(prepared, active):
    value, historical = prepared["statement"], prepared["key"]
    key = next((item for item in active["payload"]["keys"] if item["key_id"] == historical["key_id"]), None)
    source = next((item for item in active["payload"]["sources"] if item["source"] == value["source"]), None)
    authorized = (key is not None and key["status"] == "active" and key["fingerprint"] == historical["fingerprint"]
                  and key["source"] == value["source"] and source is not None
                  and value["stream_id"].startswith(source["namespace"])
                  and all(cap in source["capabilities"] for cap in prepared["capabilities"]))
    return bool(authorized), key["status"] if key else "revoked"


def _original(db, stream_id, sequence):
    return db.execute("""SELECT l.decision_id,d.endorsement_id FROM auth_delivery_links l
        JOIN auth_decisions d ON d.id=l.decision_id WHERE l.stream_id=? AND l.sequence=?""", (stream_id, sequence)).fetchone()


def _endorse(db, prepared):
    key, value = prepared["key"], prepared["statement"]
    db.execute("INSERT OR IGNORE INTO auth_endorsements VALUES (?,?,?,?,?,?,?,?,?)",
               (prepared["endorsement_id"], prepared["payload"], prepared["envelope"], value["source"],
                key["key_id"], key["fingerprint"], prepared["statement_hash"], prepared["snapshot"].input_sha256,
                prepared["plan_hash"]))


def _line(store, prepared, sequence, when, fault):
    db, value = store.db, prepared["statement"]
    stream_id, payload = value["stream_id"], prepared["snapshot"].lines[sequence - 1]
    with transaction(db):
        validate_current(db)
        protected = protection(db)
        if (protected is None or protected["receiver"] != value["receiver"]
                or protected["configuration_digest"] != value["configuration_digest"]):
            raise AuthError("AUTH_BINDING", "protected database binding changed")
        active = active_policy(db)
        authorized, key_status = _current(prepared, active)
        owner = db.execute("SELECT * FROM auth_streams WHERE stream_id=?", (stream_id,)).fetchone()
        if owner is not None and any(owner[field] != value[field] for field in ("source", "receiver", "configuration_digest")):
            raise AuthError("AUTH_OWNERSHIP", "stream belongs to a different publisher binding")
        original, effect = _original(db, stream_id, sequence), _effect(db, stream_id, sequence)
        historical = (not authorized and key_status == "revoked" and original is not None and effect is not None
                      and original["endorsement_id"] == prepared["endorsement_id"]
                      and owner is not None and owner["plan_hash"] == prepared["plan_hash"]
                      and bytes(effect["payload"]) == payload and effect["payload_sha256"] == sha256(payload))
        if not authorized and not historical:
            raise AuthError("AUTH_DENIED", "current policy denies this new effect or historical replay")
        # Even an approved old endorsement cannot clear a permanent Stage 9 block.
        decision = "CURRENT" if authorized else "HISTORICAL_REPLAY"
        _endorse(db, prepared)
        decision_id = db.execute("INSERT INTO auth_decisions(epoch,endorsement_id,stream_id,sequence,decision,current_key_status,policy_hash,observed_at) VALUES (?,?,?,?,?,?,?,?)",
                                 (active["epoch"], prepared["endorsement_id"], stream_id, sequence, decision,
                                  key_status, active["policy_hash"], when)).lastrowid
        response = _ingest_delivery_in_transaction(store, stream_id, sequence, payload, prepared["snapshot"].plan,
                                                    observed_at=when, fault=fault)
        if response["outcome"] == "COMMITTED":
            if owner is None:
                db.execute("INSERT INTO auth_streams VALUES (?,?,?,?,?)", (stream_id, value["source"], value["receiver"],
                                                                         value["configuration_digest"], prepared["plan_hash"]))
            db.execute("INSERT INTO auth_delivery_links VALUES (?,?,?,?)", (stream_id, sequence, decision_id,
                                                                           response["core_receipt_row_id"]))
        db.execute("INSERT INTO auth_attempt_links VALUES (?,?)", (response["attempt_id"], decision_id))
        response["authorization"] = {"decision_id": decision_id, "decision": decision, "epoch": active["epoch"],
                                     "policy_hash": active["policy_hash"], "key_id": prepared["key"]["key_id"],
                                     "key_status": key_status, "currently_authorized": authorized,
                                     "endorsement_id": prepared["endorsement_id"],
                                     "original_decision_id": original["decision_id"] if original is not None else (decision_id if response["outcome"] == "COMMITTED" else None)}
        inject(fault, "auth_before_commit")
    inject(fault, "auth_after_commit")
    return response


def _audit_rejection(db, request_hash, error, when):
    try:
        with transaction(db):
            if db.execute("SELECT COUNT(*) FROM auth_rejections").fetchone()[0] >= 10000:
                return {"code": error.code, "reason": str(error), "audit_id": None, "durable": False}
            audit_id = db.execute("INSERT INTO auth_rejections(request_hash,code,reason,observed_at) VALUES (?,?,?,?)",
                                  (request_hash, error.code, str(error), when)).lastrowid
        return {"code": error.code, "reason": str(error), "audit_id": audit_id, "durable": True}
    except sqlite3.OperationalError as exc:
        if not _busy(exc):
            raise
        return {"code": error.code, "reason": str(error), "audit_id": None, "durable": False}


def ingest_signed(store, snapshot_bytes, envelope_bytes, *, max_lines=None, fault=None,
                  busy_timeout_ms=250, observed_at=None):
    require_auth()  # No audit, stream or core effect if the optional dependency is absent.
    if type(busy_timeout_ms) is not int or not 0 <= busy_timeout_ms <= 5000:
        raise ValueError("AUTH_INPUT: busy timeout must be an integer between 0 and 5000 ms")
    if max_lines is not None and (type(max_lines) is not int or not 1 <= max_lines <= 10000):
        raise ValueError("AUTH_INPUT: max_lines must be a positive bounded integer")
    when = observed(observed_at)
    result = {"format": "source-auth-admission-v1", "status": "DENIED", "source": None, "stream_id": None,
              "statement_hash": None, "snapshot_hash": None, "plan": None, "responses": [],
              "rejection": None, "financial_evaluation": "NOT_RUN"}
    # Oversized rejected requests receive only a bounded audit identity, never a
    # purported full-file plan digest. Accepted inputs are hashed in full.
    def audit_identity(data, limit):
        return {"prefix_sha256": sha256(data[:limit + 1]), "bytes": len(data)} if type(data) is bytes else None
    raw_hash = sha256(canonical({"snapshot": audit_identity(snapshot_bytes, MAX_BYTES),
                                 "envelope": audit_identity(envelope_bytes, MAX_ENVELOPE)}))
    db = store.db
    previous_timeout = db.execute("PRAGMA busy_timeout").fetchone()[0]
    db.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
    try:
        prepared = _preflight(store, snapshot_bytes, envelope_bytes)
        result.update(source=prepared["statement"]["source"], stream_id=prepared["statement"]["stream_id"],
                      statement_hash=prepared["statement_hash"], snapshot_hash=prepared["snapshot"].input_sha256,
                      plan=prepared["snapshot"].plan)
        inject(fault, "auth_after_preflight")
        limit = min(max_lines or len(prepared["snapshot"].lines), len(prepared["snapshot"].lines))
        for sequence in range(1, limit + 1):
            response = _line(store, prepared, sequence, when, fault)
            result["responses"].append(response)
            if not response["ack"]:
                result["status"] = "BLOCKED" if response["blocked"] else "INCOMPLETE"
                break
        else:
            result["status"] = "COMPLETE" if limit == len(prepared["snapshot"].lines) else "INCOMPLETE"
        return result
    except AuthError as exc:
        # Legacy databases do not have an auth audit contract; a denied signed call
        # must also remain read-only there.
        result["rejection"] = (_audit_rejection(db, raw_hash, exc, when) if protection(db) is not None
                               else {"code": exc.code, "reason": str(exc), "audit_id": None, "durable": False})
        result["status"] = "DENIED"
        return result
    except sqlite3.OperationalError as exc:
        if not _busy(exc):
            raise
        result["status"] = "RETRYABLE_BUSY"
        result["rejection"] = {"code": "RETRYABLE_BUSY", "reason": "database is busy; no final commit claim", "audit_id": None, "durable": False}
        return result
    finally:
        db.execute(f"PRAGMA busy_timeout={previous_timeout}")


def auth_status(store):
    db = store.db
    if db.in_transaction:
        raise ValueError("auth status requires an independent read transaction")
    db.execute("BEGIN")
    try:
        protected = protection(db)
        result = {"format": "source-auth-status-v1", "protected": protected, "active_policy": active_policy(db) if protected else None,
                  "tables": {}}
        available = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for name in AUTH_TABLES:
            rows = db.execute('SELECT * FROM "' + name + '" ORDER BY rowid').fetchall() if name in available else []
            result["tables"][name] = [{key: bytes(value).hex() if isinstance(value, bytes) else value for key, value in dict(row).items()} for row in rows]
        db.execute("COMMIT")
        return result
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
