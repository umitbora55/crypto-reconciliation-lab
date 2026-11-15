"""Export one immutable run and a bounded closed SQL observation, never an evaluation."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile

from ..migrations import validate_schema
from ..review.adapter import _parity
from ..review.publication import publish_directory
from ..review.validation import ReviewError, validate_payload
from .common import (ProvenanceError, canonical, sha256, identity, is_digest, parse_json,
                     bounded_file, member_name, MAX_RUN_BYTES, MAX_CAPTURE_BYTES,
                     MAX_DATABASE_BYTES, MAX_TOTAL_BYTES, MAX_FILES, MAX_ROWS,
                     MAX_JSON_BYTES, MAX_DATA_BYTES, MAX_EPOCHS)

# SQL names are fixed by schema 5, never interpolated from a user-supplied name.
COLUMNS = {
    'records': 'id logical_key kind payload',
    'receipts': 'id receipt_hash record_id received_at raw error status',
    'admission_streams': 'stream_id input_sha256 input_bytes planned_lines framing plan_hash observed_at',
    'delivery_effects': 'stream_id sequence payload payload_sha256 core_receipt_id core_receipt_hash core_result disposition reason observed_at',
    'delivery_attempts': 'id stream_id sequence payload payload_sha256 plan_hash outcome effect_stream_id effect_sequence observed_at reason',
    'auth_configuration': 'id receiver configuration_digest initial_policy_hash',
    'auth_policy_snapshots': 'policy_hash payload',
    'auth_policy_activations': 'epoch policy_hash previous_epoch previous_hash observed_at',
    'auth_keys': 'key_id source public_key fingerprint first_epoch',
    'auth_streams': 'stream_id source receiver configuration_digest plan_hash',
    'auth_endorsements': 'id payload envelope source key_id fingerprint statement_hash snapshot_hash plan_hash',
    'auth_decisions': 'id epoch endorsement_id stream_id sequence decision current_key_status policy_hash observed_at',
    'auth_delivery_links': 'stream_id sequence decision_id core_receipt_id',
    'auth_attempt_links': 'attempt_id decision_id',
}
KEYS = {name: columns.split()[0:1] for name, columns in COLUMNS.items()}
for _name in ('delivery_effects', 'auth_delivery_links'):
    KEYS[_name] = ['stream_id', 'sequence']
SIDECARS = ('-wal', '-shm', '-journal')


def _require(condition, code, message):
    if not condition:
        raise ProvenanceError(code, message)


def _token(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def _state(path):
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= MAX_DATABASE_BYTES,
             'PROVENANCE_SNAPSHOT', 'bounded regular closed database required')
    for suffix in SIDECARS:
        _require(not os.path.lexists(str(path) + suffix), 'PROVENANCE_SNAPSHOT', 'WAL/SHM/journal sidecar is present')
    h, length = hashlib.sha256(), 0
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        _require(_token(os.fstat(stream.fileno())) == _token(before), 'PROVENANCE_SOURCE_CHANGED', 'database replaced before read')
        header = stream.read(100)
        _require(len(header) == 100 and header[:16] == b'SQLite format 3\0' and header[18:20] == b'\1\1',
                 'PROVENANCE_SNAPSHOT', 'closed rollback-journal SQLite file required')
        h.update(header); length += len(header)
        while chunk := stream.read(64 * 1024):
            length += len(chunk)
            _require(length <= MAX_DATABASE_BYTES, 'PROVENANCE_LIMIT', 'database grew beyond byte limit')
            h.update(chunk)
        _require(_token(os.fstat(stream.fileno())) == _token(before), 'PROVENANCE_SOURCE_CHANGED', 'database changed during read')
    _require(_token(path.lstat()) == _token(before) and length == before.st_size,
             'PROVENANCE_SOURCE_CHANGED', 'database changed while hashing')
    for suffix in SIDECARS:
        _require(not os.path.lexists(str(path) + suffix), 'PROVENANCE_SOURCE_CHANGED', 'database sidecar appeared')
    return {'database': {'bytes': length, 'sha256': h.hexdigest()}, 'filesystem': _token(before),
            'sidecars': {suffix: None for suffix in SIDECARS}}


@contextmanager
def _closed_read(path):
    before = _state(path)
    with tempfile.TemporaryDirectory(prefix='crypto-provenance-capture-') as temporary:
        copied = Path(temporary) / 'capture.sqlite'
        h, length = hashlib.sha256(), 0
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(descriptor, 'rb') as source, copied.open('xb') as target:
            _require(_token(os.fstat(source.fileno())) == before['filesystem'], 'PROVENANCE_SOURCE_CHANGED', 'database replaced before copy')
            while chunk := source.read(64 * 1024):
                length += len(chunk)
                _require(length <= MAX_DATABASE_BYTES, 'PROVENANCE_LIMIT', 'copy byte limit exceeded')
                h.update(chunk); target.write(chunk)
            target.flush(); os.fsync(target.fileno())
        _require({'bytes': length, 'sha256': h.hexdigest()} == before['database'] and _state(path) == before,
                 'PROVENANCE_SOURCE_CHANGED', 'copied database differs from original observation')
        db = sqlite3.connect(copied.as_uri() + '?mode=ro', uri=True, isolation_level=None, timeout=0)
        db.row_factory = sqlite3.Row
        try:
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_CAPTURE_BYTES)
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('BEGIN')
            _require(db.execute('PRAGMA user_version').fetchone()[0] == 5,
                     'PROVENANCE_SCHEMA', 'only closed schema-5 captures are supported; no migration is performed')
            _require(db.execute('PRAGMA encoding').fetchone()[0] == 'UTF-8', 'PROVENANCE_SCHEMA', 'UTF-8 database encoding required')
            _require(db.execute('PRAGMA journal_mode').fetchone()[0].lower() == 'delete', 'PROVENANCE_SNAPSHOT', 'rollback-journal mode required')
            _require([tuple(row) for row in db.execute('PRAGMA quick_check(10)')] == [('ok',)], 'PROVENANCE_SCHEMA', 'database integrity check failed')
            # This existing function only reads schema metadata. No migration or
            # Store initialization function is called on either file.
            validate_schema(db, 5)
            extra = {'configuration': 'id payload', 'runs': 'id balance_at knowledge_at payload',
                     'findings': 'run_id ordinal payload', 'evidence': 'run_id evidence_id payload',
                     'correction_groups': 'run_id group_id correction_record_id target_record_id payload',
                     'correction_effects': 'run_id group_id ordinal payload'}
            for table, columns in {**COLUMNS, **extra}.items():
                row = db.execute('SELECT type,sql FROM sqlite_master WHERE name=?', (table,)).fetchone()
                _require(row is not None and row['type'] == 'table' and row['sql'] and not row['sql'].lstrip().upper().startswith('CREATE VIRTUAL'),
                         'PROVENANCE_SCHEMA', 'a required table is absent or virtual: ' + table)
                _require([r['name'] for r in db.execute('PRAGMA table_info(' + table + ')')] == columns.split(),
                         'PROVENANCE_SCHEMA', 'unsupported column layout: ' + table)
            yield db, before
        finally:
            db.close()
            _require(_state(path) == before, 'PROVENANCE_SOURCE_CHANGED', 'original database or sidecar inventory changed')


def _scope(run):
    """Exporter traversal; the verifier has a separate, independently checked traversal."""
    records, hashes = set(), set()
    for eid, entry in run['evidence'].items():
        if 'record' in entry:
            _require(is_digest(eid) and sha256(canonical(entry['record'])) == eid,
                     'PROVENANCE_SCOPE', 'saved record content identity differs')
            records.add(eid)
            hashes.update(entry['receipt_ids'])
        elif 'receipt' in entry:
            _require(is_digest(eid) and sha256(canonical(entry['receipt'])) == eid,
                     'PROVENANCE_SCOPE', 'saved raw receipt identity differs')
            hashes.add(eid)
        elif 'quarantined_receipt' in entry:
            bad = entry['quarantined_receipt']
            _require(is_digest(eid) and bad.get('id') == eid and
                     sha256(canonical({'record': bad.get('record'), 'received_at': bad.get('received_at')})) == eid,
                     'PROVENANCE_SCOPE', 'saved quarantined receipt identity differs')
            hashes.add(eid)
    _require(all(is_digest(key) for key in hashes), 'PROVENANCE_SCOPE', 'invalid required receipt hash')
    return sorted(records), sorted(hashes)


def _projection(db, run, before):
    record_ids, hashes = _scope(run)
    rows_used, bytes_used = 0, 0
    def rows(table, where='', parameters=()):
        nonlocal rows_used, bytes_used
        query = 'SELECT * FROM ' + table + (' WHERE ' + where if where else '') + ' ORDER BY ' + ','.join(KEYS[table])
        result = []
        for raw in db.execute(query, parameters):
            row = {}
            for name in raw.keys():
                value = raw[name]
                _require(value is None or type(value) in (int, str, bytes), 'PROVENANCE_SCHEMA', 'unsupported SQL value type')
                row[name] = value.hex() if type(value) is bytes else value
            rows_used += 1; bytes_used += len(canonical(row))
            _require(rows_used <= MAX_ROWS and bytes_used <= MAX_CAPTURE_BYTES,
                     'PROVENANCE_LIMIT', 'projection row/byte limit exceeded')
            result.append(row)
        return result
    tables = {name: [] for name in COLUMNS}
    for key in record_ids:
        selected = rows('records', 'id=?', (key,))
        _require(len(selected) == 1, 'PROVENANCE_SCOPE', 'required saved record missing from capture')
        row = selected[0]; entry = run['evidence'][key]
        _require(parse_json(row['payload'].encode()) == entry['record'] and row['logical_key'] == entry['logical_key'],
                 'PROVENANCE_SCOPE', 'saved/capture record evidence differs')
        tables['records'].extend(selected)
    for receipt_hash in hashes:
        # Every physical candidate, without an ORDER/LIMIT preference.
        tables['receipts'].extend(rows('receipts', 'receipt_hash=?', (receipt_hash,)))
    for receipt in tables['receipts']:
        tables['delivery_effects'].extend(rows('delivery_effects', 'core_receipt_id=?', (receipt['id'],)))
    streams = sorted({r['stream_id'] for r in tables['delivery_effects']})
    for stream in streams:
        tables['admission_streams'].extend(rows('admission_streams', 'stream_id=?', (stream,)))
        tables['auth_streams'].extend(rows('auth_streams', 'stream_id=?', (stream,)))
    for effect in tables['delivery_effects']:
        key = (effect['stream_id'], effect['sequence'])
        tables['delivery_attempts'].extend(rows('delivery_attempts', 'stream_id=? AND sequence=?', key))
        tables['auth_delivery_links'].extend(rows('auth_delivery_links', 'stream_id=? AND sequence=?', key))
    for attempt in tables['delivery_attempts']:
        tables['auth_attempt_links'].extend(rows('auth_attempt_links', 'attempt_id=?', (attempt['id'],)))
    decisions = sorted({r['decision_id'] for name in ('auth_delivery_links', 'auth_attempt_links') for r in tables[name]})
    for decision in decisions:
        tables['auth_decisions'].extend(rows('auth_decisions', 'id=?', (decision,)))
    for eid in sorted({row['endorsement_id'] for row in tables['auth_decisions']}):
        tables['auth_endorsements'].extend(rows('auth_endorsements', 'id=?', (eid,)))
    tables['auth_configuration'] = rows('auth_configuration')
    tables['auth_policy_activations'] = rows('auth_policy_activations')
    _require(len(tables['auth_policy_activations']) <= MAX_EPOCHS, 'PROVENANCE_LIMIT', 'policy epoch limit exceeded')
    tables['auth_keys'] = rows('auth_keys')
    for policy_hash in sorted({r['policy_hash'] for r in tables['auth_policy_activations']}):
        tables['auth_policy_snapshots'].extend(rows('auth_policy_snapshots', 'policy_hash=?', (policy_hash,)))
    for name, values in tables.items():
        values.sort(key=lambda r: tuple(r[k] for k in KEYS[name]))
    configuration = db.execute('SELECT payload FROM configuration WHERE id=1').fetchone()
    _require(configuration is not None, 'PROVENANCE_SCHEMA', 'configuration is absent')
    config = parse_json(configuration['payload'].encode())
    _require(config == run['configuration'], 'PROVENANCE_RUN', 'capture/run configuration differs')
    return {'format': 'run-provenance-capture-v1', 'schema_version': 5,
            'database': before['database'], 'configuration': config, 'tables': tables}, record_ids, hashes


def _correction_mirrors(db, run_id, run):
    expected = {g['id']: g for ledger in run['ledgers'].values() for g in ledger.get('correction_groups', [])}
    actual = {}
    for row in db.execute('SELECT * FROM correction_groups WHERE run_id=? ORDER BY group_id', (run_id,)):
        _require(row['group_id'] not in actual, 'PROVENANCE_RUN', 'duplicate correction mirror')
        group = parse_json(row['payload'].encode())
        _require(group == expected.get(row['group_id']) and row['correction_record_id'] == group['correction_record_id']
                 and row['target_record_id'] == group['target_record_id'], 'PROVENANCE_RUN', 'correction mirror differs')
        actual[row['group_id']] = group
    _require(set(actual) == set(expected), 'PROVENANCE_RUN', 'correction mirror coverage differs')
    effects = [(gid, ordinal, effect) for gid, group in sorted(expected.items()) for ordinal, effect in enumerate(group['effects'])]
    observed = [(r['group_id'], r['ordinal'], parse_json(r['payload'].encode())) for r in db.execute(
        'SELECT group_id,ordinal,payload FROM correction_effects WHERE run_id=? ORDER BY group_id,ordinal', (run_id,))]
    _require(observed == effects, 'PROVENANCE_RUN', 'correction effect mirrors differ')


def export_provenance(db, run_id, materials, output):
    """Create a new immutable package; no expectations or verified claim are emitted."""
    database = Path(db).absolute()
    material_root = Path(materials).absolute()
    destination = Path(output).absolute()
    _require(is_digest(run_id), 'PROVENANCE_RUN', 'exact run digest required')
    _require(material_root.is_dir() and not material_root.is_symlink(), 'PROVENANCE_PATH', 'regular material directory required')
    _require(not os.path.lexists(destination), 'PROVENANCE_OUTPUT', 'output already exists')
    _require(not destination.resolve().is_relative_to(material_root.resolve()), 'PROVENANCE_OUTPUT', 'output must be outside source materials')
    # Creating an output parent can itself create a SQLite sidecar path. Guard
    # the whole destination ancestry before mkdir or atomic publication.
    resolved_output = destination.resolve()
    protected_paths = [database, *(Path(str(database) + suffix) for suffix in SIDECARS)]
    _require(not any(resolved_output.is_relative_to(path.resolve()) for path in protected_paths),
             'PROVENANCE_OUTPUT', 'output overlaps source database or sidecar namespace')
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = None
    try:
        with _closed_read(database) as (connection, before):
            header = connection.execute('SELECT length(CAST(payload AS BLOB)),typeof(payload),balance_at,knowledge_at FROM runs WHERE id=?', (run_id,)).fetchall()
            _require(len(header) == 1 and header[0][1] == 'text' and 0 < header[0][0] <= MAX_RUN_BYTES,
                     'PROVENANCE_RUN', 'one bounded saved TEXT run is required')
            raw_run = bytes(connection.execute('SELECT CAST(payload AS BLOB) FROM runs WHERE id=?', (run_id,)).fetchone()[0])
            parse_json(raw_run, MAX_RUN_BYTES)
            run = validate_payload(raw_run.decode('utf-8'), run_id, 5)
            _require((header[0][2], header[0][3]) == (run['balance_at'], run['knowledge_at']), 'PROVENANCE_RUN', 'run SQL time columns differ')
            _parity(connection, {'findings', 'evidence'}, run_id, run, raw_run.decode('utf-8'))
            _correction_mirrors(connection, run_id, run)
            capture, records, hashes = _projection(connection, run, before)
        raw_capture = canonical(capture)
        parse_json(raw_capture, MAX_CAPTURE_BYTES)
        report = {'format': 'run-provenance-report-v1', 'run_id': run_id,
                  'run_payload_sha256': sha256(raw_run), 'capture_digest': sha256(raw_capture),
                  'configuration_digest': sha256(canonical(run['configuration'])),
                  'capture_profile': 'protected' if capture['tables']['auth_configuration'] else 'legacy',
                  'record_ids': records, 'receipt_hashes': hashes,
                  'findings': [{'id': run_id + ':' + str(i), 'ordinal': i,
                                **{k: finding[k] for k in ('comparison', 'asset', 'scope', 'evidence_ids')}}
                               for i, finding in enumerate(run['findings'])],
                  'run_creation_authorization_cut': 'NOT_RECORDED',
                  'financial_recomputation': 'NOT_PERFORMED', 'source_verification': 'NOT_PERFORMED'}
        members = {'run.json': raw_run, 'capture.json': raw_capture, 'report.json': canonical(report)}
        def material(name, data, limit):
            _require(0 < len(data) <= limit, 'PROVENANCE_LIMIT', 'source material byte limit exceeded')
            _require(name in members or len(members) + 6 < MAX_FILES, 'PROVENANCE_LIMIT', 'material member limit exceeded')
            _require(sum(map(len, members.values())) + (0 if name in members else len(data)) <= MAX_TOTAL_BYTES,
                     'PROVENANCE_LIMIT', 'source material total byte limit exceeded')
            members[name] = data
        for row in capture['tables']['auth_policy_snapshots']:
            _require(is_digest(row['policy_hash']), 'PROVENANCE_PATH', 'invalid policy material identity')
            material('materials/policies/' + row['policy_hash'] + '.json', row['payload'].encode('utf-8'), 128 * 1024)
        for row in capture['tables']['auth_endorsements']:
            _require(is_digest(row['id']) and is_digest(row['snapshot_hash']), 'PROVENANCE_PATH', 'invalid endorsement material identity')
            material('materials/envelopes/' + row['id'] + '.json', bytes.fromhex(row['envelope']), 128 * 1024)
            relative = 'snapshots/' + row['snapshot_hash'] + '.jsonl'
            path = material_root / relative
            if 'materials/' + relative not in members and os.path.lexists(path):
                _require(len(members) + 6 < MAX_FILES, 'PROVENANCE_LIMIT', 'material member limit exceeded')
                _require(not path.parent.is_symlink() and path.resolve().is_relative_to(material_root.resolve()),
                         'PROVENANCE_PATH', 'snapshot material escapes directory')
                material('materials/' + relative, bounded_file(path, 16 * 1024 * 1024), 16 * 1024 * 1024)
        from .ui import render_page
        material_inventory = {name: identity(data) for name, data in members.items() if name.startswith('materials/')}
        members.update(render_page(run, report, capture, material_inventory))
        _require(len(members) + 1 <= MAX_FILES and sum(map(len, members.values())) <= MAX_TOTAL_BYTES,
                 'PROVENANCE_LIMIT', 'bundle count/byte limit exceeded')
        for name, data in members.items():
            member_name(name)
            cap = MAX_DATA_BYTES if name == 'data.js' else MAX_CAPTURE_BYTES if name == 'capture.json' else 16 * 1024 * 1024 if name.endswith('.jsonl') else MAX_JSON_BYTES
            _require(0 < len(data) <= cap, 'PROVENANCE_LIMIT', 'member byte limit exceeded: ' + name)
        manifest = {'format': 'run-provenance-bundle-v1', 'run_id': run_id,
                    'files': {name: identity(data) for name, data in sorted(members.items())}}
        manifest_raw = canonical(manifest)
        _require(sum(map(len, members.values())) + len(manifest_raw) <= MAX_TOTAL_BYTES, 'PROVENANCE_LIMIT', 'total bundle byte limit exceeded')
        staged = Path(tempfile.mkdtemp(prefix='.' + destination.name + '-provenance-', dir=destination.parent))
        for name, data in {**members, 'manifest.json': manifest_raw}.items():
            target = staged / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(data)
        _require(_state(database) == before, 'PROVENANCE_SOURCE_CHANGED', 'database changed before publication')
        _require(not os.path.lexists(destination), 'PROVENANCE_OUTPUT', 'output appeared before publication')
        publish_directory(staged, destination)
        staged = None
        return {'status': 'CREATED', 'run_id': run_id, 'output': str(destination),
                'bundle_digest': sha256(manifest_raw), 'capture_digest': sha256(raw_capture),
                'source_preservation': {'status': 'PASS', **before},
                'run_creation_authorization_cut': 'NOT_RECORDED',
                'financial_recomputation': 'NOT_PERFORMED', 'source_verification': 'NOT_PERFORMED'}
    except (ReviewError, sqlite3.Error, OSError, ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, ProvenanceError):
            raise
        raise ProvenanceError('PROVENANCE_EXPORT', str(exc)) from exc
    finally:
        if staged is not None:
            shutil.rmtree(staged)
