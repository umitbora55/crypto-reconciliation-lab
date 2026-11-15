"""S12-F1: checked export paths and actual publication share one canonical target."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

from crypto_reconciliation_lab import Store
from crypto_reconciliation_lab.execution import reconcile_recorded
from crypto_reconciliation_lab.execution.demo import build_fixture


SIDECARS = ('-journal', '-wal', '-shm')


def identity(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def namespace(database):
    result = {}
    for suffix in ('', *SIDECARS):
        path = Path(str(database) + suffix)
        if path.is_symlink():
            result[suffix] = {'kind': 'symlink', 'target': os.readlink(path)}
        elif path.is_dir():
            result[suffix] = {'kind': 'directory', 'members': sorted(p.name for p in path.iterdir())}
        elif path.is_file():
            result[suffix] = {'kind': 'file', **identity(path.read_bytes())}
        else:
            result[suffix] = {'kind': 'absent'}
    return result


class Stage121ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.serial = 0

    def fixture(self, name):
        fixture = build_fixture(self.root / name)
        with closing(Store(fixture['database'])) as store:
            execution = reconcile_recorded(store, fixture['balance_at'], fixture['knowledge_at'], 'initial')
        return fixture, execution

    def cli(self, label, arguments):
        self.serial += 1
        argv = [sys.executable, '-B', *(['-I'] if sys.flags.isolated else []), '-m', 'crypto_reconciliation_lab', *map(str, arguments)]
        started, timer = datetime.now(timezone.utc).isoformat(), time.monotonic()
        child = subprocess.run(argv, capture_output=True, timeout=30)
        try:
            result = json.loads(child.stdout)
        except ValueError:
            result = None
        record = {'argv': argv, 'cwd': str(Path.cwd()), 'started_at': started, 'seconds': time.monotonic() - timer,
                  'exit_code': child.returncode, 'stdout': identity(child.stdout), 'stderr': identity(child.stderr), 'result': result}
        evidence = os.environ.get('CRYPTO_STAGE12_1_TEST_EVIDENCE')
        if evidence:
            target = Path(evidence) / self._testMethodName / (str(self.serial) + '-' + label)
            target.mkdir(parents=True, exist_ok=False)
            (target / 'command.json').write_text(json.dumps(record, indent=2) + '\n')
            (target / 'stdout.txt').write_bytes(child.stdout)
            (target / 'stderr.txt').write_bytes(child.stderr)
        return child, result

    def export_then_write(self, label, suffix=None):
        fixture, execution = self.fixture(label)
        database = Path(fixture['database'])
        with closing(sqlite3.connect(database)) as db:
            context = db.execute('SELECT payload FROM execution_contexts').fetchone()[0]
            run = db.execute('SELECT CAST(payload AS BLOB) FROM runs').fetchone()[0]
        before = namespace(database)
        self.assertTrue(all(before[suffix] == {'kind': 'absent'} for suffix in SIDECARS))
        canonical = database.parent / 'safe-export'
        requested = Path(str(database) + suffix) / '..' / 'safe-export' if suffix else canonical
        child, exported = self.cli(label + '-export', ['export-execution', '--db', database,
                                    '--execution-id', execution['execution_id'], '--output', requested])
        after = namespace(database)
        raw_equal = canonical.is_dir() and (canonical / 'context.json').read_bytes() == context and (canonical / 'run.json').read_bytes() == run
        write, written = self.cli(label + '-write', ['reconcile-recorded', '--db', database,
                            '--balance-at', fixture['balance_at'], '--knowledge-at', fixture['knowledge_at'], '--request-id', 'after-export'])
        observation = {'requested': str(requested), 'canonical': str(canonical), 'before': before, 'after': after,
                       'raw_equal': raw_equal, 'export_exit': child.returncode, 'write_exit': write.returncode,
                       'export': exported, 'write': written}
        evidence = os.environ.get('CRYPTO_STAGE12_1_TEST_EVIDENCE')
        if evidence:
            (Path(evidence) / self._testMethodName / (label + '-namespace.json')).write_text(json.dumps(observation, indent=2) + '\n')
        self.assertEqual(child.returncode, 0, observation)
        self.assertEqual(exported['status'], 'EXPORTED')
        self.assertEqual(before[''], after[''], 'database bytes must remain exact through export')
        self.assertTrue(raw_equal, 'exported context and financial run must equal stored raw bytes')
        self.assertEqual(before, after, observation)
        self.assertEqual(exported['output'], str(canonical))
        self.assertEqual(write.returncode, 0, observation)
        self.assertEqual(written['status'], 'RECORDED')
        self.assertNotEqual(written['execution_id'], execution['execution_id'])
        self.assertEqual(written['run_id'], execution['run_id'])

    def test_ordinary_export_preserves_raw_bytes_namespace_and_next_write(self):
        self.export_then_write('ordinary')

    def test_sidecar_dotdot_routes_publish_safely_without_creating_reserved_names(self):
        for suffix in SIDECARS:
            with self.subTest(suffix=suffix):
                self.export_then_write(suffix.lstrip('-'), suffix)

    def test_canonical_database_sidecar_and_descendant_targets_are_rejected(self):
        for suffix in ('', *SIDECARS):
            for descendant in (False, True):
                with self.subTest(suffix=suffix, descendant=descendant):
                    fixture, execution = self.fixture('collision-' + (suffix or 'db') + str(descendant))
                    database = Path(fixture['database'])
                    target = Path(str(database) + suffix)
                    if descendant:
                        target /= 'child'
                    # The skipped directory must never be created either.
                    requested = database.parent / 'unused' / '..' / target.name if not descendant else target
                    if not descendant:
                        requested = database.parent / 'unused' / '..' / Path(str(database) + suffix).name
                    before = namespace(database)
                    children = sorted(p.name for p in database.parent.iterdir())
                    child, result = self.cli('collision', ['export-execution', '--db', database,
                                             '--execution-id', execution['execution_id'], '--output', requested])
                    self.assertEqual(child.returncode, 2)
                    self.assertEqual((result['status'], result['reason_code']), ('ERROR', 'EXECUTION_OUTPUT'))
                    self.assertEqual(namespace(database), before)
                    self.assertEqual(sorted(p.name for p in database.parent.iterdir()), children)

    def test_existing_directory_file_and_dangling_symlink_are_never_replaced(self):
        for kind in ('directory', 'file', 'dangling-symlink'):
            with self.subTest(kind=kind):
                fixture, execution = self.fixture(kind)
                target = Path(fixture['database']).parent / 'existing'
                if kind == 'directory':
                    target.mkdir(); (target / 'marker.txt').write_bytes(b'keep directory')
                elif kind == 'file':
                    target.write_bytes(b'keep file')
                else:
                    target.symlink_to('missing-target')
                child, result = self.cli(kind, ['export-execution', '--db', fixture['database'],
                                '--execution-id', execution['execution_id'], '--output', target])
                self.assertEqual(child.returncode, 2)
                self.assertEqual(result['reason_code'], 'EXECUTION_OUTPUT')
                if kind == 'directory':
                    self.assertEqual((target / 'marker.txt').read_bytes(), b'keep directory')
                elif kind == 'file':
                    self.assertEqual(target.read_bytes(), b'keep file')
                else:
                    self.assertTrue(target.is_symlink())
                    self.assertEqual(os.readlink(target), 'missing-target')
                    self.assertFalse((target.parent / 'missing-target').exists())
                self.assertFalse(list(target.parent.glob('.review-staging-*')))

    def test_dotdot_alias_of_existing_target_does_not_create_skipped_directory(self):
        fixture, execution = self.fixture('existing-alias')
        target = Path(fixture['database']).parent / 'existing'
        target.mkdir(); (target / 'marker').write_bytes(b'keep')
        skipped = target.parent / 'never-created'
        child, result = self.cli('alias', ['export-execution', '--db', fixture['database'],
                           '--execution-id', execution['execution_id'], '--output', skipped / '..' / target.name])
        self.assertEqual(child.returncode, 2)
        self.assertEqual(result['reason_code'], 'EXECUTION_OUTPUT')
        self.assertEqual((target / 'marker').read_bytes(), b'keep')
        self.assertFalse(skipped.exists())
        self.assertFalse(list(target.parent.glob('.review-staging-*')))
