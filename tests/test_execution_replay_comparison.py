"""Actual calculation distinguishes rehashed lies from reproducible outcomes."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from replay_fixtures import (all_rows,assert_reproduced,encoded,export_pair,hashed,
    literal_finances,rebound,verify)


class ExecutionReplayComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.original=export_pair(self.root/'original')

    def semantic(self,name,change,path):
        from crypto_reconciliation_lab.replay.validation import validate_inputs
        altered=rebound(self.original,self.root/name,mutate_run=change)
        self.assertEqual(altered['context']['tables'],self.original['context']['tables'])
        self.assertNotEqual(altered['expected'],self.original['expected'])
        # This gate must succeed, proving the negative tests exercise financial
        # calculation/comparison rather than an accidental malformed identity.
        validated=validate_inputs(altered['context_path'].read_bytes(),altered['run_path'].read_bytes(),altered['expected'])
        self.assertEqual(validated.input_data['receipts'],self.original['context']['tables']['receipts'])
        result=verify(altered)
        self.assert_diverged(result,path)
        return altered,result

    def assert_diverged(self,result,path):
        self.assertEqual((result['status'],result['exit_code'],result['reason_code']),('DIVERGED',1,'REPLAY_DIVERGED'),result)
        self.assertEqual(result['replay_state'],'DIVERGED')
        self.assertEqual(result['completion'],{'validation':'COMPLETED','calculation':'COMPLETED','comparison':'COMPLETED'})
        self.assertEqual(result['comparison']['state'],'DIFFERENT')
        self.assertFalse(result['comparison']['equal'])
        self.assertIn(path,[d['path'] for d in result['comparison']['differences']])

    def test_rehashed_wrong_numeric_result_reaches_real_engine_and_diverges(self):
        self.semantic('numeric',lambda r:r['ledgers']['ASSET_A'].update(liability='12'),'/ledgers/ASSET_A/liability')

    def test_trace_only_wrong_detail_reaches_real_engine_and_diverges(self):
        self.semantic('trace',lambda r:r['ledgers']['ASSET_A']['trace'][0]['balances_after'].update(I1='6'),'/ledgers/ASSET_A/trace/0/balances_after/I1')

    def test_finding_only_wrong_detail_and_provisional_flag_are_compared(self):
        self.semantic('finding',lambda r:r['findings'][0].update(provisional=True,difference='1'),'/findings/0/provisional')

    def test_engine_is_called_exactly_once_with_input_only_adapter(self):
        from crypto_reconciliation_lab import engine
        from crypto_reconciliation_lab.replay.validation import validate_inputs
        from crypto_reconciliation_lab.replay.adapter import compute
        v=validate_inputs(self.original['context_path'].read_bytes(),self.original['run_path'].read_bytes(),self.original['expected'])
        self.assertEqual(set(v.input_data),{'configuration','records','receipts','balance_at','knowledge_at'})
        with patch.object(engine,'reconcile',wraps=engine.reconcile) as invoked:
            actual=compute(**v.input_data)
        self.assertEqual(invoked.call_count,1)
        adapter=invoked.call_args.args[0]
        for forbidden in ('findings','evidence','ledgers','saved_payload','selected_evidence'):
            self.assertFalse(hasattr(adapter,forbidden))
        self.assertEqual(actual['run_id'],self.original['context']['run_id'])
        self.assertEqual({k:v for k,v in actual.items() if k!='run_id'},self.original['run'])

    def test_honestly_changed_inputs_and_new_output_and_new_pin_reproduce(self):
        rows=all_rows()
        next(r['record'] for r in rows if r['record'].get('ref')=='A-deposit')['amount']='3'
        for row in rows:
            r=row['record']
            if r['kind']=='report' and r['asset']=='ASSET_A':
                if r['scope']=='I1':r['amount']='8'
                if r['scope']=='external':r['amount']='10'
        changed=export_pair(self.root/'honest-changed',rows=rows)
        literal_finances(self,changed,'8','4','12','10')
        self.assertNotEqual(changed['expected'],self.original['expected'])
        assert_reproduced(self,verify(changed))
        # Equality is not a claim that these inputs came from the first DB.
        self.assertNotEqual(changed['context']['tables'],self.original['context']['tables'])

    def test_full_typed_comparison_cannot_erase_bool_integer_difference(self):
        from crypto_reconciliation_lab.replay.comparison import compare_payloads
        result=compare_payloads({'a':True,'b':1,'c':None},{'a':1,'b':'1','c':False})
        self.assertEqual(result['state'],'DIFFERENT')
        self.assertEqual(result['total_differences'],3)
        self.assertEqual([d['path'] for d in result['differences']],['/a','/b','/c'])
        self.assertEqual([(d['saved_type'],d['recomputed_type']) for d in result['differences']],
                         [('boolean','integer'),('integer','string'),('null','boolean')])

    def test_json_pointer_escaping_array_order_and_missing_values(self):
        from crypto_reconciliation_lab.replay.comparison import compare_payloads
        result=compare_payloads({'a/b':{'~key':[1,2]},'missing':None},{'a/b':{'~key':[2,1]},'extra':None})
        self.assertEqual(result['total_differences'],4)
        self.assertEqual([d['path'] for d in result['differences']],['/a~1b/~0key/0','/a~1b/~0key/1','/extra','/missing'])
        self.assertNotEqual(result['differences'][2]['saved_type'],result['differences'][2]['recomputed_type'])

    def test_diagnostic_truncation_preserves_complete_difference_count(self):
        from crypto_reconciliation_lab.replay.comparison import compare_payloads
        result=compare_payloads({'items':['a'*500]*150},{'items':['b'*500]*150})
        self.assertFalse(result['equal']);self.assertEqual(result['total_differences'],150)
        self.assertEqual(result['reported_differences'],100)
        self.assertEqual(len(result['differences']),100);self.assertTrue(result['truncated'])
        self.assertTrue(all(len(d['saved_preview'])<=256 and len(d['recomputed_preview'])<=256 for d in result['differences']))

    def test_runtime_claims_do_not_invent_historical_executable_or_signature_proof(self):
        result=verify(self.original);assert_reproduced(self,result)
        text=encoded(result).decode()
        for claim in ('NOT_RECORDED','NOT_PERFORMED','NOT_DEFINED'):
            self.assertIn(claim,text)
        self.assertIn('stage2-v2',text)
        self.assertIn('sqlite',text.lower());self.assertIn('python',text.lower())

    def test_test_only_answer_fed_mutant_is_killed_by_same_semantic_assertion(self):
        from crypto_reconciliation_lab.replay import worker
        altered=rebound(self.original,self.root/'answer-fed',mutate_run=lambda r:r['ledgers']['ASSET_A'].update(liability='12'))
        args=(altered['context_path'].read_bytes(),altered['run_path'].read_bytes(),altered['expected'])
        self.assert_diverged(worker.verify_bytes(*args),'/ledgers/ASSET_A/liability')
        supplied={'run_id':altered['context']['run_id'],**copy.deepcopy(altered['run'])}
        # Deliberately defective TEST-ONLY mutant feeds the saved answer into
        # the computation boundary. It is not a historical product defect.
        with patch.object(worker,'compute',return_value=supplied):
            wrong=worker.verify_bytes(*args)
        self.assertEqual(wrong['status'],'REPRODUCED')
        with self.assertRaises(AssertionError):self.assert_diverged(wrong,'/ledgers/ASSET_A/liability')

    def test_test_only_hash_only_comparison_mutant_is_killed(self):
        from crypto_reconciliation_lab.replay import worker
        altered=rebound(self.original,self.root/'hash-only',mutate_run=lambda r:r['ledgers']['ASSET_A']['trace'][0]['balances_after'].update(I1='6'))
        args=(altered['context_path'].read_bytes(),altered['run_path'].read_bytes(),altered['expected'])
        self.assert_diverged(worker.verify_bytes(*args),'/ledgers/ASSET_A/trace/0/balances_after/I1')
        fake={'state':'EQUAL','equal':True,'total_differences':0,'reported_differences':0,'truncated':False,'differences':[]}
        # A hash-binding-only comparer ignores the recomputed payload. The
        # existing canonical-ID cross-check also catches this defective mutant.
        with patch.object(worker,'compare_payloads',return_value=fake):wrong=worker.verify_bytes(*args)
        with self.assertRaises(AssertionError):self.assert_diverged(wrong,'/ledgers/ASSET_A/trace/0/balances_after/I1')
