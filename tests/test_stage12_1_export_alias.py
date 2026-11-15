"""Post-pair F1 boundary: dot aliases must not follow a dangling final link."""
import os
from pathlib import Path
import unittest

import test_stage12_1_export as fixture_helpers


class Stage121ExportAliasTests(unittest.TestCase):
    setUp = fixture_helpers.Stage121ExportTests.setUp
    fixture = fixture_helpers.Stage121ExportTests.fixture
    cli = fixture_helpers.Stage121ExportTests.cli

    def test_dotdot_aliases_refuse_dangling_final_symlink_before_any_publication(self):
        for skipped_name in ('unused', 'reserved-journal'):
            with self.subTest(skipped_name=skipped_name):
                fixture, execution = self.fixture(skipped_name)
                database = Path(fixture['database'])
                final = database.parent / 'dangling'
                final.symlink_to('absent-referent')
                skipped = database.parent / 'unused' if skipped_name == 'unused' else Path(str(database) + '-journal')
                requested = skipped / '..' / final.name
                before = fixture_helpers.namespace(database)
                children = sorted(path.name for path in database.parent.iterdir())
                child, result = self.cli(skipped_name, ['export-execution', '--db', database,
                                 '--execution-id', execution['execution_id'], '--output', requested])
                self.assertEqual(child.returncode, 2, result)
                self.assertEqual((result['status'], result['reason_code']), ('ERROR', 'EXECUTION_OUTPUT'))
                self.assertTrue(final.is_symlink())
                self.assertEqual(os.readlink(final), 'absent-referent')
                self.assertFalse((final.parent / 'absent-referent').exists())
                self.assertFalse(skipped.exists())
                self.assertEqual(fixture_helpers.namespace(database), before)
                self.assertEqual(sorted(path.name for path in database.parent.iterdir()), children)
                direct, direct_result = self.cli(skipped_name + '-canonical', ['export-execution', '--db', database,
                                                '--execution-id', execution['execution_id'], '--output', final])
                self.assertEqual(direct.returncode, 2)
                self.assertEqual(direct_result['reason_code'], 'EXECUTION_OUTPUT')

    def test_dotdot_alias_preserves_existing_final_symlink_and_target_bytes(self):
        fixture, execution = self.fixture('existing-link')
        database = Path(fixture['database'])
        actual = database.parent / 'actual'
        actual.mkdir(); (actual / 'marker').write_bytes(b'preserve')
        final = database.parent / 'link'
        final.symlink_to(actual.name)
        skipped = database.parent / 'unused'
        child, result = self.cli('existing-link', ['export-execution', '--db', database,
                                 '--execution-id', execution['execution_id'], '--output', skipped / '..' / final.name])
        self.assertEqual(child.returncode, 2)
        self.assertEqual(result['reason_code'], 'EXECUTION_OUTPUT')
        self.assertEqual(os.readlink(final), actual.name)
        self.assertEqual((actual / 'marker').read_bytes(), b'preserve')
        self.assertEqual(sorted(p.name for p in actual.iterdir()), ['marker'])
        self.assertFalse(skipped.exists())
