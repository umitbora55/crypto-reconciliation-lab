"""Bounded supplementary resilience probes; never a production security certificate.

Run from the checkout with ``python -m validation_lab.resilience --output NEW``.
Private-validator probes are explicitly component tests, not valid full replays.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import inspect
import json
import os
from pathlib import Path
import platform
import re
import sqlite3
import subprocess
import sys
import tempfile
import time

from crypto_reconciliation_lab.execution import capture
from crypto_reconciliation_lab.replay import api, validation
from crypto_reconciliation_lab.replay.common import ReplayError


def _outcome(function):
    try:
        function()
        return "ACCEPTED"
    except ReplayError as exc:
        return exc.reason_code


EXPECTED_CASE_IDS = (
    [f"read-bytes-{size}" for size in (16777215, 16777216, 16777217)]
    + ["public-api-oversize", "input-symlink", "input-fifo"]
    + [f"json-depth-{depth}" for depth in (1023, 1024, 1025)]
    + ["sqlite-identity-" + repr(number) for number in (2**53+1, 2**63-1, 2**63, True, 0)]
    + [f"receipt-count-{count}" for count in (9999, 10000, 10001)]
    + [f"captured-row-count-{count}" for count in (49999, 50000, 50001)]
    + ["timeout-default", "timeout-invalid-0", "timeout-invalid-61", "timeout-invalid-True"]
    + ["sqlite-quota-full", "quota-rollback-retains-anchor", "quota-integrity", "quota-recovered-write",
       "backup-exact-logical-rows", "backup-integrity", "restore-readable-count", "sqlite-busy", "busy-retry-exact-count"]
)


def acceptance(rows, expected_ids):
    """Refuse empty, duplicated, incomplete or failing evidence inventories."""
    if not rows or not expected_ids or len(set(expected_ids)) != len(expected_ids):
        return False
    if len({row.get("case_id") for row in rows}) != len(rows) or {row.get("case_id") for row in rows} != set(expected_ids):
        return False
    return all(row.get("case_id") and row.get("passed") is True
               and row.get("expected") == row.get("actual") for row in rows)


def boundary_probes(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    rows = []

    def check(name, expected, actual, level="COMPONENT_BOUNDARY", **details):
        rows.append({"case_id": name, "data_class": "FULLY_SYNTHETIC",
                     "level": level, "expected": expected, "actual": actual,
                     "passed": actual == expected, "details": details})

    # Read ceiling: an exact-size regular file is accepted by the bounded reader.
    # Its contents are deliberately NOT described as a valid financial context.
    raw = root / "size-boundary.bin"
    for size in (api.MAX_INPUT_BYTES - 1, api.MAX_INPUT_BYTES, api.MAX_INPUT_BYTES + 1):
        with raw.open("wb") as handle:
            handle.truncate(size)
        expected = "ACCEPTED" if size <= api.MAX_INPUT_BYTES else "REPLAY_LIMIT"
        check(f"read-bytes-{size}", expected, _outcome(lambda: api._read_input(raw)),
              bytes=size, sparse_file=True)
    run = root / "run.json"
    run.write_text("{}")
    report = api.verify_execution_replay(raw, run, "0" * 64)
    check("public-api-oversize", "REPLAY_LIMIT", report["reason_code"],
          level="PUBLIC_API", exit_code=report["exit_code"], report=report)
    raw.unlink()
    regular = root / "regular.json"
    regular.write_text("{}")
    symlink = root / "symlink.json"
    symlink.symlink_to(regular)
    check("input-symlink", "REPLAY_INPUT", _outcome(lambda: api._read_input(symlink)))
    fifo = root / "fifo"
    os.mkfifo(fifo)
    started = time.monotonic()
    check("input-fifo", "REPLAY_INPUT", _outcome(lambda: api._read_input(fifo)),
          elapsed_seconds=time.monotonic() - started)
    # Retain observations, not a FIFO/symlink that an archive reader could follow.
    fifo.unlink()
    symlink.unlink()

    for depth in (1023, 1024, 1025):
        value = "[" * depth + "0" + "]" * depth
        check(f"json-depth-{depth}", "ACCEPTED" if depth <= 1024 else "REPLAY_LIMIT",
              _outcome(lambda: validation._depth_before_parse(value)),
              note="Pre-parser depth guard only; not a valid recorded context")

    for number in (2**53 + 1, 2**63 - 1, 2**63, True, 0):
        check("sqlite-identity-" + repr(number),
              "ACCEPTED" if type(number) is int and 0 < number <= 2**63-1 else "REPLAY_INTEGRITY",
              _outcome(lambda: validation._positive_integer(number, "fixture.id")),
              integer=number)

    def tables():
        return {name: [] for name in capture.COLUMNS}

    for count in (9999, 10000, 10001):
        inventory = tables()
        inventory["receipts"] = [dict(id=i+1, receipt_hash="h", record_id=None,
                                      received_at=None, raw="{}", error=None, status="INVALID")
                                 for i in range(count)]
        check(f"receipt-count-{count}", "ACCEPTED" if count <= 10000 else "REPLAY_LIMIT",
              _outcome(lambda: validation._inventory_types(inventory)),
              note="Typed inventory guard only, not complete identity/financial validation")
    for count in (49999, 50000, 50001):
        inventory = tables()
        inventory["records"] = [dict(id=str(i), logical_key=str(i), kind="fixture", payload="{}")
                               for i in range(count)]
        check(f"captured-row-count-{count}", "ACCEPTED" if count <= 50000 else "REPLAY_LIMIT",
              _outcome(lambda: validation._inventory_types(inventory)),
              note="Typed inventory guard only, not complete identity/financial validation")
    check("timeout-default", 30,
          inspect.signature(api.verify_execution_replay).parameters["timeout_seconds"].default,
          level="CONFIGURATION_INSPECTION", note="The full 30-second expiration is not waited here")
    for timeout in (0, 61, True):
        result = api.verify_execution_replay(regular, run, "0" * 64, timeout_seconds=timeout)
        check("timeout-invalid-" + repr(timeout), "REPLAY_INPUT", result["reason_code"], level="PUBLIC_API")
    return rows


def sqlite_probes(root):
    """Owned SQLite microprobes, not an application-level physical disk-full test."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    rows = []

    def check(name, expected, actual, **details):
        rows.append({"case_id": name, "data_class": "FULLY_SYNTHETIC",
                     "level": "SQLITE_MICROPROBE", "expected": expected, "actual": actual,
                     "passed": actual == expected, "details": details})

    path = root / "quota.sqlite3"
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA page_size=4096")
        db.execute("CREATE TABLE evidence (id INTEGER PRIMARY KEY, payload BLOB NOT NULL)")
        db.execute("INSERT INTO evidence VALUES (?, ?)", (1, b"retained-anchor"))
        db.commit()
        old_pages = db.execute("PRAGMA page_count").fetchone()[0]
        cap = db.execute(f"PRAGMA max_page_count={old_pages + 1}").fetchone()[0]
        code = None
        try:
            db.execute("BEGIN")
            db.execute("INSERT INTO evidence VALUES (?, zeroblob(?))", (2, 65536))
            db.commit()
        except sqlite3.DatabaseError as exc:
            code = exc.sqlite_errorname
            db.rollback()
        check("sqlite-quota-full", "SQLITE_FULL", code, page_size=4096, page_limit=cap,
              note="SQLite page quota simulation; the machine filesystem was not filled")
        values = db.execute("SELECT id, hex(payload) FROM evidence ORDER BY id").fetchall()
        check("quota-rollback-retains-anchor", [[1, b"retained-anchor".hex().upper()]],
              [list(row) for row in values])
        check("quota-integrity", "ok", db.execute("PRAGMA integrity_check").fetchone()[0])
        db.execute("PRAGMA max_page_count=1024")
        db.execute("INSERT INTO evidence VALUES (?, ?)", (2, b"resumed"))
        db.commit()
        check("quota-recovered-write", 2, db.execute("SELECT count(*) FROM evidence").fetchone()[0])
        backup_path = root / "backup.sqlite3"
        backup = sqlite3.connect(backup_path)
        try:
            db.backup(backup)
            check("backup-exact-logical-rows", db.execute("SELECT * FROM evidence ORDER BY id").fetchall(),
                  backup.execute("SELECT * FROM evidence ORDER BY id").fetchall())
            check("backup-integrity", "ok", backup.execute("PRAGMA integrity_check").fetchone()[0])
        finally:
            backup.close()
        # Close original and read a separate restored copy; no overwrite of any user DB.
        restored_path = root / "restored.sqlite3"
        restored_path.write_bytes(backup_path.read_bytes())
        with sqlite3.connect(restored_path) as restored:
            check("restore-readable-count", 2, restored.execute("SELECT count(*) FROM evidence").fetchone()[0])
        contender = sqlite3.connect(path, timeout=0.05)
        try:
            db.execute("BEGIN IMMEDIATE")
            code = None
            started = time.monotonic()
            try:
                contender.execute("INSERT INTO evidence VALUES (?, ?)", (3, b"blocked"))
            except sqlite3.OperationalError as exc:
                code = exc.sqlite_errorname
                contender.rollback()
            check("sqlite-busy", "SQLITE_BUSY", code, wait_seconds=time.monotonic()-started)
            db.rollback()
            contender.execute("INSERT INTO evidence VALUES (?, ?)", (3, b"retry"))
            contender.commit()
            check("busy-retry-exact-count", 3, db.execute("SELECT count(*) FROM evidence").fetchone()[0])
        finally:
            contender.close()
    finally:
        db.close()
    # Bytes are represented only by SHA-256 in the durable JSON, never decoded.
    for row in rows:
        for field in ("expected", "actual"):
            value = row[field]
            if isinstance(value, list) and value and isinstance(value[0], tuple):
                row[field] = [[v if not isinstance(v, bytes) else {"sha256": hashlib.sha256(v).hexdigest()}
                               for v in entry] for entry in value]
    return rows


