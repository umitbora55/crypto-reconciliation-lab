"""Gate 4 research invariants; separate from the protected product test roster."""
import copy
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from validation_lab.benchmark import workload
from validation_lab.gate4_benchmark import (PROTOCOL, equivalent, kill_wait,
    run_worker, summarize, validate_protocol, write)
from validation_lab.gate4_storage import (METHODS, logical_snapshot, open_store,
                                         read_pragmas)


class BenchmarkTests(unittest.TestCase):
    def test_real_worker_starts_with_larger_child_as_bound(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            write(root / 'input.json', workload(13, 11))
            source_root = str(PROTOCOL.parents[1])
            script = '''import json,resource,subprocess,sys
from pathlib import Path
from validation_lab.gate4_benchmark import controller_limits
root=Path(sys.argv[1]); source_root=sys.argv[2]
controller_limits({'controller_address_space_bytes':1024**3,'worker_address_space_bytes':1536*1024**2})
assert resource.getrlimit(resource.RLIMIT_AS)==(1024**3,1536*1024**2)
bootstrap="import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('validation_lab.gate4_benchmark',run_name='__main__')"
result=subprocess.run([sys.executable,'-I','-B','-c',bootstrap,source_root,'--worker','--input',str(root/'input.json'),'--output',str(root/'child'),'--method','CANDIDATE_WAL_FULL','--cpu-limit','10'],capture_output=True,text=True,timeout=15)
assert result.returncode==0,result.stderr
marker=json.loads((root/'child.worker-start.json').read_text())
assert marker['effective_rlimits']['RLIMIT_AS']==[1536*1024**2]*2
assert json.loads((root/'child/metrics.json').read_text())['status']=='PASS'
'''
            child = subprocess.run([sys.executable, '-B', '-c', script, str(root), source_root],
                                   capture_output=True, text=True, timeout=20)
            self.assertEqual(child.returncode, 0, child.stderr)

    def test_pending_signals_cannot_leave_child_unowned(self):
        script = '''import os,signal,subprocess,sys
from validation_lab import gate4_benchmark as gate
real=subprocess.Popen
signum=int(sys.argv[1])
seen=[]
def launch(*args,**kwargs):
    child=real(*args,**kwargs)
    seen.append(child.pid)
    os.kill(os.getpid(),signum)
    return child
def interrupted(signum,frame):
    raise RuntimeError('INJECTED_HANDOFF_SIGNAL')
signal.signal(signum,interrupted)
gate.subprocess.Popen=launch
try:
    gate.launch_owned([sys.executable,'-c','import time;time.sleep(20)'],cwd=None,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
except RuntimeError as exc:
    assert str(exc)=='INJECTED_HANDOFF_SIGNAL'
    assert gate.ACTIVE is not None and gate.ACTIVE.pid==seen[0]
    assert gate.kill_wait(gate.ACTIVE)==-signal.SIGKILL
    try: os.waitpid(seen[0],os.WNOHANG)
    except ChildProcessError: pass
    else: raise AssertionError('child not reaped')
else: raise AssertionError('injected signal not observed')
'''
        for signum in (signal.SIGALRM, signal.SIGINT, signal.SIGTERM):
            child = subprocess.run([sys.executable, '-B', '-c', script, str(signum)],
                                   capture_output=True, text=True, timeout=10)
            self.assertEqual(child.returncode, 0, child.stderr)

    def test_full_persisted_small_pair_and_instrumented_control_are_equal(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            input_path = root / 'input.json'
            write(input_path, workload(13, 11))
            baseline = run_worker(input_path, root / 'baseline', METHODS[0])
            candidate = run_worker(input_path, root / 'candidate', METHODS[1])
            observed = run_worker(input_path, root / 'instrumented', METHODS[1], True)
            self.assertTrue(equivalent(baseline, candidate))
            self.assertTrue(equivalent(candidate, observed))
            self.assertEqual(candidate['counts']['receipts'], 30)
            self.assertEqual(candidate['counts']['runs'], 1)
            self.assertEqual(candidate['pragmas_reopen']['synchronous'], 2)
            self.assertEqual(candidate['checkpoint_result'], [0, 0, 0])
            self.assertEqual(observed['buckets']['ingest:sql_commit']['calls'], 30)
            self.assertEqual(observed['buckets']['ingest:sql_begin']['calls'], 30)
            self.assertEqual(baseline['pragmas_initial']['journal_mode'], 'delete')

    def test_adapter_keeps_foreign_keys_append_only_and_reopen(self):
        with tempfile.TemporaryDirectory() as root:
            data = workload(0, 0)
            for method in METHODS:
                path = Path(root) / method
                store = open_store(path, data['config'], method)
                store.ingest(**{'raw': data['rows'][0]['record'], 'received_at': data['rows'][0]['received_at']})
                self.assertFalse(store.db.in_transaction)
                with self.assertRaises(sqlite3.IntegrityError):
                    store.db.execute('DELETE FROM receipts')
                before = logical_snapshot(store)
                store.close()
                store = open_store(path, method=method)
                self.assertEqual(logical_snapshot(store), before)
                self.assertEqual(read_pragmas(store)['foreign_keys'], 1)
                store.close()

    def test_baseline_rejects_existing_wal_without_changing_it(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'db'
            store = open_store(path, workload(0, 0)['config'], METHODS[1])
            store.close()
            with self.assertRaisesRegex(ValueError, 'NON_EQUIVALENT_PRAGMAS'):
                open_store(path, method=METHODS[0])
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], 'wal')

    def test_logical_snapshot_preserves_blob_distinction(self):
        with tempfile.TemporaryDirectory() as root:
            store = open_store(Path(root) / 'db', workload(0, 0)['config'])
            store.db.execute('CREATE TABLE research_blob(value BLOB)')
            store.db.execute('INSERT INTO research_blob VALUES (?)', (b'\x00\xff',))
            first = logical_snapshot(store)
            store.db.execute('DELETE FROM research_blob')
            store.db.execute('INSERT INTO research_blob VALUES (?)', ('00ff',))
            second = logical_snapshot(store)
            self.assertNotEqual(first['tables']['research_blob']['sha256'], second['tables']['research_blob']['sha256'])
            store.close()

    def test_fixed_protocol_rejects_empty_duplicate_and_missing_pairs(self):
        good = json.loads(PROTOCOL.read_text())
        validate_protocol(good)
        for bad_rows in ([], good['roster'][:-1], [good['roster'][0]] * 34):
            bad = copy.deepcopy(good)
            bad['roster'] = bad_rows
            with self.assertRaises(ValueError):
                validate_protocol(bad)

    def test_incomplete_roster_cannot_satisfy_material_gain(self):
        protocol = json.loads(PROTOCOL.read_text())
        result = summarize([], protocol)
        self.assertEqual(result['performance_gate'], 'NO_CHANGE')
        self.assertEqual([p['complete_equivalent_pairs'] for p in result['profiles']], [0, 0])

    def test_kill_wait_reaps_real_owned_child(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'], start_new_session=True)
        try:
            self.assertEqual(kill_wait(process), -signal.SIGKILL)
            self.assertEqual(process.returncode, -signal.SIGKILL)
            with self.assertRaises(ChildProcessError):
                os.waitpid(process.pid, os.WNOHANG)
        finally:
            if process.poll() is None:
                kill_wait(process)


if __name__ == '__main__':
    unittest.main()
