"""Linux descriptor-based input and output boundary (no path-resolution fallback)."""
from contextlib import contextmanager
import ctypes
import errno
import fcntl
import hashlib
import os
from pathlib import Path
import platform
import stat
import sys

from . import ProtectionError

RESOLVE_NO_XDEV = 0x01
RESOLVE_NO_MAGICLINKS = 0x02
RESOLVE_NO_SYMLINKS = 0x04
RESOLVE_BENEATH = 0x08
# Linux UAPI values, identical on both audited syscall architectures. Older
# glibc-targeted Python builds may omit their Python names on a newer kernel.
F_ADD_SEALS = getattr(fcntl, "F_ADD_SEALS", 1033)
F_GET_SEALS = getattr(fcntl, "F_GET_SEALS", 1034)


class OpenHow(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_uint64), ("mode", ctypes.c_uint64),
                ("resolve", ctypes.c_uint64)]


def require_linux_root():
    if sys.platform != "linux" or os.geteuid() != 0:
        raise ProtectionError("LINUX_ROOT_REQUIRED: trusted Linux supervisor required")
    if platform.machine() not in ("aarch64", "x86_64"):
        raise ProtectionError("ARCH_UNSUPPORTED: openat2 ABI not audited")


def create_sealable_memfd(name):
    require_linux_root()
    if hasattr(os, "memfd_create"):
        return os.memfd_create(name, 3)  # MFD_CLOEXEC | MFD_ALLOW_SEALING
    # This is the SAME kernel primitive, not a file-permission fallback. If the
    # running libc/kernel lacks it, fail closed. Python availability is separate
    # from the runtime libc/kernel capability (e.g. portable CPython 3.12).
    library = ctypes.CDLL(None, use_errno=True)
    create = getattr(library, "memfd_create", None)
    if create is None:
        raise ProtectionError("MEMFD_UNSUPPORTED: libc entry point unavailable")
    create.argtypes = [ctypes.c_char_p, ctypes.c_uint]
    create.restype = ctypes.c_int
    fd = create(os.fsencode(name), 3)
    if fd < 0:
        error = ctypes.get_errno()
        raise OSError(error, "MEMFD_FAILED: " + os.strerror(error))
    return fd


def open_beneath(directory_fd, name, flags, mode=0):
    require_linux_root()
    if not isinstance(name, str) or not name or name.startswith("/") or any(
            part in ("", ".", "..") for part in name.split("/")) or "\x00" in name:
        raise ProtectionError("UNSAFE_PATH: literal relative components required")
    how = OpenHow(flags | os.O_CLOEXEC, mode,
                  RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_MAGICLINKS | RESOLVE_NO_XDEV)
    libc = ctypes.CDLL(None, use_errno=True)
    result = libc.syscall(ctypes.c_long(437), ctypes.c_int(directory_fd),
                          ctypes.c_char_p(os.fsencode(name)), ctypes.byref(how), ctypes.sizeof(how))
    if result < 0:
        error = ctypes.get_errno()
        raise OSError(error, "SECURE_OPEN_REJECTED: " + os.strerror(error), name)
    return result


def absolute_parts(path):
    value = os.fspath(path)
    if not value.startswith("/") or value.startswith("//") or "\x00" in value:
        raise ProtectionError("UNSAFE_PATH: absolute literal path required")
    parts = value[1:].split("/")
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ProtectionError("UNSAFE_PATH: no empty, dot or parent components")
    return parts


def check_directory(fd, owners, *, allow_sticky=False):
    value = os.fstat(fd)
    if not stat.S_ISDIR(value.st_mode) or value.st_uid not in owners:
        raise ProtectionError("UNTRUSTED_PARENT: directory ownership")
    # POSIX ACL write permission is bounded by the mode's group class mask.
    # Root-owned sticky ancestors are safe only above a separately trusted child.
    if value.st_mode & 0o022 and not (allow_sticky and value.st_uid == 0 and value.st_mode & stat.S_ISVTX):
        raise ProtectionError("UNTRUSTED_PARENT: writable directory or ACL mask")


@contextmanager
def parent_fd(path, producer_uid=0, *, output=False):
    require_linux_root()
    if producer_uid == 65534 or producer_uid < 0:
        raise ProtectionError("UNTRUSTED_PRODUCER: consumer cannot own input")
    parts = absolute_parts(path)
    current = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOATIME)
    try:
        owners = {0} if output else {0, producer_uid}
        check_directory(current, owners)
        for component in parts[:-1]:
            opened = open_beneath(current, component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOATIME)
            os.close(current)
            current = opened
            check_directory(current, owners, allow_sticky=True)
        # Final parent is never allowed to be shared writable, even sticky.
        check_directory(current, owners)
        yield current, parts[-1]
    finally:
        os.close(current)


@contextmanager
def source_fd(path, producer_uid=0):
    with parent_fd(path, producer_uid) as (directory, name):
        fd = open_beneath(directory, name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NOATIME | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ProtectionError("SOURCE_TYPE: single-link regular source required")
            if info.st_uid not in {0, producer_uid} or info.st_mode & 0o022:
                raise ProtectionError("SOURCE_OWNER: source and ACL mask must not permit untrusted writes")
            yield fd, directory, name
        finally:
            os.close(fd)


def metadata(fd):
    value = os.fstat(fd)
    return {"device": value.st_dev, "inode": value.st_ino, "mode": value.st_mode,
            "uid": value.st_uid, "gid": value.st_gid, "nlink": value.st_nlink,
            "size": value.st_size, "atime_ns": value.st_atime_ns,
            "mtime_ns": value.st_mtime_ns, "ctime_ns": value.st_ctime_ns,
            "xattrs": {name: os.getxattr(fd, name).hex() for name in sorted(os.listxattr(fd))}}


def digest_fd(fd):
    digest = hashlib.sha256()
    offset = 0
    while chunk := os.pread(fd, 1024 * 1024, offset):
        digest.update(chunk)
        offset += len(chunk)
    return {"bytes": offset, "sha256": digest.hexdigest()}


def same_path(fd, directory, name):
    opened = open_beneath(directory, name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NOATIME | os.O_NONBLOCK)
    try:
        before, after = os.fstat(fd), os.fstat(opened)
        if (before.st_dev, before.st_ino, before.st_nlink) != (after.st_dev, after.st_ino, 1):
            raise ProtectionError("SOURCE_CHANGED: pathname no longer identifies pinned inode")
    finally:
        os.close(opened)


def no_sidecars(directory, name):
    for suffix in ("-wal", "-shm", "-journal"):
        try:
            os.stat(name + suffix, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            continue
        raise ProtectionError("SIDECAR_PRESENT: " + suffix)


def no_target(directory, name):
    try:
        os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise FileExistsError("OUTPUT_EXISTS: previous evidence is never replaced")


def rename_noreplace(directory, source_name, target_name):
    libc = ctypes.CDLL(None, use_errno=True)
    call = getattr(libc, "renameat2", None)
    if call is None:
        raise ProtectionError("ATOMIC_PUBLICATION_UNSUPPORTED")
    result = call(ctypes.c_int(directory), ctypes.c_char_p(os.fsencode(source_name)),
                  ctypes.c_int(directory), ctypes.c_char_p(os.fsencode(target_name)), ctypes.c_uint(1))
    if result:
        error = ctypes.get_errno()
        if error in (errno.EEXIST, errno.ENOTEMPTY):
            raise FileExistsError(error, "OUTPUT_EXISTS: atomic publication refused")
        raise OSError(error, os.strerror(error))
    os.fsync(directory)
