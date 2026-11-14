"""Byte identities and finite input primitives, without relationship inference."""
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat

MAX_RUN_BYTES = 8 * 1024 * 1024
MAX_JSON_BYTES = MAX_RUN_BYTES
MAX_CAPTURE_BYTES = 32 * 1024 * 1024
MAX_DATA_BYTES = 64 * 1024 * 1024
MAX_DATABASE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_FILES = 1024
MAX_ROWS = 100_000
MAX_DEPTH = 32
MAX_NODES = 200_000
MAX_EPOCHS = 1024


class ProvenanceError(ValueError):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(code + ': ' + message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def identity(data):
    return {'bytes': len(data), 'sha256': sha256(data)}


def is_digest(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def parse_json(data, limit=MAX_JSON_BYTES):
    if type(data) is not bytes or not 0 < len(data) <= limit:
        raise ProvenanceError('PROVENANCE_JSON', 'nonempty bounded JSON bytes required')
    def pairs(values):
        obj = {}
        for key, value in values:
            if key in obj:
                raise ProvenanceError('PROVENANCE_JSON', 'duplicate JSON key')
            obj[key] = value
        return obj
    def nonfinite(_):
        raise ProvenanceError('PROVENANCE_JSON', 'nonfinite JSON number')
    def number(text):
        value = float(text)  # Parsing invalid raw evidence, never amount arithmetic.
        if not math.isfinite(value):
            nonfinite(text)
        return value
    try:
        value = json.loads(data.decode('utf-8', errors='strict'), object_pairs_hook=pairs,
                           parse_constant=nonfinite, parse_float=number)
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, ProvenanceError):
            raise
        raise ProvenanceError('PROVENANCE_JSON', 'invalid UTF-8 or JSON') from exc
    pending, count = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > MAX_DEPTH or count > MAX_NODES:
            raise ProvenanceError('PROVENANCE_LIMIT', 'JSON structural limit exceeded')
        if type(item) is str:
            if any(0xD800 <= ord(char) <= 0xDFFF for char in item):
                raise ProvenanceError('PROVENANCE_JSON', 'lone Unicode surrogate')
        elif type(item) is dict:
            pending.extend((child, depth + 1) for pair in item.items() for child in pair)
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
    return value


def bounded_file(path, limit=MAX_JSON_BYTES):
    path = Path(path)
    key = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            raise ProvenanceError('PROVENANCE_PATH', 'bounded regular non-symlink file required')
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            if key(opened) != key(before) or not stat.S_ISREG(opened.st_mode):
                raise ProvenanceError('PROVENANCE_SOURCE_CHANGED', 'file changed before read')
            data = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        if key(after) != key(before) or key(path.lstat()) != key(before) or len(data) != before.st_size:
            raise ProvenanceError('PROVENANCE_SOURCE_CHANGED', 'file changed during read')
        return data
    except OSError as exc:
        raise ProvenanceError('PROVENANCE_PATH', str(exc)) from exc


def member_name(name):
    if (type(name) is not str or not name or '\\' in name or '\x00' in name
            or PurePosixPath(name).is_absolute() or ':' in name
            or any(part in ('', '.', '..') for part in name.split('/'))):
        raise ProvenanceError('PROVENANCE_PATH', 'unsafe relative member name')
    return name
