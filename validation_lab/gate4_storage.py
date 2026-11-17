"""Gate 4 research adapter; no product configuration or transaction changes.

The unchanged Store initializes first, at its ordinary default. WAL conversion
belongs to initialization timing. Every later Store transaction is unchanged.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from crypto_reconciliation_lab import Store

METHODS = ('BASELINE', 'CANDIDATE_WAL_FULL')


def _json_cell(value):
    return {'sqlite_blob_hex': value.hex()} if isinstance(value, bytes) else value


def read_pragmas(store_or_connection):
    db = getattr(store_or_connection, 'db', store_or_connection)
    return {name: db.execute('PRAGMA ' + name).fetchone()[0] for name in
            ('journal_mode', 'synchronous', 'foreign_keys', 'page_size',
             'wal_autocheckpoint', 'user_version', 'locking_mode')}


def open_store(path, config=None, method='BASELINE', **store_kwargs):
    """Open an owned research database, retaining the ordinary Store class.

    Baseline settings are observed, never silently repaired. Candidate switches
    only journal mode and explicitly requests FULL. Caller owns close(). Existing
    candidate databases reopen with WAL and connection-local FULL readback.
    """
    if method not in METHODS:
        raise ValueError('GATE4_METHOD: unsupported research method')
    store = Store(path, config, **store_kwargs)
    try:
        if method == 'CANDIDATE_WAL_FULL':
            store.db.execute('PRAGMA journal_mode=WAL').fetchone()
            store.db.execute('PRAGMA synchronous=FULL')
        observed = read_pragmas(store)
        expected = 'delete' if method == 'BASELINE' else 'wal'
        if observed['journal_mode'] != expected or observed['synchronous'] != 2 or observed['foreign_keys'] != 1:
            raise ValueError('GATE4_NON_EQUIVALENT_PRAGMAS: ' + repr(observed))
        return store
    except BaseException:
        store.close()
        raise


def checkpoint(store_or_connection):
    """Same explicit final boundary in both methods; DELETE returns (0,-1,-1)."""
    db = getattr(store_or_connection, 'db', store_or_connection)
    return list(db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone())


def disk_snapshot(path):
    path = Path(path)
    answer = {}
    for suffix in ('', '-wal', '-shm', '-journal'):
        try:
            observed = Path(str(path) + suffix).stat()
        except FileNotFoundError:
            observed = None
        answer[path.name + suffix] = {'present': observed is not None,
                                      'logical_bytes': observed.st_size if observed else 0}
    return answer


def logical_snapshot(store_or_connection):
    """Streaming canonical table hashes, deterministic rows and schema objects.

    Explicit binary row sorting is independent of page layout or journal mode.
    Receipt identity additionally binds insertion order via its integer id.
    """
    db = getattr(store_or_connection, 'db', store_or_connection)
    tables = {}
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        quoted = '"' + name.replace('"', '""') + '"'
        columns = [row[1] for row in db.execute('PRAGMA table_info(' + quoted + ')')]
        order = ','.join(str(i + 1) + ' COLLATE BINARY' for i in range(len(columns)))
        h, count = hashlib.sha256(), 0
        for row in db.execute('SELECT * FROM ' + quoted + ' ORDER BY ' + order):
            h.update((json.dumps([_json_cell(value) for value in row], ensure_ascii=True, separators=(',', ':'), allow_nan=False) + '\n').encode())
            count += 1
        tables[name] = {'columns': columns, 'rows': count, 'sha256': h.hexdigest()}
    objects = [list(row) for row in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name')]
    receipts = hashlib.sha256()
    for row in db.execute('SELECT id,receipt_hash,record_id,received_at,status,error,raw FROM receipts ORDER BY id'):
        receipts.update((json.dumps(list(row), ensure_ascii=True, separators=(',', ':'), allow_nan=False) + '\n').encode())
    return {'tables': tables, 'schema_objects': objects,
            'ordered_receipts_sha256': receipts.hexdigest(),
            'user_version': db.execute('PRAGMA user_version').fetchone()[0]}
