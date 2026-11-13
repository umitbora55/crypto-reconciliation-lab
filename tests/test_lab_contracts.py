"""Stage 3.1 red/green regressions; expected behavior never follows the old bug."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from crypto_reconciliation_lab.lab.common import load,save,digest_bytes
from crypto_reconciliation_lab.lab.runner import generate_bundle,run_bundle,evaluate
from crypto_reconciliation_lab.lab.world import generate,config
from crypto_reconciliation_lab.lab.faults import build_case
from crypto_reconciliation_lab.lab.scoring import score
from crypto_reconciliation_lab.lab.watchdog import Budgets,supervise
from crypto_reconciliation_lab.lab.benchmark import correctness_gate,run_benchmark


def rehash(root):
    m=load(root/'bundle.json')
    for name in m['files']:
        b=(root/name).read_bytes();m['files'][name]=dict(bytes=len(b),sha256=digest_bytes(b))
    save(root/'bundle.json',m)

class ScopeRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def test_empty_full_matrix_cannot_open_benchmark_gate(self):
        src=self.root/'input';generate_bundle(src,(11,29,47),100,6)
        for p in src.glob('seed-*/*/expectations.json'):save(p,[])
        rehash(src)
        try:r=run_bundle(src,self.root/'result')
        except ValueError:return
        path=self.root/'report.json';save(path,r)
        with patch('crypto_reconciliation_lab.lab.benchmark.supervise',side_effect=AssertionError('benchmark worker launched after empty matrix')) as worker:
            with self.assertRaises(ValueError,msg='empty real matrix must not open benchmark'):run_benchmark(path,self.root/'bench')
            worker.assert_not_called()
        self.assertNotEqual(r['status'],'PASS','zero evaluated phases must be rejected')
    def test_phase_and_finding_identity_not_just_count(self):
        mutations={
          'missing_phase':lambda p:p.pop(),
          'duplicate_phase':lambda p:p.append(copy.deepcopy(p[0])),
          'same_count_impostor':lambda p:p[1].update(label='invented_phase'),
          'missing_finding':lambda p:p[0]['findings'].pop(),
          'duplicate_finding':lambda p:p[0]['findings'].append(copy.deepcopy(p[0]['findings'][0])),
          'wrong_type':lambda p:p[0]['findings'][0].update(provisional=0),
        }
        for name,mutate in mutations.items():
            with self.subTest(mutation=name):
                src=self.root/name;generate_bundle(src,(11,),12,2,('CLEAN',));f=src/'seed-11/CLEAN/expectations.json';p=load(f);mutate(p);save(f,p);rehash(src)
                with self.assertRaises(ValueError,msg=name):run_bundle(src,self.root/(name+'-result'))

class EvidenceRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        w=generate(11,12,2);self.case=build_case(w,'CLEAN');self.phase=self.case['phases'][-1]
        self.result=evaluate(config(w),self.case['rows'],self.case['phases'],self.root/'trial.sqlite3')[0][-1]
        self.assertTrue(score(self.result,self.phase,True)['passed'])
        self.assertEqual(len(self.result['evidence']),76)
    def check_bad(self,r):
        check=score(r,self.phase,True);self.assertFalse(check['passed']);self.assertGreater(check['counters']['missing_evidence']+check['counters']['structural_error'],0)
    def test_empty_payloads_with_preserved_keys_are_not_evidence(self):
        r=copy.deepcopy(self.result);r['evidence']={k:{} for k in r['evidence']};self.check_bad(r)
    def deleted(self):
        r=copy.deepcopy(self.result);eid=next(k for k,v in r['evidence'].items() if v.get('record',{}).get('kind')=='event');ids={eid,*r['evidence'][eid]['receipt_ids']}
        for k in ids:r['evidence'].pop(k)
        return r,ids
    def test_ledger_and_trace_links_cannot_dangle(self):
        r,ids=self.deleted()
        for f in r['findings']:
            for field in ('event_ids','evidence_ids'):f[field]=[x for x in f[field] if x not in ids]
            for i in f['issues']:i['evidence_ids']=[x for x in i.get('evidence_ids',[]) if x not in ids]
        self.check_bad(r)
    def test_independent_minimum_survives_coordinated_reference_deletion(self):
        r,ids=self.deleted()
        def strip(value):
            if isinstance(value,list):return [strip(x) for x in value if not (isinstance(x,str) and x in ids) and not (isinstance(x,dict) and x.get('event_id') in ids)]
            if isinstance(value,dict):return {k:strip(v) for k,v in value.items()}
            return value
        r=strip(r)
        from crypto_reconciliation_lab.lab.evidence_contract import identity
        r['run_id']=identity({k:v for k,v in r.items() if k!='run_id'})
        self.check_bad(r)
    def test_bad_payload_content_and_shape_are_controlled_failures(self):
        for mutation in ('wrong_kind','bad_hash','nonobject','bad_findings'):
            with self.subTest(mutation=mutation):
                r=copy.deepcopy(self.result);eid=next(k for k,v in r['evidence'].items() if 'record' in v)
                if mutation=='wrong_kind':r['evidence'][eid]={'unknown':{}}
                elif mutation=='bad_hash':r['evidence'][eid]['record']['source']='other'
                elif mutation=='nonobject':r['evidence'][eid]=[]
                else:r['findings']=None
                self.check_bad(r)

class OutcomeRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def watch(self,result,mode='post',limit='rss'):
        trial=self.root/str(len(list(self.root.iterdir())))
        code='from pathlib import Path;import json,time;root=Path('+repr(str(trial))+');root.joinpath("result.json").write_text('+repr(json.dumps(result))+');'
        budgets=Budgets(phase_seconds=2,total_seconds=5,rss_bytes=100_000_000,poll_seconds=.01)
        if mode=='parent':
            if limit=='phase':code+='root.joinpath("phase.json").write_text(json.dumps(dict(phase="controlled",started_monotonic=time.monotonic()-3)));'
            else:code+='root.joinpath("large").write_bytes(b"x"*4096);';budgets=Budgets(phase_seconds=2,total_seconds=5,trial_bytes=2048,poll_seconds=.01)
            code+='time.sleep(3)'
        return supervise([sys.executable,'-c',code],self.root,trial,self.root,budgets)
    def test_known_oracle_failure_survives_post_run_resource_and_time(self):
        for extra in ({'peak_rss_bytes':200_000_000},{'timings':{'oracle_check_seconds':3}}):
            with self.subTest(extra=extra):
                r=self.watch(dict(status='CORRECTNESS_FAILED',oracle={'passed':False},**extra))
                self.assertEqual(r.get('correctness'),'FAILED');self.assertEqual(r['status'],'CORRECTNESS_FAILED')
                self.assertIn(r.get('completion_state'),('RESOURCE_LIMIT','TIMED_OUT'))
    def test_parent_termination_keeps_readable_failure_and_actual_reason(self):
        for limit in ('rss','phase'):
            with self.subTest(limit=limit):
                r=self.watch(dict(status='CORRECTNESS_FAILED',oracle={'passed':False}),mode='parent',limit=limit)
                self.assertEqual(r.get('correctness'),'FAILED');self.assertNotEqual(r['exit_code'],0)
                self.assertIn(r.get('completion_state'),('RESOURCE_LIMIT','TIMED_OUT'));self.assertIsNotNone(r['reason'])
    def test_readback_failure_is_correctness_failure_even_with_completed_label(self):
        r=self.watch(dict(status='COMPLETED',oracle={'passed':True},restart_equal=False))
        self.assertEqual(r.get('correctness'),'FAILED');self.assertEqual(r['status'],'CORRECTNESS_FAILED')
    def test_failure_halts_all_later_profiles_including_smaller(self):
        gate=self.root/'gate.json';save(gate,{})
        calls=[]
        def controlled(command,cwd,trial,temp,budgets,deadline,env):
            job=load(Path(command[-1]));trial.mkdir(parents=True);calls.append((job['mode'],job['events']))
            if job['mode']=='generate':
                generate_bundle(job['bundle'],(11,),job['events'],job['investors'],('CLEAN',))
                return dict(status='COMPLETED',correctness='NOT_APPLICABLE',completion_state='COMPLETED',worker={'timings':{'generation_seconds':0}},exit_code=0)
            return dict(status='RESOURCE_LIMIT',correctness='FAILED',completion_state='RESOURCE_LIMIT',worker={'status':'CORRECTNESS_FAILED','oracle':{'passed':False}},exit_code=0,reason='controlled post-run RSS')
        with patch('crypto_reconciliation_lab.lab.benchmark.correctness_gate',return_value={'build_fingerprint':'protocol-fixture'}),patch('crypto_reconciliation_lab.lab.benchmark.PROFILES',(('first',24,3,'events'),('smaller',12,2,'investors'))),patch('crypto_reconciliation_lab.lab.benchmark.supervise',side_effect=controlled):
            r=run_benchmark(gate,self.root/'bench')
        self.assertEqual(calls,[('generate',24),('trial',24)])
        self.assertEqual(r.get('correctness'),'FAILED');self.assertEqual(r['status'],'CORRECTNESS_FAILED')
        self.assertTrue(r['profiles'][1]['status'].startswith('NOT_ATTEMPTED'))
        self.assertIsNone(r['profiles'][0].get('statistics'))

if __name__=='__main__':unittest.main()
