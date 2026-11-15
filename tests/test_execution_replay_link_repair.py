"""S13-F1: captured decisions and linked attempts must name one position."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from replay_fixtures import assert_error, assert_reproduced, hashed, write_historical
from replay_historical_fixtures import historical_0101
from replay_link_repair_fixtures import (link_pairs, ORIGINAL_PIN, STREAM_PIN,
    ORIGINAL_CONTEXT_SHA256, STREAM_CONTEXT_SHA256, RAW_RUN_SHA256)


class ExecutionReplayLinkRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.original, self.stream, self.sequence = link_pairs(self.root/'pairs')

    def run_bytes(self, pair):
        from crypto_reconciliation_lab.replay.worker import verify_bytes
        return verify_bytes(pair['context_path'].read_bytes(),
                            pair['run_path'].read_bytes(), pair['expected'])

    def assert_rejected_before_engine(self, pair):
        from crypto_reconciliation_lab import engine
        before = (pair['context_path'].read_bytes(), pair['run_path'].read_bytes())
        with patch.object(engine, 'reconcile', wraps=engine.reconcile) as invoked:
            report = self.run_bytes(pair)
        self.assertEqual(invoked.call_count, 0, report)
        assert_error(self, report, 'REPLAY_INTEGRITY')
        self.assertEqual(report['replay_state'], 'NOT_EVALUATED')
        self.assertEqual(report['completion'], {
            'validation': 'NOT_COMPLETED', 'calculation': 'NOT_COMPLETED',
            'comparison': 'NOT_COMPLETED'})
        self.assertEqual((pair['context_path'].read_bytes(), pair['run_path'].read_bytes()), before)

    def test_review_stream_mismatch_rejected_before_engine(self):
        self.assert_rejected_before_engine(self.stream)

    def test_existing_sequence_mismatch_rejected_before_engine(self):
        tables = self.sequence['context']['tables']
        attempt = next(row for row in tables['delivery_attempts'] if row['id'] == 31)
        decision = next(row for row in tables['auth_decisions'] if row['id'] == 31)
        self.assertEqual((attempt['stream_id'], attempt['sequence']), ('test-custodian:initial', 1))
        self.assertEqual((decision['stream_id'], decision['sequence']), ('test-custodian:initial', 2))
        # Both target positions really exist: existence-only checks are insufficient.
        self.assertTrue(any(row['stream_id'] == decision['stream_id'] and row['sequence'] == 2
                            for row in tables['delivery_effects']))
        self.assert_rejected_before_engine(self.sequence)

    def test_original_external_pin_still_rejects_modified_context(self):
        self.assert_rejected_before_engine(dict(self.stream, expected=ORIGINAL_PIN))

    def test_review_fixture_bytes_and_test_only_pin_are_exact(self):
        self.assertEqual(self.original['expected'], ORIGINAL_PIN)
        self.assertEqual(self.stream['expected'], STREAM_PIN)
        self.assertEqual(hashed(self.original['context_path'].read_bytes()), ORIGINAL_CONTEXT_SHA256)
        self.assertEqual(hashed(self.stream['context_path'].read_bytes()), STREAM_CONTEXT_SHA256)
        for pair in (self.original, self.stream, self.sequence):
            self.assertEqual(hashed(pair['run_path'].read_bytes()), RAW_RUN_SHA256)
            self.assertEqual(pair['context']['acceptance_epochs'], [1])
        expected = copy.deepcopy(self.original['context'])
        next(row for row in expected['tables']['auth_decisions'] if row['id'] == 31)['stream_id'] = 'nonexistent-stream'
        self.assertEqual(self.stream['context'], expected)
        link = next(row for row in expected['tables']['auth_attempt_links'] if row['attempt_id'] == 31)
        self.assertEqual(link, {'attempt_id': 31, 'decision_id': 31})
        attempt = next(row for row in expected['tables']['delivery_attempts'] if row['id'] == 31)
        decision = next(row for row in expected['tables']['auth_decisions'] if row['id'] == 31)
        self.assertEqual((attempt['outcome'], decision['decision'], decision['epoch']), ('REPLAY', 'CURRENT', 2))

    def test_genuine_current_historical_and_new_delivery_preserve_original_epochs(self):
        from crypto_reconciliation_lab import engine
        phases = (('after-current-replay', [1]), ('after-historical-replay', [1]),
                  ('after-real-new-delivery', [1, 2]))
        records = historical_0101()
        for phase, epochs in phases:
            with self.subTest(phase=phase):
                pair = write_historical(self.root/phase, records[phase])
                self.assertEqual(pair['context']['acceptance_epochs'], epochs)
                before = (pair['context_path'].read_bytes(), pair['run_path'].read_bytes())
                with patch.object(engine, 'reconcile', wraps=engine.reconcile) as invoked:
                    result = self.run_bytes(pair)
                self.assertEqual(invoked.call_count, 1)
                assert_reproduced(self, result)
                self.assertEqual((pair['context_path'].read_bytes(), pair['run_path'].read_bytes()), before)