def source_inventory(repo):
    """Bounded locations-only triage: not proof that all secrets/SQL risks are absent."""
    repo = Path(repo)
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=repo).decode().split("\0")
    signatures = {
        "private-key-header": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "github-token-shaped": re.compile(r"(?:ghp_|github_pat_)[A-Za-z0-9_]{30,}"),
        "aws-access-key-shaped": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "email-shaped": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    }
    candidates, sql = [], []
    inspected = 0
    for name in paths:
        path = repo / name
        if not name or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        inspected += 1
        for line, text in enumerate(content.splitlines(), 1):
            for label, regex in signatures.items():
                if regex.search(text):
                    candidates.append({"path": name, "line": line, "kind": label})
        if name.startswith("crypto_reconciliation_lab/") and name.endswith(".py"):
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("execute", "executemany", "executescript") and node.args:
                    sql.append({"path": name, "line": node.lineno, "operation": node.func.attr,
                                "query_expression": type(node.args[0]).__name__,
                                "bound_parameter_argument_present": len(node.args) > 1})
    return {"status": "TRIAGE_ONLY", "files_inspected": inspected, "candidate_locations": candidates,
            "sql_call_sites": sql, "limitations": ["Only tracked UTF-8 files <=2 MiB inspected",
            "Patterns are not an exhaustive secret/PII detector", "SQL AST shapes are not a source-to-sink audit",
            "No credential values or matching text retained", "Dependency vulnerabilities were not queried"]}


