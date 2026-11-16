"""Gate3-only archive controls: actual malformed ZIP bytes, separate from875."""
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
SPEC = importlib.util.spec_from_file_location('gate3_package', ROOT/'scripts/validation/package_gate3.py')
PACKAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGE)


class Gate3ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.archive = self.root/'review.zip'

    def tearDown(self):
        self.temp.cleanup()

    def write(self, entries=None, rows=None, manifest=None, duplicate=False, mode=None):
        entries = {'source/example.py': b'value = 1\n'} if entries is None else entries
        if rows is None:
            rows = [{'path': p, 'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()}
                    for p, b in entries.items()]
        if manifest is None:
            manifest = json.dumps({'format':'validation-gate3-review-v1',
                                  'repository_commit':'6'*40,'members':rows}).encode()
        with zipfile.ZipFile(self.archive,'w') as z:
            for p,b in entries.items():
                info = zipfile.ZipInfo(p)
                info.create_system = 3
                info.external_attr = (mode if mode is not None else stat.S_IFREG | 0o600) << 16
                z.writestr(info,b)
                if duplicate:
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore',UserWarning)
                        z.writestr(info,b)
            z.writestr('archive-manifest.json',manifest)

    def test_valid_archive_binds_real_payload_bytes(self):
        self.write()
        result = PACKAGE.verify(self.archive)
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(result['verified_members'],2)
        self.assertEqual(result['sha256'],hashlib.sha256(self.archive.read_bytes()).hexdigest())
        self.assertEqual(result['authority'],'BYTE_INTEGRITY_ONLY')

    def test_actual_unsafe_member_rejected_without_extraction(self):
        self.write({'../outside':b'bad'})
        with self.assertRaisesRegex(ValueError,'unsafe'):
            PACKAGE.verify(self.archive)
        self.assertFalse((self.root.parent/'outside').exists())

    def test_actual_symlink_member_rejected(self):
        self.write(mode=stat.S_IFLNK|0o777)
        with self.assertRaisesRegex(ValueError,'nonregular'):
            PACKAGE.verify(self.archive)

    def test_duplicate_zip_member_rejected(self):
        self.write(duplicate=True)
        with self.assertRaisesRegex(ValueError,'duplicate ZIP'):
            PACKAGE.verify(self.archive)

    def test_missing_expected_payload_rejected(self):
        self.write(entries={},rows=[{'path':'missing','bytes':0,'sha256':hashlib.sha256(b'').hexdigest()}])
        with self.assertRaisesRegex(ValueError,'missing, duplicate'):
            PACKAGE.verify(self.archive)

    def test_altered_payload_does_not_pass_unchanged_hash(self):
        self.write(rows=[{'path':'source/example.py','bytes':10,'sha256':'0'*64}])
        with self.assertRaisesRegex(ValueError,'identity mismatch'):
            PACKAGE.verify(self.archive)

    def test_duplicate_manifest_field_rejected(self):
        self.write(manifest=b'{"format":"validation-gate3-review-v1","format":"validation-gate3-review-v1"}')
        with self.assertRaisesRegex(ValueError,'duplicate manifest'):
            PACKAGE.verify(self.archive)

    def test_missing_manifest_is_rejected(self):
        with zipfile.ZipFile(self.archive,'w') as z:z.writestr('payload',b'x')
        with self.assertRaisesRegex(ValueError,'missing archive manifest'):
            PACKAGE.verify(self.archive)

    def test_declared_size_cannot_replace_actual_member_size(self):
        self.write(rows=[{'path':'source/example.py','bytes':0,'sha256':hashlib.sha256(b'').hexdigest()}])
        with self.assertRaisesRegex(ValueError,'declared member size'):
            PACKAGE.verify(self.archive)

    def test_expansion_limits_apply_before_payload_reads(self):
        self.write()
        for name,value,reason in [('MAX_MEMBERS',1,'member count'),
                                  ('MAX_MEMBER_BYTES',9,'member size'),
                                  ('MAX_EXPANDED_BYTES',10,'expanded size')]:
            with self.subTest(limit=name),patch.object(PACKAGE,name,value):
                with self.assertRaisesRegex(ValueError,reason):PACKAGE.verify(self.archive)

    def test_gate2_manifest_is_not_relabelled_gate3(self):
        self.write(manifest=b'{"format":"validation-gate2-review-v1","members":[{}]}')
        with self.assertRaisesRegex(ValueError,'Gate3 inventory'):
            PACKAGE.verify(self.archive)

    def test_inventory_omits_original_account_metadata_and_unlicensed_raw(self):
        evidence=self.root/'evidence';evidence.mkdir()
        (evidence/'summary.json').write_text('{"job_id":42,"status":"success"}')
        original=b'{"actor":{"login":"synthetic-user","id":123}}'
        (evidence/'api.json').write_bytes(original)
        raw=evidence/'public-data'/'access-01'/'raw';raw.mkdir(parents=True)
        (raw/'sec-ftd-202401a.body').write_bytes(b'synthetic unlicensed body')
        (raw/'dts-operating_cash_balance-2024-01.body').write_bytes(b'{"data":[]}')
        duplicate=evidence/'extracted';duplicate.mkdir();(duplicate/'duplicate').write_bytes(b'x')
        (evidence/'.env').write_bytes(b'synthetic secret')
        included,omitted=PACKAGE.inventory(evidence)
        self.assertEqual({r['path'] for r in included},{'summary.json','public-data/access-01/raw/dts-operating_cash_balance-2024-01.body'})
        byname={r['path']:r for r in omitted}
        self.assertEqual(byname['api.json']['sha256'],hashlib.sha256(original).hexdigest())
        self.assertNotIn('sha256',byname['.env'])
        self.assertEqual(byname['extracted']['kind'],'subtree')
        self.assertIn('rights',byname['public-data/access-01/raw/sec-ftd-202401a.body']['reason'])
        self.assertEqual((evidence/'api.json').read_bytes(),original)
        # Selecting the raw directory itself must not erase its source-rights boundary.
        raw_included, raw_omitted = PACKAGE.inventory(raw)
        self.assertEqual([r['path'] for r in raw_included],['dts-operating_cash_balance-2024-01.body'])
        self.assertEqual([r['path'] for r in raw_omitted],['sec-ftd-202401a.body'])


if __name__ == '__main__':
    unittest.main()
