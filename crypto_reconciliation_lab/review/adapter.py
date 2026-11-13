"""Read closed local SQLite snapshots without Store, recovery or migration."""
from dataclasses import dataclass
from contextlib import contextmanager
import hashlib
import json
import os
import tempfile
from pathlib import Path
import sqlite3
import stat

from .validation import ReviewError, canonical, strict_json, validate_payload, object_member_texts

MAX_RUNS = 100
MAX_PAYLOAD_BYTES = 64 * 1024 * 1024
MAX_SELECTION_BYTES = 1024 * 1024
CHUNK_BYTES = 64 * 1024
SIDECARS = ('-wal', '-shm', '-journal')


@dataclass(frozen=True)
class SourceSelection:
    alias: str
    database: Path
    run_ids: tuple
    label: str
    run_labels: dict


@dataclass(frozen=True)
class Selection:
    sources: tuple


@dataclass(frozen=True)
class SavedRun:
    source_alias: str
    source_label: str
    run_id: str
    run_label: str
    schema_version: int
    payload_text: str
    payload_sha256: str
    payload: dict
    evidence_texts: dict


@dataclass(frozen=True)
class ReadBundle:
    runs: tuple
    sources: tuple


def read_selection(path):
    path = Path(path).resolve()
    try:
        with _open_regular(path) as stream:
            content = stream.read(MAX_SELECTION_BYTES + 1)
        if len(content) > MAX_SELECTION_BYTES:
            raise ReviewError('SELECTION_LIMIT', 'selection JSON exceeds 1 MiB')
        data = strict_json(content.decode('utf-8'))
        if not isinstance(data, dict) or set(data) != {'format', 'sources'} or data['format'] != 'review-selection-v1':
            raise ValueError('expected review-selection-v1 with format and sources')
        if not isinstance(data['sources'], list) or not data['sources']:
            raise ValueError('sources must be a nonempty list')
        specs, aliases, count = [], set(), 0
        for source in data['sources']:
            if not isinstance(source, dict) or not {'alias', 'database', 'run_ids'} <= source.keys() or set(source) - {'alias', 'database', 'run_ids', 'label', 'run_labels'}:
                raise ValueError('invalid source selection fields')
            alias, database, ids = source['alias'], source['database'], source['run_ids']
            if not isinstance(alias, str) or not alias or alias in aliases:
                raise ValueError('source aliases must be distinct nonempty strings')
            if not isinstance(database, str) or not database or '\x00' in database:
                raise ValueError('database must be a literal filesystem path')
            if not isinstance(ids, list) or not ids or not all(isinstance(x, str) and x for x in ids) or len(ids) != len(set(ids)):
                raise ValueError('run_ids must be distinct nonempty strings')
            label = source.get('label', alias)
            labels = source.get('run_labels', {})
            if not isinstance(label, str) or not label or not isinstance(labels, dict) or set(labels) - set(ids) or not all(isinstance(v, str) and v for v in labels.values()):
                raise ValueError('presentation labels must be strings keyed by selected run IDs')
            resolved = Path(database)
            if not resolved.is_absolute(): resolved = path.parent / resolved
            specs.append(SourceSelection(alias, resolved.resolve(), tuple(ids), label, dict(labels)))
            aliases.add(alias); count += len(ids)
        if count > MAX_RUNS:
            raise ReviewError('RUN_LIMIT', f'at most {MAX_RUNS} selected runs are supported')
        return Selection(tuple(specs))
    except ReviewError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise ReviewError('SELECTION_INVALID', str(exc)) from exc


