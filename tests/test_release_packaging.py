"""Narrow failures at the new portable build/archive boundary."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/build_release.py'
SPEC = importlib.util.spec_from_file_location('stage6_build_release', SCRIPT)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class ReleasePackagingTests(unittest.TestCase):
    def test_canonical_output_does_not_create_lexical_parents_in_protected_tree(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); (root / 'docs').mkdir()
            (root / 'pyproject.toml').write_text(f'[project]\nversion="{release.VERSION}"\nrequires-python=">=3.12"\n')
            lexical = root / 'docs/unwanted/../../stage6-output/attempt'
            with patch.object(release, 'selected_files', return_value=[]), \
                    patch.object(release, 'check_links', side_effect=ValueError('stop before build tools')):
                with self.assertRaisesRegex(ValueError, 'stop before build tools'):
                    release.build(lexical, root)
            self.assertFalse((root / 'docs/unwanted').exists())
            self.assertEqual(json.loads((root / 'stage6-output/attempt/release.json').read_text())['status'], 'ERROR')

    def test_existing_output_is_preserved_before_any_build_or_source_read(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); output = root / 'existing'; output.mkdir()
            marker = output / 'marker'; marker.write_bytes(b'preserve existing bytes')
            with self.assertRaises(FileExistsError):
                release.build(output, root)
            self.assertEqual(marker.read_bytes(), b'preserve existing bytes')
            self.assertEqual(list(output.iterdir()), [marker])

    def test_traversal_and_symlink_sdist_members_fail_before_extraction(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for index, (member_name, symlink) in enumerate((('pkg/../escape', False), ('/absolute', False), ('pkg/link', True))):
                with self.subTest(member=member_name):
                    archive = root / (str(index) + '.tar.gz')
                    with tarfile.open(archive, 'w:gz') as stream:
                        item = tarfile.TarInfo(member_name)
                        if symlink:
                            item.type = tarfile.SYMTYPE; item.linkname = '../escape'; stream.addfile(item)
                        else:
                            item.size = 1; stream.addfile(item, io.BytesIO(b'x'))
                    output = root / ('extract-' + str(index))
                    with self.assertRaises(ValueError):
                        release.extract_sdist(archive, output, {})
                    self.assertFalse(output.exists())
            self.assertFalse((root / 'escape').exists())

    def test_sdist_cannot_silently_omit_a_required_test_fixture(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); archive = root / 'incomplete.tar.gz'
            with tarfile.open(archive, 'w:gz') as stream:
                item = tarfile.TarInfo('pkg/README.md'); item.size = 1
                stream.addfile(item, io.BytesIO(b'x'))
            expected = {'README.md':release.file_entry(b'x'), 'tests/required.py':release.file_entry(b'test')}
            with self.assertRaisesRegex(ValueError, 'ARCHIVE_MISSING'):
                release.extract_sdist(archive, root / 'extracted', expected)
            self.assertFalse((root / 'extracted').exists())

    def test_failed_build_command_records_actual_exit_and_never_becomes_success(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); (root / 'logs').mkdir()
            record = {'status':'RUNNING', 'commands':[]}
            with self.assertRaisesRegex(RuntimeError, 'exit 7'):
                release.run_command(record, root, 'controlled-failure',
                                    [sys.executable, '-I', '-c', 'import sys;print("controlled");sys.exit(7)'], root)
            saved = json.loads((root / 'release.json').read_text())
            self.assertNotEqual(saved['status'], 'PASS')
            self.assertEqual(saved['commands'][0]['exit_code'], 7)
            self.assertEqual((root / 'logs/controlled-failure.stdout.txt').read_text(), 'controlled\n')
