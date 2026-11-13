"""Read-only snapshot, identity, reference and lossless display regression tests."""
from copy import deepcopy
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from crypto_reconciliation_lab.review.adapter import read_selection, read_selected_sources
from crypto_reconciliation_lab.review.validation import ReviewError, validate_payload
from crypto_reconciliation_lab.review.viewmodel import build_run_view

ROOT = Path(__file__).resolve().parents[1]


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def identity(payload):
    return hashlib.sha256(wire(payload).encode()).hexdigest()


def make_snapshot(path, payload, schema=3, *, text=None, mirrors=True):
    """Owned test fixture; literals are not recomputed by the production evaluator."""
    run_id = identity(payload); text = wire(payload) if text is None else text
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE runs(id TEXT PRIMARY KEY,balance_at TEXT,knowledge_at TEXT,payload TEXT)')
    db.execute('CREATE TABLE configuration(id INTEGER PRIMARY KEY,payload TEXT)')
    db.execute('CREATE TABLE records(id TEXT PRIMARY KEY,payload TEXT)')
    db.execute('CREATE TABLE receipts(id INTEGER PRIMARY KEY,raw TEXT)')
    # Deliberately unrelated current config and records must never enrich history.
    db.execute('INSERT INTO configuration VALUES(1,?)', ('{"current":"DO NOT USE"}',))
    db.execute('INSERT INTO records VALUES(?,?)', ('later-record', '{"amount":"999"}'))
    db.execute('INSERT INTO receipts VALUES(1,?)', ('{"received_at":"2099-01-01T00:00:00Z"}',))
    db.execute('INSERT INTO runs VALUES(?,?,?,?)', (run_id, payload['balance_at'], payload['knowledge_at'], text))
    if mirrors:
        db.execute('CREATE TABLE findings(run_id TEXT,ordinal INTEGER,payload TEXT,PRIMARY KEY(run_id,ordinal))')
        db.execute('CREATE TABLE evidence(run_id TEXT,evidence_id TEXT,payload TEXT,PRIMARY KEY(run_id,evidence_id))')
        db.executemany('INSERT INTO findings VALUES(?,?,?)', [(run_id, i, wire(f)) for i, f in enumerate(payload['findings'])])
        db.executemany('INSERT INTO evidence VALUES(?,?,?)', [(run_id, key, wire(value)) for key, value in payload['evidence'].items()])
    db.execute('PRAGMA user_version=' + str(schema)); db.commit(); db.close()
    return run_id


class ReviewAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        old = json.loads((ROOT / 'fixtures/stage1_history.json').read_text())
        cls.stage1 = json.loads(old['runs']['rows'][0][-1])
        cls.stage1_id = old['runs']['rows'][0][0]
        correction = json.loads((ROOT / 'fixtures/stage3_3_schema2_history.json').read_text())
        cls.stage2 = json.loads(correction['tables']['runs']['rows'][-1][-1])
        cls.stage2_id = correction['tables']['runs']['rows'][-1][0]

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='review-adapter-test-')
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def selection(self, path, run_ids, *, alias='case', extra=None):
        data = {'format': 'review-selection-v1', 'sources': [{'alias': alias, 'database': path.name, 'run_ids': run_ids}]}
        if extra: data['sources'][0].update(extra)
        target = self.root / 'selection.json'; target.write_text(wire(data))
        return target

    def run_fixture(self, payload=None, *, schema=3, mirrors=True, text=None, name='snapshot.sqlite3'):
        path = self.root / name
        run_id = make_snapshot(path, deepcopy(self.stage2 if payload is None else payload), schema, mirrors=mirrors, text=text)
        return path, run_id, self.selection(path, [run_id])

    def assert_unchanged_error(self, selection, path, code=None):
        before = path.read_bytes()
        with self.assertRaises(ReviewError) as raised: read_selected_sources(selection)
        self.assertEqual(path.read_bytes(), before)
        if code: self.assertEqual(raised.exception.code, code)
        self.assertEqual(raised.exception.alias, 'case')
        self.assertTrue(raised.exception.audit['source_preservation_verified'])
        return raised.exception

    def test_schema_zero_two_three_legacy_rule_and_configuration_are_preserved(self):
        for index, (schema, payload) in enumerate(((0, self.stage1), (2, self.stage2), (3, self.stage1), (3, self.stage2))):
            with self.subTest(schema=schema, rule=payload['rule_version']):
                path, rid, selected = self.run_fixture(payload, schema=schema, name=f'old-{index}.sqlite3')
                before = path.read_bytes(); bundle = read_selected_sources(selected); view = build_run_view(bundle.runs[0])
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(view['run_id'], rid)
                self.assertEqual(rid, self.stage1_id if payload['rule_version'] == 'stage1-v1' else self.stage2_id)
                self.assertEqual(view['rule_version'], payload['rule_version'])
                self.assertEqual(view['findings'][0]['expected'], '7' if payload['rule_version'] == 'stage1-v1' else '8')
                self.assertEqual(json.loads(view['configuration_text']), payload['configuration'])
                self.assertNotIn('DO NOT USE', view['configuration_text'])
                self.assertEqual(bundle.sources[0]['before'], bundle.sources[0]['after'])
                self.assertTrue(bundle.sources[0]['unchanged'])
                self.assertEqual(bundle.sources[0]['verified_copy'], bundle.sources[0]['before']['files']['database'])
                if schema == 0:
                    self.assertNotIn('correction_ids', view['findings'][0])
                    self.assertNotIn('groups', view['ledgers']['ASSET_A'])
                    self.assertNotIn('correction_group_id', view['ledgers']['ASSET_A']['trace'][0])

    def test_uses_readonly_escaped_uri_only_on_verified_owned_copy(self):
        path, rid, selected = self.run_fixture(name='query?mode=rw#& space-ü.sqlite3')
        real_connect = sqlite3.connect; seen = []
        def connect(database, *args, **kwargs):
            seen.append((database, kwargs))
            db = real_connect(database, *args, **kwargs)
            return db
        with patch('crypto_reconciliation_lab.review.adapter.sqlite3.connect', side_effect=connect):
            read_selected_sources(selected)
        self.assertEqual(len(seen), 1)
        self.assertNotEqual(seen[0][0].split('?mode=ro')[0], path.as_uri())
        self.assertIn('%3Fmode%3Drw%23%26%20space-', seen[0][0])
        self.assertTrue(seen[0][0].endswith('?mode=ro')); self.assertTrue(seen[0][1]['uri'])
        self.assertFalse(any(Path(str(path) + s).exists() for s in ('-wal', '-shm', '-journal')))

    def test_same_id_under_two_aliases_keeps_two_source_identities(self):
        path, rid, selection = self.run_fixture()
        value = json.loads(selection.read_text()); value['sources'].append({**value['sources'][0], 'alias': 'second'})
        selection.write_text(wire(value)); bundle = read_selected_sources(selection)
        self.assertEqual([(r.source_alias, r.run_id) for r in bundle.runs], [('case', rid), ('second', rid)])

    def test_payload_download_text_is_exact_with_whitespace_unicode_and_microseconds(self):
        payload = deepcopy(self.stage2)
        # Adding insignificant whitespace changes bytes, not content identity.
        text = json.dumps(payload, indent=3, ensure_ascii=False) + '\n'
        path, rid, selected = self.run_fixture(payload, text=text)
        saved = read_selected_sources(selected).runs[0]; view = build_run_view(saved)
        self.assertEqual(view['raw_payload'].encode('utf-8'), text.encode('utf-8'))
        self.assertEqual(view['payload_sha256'], hashlib.sha256(text.encode('utf-8')).hexdigest())
        self.assertEqual(view['knowledge_at'], payload['knowledge_at'])
        self.assertEqual(view['knowledge_sort_key'], payload['knowledge_at'])

    def test_raw_big_integer_script_text_and_bad_time_remain_lossless_inert_strings(self):
        payload = deepcopy(self.stage2)
        big = 900719925474099312345678901234567890
        hostile = '</script><img src="https://invalid.example/x" onerror="alert(1)"> & ü'
        body = {'record': {'kind': 'event', 'amount': big, 'note': hostile}, 'received_at': {'invalid': big}, 'error': 'INVALID_TYPE'}
        eid = 'raw-invalid-test'
        payload['evidence'][eid] = {'quarantined_receipt': body}
        payload['findings'][0]['evidence_ids'].append(eid)
        payload['findings'][0]['issues'].append({'code': 'UNFAMILIAR_CODE', 'state': 'INCOMPLETE', 'evidence_ids': [eid], 'detail': hostile})
        path, rid, selected = self.run_fixture(payload)
        view = build_run_view(read_selected_sources(selected).runs[0]); entry = view['evidence'][eid]
        self.assertIn(str(big), entry['raw_text']); self.assertIn(str(big), entry['received_at_raw_text'])
        self.assertIsNone(entry['received_at'])
        self.assertIn('</script>', entry['raw_text']); self.assertIn(hostile, view['findings'][0]['issues'][0]['raw_text'].replace('\\"', '"').replace('\\u00fc', 'ü'))
        self.assertEqual(view['findings'][0]['issues'][0]['code'], 'UNFAMILIAR_CODE')
        self.assertIsInstance(entry['fields'][0]['value'], str)

    def test_amount_null_zero_negative_long_string_not_coerced(self):
        payload = deepcopy(self.stage2)
        values = [None, '0', '-1', '0.123456789012345678901234567890123456789']
        for index, value in enumerate(values): payload['findings'][index]['difference'] = value
        path, rid, selected = self.run_fixture(payload)
        view = build_run_view(read_selected_sources(selected).runs[0])
        self.assertEqual([f['difference'] for f in view['findings'][:4]], values)

    def test_missing_database_is_not_created(self):
        path = self.root / 'missing.sqlite3'; selected = self.selection(path, ['missing'])
        with self.assertRaises(ReviewError): read_selected_sources(selected)
        self.assertFalse(path.exists())

    def test_unknown_run_and_schema_errors_preserve_original(self):
        path, rid, selected = self.run_fixture()
        selected = self.selection(path, ['unknown']); self.assert_unchanged_error(selected, path, 'RUN_MISSING')
        db = sqlite3.connect(path); db.execute('PRAGMA user_version=99'); db.close()
        selected = self.selection(path, [rid]); self.assert_unchanged_error(selected, path, 'SCHEMA_UNSUPPORTED')

    def test_rejects_wal_header_even_when_no_sidecar_and_sidecar_even_if_empty(self):
        path, rid, selected = self.run_fixture()
        for suffix in ('-wal', '-shm', '-journal'):
            marker = Path(str(path) + suffix); marker.write_bytes(b'')
            self.assert_unchanged_error(selected, path, 'SNAPSHOT_UNSUPPORTED'); self.assertEqual(marker.read_bytes(), b''); marker.unlink()
        db = sqlite3.connect(path); self.assertEqual(db.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal'); db.close()
        self.assertFalse(Path(str(path) + '-wal').exists())
        self.assert_unchanged_error(selected, path, 'SNAPSHOT_UNSUPPORTED')

    def test_active_wal_is_rejected_without_checkpoint_or_sidecar_change(self):
        path, rid, selected = self.run_fixture(); db = sqlite3.connect(path)
        db.execute('PRAGMA journal_mode=WAL'); db.execute('INSERT INTO records VALUES(?,?)', ('new', '{}')); db.commit()
        before = {s: Path(str(path) + s).read_bytes() for s in ('-wal', '-shm')}
        try:
            self.assert_unchanged_error(selected, path, 'SNAPSHOT_UNSUPPORTED')
            self.assertEqual(before, {s: Path(str(path) + s).read_bytes() for s in before})
        finally: db.close()

    def test_broken_or_live_sidecar_symlink_is_rejected_without_following_target(self):
        from crypto_reconciliation_lab.review import adapter
        path, rid, selected = self.run_fixture()
        target = self.root / 'unrelated-private-file'
        target.write_bytes(b'not database evidence')
        real_entry = adapter._file_entry
        def guarded_entry(candidate):
            self.assertNotEqual(candidate, target)
            return real_entry(candidate)
        for destination in (self.root / 'nonexistent-target', target):
            sidecar = Path(str(path) + '-wal'); sidecar.symlink_to(destination)
            try:
                with patch.object(adapter, '_file_entry', side_effect=guarded_entry):
                    error = self.assert_unchanged_error(selected, path, 'SNAPSHOT_UNSUPPORTED')
                self.assertEqual(error.audit['sources'][0]['before']['files']['sidecars']['-wal']['kind'], 'symlink')
                self.assertTrue(sidecar.is_symlink())
                self.assertEqual(target.read_bytes(), b'not database evidence')
            finally: sidecar.unlink()

    def test_selection_growth_after_open_still_obeys_bounded_read(self):
        from crypto_reconciliation_lab.review import adapter
        path, rid, selected = self.run_fixture()
        real_open = adapter._open_regular
        @contextmanager
        def grow_after_open(candidate):
            with real_open(candidate) as stream:
                with candidate.open('ab') as writer:
                    writer.write(b' ' * (adapter.MAX_SELECTION_BYTES + 1))
                yield stream
        with patch.object(adapter, '_open_regular', side_effect=grow_after_open):
            with self.assertRaises(ReviewError) as raised: read_selection(selected)
        self.assertEqual(raised.exception.code, 'SELECTION_LIMIT')

    def test_identity_corruption_and_bad_json_do_not_leave_mutated_sources(self):
        for index, bad in enumerate(('{broken', wire({**self.stage2, 'unexpected': True}))):
            path, rid, selected = self.run_fixture(name=f'bad-{index}.sqlite3')
            db = sqlite3.connect(path); db.execute('UPDATE runs SET payload=?', (bad,)); db.commit(); db.close()
            exc = self.assert_unchanged_error(selected, path, 'RUN_INTEGRITY'); self.assertEqual(exc.run_id, rid)

    def test_unknown_rule_and_duplicate_or_missing_finding_scope_are_rejected(self):
        mutations = [lambda p: p.update(rule_version='future-v9'), lambda p: p['findings'].append(deepcopy(p['findings'][0])), lambda p: p['findings'].pop()]
        for index, mutate in enumerate(mutations):
            payload = deepcopy(self.stage2); mutate(payload)
            path, rid, selected = self.run_fixture(payload, name=f'bad-shape-{index}.sqlite3')
            self.assert_unchanged_error(selected, path, 'RUN_INTEGRITY')

    def test_dangling_evidence_is_not_repaired_from_current_records(self):
        payload = deepcopy(self.stage2); payload['findings'][0]['evidence_ids'].append('later-record')
        path, rid, selected = self.run_fixture(payload)
        self.assert_unchanged_error(selected, path, 'RUN_INTEGRITY')

    def test_persisted_findings_and_evidence_mirrors_cannot_silently_disagree(self):
        for index, table in enumerate(('findings', 'evidence')):
            path, rid, selected = self.run_fixture(name=f'mirror-{index}.sqlite3')
            db = sqlite3.connect(path); db.execute('UPDATE ' + table + " SET payload='{}'"); db.commit(); db.close()
            self.assert_unchanged_error(selected, path, 'RUN_INTEGRITY')

    def test_missing_mirror_tables_use_original_evidence_value_slices(self):
        payload = deepcopy(self.stage2); text = json.dumps(payload, indent=2) + '\n'
        path, rid, selected = self.run_fixture(payload, mirrors=False, text=text)
        saved = read_selected_sources(selected).runs[0]
        key = next(iter(payload['evidence']))
        self.assertIn('\n', saved.evidence_texts[key])
        self.assertEqual(json.loads(saved.evidence_texts[key]), payload['evidence'][key])

    def test_boolean_number_mirror_equivalence_is_not_accepted(self):
        payload = deepcopy(self.stage2); payload['evidence']['probe'] = {'quarantined_receipt': {'received_at': None, 'record': {'probe': 1}}}
        path, rid, selected = self.run_fixture(payload)
        db = sqlite3.connect(path); db.execute('UPDATE evidence SET payload=? WHERE evidence_id=?', (wire({'quarantined_receipt': {'received_at': None, 'record': {'probe': True}}}), 'probe')); db.commit(); db.close()
        self.assert_unchanged_error(selected, path, 'RUN_INTEGRITY')

    def test_selected_byte_limit_preflights_before_loading_or_validating_payload(self):
        path, rid, selected = self.run_fixture()
        with patch('crypto_reconciliation_lab.review.adapter.MAX_PAYLOAD_BYTES', 1), patch('crypto_reconciliation_lab.review.adapter.validate_payload') as validate:
            self.assert_unchanged_error(selected, path, 'PAYLOAD_LIMIT'); validate.assert_not_called()

    def test_selection_limit_duplicate_alias_and_bad_label_errors(self):
        path, rid, selected = self.run_fixture()
        for change in ('limit', 'alias', 'label'):
            original = json.loads(selected.read_text())
            data = {'format': 'review-selection-v1', 'sources': [{'alias': 'case', 'database': path.name, 'run_ids': [rid]}]}
            if change == 'limit': data['sources'][0]['run_ids'] = [str(i) for i in range(101)]
            if change == 'alias': data['sources'].append(deepcopy(data['sources'][0]))
            if change == 'label': data['sources'][0]['run_labels'] = {'unknown': 'bad'}
            selected.write_text(wire(data))
            with self.assertRaises(ReviewError): read_selection(selected)

    def test_unknown_states_stay_explicit_and_stage2_v1_is_not_relabelled(self):
        payload = deepcopy(self.stage2); payload['rule_version'] = 'stage2-v1'
        for finding in payload['findings']: finding['rule_version'] = 'stage2-v1'
        payload['findings'][0]['data_state'] = 'UNFAMILIAR_STATE'
        path, rid, selected = self.run_fixture(payload, schema=2)
        view = build_run_view(read_selected_sources(selected).runs[0])
        self.assertEqual(view['rule_version'], 'stage2-v1'); self.assertEqual(view['findings'][0]['data_state'], 'UNFAMILIAR_STATE')

    def test_copy_race_is_rejected_and_original_is_never_connected(self):
        from crypto_reconciliation_lab.review import adapter
        path, rid, selected = self.run_fixture(); real_copy = adapter._copy_snapshot; real_connect = sqlite3.connect; opened = []
        def racing_copy(*args):
            result = real_copy(*args)
            Path(str(path) + '-journal').write_bytes(b'external-writer')
            return result
        def connect(database, *args, **kwargs):
            opened.append(database); return real_connect(database, *args, **kwargs)
        with patch.object(adapter, '_copy_snapshot', side_effect=racing_copy), patch.object(adapter.sqlite3, 'connect', side_effect=connect):
            with self.assertRaises(ReviewError) as raised: read_selected_sources(selected)
        self.assertEqual(raised.exception.code, 'SOURCE_CHANGED')
        self.assertFalse(raised.exception.audit['source_preservation_verified'])
        self.assertEqual(opened, [])
        self.assertEqual(Path(str(path) + '-journal').read_bytes(), b'external-writer')

    def test_large_unselected_payload_is_streamed_not_decoded_or_selected(self):
        path, rid, selected = self.run_fixture()
        raw = 'not-json-' + 'X' * (1024 * 1024)
        db = sqlite3.connect(path)
        db.execute('INSERT INTO runs VALUES(?,?,?,?)', ('unselected', 'unknown', 'unknown', raw))
        db.commit(); db.close()
        from crypto_reconciliation_lab.review import adapter
        with patch.object(adapter, 'CHUNK_BYTES', 4096), patch.object(adapter, 'validate_payload', wraps=adapter.validate_payload) as validate:
            bundle = read_selected_sources(selected)
        self.assertEqual(validate.call_count, 1)
        self.assertEqual(bundle.sources[0]['before']['run_inventory']['count'], 2)
        self.assertEqual(len(bundle.runs), 1)

    def test_oversized_persisted_mirror_is_rejected_before_materialization(self):
        path, rid, selected = self.run_fixture()
        db = sqlite3.connect(path)
        db.execute("UPDATE evidence SET payload=CAST(zeroblob(?) AS TEXT) WHERE evidence_id=(SELECT MIN(evidence_id) FROM evidence)", (2 * 1024 * 1024,))
        db.commit(); db.close()
        with patch('crypto_reconciliation_lab.review.adapter.MAX_PAYLOAD_BYTES', 1024 * 1024):
            error = self.assert_unchanged_error(selected, path, 'RUN_INTEGRITY')
        self.assertIn('mirror exceeds', error.message)

    def test_wrong_record_reference_kind_and_invented_legacy_fields_fail_integrity(self):
        for index in range(2):
            payload = deepcopy(self.stage1 if index else self.stage2)
            if index:
                payload['ledgers']['ASSET_A']['trace'][0]['correction_group_id'] = None
            else:
                payload['findings'][0]['report_ids'] = payload['findings'][0]['event_ids'][:1]
            path, rid, selected = self.run_fixture(payload, schema=0 if index else 3, name=f'wrong-reference-{index}.sqlite3')
            self.assert_unchanged_error(selected, path, 'RUN_INTEGRITY')


if __name__ == '__main__': unittest.main()
