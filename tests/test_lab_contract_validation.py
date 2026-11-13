"""Contract edge cases, real matrix gate, and deterministic failure propagation."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from crypto_reconciliation_lab.lab.common import load,save,build_fingerprint
from crypto_reconciliation_lab.lab.runner import generate_bundle,run_bundle,evaluate
from crypto_reconciliation_lab.lab.world import generate,config
from crypto_reconciliation_lab.lab.faults import build_case
from crypto_reconciliation_lab.lab.scoring import score
from crypto_reconciliation_lab.lab.evidence_contract import identity
from crypto_reconciliation_lab.lab.watchdog import Budgets,supervise
from crypto_reconciliation_lab.lab.benchmark import correctness_gate,statistics_for
from test_lab_contracts import rehash

class GateValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup);cls.root=Path(cls.tmp.name)
        generate_bundle(cls.root/'input',(11,29,47),100,6)
        cls.report=run_bundle(cls.root/'input',cls.root/'output')
        if cls.report['status']!='PASS':raise AssertionError('valid full matrix failed: '+str(cls.report['counters']))
    def test_real_full_gate_and_counter_scope_integrity(self):
        p=self.root/'gate.json';save(p,self.report);self.assertEqual(correctness_gate(p)['evaluations'],162)
        mutations={
          'wrong_generator_version':lambda r:r.update(generator_version=[]),
          'wrong_fault_version':lambda r:r.update(fault_plan_version='unknown'),
          'same_count_case_substitution':lambda r:r['cases'].__setitem__(-1,copy.deepcopy(r['cases'][0])),
          'legacy_version':lambda r:r.pop('experiment_contract_version'),
          'wrong_fingerprint':lambda r:r.update(build_fingerprint='old'),
          'duplicate_seed':lambda r:r['seeds'].append(r['seeds'][0]),
          'missing_case':lambda r:r['cases'].pop(),
          'duplicate_case':lambda r:r['cases'].append(copy.deepcopy(r['cases'][0])),
          'missing_phase':lambda r:r['cases'][0]['phases'].pop(),
          'duplicate_phase':lambda r:r['cases'][0]['phases'].append(copy.deepcopy(r['cases'][0]['phases'][0])),
          'wrong_cut':lambda r:r['cases'][0]['phases'][0].update(balance_at='2026-01-01T00:00:00Z'),
          'duplicate_finding':lambda r:r['cases'][0]['phases'][0]['rows'].append(copy.deepcopy(r['cases'][0]['phases'][0]['rows'][0])),
          'missing_counters':lambda r:r.pop('counters'),
          'bool_counter':lambda r:r['counters'].update(wrong_amount=False),
          'negative_counter':lambda r:r['counters'].update(wrong_amount=-1),
          'missing_phase_counters':lambda r:r['cases'][0]['phases'][0].pop('counters'),
          'counter_total':lambda r:r['cases'][0]['phases'][0]['counters'].update(wrong_amount=1),
          'wrong_evaluations':lambda r:r.update(evaluations=0),
          'no_evidence_check':lambda r:r['cases'][0]['phases'][0].update(evidence_verified=False),
          'false_phase_pass':lambda r:r['cases'][0]['phases'][0].update(passed=False),
          'different_actual_amount':lambda r:r['cases'][0]['phases'][0]['rows'][0]['actual'].update(expected='999'),
        }
        for name,mutate in mutations.items():
            with self.subTest(mutation=name):
                r=copy.deepcopy(self.report);mutate(r);save(p,r)
                with self.assertRaises(ValueError):correctness_gate(p)
    def test_partial_case_succeeds_but_never_opens_full_gate(self):
        r=run_bundle(self.root/'input',self.root/'partial','seed-11/CLEAN')
        self.assertEqual(r['status'],'PASS');self.assertEqual(r['evaluations'],2);self.assertEqual(r['scope'],'PARTIAL')
        with self.assertRaises(ValueError):correctness_gate(self.root/'partial/correctness.json')

class BundleValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def test_config_plan_seed_and_inventory_are_not_advisory(self):
        mutations={
          'plan_seed':('fault_plan.json',lambda x:x.update(seed=29)),
          'plan_name':('fault_plan.json',lambda x:x.update(name='LATE_EVENT')),
          'asset_scale':('config.json',lambda x:x['assets'].update(ASSET_A=2)),
          'roster':('config.json',lambda x:x['investors'].append('I999')),
          'missing_inventory':('expectations.json',lambda x:x[0].pop('evidence_minimum')),
          'altered_inventory':('expectations.json',lambda x:x[0]['evidence_minimum']['source_records'].clear()),
          'missing_amount':('expectations.json',lambda x:x[0]['findings'][0].pop('reported')),
        }
        for name,(file,mutate) in mutations.items():
            with self.subTest(mutation=name):
                root=self.root/name;generate_bundle(root,(11,),12,2,('CLEAN',));p=root/'seed-11/CLEAN'/file;v=load(p);mutate(v);save(p,v);rehash(root)
                out=self.root/(name+'-out')
                with self.assertRaises(ValueError):run_bundle(root,out)
                self.assertEqual(load(out/'contract-error.json')['status'],'ERROR')
    def test_invalid_experiment_cli_retains_located_diagnostic(self):
        root=self.root/'input';generate_bundle(root,(11,),12,2,('CLEAN',));save(root/'seed-11/CLEAN/expectations.json',[]);rehash(root)
        out=self.root/'out';p=subprocess.run([sys.executable,*(['-I'] if sys.flags.isolated else []),'-m','crypto_reconciliation_lab','lab-verify','--input',str(root),'--output',str(out)],capture_output=True,text=True)
        self.assertEqual(p.returncode,2);self.assertIn('seed-11/CLEAN/expectations.json',p.stderr)
        self.assertIn('reproduce',load(out/'contract-error.json'))
    def test_single_scenario_valid_and_old_bundle_not_relabelled(self):
        root=self.root/'input';generate_bundle(root,(11,),12,2,('CLEAN',));r=run_bundle(root,self.root/'valid')
        self.assertEqual((r['status'],r['scope']),('PASS','PARTIAL'))
        manifest=load(root/'bundle.json');manifest.pop('experiment_contract_version');save(root/'bundle.json',manifest)
        with self.assertRaisesRegex(ValueError,'regenerate old 0.3.0'):run_bundle(root,self.root/'old-format')

class PayloadLinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def result(self,name):
        w=generate(11,12,2);c=build_case(w,name);rs=evaluate(config(w),c['rows'],c['phases'],self.root/(name+'.sqlite3'))[0]
        for r,p in zip(rs,c['phases']):self.assertTrue(score(r,p)['passed'],score(r,p)['errors'])
        return c,rs
    def test_quarantine_receipt_content_and_type_are_checked(self):
        c,rs=self.result('F3_LIST');r=copy.deepcopy(rs[0]);eid=next(k for k,v in r['evidence'].items() if 'quarantined_receipt' in v)
        r['evidence'][eid]['quarantined_receipt']['record']['ref']='changed'
        checked=score(r,c['phases'][0]);self.assertFalse(checked['passed']);self.assertGreater(checked['counters']['missing_evidence'],0)
    def test_derived_effect_rehash_does_not_make_wrong_content_valid(self):
        for name in ('VOID_DEPOSIT','REPLACE_WITHDRAWAL'):
            with self.subTest(scenario=name):
                c,rs=self.result(name);r=copy.deepcopy(rs[-1]);old=next(k for k,v in r['evidence'].items() if 'derived_correction_group' in v)
                group=r['evidence'][old]['derived_correction_group'];group['effects'][0]['custody_delta']='999';new=identity({k:v for k,v in group.items() if k!='id'})
                def replace(value):
                    if isinstance(value,str):return new if value==old else value
                    if isinstance(value,list):return [replace(v) for v in value]
                    if isinstance(value,dict):return {new if k==old else k:replace(v) for k,v in value.items()}
                    return value
                r=replace(r);check=score(r,c['phases'][-1]);self.assertFalse(check['passed']);self.assertGreater(check['counters']['missing_evidence'],0)
    def test_link_mutations_cover_receipts_manifests_groups_and_trace(self):
        c,rs=self.result('REPLACE_DEPOSIT');original=rs[-1];p=c['phases'][-1]
        def event(r):return next(v for v in r['evidence'].values() if v.get('record',{}).get('kind')=='event')
        mutations={
          'bool_delivery_count':lambda r:r['ledgers']['ASSET_A']['correction_deliveries'][0].update(expected_count=True),
          'bool_trace_sequence':lambda r:r['ledgers']['ASSET_A']['trace'][0].update(sequence=True),
          'wrong_finding_rule':lambda r:r['findings'][0].update(rule_version='unknown'),
          'wrong_logical_key':lambda r:event(r).update(logical_key='[]'),
          'receipt_points_to_source':lambda r:event(r).update(receipt_ids=[next(iter(p['evidence_minimum']['source_records']))]),
          'missing_delivery_manifest':lambda r:r['ledgers']['ASSET_A']['correction_deliveries'][0].update(manifest_ids=[]),
          'missing_applied_link':lambda r:r['ledgers']['ASSET_A']['correction_deliveries'][0].update(applied_correction_ids=[]),
          'trace_wrong_event':lambda r:r['ledgers']['ASSET_A']['trace'][0].update(event_id='missing'),
          'trace_wrong_group':lambda r:r['ledgers']['ASSET_A']['trace'][0].update(correction_group_id='missing'),
        }
        for name,mutate in mutations.items():
            with self.subTest(mutation=name):
                r=copy.deepcopy(original);mutate(r);check=score(r,p);self.assertFalse(check['passed']);self.assertGreater(check['counters']['missing_evidence'],0)
    def test_unselected_old_and_future_receipts_are_not_minimum(self):
        c,rs=self.result('STALE_AND_REVISED_REPORTS')
        final=c['phases'][-1]['evidence_minimum'];k1=c['phases'][0]['evidence_minimum']
        self.assertTrue(all(row['received_at']<=c['phases'][0]['knowledge_at'] for row in k1['receipts'].values()))
        self.assertFalse(any(row['record'].get('version')==1 and row['record'].get('stream')=='external_custody' and row['record'].get('asset')=='ASSET_A' for row in final['receipts'].values()))

class ProtocolValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def test_pure_timeout_and_resource_without_oracle_are_unknown(self):
        for resource in (False,True):
            with self.subTest(resource=resource):
                trial=self.root/str(resource);code='import time;time.sleep(3)'
                b=Budgets(phase_seconds=.15,total_seconds=2,poll_seconds=.01,rss_bytes=1 if resource else 1024**3)
                r=supervise([sys.executable,'-c',code],self.root,trial,self.root,b)
                self.assertEqual(r['correctness'],'UNKNOWN');self.assertEqual(r['completion_state'],'RESOURCE_LIMIT' if resource else 'TIMED_OUT')
    def test_generation_is_not_an_oracle_trial_and_unverified_statistics_fail(self):
        trial=self.root/'gen';code='from pathlib import Path;Path('+repr(str(trial/'result.json'))+').write_text('+repr(json.dumps(dict(status='COMPLETED',worker_role='generate')))+')'
        r=supervise([sys.executable,'-c',code],self.root,trial,self.root,Budgets(phase_seconds=2,total_seconds=3))
        self.assertEqual(r['correctness'],'NOT_APPLICABLE');self.assertEqual(r['completion_state'],'COMPLETED')
        unverified=dict(status='COMPLETED',completion_state='COMPLETED',correctness='PASSED',worker={'oracle':{'passed':True},'restart_equal':False})
        self.assertIsNone(statistics_for([unverified]*3))
    def test_seen_failure_survives_later_truncated_result(self):
        trial=self.root/'trial';ready=self.root/'observed'
        code='from pathlib import Path;import json,time;root=Path('+repr(str(trial))+');root.joinpath("result.json").write_text(json.dumps(dict(status="CORRECTNESS_FAILED",oracle=dict(passed=False))));'
        code+='\nwhile not Path('+repr(str(ready))+').exists(): time.sleep(.005)\n'
        code+='root.joinpath("result.json").write_text("{");root.joinpath("phase.json").write_text(json.dumps(dict(phase="done",started_monotonic=time.monotonic()-5)));time.sleep(3)'
        def rss(pid):
            p=trial/'result.json'
            if p.exists():
                try:
                    if json.loads(p.read_text()).get('status')=='CORRECTNESS_FAILED':ready.write_text('parent sampled readable failure')
                except json.JSONDecodeError:pass
            return 1024
        with patch('crypto_reconciliation_lab.lab.watchdog.current_rss',side_effect=rss):r=supervise([sys.executable,'-c',code],self.root,trial,self.root,Budgets(phase_seconds=2,total_seconds=3,poll_seconds=.01))
        self.assertEqual(r['correctness'],'FAILED');self.assertEqual(r['completion_state'],'TIMED_OUT');self.assertIsNotNone(r['observed_correctness_failure']);self.assertIsNotNone(r['result_parse_error'])

if __name__=='__main__':unittest.main()
