"""Trusted Linux namespace bootstrap and unprivileged consumer preflight.

Executed as an isolated file by sandbox.py; has no package imports before
privilege drop. Host root, the system runtime and installed package are trusted.
"""
from __future__ import annotations

import base64
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import runpy
import shutil
import signal
import stat
import subprocess
import sys
import time


LIBC = None
MS_RDONLY, MS_NOSUID, MS_NODEV, MS_NOEXEC = 1, 2, 4, 8
MS_REMOUNT, MS_BIND, MS_REC, MS_PRIVATE, MS_NOATIME = 32, 4096, 16384, 1 << 18, 1024
SEALS = 15


def load_libc():
    # ctypes/libffi retains a runtime-library FD on this platform. It belongs
    # only in the privileged setup path, never in the consumer preflight.
    global ctypes, LIBC
    if LIBC is None:
        import ctypes
        LIBC = ctypes.CDLL(None, use_errno=True)


def checked(result, operation):
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, f"ISOLATION_{operation}: {os.strerror(error)}")


def mount(source, target, kind=None, flags=0, data=None):
    load_libc()
    LIBC.mount.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
                           ctypes.c_ulong, ctypes.c_char_p]
    checked(LIBC.mount(os.fsencode(source) if source is not None else None,
                       os.fsencode(target), os.fsencode(kind) if kind else None,
                       flags, os.fsencode(data) if data else None), "MOUNT")


def prctl(option, arg=0):
    load_libc()
    checked(LIBC.prctl(ctypes.c_int(option), ctypes.c_ulong(arg), ctypes.c_ulong(0),
                       ctypes.c_ulong(0), ctypes.c_ulong(0)), "PRCTL")


def close_fds(first=3):
    load_libc()
    # close_range is atomic with respect to descriptor inheritance. No process
    # in the trusted worker is multithreaded. Fall back to the same close sweep
    # provided by Python when libc lacks this entry point.
    close_range = getattr(LIBC, "close_range", None)
    if close_range is not None:
        checked(close_range(ctypes.c_uint(first), ctypes.c_uint(0xFFFFFFFF), ctypes.c_uint(0)), "CLOSE_RANGE")
    else:
        os.closerange(first, resource.getrlimit(resource.RLIMIT_NOFILE)[0])


def snapshot_observation(path):
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NOATIME)
    try:
        info = os.fstat(fd)
        digest = hashlib.sha256()
        while block := os.read(fd, 65536):
            digest.update(block)
        return {"device": info.st_dev, "inode": info.st_ino, "size": info.st_size,
                "mode": info.st_mode, "uid": info.st_uid, "gid": info.st_gid,
                "nlink": info.st_nlink, "atime_ns": info.st_atime_ns,
                "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns,
                "sha256": digest.hexdigest(),
                "xattrs": {name: base64.b64encode(os.getxattr(fd, name)).decode("ascii")
                           for name in sorted(os.listxattr(fd))}}
    finally:
        os.close(fd)


def trusted_runtime_file(path):
    path = Path(path).resolve(strict=True)
    for current in (path, *path.parents):
        item = current.stat()
        if item.st_uid != 0 or item.st_mode & 0o022:
            raise RuntimeError(f"ISOLATION_RUNTIME_UNTRUSTED: {current}")
    if not path.is_file():
        raise RuntimeError(f"ISOLATION_RUNTIME_TYPE: {path}")
    return path


