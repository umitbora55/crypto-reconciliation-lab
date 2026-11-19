"""Real supervisor SIGKILL with a live consumer and detached grandchild.

Run as root in the local Linux VM. The observer is separate from the supervisor
being killed, and owns/reaps the process tree through PR_SET_CHILD_SUBREAPER.
"""
from __future__ import annotations

import argparse
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time


CONSUMER = '''import json, os, signal, time
from pathlib import Path
child = os.fork()
if child == 0:
    os.setsid()
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    Path('/output/detached-ready').write_text(str(os.getpid()))
    while True:
        time.sleep(1)
while not Path('/output/detached-ready').exists():
    time.sleep(0.01)
Path('/output/ready').write_text(json.dumps({'consumer': os.getpid(), 'detached': child}))
while True:
    time.sleep(1)
'''


def process_record(pid):
    try:
        text = Path(f"/proc/{pid}/status").read_text()
        fields = dict(line.split(":", 1) for line in text.splitlines())
        return {"pid": pid, "ppid": int(fields["PPid"]), "state": fields["State"].strip(),
                "nspid": fields["NSpid"].split(), "uid": fields["Uid"].split(),
                "cmdline": Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")}
    except (FileNotFoundError, ProcessLookupError):
        return None


def children(pid):
    try:
        direct = [int(value) for value in Path(f"/proc/{pid}/task/{pid}/children").read_text().split()]
    except FileNotFoundError:
        return []
    return [*direct, *(descendant for child in direct for descendant in children(child))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "linux" or os.geteuid() != 0:
        raise SystemExit("Linux root observer required")
    args.output.mkdir(mode=0o700)
    workspace = args.output / "supervisor-work"
    workspace.mkdir(mode=0o700)
    previous = args.output / "previous-completed-proof.txt"
    previous.write_bytes(b"Previously completed evidence must survive.\n")
    previous_hash = hashlib.sha256(previous.read_bytes()).hexdigest()
    script = args.output / "detached-consumer.py"
    script.write_text(CONSUMER)
    sys.path.insert(0, str(args.repo))
    sys.dont_write_bytecode = True
    from crypto_reconciliation_lab.protected_snapshot.sandbox import run_isolated
    from crypto_reconciliation_lab.protected_snapshot.securefs import create_sealable_memfd, F_ADD_SEALS
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0):  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), "cannot become subtree reaper")
    snapshot_fd = create_sealable_memfd("crl-sigkill-anchor")
    source = os.open(args.snapshot, os.O_RDONLY | os.O_NOATIME | os.O_CLOEXEC)
    while block := os.read(source, 65536):
        os.write(snapshot_fd, block)
    os.close(source)
    os.fchmod(snapshot_fd, 0o444)
    fcntl.fcntl(snapshot_fd, F_ADD_SEALS, 15)
    read_fd = os.open(f"/proc/self/fd/{snapshot_fd}", os.O_RDONLY | os.O_NOATIME | os.O_CLOEXEC)
    os.close(snapshot_fd)
    selection = json.loads(args.selection.read_text())
    selection["sources"][0]["database"] = "/input/snapshot.sqlite3"
    supervisor = os.fork()
    if supervisor == 0:
        try:
            result = run_isolated(read_fd, json.dumps(selection).encode(), workspace, args.repo,
                                  consumer_script=script, timeout=60)
            (args.output / "unexpected-supervisor-return.json").write_text(json.dumps(result, indent=2))
            os._exit(80)
        except BaseException:
            import traceback
            (args.output / "supervisor-failure.txt").write_text(traceback.format_exc())
            os._exit(81)
    os.close(read_fd)
    ready = workspace / "output" / "ready"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not ready.exists():
        observed = process_record(supervisor)
        if observed is None or observed["state"].startswith("Z"):
            break
        time.sleep(0.02)
    before_pids = [supervisor, *children(supervisor)]
    record = {"format": "protected-snapshot-supervisor-kill-v1", "supervisor_pid": supervisor,
              "ready": json.loads(ready.read_text()) if ready.exists() else None,
              "processes_before": [process_record(pid) for pid in before_pids],
              "sources": {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (args.repo / "crypto_reconciliation_lab/protected_snapshot/sandbox.py",
                                       args.repo / "crypto_reconciliation_lab/protected_snapshot/namespace_worker.py",
                                       Path(__file__).resolve())}}
    os.kill(supervisor, signal.SIGKILL)
    _, supervisor_status = os.waitpid(supervisor, 0)
    record["supervisor_wait_status"] = supervisor_status
    record["supervisor_signal"] = os.WTERMSIG(supervisor_status) if os.WIFSIGNALED(supervisor_status) else None
    reaped = []
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                pid = 0
            if not pid:
                break
            reaped.append({"pid": pid, "wait_status": status,
                           "signal": os.WTERMSIG(status) if os.WIFSIGNALED(status) else None})
        survivors = []
        for pid in before_pids:
            observed = process_record(pid)
            if observed is not None:
                survivors.append(observed)
        if not survivors:
            break
        time.sleep(0.02)
    record.update({"reaped_orphans": reaped, "survivors": survivors,
                   "published_review_exists": (workspace / "output" / "review").exists(),
                   "previous_evidence_unchanged": hashlib.sha256(previous.read_bytes()).hexdigest() == previous_hash})
    record["status"] = ("PASS" if record["ready"] and len(before_pids) >= 5
                        and record["supervisor_signal"] == signal.SIGKILL
                        and not survivors and not record["published_review_exists"]
                        and record["previous_evidence_unchanged"] else "FAIL")
    (args.output / "result.json").write_text(json.dumps(record, indent=2, sort_keys=True))
    print(json.dumps({"output": str(args.output), "status": record["status"],
                      "process_count": len(before_pids), "survivors": survivors}, indent=2))
    return 0 if record["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
