"""Protocol regressions use controlled worker observations, never fabricated benchmarks."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import shutil
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT / 'scripts'
if not (SCRIPTS / 'run_ab_stage3_3.py').exists():
    SCRIPTS = Path(__file__).resolve().parent

def module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

ab = module('run_ab_stage3_3')
worker = module('ab_worker_stage3_3')
retention = module('ab_retention_stage3_3')

class ABProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.variants = {v: dict(python_executable='/isolated/' + v + '/bin/python',
            package_root='/isolated/' + v + '/package', package_version=version,
            schema_version=schema, build_fingerprint=v * 64, python='same-python',
            sqlite='same-sqlite', correctness=str(self.root / (v + '-gate.json')))
            for v, version, schema in [('A', '0.3.2', 2), ('B', '0.3.3', 3)]}
        self.jobs = []
        self.change = None

    def fake_supervise(self, command, cwd, trial, temporary_root, budgets, deadline, env):
        job = json.loads(Path(command[-1]).read_text())
        trial = Path(trial); trial.mkdir()
        self.jobs.append(dict(job=copy.deepcopy(job), command=list(map(str, command)), deadline=deadline))
        provenance = {k:job['expected'][k] for k in ('package_version', 'schema_version', 'build_fingerprint')}
        provenance.update(package_file=job['expected']['package_root'] + '/__init__.py',
            dont_write_bytecode=True,pycache_prefix=job['expected']['bytecode_policy']['pycache_prefix'],
            instrumentation_sha256=ab.file_sha256(SCRIPTS / 'ab_worker_stage3_3.py'))
        observed = dict(status='COMPLETED', completion_state='COMPLETED', provenance=provenance)
        if job['mode'] == 'generate':
            case = Path(job['bundle']) / 'seed-11/CLEAN'; case.mkdir(parents=True)
            (case/'config.json').write_text('{}\n'); (case/'input.jsonl').write_text('{}\n')
            observed['timings'] = dict(generation_seconds=0.01)
        elif job['mode'] in ('normal','cprofile'):
            index = ['receipts_hash_lookup'] if job['variant']=='B' else []
            observed.update(oracle=dict(passed=True), restart_equal=True,
                input_sha256=ab.file_sha256(Path(job['case'])/'input.jsonl'),
                config_sha256=ab.file_sha256(Path(job['case'])/'config.json'),
                run_id='fixed-'+str(job['events'])+'-'+str(job['investors']),
                counts=dict(receipts=job['events']+9, evidence=7, trace=job['events']),
                pragmas=dict(synchronous=2,journal_mode='delete'),
                timings={k:1.0 for k in ab.CORE_PHASES},
                process_cpu_seconds={k:0.5 for k in ab.CORE_PHASES},
                peak_rss_bytes=1024,receipts_per_ingest_second=100,
                files={name:dict(bytes=5,sha256='same-'+name) for name in ('trial.sqlite3','report.json','report.md')},
                index_before_ingest=dict(user_version=job['expected']['schema_version'],receipts_count=0,
                    index_list=[[0,n,0,'c',0] for n in index],
                    indexes={n:dict(info=[[0,1,'receipt_hash']],xinfo=[[0,1,'receipt_hash',0,'BINARY',1],[1,-1,None,0,'BINARY',0]]) for n in index}))
            for name in ('trial.sqlite3','report.json','report.md'):(trial/name).write_text('test\n')
        result = dict(status='COMPLETED',completion_state='COMPLETED',worker=observed,elapsed_seconds=6.0,exit_code=0)
        if self.change:self.change(job,result)
        (trial/'result.json').write_text(json.dumps(observed))
        return result

    def run_controller(self, profiles=(('P1',12,2),('P3',12,3),('P2',24,2))):
        with patch.object(ab,'supervise',side_effect=self.fake_supervise):
            return ab.run_ab(self.variants,self.root/'output',profiles=profiles,
                worker_script=SCRIPTS/'ab_worker_stage3_3.py',cwd=self.root)

    def test_balanced_order_single_deadline_and_diagnostics_after_all_normals(self):
        result=self.run_controller()
        self.assertEqual(result['status'],'COMPLETED')
        measured=[x for x in self.jobs if x['job']['mode'] in ('normal','cprofile')]
        self.assertEqual([x['job']['variant'] for x in measured[:18]],list('ABBAAB'*3))
        self.assertEqual([x['job']['mode'] for x in measured],['normal']*18+['cprofile']*2)
        self.assertEqual([(x['job']['events'],x['job']['investors']) for x in measured[-2:]],[(24,2),(24,2)])
        performance=[x for x in self.jobs if x['job']['mode']!='gate']
        self.assertEqual(len({x['deadline'] for x in performance}),1)
        self.assertTrue(all(x['command'][1:5]==['-I','-B','-X','pycache_prefix='+result['bytecode_policy']['pycache_prefix']] for x in self.jobs))
        self.assertEqual(len({x['command'][5] for x in self.jobs}),1)
        self.assertFalse(Path(result['bytecode_policy']['pycache_prefix']).exists())
        self.assertFalse(result['bytecode_policy']['cache_path_exists_after'])
        self.assertTrue(result['source_unchanged'])
        self.assertFalse(result['runtime_preserved'])
        self.assertFalse(Path(result['storage']['owned_runtime']).exists())
        self.assertEqual(result['retention']['original_deadline_monotonic'],result['performance_deadline_monotonic'])
        self.assertTrue(result['retention']['verified'])
        self.assertEqual(result['finalization']['original_deadline_monotonic'],result['performance_deadline_monotonic'])
        receipt=json.loads((self.root/'output/finalization.json').read_text())
        self.assertEqual(receipt['status'],'COMPLETED')
        self.assertEqual(receipt['report_sha256'],ab.file_sha256(self.root/'output/ab.json'))
        self.assertEqual(receipt['markdown_sha256'],ab.file_sha256(self.root/'output/ab.md'))
        self.assertTrue((self.root/'output/migration-source/schema2.sqlite3').exists())
        self.assertEqual(len(result['profiles'][0]['statistics']['A']['ingest_jsonl_seconds']['raw']),3)

    def test_gate_failure_stops_before_generation(self):
        def change(job,result):
            if job['mode']=='gate':result.update(status='ERROR',completion_state='ERROR')
        self.change=change;result=self.run_controller()
        self.assertEqual(result['gate_status'],'FAILED')
        self.assertEqual([x['job']['mode'] for x in self.jobs],['gate'])

    def test_known_failure_survives_budget_and_stops_all_later_work(self):
        def change(job,result):
            if job['mode']=='normal':
                result['worker']['oracle']['passed']=False
                result.update(status='RESOURCE_LIMIT',completion_state='RESOURCE_LIMIT')
        self.change=change;result=self.run_controller()
        self.assertEqual(result['correctness'],'FAILED')
        self.assertEqual(result['status'],'CORRECTNESS_FAILED')
        self.assertEqual(sum(x['job']['mode']=='normal' for x in self.jobs),1)
        self.assertEqual(sum(x['job']['mode']=='generate' for x in self.jobs),1)
        self.assertTrue(all(t['status']=='NOT_ATTEMPTED_CORRECTNESS' for t in result['diagnostics']))

    def test_parity_failure_stops_remaining_workers_and_retains_counterexample(self):
        def change(job,result):
            if job['mode']=='normal' and job['variant']=='B':result['worker']['files']['report.md']['sha256']='changed'
        self.change=change;result=self.run_controller()
        self.assertEqual(result['status'],'CORRECTNESS_FAILED')
        self.assertEqual(sum(x['job']['mode']=='normal' for x in self.jobs),2)
        self.assertTrue((self.root/'output/P1/pair-1-B/counterexample-input/input.jsonl').exists())

    def test_candidate_descending_index_is_rejected_before_comparison(self):
        def change(job,result):
            if job['mode']=='normal' and job['variant']=='B':
                result['worker']['index_before_ingest']['indexes']['receipts_hash_lookup']['xinfo'][0][3]=1
        self.change=change;result=self.run_controller()
        self.assertEqual(result['status'],'CORRECTNESS_FAILED')
        self.assertIn('index',result['profiles'][0]['trials'][1]['reason'])

    def test_unknown_budget_stops_related_work_without_claiming_wrong_finance(self):
        def change(job,result):
            if job['mode']=='normal':
                result['worker'].pop('oracle');result['worker'].pop('restart_equal')
                result.update(status='TIMED_OUT',completion_state='TIMED_OUT')
        self.change=change;result=self.run_controller()
        self.assertEqual(result['correctness'],'UNKNOWN')
        self.assertEqual(result['completion_state'],'PARTIAL_BUDGET')
        self.assertEqual(sum(x['job']['mode']=='normal' for x in self.jobs),1)
        self.assertTrue(all(t['correctness']=='UNKNOWN' for t in result['diagnostics']))

    def test_pair_arithmetic_and_three_observation_statistics_exclude_diagnostics(self):
        result=self.run_controller(profiles=(('P2',12,2),))
        trials=copy.deepcopy(result['profiles'][0]['trials'])
        for trial in trials:
            trial['worker']['timings']['ingest_jsonl_seconds']=2.0 if trial['variant']=='A' else 3.0
        pair=ab.paired_results(trials)[0]['metrics']['ingest_jsonl_seconds']
        self.assertEqual(pair,dict(A=2.0,B=3.0,B_minus_A=1.0,B_over_A=1.5))
        diagnostic=copy.deepcopy(trials[0]);diagnostic['measurement_mode']='cprofile';diagnostic['worker']['timings']['ingest_jsonl_seconds']=900
        stats=ab.normal_statistics(trials+[diagnostic],'A')['ingest_jsonl_seconds']
        self.assertEqual(stats,dict(raw=[2.0,2.0,2.0],min=2.0,median=2.0,max=2.0))
        self.assertIsNone(ab.normal_statistics(trials[:-1],'B'))

    def test_provenance_rejects_wrong_build_root_or_distribution(self):
        expected=self.variants['A']
        actual={k:expected[k] for k in ('package_version','schema_version','build_fingerprint')}
        actual.update(package_file=expected['package_root']+'/__init__.py',distribution_version='0.3.2',financial_rule='stage2-v2')
        worker.check_provenance(actual,expected)
        for key,value in [('build_fingerprint','changed'),('package_file','/different/__init__.py'),('package_file',expected['package_root']+'/nested/__init__.py'),('distribution_version','0.3.3')]:
            bad=dict(actual);bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):worker.check_provenance(bad,expected)

    def test_changed_final_source_is_failed_and_stops_remaining_probe(self):
        def change(job,result):
            if job['mode']=='probe' and job['variant']=='A':
                result['worker'].update(provenance_verified=False,correctness='FAILED')
                result.update(status='ERROR',completion_state='ERROR')
        self.change=change;result=self.run_controller()
        self.assertEqual(result['status'],'CORRECTNESS_FAILED')
        self.assertEqual(result['correctness'],'FAILED')
        self.assertFalse(result['source_unchanged'])
        self.assertEqual(result['final_probes']['B']['status'],'NOT_ATTEMPTED')
        self.assertEqual(sum(x['job']['mode']=='probe' for x in self.jobs),1)

    def test_existing_bytecode_prefix_is_rejected_before_workers(self):
        cache=self.root/'existing-cache';cache.mkdir()
        with patch.object(ab,'supervise',side_effect=self.fake_supervise),self.assertRaisesRegex(ValueError,'must not exist'):
            ab.run_ab(self.variants,self.root/'output',worker_script=SCRIPTS/'ab_worker_stage3_3.py',pycache_prefix=cache)
        self.assertEqual(self.jobs,[])

    def test_combined_retention_tree_budget_blocks_copy_before_launch(self):
        runtime=self.root/'runtime';destination=self.root/'retained'
        runtime.mkdir();destination.mkdir()
        (runtime/'a').write_bytes(b'123456');(destination/'b').write_bytes(b'123456')
        budgets=dict(phase_seconds=120,temporary_bytes=11,rss_bytes=1024,poll_seconds=.01)
        with patch.object(retention.subprocess,'Popen',side_effect=AssertionError('copy must not launch')):
            result=retention.retain_runtime('script','python',[],runtime,destination,runtime,budgets,time.monotonic()+60,lambda pid:None)
        self.assertEqual(result['status'],'RESOURCE_LIMIT')
        self.assertEqual(result['last_observation']['runtime_bytes'],6)
        self.assertEqual(result['last_observation']['retained_bytes'],6)
        self.assertEqual(result['last_observation']['combined_tree_bytes'],12)
        self.assertTrue(runtime.exists())

    def test_retention_budget_keeps_known_failure_and_owned_runtime(self):
        def change(job,result):
            if job['mode']=='normal':result['worker']['oracle']['passed']=False
        self.change=change
        captured={}
        def exhausted(helper,script,python,flags,source,destination,owned,budgets,deadline,rss_reader):
            captured.update(deadline=deadline,owned=owned)
            return dict(status='RESOURCE_LIMIT',completion_state='RESOURCE_LIMIT',verified=False,reason='injected retention budget observation')
        with patch.object(ab,'supervise_final_retention',side_effect=exhausted):
            result=self.run_controller()
        self.addCleanup(shutil.rmtree,captured['owned'])
        self.assertEqual(result['correctness'],'FAILED')
        self.assertEqual(result['status'],'CORRECTNESS_FAILED')
        self.assertEqual(result['completion_state'],'PARTIAL_BUDGET')
        self.assertTrue(result['runtime_preserved'])
        self.assertTrue(captured['owned'].exists())
        self.assertEqual(captured['deadline'],result['performance_deadline_monotonic'])
        self.assertTrue((self.root/'output/ab.json').exists())

    def administrative_retention_error(self,mode):
        def change(job,result):
            if job['mode']==mode and job['variant']=='A':
                result['worker'].update(provenance_verified=False,correctness='FAILED')
                result.update(status='ERROR',completion_state='ERROR')
        self.change=change;real_save=ab.save
        def fail_retention(path,value):
            path=Path(path)
            if path.name=='worker-job.json' and (('gates' in path.parts and mode=='gate') or ('final-probes' in path.parts and mode=='probe')):
                raise OSError('injected administrative retention failure')
            return real_save(path,value)
        with patch.object(ab,'save',side_effect=fail_retention):result=self.run_controller()
        self.assertEqual(result['correctness'],'FAILED')
        self.assertEqual(result['status'],'CORRECTNESS_FAILED')
        self.assertTrue(list((self.root/'output').glob('owned-ab-*/**/result.json')))

    def test_failed_gate_survives_retention_exception(self):
        self.administrative_retention_error('gate')

    def test_failed_final_probe_survives_retention_exception(self):
        self.administrative_retention_error('probe')

    def test_streamed_hash_matches_literal_reference(self):
        path=self.root/'literal';path.write_bytes(b'abc')
        literal='ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
        self.assertEqual(ab.file_sha256(path),literal)
        self.assertEqual(worker.file_sha256(path),literal)

if __name__=='__main__':unittest.main()
