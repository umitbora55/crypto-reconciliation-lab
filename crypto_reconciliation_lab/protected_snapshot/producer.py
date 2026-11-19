"""Authorized Online Backup, finalized DELETE snapshot and sealed handoff."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time

from . import ProtectionError
from .securefs import (F_ADD_SEALS, F_GET_SEALS, create_sealable_memfd,
                       digest_fd, metadata, no_sidecars, same_path, source_fd)
from ..review.adapter import read_selection, read_selected_sources
from ..review.export import export_selection

MAX_SNAPSHOT = 256 * 1024 * 1024
SEALS = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL if hasattr(fcntl, "F_SEAL_WRITE") else 15


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def write_new(path, data, mode=0o600):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)


def selection_for(database, run_ids, alias, label, run_labels):
    return {"format": "review-selection-v1", "sources": [{"alias": alias,
            "database": str(database), "label": label, "run_ids": list(run_ids),
            "run_labels": run_labels or {}}]}


def table_identity(db):
    # All identifiers come from sqlite_master, and are quoted as identifiers.
    tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    result = {}
    for table in tables:
        quoted = '"' + table.replace('"', '""') + '"'
        rows = []
        for row in db.execute("SELECT * FROM " + quoted):
            rows.append(json.dumps([{"blob": item.hex()} if isinstance(item, bytes) else item
                                    for item in row], ensure_ascii=True, separators=(",", ":"), allow_nan=False))
        rows.sort()
        result[table] = {"rows": len(rows), "sha256": hashlib.sha256(("\n".join(rows) + "\n").encode()).hexdigest()}
    return result


def validate_database(path, selection_path):
    db = sqlite3.connect(Path(path).as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("PRAGMA query_only=ON")
        if db.execute("PRAGMA user_version").fetchone()[0] != 6:
            raise ProtectionError("SCHEMA_UNSUPPORTED: protected v1 requires schema 6")
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)] or db.execute("PRAGMA foreign_key_check").fetchall():
            raise ProtectionError("SNAPSHOT_CORRUPT: SQLite integrity/foreign key check failed")
        tables = table_identity(db)
    finally:
        db.close()
    bundle = read_selected_sources(read_selection(selection_path))
    return {"tables": tables, "selected_runs": [{"run_id": run.run_id,
             "payload_sha256": run.payload_sha256,
             "evidence_ids": sorted(run.evidence_texts)} for run in bundle.runs]}


def sealed_copy(fd):
    if os.fstat(fd).st_size > MAX_SNAPSHOT:
        raise ProtectionError("SNAPSHOT_LIMIT: maximum 256 MiB")
    writable = create_sealable_memfd("crl-protected-snapshot")
    try:
        offset = 0
        while chunk := os.pread(fd, 1024 * 1024, offset):
            if offset + len(chunk) > MAX_SNAPSHOT:
                raise ProtectionError("SNAPSHOT_LIMIT")
            view = memoryview(chunk)
            while view:
                view = view[os.write(writable, view):]
            offset += len(chunk)
        os.fchmod(writable, 0o444)
        fcntl.fcntl(writable, F_ADD_SEALS, SEALS)
        if fcntl.fcntl(writable, F_GET_SEALS) != SEALS:
            raise ProtectionError("SEAL_FAILED")
        readonly = os.open(f"/proc/self/fd/{writable}", os.O_RDONLY | os.O_CLOEXEC | os.O_NOATIME)
        return readonly
    finally:
        # No writable transport descriptor survives the handoff.
        os.close(writable)


@contextmanager
def prepare(source, workspace, *, kind, expected_sha256, producer_uid, run_ids,
            alias="custody_difference", label="Custody difference", run_labels=None):
    if kind not in ("snapshot", "wal"):
        raise ProtectionError("INPUT_KIND_REQUIRED")
    if not run_ids or len(run_ids) > 100 or len(set(run_ids)) != len(run_ids) or any(
            not re.fullmatch(r"[0-9a-f]{64}", run) for run in run_ids):
        raise ProtectionError("RUN_ID_INVALID")
    if kind == "snapshot" and (not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)):
        raise ProtectionError("EXPECTED_SHA256_REQUIRED: imported snapshot identity must be supplied")
    workspace = Path(workspace)
    target = workspace / "snapshot-delete.sqlite3"
    selection_path = workspace / "validation-selection.json"
    timings = {}
    with source_fd(source, producer_uid) as (original, directory, name):
        before = metadata(original)
        identity = digest_fd(original)
        if before["size"] > MAX_SNAPSHOT:
            raise ProtectionError("SNAPSHOT_LIMIT")
        start = time.monotonic()
        if kind == "snapshot":
            no_sidecars(directory, name)
            if identity["sha256"] != expected_sha256:
                raise ProtectionError("SOURCE_HASH_MISMATCH")
            if os.pread(original, 20, 0)[:16] != b"SQLite format 3\x00" or os.pread(original, 2, 18) != b"\x01\x01":
                raise ProtectionError("SNAPSHOT_UNSUPPORTED: closed DELETE header required")
            with target.open("xb") as output:
                offset = 0
                while chunk := os.pread(original, 1024 * 1024, offset):
                    output.write(chunk)
                    offset += len(chunk)
                    if offset > MAX_SNAPSHOT:
                        raise ProtectionError("SNAPSHOT_LIMIT")
                output.flush()
                os.fsync(output.fileno())
            timings["import_copy_seconds"] = time.monotonic() - start
            timings["online_backup_seconds"] = None
            timings["conversion_seconds"] = None
        else:
            # The explicitly trusted producer owns this namespace. It may append
            # transactions, but must not rename/unlink files during Online Backup.
            if os.pread(original, 2, 18) != b"\x02\x02":
                raise ProtectionError("WAL_REQUIRED: producer mode must be explicit")
            same_path(original, directory, name)
            live = sqlite3.connect(Path(source).as_uri() + "?mode=ro", uri=True, timeout=1)
            backup = sqlite3.connect(target)
            try:
                live.execute("PRAGMA trusted_schema=OFF")
                live.execute("PRAGMA query_only=ON")
                deadline = start + 30
                def progress(status, remaining, total):
                    if time.monotonic() > deadline or total * 65536 > MAX_SNAPSHOT * 16:
                        raise ProtectionError("BACKUP_BUDGET_EXCEEDED")
                live.backup(backup, pages=256, progress=progress, sleep=0.01)
                timings["online_backup_seconds"] = time.monotonic() - start
                convert = time.monotonic()
                if backup.execute("PRAGMA journal_mode=DELETE").fetchone()[0].lower() != "delete":
                    raise ProtectionError("DELETE_CONVERSION_FAILED")
                backup.execute("PRAGMA synchronous=FULL")
                backup.commit()
                timings["conversion_seconds"] = time.monotonic() - convert
            finally:
                backup.close()
                live.close()
            same_path(original, directory, name)
        os.chmod(target, 0o600)
        if target.stat().st_size > MAX_SNAPSHOT:
            raise ProtectionError("SNAPSHOT_LIMIT")
        write_new(selection_path, encoded(selection_for(target, run_ids, alias, label, run_labels)))
        start = time.monotonic()
        financial = validate_database(target, selection_path)
        timings["snapshot_validation_seconds"] = time.monotonic() - start
        start = time.monotonic()
        export_selection(selection_path, workspace / "reference-review")
        reference = {name: {"sha256": hashlib.sha256((workspace / "reference-review" / name).read_bytes()).hexdigest(),
                            "bytes": (workspace / "reference-review" / name).stat().st_size}
                     for name in ("index.html", "summary.json", "manifest.json")}
        timings["trusted_reference_review_seconds"] = time.monotonic() - start
        with source_fd(target) as (finalized, _, __):
            if os.pread(finalized, 2, 18) != b"\x01\x01":
                raise ProtectionError("DELETE_HEADER_REQUIRED")
            snapshot_identity = digest_fd(finalized)
            if kind == "snapshot" and snapshot_identity != identity:
                raise ProtectionError("SOURCE_CHANGED: pinned copy identity mismatch")
            snapshot_metadata = metadata(finalized)
            sealed = sealed_copy(finalized)
        try:
            # Writer and finalized-file descriptors are now closed; only RO memfd.
            sealed_identity = digest_fd(sealed)
            sealed_before = metadata(sealed)
            if sealed_identity != snapshot_identity:
                raise ProtectionError("HANDOFF_HASH_MISMATCH")
            same_path(original, directory, name)
            if kind == "snapshot" and (metadata(original) != before or digest_fd(original) != identity):
                raise ProtectionError("SOURCE_CHANGED: import raced")
            proof = {"input_kind": kind, "source": str(source), "source_before": before,
                     "source_bytes_before": identity, "snapshot": snapshot_metadata,
                     "snapshot_bytes": snapshot_identity, "transport": sealed_before,
                     "seals": fcntl.fcntl(sealed, F_GET_SEALS), "financial": financial,
                     "reference_files": reference,
                     "timings": timings, "writer_descriptors_closed_before_handoff": True}
            yield sealed, encoded(selection_for("/input/snapshot.sqlite3", run_ids, alias, label, run_labels)), proof
            same_path(original, directory, name)
            proof["source_after"] = metadata(original)
            proof["source_bytes_after"] = digest_fd(original)
            proof["transport_after"] = metadata(sealed)
            proof["transport_bytes_after"] = digest_fd(sealed)
            if proof["transport_after"] != sealed_before or proof["transport_bytes_after"] != sealed_identity:
                raise ProtectionError("TRANSPORT_CHANGED")
            if kind == "snapshot":
                no_sidecars(directory, name)
                if proof["source_after"] != before or proof["source_bytes_after"] != identity:
                    raise ProtectionError("SOURCE_CHANGED: consumption raced")
        finally:
            os.close(sealed)
