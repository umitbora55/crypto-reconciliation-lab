"""Independent schema-4 fixture frozen from accepted c49f1a1, not current DDL.

Only the historical Stage 9 reader test uses this additive fixture. Its input is
an independently constructed schema-3 database; no schema-5 migration is called.
"""

SCHEMA4_DDL = ('CREATE TABLE admission_streams (\n'
 "        stream_id TEXT PRIMARY KEY NOT NULL CHECK(typeof(stream_id)='text' AND length(stream_id) "
 'BETWEEN 1 AND 128\n'
 "            AND stream_id NOT GLOB '*[^A-Za-z0-9_.:-]*' AND substr(stream_id,1,1) GLOB "
 "'[A-Za-z0-9]'),\n"
 "        input_sha256 TEXT NOT NULL CHECK(typeof(input_sha256)='text' AND length(input_sha256)=64 "
 "AND input_sha256 NOT GLOB '*[^0-9a-f]*'),\n"
 "        input_bytes INTEGER NOT NULL CHECK(typeof(input_bytes)='integer' AND input_bytes BETWEEN "
 '1 AND 16777216),\n'
 "        planned_lines INTEGER NOT NULL CHECK(typeof(planned_lines)='integer' AND planned_lines "
 'BETWEEN 1 AND 10000),\n'
 "        framing TEXT NOT NULL CHECK(framing='utf8-lf-jsonl-v1'),\n"
 "        plan_hash TEXT NOT NULL CHECK(typeof(plan_hash)='text' AND length(plan_hash)=64 AND "
 "plan_hash NOT GLOB '*[^0-9a-f]*'),\n"
 "        observed_at TEXT NOT NULL CHECK(typeof(observed_at)='text' AND length(observed_at) "
 'BETWEEN 1 AND 64))',
 'CREATE TABLE delivery_effects (\n'
 '        stream_id TEXT NOT NULL REFERENCES admission_streams(stream_id),\n'
 "        sequence INTEGER NOT NULL CHECK(typeof(sequence)='integer' AND sequence BETWEEN 1 AND "
 '10000),\n'
 "        payload BLOB NOT NULL CHECK(typeof(payload)='blob' AND length(payload) BETWEEN 1 AND "
 '65536),\n'
 "        payload_sha256 TEXT NOT NULL CHECK(typeof(payload_sha256)='text' AND "
 "length(payload_sha256)=64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'),\n"
 '        core_receipt_id INTEGER UNIQUE REFERENCES receipts(id),\n'
 '        core_receipt_hash TEXT,\n'
 '        core_result TEXT,\n'
 '        disposition TEXT NOT NULL CHECK(disposition IN '
 "('ACCEPTED','DUPLICATE','CONFLICT','INVALID','REJECTED_FRAME')),\n"
 "        reason TEXT CHECK(reason IS NULL OR typeof(reason)='text'),\n"
 "        observed_at TEXT NOT NULL CHECK(typeof(observed_at)='text' AND length(observed_at) "
 'BETWEEN 1 AND 64),\n'
 '        PRIMARY KEY(stream_id,sequence),\n'
 "        CHECK((disposition='REJECTED_FRAME' AND core_receipt_id IS NULL AND core_receipt_hash IS "
 'NULL AND core_result IS NULL)\n'
 "          OR (disposition<>'REJECTED_FRAME' AND typeof(core_receipt_id)='integer' AND "
 'core_receipt_id>0\n'
 "            AND typeof(core_receipt_hash)='text' AND length(core_receipt_hash)=64 AND "
 "core_receipt_hash NOT GLOB '*[^0-9a-f]*'\n"
 "            AND typeof(core_result)='text' AND length(core_result)>1)))",
 'CREATE TABLE delivery_attempts (\n'
 '        id INTEGER PRIMARY KEY,\n'
 "        stream_id TEXT NOT NULL CHECK(typeof(stream_id)='text' AND length(stream_id) BETWEEN 1 "
 'AND 128\n'
 "            AND stream_id NOT GLOB '*[^A-Za-z0-9_.:-]*' AND substr(stream_id,1,1) GLOB "
 "'[A-Za-z0-9]'),\n"
 "        sequence INTEGER NOT NULL CHECK(typeof(sequence)='integer' AND sequence BETWEEN 1 AND "
 '10000),\n'
 "        payload BLOB NOT NULL CHECK(typeof(payload)='blob' AND length(payload) BETWEEN 1 AND "
 '65536),\n'
 "        payload_sha256 TEXT NOT NULL CHECK(typeof(payload_sha256)='text' AND "
 "length(payload_sha256)=64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'),\n"
 "        plan_hash TEXT NOT NULL CHECK(typeof(plan_hash)='text' AND length(plan_hash)=64 AND "
 "plan_hash NOT GLOB '*[^0-9a-f]*'),\n"
 '        outcome TEXT NOT NULL CHECK(outcome IN '
 "('COMMITTED','REPLAY','TRANSPORT_CONFLICT','PLAN_CONFLICT','BLOCKED','GAP','OUT_OF_RANGE')),\n"
 '        effect_stream_id TEXT,\n'
 '        effect_sequence INTEGER,\n'
 "        observed_at TEXT NOT NULL CHECK(typeof(observed_at)='text' AND length(observed_at) "
 'BETWEEN 1 AND 64),\n'
 "        reason TEXT CHECK(reason IS NULL OR typeof(reason)='text'),\n"
 '        FOREIGN KEY(effect_stream_id,effect_sequence) REFERENCES '
 'delivery_effects(stream_id,sequence),\n'
 '        CHECK((effect_stream_id IS NULL AND effect_sequence IS NULL)\n'
 '          OR (effect_stream_id IS NOT NULL AND effect_sequence IS NOT NULL\n'
 '            AND effect_stream_id=stream_id AND effect_sequence=sequence)),\n'
 "        CHECK(outcome NOT IN ('COMMITTED','REPLAY') OR effect_stream_id IS NOT NULL),\n"
 "        CHECK(outcome NOT IN ('GAP','OUT_OF_RANGE') OR effect_stream_id IS NULL))",
 'CREATE INDEX delivery_attempts_stream_outcome ON delivery_attempts(stream_id,outcome,id)',
 'CREATE TRIGGER delivery_effects_strict_next BEFORE INSERT ON delivery_effects BEGIN\n'
 '        SELECT CASE WHEN NEW.sequence <> COALESCE((SELECT MAX(sequence) FROM delivery_effects '
 'WHERE stream_id=NEW.stream_id),0)+1\n'
 "            THEN RAISE(ABORT,'delivery sequence is not strict next') END;\n"
 '        SELECT CASE WHEN NEW.sequence > (SELECT planned_lines FROM admission_streams WHERE '
 'stream_id=NEW.stream_id)\n'
 "            THEN RAISE(ABORT,'delivery exceeds immutable plan') END;\n"
 '        SELECT CASE WHEN EXISTS(SELECT 1 FROM delivery_attempts WHERE stream_id=NEW.stream_id\n'
 "            AND outcome IN ('TRANSPORT_CONFLICT','PLAN_CONFLICT'))\n"
 "            THEN RAISE(ABORT,'delivery stream is blocked') END;\n"
 '    END',
 'CREATE TRIGGER delivery_effects_receipt_link BEFORE INSERT ON delivery_effects\n'
 "        WHEN NEW.disposition <> 'REJECTED_FRAME' BEGIN\n"
 '        SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM receipts WHERE id=NEW.core_receipt_id\n'
 '            AND receipt_hash=NEW.core_receipt_hash AND status=NEW.disposition)\n'
 "            THEN RAISE(ABORT,'delivery core receipt identity/status differs') END;\n"
 '    END',
 'CREATE TRIGGER delivery_attempts_effect_link BEFORE INSERT ON delivery_attempts\n'
 "        WHEN NEW.outcome IN ('COMMITTED','REPLAY') BEGIN\n"
 '        SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM delivery_effects e JOIN admission_streams s ON '
 's.stream_id=e.stream_id\n'
 '            WHERE e.stream_id=NEW.effect_stream_id AND e.sequence=NEW.effect_sequence\n'
 '            AND e.payload=NEW.payload AND e.payload_sha256=NEW.payload_sha256 AND '
 's.plan_hash=NEW.plan_hash)\n'
 "            THEN RAISE(ABORT,'delivery attempt differs from original effect/plan') END;\n"
 '    END',
 'CREATE TRIGGER immutable_admission_streams_UPDATE BEFORE UPDATE ON admission_streams BEGIN '
 "SELECT RAISE(ABORT, 'append-only table'); END",
 'CREATE TRIGGER immutable_admission_streams_DELETE BEFORE DELETE ON admission_streams BEGIN '
 "SELECT RAISE(ABORT, 'append-only table'); END",
 'CREATE TRIGGER immutable_delivery_effects_UPDATE BEFORE UPDATE ON delivery_effects BEGIN SELECT '
 "RAISE(ABORT, 'append-only table'); END",
 'CREATE TRIGGER immutable_delivery_effects_DELETE BEFORE DELETE ON delivery_effects BEGIN SELECT '
 "RAISE(ABORT, 'append-only table'); END",
 'CREATE TRIGGER immutable_delivery_attempts_UPDATE BEFORE UPDATE ON delivery_attempts BEGIN '
 "SELECT RAISE(ABORT, 'append-only table'); END",
 'CREATE TRIGGER immutable_delivery_attempts_DELETE BEFORE DELETE ON delivery_attempts BEGIN '
 "SELECT RAISE(ABORT, 'append-only table'); END")

def install_historical_schema4(db):
    if db.execute('PRAGMA user_version').fetchone()[0] != 3:
        raise ValueError('Historical schema-4 fixture requires schema 3')
    db.execute('BEGIN IMMEDIATE')
    try:
        for sql in SCHEMA4_DDL:
            db.execute(sql)
        db.execute('INSERT INTO schema_migrations VALUES (?,?)',
                   (4, 'Add immutable admission streams, delivery effects and attempts; preserve financial history'))
        db.execute('PRAGMA user_version=4')
        db.execute('COMMIT')
    except BaseException:
        db.execute('ROLLBACK')
        raise
