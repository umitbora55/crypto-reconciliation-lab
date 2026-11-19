"""Opt-in Linux process isolation for an already sealed snapshot.

The caller, source code, host root, system interpreter and kernel are trusted.
No pathname supplied by a consumer is opened by this privileged module.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time

from .securefs import F_GET_SEALS


REQUIRED_SEALS = 0x01 | 0x02 | 0x04 | 0x08  # SEAL, SHRINK, GROW, WRITE
CONSUMER_UID = 65534
CONSUMER_GID = 65534


class IsolationError(RuntimeError):
    """Protection cannot be established; do not start an exporter."""


def _sealed(fd):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 0:
        raise IsolationError("ISOLATION_INPUT: expected an anonymous sealed regular file")
    if info.st_uid != 0 or info.st_mode & 0o222:
        raise IsolationError("ISOLATION_INPUT: snapshot must be root owned and nonwritable")
    if fcntl.fcntl(fd, F_GET_SEALS) & REQUIRED_SEALS != REQUIRED_SEALS:
        raise IsolationError("ISOLATION_INPUT: all four immutable content seals are required")
    return info


def run_isolated(snapshot_fd: int, selection_bytes: bytes, workspace: Path,
                 package_root: Path, *, consumer_script: Path | None = None,
                 timeout: float = 60) -> dict:
    """Run the unchanged exporter behind a sealed, read-only namespace path.

    workspace must be a newly created root-owned 0700 directory on a local
    filesystem. It remains private, including on failure. The caller publishes
    output/review only after separately validating the result. Nonzero process
    exits are returned, never interpreted as successful exports.

    consumer_script is an internal verification seam: its bytes execute only
    AFTER the exact same privilege drop and kernel preflight as the exporter.
    It is never imported or executed by a privileged process.
    """
    if sys.platform != "linux" or os.geteuid() != 0:
        raise IsolationError("ISOLATION_UNSUPPORTED: Linux trusted root supervisor required")
    if not 0 < timeout <= 300:
        raise IsolationError("ISOLATION_LIMIT: timeout must be in (0,300]")
    if not isinstance(selection_bytes, bytes) or len(selection_bytes) > 1024 * 1024:
        raise IsolationError("ISOLATION_SELECTION: bounded selection bytes required")
    workspace = Path(workspace)
    if not workspace.is_absolute() or workspace.resolve() != workspace:
        raise IsolationError("ISOLATION_WORKSPACE: canonical absolute directory required")
    before = workspace.lstat()
    if not stat.S_ISDIR(before.st_mode) or before.st_uid != 0 or before.st_mode & 0o777 != 0o700:
        raise IsolationError("ISOLATION_WORKSPACE: root-owned mode 0700 required")
    info = _sealed(snapshot_fd)
    if fcntl.fcntl(snapshot_fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY:
        raise IsolationError("ISOLATION_INPUT: caller must release writable descriptions before handoff")
    runtime = Path("/usr/bin/python3").resolve(strict=True)
    runtime_info = runtime.stat()
    if runtime.parent != Path("/usr/bin") or runtime_info.st_uid or runtime_info.st_mode & 0o022:
        raise IsolationError("ISOLATION_RUNTIME: trusted system Python required")
    package = Path(package_root).resolve(strict=True)
    if package.name != "crypto_reconciliation_lab":
        package = package / "crypto_reconciliation_lab"
    if not (package / "__init__.py").is_file():
        raise IsolationError("ISOLATION_PACKAGE: package directory required")
    worker = Path(__file__).with_name("namespace_worker.py")
    # Resolve an O_RDONLY handle to the same sealed inode. The producer's
    # writable open file description is never passed to a child.
    read_fd = os.open(f"/proc/self/fd/{snapshot_fd}", os.O_RDONLY | os.O_CLOEXEC | os.O_NOATIME)
    try:
        actual = _sealed(read_fd)
        if (actual.st_dev, actual.st_ino) != (info.st_dev, info.st_ino):
            raise IsolationError("ISOLATION_INPUT: descriptor identity mismatch")
        config = {
            "format": "protected-snapshot-sandbox-v1", "parent_pid": os.getpid(),
            "snapshot_fd": read_fd, "snapshot_device": info.st_dev,
            "snapshot_inode": info.st_ino, "snapshot_size": info.st_size,
            "uid": CONSUMER_UID, "gid": CONSUMER_GID,
            "runtime": str(runtime), "package": str(package),
            "workspace": str(workspace),
            "host_namespaces": {name: os.readlink(f"/proc/self/ns/{name}")
                                for name in ("mnt", "pid", "net", "ipc", "uts")},
        }
        config_path = workspace / "sandbox-config.json"
        with config_path.open("x", encoding="utf-8") as stream:
            json.dump(config, stream, sort_keys=True)
        with (workspace / "selection.json").open("xb") as stream:
            stream.write(selection_bytes)
        if consumer_script is not None:
            # Only copy data; the privileged worker never executes this file.
            with Path(consumer_script).open("rb") as stream:
                code = stream.read(1024 * 1024 + 1)
            if len(code) > 1024 * 1024:
                raise IsolationError("ISOLATION_LIMIT: consumer script exceeds 1 MiB")
            with (workspace / "consumer-script.py").open("xb") as stream:
                stream.write(code)
        command = [str(runtime), "-I", "-S", str(worker), "--bootstrap", str(config_path)]
        started = time.monotonic()
        env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
        # Bound persisted logs as well as child file writes: inherited stdout
        # regular files are not writable source handles and stay root-private.
        with (workspace / "sandbox.stdout").open("xb") as stdout, (workspace / "sandbox.stderr").open("xb") as stderr:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, close_fds=True,
                                       pass_fds=(read_fd,), start_new_session=True,
                                       cwd="/", env=env)
            timed_out = False
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                # SIGKILL is intentional: namespace PID1 death kills even
                # descendants which created their own sessions/process groups.
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        result = {
            "command": command, "returncode": process.returncode,
            "timed_out": timed_out, "elapsed_seconds": time.monotonic() - started,
            "stdout": (workspace / "sandbox.stdout").read_text(errors="replace"),
            "stderr": (workspace / "sandbox.stderr").read_text(errors="replace"),
            "workspace": str(workspace), "consumer_audit": None,
            "trusted_attestation": None,
        }
        audit = workspace / "output" / "consumer.json"
        if audit.is_file() and not audit.is_symlink() and audit.stat().st_size <= 1024 * 1024:
            try:
                result["consumer_audit"] = json.loads(audit.read_text())
            except (ValueError, OSError):
                pass
        attestation = workspace / "sandbox-boundary.json"
        if attestation.is_file():
            result["trusted_attestation"] = json.loads(attestation.read_text())
        return result
    finally:
        os.close(read_fd)
