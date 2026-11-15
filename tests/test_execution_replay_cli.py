"""New command syntax errors also carry a structured operation result."""
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ExecutionReplayCliTests(unittest.TestCase):
    def test_real_cli_identifies_the_worker_it_actually_executes(self):
        from replay_fixtures import export_pair
        import crypto_reconciliation_lab
        with tempfile.TemporaryDirectory() as temporary:
            pair = export_pair(Path(temporary)/'source')
            argv = [sys.executable, '-B', *(['-I'] if sys.flags.isolated else []),
                    '-m', 'crypto_reconciliation_lab', 'verify-execution-replay',
                    '--context', str(pair['context_path']), '--run', str(pair['run_path']),
                    '--expected-execution-id', pair['expected']]
            done = subprocess.run(argv, capture_output=True, timeout=30)
            self.assertEqual(done.returncode, 0, done.stderr)
            result = json.loads(done.stdout)
            package = Path(crypto_reconciliation_lab.__file__).resolve().parent
            for name in ('engine', 'replay.worker'):
                path = package.joinpath(*name.split('.')).with_suffix('.py')
                raw = path.read_bytes()
                self.assertEqual(result['runtime']['modules'][name],
                                 {'path': str(path), 'bytes': len(raw),
                                  'sha256': hashlib.sha256(raw).hexdigest()})

    def test_invalid_timeout_and_missing_or_unknown_arguments_are_structured(self):
        base = [sys.executable, '-B', *(['-I'] if sys.flags.isolated else []),
                '-m', 'crypto_reconciliation_lab', 'verify-execution-replay']
        valid = ['--context', 'absent-context.json', '--run', 'absent-run.json',
                 '--expected-execution-id', '0' * 64]
        for arguments in ([], valid + ['--timeout-seconds', '1.5'], valid + ['--database', 'ignored.db']):
            with self.subTest(arguments=arguments):
                done = subprocess.run(base + arguments, capture_output=True, timeout=10)
                self.assertEqual(done.returncode, 2)
                self.assertEqual(done.stderr, b'')
                result = json.loads(done.stdout)
                self.assertEqual((result['status'], result['reason_code'], result['exit_code']),
                                 ('ERROR', 'REPLAY_INPUT', 2))
                self.assertEqual(result['completion']['calculation'], 'NOT_COMPLETED')
