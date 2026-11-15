"""Real subprocess deadline, CLI portability and atomic report publication."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from replay_fixtures import (assert_error,assert_reproduced,encoded,export_pair,hashed,
                            load_pair,rebound,verify,write_historical)
from replay_historical_fixtures import historical_0101


class ExecutionReplayProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.pair=export_pair(self.root/'original')

    def worker_command(self,mode,marker,payload=None):
        def command(directory,expected):
            argv=[sys.executable,'-I','-B',str(Path(__file__).with_name('replay_worker.py')),str(directory),mode,str(marker)]
            return argv+([str(payload)] if payload else [])
        return command

    def test_real_blocked_child_hits_deadline_is_killed_and_reaped(self):
        from crypto_reconciliation_lab.replay import api
        marker=self.root/'blocked-child.json';children=[];real_popen=subprocess.Popen
        def spawn(*args,**kwargs):
            child=real_popen(*args,**kwargs);children.append(child);return child
        started=time.monotonic()
        with patch.object(api,'_worker_command',self.worker_command('hang',marker)),patch.object(api.subprocess,'Popen',side_effect=spawn):
            result=verify(self.pair,timeout_seconds=1)
        assert_error(self,result,'REPLAY_TIMEOUT')
        self.assertEqual(len(children),1);self.assertEqual(children[0].returncode,-9)
        self.assertEqual(json.loads(marker.read_bytes())['pid'],children[0].pid)
        self.assertLess(time.monotonic()-started,8)
        self.assertEqual(result['completion']['calculation'],'NOT_COMPLETED')
        evidence=os.environ.get('CRYPTO_EXECUTION_REPLAY_TEST_EVIDENCE')
        if evidence:
            target=Path(evidence)/self._testMethodName;target.mkdir(parents=True,exist_ok=False)
            (target/'observation.json').write_bytes(encoded({'result':result,'child':json.loads(marker.read_bytes()),
                'returncode':children[0].returncode,'duration_seconds':time.monotonic()-started,
                'interpreter':sys.executable,'isolated':bool(sys.flags.isolated)}))

    def test_missing_partial_excessive_and_failed_child_results_never_pass(self):
        from crypto_reconciliation_lab.replay import api
        for mode in ('missing','partial','oversized','failure'):
            with self.subTest(mode=mode),patch.object(api,'_worker_command',self.worker_command(mode,self.root/(mode+'.json'))):
                assert_error(self,verify(self.pair),'REPLAY_LIMIT')

    def test_complete_real_result_is_accepted_and_incomplete_extra_field_is_not(self):
        from crypto_reconciliation_lab.replay import api,worker
        report=worker.verify_bytes(self.pair['context_path'].read_bytes(),self.pair['run_path'].read_bytes(),self.pair['expected'])
        assert_reproduced(self,report)
        payload=self.root/'protocol.json';payload.write_bytes(encoded(report))
        with patch.object(api,'_worker_command',self.worker_command('supplied',self.root/'complete.json',payload)):
            assert_reproduced(self,verify(self.pair))
        invalid=copy.deepcopy(report);del invalid['claims'];invalid['unrelated']=True
        payload.write_bytes(encoded(invalid))
        with patch.object(api,'_worker_command',self.worker_command('supplied',self.root/'incomplete.json',payload)):
            assert_error(self,verify(self.pair),'REPLAY_LIMIT')

    def test_exact_timeout_input_domain(self):
        for value in (True,0,-1,61,1.5,'1',None):
            with self.subTest(value=value):assert_error(self,verify(self.pair,timeout_seconds=value),'REPLAY_INPUT')

    def test_input_paths_are_read_once_then_worker_uses_original_bytes(self):
        from crypto_reconciliation_lab.replay import api
        old=api._run_worker;observed={};before={k:self.pair[k].read_bytes() for k in ('context_path','run_path')}
        def run(context,financial,expected,timeout):
            observed.update(context=context,run=financial)
            # Files change only after the bounded read, so result must remain
            # tied to the first bytes; there must be no hidden worker reread.
            self.pair['context_path'].write_bytes(b'{}');self.pair['run_path'].write_bytes(b'{}')
            return old(context,financial,expected,timeout)
        with patch.object(api,'_run_worker',side_effect=run),patch.object(api,'_read_input',wraps=api._read_input) as reads:
            result=verify(self.pair)
        assert_reproduced(self,result);self.assertEqual(reads.call_count,2)
        self.assertEqual(observed,{'context':before['context_path'],'run':before['run_path']})
        self.assertEqual(result['inputs']['context']['sha256'],hashed(before['context_path']))
        self.assertEqual(result['inputs']['run']['sha256'],hashed(before['run_path']))

    def test_fresh_output_is_atomic_and_inputs_unchanged(self):
        target=self.root/'published';before=[self.pair[k].read_bytes() for k in ('context_path','run_path')]
        result=verify(self.pair,output=target);assert_reproduced(self,result)
        self.assertEqual({p.name for p in target.iterdir()},{'report.json','report.md'})
        self.assertEqual(json.loads((target/'report.json').read_bytes()),result)
        self.assertEqual([self.pair[k].read_bytes() for k in ('context_path','run_path')],before)
        hashes={p.name:hashed(p.read_bytes()) for p in target.iterdir()}
        assert_error(self,verify(self.pair,output=target),'REPLAY_OUTPUT')
        self.assertEqual({p.name:hashed(p.read_bytes()) for p in target.iterdir()},hashes)

    def test_output_final_links_collisions_and_dotdot_canonicalization(self):
        directory=self.root/'existing';directory.mkdir();(directory/'keep').write_bytes(b'owned')
        alias=self.root/'alias';alias.symlink_to(directory,target_is_directory=True)
        dangling=self.root/'dangling';dangling.symlink_to(self.root/'missing')
        for path in (directory,alias,dangling,self.pair['context_path'],self.pair['run_path']):
            with self.subTest(path=path):assert_error(self,verify(self.pair,output=path),'REPLAY_OUTPUT')
        self.assertEqual((directory/'keep').read_bytes(),b'owned');self.assertFalse((self.root/'missing').exists())
        parent=self.root/'parent';parent.mkdir()
        canonical=self.root/'canonical'
        assert_reproduced(self,verify(self.pair,output=parent/'..'/'canonical'))
        self.assertTrue((canonical/'report.json').is_file())
        self.assertFalse(any(p.name.startswith('.canonical') for p in self.root.iterdir()))

    def test_final_dotdot_cannot_create_missing_parent_before_collision(self):
        missing=self.root/'must-not-be-created'
        result=verify(self.pair,output=missing/'..')
        assert_error(self,result,'REPLAY_OUTPUT')
        self.assertFalse(missing.exists())

    @unittest.skipUnless(hasattr(os,'mkfifo'),'named pipe is unavailable')
    def test_named_pipe_input_is_rejected_without_blocking_open(self):
        from crypto_reconciliation_lab.replay import verify_execution_replay
        fifo=self.root/'input-pipe';os.mkfifo(fifo)
        start=time.monotonic()
        result=verify_execution_replay(fifo,self.pair['run_path'],self.pair['expected'])
        assert_error(self,result,'REPLAY_INPUT')
        self.assertLess(time.monotonic()-start,3)

    def test_later_publication_failure_preserves_completed_divergence(self):
        altered=rebound(self.pair,self.root/'divergent',mutate_run=lambda r:r['ledgers']['ASSET_A'].update(liability='12'))
        existing=self.root/'occupied';existing.mkdir();(existing/'keep').write_bytes(b'old')
        result=verify(altered,output=existing);assert_error(self,result,'REPLAY_OUTPUT')
        self.assertEqual(result['replay_state'],'DIVERGED')
        self.assertEqual(result['comparison']['state'],'DIFFERENT')
        self.assertFalse(result['comparison']['equal'])
        self.assertEqual(result['completion']['comparison'],'COMPLETED')
        self.assertEqual((existing/'keep').read_bytes(),b'old')

    def late_child_failure(self,mode,reason):
        import crypto_reconciliation_lab as package
        from crypto_reconciliation_lab.replay import api
        altered=rebound(self.pair,self.root/mode,mutate_run=lambda r:r['ledgers']['ASSET_A'].update(liability='12'))
        def command(directory,expected):
            return [sys.executable,'-I','-B',str(Path(__file__).with_name('replay_worker.py')),
                    str(directory),mode,str(self.root/(mode+'-child.json')),
                    str(Path(package.__file__).resolve().parent.parent),expected]
        with patch.object(api,'_worker_command',command):result=verify(altered)
        assert_error(self,result,reason)
        self.assertEqual(result['replay_state'],'DIVERGED')
        self.assertEqual(result['comparison']['state'],'DIFFERENT')
        self.assertFalse(result['comparison']['equal'])
        self.assertEqual(result['comparison']['total_differences'],1)
        self.assertEqual(result['completion']['comparison'],'COMPLETED')
        return result

    def test_completed_divergence_survives_late_runtime_identity_io_error(self):
        self.late_child_failure('runtime-failure','REPLAY_OUTPUT')

    def test_completed_divergence_survives_child_report_byte_limit(self):
        result=self.late_child_failure('report-limit','REPLAY_LIMIT')
        self.assertEqual(result['comparison']['reported_differences'],0)
        self.assertTrue(result['comparison']['truncated'])
        self.assertEqual(result['comparison']['differences'],[])

    def test_actual_cli_relocated_two_files_without_source_database(self):
        moved=self.root/'transport';moved.mkdir()
        for key,name in (('context_path','context.json'),('run_path','run.json')):shutil.copyfile(self.pair[key],moved/name)
        before={p.name:hashed(p.read_bytes()) for p in moved.iterdir()}
        shutil.rmtree(self.root/'original')
        argv=[sys.executable,'-B',*(['-I'] if sys.flags.isolated else []),'-m','crypto_reconciliation_lab',
              'verify-execution-replay','--context',str(moved/'context.json'),'--run',str(moved/'run.json'),
              '--expected-execution-id',self.pair['expected']]
        done=subprocess.run(argv,capture_output=True,timeout=30)
        self.assertEqual(done.returncode,0,done.stderr.decode());self.assertEqual(done.stderr,b'')
        result=json.loads(done.stdout);assert_reproduced(self,result)
        self.assertEqual({p.name:hashed(p.read_bytes()) for p in moved.iterdir()},before)
        self.assertFalse(self.pair['database'].exists())

    def test_pre_recorded_protected_consumption_imports_no_optional_crypto_or_ai(self):
        from crypto_reconciliation_lab.replay.worker import verify_bytes
        pair=write_historical(self.root/'protected',historical_0101()['after-historical-replay'])
        class DenyOptional:
            def find_spec(self,fullname,path=None,target=None):
                if fullname.split('.')[0] in ('cryptography','numpy','scipy','sklearn'):
                    raise AssertionError('optional dependency requested: '+fullname)
        guard=DenyOptional();sys.meta_path.insert(0,guard)
        try:result=verify_bytes(pair['context_path'].read_bytes(),pair['run_path'].read_bytes(),pair['expected'])
        finally:sys.meta_path.remove(guard)
        assert_reproduced(self,result)
