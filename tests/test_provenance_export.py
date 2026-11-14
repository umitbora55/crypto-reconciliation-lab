"""Closed capture, byte preservation and publication boundaries for the new exporter."""
import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from review_fixtures import create_source
from crypto_reconciliation_lab.provenance.common import ProvenanceError, parse_json, bounded_file
from crypto_reconciliation_lab.provenance.exporter import export_provenance
from crypto_reconciliation_lab.provenance import exporter


class ProvenanceExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.db, self.run_id = create_source(self.root / 'fixture')
        self.materials = self.root / 'materials'
        self.materials.mkdir()
        self.output = self.root / 'bundle'

    def raw_run(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            return db.execute('SELECT CAST(payload AS BLOB) FROM runs WHERE id=?', (self.run_id,)).fetchone()[0]

    def export(self):
        return export_provenance(self.db, self.run_id, self.materials, self.output)

    def test_saved_raw_payload_and_source_bytes_are_preserved_without_recomputation(self):
        before = self.db.read_bytes()
        raw = self.raw_run()
        with mock.patch('crypto_reconciliation_lab.store.Store.__init__', side_effect=AssertionError('Store forbidden')), \
             mock.patch('crypto_reconciliation_lab.engine.reconcile', side_effect=AssertionError('engine forbidden')), \
             mock.patch('crypto_reconciliation_lab.migrations.migrate_connection', side_effect=AssertionError('migration forbidden')), \
             mock.patch('crypto_reconciliation_lab.store.Store.save_run', side_effect=AssertionError('save_run forbidden')):
            result = self.export()
        self.assertEqual(result['status'], 'CREATED')
        self.assertEqual(result['source_verification'], 'NOT_PERFORMED')
        self.assertEqual(result['run_creation_authorization_cut'], 'NOT_RECORDED')
        self.assertEqual(result['financial_recomputation'], 'NOT_PERFORMED')
        self.assertEqual((self.output / 'run.json').read_bytes(), raw)
        self.assertEqual(self.db.read_bytes(), before)
        self.assertFalse(any(Path(str(self.db) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')))
        saved = json.loads(raw)
        # Independent literals from the published clean example, never a calculator oracle.
        self.assertEqual(saved['ledgers']['ASSET_A']['investor_balances'], {'I1': '7', 'I2': '4'})
        self.assertEqual(saved['ledgers']['ASSET_A']['liability'], '11')
        self.assertEqual(saved['ledgers']['ASSET_B']['liability'], '0.5')

    def test_noncanonical_saved_text_has_separate_canonical_and_raw_identities(self):
        raw = self.raw_run()
        unusual = b' \n' + raw + b'\n '
        with closing(sqlite3.connect(self.db)) as db, db:
            trigger = db.execute("SELECT sql FROM sqlite_master WHERE name='immutable_runs_UPDATE'").fetchone()[0]
            db.execute('DROP TRIGGER immutable_runs_UPDATE')
            db.execute('UPDATE runs SET payload=? WHERE id=?', (unusual.decode(), self.run_id))
            db.execute(trigger)
        self.export()
        report = json.loads((self.output / 'report.json').read_bytes())
        self.assertEqual((self.output / 'run.json').read_bytes(), unusual)
        self.assertEqual(report['run_id'], self.run_id)
        self.assertEqual(report['run_payload_sha256'], hashlib.sha256(unusual).hexdigest())
        self.assertNotEqual(report['run_payload_sha256'], self.run_id)

    def test_every_physical_duplicate_is_captured_even_after_run_saved(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            first = db.execute('SELECT * FROM receipts ORDER BY id').fetchone()
            db.execute('INSERT INTO receipts(receipt_hash,record_id,received_at,raw,error,status) VALUES (?,?,?,?,?,?)',
                       (*first[1:6], 'DUPLICATE'))
        raw = self.raw_run()
        self.export()
        capture = json.loads((self.output / 'capture.json').read_bytes())
        candidates = [r for r in capture['tables']['receipts'] if r['receipt_hash'] == first[1]]
        self.assertEqual(len(candidates), 2)
        self.assertEqual(len({r['id'] for r in candidates}), 2)
        self.assertEqual((self.output / 'run.json').read_bytes(), raw)
        self.assertEqual(capture['tables']['auth_configuration'], [])

    def test_capture_is_read_from_one_private_copy_transaction(self):
        connect = sqlite3.connect
        observed = []
        def checked(database, *args, **kwargs):
            self.assertNotIn(str(self.db), str(database))
            self.assertIn('?mode=ro', str(database))
            connection = connect(database, *args, **kwargs)
            connection.set_trace_callback(observed.append)
            return connection
        with mock.patch.object(exporter.sqlite3, 'connect', side_effect=checked):
            self.export()
        self.assertEqual(observed.count('BEGIN'), 1)
        self.assertFalse(any(statement.lstrip().upper().startswith(('INSERT ', 'UPDATE ', 'DELETE ', 'CREATE ', 'ALTER ')) for statement in observed))

    def test_schema_four_is_rejected_without_migrating_source(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('PRAGMA user_version=4')
        before = self.db.read_bytes()
        with self.assertRaisesRegex(ProvenanceError, 'PROVENANCE_SCHEMA'):
            self.export()
        self.assertEqual(self.db.read_bytes(), before)
        self.assertFalse(self.output.exists())

    def test_sidecars_are_rejected_and_preserved(self):
        for suffix in ('-wal', '-shm', '-journal'):
            with self.subTest(suffix=suffix):
                sidecar = Path(str(self.db) + suffix)
                sidecar.write_bytes(b'owned test marker')
                with self.assertRaisesRegex(ProvenanceError, 'PROVENANCE_SNAPSHOT'):
                    self.export()
                self.assertEqual(sidecar.read_bytes(), b'owned test marker')
                self.assertFalse(self.output.exists())
                sidecar.unlink()

    def test_source_replacement_or_change_during_read_prevents_publication(self):
        projection = exporter._projection
        def changed(*args):
            value = projection(*args)
            info = self.db.stat()
            os.utime(self.db, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
            return value
        with mock.patch.object(exporter, '_projection', side_effect=changed):
            with self.assertRaisesRegex(ProvenanceError, 'PROVENANCE_SOURCE_CHANGED'):
                self.export()
        self.assertFalse(self.output.exists())

    def test_database_symlink_is_rejected(self):
        link = self.root / 'linked.sqlite'
        link.symlink_to(self.db)
        with self.assertRaisesRegex(ProvenanceError, 'PROVENANCE_SNAPSHOT'):
            export_provenance(link, self.run_id, self.materials, self.output)
        self.assertFalse(self.output.exists())

    def test_unknown_or_wrong_run_does_not_publish_a_partial_bundle(self):
        with self.assertRaisesRegex(ProvenanceError, 'PROVENANCE_RUN'):
            export_provenance(self.db, 'f' * 64, self.materials, self.output)
        self.assertFalse(self.output.exists())

    def test_existing_output_and_material_ancestor_are_not_modified(self):
        self.output.mkdir()
        marker = self.output / 'user.txt'
        marker.write_bytes(b'preserve')
        with self.assertRaisesRegex(ProvenanceError, 'PROVENANCE_OUTPUT'):
            self.export()
        self.assertEqual(marker.read_bytes(), b'preserve')
        with self.assertRaisesRegex(ProvenanceError, 'PROVENANCE_OUTPUT'):
            export_provenance(self.db, self.run_id, self.materials, self.materials / 'new' / 'bundle')
        self.assertEqual(list(self.materials.iterdir()), [])

    def test_output_cannot_create_a_database_sidecar_or_its_descendant(self):
        for suffix in ('-wal', '-shm', '-journal'):
            for descendant in (False, True):
                with self.subTest(suffix=suffix, descendant=descendant), tempfile.TemporaryDirectory() as folder:
                    database, run_id = create_source(Path(folder) / 'isolated')
                    before = database.read_bytes()
                    sidecar = Path(str(database) + suffix)
                    output = sidecar / 'bundle' if descendant else sidecar
                    with self.assertRaisesRegex(ProvenanceError, 'PROVENANCE_OUTPUT'):
                        export_provenance(database, run_id, self.materials, output)
                    self.assertFalse(sidecar.exists())
                    self.assertEqual(database.read_bytes(), before)

    def test_atomic_publish_never_replaces_a_racing_empty_directory(self):
        publish = exporter.publish_directory
        def raced(source, destination):
            destination.mkdir()
            return publish(source, destination)
        with mock.patch.object(exporter, 'publish_directory', side_effect=raced):
            with self.assertRaises(ProvenanceError):
                self.export()
        self.assertTrue(self.output.is_dir())
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(list(self.root.glob('.bundle-provenance-*')), [])

    def test_failed_render_leaves_no_bundle_or_staging_directory(self):
        before = self.db.read_bytes()
        with mock.patch('crypto_reconciliation_lab.provenance.ui.render_page', side_effect=ValueError('render failure')):
            with self.assertRaisesRegex(ProvenanceError, 'render failure'):
                self.export()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob('.bundle-provenance-*')), [])
        self.assertEqual(self.db.read_bytes(), before)

    def test_manifest_covers_every_original_member_and_no_database(self):
        self.export()
        manifest = json.loads((self.output / 'manifest.json').read_bytes())
        files = {p.relative_to(self.output).as_posix(): p for p in self.output.rglob('*') if p.is_file()}
        self.assertEqual(set(files), set(manifest['files']) | {'manifest.json'})
        for name, item in manifest['files'].items():
            data = files[name].read_bytes()
            self.assertEqual(item, {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        self.assertFalse(any(name.endswith(('.db', '.sqlite', '.sqlite3')) for name in files))

    def test_source_and_projection_limits_reject_without_publication(self):
        for name, value in [('MAX_DATABASE_BYTES', 100), ('MAX_ROWS', 1), ('MAX_CAPTURE_BYTES', 256), ('MAX_TOTAL_BYTES', 1024)]:
            with self.subTest(limit=name), mock.patch.object(exporter, name, value):
                with self.assertRaises(ProvenanceError):
                    self.export()
                self.assertFalse(self.output.exists())


class ProvenanceInputPrimitiveTests(unittest.TestCase):
    def test_json_rejects_duplicate_keys_nonfinite_surrogates_and_excess_depth(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e9999}', b'"\\ud800"', b'[' * 34 + b'0' + b']' * 34):
            with self.subTest(raw=raw), self.assertRaises(ProvenanceError):
                parse_json(raw)

    def test_file_guard_rejects_symlinks_and_oversized_material(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root / 'raw'
            path.write_bytes(b'12345'); link = root / 'link'; link.symlink_to(path)
            with self.assertRaises(ProvenanceError):
                bounded_file(link, 10)
            with self.assertRaises(ProvenanceError):
                bounded_file(path, 4)
            self.assertEqual(bounded_file(path, 5), b'12345')


if __name__ == '__main__':
    unittest.main()
