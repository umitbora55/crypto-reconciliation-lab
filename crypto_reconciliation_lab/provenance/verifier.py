"""Independent, bounded reader of saved-run provenance and external trust.

This module never opens a database, invokes an exporter or computes financial
amounts. The relationship inventory is derived from the pinned saved run.
"""
from pathlib import Path, PurePosixPath
import os
import re
import stat

from .common import ProvenanceError, bounded_file, canonical, parse_json, sha256
from ..review.validation import validate_payload, ReviewError
from ..model import timestamp
from ..source_auth.crypto import (AuthError, MAX_ENVELOPE, MAX_PAYLOAD, PAYLOAD_TYPE,
                                 parse_envelope, pae, require_auth, verify_signature)
from ..source_auth.policy import validate_policy
from ..source_auth.scope import (capabilities, capability_inventory, snapshot_bytes,
                                statement as validate_statement)
from ..admission.runtime import validate_plan

MAX_JSON = 8 * 1024 * 1024
MAX_CAPTURE = 32 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
MAX_ROWS = 100000
MAX_EPOCHS = 1024
HEX = re.compile(r'[0-9a-f]{64}\Z')
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z')
FIXED = {'run.json', 'capture.json', 'report.json', 'index.html', 'app.js', 'style.css', 'data.js'}
MATERIAL = re.compile(r'materials/(policies|envelopes|snapshots)/([0-9a-f]{64})\.(json|jsonl)\Z')

# Exact portable projection of existing schema-5 columns, not a second schema.
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
KEYS = {'records': ('id',), 'receipts': ('id',), 'admission_streams': ('stream_id',),
        'delivery_effects': ('stream_id', 'sequence'), 'delivery_attempts': ('id',),
        'auth_configuration': ('id',), 'auth_policy_snapshots': ('policy_hash',),
        'auth_policy_activations': ('epoch',), 'auth_keys': ('key_id',),
        'auth_streams': ('stream_id',), 'auth_endorsements': ('id',),
        'auth_decisions': ('id',), 'auth_delivery_links': ('stream_id', 'sequence'),
        'auth_attempt_links': ('attempt_id',)}
INTEGER_COLUMNS = {'id', 'sequence', 'core_receipt_id', 'input_bytes', 'planned_lines',
                   'epoch', 'previous_epoch', 'first_epoch', 'decision_id', 'attempt_id', 'effect_sequence'}
NULL_COLUMNS = {'record_id', 'received_at', 'error', 'core_receipt_id', 'core_receipt_hash',
                'core_result', 'reason', 'effect_stream_id', 'effect_sequence', 'previous_epoch', 'previous_hash'}


def _need(condition, code, message):
    if not condition:
        raise ProvenanceError(code, message)


def _hex(value):
    return type(value) is str and HEX.fullmatch(value) is not None


def _positive(value, maximum=2**63-1):
    return type(value) is int and 0 < value <= maximum


def _same(a, b):
    return canonical(a) == canonical(b)


def _blob(value, limit, code='DELIVERY_RELATION'):
    _need(type(value) is str and 0 < len(value) <= limit * 2 and len(value) % 2 == 0
          and re.fullmatch('[0-9a-f]+', value) is not None, code, 'invalid bounded lowercase BLOB hex')
    return bytes.fromhex(value)


def _json_text(value, limit=MAX_JSON):
    _need(type(value) is str, 'CAPTURE_STRUCTURE', 'SQL TEXT must remain text')
    return parse_json(value.encode('utf-8'), limit=limit)


def _member_limit(name):
    if name == 'capture.json': return MAX_CAPTURE
    if name == 'data.js': return 64 * 1024 * 1024
    if name.startswith('materials/snapshots/'): return 16 * 1024 * 1024
    if name.startswith('materials/envelopes/'): return MAX_ENVELOPE
    if name.startswith('materials/policies/'): return 128 * 1024
    return MAX_JSON


def _valid_name(name):
    if type(name) is not str or not name or '\\' in name or '\x00' in name:
        return False
    path = PurePosixPath(name)
    if path.is_absolute() or path.as_posix() != name or any(p in ('', '.', '..') for p in path.parts):
        return False
    if name in FIXED: return True
    match = MATERIAL.fullmatch(name)
    return bool(match and (match[3] == ('jsonl' if match[1] == 'snapshots' else 'json')))


