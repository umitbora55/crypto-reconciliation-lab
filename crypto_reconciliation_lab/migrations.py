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
SCHEMA_VERSION = 6
INDEX_NAME = "receipts_hash_lookup"
INDEX_SQL = "CREATE INDEX receipts_hash_lookup ON receipts(receipt_hash)"
MIGRATIONS = {
    2: "Add immutable correction groups/effects; retain all Stage 1 columns",
    3: "Add nonunique receipts_hash_lookup(receipt_hash); preserve all financial data",
    4: "Add immutable admission streams, delivery effects and attempts; preserve financial history",
    5: "Add immutable source authority, policy epochs and atomic admission links; preserve financial history",
    6: "Add immutable recorded execution contexts and local request bindings; preserve financial history",
}

# Required historical definitions are independent of the current Store initializer.
# Validation is read-only and permits unrelated extension objects.
FINANCIAL_TABLES = {
    'configuration': 'CREATE TABLE configuration (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)',
    'records': '''CREATE TABLE records (
 id TEXT PRIMARY KEY, logical_key TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL
)''',
    'receipts': '''CREATE TABLE receipts (
 id INTEGER PRIMARY KEY, receipt_hash TEXT NOT NULL, record_id TEXT REFERENCES records(id),
 received_at TEXT, raw TEXT NOT NULL, error TEXT, status TEXT NOT NULL
)''',
    'runs': 'CREATE TABLE runs (id TEXT PRIMARY KEY, balance_at TEXT NOT NULL, knowledge_at TEXT NOT NULL, payload TEXT NOT NULL)',
    'findings': 'CREATE TABLE findings (run_id TEXT NOT NULL REFERENCES runs(id), ordinal INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(run_id, ordinal))',
    'evidence': 'CREATE TABLE evidence (run_id TEXT NOT NULL REFERENCES runs(id), evidence_id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(run_id, evidence_id))',
}
FINANCIAL_INDEXES = {
    'receipts_time': 'CREATE INDEX receipts_time ON receipts(received_at)',
    'records_key': 'CREATE INDEX records_key ON records(logical_key)',
}
CORRECTION_TABLES = {
    'schema_migrations': 'CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, description TEXT NOT NULL)',
    'correction_groups': '''CREATE TABLE correction_groups (
            run_id TEXT NOT NULL REFERENCES runs(id), group_id TEXT NOT NULL,
            correction_record_id TEXT NOT NULL REFERENCES records(id),
            target_record_id TEXT NOT NULL REFERENCES records(id), payload TEXT NOT NULL,
            PRIMARY KEY(run_id,group_id))''',
    'correction_effects': '''CREATE TABLE correction_effects (
            run_id TEXT NOT NULL, group_id TEXT NOT NULL, ordinal INTEGER NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(run_id,group_id,ordinal),
            FOREIGN KEY(run_id,group_id) REFERENCES correction_groups(run_id,group_id))''',
}


def _immutable_triggers(tables):
    return {f'immutable_{table}_{action}':
            f"CREATE TRIGGER immutable_{table}_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'append-only table'); END"
            for table in tables for action in ('UPDATE', 'DELETE')}