def run(output, repo=None):
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    repo = Path(repo) if repo else Path(__file__).resolve().parents[1]
    preregistered = {"format": "validation-resilience-protocol-v1", "data_class": "FULLY_SYNTHETIC",
                     "run": "one bounded execution", "disk_budget_bytes": 300*1024*1024,
                     "scopes": ["bounded replay component/public API limits", "SQLite owned quota/backup/busy microprobes"],
                     "expected_case_ids": EXPECTED_CASE_IDS,
                     "acceptance": "exact preregistered case ID set, unique results, literal expected outcomes",
                     "not_run": ["physical disk exhaustion", "power loss", "months-long soak", "16,777,216 parsed-node boundary",
                                 "valid end-to-end 10,000 receipt/50,000 captured-row replay", "macOS arm64"]}
    (output / "protocol.json").write_text(json.dumps(preregistered, indent=2) + "\n")
    started = time.monotonic()
    rows = boundary_probes(output / "boundary") + sqlite_probes(output / "sqlite")
    scan = source_inventory(repo)
    (output / "source-triage.json").write_text(json.dumps(scan, indent=2) + "\n")
    sbom = [{"name": d.metadata.get("Name"), "version": d.version}
            for d in importlib.metadata.distributions()]
    (output / "installed-sbom.json").write_text(json.dumps(sorted(sbom, key=lambda r:r["name"].lower()), indent=2) + "\n")
    result = {"format": "validation-resilience-v1", "status": "PASS" if acceptance(rows, EXPECTED_CASE_IDS) else "FAIL",
              "case_count": len(rows), "cases": rows, "elapsed_seconds": time.monotonic()-started,
              "command": sys.argv, "environment": {"python": sys.version, "executable": sys.executable,
              "sqlite": sqlite3.sqlite_version, "platform": platform.platform()},
              "not_run": preregistered["not_run"], "claims": "Finite component/SQLite behavior only; no institutional risk reduction"}
    (output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "case_count": len(rows), "report": str(output / "results.json")}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    raise SystemExit(run(args.output))