def _read_member(root, name, limit):
    """Walk open directory descriptors without following replacement links."""
    parts = PurePosixPath(name).parts
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    descriptors = []
    try:
        directory = os.open(root, flags | getattr(os, 'O_DIRECTORY', 0))
        descriptors.append(directory)
        for part in parts[:-1]:
            directory = os.open(part, flags | getattr(os, 'O_DIRECTORY', 0), dir_fd=directory)
            descriptors.append(directory)
            _need(stat.S_ISDIR(os.fstat(directory).st_mode), 'BUNDLE_PATH', 'member ancestor is not a directory')
        descriptor = os.open(parts[-1], flags, dir_fd=directory)
        with os.fdopen(descriptor, 'rb') as stream:
            before = os.fstat(stream.fileno())
            _need(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= limit, 'BUNDLE_LIMIT', 'bounded regular member required')
            raw = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        now = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
        fields = lambda row: (row.st_dev, row.st_ino, row.st_mode, row.st_size, row.st_mtime_ns, row.st_ctime_ns)
        _need(fields(before) == fields(after) == fields(now) and len(raw) == before.st_size,
              'BUNDLE_CHANGED', 'member changed while reading')
        return raw
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _load_expectations(path, root):
    path = Path(path)
    _need(not path.is_symlink(), 'EXPECTATIONS_PATH', 'expectations must not be a symlink')
    resolved = path.resolve(strict=True)
    _need(not resolved.is_relative_to(root), 'EXPECTATIONS_PATH', 'expectations must be outside the bundle')
    value = parse_json(_read_member(Path(resolved.anchor), resolved.relative_to(resolved.anchor).as_posix(), MAX_JSON), limit=MAX_JSON)
    fields = {'format', 'profile', 'run_id', 'run_payload_sha256', 'configuration_digest',
              'capture_digest', 'receiver', 'policy_head', 'policies'}
    _need(type(value) is dict and set(value) == fields and value['format'] == 'provenance-expectations-v1',
          'EXPECTATIONS_FORMAT', 'exact external expectations fields required')
    _need(value['profile'] in ('protected', 'legacy'), 'EXPECTATIONS_FORMAT', 'unknown profile')
    _need(all(_hex(value[k]) for k in ('run_id', 'run_payload_sha256', 'configuration_digest', 'capture_digest')),
          'EXPECTATIONS_FORMAT', 'external identity must be a SHA-256 digest')
    if value['profile'] == 'legacy':
        _need(value['receiver'] is None and value['policy_head'] is None and value['policies'] == [],
              'EXPECTATIONS_FORMAT', 'legacy trust has no receiver or policy authority')
    else:
        _need(type(value['receiver']) is str and IDENTIFIER.fullmatch(value['receiver']) is not None,
              'EXPECTATIONS_FORMAT', 'protected receiver is required')
        policies = value['policies']
        _need(type(policies) is list and 0 < len(policies) <= MAX_EPOCHS, 'EXPECTATIONS_FORMAT', 'bounded complete policy map required')
        for epoch, row in enumerate(policies, 1):
            _need(type(row) is dict and set(row) == {'epoch', 'policy_hash'} and type(row['epoch']) is int
                  and row['epoch'] == epoch and _hex(row['policy_hash']), 'EXPECTATIONS_FORMAT', 'policy epochs must be contiguous from one')
        _need(_same(value['policy_head'], policies[-1]), 'EXPECTATIONS_FORMAT', 'explicit capture head differs from full epoch map')
    return value


def _load_members(root):
    manifest_bytes = _read_member(root, 'manifest.json', MAX_JSON)
    manifest = parse_json(manifest_bytes, limit=MAX_JSON)
    _need(type(manifest) is dict and set(manifest) == {'format', 'run_id', 'files'}
          and manifest['format'] == 'run-provenance-bundle-v1' and _hex(manifest['run_id']),
          'BUNDLE_MANIFEST', 'exact bundle manifest fields required')
    entries = manifest['files']
    _need(type(entries) is dict and FIXED <= set(entries) and len(entries) + 1 <= 1024,
          'BUNDLE_MANIFEST', 'missing fixed members or too many files')
    actual = set()
    allowed_directories = {'materials', 'materials/policies', 'materials/envelopes', 'materials/snapshots'}
    for directory, dirs, files in os.walk(root, followlinks=False):
        _need(len(dirs) + len(files) <= 1024, 'BUNDLE_LIMIT', 'directory member limit exceeded')
        for name in dirs + files:
            path = Path(directory) / name
            info = path.lstat()
            _need(not stat.S_ISLNK(info.st_mode), 'BUNDLE_PATH', 'bundle links are forbidden')
            _need(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode), 'BUNDLE_PATH', 'bundle special files are forbidden')
            if stat.S_ISDIR(info.st_mode):
                _need(path.relative_to(root).as_posix() in allowed_directories, 'BUNDLE_PATH', 'unexpected material directory')
        actual.update((Path(directory) / name).relative_to(root).as_posix() for name in files)
        _need(len(actual) <= 1024, 'BUNDLE_LIMIT', 'bundle member limit exceeded')
    _need(actual == set(entries) | {'manifest.json'}, 'BUNDLE_MEMBERS', 'actual member inventory differs from manifest')
    total = len(manifest_bytes)
    data = {}
    for name, item in sorted(entries.items()):
        _need(_valid_name(name), 'BUNDLE_PATH', 'unexpected or unsafe member path')
        _need(type(item) is dict and set(item) == {'bytes', 'sha256'} and type(item['bytes']) is int
              and 0 <= item['bytes'] <= _member_limit(name) and _hex(item['sha256']),
              'BUNDLE_MANIFEST', 'invalid member byte identity')
        total += item['bytes']
        _need(total <= MAX_TOTAL, 'BUNDLE_LIMIT', 'total material limit exceeded')
        raw = _read_member(root, name, _member_limit(name))
        _need(len(raw) == item['bytes'] and sha256(raw) == item['sha256'], 'MEMBER_HASH', 'member bytes differ: ' + name)
        data[name] = raw
    return manifest, manifest_bytes, data