FINANCIAL_TRIGGERS = _immutable_triggers(FINANCIAL_TABLES)
CORRECTION_TRIGGERS = _immutable_triggers(CORRECTION_TABLES)
EXECUTION_TABLES = {
    'execution_contexts': '''CREATE TABLE execution_contexts (
        context_hash TEXT PRIMARY KEY NOT NULL CHECK(typeof(context_hash)='text' AND length(context_hash)=64 AND context_hash NOT GLOB '*[^0-9a-f]*'),
        format TEXT NOT NULL CHECK(typeof(format)='text' AND format='recorded-execution-v1'),
        payload BLOB NOT NULL CHECK(typeof(payload)='blob' AND length(payload) BETWEEN 1 AND 16777216))''',
    'recorded_executions': '''CREATE TABLE recorded_executions (
        execution_id TEXT PRIMARY KEY NOT NULL CHECK(typeof(execution_id)='text' AND length(execution_id)=64 AND execution_id NOT GLOB '*[^0-9a-f]*'),
        request_id TEXT NOT NULL UNIQUE CHECK(typeof(request_id)='text' AND length(request_id) BETWEEN 1 AND 128
            AND request_id NOT GLOB '*[^A-Za-z0-9_.:-]*' AND substr(request_id,1,1) GLOB '[A-Za-z0-9]'),
        request_fingerprint TEXT NOT NULL CHECK(typeof(request_fingerprint)='text' AND length(request_fingerprint)=64 AND request_fingerprint NOT GLOB '*[^0-9a-f]*'),
        request_payload BLOB NOT NULL CHECK(typeof(request_payload)='blob' AND length(request_payload) BETWEEN 1 AND 16384),
        run_id TEXT NOT NULL REFERENCES runs(id) CHECK(typeof(run_id)='text' AND length(run_id)=64 AND run_id NOT GLOB '*[^0-9a-f]*'),
        run_payload_sha256 TEXT NOT NULL CHECK(typeof(run_payload_sha256)='text' AND length(run_payload_sha256)=64 AND run_payload_sha256 NOT GLOB '*[^0-9a-f]*'),
        context_hash TEXT NOT NULL UNIQUE REFERENCES execution_contexts(context_hash))''',
}
EXECUTION_INDEXES = {
    'recorded_executions_run': 'CREATE INDEX recorded_executions_run ON recorded_executions(run_id,execution_id)',
}
EXECUTION_TRIGGERS = _immutable_triggers(EXECUTION_TABLES)

