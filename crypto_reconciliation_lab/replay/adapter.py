"""Two-table input-only facade for the unchanged reconciliation engine."""
import sqlite3

from .. import engine
from ..execution.common import canonical, sha256
from ..store import Store
from .common import MAX_COMPUTED_BYTES, ReplayError, require


class InputOnlyStore:
    """Private captured records/receipts only; the saved answer is never accepted."""
    def __init__(self, configuration, records, receipts):
        self.config = configuration
        self.db = sqlite3.connect(':memory:', isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.save_count = 0
        try:
            self.db.execute('CREATE TABLE records (id TEXT PRIMARY KEY, logical_key TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL)')
            self.db.execute('CREATE TABLE receipts (id INTEGER PRIMARY KEY, receipt_hash TEXT NOT NULL, record_id TEXT, received_at TEXT, raw TEXT NOT NULL, error TEXT, status TEXT NOT NULL)')
            self.db.executemany('INSERT INTO records (id,logical_key,kind,payload) VALUES (?,?,?,?)',
                                ((r['id'], r['logical_key'], r['kind'], r['payload']) for r in records))
            self.db.executemany('INSERT INTO receipts (id,receipt_hash,record_id,received_at,raw,error,status) VALUES (?,?,?,?,?,?,?)',
                                ((r['id'], r['receipt_hash'], r['record_id'], r['received_at'], r['raw'], r['error'], r['status']) for r in receipts))
            self.db.execute('PRAGMA query_only=ON')
        except BaseException:
            self.db.close()
            raise

    def known(self, knowledge_at):
        return Store.known(self, knowledge_at)

    def save_run(self, result, *, fault=None):
        require(fault is None and self.save_count == 0, 'replay sink must receive one new result', 'REPLAY_COMPUTATION')
        self.save_count += 1
        raw = canonical(result)
        require(len(raw) <= MAX_COMPUTED_BYTES, 'computed financial payload byte limit', 'REPLAY_LIMIT')
        return {'run_id': sha256(raw), **result}

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def compute(*, configuration, records, receipts, balance_at, knowledge_at):
    """Call the fixed engine exactly once with every validated captured input."""
    try:
        with InputOnlyStore(configuration, records, receipts) as store:
            result = engine.reconcile(store, balance_at, knowledge_at)
            require(store.save_count == 1, 'financial calculation did not complete once', 'REPLAY_COMPUTATION')
            return result
    except ReplayError:
        raise
    except (ValueError, TypeError, KeyError, ArithmeticError, sqlite3.Error) as exc:
        raise ReplayError('REPLAY_COMPUTATION', str(exc)) from exc