def _scope(run):
    """Derive required saved evidence; deliberately separate from SQL export."""
    evidence = run['evidence']
    records, receipts, record_for_receipt, quarantine = {}, {}, {}, {}
    for eid, entry in evidence.items():
        _need(_hex(eid), 'EVIDENCE_SCOPE', 'saved evidence ID must be a content digest')
        if 'record' in entry:
            value = entry['record']
            _need(sha256(canonical(value)) == eid and type(entry['logical_key']) is str,
                  'EVIDENCE_SCOPE', 'saved normalized record content ID differs')
            refs = entry['receipt_ids']
            _need(type(refs) is list and refs and len(refs) == len(set(refs)), 'EVIDENCE_SCOPE', 'record requires unique receipt references')
            records[eid] = entry
            for rid in refs:
                _need(_hex(rid) and rid in evidence and set(evidence[rid]) == {'receipt'},
                      'EVIDENCE_SCOPE', 'record receipt reference is missing or has wrong kind')
                _need(rid not in record_for_receipt or record_for_receipt[rid] == eid,
                      'EVIDENCE_SCOPE', 'one saved receipt names different normalized records')
                record_for_receipt[rid] = eid
        elif 'receipt' in entry:
            raw = entry['receipt']
            _need(type(raw) is dict and set(raw) == {'record', 'received_at'} and sha256(canonical(raw)) == eid,
                  'EVIDENCE_SCOPE', 'saved raw receipt identity differs')
            receipts[eid] = raw
        elif 'quarantined_receipt' in entry:
            bad = entry['quarantined_receipt']
            _need(type(bad) is dict and set(bad) == {'id', 'error', 'record', 'received_at'} and bad['id'] == eid
                  and type(bad['error']) is str, 'EVIDENCE_SCOPE', 'invalid quarantined receipt identity')
            raw = {k: bad[k] for k in ('record', 'received_at')}
            _need(sha256(canonical(raw)) == eid, 'EVIDENCE_SCOPE', 'quarantine raw content ID differs')
            receipts[eid], quarantine[eid] = raw, bad['error']
        else:
            _need(set(entry) == {'derived_correction_group'}, 'EVIDENCE_SCOPE', 'unsupported saved evidence kind')
            group = entry['derived_correction_group']
            _need(group.get('id') == eid and sha256(canonical({k: v for k, v in group.items() if k != 'id'})) == eid,
                  'EVIDENCE_SCOPE', 'correction group identity differs')
            for name in ('correction_record_id', 'target_record_id'):
                _need(group.get(name) in evidence and 'record' in evidence[group[name]],
                      'EVIDENCE_SCOPE', 'correction target or source is absent')
    _need(set(record_for_receipt) <= set(receipts), 'EVIDENCE_SCOPE', 'uncovered record receipt reference')
    _need(bool(receipts), 'NO_LISTED_EVIDENCE', 'this provenance profile requires nonempty listed receipt evidence')
    run_id = sha256(canonical(run))
    findings = [{'id': run_id + ':' + str(i), 'ordinal': i,
                 **{k: finding[k] for k in ('comparison', 'asset', 'scope', 'evidence_ids')}}
                for i, finding in enumerate(run['findings'])]
    return records, receipts, record_for_receipt, quarantine, findings


def _tables(capture):
    _need(type(capture) is dict and set(capture) == {'format', 'schema_version', 'database', 'configuration', 'tables'}
          and capture['format'] == 'run-provenance-capture-v1' and type(capture['schema_version']) is int
          and capture['schema_version'] == 5, 'CAPTURE_STRUCTURE', 'exact schema-5 capture required')
    db = capture['database']
    _need(type(db) is dict and set(db) == {'bytes', 'sha256'} and _positive(db['bytes'], 256*1024*1024)
          and _hex(db['sha256']), 'CAPTURE_STRUCTURE', 'bounded database byte identity required')
    tables = capture['tables']
    _need(type(tables) is dict and set(tables) == set(COLUMNS), 'CAPTURE_STRUCTURE', 'projection table inventory differs')
    result, count = {}, 0
    for name, columns in COLUMNS.items():
        rows = tables[name]
        _need(type(rows) is list, 'CAPTURE_STRUCTURE', 'table rows must be arrays')
        count += len(rows)
        _need(count <= MAX_ROWS, 'BUNDLE_LIMIT', 'projected row limit exceeded')
        indexed = {}
        for row in rows:
            _need(type(row) is dict and set(row) == set(columns.split()), 'CAPTURE_STRUCTURE', 'wrong columns: ' + name)
            for column, value in row.items():
                if value is None and column in NULL_COLUMNS: continue
                integer = column in INTEGER_COLUMNS and not (column == 'id' and name in ('records', 'auth_endorsements'))
                _need(_positive(value) if integer else type(value) is str,
                      'CAPTURE_STRUCTURE', 'wrong SQL value type: ' + name + '.' + column)
                if column in ('stream_id', 'effect_stream_id'):
                    _need(IDENTIFIER.fullmatch(value) is not None, 'CAPTURE_STRUCTURE', 'invalid stream identifier')
                if column.endswith('_hash') or column.endswith('_sha256') or column in ('record_id', 'fingerprint') or (column == 'id' and name in ('records', 'auth_endorsements')):
                    _need(_hex(value), 'CAPTURE_STRUCTURE', 'invalid captured content digest')
                if column == 'observed_at':
                    _need(timestamp(value) == value, 'CAPTURE_STRUCTURE', 'normalized observation time required')
            key = tuple(row[k] for k in KEYS[name])
            _need(key not in indexed, 'CAPTURE_STRUCTURE', 'duplicate SQL identity: ' + name)
            indexed[key] = row
        _need(list(indexed) == sorted(indexed), 'CAPTURE_STRUCTURE', 'rows must retain primary-key order: ' + name)
        result[name] = indexed
    return result


def _report(report, run, expectations, records, receipts, findings):
    expected = {'format': 'run-provenance-report-v1', 'run_id': expectations['run_id'],
                'run_payload_sha256': expectations['run_payload_sha256'],
                'capture_digest': expectations['capture_digest'],
                'configuration_digest': expectations['configuration_digest'],
                'capture_profile': expectations['profile'], 'record_ids': sorted(records),
                'receipt_hashes': sorted(receipts), 'findings': findings,
                'run_creation_authorization_cut': 'NOT_RECORDED',
                'financial_recomputation': 'NOT_PERFORMED', 'source_verification': 'NOT_PERFORMED'}
    _need(_same(report, expected), 'REPORT_SCOPE', 'exported report differs from independently listed run scope')