def copy_regular(source, destination, *, trusted=False, executable=False):
    source, destination = Path(source), Path(destination)
    if trusted:
        source = trusted_runtime_file(source)
    else:
        info = source.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise RuntimeError(f"ISOLATION_CODE_TYPE: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as incoming, destination.open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing)
    destination.chmod(0o555 if executable else 0o444)


def runtime_copy(runtime, root):
    """Copy a bounded system runtime, never bind a host library directory."""
    runtime = trusted_runtime_file(runtime)
    details = subprocess.check_output([str(runtime), "-I", "-S", "-c",
        "import sys,sysconfig,json;print(json.dumps({'stdlib':sysconfig.get_path('stdlib'),'version':sys.version}))"],
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8"}, text=True)
    details = json.loads(details)
    stdlib = Path(details["stdlib"]).resolve(strict=True)
    if stdlib.parent != Path("/usr/lib") or not re.fullmatch(r"python3\.\d+", stdlib.name):
        raise RuntimeError("ISOLATION_RUNTIME_LAYOUT: system /usr/lib/python3.X required")
    copy_regular(runtime, root / runtime.relative_to("/"), trusted=True, executable=True)
    libraries = set()
    elf_files = [runtime]
    for directory, names, files in os.walk(stdlib, followlinks=False):
        names[:] = sorted(name for name in names if name not in ("__pycache__", "test", "tests", "site-packages", "dist-packages")
                          and not name.startswith("config-"))
        for name in sorted(files):
            source = Path(directory) / name
            if source.suffix not in (".py", ".so", ".json"):
                continue
            copy_regular(source, root / source.relative_to("/"), trusted=True,
                         executable=source.suffix == ".so")
            if source.suffix == ".so":
                elf_files.append(source)
    # ldd is applied only to verified system ELF files, never source inputs or
    # attacker supplied binaries. Dependencies are copied as individual files.
    for elf in elf_files:
        output = subprocess.check_output(["/usr/bin/ldd", str(elf)], text=True,
                                         env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
        if "not found" in output:
            raise RuntimeError("ISOLATION_RUNTIME_DEPENDENCY: " + output)
        for name in re.findall(r"(?:=>\s+)?(/\S+)\s+\(", output):
            libraries.add(name)
    for name in sorted(libraries):
        destination = root / Path(name).relative_to("/")
        if not destination.exists():
            copy_regular(name, destination, trusted=True, executable=True)
    return details


def copy_package(source, root):
    source = Path(source)
    for directory, names, files in os.walk(source, followlinks=False):
        for name in names:
            if (Path(directory) / name).is_symlink():
                raise RuntimeError("ISOLATION_PACKAGE_LINK: package directories must be regular")
        names[:] = sorted(name for name in names if name != "__pycache__")
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix in (".py", ".html", ".css", ".js", ".json"):
                copy_regular(path, root / "app" / "crypto_reconciliation_lab" / path.relative_to(source))


def prepare(config):
    workspace = Path(config["workspace"])
    root = workspace / "root"
    root.mkdir(mode=0o700)
    mount(None, "/", flags=MS_REC | MS_PRIVATE)
    mount("tmpfs", root, "tmpfs", MS_NOSUID | MS_NODEV | MS_NOATIME,
          "size=256m,nr_inodes=20000,mode=0755")
    for name in ("input", "output", "tmp", "proc", "dev", "app"):
        (root / name).mkdir()
    details = runtime_copy(config["runtime"], root)
    copy_package(config["package"], root)
    copy_regular(__file__, root / "app" / "consumer-entry.py")
    contract = {key: value for key, value in config.items()
                if key in ("uid", "gid", "host_namespaces")}
    contract["runtime"] = details
    copy_regular(workspace / "selection.json", root / "input" / "selection.json")
    if (workspace / "consumer-script.py").exists():
        copy_regular(workspace / "consumer-script.py", root / "app" / "consumer-script.py")
    snapshot = root / "input" / "snapshot.sqlite3"
    fd = config["snapshot_fd"]
    if fcntl.fcntl(fd, fcntl.F_GET_SEALS) & SEALS != SEALS:
        raise RuntimeError("ISOLATION_SEALS: required seals missing")
    if fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY:
        raise RuntimeError("ISOLATION_FD: writable snapshot description refused")
    opened = os.fstat(fd)
    if (opened.st_dev, opened.st_ino, opened.st_size) != (config["snapshot_device"], config["snapshot_inode"], config["snapshot_size"]):
        raise RuntimeError("ISOLATION_IDENTITY: sealed descriptor differs")
    # Linux refuses binding the internal mount of a memfd (EINVAL). Materialize
    # its sealed bytes into a fresh inode of this private namespace's tmpfs.
    # No untrusted process exists here yet. Close the SOLE writable descriptor
    # before remounting the entire filesystem read-only and starting consumers.
    os.lseek(fd, 0, os.SEEK_SET)
    anchor_digest = hashlib.sha256()
    with snapshot.open("xb") as target:
        while block := os.read(fd, 65536):
            target.write(block)
            anchor_digest.update(block)
        target.flush()
        os.fsync(target.fileno())
        os.fchmod(target.fileno(), 0o444)
    os.close(fd)
    snapshot_before = snapshot_observation(snapshot)
    if snapshot_before["sha256"] != anchor_digest.hexdigest() or snapshot_before["size"] != opened.st_size:
        raise RuntimeError("ISOLATION_COPY: materialized bytes differ from sealed anchor")
    contract["snapshot"] = snapshot_before
    contract["sealed_anchor"] = {"device": opened.st_dev, "inode": opened.st_ino,
                                  "size": opened.st_size, "sha256": anchor_digest.hexdigest(), "seals": SEALS}
    (root / "input" / "contract.json").write_text(json.dumps(contract, sort_keys=True))
    output = workspace / "output"
    output.mkdir(mode=0o700)
    os.chown(output, config["uid"], config["gid"])
    mount(output, root / "output", flags=MS_BIND)
    mount(None, root / "output", flags=MS_BIND | MS_REMOUNT | MS_NODEV | MS_NOSUID | MS_NOEXEC | MS_NOATIME)
    mount("tmpfs", root / "tmp", "tmpfs", MS_NODEV | MS_NOSUID | MS_NOEXEC | MS_NOATIME,
          "size=128m,nr_inodes=4096,mode=1777")
    mount("proc", root / "proc", "proc", MS_NOSUID | MS_NODEV | MS_NOEXEC | MS_RDONLY,
          "hidepid=2")
    # Only a harmless character device is needed. There are no host disks,
    # /dev/fd aliases or terminals in the consumer root.
    os.mknod(root / "dev" / "null", stat.S_IFCHR | 0o666, os.makedev(1, 3))
    mount(None, root, flags=MS_REMOUNT | MS_RDONLY | MS_NOSUID | MS_NODEV | MS_NOATIME)
    # This attestation FD is retained only by trusted PID1. The consumer closes
    # it before exec; neither its output directory nor proc can modify it.
    attest_fd = os.open(workspace / "sandbox-boundary.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    if attest_fd != 3:
        os.dup2(attest_fd, 3, inheritable=False)
        os.close(attest_fd)
    os.chroot(root)
    os.chdir("/")
    close_fds(4)
    return contract


def drop_privileges(uid, gid):
    prctl(38, 1)  # PR_SET_NO_NEW_PRIVS
    # Clear ambient capabilities, then all supported bounding-set entries.
    prctl(47, 4)  # PR_CAP_AMBIENT, PR_CAP_AMBIENT_CLEAR_ALL
    last_cap = int(Path("/proc/sys/kernel/cap_last_cap").read_text())
    for capability in range(last_cap + 1):
        prctl(24, capability)  # PR_CAPBSET_DROP
    os.setgroups([])
    os.setresgid(gid, gid, gid)
    os.setresuid(uid, uid, uid)
    class Header(ctypes.Structure):
        _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]
    class Data(ctypes.Structure):
        _fields_ = [("effective", ctypes.c_uint32), ("permitted", ctypes.c_uint32), ("inheritable", ctypes.c_uint32)]
    checked(LIBC.capset(ctypes.byref(Header(0x20080522, 0)), ctypes.byref((Data * 2)())), "CAPSET")
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
    resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 1024 * 1024, 256 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    install_seccomp()
    close_fds()


def install_seccomp():
    """Forbid acquiring another namespace or new mount topology after drop.

    No generic syscall allowlist or financial behavior change is introduced.
    clone remains available for normal fork, with namespace creation bits
    rejected. clone3 returns ENOSYS because BPF cannot safely inspect its pointed
    argument structure. Architecture mismatch kills the process, fail closed.
    """
    architecture = os.uname().machine
    if architecture == "aarch64":
        arch, clone = 0xC00000B7, 220
        denied = (40, 39, 41, 51, 97, 268, 265)  # mount, umount2, pivot_root, chroot, unshare, setns, open_by_handle_at
    elif architecture == "x86_64":
        arch, clone = 0xC000003E, 56
        denied = (165, 166, 155, 161, 272, 308, 304)
    else:
        raise RuntimeError("ISOLATION_SECCOMP_ARCH: only aarch64 and x86_64 supported")
    # Linux's newer mount API and clone3 share these numbers on both targets.
    denied += (428, 429, 430, 431, 432, 442)
    class Filter(ctypes.Structure):
        _fields_ = [("code", ctypes.c_ushort), ("jt", ctypes.c_ubyte),
                    ("jf", ctypes.c_ubyte), ("k", ctypes.c_uint32)]
    class Program(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.POINTER(Filter))]
    # BPF_LD|W|ABS, BPF_JMP|JEQ|K, BPF_RET|K.
    code = [(0x20, 0, 0, 4), (0x15, 1, 0, arch), (0x06, 0, 0, 0x80000000),
            (0x20, 0, 0, 0),
            # x32 uses AUDIT_ARCH_X86_64 with a tagged syscall number. Do not
            # allow this second ABI to bypass the native number checks.
            (0x45, 0, 1, 0x40000000), (0x06, 0, 0, 0x00050000 | errno.ENOSYS)]
    for syscall in denied:
        code.extend([(0x15, 0, 1, syscall), (0x06, 0, 0, 0x00050000 | errno.EPERM)])
    code.extend([(0x15, 0, 1, 435), (0x06, 0, 0, 0x00050000 | errno.ENOSYS)])
    # args[0] lower 32 bits; namespace clone flags all live in that half.
    code.extend([(0x15, 0, 3, clone), (0x20, 0, 0, 16),
                 (0x45, 0, 1, 0x7E020000),  # all CLONE_NEW* bits incl NEWCGROUP
                 (0x06, 0, 0, 0x00050000 | errno.EPERM),
                 (0x06, 0, 0, 0x7FFF0000)])
    instructions = (Filter * len(code))(*(Filter(*item) for item in code))
    program = Program(len(code), instructions)
    checked(LIBC.prctl(ctypes.c_int(22), ctypes.c_ulong(2), ctypes.byref(program),
                       ctypes.c_ulong(0), ctypes.c_ulong(0)), "SECCOMP")


def consumer_preflight():
    contract = json.loads(Path("/input/contract.json").read_text())
    status = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        key, value = line.split(":", 1)
        status[key] = value.strip()
    if (os.getresuid() != (contract["uid"],) * 3 or os.getresgid() != (contract["gid"],) * 3
            or os.getgroups() or os.geteuid() == 0 or status.get("NoNewPrivs") != "1"):
        raise RuntimeError("ISOLATION_CREDENTIALS: privilege boundary not established")
    if status.get("Seccomp") != "2" or int(status.get("Seccomp_filters", "0")) < 1:
        raise RuntimeError("ISOLATION_SECCOMP: namespace-creation filter missing")
    for name in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"):
        if int(status[name], 16):
            raise RuntimeError("ISOLATION_CAPABILITIES: " + name)
    namespaces = {name: os.readlink(f"/proc/self/ns/{name}") for name in contract["host_namespaces"]}
    if any(namespaces[name] == original for name, original in contract["host_namespaces"].items()):
        raise RuntimeError("ISOLATION_NAMESPACES: host namespace retained")
    inherited = {}
    for name in os.listdir("/proc/self/fd"):
        try:
            inherited[name] = os.readlink("/proc/self/fd/" + name)
        except FileNotFoundError:
            continue  # the directory enumeration descriptor has closed
    if any(int(name) > 2 for name in inherited):
        raise RuntimeError("ISOLATION_FDS: unexpected inherited descriptor " + repr(inherited))
    entries = [line.split() for line in Path("/proc/self/mountinfo").read_text().splitlines()]
    root_mount = [entry for entry in entries if entry[4] == "/"]
    if len(root_mount) != 1 or not {"ro", "noatime", "nosuid", "nodev"} <= set(root_mount[0][5].split(",")):
        raise RuntimeError("ISOLATION_ROOT: ro,noatime,nosuid,nodev private root required")
    separator = root_mount[0].index("-")
    if root_mount[0][separator + 1] != "tmpfs" or any(entry[4] == "/input" or entry[4].startswith("/input/") for entry in entries):
        raise RuntimeError("ISOLATION_MOUNT: snapshot must belong to the private read-only tmpfs")
    fd = os.open("/input/snapshot.sqlite3", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        expected = contract["snapshot"]
        if (info.st_dev, info.st_ino, info.st_size) != (expected["device"], expected["inode"], expected["size"]):
            raise RuntimeError("ISOLATION_IDENTITY: consumer opened a different inode")
        digest = hashlib.sha256()
        while block := os.read(fd, 65536):
            digest.update(block)
        if digest.hexdigest() != expected["sha256"] or info.st_uid != 0 or info.st_mode & 0o222 or info.st_nlink != 1:
            raise RuntimeError("ISOLATION_COPY: protected snapshot contract failed")
    finally:
        os.close(fd)
    # Existing exporter reopens this exact root-owned path. Its parent and file
    # filesystem cannot be renamed/replaced by the consumer. No writer exists.
    return {"format": "protected-snapshot-consumer-observation-v1", "uid": os.getuid(),
            "gid": os.getgid(), "pid": os.getpid(), "status": status,
            "namespaces": namespaces, "inherited_fds": inherited,
            "snapshot_mount": root_mount[0], "root_mount": root_mount[0],
            "snapshot_identity": [info.st_dev, info.st_ino], "sealed_anchor": contract["sealed_anchor"],
            "runtime": contract["runtime"], "preflight": "PASS"}


# Explicit name for independent wrong-boundary verification. This performs
# kernel observations; a caller's flag or environment value never grants trust.
verify_consumer_boundary = consumer_preflight


def consume():
    audit = consumer_preflight()
    audit["export_started_monotonic"] = time.monotonic()
    # -I -S excludes cwd, user sites, PYTHONPATH and system .pth/sitecustomize.
    # /app contains only the supervisor's frozen package copy.
    sys.path.insert(0, "/app")
    Path("/output/consumer.json").write_text(json.dumps(audit, indent=2, sort_keys=True))
    custom = Path("/app/consumer-script.py")
    if custom.exists():
        runpy.run_path(str(custom), run_name="__main__")
    else:
        from crypto_reconciliation_lab.review.export import export_selection
        export_selection("/input/selection.json", "/output/review")
    audit["consumer_seconds"] = time.monotonic() - audit["export_started_monotonic"]
    Path("/output/consumer.json").write_text(json.dumps(audit, indent=2, sort_keys=True))


def namespace_init(config, parent_alive_fd):
    namespace_started = time.monotonic()
    # The outside namespace monitor owns the write end. Setting PDEATHSIG then
    # checking EOF closes the fork-to-prctl race even though getppid()==0 here.
    prctl(1, signal.SIGKILL)
    try:
        if os.read(parent_alive_fd, 1) == b"":
            raise RuntimeError("ISOLATION_PARENT: bootstrap disappeared")
    except BlockingIOError:
        pass
    setup_started = time.monotonic()
    contract = prepare(config)
    setup_seconds = time.monotonic() - setup_started
    consumer_started = time.monotonic()
    child = os.fork()
    if child == 0:
        try:
            drop_privileges(config["uid"], config["gid"])
            # runpy closes its code-reading FD before executing the module;
            # CPython's direct script runner retains an extra script FD.
            os.execve(config["runtime"], [config["runtime"], "-I", "-S", "-c",
                      "import runpy;runpy.run_path('/app/consumer-entry.py',run_name='__main__')", "--consumer"],
                      {"PATH": "/usr/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TMPDIR": "/tmp"})
        except BaseException:
            import traceback
            traceback.print_exc()
            os._exit(120)
    # PID1 retains root to preserve PDEATHSIG across the child's UID changes.
    # It has chrooted and retained only stdio plus its private attestation FD3;
    # the consumer closes that FD3 before exec and cannot reach root's proc FDs.
    _, status = os.waitpid(child, 0)
    result = os.waitstatus_to_exitcode(status)
    consumer_process_seconds = time.monotonic() - consumer_started
    postcheck_started = time.monotonic()
    snapshot_after = snapshot_observation("/input/snapshot.sqlite3")
    snapshot_postcheck_seconds = time.monotonic() - postcheck_started
    attestation = {"format": "protected-snapshot-supervisor-attestation-v1",
                   "sealed_anchor": contract["sealed_anchor"],
                   "snapshot_before": contract["snapshot"], "snapshot_after": snapshot_after,
                   "snapshot_unchanged": contract["snapshot"] == snapshot_after,
                   "consumer_returncode": result,
                   "timings": {"setup_seconds": setup_seconds,
                               "consumer_process_seconds": consumer_process_seconds,
                               "snapshot_postcheck_seconds": snapshot_postcheck_seconds,
                               "namespace_total_seconds": time.monotonic() - namespace_started}}
    encoded = (json.dumps(attestation, sort_keys=True, indent=2) + "\n").encode()
    with os.fdopen(3, "wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    if not attestation["snapshot_unchanged"]:
        return 122
    return result


def bootstrap(config_path):
    if sys.platform != "linux" or os.geteuid() != 0:
        raise RuntimeError("ISOLATION_UNSUPPORTED: Linux root supervisor required")
    config = json.loads(Path(config_path).read_text())
    prctl(1, signal.SIGKILL)
    if os.getppid() != config["parent_pid"]:
        raise RuntimeError("ISOLATION_PARENT: supervisor disappeared")
    # No new user namespace: uid 0 is never mapped to the untrusted consumer.
    flags = 0x00020000 | 0x20000000 | 0x40000000 | 0x08000000 | 0x04000000
    checked(LIBC.unshare(ctypes.c_int(flags)), "UNSHARE")
    read_fd, write_fd = os.pipe2(os.O_CLOEXEC | os.O_NONBLOCK)
    child = os.fork()
    if child == 0:
        os.close(write_fd)
        try:
            result = namespace_init(config, read_fd)
            os._exit(result if result >= 0 else 128 - result)
        except BaseException:
            import traceback
            traceback.print_exc()
            os._exit(121)
    os.close(read_fd)
    os.close(config["snapshot_fd"])
    _, status = os.waitpid(child, 0)
    os.close(write_fd)
    result = os.waitstatus_to_exitcode(status)
    return result if result >= 0 else 128 - result


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--bootstrap":
        raise SystemExit(bootstrap(sys.argv[2]))
    if sys.argv[1:] == ["--consumer"]:
        consume()
    else:
        raise SystemExit("ISOLATION_INVOCATION: internal worker only")