@contextmanager
def _open_regular(path):
    """Never follow a replacement link or block on an unexpected special file."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise OSError('a regular local file is required')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise OSError('file identity changed before opening')
        yield stream


def _file_entry(path):
    before = path.lstat()
    h = hashlib.sha256(); length = 0
    with _open_regular(path) as stream:
        for data in iter(lambda: stream.read(CHUNK_BYTES), b''):
            length += len(data); h.update(data)
    after = path.lstat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or length != after.st_size:
        raise OSError('source changed while hashing')
    return {'bytes': length, 'sha256': h.hexdigest()}


def _files(path):
    main = _file_entry(path)
    sidecars = {}
    for suffix in SIDECARS:
        candidate = Path(str(path) + suffix)
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            sidecars[suffix] = None
            continue
        if stat.S_ISREG(info.st_mode):
            sidecars[suffix] = {'kind': 'regular', **_file_entry(candidate)}
        elif stat.S_ISLNK(info.st_mode):
            sidecars[suffix] = {'kind': 'symlink', 'bytes': info.st_size,
                               'link_text_sha256': hashlib.sha256(os.fsencode(os.readlink(candidate))).hexdigest()}
        else:
            sidecars[suffix] = {'kind': 'directory' if stat.S_ISDIR(info.st_mode) else 'special', 'bytes': info.st_size}
    return {'database': main, 'sidecars': sidecars}


def _quiet(path, files):
    if any(value is not None for value in files['sidecars'].values()):
        raise ReviewError('SNAPSHOT_UNSUPPORTED', 'WAL/SHM/journal sidecar present; provide a closed rollback-journal snapshot')
    with _open_regular(path) as stream:
        header = stream.read(100)
    if len(header) != 100 or header[:16] != b'SQLite format 3\x00':
        raise ReviewError('SNAPSHOT_UNSUPPORTED', 'not a supported SQLite database file')
    if header[18:20] != b'\x01\x01':
        raise ReviewError('SNAPSHOT_UNSUPPORTED', 'WAL or unknown database header mode is not supported')



def _copy_snapshot(path, destination, expected):
    """Copy bytes, never invoke SQLite on the original (including failure paths)."""
    h = hashlib.sha256(); length = 0
    with _open_regular(path) as source, destination.open('xb') as target:
        for data in iter(lambda: source.read(CHUNK_BYTES), b''):
            target.write(data); h.update(data); length += len(data)
        target.flush(); os.fsync(target.fileno())
    copied = {'bytes': length, 'sha256': h.hexdigest()}
    if copied != expected or _file_entry(destination) != expected:
        raise ReviewError('SOURCE_CHANGED', 'copied snapshot differs from the original byte inventory')
    return copied


def _schema(db):
    version = db.execute('PRAGMA user_version').fetchone()[0]
    objects = [list(row) for row in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name')]
    tables = {row[1] for row in objects if row[0] == 'table'}
    if db.execute('PRAGMA encoding').fetchone()[0] != 'UTF-8':
        raise ReviewError('SCHEMA_UNSUPPORTED', 'only UTF-8 SQLite snapshot encoding is supported')
    if version not in (0, 2, 3):
        raise ReviewError('SCHEMA_UNSUPPORTED', 'supported physical schema versions are 0, 2 and 3')
    if 'runs' not in tables:
        raise ReviewError('SCHEMA_UNSUPPORTED', 'runs must be a real table')
    for name, required in (('runs', {'id', 'balance_at', 'knowledge_at', 'payload'}),
                           ('findings', {'run_id', 'ordinal', 'payload'}),
                           ('evidence', {'run_id', 'evidence_id', 'payload'})):
        if any(row[1] == name and row[0] != 'table' for row in objects):
            raise ReviewError('SCHEMA_UNSUPPORTED', name + ' must not be a view or virtual alias')
        if any(row[1] == name and isinstance(row[3], str) and row[3].lstrip().upper().startswith('CREATE VIRTUAL TABLE') for row in objects):
            raise ReviewError('SCHEMA_UNSUPPORTED', name + ' must not be a virtual table')
        if name in tables:
            # Names come only from this fixed tuple, never from selection input.
            columns = {r[1] for r in db.execute('PRAGMA table_info(' + name + ')')}
            if not required <= columns:
                raise ReviewError('SCHEMA_UNSUPPORTED', 'unsupported ' + name + ' columns')
    return {'user_version': version, 'objects_sha256': hashlib.sha256(canonical(objects).encode()).hexdigest()}, tables


def _inventory(db):
    """Stream every run payload into hashes; never fetch an unselected huge TEXT."""
    aggregate = hashlib.sha256(); count = 0; previous = None
    cursor = db.execute('SELECT id,balance_at,knowledge_at,length(CAST(payload AS BLOB)),typeof(payload) FROM runs ORDER BY id')
    for run_id, balance, knowledge, length, kind in cursor:
        if not isinstance(run_id, str) or kind != 'text' or type(length) is not int:
            raise ReviewError('SOURCE_INTEGRITY', 'run inventory contains a non-text ID/payload')
        if run_id == previous:
            raise ReviewError('SOURCE_INTEGRITY', 'duplicate run IDs in source inventory')
        previous = run_id
        h = hashlib.sha256()
        for offset in range(1, length + 1, CHUNK_BYTES):
            chunk = db.execute('SELECT substr(CAST(payload AS BLOB),?,?) FROM runs WHERE id=?', (offset, CHUNK_BYTES, run_id)).fetchone()[0]
            h.update(chunk)
        aggregate.update(canonical([run_id, balance, knowledge, length, h.hexdigest()]).encode() + b'\n')
        count += 1
    return {'count': count, 'sha256': aggregate.hexdigest(), 'algorithm': 'SHA-256 of ordered canonical [id,balance_at,knowledge_at,UTF8_bytes,payload_sha256] lines'}


def _parity(db, tables, run_id, payload, text):
    """Persisted mirrors, if present, must match the selected run's own snapshot."""
    if 'findings' in tables:
        rows = db.execute('SELECT ordinal,length(CAST(payload AS BLOB)),typeof(payload) FROM findings WHERE run_id=? ORDER BY ordinal', (run_id,))
        count = 0
        for ordinal, length, kind in rows:
            if kind != 'text' or type(length) is not int or length > MAX_PAYLOAD_BYTES:
                raise ValueError('persisted finding mirror exceeds the supported text budget')
            raw = db.execute('SELECT payload FROM findings WHERE run_id=? AND ordinal=?', (run_id, ordinal)).fetchone()[0]
            if ordinal != count or count >= len(payload['findings']) or canonical(strict_json(raw)) != canonical(payload['findings'][count]):
                raise ValueError('persisted finding rows differ from saved run payload')
            count += 1
        if count != len(payload['findings']):
            raise ValueError('persisted finding row count differs from saved run payload')
    evidence_texts = object_member_texts(object_member_texts(text)['evidence'])
    if 'evidence' in tables:
        seen = set()
        for key, length, kind in db.execute('SELECT evidence_id,length(CAST(payload AS BLOB)),typeof(payload) FROM evidence WHERE run_id=? ORDER BY evidence_id', (run_id,)):
            if kind != 'text' or type(length) is not int or length > MAX_PAYLOAD_BYTES:
                raise ValueError('persisted evidence mirror exceeds the supported text budget')
            raw = db.execute('SELECT payload FROM evidence WHERE run_id=? AND evidence_id=?', (run_id, key)).fetchone()[0]
            if key in seen or key not in payload['evidence'] or not isinstance(raw, str) or canonical(strict_json(raw)) != canonical(payload['evidence'][key]):
                raise ValueError('persisted evidence rows differ from saved run payload')
            seen.add(key); evidence_texts[key] = raw
        if seen != set(payload['evidence']):
            raise ValueError('persisted evidence row coverage differs from saved run payload')
    return evidence_texts


