"""Real CLI public-path guards before and after protected stream binding."""
from contextlib import closing
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from crypto_reconciliation_lab import Store
from crypto_reconciliation_lab.migrations import application_snapshot
from crypto_reconciliation_lab.source_auth.fixtures import CONFIG, RECEIVER, policy, small_records, snapshot, signed


class SourceAuthCliTests(unittest.TestCase):
    def call(self, *args):
        return subprocess.run([sys.executable, *(['-I'] if sys.flags.isolated else []),
            '-m', 'crypto_reconciliation_lab', *map(str, args)], capture_output=True, text=True, timeout=20)

    def test_unsigned_ingest_and_feed_cli_refused_before_and_after_binding(self):
        from crypto_reconciliation_lab.source_auth.runtime import enable_protection, ingest_signed
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); path = root / 'protected.db'; feed = root / 'feed.jsonl'
            data = snapshot(small_records()); feed.write_bytes(data)
            with closing(Store(path, CONFIG)) as store:
                enable_protection(store, RECEIVER, policy())
                for bound in (False, True):
                    if bound:
                        result = ingest_signed(store, data, signed(data), max_lines=1)
                        self.assertEqual(len(result['responses']), 1)
                    before = application_snapshot(store.db)
                    for args in (('ingest', '--db', path, '--input', feed),
                                 ('ingest-feed', '--db', path, '--input', feed, '--stream-id', 'platform-demo:sample')):
                        with self.subTest(bound=bound, command=args[0]):
                            process = self.call(*args)
                            self.assertEqual(process.returncode, 2, process.stderr)
                            self.assertIn('SOURCE_AUTH_REQUIRED', process.stderr)
                            self.assertEqual(application_snapshot(store.db), before)

    def test_operator_and_signed_cli_keep_financial_evaluation_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); path = root / 'protected.db'
            with closing(Store(path, CONFIG)):
                pass
            policy_file = root / 'policy.json'; policy_file.write_text(json.dumps(policy()))
            feed = root / 'feed.jsonl'; data = snapshot(small_records()); feed.write_bytes(data)
            envelope = root / 'envelope.json'; envelope.write_bytes(signed(data))
            enabled = self.call('auth-enable', '--db', path, '--receiver', RECEIVER, '--policy', policy_file)
            self.assertEqual(enabled.returncode, 0, enabled.stderr)
            accepted = self.call('ingest-signed', '--db', path, '--input', feed, '--envelope', envelope)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            status = self.call('auth-status', '--db', path)
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertEqual(json.loads(status.stdout)['active_policy']['epoch'], 1)
            with closing(Store(path)) as store:
                self.assertEqual(store.db.execute('SELECT COUNT(*) FROM receipts').fetchone()[0], 2)
                self.assertEqual(store.db.execute('SELECT COUNT(*) FROM auth_delivery_links').fetchone()[0], 2)
                self.assertEqual(store.db.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 0)
