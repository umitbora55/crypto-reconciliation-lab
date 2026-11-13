import ast
import copy
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from crypto_reconciliation_lab import Store,reconcile
from crypto_reconciliation_lab.lab import GENERATOR_VERSION
from crypto_reconciliation_lab.lab.common import encoded,load,save
from crypto_reconciliation_lab.lab.oracle import balances,decimal_text,financial_text,units
from crypto_reconciliation_lab.lab.world import generate,config,wire
from crypto_reconciliation_lab.lab.faults import SCENARIOS,build_case
from crypto_reconciliation_lab.lab.runner import generate_bundle,run_bundle,evaluate,verify_bundle_files
from crypto_reconciliation_lab.lab.scoring import score
from crypto_reconciliation_lab.lab.watchdog import Budgets,supervise,current_rss
from crypto_reconciliation_lab.lab.benchmark import correctness_gate,statistics_for,run_benchmark


def manual_world():
    a='ASSET_A';b='ASSET_B'
    def event(ref,asset,kind,q,sender,recipient,custody,at):
        return dict(ref=ref,asset=asset,kind=kind,units=q,sender=sender,recipient=recipient,custody=custody,at=str(at),sequence=1)
    return dict(assets={a:8,b:2},investors=['I1','I2'],opening={
        a:dict(investors={'I1':600000000,'I2':400000000},custody={'platform':200000000,'external':800000000}),
        b:dict(investors={'I1':10,'I2':20},custody={'platform':5,'external':25})},events=[
        event('A1',a,'transfer',100000000,'I1','I2',None,1),event('A2',a,'deposit',200000000,None,'I1','external',2),
        event('A3',a,'withdrawal',100000000,'I2',None,'external',3),event('B1',b,'deposit',20,None,'I1','external',2)])


class OracleTests(unittest.TestCase):
    def test_manual_clean_balances(self):
        w=manual_world();r=financial_text(w,balances(w,'3'))
        self.assertEqual(r['ASSET_A'],dict(investor_balances={'I1':'7','I2':'4'},liability='11',custody_rollforward={'platform':'2','external':'9'}))
        self.assertEqual(r['ASSET_B'],dict(investor_balances={'I1':'0.3','I2':'0.2'},liability='0.5',custody_rollforward={'platform':'0.05','external':'0.45'}))

    def test_manual_correction_sign_table(self):
        w=manual_world()
        cases=[('A2','REPLACE',300000000,('8','4','12','10')),('A2','VOID',None,('5','4','9','7')),
               ('A1','VOID',None,('8','3','11','9')),('A3','VOID',None,('7','5','12','10')),
               ('A3','REPLACE',200000000,('7','3','10','8')),('A1','REPLACE',200000000,('6','5','11','9'))]
        for target,mode,q,expected in cases:
            with self.subTest(target=target,mode=mode):
                r=financial_text(w,balances(w,'3',[dict(target=target,mode=mode,units=q)]))['ASSET_A']
                self.assertEqual((r['investor_balances']['I1'],r['investor_balances']['I2'],r['liability'],r['custody_rollforward']['external']),expected)

    def test_smallest_units_and_scale_18(self):
        for text,scale,q in [('0.01',2,1),('0.00000001',8,1),('0.000000000000000001',18,1),('0',18,0),('-0.01',2,-1),('12',0,12)]:
            self.assertEqual(units(text,scale),q);self.assertEqual(decimal_text(q,scale),text)
        self.assertEqual(units('0.10',2),10)

    def test_invalid_decimal_types_and_null_are_not_zero(self):
        for value in (None,0,True,0.1,[],{},'NaN','Infinity','1e2','0.001',' 1'):
            with self.subTest(value=value),self.assertRaises(ValueError):units(value,2)
        self.assertEqual(units('0',2),0)
        with self.assertRaises(ValueError):decimal_text(None,2)

    def test_oracle_refuses_invalid_world_instead_of_clipping(self):
        w=manual_world();w['events'][0]['units']=700000000
        with self.assertRaises(ValueError):balances(w,'3')
        with self.assertRaises(ValueError):balances(manual_world(),'3',[dict(target='missing',mode='VOID')])

    def test_transfer_preserves_total_liability_and_custody(self):
        r=balances(manual_world(),'1')['ASSET_A']
        self.assertEqual(r['liability'],1000000000);self.assertEqual(r['custody'],{'platform':200000000,'external':800000000})

    def test_partial_observation_is_not_full_truth(self):
        w=manual_world()
        self.assertEqual(balances(w,'3')['ASSET_A']['liability'],1100000000)
        self.assertEqual(balances(w,'3',exclude=['A3'])['ASSET_A']['liability'],1200000000)

    def test_independence_from_production_domain_functions(self):
        with patch('crypto_reconciliation_lab.engine.reconcile',side_effect=AssertionError('engine called')),patch('crypto_reconciliation_lab.model.normalize',side_effect=AssertionError('normalizer called')),patch('crypto_reconciliation_lab.corrections.resolve_corrections',side_effect=AssertionError('resolver called')):
            w=generate(11,12,2);wire(w);build_case(w,'F1');balances(manual_world(),'3')
        for name in ('oracle','world','faults'):
            path=Path(__import__('crypto_reconciliation_lab.lab.'+name,fromlist=[name]).__file__)
            tree=ast.parse(path.read_text())
            imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
            self.assertFalse(any(any(bad in module for bad in ('engine','model','corrections','quarantine','demo','store')) for module in imports))


class LabTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.world=generate(11,12,2)
    def result(self,name='CLEAN',reverse=False):
        case=build_case(self.world,name);rows=list(reversed(case['rows'])) if reverse else case['rows']
        folder=self.root/str(len(list(self.root.iterdir())));folder.mkdir()
        results,audit=evaluate(config(self.world),rows,case['phases'],folder/'test.sqlite3')
        return case,results,audit

    def test_generator_original_event_definition_and_funded_world(self):
        world=generate(29,100,6);rows=wire(world)
        self.assertEqual(sum(r['record']['kind']=='event' for r in rows),100)
        self.assertEqual({e['kind'] for e in world['events']},{'deposit','withdrawal','transfer'})
        self.assertEqual({e['custody'] for e in world['events']},{'platform','external',None})
        for cut in world['cuts']:balances(world,cut)
        for r in rows:
            if r['record']['kind']=='manifest' and r['record']['stream']=='event':
                m=r['record'];self.assertEqual(m['expected_count'],sum(e['asset']==m['asset'] and e['at']<=m['coverage_to'] for e in world['events']))

    def test_bundle_bytes_repeat_and_refuse_overwrite(self):
        a=self.root/'a';b=self.root/'b'
        generate_bundle(a,(11,),12,2,('CLEAN','F1'));generate_bundle(b,(11,),12,2,('CLEAN','F1'))
        self.assertEqual({str(p.relative_to(a)):p.read_bytes() for p in a.rglob('*') if p.is_file()},{str(p.relative_to(b)):p.read_bytes() for p in b.rglob('*') if p.is_file()})
        with self.assertRaises(FileExistsError):generate_bundle(a,(11,),12,2)

    def test_hash_seed_order_does_not_change_generation(self):
        code='from crypto_reconciliation_lab.lab.world import generate,wire; from crypto_reconciliation_lab.lab.common import encoded; import sys; sys.stdout.buffer.write(encoded(wire(generate(47,12,2))))'
        outputs=[]
        for seed in ('1','2'):
            env=os.environ.copy();env['PYTHONHASHSEED']=seed
            p=subprocess.run([sys.executable,'-c',code],capture_output=True,env=env)
            self.assertEqual(p.returncode,0,p.stderr);outputs.append(p.stdout)
        self.assertEqual(*outputs)

    def test_input_contract_has_no_answer_tags(self):
        forbidden={'scenario_name','fault_type','expected_result','is_anomaly','truth','scenario'}
        for name in SCENARIOS:
            for row in build_case(self.world,name)['rows']:
                self.assertEqual(set(row),{'record','received_at'});self.assertFalse(forbidden&set(row['record']))
        self.assertEqual(set(config(self.world)),{'platform','custodian','investors','assets','opening_at'})

    def test_fault_target_precondition_failure_is_not_pass(self):
        w=copy.deepcopy(self.world);w['events']=[e for e in w['events'] if e['kind']!='withdrawal']
        with self.assertRaises(ValueError):build_case(w,'VOID_WITHDRAWAL')
        with self.assertRaises(ValueError):build_case(self.world,'UNKNOWN')

    def test_all_small_scenarios_exact_oracle(self):
        source=self.root/'inputs';generate_bundle(source,(11,),12,2)
        report=run_bundle(source,self.root/'results')
        self.assertEqual(report['status'],'PASS');self.assertEqual(len(report['cases']),23);self.assertEqual(report['evaluations'],54)
        self.assertEqual(report['negative_controls'],1);self.assertFalse(any(report['counters'].values()))

    def test_physical_order_same_finance_and_evidence(self):
        for name in ('CLEAN','IDENTITY_CONFLICT','F1','F2_STREAM_TIME'):
            with self.subTest(name=name):self.assertEqual(self.result(name)[1],self.result(name,True)[1])

    def test_new_retry_preserves_quantities_not_receipt_count(self):
        _,results,audit=self.result('EXACT_RETRY')
        self.assertEqual(results[0]['ledgers'],results[1]['ledgers'])
        self.assertNotEqual(results[0]['run_id'],results[1]['run_id'])
        self.assertEqual(audit['counts']['receipts'],audit['counts']['records']+1)

    def test_later_knowledge_and_saved_history(self):
        case=build_case(self.world,'COMBINED_LATE_EVENT_AND_CUSTODY_DIFFERENCE');p1,p2,p3=case['phases'];s=Store(self.root/'history.sqlite3',config(self.world))
        try:
            for row in case['rows']:
                if row['received_at']<=p1['knowledge_at']:s.ingest(row['record'],row['received_at'])
            first=reconcile(s,p1['balance_at'],p1['knowledge_at'])
            for row in case['rows']:
                if row['received_at']>p1['knowledge_at']:s.ingest(row['record'],row['received_at'])
            self.assertEqual(reconcile(s,p1['balance_at'],p1['knowledge_at']),first)
            second=reconcile(s,p2['balance_at'],p2['knowledge_at']);third=reconcile(s,p3['balance_at'],p3['knowledge_at'])
            self.assertTrue(score(first,p1)['passed']);self.assertTrue(score(second,p2)['passed']);self.assertTrue(score(third,p3)['passed'])
            self.assertEqual(s.read_run(first['run_id']),first);self.assertNotEqual(second['run_id'],third['run_id'])
        finally:s.close()

    def test_assets_do_not_net_opposite_custody_errors(self):
        case=build_case(self.world,'CUSTODY_SHORTFALL');phase=case['phases'][0]
        for row in case['rows']:
            r=row['record']
            if r['kind']=='report' and r['asset']=='ASSET_B' and r['stream']=='external_custody' and r['balance_at']==phase['balance_at']:
                r['amount']=decimal_text(units(r['amount'],2)+7,2)
        results,_=evaluate(config(self.world),case['rows'],case['phases'],self.root/'net.sqlite3')
        b={f['asset']:f for f in results[0]['findings'] if f['comparison']=='B'}
        self.assertEqual(b['ASSET_A']['difference'],'0.00000007');self.assertEqual(b['ASSET_B']['difference'],'-0.07')
        self.assertEqual([b[a]['reconciliation_state'] for a in sorted(b)],['MISMATCH','MISMATCH'])

    def test_labels_do_not_influence_engine(self):
        case,results,_=self.result('CLEAN');case['name']='misleading';case['is_anomaly']=True
        for p in case['phases']:p['available_ledger']={'wrong':0};p['expected_result']='CONFLICT'
        other,_=evaluate(config(self.world),case['rows'],case['phases'],self.root/'labels.sqlite3')
        self.assertEqual(results,other)

    def test_scorer_detects_changed_amount_state_and_missing_evidence(self):
        case,results,_=self.result();phase=case['phases'][-1];original=results[-1]
        for field,value,counter in [('expected','999','wrong_amount'),('reconciliation_state','MISMATCH','clean_false_mismatch')]:
            r=copy.deepcopy(original);r['findings'][0][field]=value;check=score(r,phase,True)
            self.assertFalse(check['passed']);self.assertGreater(check['counters'][counter],0)
        r=copy.deepcopy(original);r['evidence'].pop(r['findings'][0]['evidence_ids'][0]);check=score(r,phase)
        self.assertFalse(check['passed']);self.assertGreater(check['counters']['missing_evidence'],0)

    def test_scorer_distinguishes_null_from_zero_and_missing_reason(self):
        case,results,_=self.result('STALE_AND_REVISED_REPORTS');r=copy.deepcopy(results[0])
        f=next(f for f in r['findings'] if f['asset']=='ASSET_A' and f['comparison']=='B');self.assertIsNone(f['reported']);f['reported']='0';f['issues']=[]
        check=score(r,case['phases'][0]);self.assertFalse(check['passed']);self.assertGreater(check['counters']['wrong_amount'],0);self.assertGreater(check['counters']['missing_reason'],0)

    def test_bundle_tampering_is_rejected(self):
        path=self.root/'input';generate_bundle(path,(11,),12,2,('CLEAN',));(path/'seed-11/CLEAN/input.jsonl').write_text('{}\n')
        with self.assertRaises(ValueError):verify_bundle_files(path)

    def test_engine_error_keeps_reproducible_counterexample(self):
        source=self.root/'inputs';generate_bundle(source,(11,),12,2,('CLEAN',))
        with patch('crypto_reconciliation_lab.lab.runner.evaluate',side_effect=RuntimeError('injected runner failure')):
            report=run_bundle(source,self.root/'output')
        self.assertEqual(report['status'],'ERROR')
        failure=self.root/'output/counterexamples/seed-11/CLEAN'
        self.assertTrue((failure/'input/bundle.json').is_file())
        self.assertIn('injected runner failure',load(failure/'audit.json')['error'])

    def test_three_fresh_benchmark_workers_on_small_fixture(self):
        gate=self.root/'gate.json';save(gate,{})
        with patch('crypto_reconciliation_lab.lab.benchmark.correctness_gate',return_value={'build_fingerprint':'test-only'}),patch('crypto_reconciliation_lab.lab.benchmark.PROFILES',(('test_profile',12,2,'events'),)):
            result=run_benchmark(gate,self.root/'bench',Budgets(phase_seconds=10,total_seconds=40))
        self.assertEqual(result['status'],'COMPLETED')
        profile=result['profiles'][0];self.assertEqual(len(profile['trials']),3)
        self.assertEqual(len({t['command'][-1] for t in profile['trials']}),3)
        for trial in profile['trials']:
            self.assertEqual(trial['exit_code'],0);self.assertTrue(trial['worker']['oracle']['passed'])
            self.assertEqual(trial['worker']['pragmas']['synchronous'],2)
        self.assertEqual(len(profile['statistics']['ingest_jsonl_seconds']['raw']),3)
        self.assertGreater(profile['statistics']['markdown_bytes']['min'],1000)

    def test_correctness_gate_rejects_incomplete_matrix(self):
        p=self.root/'correctness.json';save(p,dict(status='CORRECTNESS_FAILED',counters={}))
        with self.assertRaises(ValueError):correctness_gate(p)
        self.assertIsNone(statistics_for([]))


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def watch(self,code,**kwargs):
        budgets=Budgets(phase_seconds=kwargs.pop('phase_seconds',2),total_seconds=kwargs.pop('total_seconds',5),poll_seconds=0.02,**kwargs)
        return supervise([sys.executable,'-c',code],self.root,self.root/'trial',self.root,budgets)
    def test_phase_timeout_really_terminates_worker(self):
        r=self.watch('import time;time.sleep(5)',phase_seconds=0.15)
        self.assertEqual(r['status'],'TIMED_OUT');self.assertNotEqual(r['exit_code'],0);self.assertLess(r['elapsed_seconds'],3)
    def test_total_timeout(self):
        r=self.watch('import time;time.sleep(5)',total_seconds=0.15)
        self.assertEqual(r['status'],'TIMED_OUT');self.assertEqual(r['reason'],'total wall-clock deadline')
    def test_disk_resource_target(self):
        r=self.watch("from pathlib import Path;import time;Path('trial/large.bin').write_bytes(b'x'*4096);time.sleep(3)",trial_bytes=1024)
        self.assertEqual(r['status'],'RESOURCE_LIMIT');self.assertGreater(r['last_observation']['trial_bytes'],1024)
    def test_rss_target_is_sampled_not_peak_only(self):
        self.assertIsNotNone(current_rss(os.getpid()))
        r=self.watch('import time;time.sleep(3)',rss_bytes=1)
        self.assertEqual(r['status'],'RESOURCE_LIMIT');self.assertGreater(r['peak_sampled_rss_bytes'],1)
    def test_aggregate_temporary_budget_is_separate(self):
        r=self.watch("from pathlib import Path;import time;Path('shared.bin').write_bytes(b'x'*4096);time.sleep(3)",temporary_bytes=1024)
        self.assertEqual(r['status'],'RESOURCE_LIMIT');self.assertEqual(r['reason'],'temporary tree budget')

    def test_exhausted_budget_does_not_launch(self):
        r=supervise(['/nonexistent-command'],self.root,self.root/'trial',self.root,Budgets(),deadline=time.monotonic()-1)
        self.assertEqual(r['status'],'NOT_ATTEMPTED_BUDGET');self.assertIsNone(r['exit_code'])
    def test_worker_error_exit_is_not_completed(self):
        r=self.watch('raise SystemExit(7)');self.assertEqual(r['status'],'ERROR');self.assertEqual(r['exit_code'],7)
    def test_correctness_failure_is_not_application_success(self):
        r=self.watch("from pathlib import Path;Path('trial/result.json').write_text('{\"status\":\"CORRECTNESS_FAILED\"}');raise SystemExit(3)")
        self.assertEqual(r['status'],'CORRECTNESS_FAILED');self.assertEqual(r['exit_code'],3)
    def test_truncated_result_does_not_hide_watchdog_timeout(self):
        r=self.watch("from pathlib import Path;import time;Path('trial/result.json').write_text('{');time.sleep(4)",phase_seconds=0.3)
        self.assertEqual(r['status'],'TIMED_OUT');self.assertIsNotNone(r['result_parse_error'])

    def test_budget_validation(self):
        for value in (0,-1,float('inf'),float('nan'),True):
            with self.assertRaises(ValueError):Budgets(phase_seconds=value)

if __name__=='__main__':unittest.main()
