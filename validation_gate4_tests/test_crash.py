"""Negative checks for research crash witnesses; original tests stay unchanged."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from validation_lab.gate4_crash import APIS, STAGES, CATALOG, kill_at_gate, sha, validate_ack


class CrashEvidenceTests(unittest.TestCase):
    def test_catalog_has_exact_twenty_cells_and_no_power_loss_claim(self):
        catalog = json.loads(CATALOG.read_bytes())
        self.assertEqual(catalog['trials'], len(catalog['methods']) * len(APIS) * len(STAGES))
        self.assertEqual(catalog['trials'], 20)
        self.assertEqual(catalog['stages'], list(STAGES))
        self.assertIn('No host power removal', catalog['exclusions'][0])

    def test_ack_at_before_commit_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'ack.json').write_text('{}')
            with self.assertRaisesRegex(AssertionError, 'wrong crash boundary'):
                validate_ack(root, 'after_insert_before_commit', b'request', {})

    def test_missing_ack_at_ack_barrier_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(AssertionError, 'wrong crash boundary'):
                validate_ack(Path(directory), 'after_ack', b'request', {})

    def test_same_response_with_substituted_original_request_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = {'request_sha256': sha(b'original'), 'response': {'status': 'ACCEPTED'},
                     'commit_completed': True, 'commits': 1}
            (root / 'ack.json').write_text(json.dumps(value))
            validate_ack(root, 'after_ack', b'original', value['response'])
            with self.assertRaisesRegex(AssertionError, 'binding differs'):
                validate_ack(root, 'after_ack', b'substituted', value['response'])

    def test_fabricated_precommit_ack_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = {'request_sha256': sha(b'original'), 'response': {},
                     'commit_completed': False, 'commits': 0}
            (root / 'ack.json').write_text(json.dumps(value))
            with self.assertRaisesRegex(AssertionError, 'completed commit'):
                validate_ack(root, 'after_ack', b'original', {})

    def test_controller_exception_kills_and_reaps_owned_real_child(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root / 'request.jsonl'
            request.write_bytes(b'{}\n')
            with patch('validation_lab.gate4_crash.read_barrier', side_effect=RuntimeError('controller witness')):
                with self.assertRaisesRegex(RuntimeError, 'controller witness'):
                    kill_at_gate(root, root / 'never-opened.sqlite3', request,
                                 'BASELINE', 'ordinary_ingest', 'before_begin')
            command = json.loads((root / 'command.json').read_bytes())
            self.assertEqual(command['actual_exit'], -9)
            self.assertEqual(command['cleanup_signal'], 'SIGKILL')
            self.assertTrue(command['reaped'])


if __name__ == '__main__':
    unittest.main()
