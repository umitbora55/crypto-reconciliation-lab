"""S11-F2: exact physical identities before the browser's JSON number parser.

The literal string expectations do not come from the renderer or verifier.
The same file is executed unchanged against 0.9.0 and the repaired package.
"""
import copy
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from crypto_reconciliation_lab.provenance.demo import build_fixture
from crypto_reconciliation_lab.provenance.exporter import export_provenance
from crypto_reconciliation_lab.provenance.ui import render_page
from crypto_reconciliation_lab.provenance.verifier import verify_bundle


BOUNDARIES = (9007199254740991, 9007199254740992, 9007199254740993, 9223372036854775807)
IDENTITY_FIELDS = {
    'receipts': ('id',), 'delivery_effects': ('sequence', 'core_receipt_id'),
    'delivery_attempts': ('id', 'sequence', 'effect_sequence'), 'auth_configuration': ('id',),
    'auth_policy_activations': ('epoch', 'previous_epoch'), 'auth_keys': ('first_epoch',),
    'auth_decisions': ('id', 'epoch', 'sequence'),
    'auth_delivery_links': ('sequence', 'decision_id', 'core_receipt_id'),
    'auth_attempt_links': ('attempt_id', 'decision_id'),
}


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def load(path):
    return json.loads(Path(path).read_bytes())


def unpack(raw):
    prefix, suffix = b'window.PROVENANCE_DATA = JSON.parse(', b');\n'
    if not raw.startswith(prefix) or not raw.endswith(suffix):
        raise AssertionError('unexpected deterministic data wrapper')
    return json.loads(json.loads(raw[len(prefix):-len(suffix)]))


