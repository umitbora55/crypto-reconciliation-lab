"""Publish a complete owned directory atomically, without replacing a target."""
import ctypes
import errno
import os
from pathlib import Path
import shutil
import sys
import tempfile
from contextlib import contextmanager


def publish_directory(source, destination):
    """Use the OS no-replace rename; refuse unsupported platforms/filesystems.

    A plain POSIX rename can replace an existing empty directory after a race.
    macOS renamex_np(RENAME_EXCL) and Linux renameat2(RENAME_NOREPLACE) avoid it.
    Windows os.rename already refuses an existing destination. Only macOS is
    exercised in the recorded release environment.
    """
    source, destination = Path(source), Path(destination)
    if os.name == "nt":
        os.rename(source, destination)
        return
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        function = getattr(library, "renamex_np", None)
        if function is None:
            raise OSError("ATOMIC_PUBLICATION_UNSUPPORTED: renamex_np unavailable")
        function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        result = function(os.fsencode(source), os.fsencode(destination), 0x4)
    elif sys.platform.startswith("linux"):
        function = getattr(library, "renameat2", None)
        if function is None:
            raise OSError("ATOMIC_PUBLICATION_UNSUPPORTED: renameat2 unavailable")
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                             ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        result = function(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    else:
        raise OSError("ATOMIC_PUBLICATION_UNSUPPORTED: no no-replace directory rename")
    if result:
        error = ctypes.get_errno()
        if error in (errno.EEXIST, errno.ENOTEMPTY):
            raise FileExistsError(error, "OUTPUT_EXISTS: destination is never replaced", str(destination))
        raise OSError(error, "ATOMIC_PUBLICATION_FAILED: " + os.strerror(error), str(destination))


@contextmanager
def new_output_directory(destination):
    """Yield a new sibling staging directory and publish only after success."""
    requested = Path(destination).expanduser().absolute()
    if os.path.lexists(requested):
        raise FileExistsError("OUTPUT_EXISTS: choose a new output directory")
    requested.parent.mkdir(parents=True, exist_ok=True)
    destination = requested.parent.resolve() / requested.name
    if os.path.lexists(destination):
        raise FileExistsError("OUTPUT_EXISTS: choose a new output directory")
    staging = Path(tempfile.mkdtemp(prefix=".review-staging-", dir=destination.parent))
    try:
        yield staging
        publish_directory(staging, destination)
    finally:
        # Only the exact directory created above belongs to this operation.
        if staging.exists():
            shutil.rmtree(staging)
