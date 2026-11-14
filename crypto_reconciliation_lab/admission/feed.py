"""Bounded immutable JSONL snapshots and replay-from-start admission."""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import sqlite3
import stat

MAX_BYTES = 16 * 1024 * 1024
MAX_LINES = 10_000
MAX_LINE_BYTES = 65_536
FRAMING = "utf8-lf-jsonl-v1"


@dataclass(frozen=True)
class FeedSnapshot:
    lines: tuple[bytes, ...]
    input_sha256: str
    input_bytes: int

    @property
    def plan(self):
        return {"format": "admission-plan-v1", "input_sha256": self.input_sha256,
                "input_bytes": self.input_bytes, "planned_lines": len(self.lines), "framing": FRAMING}


def snapshot_feed(path):
    """Read a finite regular file once; never seek over a previously committed prefix."""
    path = Path(path)
    initial = path.lstat()
    if not stat.S_ISREG(initial.st_mode):
        raise ValueError("FEED_INPUT: a regular nonsymlink finite file is required")
    key = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns)
    # O_NONBLOCK also closes the FIFO-replacement race between lstat and open.
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or key(initial) != key(before) or not 0 < before.st_size <= MAX_BYTES:
            raise ValueError("FEED_INPUT: expected a nonempty regular file within 16 MiB")
        data = source.read(MAX_BYTES + 1)
        after = os.fstat(source.fileno())
    if key(before) != key(after) or len(data) != before.st_size or key(after) != key(path.lstat()):
        raise ValueError("FEED_INPUT: file changed while taking its snapshot")
    if not data.endswith(b"\n") or b"\r" in data or data.startswith(b"\xef\xbb\xbf"):
        raise ValueError("FEED_FRAMING: UTF-8 without BOM, LF only, final LF required")
    lines = tuple(part + b"\n" for part in data[:-1].split(b"\n"))
    if not 1 <= len(lines) <= MAX_LINES or any(not line[:-1].strip() or len(line) > MAX_LINE_BYTES for line in lines):
        raise ValueError("FEED_FRAMING: blank/oversized line or too many lines")
    return FeedSnapshot(lines, hashlib.sha256(data).hexdigest(), len(data))


def unknown_status(stream_id, reason):
    return {"format": "feed-status-v1", "stream_id": stream_id, "status": "UNKNOWN",
            "committed_prefix": None, "blocked": None, "planned_lines": None,
            "pending_sequences": None, "effects": [], "attempts": [],
            "core_invalid_count": None, "frame_rejected_count": None,
            "reason": reason, "financial_evaluation": "NOT_RUN"}


def ingest_feed(store, path, stream_id, *, busy_timeout_ms=250):
    snapshot = snapshot_feed(path)
    if type(busy_timeout_ms) is not int or not 0 <= busy_timeout_ms <= 5000:
        raise ValueError("DELIVERY_INPUT: busy timeout must be an integer between 0 and 5000 ms")
    responses = []
    previous = store.db.execute("PRAGMA busy_timeout").fetchone()[0]
    store.db.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
    try:
        for sequence, payload in enumerate(snapshot.lines, 1):
            result = store.ingest_delivery(stream_id, sequence, payload, snapshot.plan,
                                           busy_timeout_ms=busy_timeout_ms)
            responses.append(result)
            if not result["ack"]:
                break
        if responses[-1]["outcome"] == "RETRYABLE_BUSY":
            state = unknown_status(stream_id, "RETRYABLE_BUSY: no committed prefix readback was available")
        else:
            try:
                state = store.feed_status(stream_id)
            except sqlite3.OperationalError as exc:
                if getattr(exc, "sqlite_errorcode", 0) & 255 not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                    raise
                state = unknown_status(stream_id, "RETRYABLE_BUSY: final status readback unavailable")
    finally:
        store.db.execute(f"PRAGMA busy_timeout={previous}")
    complete = (len(responses) == len(snapshot.lines) and all(r["ack"] for r in responses)
                and state["committed_prefix"] == len(snapshot.lines) and not state["blocked"])
    return {"format": "feed-admission-v1", "stream_id": stream_id, "plan": snapshot.plan,
            "status": "COMPLETE" if complete else ("BLOCKED" if state["blocked"] else "INCOMPLETE"),
            "responses": responses, "delivery_status": state,
            "financial_evaluation": "NOT_RUN", "eof_is_financial_completeness": False}