def seal_files(bundle):
    manifest = load(bundle/'manifest.json')
    manifest['files'] = {p.relative_to(bundle).as_posix(): {'bytes': len(p.read_bytes()), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                         for p in sorted(bundle.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
    (bundle/'manifest.json').write_bytes(encode(manifest))


def large_identity_fixture(root, *, scenario='clean', offset=None):
    """Controlled test SQL copy; no authoritative format or financial edits.

    Changing local PK/FKs and refreshing this fixture operator's capture pin is
    explicit. Original fixtures, raw run and signed material remain unchanged.
    """
    fixture = build_fixture(root/'original', scenario=scenario)
    database = root/'large-ids.sqlite3'
    shutil.copyfile(fixture['database'], database)
    capture = load(root/'original/operator-observation/original.json')
    if offset is None:
        maps = {table: {row['id']: value for row, value in zip(capture['tables'][table][:4], BOUNDARIES)}
                for table in ('receipts', 'delivery_attempts', 'auth_decisions')}
    else:
        maps = {table: {row['id']: row['id'] + offset for row in capture['tables'][table]}
                for table in ('receipts', 'delivery_attempts', 'auth_decisions')}
    targets = {'receipts': {'id': maps['receipts']},
               'delivery_effects': {'core_receipt_id': maps['receipts']},
               'delivery_attempts': {'id': maps['delivery_attempts']},
               'auth_decisions': {'id': maps['auth_decisions']},
               'auth_delivery_links': {'core_receipt_id': maps['receipts'], 'decision_id': maps['auth_decisions']},
               'auth_attempt_links': {'attempt_id': maps['delivery_attempts'], 'decision_id': maps['auth_decisions']}}
    with closing(sqlite3.connect(database)) as db, db:
        triggers = []
        for table in targets:
            trigger = db.execute("SELECT name,sql FROM sqlite_master WHERE name=? AND type='trigger'", ('immutable_' + table + '_UPDATE',)).fetchone()
            assert trigger, table
            triggers.append(trigger)
            db.execute('DROP TRIGGER ' + trigger[0])
        for table, fields in targets.items():
            for column, mapping in fields.items():
                for old, new in mapping.items():
                    db.execute('UPDATE ' + table + ' SET ' + column + '=? WHERE ' + column + '=?', (new, old))
            for row in capture['tables'][table]:
                for column, mapping in fields.items():
                    row[column] = mapping.get(row[column], row[column])
        for _, sql in triggers:
            db.execute(sql)
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert list(db.execute('PRAGMA foreign_key_check')) == []
    for table, key in (('receipts', 'id'), ('delivery_attempts', 'id'), ('auth_decisions', 'id'), ('auth_attempt_links', 'attempt_id')):
        capture['tables'][table].sort(key=lambda row: row[key])
    raw = database.read_bytes()
    capture['database'] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    expected = load(fixture['expectations'])
    expected['capture_digest'] = hashlib.sha256(encode(capture)).hexdigest()
    path = root/'expectations.json'
    path.write_bytes(encode(expected))
    return {**fixture, 'database': database, 'expectations': path}, capture


class ProvenanceIdentityTransportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)

    def test_every_physical_identity_field_is_exact_text_before_javascript_parse(self):
        tables = {table: [{column: value for column in columns} for value in BOUNDARIES]
                  for table, columns in IDENTITY_FIELDS.items()}
        original = {'schema_version': 5, 'tables': tables}
        preserved = copy.deepcopy(original)
        actual = unpack(render_page({}, {}, original, {})['data.js'])['capture']
        for table, columns in IDENTITY_FIELDS.items():
            for i, row in enumerate(actual['tables'][table]):
                for column in columns:
                    with self.subTest(table=table, column=column, value=BOUNDARIES[i]):
                        self.assertEqual(row[column], ('9007199254740991', '9007199254740992', '9007199254740993', '9223372036854775807')[i])
                        self.assertIs(type(row[column]), str)
        self.assertEqual(original, preserved)
        self.assertIs(type(actual['schema_version']), int)

    def test_null_hashes_financial_strings_and_hostile_keys_remain_unchanged(self):
        raw = {'tables': {'receipts': [{'id': 9007199254740993, 'receipt_hash': 'a'*64,
                                      'record_id': None, 'raw': '{"amount":"0.10","id":9007199254740993}'}],
                          'delivery_attempts': [{'id': 9007199254740992, 'sequence': 2, 'effect_sequence': None}],
                          '__proto__': [{'hostile': '</script><img src=x onerror="BAD=1">'}]}}
        run = {'amount': '0.10', '__proto__': {'own': True}}
        actual = unpack(render_page(run, {}, raw, {})['data.js'])
        self.assertEqual(actual['run'], run)
        self.assertEqual(actual['capture']['tables']['receipts'][0]['id'], '9007199254740993')
        self.assertEqual(actual['capture']['tables']['receipts'][0]['raw'], raw['tables']['receipts'][0]['raw'])
        self.assertEqual(actual['capture']['tables']['receipts'][0]['receipt_hash'], 'a'*64)
        self.assertIsNone(actual['capture']['tables']['delivery_attempts'][0]['effect_sequence'])
        self.assertEqual(actual['capture']['tables']['__proto__'], raw['tables']['__proto__'])

    def exported_large(self, *, scenario='clean', offset=None):
        fixture, expected_capture = large_identity_fixture(self.root, scenario=scenario, offset=offset)
        bundle = self.root/'bundle'
        export_provenance(fixture['database'], fixture['run_id'], fixture['material_dir'], bundle)
        self.assertEqual(load(bundle/'capture.json'), expected_capture)
        result = verify_bundle(bundle, fixture['expectations'])
        self.assertEqual(result['exit_code'], 0, result)
        self.assertEqual(result['run_creation_authorization_cut'], 'NOT_RECORDED')
        return fixture, bundle, unpack((bundle/'data.js').read_bytes())

    def test_supported_sql_boundaries_export_verify_and_keep_distinct_receipt_paths(self):
        fixture, bundle, data = self.exported_large()
        with closing(sqlite3.connect(fixture['database'])) as db:
            self.assertEqual((bundle/'run.json').read_bytes(), db.execute('SELECT payload FROM runs WHERE id=?', (fixture['run_id'],)).fetchone()[0].encode())
        raw = load(bundle/'capture.json')['tables']
        shown = data['capture']['tables']
        self.assertTrue(set(map(str, BOUNDARIES)) <= {r['id'] for r in shown['receipts']}, 'supported SQL identities must arrive as exact text before JS JSON.parse')
        for wanted in BOUNDARIES:
            receipt = next(r for r in shown['receipts'] if r['id'] == str(wanted))
            effects = [e for e in shown['delivery_effects'] if e['core_receipt_id'] == receipt['id']]
            self.assertEqual(len(effects), 1)
            self.assertEqual(effects[0]['core_receipt_hash'], receipt['receipt_hash'])
            self.assertEqual(sum(r['id'] == wanted for r in raw['receipts']), 1)
        self.assertTrue(all(type(r['id']) is int for r in raw['receipts']))

    def test_large_attempt_decision_and_replay_paths_are_distinct(self):
        _, _, data = self.exported_large(scenario='rotation', offset=9007199254740991)
        tables = data['capture']['tables']
        original = next(row for row in tables['auth_delivery_links'] if row['stream_id'] == 'lark-feed:financial' and str(row['sequence']) == '1')
        self.assertEqual(original['decision_id'], '9007199254740992')
        linked = [row for row in tables['auth_decisions'] if row['id'] == original['decision_id']]
        self.assertEqual(len(linked), 1)
        self.assertEqual(linked[0]['decision'], 'CURRENT')
        attempts = [r for r in tables['delivery_attempts'] if r['stream_id'] == 'lark-feed:financial' and str(r['sequence']) == '1']
        self.assertEqual({(r['id'], r['outcome']) for r in attempts}, {('9007199254740992', 'COMMITTED'), ('9007199254741022', 'REPLAY')})
        identities = {r['id'] for r in attempts}
        links = [r for r in tables['auth_attempt_links'] if r['attempt_id'] in identities]
        self.assertEqual({r['decision_id'] for r in links}, {'9007199254740992', '9007199254741022'})

    def test_tampered_transport_identity_is_rejected_after_manifest_refresh(self):
        fixture, bundle, data = self.exported_large()
        data['capture']['tables']['receipts'][-1]['id'] = '9007199254740992'
        (bundle/'data.js').write_bytes(b'window.PROVENANCE_DATA = JSON.parse(' + encode(encode(data).decode('ascii')) + b');\n')
        seal_files(bundle)
        result = verify_bundle(bundle, fixture['expectations'])
        self.assertEqual((result['exit_code'], result['reasons'][0]['code']), (2, 'PRESENTATION_INTEGRITY'))

    def test_small_ids_and_genuine_ambiguity_remain_visible(self):
        fixture = build_fixture(self.root/'fixture', scenario='ambiguous')
        bundle = self.root/'bundle'
        export_provenance(fixture['database'], fixture['run_id'], fixture['material_dir'], bundle)
        result = verify_bundle(bundle, fixture['expectations'])
        self.assertEqual((result['exit_code'], result['reasons'][0]['code']), (3, 'MULTIPLE_RECEIPT_CANDIDATES'))
        raw = load(bundle/'capture.json')['tables']['receipts']
        displayed = unpack((bundle/'data.js').read_bytes())['capture']['tables']['receipts']
        self.assertEqual(len(raw), len(displayed))
        self.assertEqual({str(r['id']) for r in raw}, {str(r['id']) for r in displayed})
        self.assertEqual(len(raw), 31)


if __name__ == '__main__':
    unittest.main()
