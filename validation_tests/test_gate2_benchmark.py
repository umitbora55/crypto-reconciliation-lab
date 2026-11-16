"""Gate 2 shared-contract, real engine, arithmetic and controller controls."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from validation_lab.benchmark import workload, summarize, file_proof
from validation_lab.benchmark_gate2 import ROOT, bindings, finite_gate, run_worker, parity, execute, payload, validate_record_inventory, write


class Gate2BenchmarkTests(unittest.TestCase):
    def test_three_actual_methods_same_persisted_contract_and_literal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.json"
            input_path.write_text(json.dumps(workload(4,11)))
            trials = []
            for method in ("stdlib_integer","sqlite_integer","production"):
                metric = run_worker(method, input_path, root / method)
                self.assertEqual(metric['common_output']['balances'], {'I0':10000,'I1':10029,'I2':10000,'I3':10000})
                self.assertEqual(metric['common_output']['custody'], {'platform':0,'external':40029})
                self.assertEqual(metric['common_output']['liability'],40029)
                self.assertEqual(set(metric['common_output']['outcomes'].values()),{'MATCHED'})
                self.assertIn('reread_verify',metric['phases'])
                trials.append({'events':4,'repeat':0,'method':method,'status':'PASS','metrics':metric})
            self.assertEqual(parity(trials,[4])[0]['status'],'EQUIVALENT_COMMON_ARITHMETIC')
            for row in parity(trials,[4])[1:]:
                self.assertEqual(row['status'],'NOT_ESTABLISHED')
            changed=copy.deepcopy(trials)
            changed[1]['metrics']['artifacts']['export.json']['sha256']='0'*64
            self.assertEqual(parity(changed,[4])[0]['status'],'PARITY_FAILURE')

    def test_empty_duplicate_and_missing_method_not_equivalent(self):
        with self.assertRaises(ValueError):
            parity([],[])
        with self.assertRaises(ValueError):
            parity([],[100,100])
        self.assertTrue(all(x['status']=='NOT_ESTABLISHED' for x in parity([],[100])))

    def test_same_count_identity_substitution_refused_by_explicit_finite_contract(self):
        data=workload(4,11)
        next(e['record'] for e in data['rows'] if e['record']['kind']=='event')['ref']='REPLACEMENT'
        with self.assertRaisesRegex(ValueError,'COMMON_CONTRACT'):
            finite_gate(data)

    def test_bad_report_time_and_count_metadata_refused(self):
        for field in ('amount','time','count'):
            data=workload(4,11)
            if field=='amount':
                next(e['record'] for e in data['rows'] if e['record']['kind']=='report')['amount']='100.01'
            elif field=='time':
                data['balance_at']='2026-01-04T00:00:00Z'
            else:
                data['events']=400
            with self.subTest(field=field),self.assertRaises(ValueError):
                finite_gate(data)

    def test_one_cent_and_zero_event_boundary_all_methods(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for n,seed,expected in [(0,11,40000),(1,0,40001),(2,0,40001),(3,0,40000)]:
                path=root/f'{n}.json'; path.write_text(json.dumps(workload(n,seed)))
                for method in ('stdlib_integer','sqlite_integer','production'):
                    result=run_worker(method,path,root/f'{n}-{method}')
                    self.assertEqual(result['common_output']['liability'],expected)

    def test_timeout_wait_captures_actual_exit_and_original_stdout(self):
        result=execute([sys.executable,'-u','-c','import time; print("BEFORE_DEADLINE"); time.sleep(5)'],Path.cwd(),0.2)
        self.assertEqual(result['status'],'TIMEOUT')
        self.assertTrue(result['timed_out'])
        self.assertIsInstance(result['exit_code'],int)
        self.assertLess(result['exit_code'],0)
        self.assertEqual(result['stdout'],'BEFORE_DEADLINE\n')

    def test_nonzero_child_exit_preserved(self):
        result=execute([sys.executable,'-c','import sys; sys.exit(17)'],Path.cwd(),1)
        self.assertEqual(result['status'],'FAILED')
        self.assertEqual(result['exit_code'],17)
        self.assertFalse(result['timed_out'])

    def test_new_output_cannot_overwrite_previous_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            path=root/'input.json'; path.write_text(json.dumps(workload(1,11)))
            prior=root/'prior'; prior.mkdir(); (prior/'RED.txt').write_text('original')
            with self.assertRaises(FileExistsError):
                run_worker('production',path,prior)
            self.assertEqual((prior/'RED.txt').read_text(),'original')

    def test_retained_partial_inventory_cannot_be_relabeled_complete(self):
        record={'mode':'triage','bindings':{'reviewed':'source'},'status':'PARTIAL','data_class':'FULLY_SYNTHETIC',
                'institutional_cost_savings':'NOT_PROVEN','institutional_risk_reduction':'NOT_PROVEN',
                'trials':[{'events':n,'repeat':0,'method':'production','seed':11,'status':'NOT_RUN','exit_code':None} for n in (100000,25000,50000)]}
        self.assertEqual(validate_record_inventory(record,'triage',{'reviewed':'source'})['observed'],3)
        for mutation in ('empty','omit','duplicate','substitute','complete','mode','source','false_exit','real_label'):
            bad=copy.deepcopy(record)
            if mutation=='empty': bad['trials']=[]
            elif mutation=='omit': bad['trials'].pop()
            elif mutation=='duplicate': bad['trials'][2]=copy.deepcopy(bad['trials'][0])
            elif mutation=='substitute': bad['trials'][0]['events']=99999
            elif mutation=='complete': bad['status']='COMPLETE'
            elif mutation=='mode': bad['mode']='smoke'
            elif mutation=='source': bad['bindings']={'self_issued':'pin'}
            elif mutation=='false_exit': bad['trials'][0]['status']='TIMEOUT'
            elif mutation=='real_label': bad['data_class']='REAL_PUBLIC_DIRECT'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                validate_record_inventory(bad,'triage',{'reviewed':'source'})

    def test_declared_seed_population_is_finite(self):
        with self.assertRaisesRegex(ValueError,'seed'):
            finite_gate(workload(4,99))

    def test_no_executed_trials_cannot_publish_measured_summary(self):
        methods=('stdlib_integer','sqlite_integer','production')
        trials=[{'events':n,'repeat':r,'method':m,'seed':(11,29,47,71,97)[r],'status':'NOT_RUN','exit_code':None}
                for n in (100,1000,10000) for r in range(5) for m in methods]
        summary,comparisons=summarize(trials)
        for row in comparisons:
            row['semantic_parity']='NOT_ESTABLISHED'
            row['speed_advantage']='DESCRIPTIVE_COMMON_TASK_ONLY; FULL_PRODUCT_INCONCLUSIVE'
        record={'mode':'full','bindings':{'reviewed':'source'},'status':'PARTIAL','data_class':'FULLY_SYNTHETIC',
                'institutional_cost_savings':'NOT_PROVEN','institutional_risk_reduction':'NOT_PROVEN',
                'trials':trials,'parity':parity(trials,[100,1000,10000]),'comparative_status':'INCONCLUSIVE',
                'summary':summary,'comparisons':comparisons}
        self.assertTrue(all(row['completed_repeats']==0 and row['wall_seconds'] is None for row in summary))
        self.assertEqual(validate_record_inventory(record,'full',{'reviewed':'source'})['observed'],45)
        bad=copy.deepcopy(record)
        bad['summary'][0]['completed_repeats']=5
        bad['summary'][0]['wall_seconds']={'p50':0.000001,'p95_nearest_rank':0.000002,'min':0.000001,'max':0.000002}
        with self.assertRaisesRegex(ValueError,'derived summaries'):
            validate_record_inventory(bad,'full',{'reviewed':'source'})
        bad=copy.deepcopy(record)
        bad['comparisons'][0]['n']=5
        bad['comparisons'][0]['median_ratio']=0.0001
        with self.assertRaisesRegex(ValueError,'derived summaries'):
            validate_record_inventory(bad,'full',{'reviewed':'source'})

    def test_executed_trial_requires_actual_nonempty_input_proof(self):
        record={'mode':'triage','bindings':{'reviewed':'source'},'status':'PARTIAL','data_class':'FULLY_SYNTHETIC',
                'institutional_cost_savings':'NOT_PROVEN','institutional_risk_reduction':'NOT_PROVEN',
                'trials':[{'events':n,'repeat':0,'method':'production','seed':11,'status':'NOT_RUN','exit_code':None} for n in (100000,25000,50000)]}
        record['trials'][0].update(status='PASS',exit_code=0,input=None)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'missing input path'):
                validate_record_inventory(record,'triage',{'reviewed':'source'},tmp)
            record['trials'][0]['input']={'path':str(Path(tmp)/'inputs/events100000-seed11.json'),'sha256':'','bytes':0}
            with self.assertRaisesRegex(ValueError,'byte proof'):
                validate_record_inventory(record,'triage',{'reviewed':'source'},tmp)

    def test_actual_retained_worker_artifacts_validate_and_tamper_is_rejected(self):
        # One functional worker, not a comparative timing program; the other44
        # declared trials stay explicitly NOT_RUN and no performance claim follows.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'inputs').mkdir(); (root/'trials').mkdir()
            source=root/'inputs/events100-seed11.json'; write(source,workload(100,11))
            target=root/'trials/n100-r0-production'
            command=[sys.executable,'-B','-m','validation_lab.benchmark_gate2','--worker','production','--input',str(source),'--output',str(target)]
            begun=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
            observation=execute(command,ROOT,10)
            self.assertEqual(observation['exit_code'],0,observation['stderr'])
            metric=json.loads((target/'metrics.json').read_text())
            trial={'events':100,'repeat':0,'method':'production','seed':11,'command':command,'cwd':str(ROOT),
                   'input':{'path':str(source),**file_proof(source)},'started_utc':begun,
                   'completed_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'metrics':metric,**observation,
                   'artifact_inventory':[{'name':name,**proof,'retained':True} for name,proof in metric['artifacts'].items()]}
            write(target/'command.json',trial)
            trials=[trial if (n,r,m)==(100,0,'production') else {'events':n,'repeat':r,'method':m,'seed':(11,29,47,71,97)[r],'status':'NOT_RUN','exit_code':None}
                    for n in (100,1000,10000) for r in range(5) for m in ('stdlib_integer','sqlite_integer','production')]
            summary,comparisons=summarize(trials)
            for row in comparisons:
                row['semantic_parity']='NOT_ESTABLISHED'
                row['speed_advantage']='DESCRIPTIVE_COMMON_TASK_ONLY; FULL_PRODUCT_INCONCLUSIVE'
            record={'mode':'full','bindings':bindings(),'status':'PARTIAL','data_class':'FULLY_SYNTHETIC',
                'institutional_cost_savings':'NOT_PROVEN','institutional_risk_reduction':'NOT_PROVEN',
                'trials':trials,'parity':parity(trials,[100,1000,10000]),'comparative_status':'INCONCLUSIVE',
                'summary':summary,'comparisons':comparisons}
            self.assertEqual(validate_record_inventory(record,'full',bindings(),root)['status'],'PASS')
            (target/'export.json').write_bytes((target/'export.json').read_bytes()+b'TAMPER')
            with self.assertRaisesRegex(ValueError,'retained100-event artifact bytes'):
                validate_record_inventory(record,'full',bindings(),root)


if __name__=='__main__':
    unittest.main()
