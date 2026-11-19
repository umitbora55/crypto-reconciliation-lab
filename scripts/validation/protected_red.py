#!/usr/bin/env python3
"""Reproduce the pre-boundary C03/C04 defects on owned Linux fixture copies.

The original financial snapshot is opened O_NOATIME; no original database is
opened through SQLite. A RED result means the requested protection is absent,
not a passing acceptance test. Run against the immutable Gate 4 checkout.
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


BASE = "19b19c7cd17bd0b7e6a93964044562c584f7e63a"
RUN = "db050c7ea9ce4aec4f0a99ea47ecd3e32d30b2d10ec209ff31c12e8cc139115b"
SHA = "1a37873cd1ec44a2e498baedb26c71250fb15afa0cc85e65c21cb35cc3669133"


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def save(path, value):
    with path.open("xb") as stream:
        stream.write(encoded(value))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def meta(info):
    return {name: getattr(info, name) for name in (
        "st_dev", "st_ino", "st_mode", "st_nlink", "st_uid", "st_gid",
        "st_size", "st_atime_ns", "st_mtime_ns", "st_ctime_ns")}


def read_noatime(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NOATIME)
    try:
        before = meta(os.fstat(fd))
        chunks = []
        while data := os.read(fd, 1024 * 1024):
            chunks.append(data)
        after = meta(os.fstat(fd))
        if before != after:
            raise RuntimeError("original changed during O_NOATIME read")
        return b"".join(chunks), before
    finally:
        os.close(fd)


def identity(path):
    data, observed = read_noatime(path)
    return {"stat": observed, "sha256": sha(data)}


def selection(path, database):
    save(path, {"format": "review-selection-v1", "sources": [{
        "alias": "custody_difference", "database": str(database),
        "label": "Custody difference", "run_ids": [RUN],
        "run_labels": {RUN: "Initial knowledge"}}]})


def command(argv, output):
    started = time.monotonic()
    result = subprocess.run(argv, capture_output=True, timeout=60)
    (output / "stdout.log").write_bytes(result.stdout)
    (output / "stderr.log").write_bytes(result.stderr)
    record = {"argv": argv, "returncode": result.returncode,
              "seconds": time.monotonic() - started}
    save(output / "command.json", record)
    return result


def mount_probe(folder):
    """Runs only in a new private mount namespace; never mounts on the host."""
    subprocess.run(["mount", "--make-rprivate", "/"], check=True)
    source, view = folder / "source.sqlite3", folder / "view.sqlite3"
    source.chmod(0o666)
    writable = os.open(source, os.O_RDWR | os.O_CLOEXEC)
    view.touch(exist_ok=False)
    subprocess.run(["mount", "--bind", str(source), str(view)], check=True)
    try:
        subprocess.run(["mount", "-o", "remount,bind,ro,noatime", str(view)], check=True)
        mount = subprocess.check_output(["findmnt", "-J", "-T", str(view)]).decode()
        before = identity(source)
        attacker_code = (
            "import json,os,pathlib,sys; p=pathlib.Path('/proc/self/status').read_text();"
            "fd=os.open(sys.argv[1],os.O_RDWR) if sys.argv[2]=='alias' else int(sys.argv[1]);"
            "os.pwrite(fd,sys.argv[3].encode(),68);os.fsync(fd);"
            "print(json.dumps({'uid':os.getuid(),'gid':os.getgid(),"
            "'status':[x for x in p.splitlines() if x.startswith(('Cap','NoNewPrivs'))],"
            "'write_completed':True}))"
        )
        prefix = ["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups",
                  "--bounding-set=-all", "--inh-caps=-all", "--ambient-caps=-all",
                  "--no-new-privs", sys.executable, "-I", "-B", "-c", attacker_code]
        alias = subprocess.run(prefix + [str(source), "alias", "CRL1"],
                               capture_output=True, text=True, timeout=10)
        alias_after = identity(view)
        # Mode/ownership removal does not revoke a previously opened writable FD.
        source.chmod(0o400)
        retained = subprocess.run(prefix + [str(writable), "fd", "CRL2"],
                                  pass_fds=(writable,), capture_output=True,
                                  text=True, timeout=10)
        fd_after = identity(view)
        view_error = None
        try:
            impossible = os.open(view, os.O_WRONLY)
        except OSError as error:
            view_error = {"errno": error.errno, "message": str(error)}
        else:
            os.close(impossible)
        result = {"case": "C03", "mount": json.loads(mount), "before": before,
                  "after_alias": alias_after, "after_retained_fd": fd_after,
                  "alias_process": {"returncode": alias.returncode,
                                    "stdout": alias.stdout, "stderr": alias.stderr},
                  "retained_fd_process": {"returncode": retained.returncode,
                                          "stdout": retained.stdout, "stderr": retained.stderr},
                  "readonly_view_write_error": view_error,
                  "status": "RED_REPRODUCED" if (
                      alias.returncode == retained.returncode == 0 and view_error
                      and before["sha256"] != alias_after["sha256"]
                      and alias_after["sha256"] != fd_after["sha256"]
                  ) else "REPRODUCTION_FAILED",
                  "scope": "Task-owned insecure setup only; no host-root adversary claim."}
        save(folder / "result.json", result)
        return 0 if result["status"] == "RED_REPRODUCED" else 1
    finally:
        os.close(writable)
        subprocess.run(["umount", str(view)], check=True)


def run_export(repo, selected, output, logs):
    bootstrap = (
        "import sys; sys.path.insert(0,sys.argv.pop(1)); "
        "from crypto_reconciliation_lab.review.export import export_selection; "
        "r=export_selection(sys.argv[1],sys.argv[2]); print(r['status'])"
    )
    return command([sys.executable, "-I", "-B", "-c", bootstrap,
                    str(repo), str(selected), str(output)], logs)


def main(args):
    if not sys.platform.startswith("linux") or os.geteuid() != 0:
        raise RuntimeError("Linux trusted-root test runner required; no fallback")
    if args.mount_probe:
        return mount_probe(Path(args.mount_probe))
    repo, fixture, output = Path(args.source_repo), Path(args.fixture), Path(args.output)
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                   text=True).strip()
    if head != BASE:
        raise RuntimeError("RED execution must use the exact accepted Gate4 HEAD")
    if subprocess.check_output(["git", "-C", str(repo), "diff", "HEAD", "--",
                                "crypto_reconciliation_lab"]):
        raise RuntimeError("baseline runtime has local edits")
    original, original_meta = read_noatime(fixture)
    if sha(original) != SHA:
        raise RuntimeError("reference SHA mismatch")
    output.mkdir(mode=0o755)
    save(output / "protocol.json", {
        "format": "protected-snapshot-red-v1", "baseline_commit": head,
        "script_sha256": sha(Path(__file__).read_bytes()),
        "reference_sha256": SHA, "reference_metadata_before": original_meta,
        "source_repo": str(repo), "fixture": str(fixture), "kernel": os.uname().release,
        "python": sys.version, "cases": [
            "C03 ro bind view with different non-root alias writer",
            "C03 previously opened writable FD passed to capability-free non-root",
            "C04 unchanged exporter accepts source symlink",
            "C04 unchanged exporter accepts source hardlink",
            "C04 external fd precheck followed by real process inode replacement",
            "C04 adapter hash-to-copy real process same-bytes inode replacement"],
        "budget": {"runs_per_case": 1, "subprocess_timeout_seconds": 60},
        "meaning": "RED demonstrates a missing protection; never acceptance PASS."})
    c03 = output / "C03"
    c03.mkdir(mode=0o755)
    (c03 / "source.sqlite3").write_bytes(original)
    result = command(["unshare", "--mount", "--fork", sys.executable, "-I", "-B",
                      str(Path(__file__).resolve()), "--mount-probe", str(c03)], c03)
    if result.returncode:
        raise RuntimeError("C03 RED witness failed; original logs retained")
    results = [json.loads((c03 / "result.json").read_text())]
    for variant in ("symlink", "hardlink"):
        case = output / ("C04-" + variant)
        case.mkdir()
        source = case / "source.sqlite3"
        source.write_bytes(original)
        selected = case / "selected.sqlite3"
        if variant == "symlink":
            selected.symlink_to(source)
        else:
            os.link(source, selected)
        selection(case / "selection.json", selected)
        before = meta(selected.lstat())
        outcome = run_export(repo, case / "selection.json", case / "export", case)
        record = {"case": "C04-" + variant, "selected_lstat": before,
                  "returncode": outcome.returncode,
                  "status": "RED_REPRODUCED" if outcome.returncode == 0
                  and b"COMPLETE" in outcome.stdout else "REPRODUCTION_FAILED"}
        save(case / "result.json", record)
        results.append(record)
    sys.path.insert(0, str(repo))
    from crypto_reconciliation_lab.review import adapter
    from crypto_reconciliation_lab.review.export import export_selection
    for variant in ("precheck-race", "hash-copy-race"):
        case = output / ("C04-" + variant)
        case.mkdir()
        source, replacement = case / "source.sqlite3", case / "replacement.sqlite3"
        source.write_bytes(original)
        replacement.write_bytes(original)
        if variant == "precheck-race":
            with sqlite3.connect(replacement) as db:
                db.execute("PRAGMA application_id=12345")
        selection(case / "selection.json", source)
        pinned_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NOATIME)
        pinned_before = meta(os.fstat(pinned_fd))
        before = identity(source)
        read_pipe, write_pipe = os.pipe()
        attacker = subprocess.Popen([
            sys.executable, "-I", "-B", "-c",
            "import os,sys; os.read(int(sys.argv[1]),1); os.replace(sys.argv[2],sys.argv[3])",
            str(read_pipe), str(replacement), str(source)], pass_fds=(read_pipe,),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        os.close(read_pipe)
        original_copy = adapter._copy_snapshot
        def replace_now():
            os.write(write_pipe, b"1")
            attacker_stdout, attacker_stderr = attacker.communicate(timeout=10)
            (case / "attacker.stdout").write_bytes(attacker_stdout)
            (case / "attacker.stderr").write_bytes(attacker_stderr)
            if attacker.returncode:
                raise RuntimeError("race attacker failed")
        def raced_copy(*positional, **keywords):
            replace_now()
            return original_copy(*positional, **keywords)
        try:
            if variant == "precheck-race":
                replace_now()
            else:
                adapter._copy_snapshot = raced_copy
            manifest = export_selection(case / "selection.json", case / "export")
            after = identity(source)
            record = {"case": "C04-" + variant,
                      "before_precheck": before, "actual_consumed_path": after,
                      "pinned_fd_before": pinned_before,
                      "pinned_fd_after": meta(os.fstat(pinned_fd)),
                      "attacker_returncode": attacker.returncode,
                      "export_status": manifest["status"],
                      "export_consumed_sha256": manifest["sources"][0]["before"]["files"]["database"]["sha256"],
                      "instrumentation": "External pinned FD barrier" if variant == "precheck-race"
                      else "Test-only barrier at adapter _copy_snapshot entry; unchanged copy implementation",
                      "status": "RED_REPRODUCED" if manifest["status"] == "COMPLETE"
                      and before["stat"]["st_ino"] != after["stat"]["st_ino"]
                      else "REPRODUCTION_FAILED"}
            save(case / "result.json", record)
            results.append(record)
        finally:
            adapter._copy_snapshot = original_copy
            os.close(pinned_fd)
            os.close(write_pipe)
            if attacker.poll() is None:
                attacker.kill()
                attacker.wait()
    original_after, original_after_meta = read_noatime(fixture)
    final = {"format": "protected-snapshot-red-results-v1", "cases": results,
             "original_unchanged": original_after == original and original_after_meta == original_meta,
             "baseline_commit": BASE, "script_sha256": sha(Path(__file__).read_bytes())}
    final["status"] = "RED_REPRODUCED" if final["original_unchanged"] and all(
        item["status"] == "RED_REPRODUCED" for item in results) else "REPRODUCTION_FAILED"
    save(output / "results.json", final)
    print(json.dumps({"status": final["status"], "output": str(output)}))
    return 0 if final["status"] == "RED_REPRODUCED" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repo")
    parser.add_argument("--fixture")
    parser.add_argument("--output")
    parser.add_argument("--mount-probe", help=argparse.SUPPRESS)
    raise SystemExit(main(parser.parse_args()))