def _presentation(data, run, capture, report, manifest):
    assets = Path(__file__).with_name('assets')
    for name in ('index.html', 'app.js', 'style.css'):
        _need(data[name] == bounded_file(assets/name, MAX_JSON), 'PRESENTATION_INTEGRITY', 'unrecognized offline asset: ' + name)
    material = {name: value for name, value in manifest['files'].items() if name.startswith('materials/')}
    # Independently derive the display projection from already typed raw SQL
    # rows. Do not trust exporter labels or share its presentation builder.
    identity_columns = {
        'receipts': ('id',), 'delivery_effects': ('sequence', 'core_receipt_id'),
        'delivery_attempts': ('id', 'sequence', 'effect_sequence'), 'auth_configuration': ('id',),
        'auth_policy_activations': ('epoch', 'previous_epoch'), 'auth_keys': ('first_epoch',),
        'auth_decisions': ('id', 'epoch', 'sequence'),
        'auth_delivery_links': ('sequence', 'decision_id', 'core_receipt_id'),
        'auth_attempt_links': ('attempt_id', 'decision_id'),
    }
    shown_tables = {}
    for table, rows in capture['tables'].items():
        shown_tables[table] = []
        for original in rows:
            row = dict(original)
            for column in identity_columns.get(table, ()):
                if row[column] is not None:
                    row[column] = str(row[column])
            shown_tables[table].append(row)
    shown_capture = {**capture, 'tables': shown_tables}
    payload = {'run': run, 'capture': shown_capture, 'report': report, 'materials': material}
    expected = b'window.PROVENANCE_DATA = JSON.parse(' + canonical(canonical(payload).decode('ascii')) + b');\n'
    _need(data['data.js'] == expected, 'PRESENTATION_INTEGRITY', 'offline data differs from the independently verified payloads')


def _receipt_rows(t, records, receipts, record_for_receipt, quarantine):
    stored = {key[0]: value for key, value in t['records'].items()}
    _need(set(stored) == set(records), 'EVIDENCE_SCOPE', 'normalized record inventory differs from immutable run')
    for rid, entry in records.items():
        row = stored[rid]
        _need(_same(_json_text(row['payload']), entry['record']) and row['logical_key'] == entry['logical_key']
              and row['kind'] == entry['record']['kind'], 'EVIDENCE_SCOPE', 'captured normalized record differs from saved evidence')
    physical = {key[0]: value for key, value in t['receipts'].items()}
    _need({r['receipt_hash'] for r in physical.values()} == set(receipts), 'EVIDENCE_SCOPE', 'required receipt coverage differs')
    groups = {rid: [] for rid in receipts}
    for row_id, row in physical.items():
        rid = row['receipt_hash']
        _need(_same(_json_text(row['raw']), receipts[rid]), 'RECEIPT_BINDING', 'captured raw receipt differs from immutable run')
        _need(row['status'] in ('ACCEPTED', 'DUPLICATE', 'CONFLICT', 'INVALID'), 'RECEIPT_BINDING', 'unsupported receipt status')
        try:
            normalized_time = timestamp(receipts[rid]['received_at'])
        except (ValueError, TypeError, OverflowError):
            normalized_time = None
        _need(row['received_at'] == normalized_time, 'RECEIPT_BINDING', 'captured receipt normalized time differs')
        if rid in quarantine:
            _need(row['record_id'] is None and row['status'] == 'INVALID' and row['error'] == quarantine[rid],
                  'RECEIPT_BINDING', 'quarantine relationship differs from immutable run')
        else:
            _need(row['record_id'] == record_for_receipt.get(rid) and row['record_id'] in stored
                  and row['status'] != 'INVALID' and row['error'] is None,
                  'RECEIPT_BINDING', 'record-to-receipt relationship differs from immutable run')
        groups[rid].append(row_id)
    return physical, groups