# These additive definitions deliberately leave every financial table/index alone.
# Exact byte hashes are checked by the admission API; SQLite stores the original BLOB.
ADMISSION_TABLES = {
    'admission_streams': '''CREATE TABLE admission_streams (
        stream_id TEXT PRIMARY KEY NOT NULL CHECK(typeof(stream_id)='text' AND length(stream_id) BETWEEN 1 AND 128
            AND stream_id NOT GLOB '*[^A-Za-z0-9_.:-]*' AND substr(stream_id,1,1) GLOB '[A-Za-z0-9]'),
        input_sha256 TEXT NOT NULL CHECK(typeof(input_sha256)='text' AND length(input_sha256)=64 AND input_sha256 NOT GLOB '*[^0-9a-f]*'),
        input_bytes INTEGER NOT NULL CHECK(typeof(input_bytes)='integer' AND input_bytes BETWEEN 1 AND 16777216),
        planned_lines INTEGER NOT NULL CHECK(typeof(planned_lines)='integer' AND planned_lines BETWEEN 1 AND 10000),
        framing TEXT NOT NULL CHECK(framing='utf8-lf-jsonl-v1'),
        plan_hash TEXT NOT NULL CHECK(typeof(plan_hash)='text' AND length(plan_hash)=64 AND plan_hash NOT GLOB '*[^0-9a-f]*'),
        observed_at TEXT NOT NULL CHECK(typeof(observed_at)='text' AND length(observed_at) BETWEEN 1 AND 64))''',
    'delivery_effects': '''CREATE TABLE delivery_effects (
        stream_id TEXT NOT NULL REFERENCES admission_streams(stream_id),
        sequence INTEGER NOT NULL CHECK(typeof(sequence)='integer' AND sequence BETWEEN 1 AND 10000),
        payload BLOB NOT NULL CHECK(typeof(payload)='blob' AND length(payload) BETWEEN 1 AND 65536),
        payload_sha256 TEXT NOT NULL CHECK(typeof(payload_sha256)='text' AND length(payload_sha256)=64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'),
        core_receipt_id INTEGER UNIQUE REFERENCES receipts(id),
        core_receipt_hash TEXT,
        core_result TEXT,
        disposition TEXT NOT NULL CHECK(disposition IN ('ACCEPTED','DUPLICATE','CONFLICT','INVALID','REJECTED_FRAME')),
        reason TEXT CHECK(reason IS NULL OR typeof(reason)='text'),
        observed_at TEXT NOT NULL CHECK(typeof(observed_at)='text' AND length(observed_at) BETWEEN 1 AND 64),
        PRIMARY KEY(stream_id,sequence),
        CHECK((disposition='REJECTED_FRAME' AND core_receipt_id IS NULL AND core_receipt_hash IS NULL AND core_result IS NULL)
          OR (disposition<>'REJECTED_FRAME' AND typeof(core_receipt_id)='integer' AND core_receipt_id>0
            AND typeof(core_receipt_hash)='text' AND length(core_receipt_hash)=64 AND core_receipt_hash NOT GLOB '*[^0-9a-f]*'
            AND typeof(core_result)='text' AND length(core_result)>1)))''',
    'delivery_attempts': '''CREATE TABLE delivery_attempts (
        id INTEGER PRIMARY KEY,
        stream_id TEXT NOT NULL CHECK(typeof(stream_id)='text' AND length(stream_id) BETWEEN 1 AND 128
            AND stream_id NOT GLOB '*[^A-Za-z0-9_.:-]*' AND substr(stream_id,1,1) GLOB '[A-Za-z0-9]'),
        sequence INTEGER NOT NULL CHECK(typeof(sequence)='integer' AND sequence BETWEEN 1 AND 10000),
        payload BLOB NOT NULL CHECK(typeof(payload)='blob' AND length(payload) BETWEEN 1 AND 65536),
        payload_sha256 TEXT NOT NULL CHECK(typeof(payload_sha256)='text' AND length(payload_sha256)=64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'),
        plan_hash TEXT NOT NULL CHECK(typeof(plan_hash)='text' AND length(plan_hash)=64 AND plan_hash NOT GLOB '*[^0-9a-f]*'),
        outcome TEXT NOT NULL CHECK(outcome IN ('COMMITTED','REPLAY','TRANSPORT_CONFLICT','PLAN_CONFLICT','BLOCKED','GAP','OUT_OF_RANGE')),
        effect_stream_id TEXT,
        effect_sequence INTEGER,
        observed_at TEXT NOT NULL CHECK(typeof(observed_at)='text' AND length(observed_at) BETWEEN 1 AND 64),
        reason TEXT CHECK(reason IS NULL OR typeof(reason)='text'),
        FOREIGN KEY(effect_stream_id,effect_sequence) REFERENCES delivery_effects(stream_id,sequence),
        CHECK((effect_stream_id IS NULL AND effect_sequence IS NULL)
          OR (effect_stream_id IS NOT NULL AND effect_sequence IS NOT NULL
            AND effect_stream_id=stream_id AND effect_sequence=sequence)),
        CHECK(outcome NOT IN ('COMMITTED','REPLAY') OR effect_stream_id IS NOT NULL),
        CHECK(outcome NOT IN ('GAP','OUT_OF_RANGE') OR effect_stream_id IS NULL))''',
}
ADMISSION_INDEXES = {
    'delivery_attempts_stream_outcome': 'CREATE INDEX delivery_attempts_stream_outcome ON delivery_attempts(stream_id,outcome,id)',
}
ADMISSION_TRIGGERS = {
    'delivery_effects_strict_next': '''CREATE TRIGGER delivery_effects_strict_next BEFORE INSERT ON delivery_effects BEGIN
        SELECT CASE WHEN NEW.sequence <> COALESCE((SELECT MAX(sequence) FROM delivery_effects WHERE stream_id=NEW.stream_id),0)+1
            THEN RAISE(ABORT,'delivery sequence is not strict next') END;
        SELECT CASE WHEN NEW.sequence > (SELECT planned_lines FROM admission_streams WHERE stream_id=NEW.stream_id)
            THEN RAISE(ABORT,'delivery exceeds immutable plan') END;
        SELECT CASE WHEN EXISTS(SELECT 1 FROM delivery_attempts WHERE stream_id=NEW.stream_id
            AND outcome IN ('TRANSPORT_CONFLICT','PLAN_CONFLICT'))
            THEN RAISE(ABORT,'delivery stream is blocked') END;
    END''',
    'delivery_effects_receipt_link': '''CREATE TRIGGER delivery_effects_receipt_link BEFORE INSERT ON delivery_effects
        WHEN NEW.disposition <> 'REJECTED_FRAME' BEGIN
        SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM receipts WHERE id=NEW.core_receipt_id
            AND receipt_hash=NEW.core_receipt_hash AND status=NEW.disposition)
            THEN RAISE(ABORT,'delivery core receipt identity/status differs') END;
    END''',
    'delivery_attempts_effect_link': '''CREATE TRIGGER delivery_attempts_effect_link BEFORE INSERT ON delivery_attempts
        WHEN NEW.outcome IN ('COMMITTED','REPLAY') BEGIN
        SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM delivery_effects e JOIN admission_streams s ON s.stream_id=e.stream_id
            WHERE e.stream_id=NEW.effect_stream_id AND e.sequence=NEW.effect_sequence
            AND e.payload=NEW.payload AND e.payload_sha256=NEW.payload_sha256 AND s.plan_hash=NEW.plan_hash)
            THEN RAISE(ABORT,'delivery attempt differs from original effect/plan') END;
    END''',
}
for _table in ADMISSION_TABLES:
    for _action in ('UPDATE', 'DELETE'):
        _name = f'immutable_{_table}_{_action}'
        ADMISSION_TRIGGERS[_name] = (f"CREATE TRIGGER {_name} BEFORE {_action} ON {_table} "
                                   "BEGIN SELECT RAISE(ABORT, 'append-only table'); END")


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


