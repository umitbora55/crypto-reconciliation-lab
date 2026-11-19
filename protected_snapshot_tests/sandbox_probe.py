"""Adversarial consumer: execute only through the real sandbox boundary.

This is deliberately not imported by runtime code. It exercises attacks and
the unchanged financial exporter in concurrent, actual forked processes.
"""
import errno
import hashlib
import json
import os
from pathlib import Path
import time


SNAPSHOT = "/input/snapshot.sqlite3"
HOST_SOURCE = "/var/tmp/crl-financial-wal-_2p915zx/evidence.sqlite3"
observations = []


def denied(name, operation):
    try:
        operation()
    except OSError as error:
        observations.append({"attack": name, "status": "EXPECTED_REJECTION", "errno": error.errno})
        return
    observations.append({"attack": name, "status": "UNEXPECTED_SUCCESS"})
    raise AssertionError("Attack succeeded: " + name)


def writable_open():
    fd = os.open(SNAPSHOT, os.O_RDWR)
    os.close(fd)


denied("snapshot_writable_open", writable_open)
denied("snapshot_truncate", lambda: os.truncate(SNAPSHOT, 0))
denied("snapshot_chmod", lambda: os.chmod(SNAPSHOT, 0o666))
denied("snapshot_utime", lambda: os.utime(SNAPSHOT, ns=(1, 1)))
denied("snapshot_unlink", lambda: os.unlink(SNAPSHOT))
denied("snapshot_rename", lambda: os.rename(SNAPSHOT, "/output/stolen.sqlite3"))
denied("snapshot_hardlink_alias", lambda: os.link(SNAPSHOT, "/output/alias.sqlite3"))
denied("live_wal_visibility", lambda: os.open(HOST_SOURCE, os.O_RDONLY))
denied("host_tmp_visibility", lambda: os.stat("/var/tmp/crl-protected-evidence-v1"))
denied("supervisor_fd_visibility", lambda: os.open("/proc/1/fd/3", os.O_WRONLY))
denied("regain_root", lambda: os.setresuid(0, 0, 0))

# New user namespaces are denied even on a kernel where unprivileged userns is
# enabled. A namespace-local root cannot be acquired after initial preflight.
import ctypes
libc = ctypes.CDLL(None, use_errno=True)
nr = 97 if os.uname().machine == "aarch64" else 272
result = libc.syscall(ctypes.c_long(nr), ctypes.c_ulong(0x10000000))
assert result == -1 and ctypes.get_errno() == errno.EPERM
observations.append({"attack": "new_user_namespace", "status": "EXPECTED_REJECTION", "errno": ctypes.get_errno()})
clone_nr = 220 if os.uname().machine == "aarch64" else 56
result = libc.syscall(ctypes.c_long(clone_nr), ctypes.c_ulong(0x10000000), 0, 0, 0, 0)
assert result == -1 and ctypes.get_errno() == errno.EPERM
observations.append({"attack": "clone_user_namespace", "status": "EXPECTED_REJECTION", "errno": ctypes.get_errno()})
result = libc.syscall(ctypes.c_long(435), 0, 0)
assert result == -1 and ctypes.get_errno() == errno.ENOSYS
observations.append({"attack": "clone3", "status": "EXPECTED_REJECTION", "errno": ctypes.get_errno()})

before = hashlib.sha256(Path(SNAPSHOT).read_bytes()).hexdigest()
read_fd, write_fd = os.pipe()
children = []
for index in range(3):
    pid = os.fork()
    if pid == 0:
        os.close(write_fd)
        os.read(read_fd, 1)
        child_observations = []
        for iteration in range(12):
            try:
                writable_open()
            except OSError as error:
                child_observations.append({"iteration": iteration, "errno": error.errno})
            else:
                os._exit(90)
            time.sleep(0.01)
        Path(f"/output/attacker-{index}.json").write_text(json.dumps(child_observations))
        os._exit(0)
    children.append(pid)
os.close(read_fd)
os.write(write_fd, b"go!")
os.close(write_fd)
from crypto_reconciliation_lab.review.export import export_selection
export_selection("/input/selection.json", "/output/review")
waited = [os.waitpid(pid, 0) for pid in children]
assert all(status == 0 for _, status in waited)
after = hashlib.sha256(Path(SNAPSHOT).read_bytes()).hexdigest()
assert before == after
Path("/output/attacks.json").write_text(json.dumps({"observations": observations,
    "concurrent_processes": children, "waited": waited, "snapshot_before": before,
    "snapshot_after": after, "status": "PASS"}, indent=2, sort_keys=True))