def _policies(t, expected, config, data):
    auth_names = [name for name in COLUMNS if name.startswith('auth_')]
    if expected['profile'] == 'legacy':
        _need(all(not t[name] for name in auth_names), 'PROFILE_MISMATCH', 'legacy expectations cannot conceal protected authorization rows')
        return {}, {}, {}
    protection = list(t['auth_configuration'].values())
    _need(len(protection) == 1 and protection[0]['id'] == 1
          and protection[0]['receiver'] == expected['receiver']
          and protection[0]['configuration_digest'] == expected['configuration_digest'],
          'PROFILE_MISMATCH', 'protected receiver/configuration binding differs')
    _need(protection[0]['initial_policy_hash'] == expected['policies'][0]['policy_hash'],
          'POLICY_BINDING', 'initial policy differs from the operator policy map')
    epochs = {key[0]: row for key, row in t['auth_policy_activations'].items()}
    bodies = {key[0]: row for key, row in t['auth_policy_snapshots'].items()}
    _need(set(epochs) == set(range(1, len(expected['policies'])+1)), 'POLICY_BINDING', 'capture hides or adds policy epochs')
    _need(set(bodies) == {p['policy_hash'] for p in expected['policies']}, 'POLICY_BINDING', 'activated policy inventory differs')
    policies, first_keys, old_keys, old_sources = {}, {}, {}, {}
    for spec in expected['policies']:
        epoch, policy_hash = spec['epoch'], spec['policy_hash']
        row = epochs[epoch]
        _need(row['policy_hash'] == policy_hash and row['previous_epoch'] == (epoch-1 if epoch>1 else None)
              and row['previous_hash'] == (epochs[epoch-1]['policy_hash'] if epoch>1 else None),
              'POLICY_BINDING', 'activation predecessor or trusted policy identity differs')
        raw = bodies[policy_hash]['payload'].encode('utf-8')
        name = 'materials/policies/' + policy_hash + '.json'
        _need(name in data and data[name] == raw, 'POLICY_BINDING', 'original policy material is missing or changed')
        value = validate_policy(raw, config, expected['receiver'])
        _need(sha256(canonical(value)) == policy_hash and raw == canonical(value),
              'POLICY_BINDING', 'policy body is not the activated canonical policy')
        keys = {k['key_id']: k for k in value['keys']}
        sources = {s['source']: s for s in value['sources']}
        for kid, old in old_keys.items():
            new = keys.get(kid)
            _need(new is not None and all(new[k] == old[k] for k in ('source', 'public_key', 'fingerprint'))
                  and (old['status'] != 'revoked' or new['status'] == 'revoked'),
                  'POLICY_BINDING', 'historical key identity or revocation changed')
        for source, old in old_sources.items():
            _need(source in sources and old['namespace'] == sources[source]['namespace'],
                  'POLICY_BINDING', 'historical source namespace changed')
        for kid, key in keys.items():
            first_keys.setdefault(kid, {'key_id': kid, **{k: key[k] for k in ('source', 'public_key', 'fingerprint')}, 'first_epoch': epoch})
        old_keys, old_sources = keys, sources
        policies[epoch] = value
    keys = {key[0]: row for key, row in t['auth_keys'].items()}
    _need(_same(keys, first_keys), 'POLICY_BINDING', 'persistent key registry differs from activated policy history')
    return policies, keys, old_keys


def _endorsements(t, policies, keys, expected, config, data, partial):
    claims = {}
    for (eid,), row in t['auth_endorsements'].items():
        payload = _blob(row['payload'], MAX_PAYLOAD, 'SOURCE_SIGNATURE')
        envelope = _blob(row['envelope'], MAX_ENVELOPE, 'SOURCE_SIGNATURE')
        name = 'materials/envelopes/' + eid + '.json'
        _need(name in data and data[name] == envelope, 'SOURCE_SIGNATURE', 'original envelope material missing or changed')
        decoded, kid, signature = parse_envelope(envelope)
        _need(decoded == payload and kid in keys, 'SOURCE_SIGNATURE', 'payload or persistent key binding differs')
        key = keys[kid]
        verify_signature(bytes.fromhex(key['public_key']), pae(PAYLOAD_TYPE, payload), signature)
        statement = parse_json(payload, limit=MAX_PAYLOAD)
        fields = {'format', 'source', 'receiver', 'configuration_digest', 'stream_id', 'plan', 'capabilities'}
        _need(type(statement) is dict and set(statement) == fields and statement['format'] == 'source-admission-statement-v1',
              'SIGNED_SCOPE', 'signed statement fields differ')
        _need(all(type(statement[k]) is str and IDENTIFIER.fullmatch(statement[k]) for k in ('source', 'receiver', 'stream_id')),
              'SIGNED_SCOPE', 'signed authority identifiers are invalid')
        plan_hash = validate_plan(statement['plan'])
        caps = capability_inventory(statement['capabilities'], config)
        _need(all(c['source'] == statement['source'] for c in caps),
              'SIGNED_SCOPE', 'signed capability inventory differs')
        _need(statement['receiver'] == expected['receiver'] and statement['configuration_digest'] == expected['configuration_digest']
              and statement['source'] == key['source'], 'SIGNED_SCOPE', 'signed source/receiver/configuration binding differs')
        derived_id = sha256(canonical({'payload_sha256': sha256(payload), 'signature': signature.hex(),
                                     'fingerprint': key['fingerprint'], 'key_id': kid}))
        _need(eid == derived_id and all(row[field] == wanted for field, wanted in {
            'source': statement['source'], 'key_id': kid, 'fingerprint': key['fingerprint'],
            'statement_hash': sha256(payload), 'snapshot_hash': statement['plan']['input_sha256'],
            'plan_hash': plan_hash}.items()), 'ENDORSEMENT_BINDING', 'endorsement content identity or immutable fields differ')
        snapshot_name = 'materials/snapshots/' + row['snapshot_hash'] + '.jsonl'
        snapshot = None
        if snapshot_name in data:
            snapshot = snapshot_bytes(data[snapshot_name])
            validate_statement(statement, snapshot, config)
        else:
            partial.append({'code': 'MISSING_SIGNED_SNAPSHOT', 'message': 'Full signed snapshot is not supplied',
                            'endorsement_id': eid, 'snapshot_hash': row['snapshot_hash']})
        claims[eid] = {'statement': statement, 'key': key, 'snapshot': snapshot,
                       'envelope_member': name, 'snapshot_member': snapshot_name}
    return claims


