"""Explicit additive schema migrations, verified SQLite backups and bounded audits."""
import hashlib
import json
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from .model import digest

LEGACY_TABLES = ("configuration", "records", "receipts", "runs", "findings", "evidence")
SCHEMA_VERSION = 3
INDEX_NAME = "receipts_hash_lookup"
INDEX_SQL = "CREATE INDEX receipts_hash_lookup ON receipts(receipt_hash)"
MIGRATIONS = {
    2: "Add immutable correction groups/effects; retain all Stage 1 columns",
    3: "Add nonunique receipts_hash_lookup(receipt_hash); preserve all financial data",
}


def inject(fault, point):
    if fault:
        fault(point)


@contextmanager
def transaction(db):
    """Explicit SQL transaction; isolation_level=None on owned connections."""
    if db.in_transaction:
        raise ValueError("nested transaction not supported")
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def schema_snapshot(db):
    return [list(r) for r in db.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name")]


def _cell(value):
    # Type tags preserve SQLite storage classes and BLOBs without loading a table.
    if value is None:
        return ['null', None]
    if isinstance(value, bytes):
        return ['blob', value.hex()]
    if isinstance(value, int):
        return ['integer', str(value)]
    if isinstance(value, float):
        return ['real', value.hex()]
    return ['text', value]


def table_snapshot(db, table, *, exclude_new_migration=False):
    columns = [list(r) for r in db.execute('PRAGMA table_xinfo(' + quoted(table) + ')')]
    names = [r[1] for r in columns if r[6] != 1]
    order = ','.join('typeof(' + quoted(n) + '),' + quoted(n) + ' COLLATE BINARY' for n in names)
    sql = 'SELECT * FROM ' + quoted(table)
    if exclude_new_migration:
        sql += ' WHERE version<>3'
    if order:
        sql += ' ORDER BY ' + order
    h = hashlib.sha256()
    count = 0
    for row in db.execute(sql):
        raw = json.dumps([_cell(v) for v in row], ensure_ascii=True, separators=(',', ':')).encode()
        h.update(len(raw).to_bytes(8, 'big')); h.update(raw)
        count += 1
    return dict(columns=columns, rows=count, sha256=h.hexdigest(),
                foreign_keys=[list(r) for r in db.execute('PRAGMA foreign_key_list(' + quoted(table) + ')')])


def application_snapshot(db):
    """Stream ordered rows; include every existing table, object and foreign key."""
    objects = [list(r) for r in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name')]
    return dict(user_version=db.execute('PRAGMA user_version').fetchone()[0], objects=objects,
                tables={r[1]: table_snapshot(db, r[1]) for r in objects if r[0] == 'table'})


def logical_snapshot(db):
    """Compatibility name: bounded summaries now cover all application tables."""
    return application_snapshot(db)['tables']


def assert_preserved(db, before):
    current_objects = {tuple(r) for r in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master')}
    for obj in before['objects']:
        require(tuple(obj) in current_objects, 'migration changed an existing schema object: ' + obj[1])
    preserved = {}
    for name, expected in before['tables'].items():
        actual = table_snapshot(db, name, exclude_new_migration=(name == 'schema_migrations' and before['user_version'] == 2))
        require(actual == expected, 'migration changed existing rows/columns/foreign keys: ' + name)
        preserved[name] = actual
    return preserved


def index_inventory(db):
    listing = [list(r) for r in db.execute('PRAGMA index_list(receipts)')]
    return dict(sqlite_version=sqlite3.sqlite_version, index_list=listing,
        indexes={r[1]: dict(info=[list(x) for x in db.execute('PRAGMA index_info(' + quoted(r[1]) + ')')],
                           xinfo=[list(x) for x in db.execute('PRAGMA index_xinfo(' + quoted(r[1]) + ')')]) for r in listing},
        sqlite_master=[list(r) for r in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE tbl_name='receipts' OR name=? ORDER BY type,name", (INDEX_NAME,))])


def query_plans(db, hashes):
    return {name: [list(r) for r in db.execute('EXPLAIN QUERY PLAN SELECT raw FROM receipts WHERE receipt_hash=? LIMIT 1', (value,))]
            for name, value in hashes.items()}


def validate_index(db, *, required=True):
    obj = db.execute('SELECT type,tbl_name FROM sqlite_master WHERE name=? COLLATE NOCASE', (INDEX_NAME,)).fetchone()
    if obj is None:
        require(not required, 'SCHEMA_INVALID: required receipts_hash_lookup index is absent')
        return False
    require(tuple(obj) == ('index', 'receipts'), 'SCHEMA_INVALID: receipts_hash_lookup names the wrong object/table')
    listing = next((r for r in db.execute('PRAGMA index_list(receipts)') if r[1] == INDEX_NAME), None)
    require(listing is not None and listing[2] == 0 and listing[3] == 'c' and listing[4] == 0,
            'SCHEMA_INVALID: receipts_hash_lookup must be nonunique and nonpartial')
    columns = [r for r in db.execute('PRAGMA index_xinfo(' + quoted(INDEX_NAME) + ')') if r[5] == 1]
    require(len(columns) == 1 and columns[0][2] == 'receipt_hash' and columns[0][1] >= 0
            and columns[0][3] == 0 and columns[0][4] == 'BINARY',
            'SCHEMA_INVALID: receipts_hash_lookup must index only receipt_hash with BINARY ascending order')
    return True


def _validate_metadata(db, version):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    require(set(LEGACY_TABLES) | {'schema_migrations', 'correction_groups', 'correction_effects'} <= tables,
            'SCHEMA_INVALID: required application tables are missing')
    rows = [tuple(r) for r in db.execute('SELECT version,description FROM schema_migrations ORDER BY version')]
    wanted = [(n, MIGRATIONS[n]) for n in (2, 3) if n <= version]
    require(rows == wanted, 'SCHEMA_INVALID: migration metadata differs from physical version')


def validate_current(db):
    require(db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION,
            'MIGRATION_REQUIRED: use migrate with a backup directory before creating new evaluations')
    _validate_metadata(db, SCHEMA_VERSION)
    validate_index(db)
    return True


def validate_open(db):
    version = db.execute('PRAGMA user_version').fetchone()[0]
    require(version in (0, 2, 3), 'unsupported schema version: ' + str(version))
    if version == 3:
        validate_current(db)
    elif version == 2:
        _validate_metadata(db, 2)
    return version


def _stage2(db, fault):
    # The historical unversioned -> 2 definitions and row 2 description are unchanged.
    db.execute('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, description TEXT NOT NULL)')
    db.execute('''CREATE TABLE correction_groups (
            run_id TEXT NOT NULL REFERENCES runs(id), group_id TEXT NOT NULL,
            correction_record_id TEXT NOT NULL REFERENCES records(id),
            target_record_id TEXT NOT NULL REFERENCES records(id), payload TEXT NOT NULL,
            PRIMARY KEY(run_id,group_id))''')
    inject(fault, 'migration_after_group_table')
    db.execute('''CREATE TABLE correction_effects (
            run_id TEXT NOT NULL, group_id TEXT NOT NULL, ordinal INTEGER NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(run_id,group_id,ordinal),
            FOREIGN KEY(run_id,group_id) REFERENCES correction_groups(run_id,group_id))''')
    for table in ('schema_migrations', 'correction_groups', 'correction_effects'):
        for action in ('UPDATE', 'DELETE'):
            db.execute(f"CREATE TRIGGER immutable_{table}_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'append-only table'); END")
    db.execute('INSERT INTO schema_migrations VALUES (?,?)', (2, MIGRATIONS[2]))
    db.execute('PRAGMA user_version=2')
    inject(fault, 'migration_after_schema2')


def migrate_connection(db, fault=None, *, timings=None, expected_snapshot=None):
    current = db.execute('PRAGMA user_version').fetchone()[0]
    if current == SCHEMA_VERSION:
        validate_current(db)
        return False
    require(current in (0, 2), 'unsupported schema version: ' + str(current))
    require(not db.in_transaction, 'nested transaction not supported')
    timings = {} if timings is None else timings
    started = time.perf_counter()
    db.execute('BEGIN IMMEDIATE')
    try:
        phase = time.perf_counter()
        before = application_snapshot(db)
        if expected_snapshot is not None:
            require(before == expected_snapshot, 'source changed after verified backup')
        if current == 2:
            _validate_metadata(db, 2)
        timings['preservation_before_seconds'] = time.perf_counter() - phase
        if current == 0:
            _stage2(db, fault)
        inject(fault, 'migration_before_index')
        phase = time.perf_counter()
        if not validate_index(db, required=False):
            db.execute(INDEX_SQL)
        timings['index_create_seconds'] = time.perf_counter() - phase
        inject(fault, 'migration_after_index')
        db.execute('INSERT INTO schema_migrations VALUES (?,?)', (3, MIGRATIONS[3]))
        db.execute('PRAGMA user_version=3')
        phase = time.perf_counter()
        assert_preserved(db, before)
        validate_current(db)
        require(not db.execute('PRAGMA foreign_key_check').fetchall(), 'foreign key check failed')
        timings['preservation_after_seconds'] = time.perf_counter() - phase
        inject(fault, 'migration_before_commit')
        phase = time.perf_counter(); db.execute('COMMIT')
        timings['commit_seconds'] = time.perf_counter() - phase
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise
    finally:
        timings['transaction_total_seconds'] = time.perf_counter() - started
    return True


def backup_database(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    require(source.is_file(), 'backup source does not exist')
    require(not destination.exists(), 'backup destination must be new; never overwrite an existing backup')
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, isolation_level=None)
    dst = sqlite3.connect(destination, isolation_level=None)
    try:
        src.backup(dst)
        require(dst.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'backup integrity check failed')
    finally:
        dst.close(); src.close()


def migrate_database(path, backup_dir, fault=None):
    """Explicit backup + file-copy rehearsal + one atomic source transaction."""
    started = time.perf_counter(); timings = {}
    path, folder = Path(path).resolve(), Path(backup_dir).resolve()
    require(path.is_file(), 'database does not exist')
    db = sqlite3.connect(path, isolation_level=None); db.execute('PRAGMA foreign_keys=ON')
    try:
        phase = time.perf_counter(); before = application_snapshot(db)
        version = before['user_version']; validate_open(db)
        timings['initial_preservation_seconds'] = time.perf_counter() - phase
        if version == SCHEMA_VERSION:
            return dict(status='ALREADY_CURRENT', schema_version=version, logical_digest=digest(before), timings=timings)
        folder.mkdir(parents=True, exist_ok=True)
        prefix = f'{path.stem}-{digest(before)[:16]}'
        backup = folder / (prefix + ('.stage1.sqlite3' if version == 0 else '.schema2.sqlite3'))
        phase = time.perf_counter()
        if not backup.exists():
            backup_database(path, backup)
        saved = sqlite3.connect(backup.resolve().as_uri() + '?mode=ro', uri=True, isolation_level=None)
        try:
            require(application_snapshot(saved) == before, 'existing backup does not match source data/schema/version')
            require(saved.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'backup integrity check failed')
        finally:
            saved.close()
        timings['backup_seconds'] = time.perf_counter() - phase
        phase = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix='migration-owned-', dir=folder) as directory:
            trial_path = Path(directory) / 'trial.sqlite3'; restored_path = Path(directory) / 'restored.sqlite3'
            backup_database(backup, trial_path)
            trial = sqlite3.connect(trial_path, isolation_level=None); trial.execute('PRAGMA foreign_keys=ON')
            try:
                def fail(point):
                    if point == 'migration_before_commit':
                        raise RuntimeError('controlled migration failure')
                try:
                    migrate_connection(trial, fail)
                except RuntimeError as exc:
                    require(str(exc) == 'controlled migration failure', 'unexpected rehearsal failure')
                else:
                    raise ValueError('rollback rehearsal did not fail')
                require(application_snapshot(trial) == before, 'trial rollback changed data/schema/version')
                migrate_connection(trial)
                assert_preserved(trial, before)
                require(not migrate_connection(trial), 'migration was not idempotent')
                require(trial.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'trial integrity check failed')
                require(not trial.execute('PRAGMA foreign_key_check').fetchall(), 'trial foreign key check failed')
            finally:
                trial.close()
            # Restore only to a separate, new owned target; no destructive downgrade.
            backup_database(backup, restored_path)
            restored = sqlite3.connect(restored_path, isolation_level=None)
            try:
                require(application_snapshot(restored) == before, 'restored backup differs from starting state')
            finally:
                restored.close()
        timings['copy_verification_seconds'] = time.perf_counter() - phase
        phase = time.perf_counter(); source_timings = {}
        migrate_connection(db, fault, timings=source_timings, expected_snapshot=before)
        timings['source_migration_seconds'] = time.perf_counter() - phase
        timings['source_transaction'] = source_timings
        after = assert_preserved(db, before)
        integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
        foreign_keys = [list(r) for r in db.execute('PRAGMA foreign_key_check')]
        require(integrity == 'ok' and not foreign_keys, 'migrated database integrity failure')
        timings['total_seconds'] = time.perf_counter() - started
        old_digest = digest(before['tables'])
        return dict(status='MIGRATED', from_version=version, schema_version=SCHEMA_VERSION,
            backup=str(backup), before_digest=old_digest, after_digest=digest(after),
            rows={name: data['rows'] for name, data in before['tables'].items()},
            all_old_columns_equal=True, all_old_tables_equal=True, all_old_objects_equal=True,
            copy_rollback_verified=True, copy_restore_verified=True, idempotency_verified=True,
            integrity_check=integrity, foreign_key_check=foreign_keys, preserved_snapshot=before,
            index=index_inventory(db), timings=timings)
    finally:
        db.close()