def table_snapshot(db, table, *, exclude_new_migration=False, migration_through=None):
    columns = [list(r) for r in db.execute('PRAGMA table_xinfo(' + quoted(table) + ')')]
    names = [r[1] for r in columns if r[6] != 1]
    order = ','.join('typeof(' + quoted(n) + '),' + quoted(n) + ' COLLATE BINARY' for n in names)
    sql = 'SELECT * FROM ' + quoted(table)
    if exclude_new_migration:
        sql += ' WHERE version<>3'
    elif migration_through is not None:
        sql += ' WHERE version<=' + str(int(migration_through))
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
        actual = table_snapshot(db, name,
            migration_through=before['user_version'] if name == 'schema_migrations' else None)
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
    wanted = [(n, MIGRATIONS[n]) for n in (2, 3, 4, 5, 6) if n <= version]
    require(rows == wanted, 'SCHEMA_INVALID: migration metadata differs from physical version')


def validate_admission_schema(db):
    """Reject missing/altered schema-4 guards; never repair during ordinary open."""
    for kind, definitions in (('table', ADMISSION_TABLES), ('index', ADMISSION_INDEXES), ('trigger', ADMISSION_TRIGGERS)):
        for name, expected in definitions.items():
            row = db.execute('SELECT type,sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
            require(row is not None and row[0] == kind and row[1] is not None
                    and ' '.join(row[1].split()) == ' '.join(expected.split()),
                    'SCHEMA_INVALID: admission schema object differs: ' + name)
    return True


def _validate_definitions(db, kind, definitions):
    for name, expected in definitions.items():
        row = db.execute('SELECT type,sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
        require(row is not None and row[0] == kind and row[1] is not None
                and ' '.join(row[1].split()) == ' '.join(expected.split()),
                'SCHEMA_INVALID: required schema object differs: ' + name)


def validate_schema(db, version):
    """Validate one explicit physical version, including its full required guards."""
    require(type(version) is int and version in (0, 2, 3, 4, 5, 6),
            'unsupported schema version: ' + str(version))
    require(db.execute('PRAGMA user_version').fetchone()[0] == version,
            'SCHEMA_INVALID: physical schema version differs from requested historical version')
    for kind, definitions in (('table', FINANCIAL_TABLES), ('index', FINANCIAL_INDEXES),
                              ('trigger', FINANCIAL_TRIGGERS)):
        _validate_definitions(db, kind, definitions)
    if version >= 2:
        _validate_metadata(db, version)
        _validate_definitions(db, 'table', CORRECTION_TABLES)
        _validate_definitions(db, 'trigger', CORRECTION_TRIGGERS)
    if version >= 3:
        validate_index(db)
    if version >= 4:
        validate_admission_schema(db)
    if version >= 5:
        from .source_auth.schema import validate_auth_schema
        validate_auth_schema(db)
    if version >= 6:
        for kind, definitions in (('table', EXECUTION_TABLES), ('index', EXECUTION_INDEXES),
                                  ('trigger', EXECUTION_TRIGGERS)):
            _validate_definitions(db, kind, definitions)
    else:
        # A schema-6 database must never masquerade as historical provenance-v1.
        reserved = set(EXECUTION_TABLES) | set(EXECUTION_INDEXES) | set(EXECUTION_TRIGGERS)
        actual = {row[0] for row in db.execute('SELECT name FROM sqlite_master')}
        require(not reserved & actual, 'SCHEMA_INVALID: future execution objects in historical schema')
    return True


def validate_runtime(db):
    """Ordinary financial/admission/auth operations support exactly 5 and 6."""
    version = db.execute('PRAGMA user_version').fetchone()[0]
    require(version in (5, 6),
            'MIGRATION_REQUIRED: use migrate with a backup directory before creating new evaluations')
    return validate_schema(db, version)


def validate_current(db):
    require(db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION,
            'MIGRATION_REQUIRED: use migrate with a backup directory before creating new evaluations')
    return validate_schema(db, SCHEMA_VERSION)


def validate_open(db):
    version = db.execute('PRAGMA user_version').fetchone()[0]
    validate_schema(db, version)
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


def _stage4(db, fault):
    inject(fault, 'migration_before_admission')
    for sql in ADMISSION_TABLES.values():
        db.execute(sql)
    inject(fault, 'migration_after_admission_tables')
    for sql in (*ADMISSION_INDEXES.values(), *ADMISSION_TRIGGERS.values()):
        db.execute(sql)
    db.execute('INSERT INTO schema_migrations VALUES (?,?)', (4, MIGRATIONS[4]))
    db.execute('PRAGMA user_version=4')
    inject(fault, 'migration_after_schema4')


def _stage5(db, fault):
    from .source_auth.schema import AUTH_TABLES, AUTH_TRIGGERS
    inject(fault, 'migration_before_auth')
    for sql in AUTH_TABLES.values():
        db.execute(sql)
    inject(fault, 'migration_after_auth_tables')
    for sql in AUTH_TRIGGERS.values():
        db.execute(sql)
    db.execute('INSERT INTO schema_migrations VALUES (?,?)', (5, MIGRATIONS[5]))
    db.execute('PRAGMA user_version=5')
    inject(fault, 'migration_after_schema5')


def _stage6(db, fault):
    inject(fault, 'migration_before_execution')
    for sql in EXECUTION_TABLES.values():
        db.execute(sql)
    inject(fault, 'migration_after_execution_tables')
    for sql in (*EXECUTION_INDEXES.values(), *EXECUTION_TRIGGERS.values()):
        db.execute(sql)
    db.execute('INSERT INTO schema_migrations VALUES (?,?)', (6, MIGRATIONS[6]))
    db.execute('PRAGMA user_version=6')
    inject(fault, 'migration_after_schema6')


def migrate_connection(db, fault=None, *, timings=None, expected_snapshot=None, target_version=SCHEMA_VERSION):
    require(type(target_version) is int and target_version in (5, 6), 'migration target must be 5 or 6')
    current = db.execute('PRAGMA user_version').fetchone()[0]
    if current == target_version:
        validate_schema(db, target_version)
        return False
    require(current in (0, 2, 3, 4, 5) and current < target_version,
            'unsupported schema version or downgrade: ' + str(current))
    require(not db.in_transaction, 'nested transaction not supported')
    timings = {} if timings is None else timings
    started = time.perf_counter()
    db.execute('BEGIN IMMEDIATE')
    try:
        phase = time.perf_counter()
        before = application_snapshot(db)
        if expected_snapshot is not None:
            require(before == expected_snapshot, 'source changed after verified backup')
        validate_schema(db, current)
        timings['preservation_before_seconds'] = time.perf_counter() - phase
        if current == 0:
            _stage2(db, fault)
        if current < 3:
            inject(fault, 'migration_before_index')
            phase = time.perf_counter()
            if not validate_index(db, required=False):
                db.execute(INDEX_SQL)
            timings['index_create_seconds'] = time.perf_counter() - phase
            inject(fault, 'migration_after_index')
            db.execute('INSERT INTO schema_migrations VALUES (?,?)', (3, MIGRATIONS[3]))
            db.execute('PRAGMA user_version=3')
        phase = time.perf_counter()
        if current < 4:
            _stage4(db, fault)
        timings['admission_create_seconds'] = time.perf_counter() - phase
        phase = time.perf_counter()
        if current < 5:
            _stage5(db, fault)
        timings['auth_create_seconds'] = time.perf_counter() - phase
        phase = time.perf_counter()
        if target_version == 6:
            _stage6(db, fault)
        timings['execution_create_seconds'] = time.perf_counter() - phase
        phase = time.perf_counter()
        assert_preserved(db, before)
        validate_schema(db, target_version)
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
        backup = folder / (prefix + ('.stage1.sqlite3' if version == 0 else f'.schema{version}.sqlite3'))
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
