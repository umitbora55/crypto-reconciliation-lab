#!/usr/bin/env python3
"""Independent read-only financial witness and historical regression audit.

This reader never imports the protected snapshot implementation. It reads old
evidence with O_NOATIME and runs SQLite only on separately owned copies. A raw
WAL copy here is an inspection fixture, never a supported producer handoff.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import time

EXPECTED_SNAPSHOT = "1a37873cd1ec44a2e498baedb26c71250fb15afa0cc85e65c21cb35cc3669133"
EXPECTED_RUN = "db050c7ea9ce4aec4f0a99ea47ecd3e32d30b2d10ec209ff31c12e8cc139115b"
EXPECTED_COUNTS = {"receipts": 30, "runs": 1, "findings": 6, "evidence": 60}
STAT_FIELDS = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_uid", "st_gid",
               "st_size", "st_atime_ns", "st_mtime_ns", "st_ctime_ns")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def write_new(path, value):
    with Path(path).open("xb") as stream:
        stream.write(encoded(value))


def metadata(fd):
    info = os.fstat(fd)
    return {**{name: getattr(info, name) for name in STAT_FIELDS},
            "xattrs": {name: os.getxattr(fd, name).hex()
                       for name in sorted(os.listxattr(fd))}}


def read_noatime(path):
    require(sys.platform == "linux" and hasattr(os, "O_NOATIME"),
            "Linux O_NOATIME is required; no metadata-changing fallback")
    fd = os.open(path, os.O_RDONLY | os.O_NOATIME | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = metadata(fd)
        require(stat.S_ISREG(before["st_mode"]), "regular file required")
        chunks = []
        while chunk := os.read(fd, 1024 * 1024):
            chunks.append(chunk)
        after = metadata(fd)
        require(before == after, "source changed while inspecting")
        data = b"".join(chunks)
        require(len(data) == before["st_size"], "source read length changed")
        return data, {"metadata": before, "bytes": len(data), "sha256": sha(data)}
    finally:
        os.close(fd)


def table_payloads(connection):
    result = {}
    for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        quoted = '"' + name.replace('"', '""') + '"'
        columns = [row[1] for row in connection.execute("PRAGMA table_info(" + quoted + ")")]
        rows = connection.execute("SELECT * FROM " + quoted).fetchall()
        row_bytes = sorted(json.dumps(row, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False, default=lambda value: {"bytes_hex": value.hex()})
                           for row in rows)
        raw = json.dumps(row_bytes, separators=(",", ":")).encode()
        result[name] = {"columns": columns, "rows": len(rows), "rows_sha256": sha(raw)}
    return result


def database_witness(path, *, immutable):
    suffix = "&immutable=1" if immutable else ""
    with sqlite3.connect(path.as_uri() + "?mode=ro" + suffix, uri=True) as connection:
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        schema = connection.execute("PRAGMA user_version").fetchone()[0]
        counts = {name: connection.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
                  for name in EXPECTED_COUNTS}
        runs = [row[0] for row in connection.execute("SELECT id FROM runs ORDER BY id")]
        tables = table_payloads(connection)
    require(integrity == ["ok"] and not foreign_keys, "database integrity failed")
    require(schema == 6 and counts == EXPECTED_COUNTS and runs == [EXPECTED_RUN],
            "fixed custody_difference financial identity differs")
    return {"schema": schema, "counts": counts, "run_ids": runs, "integrity": integrity,
            "foreign_key_check": foreign_keys, "tables": tables}


def audit_financial(args):
    output = args.output.absolute()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    record = {"format": "protected-independent-financial-v1", "status": "ERROR",
              "invocation": sys.argv, "reader_sha256": sha(Path(__file__).read_bytes()),
              "python": sys.version, "sqlite": sqlite3.sqlite_version,
              "started_unix_ns": time.time_ns(),
              "scope": "fixed synthetic custody_difference; hashes do not authenticate external truth"}
    try:
        before, originals = {}, {}
        copies = output / "inspection-copies"
        copies.mkdir(mode=0o700)
        snapshot, row = read_noatime(args.snapshot)
        require(row["sha256"] == EXPECTED_SNAPSHOT, "reference snapshot digest differs")
        require(snapshot[18:20] == bytes((1, 1)), "reference snapshot is not DELETE")
        originals["snapshot"] = args.snapshot
        before["snapshot"] = row
        (copies / "snapshot.sqlite3").write_bytes(snapshot)
        for suffix in ("", "-wal", "-shm"):
            source = Path(str(args.wal) + suffix)
            data, row = read_noatime(source)
            name = "source" + suffix
            originals[name] = source
            before[name] = row
            (copies / ("source.sqlite3" + suffix)).write_bytes(data)
        require((copies / "source.sqlite3").read_bytes()[18:20] == bytes((2, 2)),
                "source fixture does not have WAL header")
        source = database_witness(copies / "source.sqlite3", immutable=False)
        snapshot_witness = database_witness(copies / "snapshot.sqlite3", immutable=True)
        after = {name: read_noatime(path)[1] for name, path in originals.items()}
        record.update(originals={name: str(path) for name, path in originals.items()},
                      before=before, after=after, source=source, snapshot=snapshot_witness,
                      metadata_and_hashes_preserved=before == after,
                      full_sql_table_payloads_equal=source == snapshot_witness)
        require(before == after, "original metadata or content changed during witness")
        require(source == snapshot_witness, "source/snapshot SQL payload differs")
        record["status"] = "PASS"
    except Exception as error:
        record["error"] = f"{type(error).__name__}: {error}"
    write_new(output / "result.json", record)
    print(json.dumps({"status": record["status"], "result": str(output / "result.json")}))
    return 0 if record["status"] == "PASS" else 1


def audit_release(args):
    """Read every required report and exact roster; do not substitute old passes."""
    repo = args.repo.absolute()
    sys.path.insert(0, str(repo / "scripts"))
    import release_test_scope
    scope = release_test_scope.load_test_scope(repo)
    release_test_scope.validate_test_files(repo, scope)
    expected = set(scope["current"]["test_ids"])
    require(len(expected) == 875, "historical roster differs")
    reference_path = repo / "docs/stage6/financial-reference.json"
    require(sha(reference_path.read_bytes()) == "4abda380a19acd4cdfed97a46b6fb15528f32b8ef308c6931815c5b03641275e",
            "financial reference identity differs")
    reference = json.loads(reference_path.read_bytes())
    results = []
    for path in args.reports:
        raw = path.read_bytes()
        record = json.loads(raw)
        require(record.get("status") == "PASS" and record.get("exit_code") == 0,
                "release verification did not pass: " + str(path))
        require(record.get("profile") == "full", "full release profile required")
        for mode in ("source", "installed"):
            tests = record[mode + "_tests"]
            require(all(set(tests[key]) == expected and len(tests[key]) == 875
                        for key in ("expected_ids", "discovered_ids", "executed_ids")),
                    "test identity coverage differs")
            require(tests.get("executed") == 875 and tests.get("status") == "PASS"
                    and all(tests.get(key) == 0 for key in ("skips", "failures", "errors",
                                                          "expected_failures", "unexpected_successes")),
                    "historical suite contains incomplete or unsuccessful results")
            require(tests["isolated"] is (mode == "installed"), "source/installed distinction lost")
        financial = record["financial_matrix"]
        require(financial.get("status") == "PASS" and financial.get("cases") == 69
                and financial.get("evaluations") == 162, "financial matrix missing")
        comparisons = [("matrix", path.parent / "financial-matrix", financial["reports"])]
        for mode in ("source", "installed"):
            for stage in ("stage1", "stage2"):
                comparisons.append((stage, path.parent / (mode + "-reproduction") / "review/sources" / stage,
                                    record[mode + "_reproduction"]["financial_reports"][stage]))
        for group, directory, comparison in comparisons:
            wanted = reference["reports"][group]["files"]
            require(comparison.get("status") == "PASS" and comparison.get("files") == wanted
                    and comparison.get("compared_count") == len(wanted), "financial comparison scope differs")
            for name, expected_file in wanted.items():
                data = (directory / name).read_bytes()
                require(expected_file == {"bytes": len(data), "sha256": sha(data)},
                        "actual financial artifact differs: " + str(directory / name))
        for command in record["commands"]:
            require(command.get("status") == "PASS" and command.get("exit_code") == command.get("expected_exit"),
                    "failed or unfinished command")
            for channel in ("stdout", "stderr"):
                data = (path.parent / command[channel]).read_bytes()
                require(command[channel + "_hash"] == {"bytes": len(data), "sha256": sha(data)},
                        "command log binding differs")
        results.append({"path": str(path), "sha256": sha(raw),
                        "python": record["installed_import"]["python"],
                        "source_origin": record["source_import"]["origin"],
                        "installed_origin": record["installed_import"]["origin"],
                        "test_ids": 875, "financial_cases": 69, "financial_evaluations": 162})
    require(len(results) == 2 and {row["python"].split()[0].rsplit(".", 1)[0] for row in results}
            == {"3.12", "3.14"}, "both Python versions required exactly once")
    result = {"format": "protected-independent-regression-v1", "status": "PASS",
              "reader_sha256": sha(Path(__file__).read_bytes()), "reports": results}
    write_new(args.output, result)
    print(json.dumps(result))
    return 0


def source_matrix(args):
    """Complement the release gate's installed matrix with the source path."""
    repo = args.repo.absolute()
    output = args.output.absolute()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    sys.path.insert(0, str(repo / "scripts"))
    import release_financial_scope
    reference = release_financial_scope.load_financial_reference(repo / release_financial_scope.REFERENCE_PATH)
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    record = {"format": "protected-source-matrix-v1", "status": "ERROR", "commands": [],
              "reader_sha256": sha(Path(__file__).read_bytes()), "source": str(repo)}
    try:
        for name, tail in (
            ("origin", ["-c", "import crypto_reconciliation_lab,sys,json; print(json.dumps(dict(origin=crypto_reconciliation_lab.__file__,python=sys.version)))"]),
            ("generate", ["-m", "crypto_reconciliation_lab", "lab-generate", "--output", str(output / "inputs"),
                          "--seed", "11", "--seed", "29", "--seed", "47", "--events", "100", "--investors", "6"]),
            ("verify", ["-m", "crypto_reconciliation_lab", "lab-verify", "--input", str(output / "inputs"),
                        "--output", str(output / "reports")]),
        ):
            argv = [str(args.python), "-B", *tail]
            started = time.monotonic()
            result = subprocess.run(argv, cwd=repo, env=environment, capture_output=True, timeout=180)
            (output / (name + ".stdout")).write_bytes(result.stdout)
            (output / (name + ".stderr")).write_bytes(result.stderr)
            record["commands"].append({"argv": argv, "cwd": str(repo), "returncode": result.returncode,
                                       "seconds": time.monotonic() - started,
                                       "stdout_sha256": sha(result.stdout), "stderr_sha256": sha(result.stderr)})
            require(result.returncode == 0, name + " command failed")
            value = json.loads(result.stdout)
            record[name] = value
            if name == "origin":
                require(Path(value["origin"]) == repo / "crypto_reconciliation_lab/__init__.py", "source import differs")
            elif name == "generate":
                require(value.get("cases") == 69, "source matrix count differs")
            else:
                release_financial_scope.validate_matrix_result(value)
        record["comparison"] = release_financial_scope.compare_required_reports(output / "reports", reference, "matrix")
        record["status"] = "PASS"
    except Exception as error:
        record["error"] = f"{type(error).__name__}: {error}"
    write_new(output / "result.json", record)
    print(json.dumps({"status": record["status"], "result": str(output / "result.json")}))
    return 0 if record["status"] == "PASS" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    audit = sub.add_parser("financial")
    audit.add_argument("--snapshot", type=Path, required=True)
    audit.add_argument("--wal", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)
    release = sub.add_parser("release")
    release.add_argument("--repo", type=Path, required=True)
    release.add_argument("--reports", type=Path, nargs="+", required=True)
    release.add_argument("--output", type=Path, required=True)
    matrix = sub.add_parser("source-matrix")
    matrix.add_argument("--repo", type=Path, required=True)
    matrix.add_argument("--python", type=Path, required=True)
    matrix.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return {"financial": audit_financial, "release": audit_release,
            "source-matrix": source_matrix}[args.action](args)


if __name__ == "__main__":
    raise SystemExit(main())
