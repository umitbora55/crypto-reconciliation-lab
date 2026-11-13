"""One-transaction delivery dispositions and append-only operational attempts."""
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import sqlite3

from ..migrations import inject, transaction, validate_current
from ..model import dumps, timestamp
from .feed import FRAMING, MAX_BYTES, MAX_LINES, MAX_LINE_BYTES

BLOCKING = ("TRANSPORT_CONFLICT", "PLAN_CONFLICT")


def validate_stream(stream_id):
    if type(stream_id) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", stream_id) is None:
        raise ValueError("DELIVERY_INPUT: invalid stream identifier")


def validate_plan(plan):
    if type(plan) is not dict or set(plan) != {"format", "input_sha256", "input_bytes", "planned_lines", "framing"}:
        raise ValueError("DELIVERY_PLAN: exact admission-plan-v1 fields required")
    if (plan["format"] != "admission-plan-v1" or plan["framing"] != FRAMING
            or type(plan["input_sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", plan["input_sha256"]) is None
            or type(plan["input_bytes"]) is not int or not 0 < plan["input_bytes"] <= MAX_BYTES
            or type(plan["planned_lines"]) is not int or not 0 < plan["planned_lines"] <= MAX_LINES):
        raise ValueError("DELIVERY_PLAN: invalid immutable snapshot identity or limits")
    return hashlib.sha256(dumps(plan).encode("utf-8")).hexdigest()


def _envelope(payload):
    if not payload.endswith(b"\n") or payload.count(b"\n") != 1 or b"\r" in payload or payload.startswith(b"\xef\xbb\xbf"):
        raise ValueError("exactly one LF-terminated UTF-8 JSON line without BOM/CR is required")
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key: " + key)
            value[key] = item
        return value
    def nonfinite(value):
        raise ValueError("non-finite JSON constant: " + value)
    def finite_number(value):
        # Parsing only: a numeric financial amount is still rejected by the core.
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("non-finite JSON numeric exponent")
        return number
    value = json.loads(payload.decode("utf-8"), object_pairs_hook=unique,
                       parse_constant=nonfinite, parse_float=finite_number)
    if type(value) is not dict or set(value) != {"record", "received_at"}:
        raise ValueError("envelope requires only record and received_at")
    return value


def _prefix(db, stream_id):
    sequences = [r[0] for r in db.execute("SELECT sequence FROM delivery_effects WHERE stream_id=? ORDER BY sequence", (stream_id,))]
    if sequences != list(range(1, len(sequences) + 1)):
        raise ValueError("DELIVERY_STATE: committed effects are not a contiguous prefix")
    return len(sequences)


def _blocked(db, stream_id):
    return db.execute("SELECT 1 FROM delivery_attempts WHERE stream_id=? AND outcome IN (?,?) LIMIT 1",
                      (stream_id, *BLOCKING)).fetchone() is not None


def _effect(db, stream_id, sequence):
    return db.execute("SELECT * FROM delivery_effects WHERE stream_id=? AND sequence=?", (stream_id, sequence)).fetchone()


def _attempt(db, stream_id, sequence, payload, payload_hash, plan_hash, outcome, effect, observed, reason):
    return db.execute("""INSERT INTO delivery_attempts
        (stream_id,sequence,payload,payload_sha256,plan_hash,outcome,effect_stream_id,effect_sequence,observed_at,reason)
        VALUES (?,?,?,?,?,?,?,?,?,?)""", (stream_id, sequence, payload, payload_hash, plan_hash, outcome,
        stream_id if effect is not None else None, sequence if effect is not None else None, observed, reason)).lastrowid


def _response(db, stream_id, sequence, outcome, attempt_id, effect, reason):
    return {"format": "delivery-response-v1", "stream_id": stream_id, "sequence": sequence,
            "outcome": outcome, "ack": outcome in ("COMMITTED", "REPLAY"), "durable": True,
            "attempt_id": attempt_id, "committed_prefix": _prefix(db, stream_id),
            "blocked": _blocked(db, stream_id), "reason": reason,
            "disposition": effect["disposition"] if effect is not None else None,
            "core_receipt_row_id": effect["core_receipt_id"] if effect is not None else None,
            "core_result": json.loads(effect["core_result"]) if effect is not None and effect["core_result"] is not None else None}


def ingest_delivery(store, stream_id, sequence, payload, plan, *, observed_at=None, busy_timeout_ms=250, fault=None):
    validate_stream(stream_id)
    plan_hash = validate_plan(plan)
    if type(sequence) is not int or not 1 <= sequence <= MAX_LINES:
        raise ValueError("DELIVERY_INPUT: positive bounded integer sequence required")
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_LINE_BYTES:
        raise ValueError("DELIVERY_INPUT: nonempty bounded exact bytes required")
    if type(busy_timeout_ms) is not int or not 0 <= busy_timeout_ms <= 5000:
        raise ValueError("DELIVERY_INPUT: busy timeout must be an integer between 0 and 5000 ms")
    observed = timestamp(observed_at if observed_at is not None else datetime.now(timezone.utc).isoformat())
    payload_hash = hashlib.sha256(payload).hexdigest()
    db = store.db
    previous_timeout = db.execute("PRAGMA busy_timeout").fetchone()[0]
    db.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
    try:
        with transaction(db):
            validate_current(db)
            stream = db.execute("SELECT * FROM admission_streams WHERE stream_id=?", (stream_id,)).fetchone()
            effect = _effect(db, stream_id, sequence)
            prefix = _prefix(db, stream_id)
            reason = None
            if _blocked(db, stream_id):
                outcome, reason = "BLOCKED", "stream has a permanent transport/plan conflict"
            elif stream is not None and (stream["plan_hash"] != plan_hash or
                    any(stream[k] != plan[k] for k in ("input_sha256", "input_bytes", "planned_lines", "framing"))):
                outcome, reason = "PLAN_CONFLICT", "snapshot differs from the stream's first immutable plan"
            elif effect is not None:
                if bytes(effect["payload"]) == payload and effect["payload_sha256"] == payload_hash:
                    outcome = "REPLAY"
                else:
                    outcome, reason = "TRANSPORT_CONFLICT", "same delivery identity has different exact bytes"
            elif sequence > plan["planned_lines"]:
                outcome, reason = "OUT_OF_RANGE", "sequence exceeds the immutable planned scope"
            elif sequence != prefix + 1:
                outcome, reason = "GAP", "expected sequence " + str(prefix + 1)
            else:
                if stream is None:
                    db.execute("""INSERT INTO admission_streams
                        (stream_id,input_sha256,input_bytes,planned_lines,framing,plan_hash,observed_at)
                        VALUES (?,?,?,?,?,?,?)""", (stream_id, plan["input_sha256"], plan["input_bytes"],
                        plan["planned_lines"], plan["framing"], plan_hash, observed))
                core, row_id, receipt_hash = None, None, None
                try:
                    envelope = _envelope(payload)
                except (ValueError, UnicodeError, RecursionError) as exc:
                    disposition, reason = "REJECTED_FRAME", str(exc)
                else:
                    core, row_id = store._ingest_in_transaction(envelope["record"], envelope["received_at"], fault=fault)
                    receipt_hash, disposition = core["receipt_id"], core["status"]
                    inject(fault, "delivery_after_receipt")
                db.execute("""INSERT INTO delivery_effects
                    (stream_id,sequence,payload,payload_sha256,core_receipt_id,core_receipt_hash,core_result,disposition,reason,observed_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""", (stream_id, sequence, payload, payload_hash, row_id,
                    receipt_hash, dumps(core) if core is not None else None, disposition, reason, observed))
                effect = _effect(db, stream_id, sequence)
                outcome = "COMMITTED"
            attempt_id = _attempt(db, stream_id, sequence, payload, payload_hash, plan_hash, outcome, effect, observed, reason)
            result = _response(db, stream_id, sequence, outcome, attempt_id, effect, reason)
            inject(fault, "delivery_before_commit")
        inject(fault, "delivery_after_commit")
        return result
    except sqlite3.OperationalError as exc:
        code = getattr(exc, "sqlite_errorcode", 0)
        if code & 255 not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise
        return {"format": "delivery-response-v1", "stream_id": stream_id, "sequence": sequence,
                "outcome": "RETRYABLE_BUSY", "ack": False, "durable": False, "attempt_id": None,
                "committed_prefix": None, "blocked": None, "disposition": None,
                "core_receipt_row_id": None, "core_result": None, "reason": str(exc)}
    finally:
        db.execute(f"PRAGMA busy_timeout={previous_timeout}")


def feed_status(store, stream_id):
    validate_stream(stream_id)
    db = store.db
    validate_current(db)
    # A read transaction keeps all history/counts on one SQLite snapshot.
    if db.in_transaction:
        raise ValueError("feed status requires an independent read transaction")
    db.execute("BEGIN")
    try:
        stream = db.execute("SELECT * FROM admission_streams WHERE stream_id=?", (stream_id,)).fetchone()
        prefix, blocked = _prefix(db, stream_id), _blocked(db, stream_id)
        effects = []
        for row in db.execute("SELECT * FROM delivery_effects WHERE stream_id=? ORDER BY sequence", (stream_id,)):
            effect = dict(row); effect["payload_hex"] = bytes(effect.pop("payload")).hex()
            effect["core_result"] = json.loads(effect["core_result"]) if effect["core_result"] is not None else None
            effects.append(effect)
        attempts = []
        for row in db.execute("SELECT * FROM delivery_attempts WHERE stream_id=? ORDER BY id", (stream_id,)):
            attempt = dict(row); attempt["payload_hex"] = bytes(attempt.pop("payload")).hex(); attempts.append(attempt)
        planned = stream["planned_lines"] if stream is not None else None
        result = {"format": "feed-status-v1", "stream_id": stream_id,
            "status": "BLOCKED" if blocked else ("UNSEEN" if stream is None else ("COMPLETE" if prefix == planned else "OPEN")),
            "plan": dict(stream) if stream is not None else None, "planned_lines": planned,
            "committed_prefix": prefix, "pending_sequences": list(range(prefix + 1, planned + 1)) if planned is not None else None,
            "blocked": blocked, "replay_count": sum(a["outcome"] == "REPLAY" for a in attempts),
            "gap_count": sum(a["outcome"] == "GAP" for a in attempts),
            "conflict_count": sum(a["outcome"] in BLOCKING for a in attempts),
            "core_invalid_count": sum(e["disposition"] == "INVALID" for e in effects),
            "frame_rejected_count": sum(e["disposition"] == "REJECTED_FRAME" for e in effects),
            "effects": effects, "attempts": attempts, "financial_evaluation": "NOT_RUN"}
        db.execute("COMMIT")
        return result
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
