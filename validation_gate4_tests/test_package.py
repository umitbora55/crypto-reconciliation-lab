"""Gate 4 byte-seal witnesses; distinct from evidence/verifier and original875 tests."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('gate4_package', ROOT/'scripts/validation/package_gate4.py')
PACKAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGE)
COMMIT = '6' * 40


def identity(name, raw):
    return {'path': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


class Gate4ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.archive = self.root/'fixture.zip'
        self.payloads = {'source/example.py': b'value = 1\n',
                         'evidence/fixture.json': b'{"kind":"test fixture, not trial evidence"}\n'}
        source = self.payloads['source/example.py']
        self.evidence = {
            'format': 'validation-gate4-evidence-v1',
            'repository_commit_at_seal': COMMIT,
            'gate3_baseline_commit': PACKAGE.BASELINE,
            'gate3_archive_reference': dict(PACKAGE.GATE3_ARCHIVE),
            'committed_source': [{'path': 'example.py', 'git_mode': '100644',
                                  'git_blob': hashlib.sha1(b'blob '+str(len(source)).encode()+b'\0'+source).hexdigest()}],
            'files': [identity('fixture.json', self.payloads['evidence/fixture.json'])],
            'omitted': [],
        }

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, *, evidence=None, payloads=None, manifest=None, duplicate=False, mode=None):
        entries = dict(self.payloads if payloads is None else payloads)
        entries['evidence-manifest.json'] = json.dumps(self.evidence if evidence is None else evidence).encode()
        if manifest is None:
            manifest = json.dumps({'format': 'validation-gate4-review-v1',
                                   'repository_commit': COMMIT,
                                   'members': [identity(n, b) for n, b in entries.items()]}).encode()
        with zipfile.ZipFile(self.archive, 'w') as zipped:
            for name, raw in entries.items():
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o600 if mode is None else mode) << 16
                zipped.writestr(info, raw)
                if duplicate:
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore', UserWarning)
                        zipped.writestr(info, raw)
            zipped.writestr('archive-manifest.json', manifest)

    def test_complete_seal_checks_real_bytes_external_identity_and_git_blob(self):
        self.write()
        raw = self.archive.read_bytes()
        result = PACKAGE.verify(self.archive, expected_commit=COMMIT,
                                expected_sha256=hashlib.sha256(raw).hexdigest(),
                                expected_bytes=len(raw), expected_members=4)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['verified_source_members'], 1)
        self.assertEqual(result['verified_evidence_members'], 1)
        self.assertEqual(result['authority'], 'BYTE_INTEGRITY_ONLY')
        for pin in [{'expected_commit': '7'*40}, {'expected_sha256': '0'*64},
                    {'expected_bytes': len(raw)+1}, {'expected_members': 5}]:
            with self.subTest(pin=pin), self.assertRaisesRegex(ValueError, 'external'):
                PACKAGE.verify(self.archive, **pin)
        substituted = dict(self.payloads)
        substituted['source/example.py'] = b'value = 2\n'
        self.write(payloads=substituted)  # Rehashing the outer manifest cannot conceal the original Git blob.
        with self.assertRaisesRegex(ValueError, 'Git source blob'):
            PACKAGE.verify(self.archive)

    def test_empty_duplicate_or_inconsistent_evidence_inventory_is_rejected(self):
        for mutation, reason in [
                (lambda e: e.update(files=[]), 'nonempty'),
                (lambda e: e.update(committed_source=[]), 'nonempty'),
                (lambda e: e['files'].append(dict(e['files'][0])), 'duplicate evidence'),
                (lambda e: e['committed_source'].append(dict(e['committed_source'][0])), 'duplicate or sensitive'),
                (lambda e: e['files'][0].update(sha256='0'*64), 'disagrees'),
                (lambda e: e['files'][0].update(bytes=True), 'malformed evidence'),
                (lambda e: e.update(gate3_baseline_commit='0'*40), 'baseline identity'),
                (lambda e: e.update(omitted=[{'path': 'fixture.json', 'reason': 'contradictory omission'}]), 'included omission'),
                (lambda e: e.update(omitted=[{'path': 'db.sqlite3', 'reason': 'omitted', 'bytes': 2}]), 'partial omission')]:
            evidence = copy.deepcopy(self.evidence)
            mutation(evidence)
            self.write(evidence=evidence)
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                PACKAGE.verify(self.archive)

    def test_zip_paths_modes_duplicates_and_expansion_limits_are_rejected(self):
        cases = [({'payloads': {**self.payloads, '../outside': b'x'}}, 'unsafe'),
                 ({'mode': stat.S_IFLNK | 0o777}, 'nonregular'),
                 ({'duplicate': True}, 'duplicate ZIP'),
                 ({'payloads': {**self.payloads, 'undeclared': b'x'}}, 'undeclared')]
        for arguments, reason in cases:
            self.write(**arguments)
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                PACKAGE.verify(self.archive)
        self.write()
        for name, value, reason in [('MAX_MEMBERS', 1, 'member count'),
                                    ('MAX_MEMBER_BYTES', 3, 'member size'),
                                    ('MAX_EXPANDED_BYTES', 5, 'expanded size')]:
            with self.subTest(limit=name), patch.object(PACKAGE, name, value):
                with self.assertRaisesRegex(ValueError, reason):
                    PACKAGE.verify(self.archive)
        self.assertFalse((self.root.parent/'outside').exists())

    def test_missing_duplicate_and_previous_gate_manifests_are_rejected(self):
        for manifest, reason in [
                (b'{"format":"validation-gate4-review-v1","format":"validation-gate4-review-v1"}', 'duplicate manifest'),
                (b'{"format":"validation-gate3-review-v1","members":[{}]}', 'Gate4 inventory'),
                (b'{"format":"validation-gate4-review-v1","members":[]}', 'nonempty')]:
            self.write(manifest=manifest)
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                PACKAGE.verify(self.archive)
        with zipfile.ZipFile(self.archive, 'w') as zipped:
            zipped.writestr('payload', b'x')
        with self.assertRaisesRegex(ValueError, 'missing archive manifest'):
            PACKAGE.verify(self.archive)

    def test_input_over_old_eight_mib_threshold_is_included_and_oversize_raw_fails(self):
        evidence = self.root/'inputs'
        evidence.mkdir()
        raw = b' '*(9*1024*1024)+b'[]\n'
        (evidence/'original-input.json').write_bytes(raw)
        included, omitted = PACKAGE.inventory(evidence)
        self.assertEqual(included, [identity('original-input.json', raw)])
        self.assertEqual(omitted, [])
        with patch.object(PACKAGE, 'MAX_MEMBER_BYTES', len(raw)-1):
            with self.assertRaisesRegex(ValueError, 'required raw record exceeds'):
                PACKAGE.inventory(evidence)

    def test_databases_sidecars_and_account_logs_have_hashed_explicit_omissions(self):
        evidence = self.root/'evidence'
        evidence.mkdir()
        (evidence/'logical.json').write_text('{"rows":[]}')
        excluded = {'input.sqlite3': b'db bytes', 'input.sqlite3-wal': b'wal bytes',
                    'input.sqlite3-shm': b'shm bytes', 'input.sqlite3-journal': b'journal bytes',
                    'api.json': b'{"actor":{"login":"lab-fixture","id":123}}',
                    'stdout.txt': b'{"actor":{"login":"lab-fixture","id":123}}',
                    'stdout.bin': b'{"actor":{"login":"lab-fixture","id":123}}',
                    'sec-fixture.body': b'no redistribution permission'}
        for name, raw in excluded.items():
            (evidence/name).write_bytes(raw)
        (evidence/'.env').write_text('synthetic placeholder')
        (evidence/'link').symlink_to(evidence/'logical.json')
        included, omitted = PACKAGE.inventory(evidence)
        self.assertEqual([row['path'] for row in included], ['logical.json'])
        rows = {row['path']: row for row in omitted}
        for name, raw in excluded.items():
            self.assertEqual({key: rows[name][key] for key in ['path', 'bytes', 'sha256']}, identity(name, raw))
            self.assertTrue(rows[name]['reason'])
            self.assertEqual((evidence/name).read_bytes(), raw)
        self.assertNotIn('sha256', rows['.env'])
        self.assertNotIn('sha256', rows['link'])

    def test_output_namespace_and_evidence_symlink_fail_before_git_or_writes(self):
        evidence = self.root/'evidence'
        evidence.mkdir()
        existing = self.root/'existing'
        existing.write_bytes(b'original')
        for output in [existing, evidence/'nested']:
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, 'fresh and outside'):
                PACKAGE.package(evidence, output)
        linked = self.root/'linked'
        linked.symlink_to(evidence, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'real directory'):
            PACKAGE.package(linked, self.root/'new')
        self.assertEqual(existing.read_bytes(), b'original')
        self.assertFalse((evidence/'nested').exists())

    def test_named_small_raw_portability_exception_and_renamed_database_omissions(self):
        evidence = self.root/'binary-evidence'
        raw = evidence/'pre-checkpoint-raw'
        raw.mkdir(parents=True)
        payloads = {'database.bin': b'SQLite format 3\0'+b'x'*32,
                    'wal.bin': b'\x37\x7f\x06\x82'+b'y'*32,
                    'shm.bin': b'shm fixture bytes'}
        for name, contents in payloads.items():
            (raw/name).write_bytes(contents)
        (evidence/'renamed.bin').write_bytes(payloads['database.bin'])
        (evidence/'other-wal.bin').write_bytes(payloads['wal.bin'])
        (evidence/'shm.bin').write_bytes(payloads['shm.bin'])
        included, omitted = PACKAGE.inventory(evidence)
        self.assertEqual({r['path'] for r in included}, {'pre-checkpoint-raw/'+name for name in payloads})
        self.assertEqual({r['path'] for r in omitted}, {'renamed.bin', 'other-wal.bin', 'shm.bin'})
        (evidence/'note.txt').write_text('keep inventory nonempty')
        with patch.object(PACKAGE, 'MAX_PORTABILITY_RAW_BYTES', 1):
            included, omitted = PACKAGE.inventory(evidence)
        self.assertEqual([r['path'] for r in included], ['note.txt'])
        self.assertEqual(len(omitted), 6)


if __name__ == '__main__':
    unittest.main()
