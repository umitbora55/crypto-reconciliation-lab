"""S12-F3: overflowing UTC normalization is a structured recorded-input error."""
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
from crypto_reconciliation_lab.execution import ExecutionError, reconcile_recorded
from crypto_reconciliation_lab.execution.demo import build_fixture, CONFIG

TABLES = ('runs', 'findings', 'evidence', 'correction_groups', 'correction_effects', 'execution_contexts', 'recorded_executions')


def saved_rows(database):
    with closing(sqlite3.connect(database)) as db:
        return {table: db.execute('SELECT * FROM ' + table + ' ORDER BY rowid').fetchall() for table in TABLES}


class Stage121TimestampTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = build_fixture(self.root / 'input')
        self.serial = 0

    def cli(self, database, balance, knowledge, request_id):
        self.serial += 1
        argv = [sys.executable, '-B', *(['-I'] if sys.flags.isolated else []), '-m', 'crypto_reconciliation_lab',
                'reconcile-recorded', '--db', str(database), '--balance-at', balance, '--knowledge-at', knowledge,
                '--request-id', request_id]
        started, timer = datetime.now(timezone.utc).isoformat(), time.monotonic()
        child = subprocess.run(argv, capture_output=True, timeout=30)
        try:
            result = json.loads(child.stdout)
        except ValueError:
            result = None
        record = {'argv': argv, 'cwd': str(Path.cwd()), 'started_at': started, 'seconds': time.monotonic() - timer,
                  'exit_code': child.returncode, 'result': result}
        evidence = os.environ.get('CRYPTO_STAGE12_1_TEST_EVIDENCE')
        if evidence:
            target = Path(evidence) / self._testMethodName / str(self.serial)
            target.mkdir(parents=True, exist_ok=False)
            for channel, data in [('stdout', child.stdout), ('stderr', child.stderr)]:
                (target / (channel + '.txt')).write_bytes(data)
                record[channel] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            (target / 'command.json').write_text(json.dumps(record, indent=2) + '\n')
        return child, result

    def assert_input_rejected(self, field, value):
        fixture = self.fixture
        database = fixture['database']
        # Preserve a genuinely populated pre-existing run and execution too.
        with closing(Store(database)) as store:
            reconcile_recorded(store, fixture['balance_at'], fixture['knowledge_at'], 'prior')
        before = saved_rows(database)
        cuts = {key: fixture[key] for key in ('balance_at', 'knowledge_at')}
        cuts[field] = value
        caught = None
        with closing(Store(database)) as store:
            try:
                reconcile_recorded(store, **cuts, request_id='api-invalid')
            except Exception as error:
                caught = error  # Observe raw baseline exception without masking the CLI witness.
            self.assertFalse(store.db.in_transaction)
        after_api = saved_rows(database)
        child, result = self.cli(database, cuts['balance_at'], cuts['knowledge_at'], 'cli-invalid')
        after_cli = saved_rows(database)
        self.assertEqual(before, after_api)
        self.assertEqual(before, after_cli)
        self.assertIsInstance(caught, ExecutionError, repr(caught))
        self.assertEqual(caught.reason_code, 'EXECUTION_INPUT')
        self.assertEqual(child.returncode, 2, child.stderr.decode())
        self.assertEqual((result['status'], result['reason_code']), ('ERROR', 'EXECUTION_INPUT'))
        self.assertNotIn(b'Traceback', child.stderr)

    def test_lower_utc_overflow_balance_at_is_controlled_input_error(self):
        self.assert_input_rejected('balance_at', '0001-01-01T00:00:00+23:59')

    def test_lower_utc_overflow_knowledge_at_is_controlled_input_error(self):
        self.assert_input_rejected('knowledge_at', '0001-01-01T00:00:00+23:59')

    def test_upper_utc_overflow_balance_at_is_controlled_input_error(self):
        self.assert_input_rejected('balance_at', '9999-12-31T23:59:59-23:59')

    def test_upper_utc_overflow_knowledge_at_is_controlled_input_error(self):
        self.assert_input_rejected('knowledge_at', '9999-12-31T23:59:59-23:59')

    def test_invalid_syntax_remains_structured_input_error(self):
        for field in ('balance_at', 'knowledge_at'):
            with self.subTest(field=field):
                self.assert_input_rejected(field, 'not-a-timestamp')

    def test_near_utc_bounds_are_valid_with_appropriate_opening(self):
        cases = [('lower', '0001-01-01T00:00:00Z', '0001-01-02T00:00:00+23:59', '0001-01-01T00:01:00.000000Z'),
                 ('upper', '9999-12-30T00:00:00Z', '9999-12-30T23:59:59-23:59', '9999-12-31T23:58:59.000000Z')]
        for label, opening, local, normalized in cases:
            for field in ('balance_at', 'knowledge_at'):
                with self.subTest(label=label, field=field):
                    database = self.root / (label + '-' + field + '.sqlite3')
                    config = dict(CONFIG, opening_at=opening)
                    with closing(Store(database, config)) as store:
                        cuts = {'balance_at': normalized, 'knowledge_at': normalized}
                        cuts[field] = local
                        result = reconcile_recorded(store, **cuts, request_id='near-bound')
                    self.assertEqual(result['status'], 'RECORDED')
                    self.assertEqual(result['request'][field], normalized)
                    child, readback = self.cli(database, cuts['balance_at'], cuts['knowledge_at'], 'near-bound')
                    self.assertEqual(child.returncode, 1, child.stderr.decode())
                    self.assertEqual(readback['status'], 'RECORDED')
                    self.assertTrue(readback['replayed'])
                    self.assertEqual(readback['execution_id'], result['execution_id'])
                    self.assertEqual(readback['context']['counts']['receipts'], 0)

    def test_valid_matched_and_financial_mismatch_keep_distinct_exit_codes(self):
        for mismatch in (False, True):
            with self.subTest(mismatch=mismatch):
                fixture = build_fixture(self.root / ('valid-' + str(mismatch)), mismatch=mismatch)
                child, result = self.cli(fixture['database'], fixture['balance_at'], fixture['knowledge_at'], 'valid')
                self.assertEqual(child.returncode, 1 if mismatch else 0, child.stderr.decode())
                self.assertEqual(result['status'], 'RECORDED')
                finding = next(row for row in result['financial_result']['findings'] if row['asset'] == 'ASSET_A' and row['comparison'] == 'B')
                self.assertEqual((finding['expected'], finding['reported'], finding['difference']),
                                 ('11', '10', '1') if mismatch else ('11', '11', '0'))
                self.assertEqual(finding['reconciliation_state'], 'MISMATCH' if mismatch else 'MATCHED')
