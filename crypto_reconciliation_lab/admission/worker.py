"""Opt-in bounded recovery child; the ordinary admission path enables no hooks."""
import argparse
import base64
import json
import os
from pathlib import Path
import sqlite3
import sys
from ..store import Store
from ..engine import reconcile


def emit(value):
    print(json.dumps(value, sort_keys=True), flush=True)


def command(expected):
    value = sys.stdin.readline().strip()
    if value != expected:
        raise RuntimeError('supervisor command missing: ' + expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    store = Store(request['db'])

    def settings():
        return {'journal_mode': store.db.execute('PRAGMA journal_mode').fetchone()[0],
                'synchronous': store.db.execute('PRAGMA synchronous').fetchone()[0],
                'busy_timeout_ms': store.db.execute('PRAGMA busy_timeout').fetchone()[0]}

    emit({'type': 'READY', 'pid': os.getpid(), 'interpreter': sys.executable,
          'import_origin': str(Path(__file__).resolve()), 'sqlite': sqlite3.sqlite_version,
          'writer_connection': settings()})
    command('GO')
    barrier = request.get('barrier')

    def fault(point):
        if barrier and point == barrier:
            emit({'type': 'BARRIER', 'point': point, 'pid': os.getpid(), 'writer_connection': settings()})
            command('CONTINUE')

    try:
        action = request['action']
        if action == 'delivery':
            result = store.ingest_delivery(request['stream_id'], request['sequence'],
                base64.b64decode(request['payload_base64'], validate=True), request['plan'],
                busy_timeout_ms=request.get('busy_timeout_ms', 250), fault=fault if barrier else None)
        elif action == 'feed':
            from .feed import ingest_feed
            result = ingest_feed(store, request['input'], request['stream_id'],
                                 busy_timeout_ms=request.get('busy_timeout_ms', 250))
        elif action == 'reconcile':
            result = reconcile(store, request['balance_at'], request['knowledge_at'], fault=fault if barrier else None)
        else:
            raise ValueError('unknown recovery child action')
        emit({'type': 'RESULT', 'pid': os.getpid(), 'result': result, 'writer_connection': settings()})
    finally:
        store.close()


if __name__ == '__main__':
    main()
