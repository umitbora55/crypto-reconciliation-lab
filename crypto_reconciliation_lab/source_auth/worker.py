"""Bounded test-only signed-admission process with observable named barriers."""
import argparse
import json
import os
from pathlib import Path
import sys
from ..store import Store
from .runtime import ingest_signed


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',type=Path,required=True)
    args=parser.parse_args()
    request=json.loads(args.request.read_text())
    store=Store(request['db'])
    def emit(kind,**fields):
        print(json.dumps({'type':kind,'pid':os.getpid(),**fields},sort_keys=True),flush=True)
    def settings():
        return {p:store.db.execute('PRAGMA '+p).fetchone()[0] for p in ('journal_mode','synchronous','busy_timeout')}
    def command(value):
        if sys.stdin.readline().strip()!=value:
            raise RuntimeError('missing supervisor command: '+value)
    emit('READY',interpreter=sys.executable,import_origin=__file__,writer_settings=settings())
    command('GO')
    reached=False
    def fault(point):
        nonlocal reached
        if not reached and point==request['barrier']:
            reached=True
            emit('BARRIER',point=point,writer_settings=settings())
            command('CONTINUE')
    try:
        result=ingest_signed(store,Path(request['snapshot']).read_bytes(),Path(request['envelope']).read_bytes(),fault=fault)
        emit('RESULT',result=result,writer_settings=settings())
    finally:
        store.close()


if __name__=='__main__':
    main()