def _deliveries(t, physical, expected, policies, keys, current_keys, claims, config):
    effects, attempts, streams = t['delivery_effects'], t['delivery_attempts'], t['admission_streams']
    covered = [e['core_receipt_id'] for e in effects.values()]
    _need(len(covered) == len(set(covered)) and set(covered) <= set(physical), 'DELIVERY_RELATION', 'effect-to-receipt identity is not unique')
    _need(set(streams) == {(sid,) for sid, seq in effects}, 'DELIVERY_RELATION', 'selected stream inventory differs from effects')
    protected = expected['profile'] == 'protected'
    if protected:
        _need(set(covered) == set(physical) and set(t['auth_delivery_links']) == set(effects)
              and set(t['auth_streams']) == set(streams), 'PROTECTED_LINK', 'protected receipt lacks its original effect/link/owner')
    selected_positions = set(effects)
    _need(all((a['stream_id'], a['sequence']) in selected_positions for a in attempts.values()),
          'DELIVERY_RELATION', 'attempt is outside selected receipt positions')
    for (sid,), stream in streams.items():
        plan = {'format': 'admission-plan-v1', **{k: stream[k] for k in ('input_sha256', 'input_bytes', 'planned_lines', 'framing')}}
        _need(validate_plan(plan) == stream['plan_hash'], 'DELIVERY_RELATION', 'stream plan identity differs')
    committed = {}
    for (aid,), attempt in attempts.items():
        pos = attempt['stream_id'], attempt['sequence']
        raw = _blob(attempt['payload'], 65536)
        _need(sha256(raw) == attempt['payload_sha256'] and _hex(attempt['plan_hash']), 'DELIVERY_RELATION', 'attempt exact byte identity differs')
        _need(attempt['outcome'] in ('COMMITTED', 'REPLAY', 'TRANSPORT_CONFLICT', 'PLAN_CONFLICT', 'BLOCKED', 'GAP', 'OUT_OF_RANGE'),
              'DELIVERY_RELATION', 'unknown attempt outcome')
        effect_ref = attempt['effect_stream_id'], attempt['effect_sequence']
        _need(effect_ref in (pos, (None, None)), 'DELIVERY_RELATION', 'attempt effect reference differs')
        if attempt['outcome'] in ('COMMITTED', 'REPLAY'):
            effect = effects[pos]
            _need(effect_ref == pos and raw.hex() == effect['payload'] and attempt['payload_sha256'] == effect['payload_sha256']
                  and attempt['plan_hash'] == streams[(pos[0],)]['plan_hash'], 'DELIVERY_RELATION', 'successful attempt differs from immutable effect/plan')
        if attempt['outcome'] == 'COMMITTED':
            _need(pos not in committed, 'DELIVERY_RELATION', 'more than one original committed attempt')
            committed[pos] = aid
    _need(set(committed) == set(effects), 'DELIVERY_RELATION', 'effect lacks its sole original COMMITTED attempt')
    for (aid,), attempt in attempts.items():
        if attempt['effect_stream_id'] is not None:
            pos = attempt['stream_id'], attempt['sequence']
            # The effect and its COMMITTED attempt are inserted atomically.
            # An earlier GAP without an effect reference remains admissible.
            _need(aid >= committed[pos], 'DELIVERY_CAUSALITY',
                  'effect-referencing attempt precedes its original COMMITTED attempt')
    for pos, effect in effects.items():
        _need(_positive(pos[1], streams[(pos[0],)]['planned_lines']), 'DELIVERY_RELATION', 'effect sequence outside signed plan')
        raw = _blob(effect['payload'], 65536)
        _need(raw.endswith(b'\n') and raw.count(b'\n') == 1 and b'\r' not in raw and not raw.startswith(b'\xef\xbb\xbf')
              and sha256(raw) == effect['payload_sha256'], 'DELIVERY_RELATION', 'effect line framing/hash differs')
        envelope = parse_json(raw, limit=65536)
        receipt = physical[effect['core_receipt_id']]
        _need(type(envelope) is dict and set(envelope) == {'record', 'received_at'}
              and _same(envelope, _json_text(receipt['raw'])) and sha256(canonical(envelope)) == receipt['receipt_hash'],
              'DELIVERY_RELATION', 'effect line differs from receipt content')
        core = _json_text(effect['core_result'])
        wanted = {'receipt_id': receipt['receipt_hash'], 'record_id': receipt['record_id'], 'status': receipt['status'],
                  'error': receipt['error'], 'reason_code': receipt['error'].split(':', 1)[0] if receipt['error'] and ':' in receipt['error'] else None}
        _need(_same(core, wanted) and effect['core_receipt_hash'] == receipt['receipt_hash']
              and effect['disposition'] == receipt['status'], 'DELIVERY_RELATION', 'captured core result or disposition differs')
    if not protected:
        return [{'receipt_hash': r['receipt_hash'], 'row_id': rid, 'source_admission': 'UNSIGNED_LEGACY',
                 'run_creation_authorization_cut': 'NOT_RECORDED'} for rid, r in physical.items()]
    decisions, links, attempt_links = t['auth_decisions'], t['auth_delivery_links'], t['auth_attempt_links']
    _need(set(attempt_links) == set(attempts), 'PROTECTED_LINK', 'protected attempt decision coverage differs')
    decision_refs = [row['decision_id'] for row in attempt_links.values()]
    _need(len(decision_refs) == len(set(decision_refs)) and set(decisions) == {(d,) for d in decision_refs}
          and {d['endorsement_id'] for d in decisions.values()} == set(claims),
          'PROTECTED_LINK', 'decision/endorsement inventory differs from selected attempts')
    for (aid,), attempt in attempts.items():
        pos = attempt['stream_id'], attempt['sequence']
        if attempt['effect_stream_id'] is not None and aid != committed[pos]:
            original_did = attempt_links[(committed[pos],)]['decision_id']
            # Compare persistent IDs within each table, never across namespaces
            # or via list position / untrusted observed_at wall-clock values.
            _need(attempt_links[(aid,)]['decision_id'] > original_did,
                  'DELIVERY_CAUSALITY',
                  'effect-referencing decision precedes its original COMMITTED decision')
    for (did,), decision in decisions.items():
        epoch = decision['epoch']
        _need(epoch in policies and decision['policy_hash'] == expected['policies'][epoch-1]['policy_hash']
              and decision['endorsement_id'] in claims, 'PROTECTED_LINK', 'decision has missing policy or endorsement')
        claim = claims[decision['endorsement_id']]
        statement = claim['statement']
        policy = policies[epoch]
        key = next((k for k in policy['keys'] if k['key_id'] == claim['key']['key_id']), None)
        source = next((s for s in policy['sources'] if s['source'] == statement['source']), None)
        _need(key is not None and source is not None and decision['current_key_status'] == key['status']
              and decision['stream_id'] == statement['stream_id'] and _positive(decision['sequence'], statement['plan']['planned_lines'])
              and decision['stream_id'].startswith(source['namespace']), 'POLICY_BINDING', 'decision source/key/namespace differs from original policy')
        if decision['decision'] == 'CURRENT':
            _need(key['status'] == 'active' and all(cap in source['capabilities'] for cap in statement['capabilities']),
                  'POLICY_BINDING', 'original policy does not authorize signed capabilities')
        elif decision['decision'] == 'HISTORICAL_REPLAY':
            pos = decision['stream_id'], decision['sequence']
            link = links.get(pos)
            original = decisions.get((link['decision_id'],)) if link else None
            _need(key['status'] == 'revoked' and original is not None and original['id'] < did
                  and original['epoch'] < epoch and original['decision'] == 'CURRENT'
                  and original['endorsement_id'] == decision['endorsement_id'],
                  'PROTECTED_LINK', 'historical replay lacks its original current approval')
        else:
            _need(False, 'PROTECTED_LINK', 'unknown authorization decision kind')
    observed_lines = {}
    for (aid,), attempt in attempts.items():
        decision = decisions[(attempt_links[(aid,)]['decision_id'],)]
        pos = attempt['stream_id'], attempt['sequence']
        claim = claims[decision['endorsement_id']]
        statement = claim['statement']
        _need((decision['stream_id'], decision['sequence']) == pos and attempt['plan_hash'] == sha256(canonical(statement['plan'])),
              'PROTECTED_LINK', 'attempt/decision/signed plan identity differs')
        # An absent full snapshot prevents proving membership, but cannot hide
        # an available line whose authority contradicts the signed statement.
        line = bytes.fromhex(attempt['payload'])
        listed = observed_lines.setdefault(decision['endorsement_id'], {})
        _need(pos[1] not in listed or listed[pos[1]] == line,
              'SIGNED_SCOPE', 'one signed source position has conflicting observed bytes')
        listed[pos[1]] = line
        observed_scope = capabilities(snapshot_bytes(line), config)
        _need(all(cap in statement['capabilities'] for cap in observed_scope),
              'SIGNED_SCOPE', 'observed delivery line exceeds its signed capability inventory')
        if claim['snapshot'] is not None:
            _need(attempt['payload'] == claim['snapshot'].lines[pos[1]-1].hex(), 'DELIVERY_RELATION', 'attempt is not its original signed source line')
        if decision['decision'] == 'HISTORICAL_REPLAY':
            _need(attempt['outcome'] in ('REPLAY', 'BLOCKED'), 'PROTECTED_LINK', 'revoked historical approval creates a new effect')
    for eid, listed in observed_lines.items():
        _need(sum(len(line) for line in listed.values()) <= claims[eid]['statement']['plan']['input_bytes'],
              'SIGNED_SCOPE', 'observed distinct source lines exceed the signed full byte count')
    chains = []
    for pos, effect in effects.items():
        link = links[pos]
        original = decisions.get((link['decision_id'],))
        aid = committed[pos]
        _need(original is not None and original['decision'] == 'CURRENT'
              and (original['stream_id'], original['sequence']) == pos
              and link['core_receipt_id'] == effect['core_receipt_id']
              and attempt_links[(aid,)]['decision_id'] == original['id'],
              'PROTECTED_LINK', 'effect does not point to its original COMMITTED/current acceptance')
        claim = claims[original['endorsement_id']]
        statement = claim['statement']
        owner = t['auth_streams'][(pos[0],)]
        stream = streams[(pos[0],)]
        _need(all(owner[k] == statement[k] for k in ('source', 'receiver', 'configuration_digest'))
              and owner['plan_hash'] == sha256(canonical(statement['plan']))
              and all(stream[k] == statement['plan'][k] for k in ('input_sha256', 'input_bytes', 'planned_lines', 'framing')),
              'PROTECTED_LINK', 'stream owner/immutable plan differs from original acceptance')
        if claim['snapshot'] is not None:
            _need(effect['payload'] == claim['snapshot'].lines[pos[1]-1].hex(), 'DELIVERY_RELATION', 'effect is not its original signed source line')
        key_id = claim['key']['key_id']
        chains.append({'receipt_hash': effect['core_receipt_hash'], 'row_id': effect['core_receipt_id'],
                       'stream_id': pos[0], 'sequence': pos[1], 'committed_attempt_id': aid,
                       'original_decision_id': original['id'], 'original_policy_epoch': original['epoch'],
                       'original_policy_hash': original['policy_hash'], 'endorsement_id': original['endorsement_id'],
                       'key_id': key_id, 'current_key_status': current_keys[key_id]['status'],
                       'capture_policy_epoch': expected['policy_head']['epoch'],
                       'source': statement['source'], 'source_line': bytes.fromhex(effect['payload']).decode('utf-8'),
                       'line_sha256': effect['payload_sha256'], 'envelope_member': claim['envelope_member'],
                       'snapshot_member': claim['snapshot_member'],
                       'source_admission': 'VERIFIED' if claim['snapshot'] is not None else 'MISSING_MATERIAL',
                       'replay_attempt_ids': [a['id'] for a in attempts.values() if (a['stream_id'], a['sequence']) == pos and a['outcome'] == 'REPLAY'],
                       'run_creation_authorization_cut': 'NOT_RECORDED'})
    return sorted(chains, key=lambda x: (x['receipt_hash'], x['row_id']))


