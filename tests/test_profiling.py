"""Stage 3.2 profiler isolation, budget orchestration and outcome regressions."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tracemalloc
import unittest
from unittest.mock import patch
from crypto_reconciliation_lab.lab.common import build_fingerprint, digest_bytes, load, save
from crypto_reconciliation_lab.lab.profile_worker import run_job
from crypto_reconciliation_lab.lab.profiling import MODES, PROFILES, normal_statistics, run_profiling
from crypto_reconciliation_lab.lab.runner import generate_bundle
from crypto_reconciliation_lab.lab.watchdog import Budgets


class ProfilingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.gate = self.root / 'gate.json'
        self.gate.write_text('{}')
        self.fingerprint = build_fingerprint()

    def gate_patch(self):
        return patch('crypto_reconciliation_lab.lab.profiling.correctness_gate', return_value={'build_fingerprint': self.fingerprint})

    def test_real_small_workers_are_isolated_and_have_equal_financial_evidence(self):
        with self.gate_patch():
            report = run_profiling(self.gate, self.root / 'output',
                Budgets(total_seconds=60, phase_seconds=20, poll_seconds=.02), profiles=(('SMALL',12,2),))
        self.assertEqual((report['status'], report['correctness']), ('COMPLETED','PASSED'))
        profile = report['profiles'][0]
        self.assertEqual([t['measurement_mode'] for t in profile['trials']], list(MODES))
        workers = [t['worker'] for t in profile['trials']]
        self.assertEqual(len({w['run_id'] for w in workers}), 1)
        self.assertEqual(len({w['files']['report.json']['sha256'] for w in workers}), 1)
        self.assertEqual(len({w['files']['report.md']['sha256'] for w in workers}), 1)
        self.assertEqual(len({t['command'][-1] for t in profile['trials']}), 5)
        self.assertEqual(len(profile['statistics']['ingest_jsonl_seconds']['raw']), 3)
        for worker in workers:
            self.assertEqual(worker['counts']['runs'], 1)
            self.assertEqual(worker['counts']['trace'], 12)
            self.assertGreater(worker['counts']['receipts'], 12)
            self.assertEqual(worker['pragmas']['synchronous'], 2)
            self.assertTrue(worker['oracle']['passed'])
            self.assertTrue(worker['restart_equal'])
        self.assertFalse(workers[0]['cpu_profiles']); self.assertFalse(workers[0]['python_memory'])
        self.assertEqual(set(workers[3]['cpu_profiles']), {'ingest_jsonl_seconds','reconcile_and_persist_seconds'})
        self.assertFalse(workers[3]['python_memory']); self.assertFalse(workers[4]['cpu_profiles'])
        self.assertEqual(len(workers[4]['python_memory']),5)
        for measurement in workers[4]['python_memory'].values():
            self.assertGreaterEqual(measurement['peak_since_reset_bytes'], measurement['start_current_bytes'])
            self.assertIn('net live Python', measurement['interpretation'])
        self.assertTrue(list((self.root/'output').rglob('*.pstats')))
        self.assertTrue(list((self.root/'output').rglob('*.snapshot')))
        self.assertFalse(list((self.root/'output').rglob('*.sqlite3')))
        self.assertEqual(PROFILES,(('P1',1000,20),('P3',1000,100),('P2',10000,20)))

    def test_false_readback_survives_later_snapshot_failure(self):
        bundle=self.root/'readback-input';generate_bundle(bundle,(11,),12,2,('CLEAN',))
        trial=self.root/'snapshot-failure';trial.mkdir()
        job=dict(mode='tracemalloc',trial=str(trial),case=str(bundle/'seed-11/CLEAN'),seed=11,events=12,investors=2,generation_seconds=0)
        original=tracemalloc.take_snapshot
        calls=0
        def snapshot():
            nonlocal calls
            calls+=1
            if calls==10:raise RuntimeError('controlled post-readback snapshot failure')
            return original()
        with patch('crypto_reconciliation_lab.store.Store.read_run',return_value={}),patch('crypto_reconciliation_lab.lab.profile_worker.tracemalloc.take_snapshot',side_effect=snapshot):
            self.assertEqual(run_job(job),2)
        result=load(trial/'result.json')
        self.assertEqual(result['correctness'],'FAILED')
        self.assertFalse(result['restart_equal'])
        self.assertIn('controlled post-readback snapshot failure',result['error'])

    def fake_worker(self, mode):
        return dict(status='COMPLETED',correctness='PASSED',completion_state='COMPLETED',worker_role='trial',
            measurement_mode=mode,oracle={'passed':True},restart_equal=True,input_sha256='input',config_sha256='config',
            run_id='run',build_fingerprint=self.fingerprint,pragmas={'synchronous':2},peak_rss_bytes=1234,
            receipts_per_ingest_second=20,timings={k:1 for k in ('db_setup_seconds','ingest_jsonl_seconds','reconcile_and_persist_seconds','export_seconds','reopen_readback_seconds')},
            process_cpu_seconds={k:.5 for k in ('db_setup_seconds','ingest_jsonl_seconds','reconcile_and_persist_seconds','export_seconds','reopen_readback_seconds')},
            files={k:dict(bytes=10,sha256=k) for k in ('trial.sqlite3','report.json','report.md')})

    def fake_supervisor(self, mutation=None):
        calls = []
        def supervise(command,cwd,trial,temporary,budgets,deadline,env):
            job = load(command[-1]); calls.append((job, deadline, temporary))
            trial.mkdir()
            if job['mode']=='generate':
                generate_bundle(job['bundle'],(11,),job['events'],job['investors'],('CLEAN',))
                worker = dict(status='COMPLETED',worker_role='generate',timings={'generation_seconds':.1})
            else:
                worker = self.fake_worker(job['mode'])
                worker['input_sha256'] = digest_bytes((Path(job['case'])/'input.jsonl').read_bytes())
                worker['config_sha256'] = digest_bytes((Path(job['case'])/'config.json').read_bytes())
            outcome = dict(status='COMPLETED',completion_state='COMPLETED',correctness='PASSED',worker=worker,exit_code=0)
            if mutation:mutation(job,outcome)
            save(trial/'result.json',worker)
            return outcome
        return calls, supervise

    def test_known_failure_in_any_mode_halts_every_later_worker(self):
        for mode in ('normal','cprofile','tracemalloc'):
            with self.subTest(mode=mode):
                def mutate(job,result):
                    if job['mode']==mode:
                        result['status']='RESOURCE_LIMIT';result['completion_state']='RESOURCE_LIMIT'
                        result['worker']['oracle']['passed']=False
                calls, fake = self.fake_supervisor(mutate)
                with self.gate_patch(),patch('crypto_reconciliation_lab.lab.profiling.supervise',side_effect=fake):
                    r=run_profiling(self.gate,self.root/mode,profiles=(('FIRST',24,2),('SMALLER',12,2)))
                self.assertEqual(r['correctness'],'FAILED')
                self.assertEqual(r['status'],'CORRECTNESS_FAILED')
                self.assertTrue(all(t['status']=='NOT_ATTEMPTED_CORRECTNESS' for t in r['profiles'][1]['trials']))
                self.assertEqual(sum(job['mode']=='generate' for job,_,_ in calls),1)
                self.assertEqual(len({deadline for _,deadline,_ in calls}),1)
                self.assertTrue(all(Path(temp)==self.root/mode for _,_,temp in calls))

    def test_correctness_only_abort_does_not_invent_a_budget_failure(self):
        def mutate(job,result):
            if job['mode']=='normal':result['worker']['oracle']['passed']=False
        calls,fake=self.fake_supervisor(mutate)
        with self.gate_patch(),patch('crypto_reconciliation_lab.lab.profiling.supervise',side_effect=fake):
            r=run_profiling(self.gate,self.root/'correctness-only',profiles=(('FIRST',24,2),('SECOND',12,2)))
        self.assertEqual(r['correctness'],'FAILED')
        self.assertEqual(r['completion_state'],'STOPPED_CORRECTNESS')
        self.assertEqual(r['profiles'][0]['completion_state'],'STOPPED_CORRECTNESS')

    def test_readback_failure_cannot_be_masked_by_timeout(self):
        def mutate(job,result):
            if job['mode']=='normal':
                result.update(status='TIMED_OUT',completion_state='TIMED_OUT')
                result['worker']['restart_equal']=False
        calls, fake=self.fake_supervisor(mutate)
        with self.gate_patch(),patch('crypto_reconciliation_lab.lab.profiling.supervise',side_effect=fake):
            r=run_profiling(self.gate,self.root/'readback',profiles=(('FIRST',24,2),('SMALLER',12,2)))
        self.assertEqual(r['correctness'],'FAILED');self.assertEqual(len(calls),2)
        t=r['profiles'][0]['trials'][0]
        self.assertEqual(t['completion_state'],'TIMED_OUT')
        self.assertEqual(t['correctness'],'FAILED')

    def test_profiler_budget_blocks_related_workloads_but_not_smaller(self):
        def mutate(job,result):
            if job['mode']=='cprofile' and job['events']==24:
                result.update(status='RESOURCE_LIMIT',completion_state='RESOURCE_LIMIT')
                result['worker'].pop('oracle');result['worker'].pop('restart_equal')
        calls,fake=self.fake_supervisor(mutate)
        with self.gate_patch(),patch('crypto_reconciliation_lab.lab.profiling.supervise',side_effect=fake):
            r=run_profiling(self.gate,self.root/'budget',profiles=(('FIRST',24,2),('LARGER',48,2),('SMALLER',12,2)))
        self.assertEqual(r['status'],'PARTIAL_BUDGET')
        self.assertIsNotNone(r['profiles'][0]['statistics'])
        self.assertEqual(r['profiles'][0]['trials'][3]['correctness'],'UNKNOWN')
        self.assertEqual(r['profiles'][1]['status'],'NOT_ATTEMPTED_BUDGET')
        self.assertEqual(r['profiles'][2]['status'],'COMPLETED')
        self.assertEqual(len({d for _,d,_ in calls}),1)

    def test_financial_parity_or_build_change_halts_all_modes(self):
        for change in ('run_id','build_fingerprint','input_sha256','pragmas'):
            with self.subTest(change=change):
                def mutate(job,result):
                    if job['mode']=='cprofile':result['worker'][change]='different'
                calls,fake=self.fake_supervisor(mutate)
                with self.gate_patch(),patch('crypto_reconciliation_lab.lab.profiling.supervise',side_effect=fake):
                    r=run_profiling(self.gate,self.root/change,profiles=(('FIRST',24,2),('SECOND',12,2)))
                self.assertEqual(r['correctness'],'FAILED')
                self.assertTrue(r['profiles'][0]['trials'][3]['parity_failed'])
                self.assertEqual(r['profiles'][0]['trials'][4]['status'],'NOT_ATTEMPTED_CORRECTNESS')

    def test_statistics_exclude_profiler_and_unverified_trials(self):
        trials=[dict(status='COMPLETED',completion_state='COMPLETED',correctness='PASSED',
            measurement_mode=mode,worker=self.fake_worker(mode)) for mode in MODES]
        trials[3]['worker']['timings']['ingest_jsonl_seconds']=999
        self.assertEqual(normal_statistics(trials)['ingest_jsonl_seconds']['raw'],[1,1,1])
        trials[1]['worker']['restart_equal']=False
        self.assertIsNone(normal_statistics(trials))
        self.assertIsNone(normal_statistics(trials[:2]))

    def test_invalid_gate_never_starts_generation(self):
        with patch('crypto_reconciliation_lab.lab.profiling.supervise') as worker:
            with self.assertRaises(ValueError):run_profiling(self.gate,self.root/'bad-gate')
            worker.assert_not_called()
        self.assertFalse((self.root/'bad-gate').exists())


if __name__=='__main__':
    unittest.main()
