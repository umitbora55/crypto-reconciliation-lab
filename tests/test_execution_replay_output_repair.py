"""S13-F2: completed comparisons survive output-parent canonicalization errors."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from crypto_reconciliation_lab.replay import api
from stage13_1_output_fixture import write_pair


class ExecutionReplayOutputRepairTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def pair(self, name):
        pair = write_pair(self.root / name, name)
        self.input_hashes = tuple(hashlib.sha256(p.read_bytes()).hexdigest() for p in pair[:2])
        return pair

    def assert_unchanged(self, pair):
        self.assertEqual(tuple(hashlib.sha256(p.read_bytes()).hexdigest() for p in pair[:2]),
                         self.input_hashes)

    def assert_completed(self, result, name, *, output_error):
        divergent = name == 'divergent'
        replay_state = 'DIVERGED' if divergent else 'REPRODUCED'
        self.assertEqual(result['replay_state'], replay_state)
        self.assertEqual(result['completion'], {
            'validation': 'COMPLETED', 'calculation': 'COMPLETED', 'comparison': 'COMPLETED'})
        self.assertEqual(result['comparison']['state'], 'DIFFERENT' if divergent else 'EQUAL')
        self.assertIs(result['comparison']['equal'], not divergent)
        self.assertEqual(result['comparison']['total_differences'], 1 if divergent else 0)
        if divergent:
            self.assertEqual(result['comparison']['differences'][0]['path'],
                             '/ledgers/ASSET_A/liability')
            self.assertEqual(result['comparison']['differences'][0]['saved_preview'], '12')
            self.assertEqual(result['comparison']['differences'][0]['recomputed_preview'], '11')
        else:
            self.assertEqual(result['comparison']['differences'], [])
        if output_error:
            self.assertEqual((result['status'], result['reason_code'], result['exit_code'],
                              result['operation_state']),
                             ('ERROR', 'REPLAY_OUTPUT', 2, 'ERROR'))
        else:
            self.assertEqual((result['status'], result['reason_code'], result['exit_code'],
                              result['operation_state']),
                             (replay_state, 'REPLAY_' + replay_state, int(divergent), 'COMPLETE'))

    def real_loop(self):
        loop = self.root / 'loop'
        loop.symlink_to('loop', target_is_directory=True)
        return loop

    def assert_no_partial_output(self, loop, pair):
        self.assertEqual(os.readlink(loop), 'loop')
        self.assertEqual({p.name for p in self.root.iterdir()}, {pair[0].parent.name, 'loop'})
        self.assert_unchanged(pair)

    def api_loop(self, name):
        pair = self.pair(name)
        loop = self.real_loop()
        result = api.verify_execution_replay(*pair, output=loop / 'new-report')
        self.assert_completed(result, name, output_error=True)
        self.assert_no_partial_output(loop, pair)

    def test_real_self_loop_api_preserves_clean_completion(self):
        self.api_loop('clean')

    def test_real_self_loop_api_preserves_diverged_completion(self):
        self.api_loop('divergent')

    def cli_loop(self, name):
        pair = self.pair(name)
        loop = self.real_loop()
        argv = [sys.executable, '-B', *(['-I'] if sys.flags.isolated else []),
                '-m', 'crypto_reconciliation_lab', 'verify-execution-replay',
                '--context', str(pair[0]), '--run', str(pair[1]),
                '--expected-execution-id', pair[2], '--output', str(loop / 'new-report')]
        done = subprocess.run(argv, capture_output=True, timeout=30)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertEqual(done.stderr, b'')
        self.assert_completed(json.loads(done.stdout), name, output_error=True)
        self.assert_no_partial_output(loop, pair)

    def test_real_self_loop_cli_returns_json_for_clean(self):
        self.cli_loop('clean')

    def test_real_self_loop_cli_returns_json_for_diverged(self):
        self.cli_loop('divergent')

    def normal_output(self, name):
        pair = self.pair(name)
        output = self.root / 'report'
        result = api.verify_execution_replay(*pair, output=output)
        self.assert_completed(result, name, output_error=False)
        self.assertEqual({p.name for p in output.iterdir()}, {'report.json', 'report.md'})
        self.assertEqual(json.loads((output / 'report.json').read_bytes()), result)
        self.assert_unchanged(pair)

    def test_normal_output_clean_control(self):
        self.normal_output('clean')

    def test_normal_output_diverged_control(self):
        self.normal_output('divergent')

    def deterministic_parent_runtime_error(self, name):
        pair = self.pair(name)
        # Only this new output parent is intercepted. Authoritative input reads,
        # worker spawning and real financial calculation retain their normal paths.
        parent = self.root / 'output-parent'
        parent.mkdir()
        target = parent / 'new-report'
        original_resolve = Path.resolve
        calls = []

        def resolve(path, *args, **kwargs):
            if path == parent:
                calls.append(path)
                raise RuntimeError('test-owned output-parent canonicalization failure')
            return original_resolve(path, *args, **kwargs)

        with patch.object(Path, 'resolve', resolve):
            result = api.verify_execution_replay(*pair, output=target)
        self.assertEqual(calls, [parent])
        self.assert_completed(result, name, output_error=True)
        self.assertEqual(list(parent.iterdir()), [])
        self.assert_unchanged(pair)

    def test_output_parent_runtime_error_preserves_real_clean_completion(self):
        self.deterministic_parent_runtime_error('clean')

    def test_output_parent_runtime_error_preserves_real_diverged_completion(self):
        self.deterministic_parent_runtime_error('divergent')
