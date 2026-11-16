"""New research checks do not join the protected historical875 inventory."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from validation_lab import benchmark
from validation_lab import gate3_capacity as capacity


class CapacityResearchTests(unittest.TestCase):
    def test_observer_preserves_full_evidence_and_transaction_counts(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            path=root/'input.json'
            capacity.write(path,benchmark.workload(3,11))
            off=capacity.full_worker(path,root/'off',False)
            on=capacity.full_worker(path,root/'on',True)
            for key in ('artifacts','financial_projection','run_id','counts','sqlite_settings'):
                self.assertEqual(off[key],on[key],key)
            self.assertEqual(on['buckets']['ingest:sql_commit']['calls'],20)
            self.assertEqual(on['buckets']['ingest:sql_begin']['calls'],20)
            self.assertEqual(on['counts']['runs'],1)
            self.assertGreater(on['counts']['evidence'],0)

    def test_readback_uses_committed_database_not_progress(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            path=root/'input.json'
            capacity.write(path,benchmark.workload(0,11))
            capacity.full_worker(path,root/'run',False)
            capacity.write(root/'run/progress.json',{'committed_receipts':999999})
            observed=capacity.database_readback(root/'run')
            self.assertEqual(observed['committed_rows']['receipts'],17)
            self.assertTrue(observed['originals_unchanged'])

    def test_missing_database_is_not_run(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(capacity.database_readback(Path(root))['status'],'NOT_RUN')

    def test_deleted_historical_input_is_not_regenerated(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            result=capacity.program(root/'output',root/'missing-history')
            self.assertEqual(result['status'],'ERROR')
            self.assertIn('HISTORICAL_INPUT_MISSING_OR_SUBSTITUTED',result['termination_reason'])
            self.assertFalse((root/'output/inputs/events100-seed11.json').exists())

    def test_readback_budget_prevents_copy(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            path=root/'input.json'
            capacity.write(path,benchmark.workload(0,11))
            capacity.full_worker(path,root/'run',False)
            before=capacity.proof(root/'run/input.sqlite3')
            result=capacity.database_readback(root/'run',root,disk_limit=1)
            self.assertEqual(result['status'],'NOT_RUN')
            self.assertEqual(before,capacity.proof(root/'run/input.sqlite3'))
            self.assertFalse((root/'run/postprocess-recovery-copy').exists())

    def test_disappearing_journal_does_not_abort_disk_observation(self):
        candidate=mock.Mock()
        candidate.is_file.return_value=True
        candidate.stat.side_effect=FileNotFoundError('SQLite committed and removed journal')
        with mock.patch.object(Path,'rglob',return_value=iter([candidate])):
            self.assertEqual(capacity.disk_bytes(Path('/unused')),0)

    def test_unexpected_controller_exception_kills_and_waits_worker(self):
        children=[]
        def broken(output,history,*args):
            output.mkdir()
            child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True)
            children.append(child)
            capacity.ACTIVE_PROCESS=child
            capacity.PROGRAM_RECORD={'trials':[]}
            raise RuntimeError('independent unexpected sampler failure')
        try:
            with tempfile.TemporaryDirectory() as root, mock.patch.object(capacity,'_program',side_effect=broken):
                result=capacity.program(Path(root)/'out',Path(root)/'history')
                self.assertEqual(result['status'],'ERROR')
                self.assertEqual(result['active_worker_exit_code'],-9)
                self.assertIsNotNone(children[0].poll(),'controller left owned worker alive')
                self.assertEqual(children[0].returncode,-9)
        finally:
            for child in children:
                if child.poll() is None: child.kill()
                child.wait()

    def test_existing_evidence_directory_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            (root/'results.json').write_text('historical failure')
            with self.assertRaises(FileExistsError):
                capacity.program(root,root/'missing-history')
            self.assertEqual((root/'results.json').read_text(),'historical failure')

    def test_missing_selected_continuation_input_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            historical=root/'history/common-full/inputs/events100-seed11.json'
            historical.parent.mkdir(parents=True)
            capacity.write(historical,benchmark.workload(100,11))
            protocol=json.loads(capacity.PROTOCOL.read_text())
            protocol['roster']=protocol['roster'][:1]
            protocol['continuation']={'input_root':str(root/'missing-selected-capture')}
            path=root/'continuation.json'
            capacity.write(path,protocol)
            result=capacity.program(root/'out',root/'history',path)
            self.assertEqual(result['status'],'ERROR')
            self.assertIn('HISTORICAL_INPUT_MISSING_OR_SUBSTITUTED',result['termination_reason'])
            self.assertFalse((root/'out/inputs/events100-seed11.json').exists())

    def test_preregistered_caps_and_separate_populations(self):
        protocol=json.loads(capacity.PROTOCOL.read_text())
        rows=protocol['roster']
        self.assertEqual(len({r['id'] for r in rows}),len(rows))
        self.assertEqual([r['wall_cap'] for r in rows if r['classification']=='ORIGINAL_60S_CAP'],[60,60,60])
        self.assertEqual([r['wall_cap'] for r in rows if r['classification']=='EXTENDED_DIAGNOSTIC'],[120,180])
        self.assertFalse(protocol['replay']['ordinary_ingestion_is_replay_proof'])


if __name__=='__main__':
    unittest.main()