def verify_bundle(bundle, expectations):
    """Return a machine report with exit 0, 3 or 2; never mutate the bundle."""
    result = {'format': 'run-provenance-verification-v1', 'status': 'FAILED', 'exit_code': 2,
              'run_identity': 'FAILED', 'listed_evidence_coverage': 'PARTIAL', 'capture_binding': 'FAILED',
              'source_admission': 'INCONSISTENT', 'physical_receipt_binding': None,
              'run_creation_authorization_cut': 'NOT_RECORDED', 'financial_recomputation': 'NOT_PERFORMED',
              'reasons': [], 'candidates': [], 'financial': []}
    try:
        require_auth()
        root = Path(bundle)
        _need(root.is_dir() and not root.is_symlink(), 'BUNDLE_PATH', 'bundle must be a real directory')
        root = root.resolve(strict=True)
        expected = _load_expectations(expectations, root)
        manifest, manifest_raw, data = _load_members(root)
        result['bundle_digest'] = sha256(manifest_raw)
        result['run_id'] = expected['run_id']
        _need(manifest['run_id'] == expected['run_id'] and sha256(data['run.json']) == expected['run_payload_sha256'],
              'RUN_IDENTITY', 'selected run or original payload bytes differ from external expectations')
        run = parse_json(data['run.json'], limit=MAX_JSON)
        _need(type(run) is dict and sha256(canonical(run)) == expected['run_id'], 'RUN_IDENTITY', 'canonical saved run ID differs')
        validate_payload(data['run.json'].decode('utf-8'), expected['run_id'], 5)
        result['run_identity'] = 'VERIFIED'
        result['financial'] = run['findings']
        records, receipts, record_for_receipt, quarantine, findings = _scope(run)
        capture = parse_json(data['capture.json'], limit=MAX_CAPTURE)
        t = _tables(capture)
        _need(_same(capture['configuration'], run['configuration'])
              and sha256(canonical(run['configuration'])) == expected['configuration_digest'],
              'CONFIGURATION_BINDING', 'saved run/capture/external configuration differs')
        _need(sha256(canonical(capture)) == expected['capture_digest'], 'CAPTURE_BINDING', 'capture differs from external observation pin')
        result['capture_binding'] = 'MATCHES_EXTERNAL_OBSERVATION'
        report = parse_json(data['report.json'], limit=MAX_JSON)
        _report(report, run, expected, records, receipts, findings)
        _presentation(data, run, capture, report, manifest)
        physical, groups = _receipt_rows(t, records, receipts, record_for_receipt, quarantine)
        result['listed_evidence_coverage'] = 'COMPLETE'
        policies, keys, current_keys = _policies(t, expected, run['configuration'], data)
        partial = []
        claims = _endorsements(t, policies, keys, expected, run['configuration'], data, partial) if expected['profile'] == 'protected' else {}
        allowed_material = {'materials/policies/' + key[0] + '.json' for key in t['auth_policy_snapshots']}
        allowed_material |= {'materials/envelopes/' + key[0] + '.json' for key in t['auth_endorsements']}
        allowed_material |= {'materials/snapshots/' + row['snapshot_hash'] + '.jsonl' for row in t['auth_endorsements'].values()}
        _need({name for name in data if name.startswith('materials/')} <= allowed_material,
              'MATERIAL_SCOPE', 'material has no captured policy or endorsement relationship')
        result['candidates'] = _deliveries(t, physical, expected, policies, keys, current_keys, claims, run['configuration'])
        multiple = any(len(rows) > 1 for rows in groups.values())
        result['physical_receipt_binding'] = 'MULTIPLE_CANDIDATES' if multiple else 'UNIQUE_CANDIDATE'
        if multiple:
            partial.append({'code': 'MULTIPLE_RECEIPT_CANDIDATES', 'message': 'Capture contains multiple physical candidates; no preferred historic origin is selected'})
        if expected['profile'] == 'legacy':
            partial.append({'code': 'UNSIGNED_LEGACY', 'message': 'Genuine legacy observation has no source authorization'})
        result['source_admission'] = 'UNSIGNED_LEGACY' if expected['profile'] == 'legacy' else ('MISSING_MATERIAL' if any(r['code']=='MISSING_SIGNED_SNAPSHOT' for r in partial) else 'VERIFIED')
        result['reasons'] = partial
        result['status'], result['exit_code'] = ('PARTIAL', 3) if partial else ('VERIFIED_FOR_CAPTURE', 0)
        result['receipt_candidates'] = [{'receipt_hash': rid, 'physical_row_ids': rows} for rid, rows in sorted(groups.items())]
        return result
    except (ProvenanceError, AuthError) as exc:
        result['reasons'] = [{'code': exc.code, 'message': str(exc)}]
    except ReviewError as exc:
        result['reasons'] = [{'code': 'RUN_IDENTITY', 'message': str(exc)}]
    except (OSError, ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError) as exc:
        result['reasons'] = [{'code': 'PROVENANCE_INPUT', 'message': str(exc)}]
    result['status'], result['exit_code'], result['source_admission'] = 'FAILED', 2, 'INCONSISTENT'
    return result