def _error(exc, source, run_id=None):
    if isinstance(exc, ReviewError):
        if exc.alias is None: exc.alias = source.alias
        if exc.run_id is None: exc.run_id = run_id
        return exc
    return ReviewError('SOURCE_READ' if isinstance(exc, (OSError, sqlite3.Error)) else 'RUN_INTEGRITY',
                       str(exc), alias=source.alias, run_id=run_id)


def read_selected_sources(selection):
    """Read one transaction per DB, with no atomic-snapshot claim across DBs."""
    if not isinstance(selection, Selection): selection = read_selection(selection)
    if sum(len(s.run_ids) for s in selection.sources) > MAX_RUNS:
        raise ReviewError('RUN_LIMIT', 'at most 100 selected runs are supported')
    handles, proofs, runs = [], [], []
    error = None; current = None; current_run = None; total_bytes = 0
    try:
        # Preflight every selected byte length before loading any selected payload.
        for source in selection.sources:
            current = source; current_run = None
            before = _files(source.database)
            item = {'source': source, 'before_files': before, 'db': None, 'schema': None, 'inventory': None, 'tables': None, 'temporary': None, 'copy': None}
            handles.append(item)
            _quiet(source.database, before)
            item['temporary'] = tempfile.TemporaryDirectory(prefix='crypto-review-snapshot-')
            copied_path = Path(item['temporary'].name) / ('snapshot-' + source.database.name)
            item['copy'] = _copy_snapshot(source.database, copied_path, before['database'])
            after_copy = _files(source.database)
            _quiet(source.database, after_copy)
            if after_copy != before:
                raise ReviewError('SOURCE_CHANGED', 'original changed while snapshot bytes were copied')
            db = sqlite3.connect(copied_path.as_uri() + '?mode=ro', uri=True, isolation_level=None, timeout=0)
            item['db'] = db
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('BEGIN')
            if db.execute('PRAGMA journal_mode').fetchone()[0].lower() != 'delete':
                raise ReviewError('SNAPSHOT_UNSUPPORTED', 'only closed rollback-journal snapshots are supported')
            item['schema'], item['tables'] = _schema(db)
            sizes = {}
            for run_id in source.run_ids:
                current_run = run_id
                row = db.execute('SELECT length(CAST(payload AS BLOB)),typeof(payload) FROM runs WHERE id=?', (run_id,)).fetchone()
                if row is None:
                    raise ReviewError('RUN_MISSING', 'selected run ID is absent')
                if row[1] != 'text' or type(row[0]) is not int:
                    raise ReviewError('RUN_INTEGRITY', 'saved payload must be SQLite TEXT')
                sizes[run_id] = row[0]; total_bytes += row[0]
                if total_bytes > MAX_PAYLOAD_BYTES:
                    raise ReviewError('PAYLOAD_LIMIT', 'selected saved payloads exceed 64 MiB')
            item['sizes'] = sizes
            item['inventory'] = _inventory(db)
        for item in handles:
            source, db = item['source'], item['db']; current = source
            for run_id in source.run_ids:
                current_run = run_id
                row = db.execute('SELECT balance_at,knowledge_at,payload FROM runs WHERE id=?', (run_id,)).fetchone()
                text = row[2]
                if len(text.encode('utf-8')) != item['sizes'][run_id]:
                    raise ReviewError('SOURCE_CHANGED', 'selected payload byte length changed')
                payload = validate_payload(text, run_id, item['schema']['user_version'], alias=source.alias)
                if (row[0], row[1]) != (payload['balance_at'], payload['knowledge_at']):
                    raise ReviewError('RUN_INTEGRITY', 'runs time columns differ from saved payload')
                evidence_texts = _parity(db, item['tables'], run_id, payload, text)
                runs.append(SavedRun(source.alias, source.label, run_id, source.run_labels.get(run_id, run_id),
                    item['schema']['user_version'], text, hashlib.sha256(text.encode('utf-8')).hexdigest(), payload, evidence_texts))
    except (ReviewError, OSError, sqlite3.Error, ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        error = _error(exc, current, current_run) if current else ReviewError('SOURCE_READ', str(exc))
    finally:
        for item in handles:
            source, db = item['source'], item['db']
            proof = {'alias': source.alias, 'label': source.label, 'run_ids': list(source.run_ids),
                     'run_labels': source.run_labels, 'before': {'files': item['before_files'], 'schema': item['schema'], 'run_inventory': item['inventory']},
                     'verified_copy': item['copy'], 'sqlite_access': 'mode=ro;query_only=ON;verified-owned-byte-copy',
                     'snapshot_boundary': 'Closed quiet local rollback-journal file; independent read transaction per source copy; no cross-database atomic snapshot claim'}
            try:
                if db is not None:
                    after_schema = _schema(db)[0] if item['schema'] is not None else None
                    after_inventory = _inventory(db) if item['inventory'] is not None else None
                    if after_schema != item['schema']:
                        raise ReviewError('SOURCE_CHANGED', 'schema changed during the read transaction')
                    if after_inventory != item['inventory']:
                        raise ReviewError('SOURCE_CHANGED', 'run inventory changed during the read transaction')
                    db.rollback(); db.close(); item['db'] = None
                after_files = _files(source.database)
                proof['after'] = {'files': after_files, 'schema': item['schema'], 'run_inventory': item['inventory']}
                proof['unchanged'] = after_files == item['before_files']
                proof['schema_version'] = item['schema']['user_version'] if item['schema'] else None
                if not proof['unchanged']:
                    raise ReviewError('SOURCE_CHANGED', 'source bytes or sidecar inventory changed during export')
            except (ReviewError, OSError, sqlite3.Error, ValueError) as exc:
                proof['unchanged'] = False; proof['audit_error'] = str(exc)
                error = ReviewError('SOURCE_CHANGED', 'source preservation could not be verified', alias=source.alias,
                                    run_id=error.run_id if error else None)
            finally:
                if item['db'] is not None:
                    item['db'].close()
                if item['temporary'] is not None:
                    item['temporary'].cleanup()
            proofs.append(proof)
    if error is not None:
        error.audit = {'sources': proofs, 'source_preservation_verified': bool(proofs) and all(p['unchanged'] for p in proofs)}
        # Rebuild exception args after attaching a previously unknown source/run.
        error.args = (f'{error.code}: {error.message} [source={error.alias}, run={error.run_id}]',)
        raise error
    return ReadBundle(tuple(runs), tuple(proofs))
