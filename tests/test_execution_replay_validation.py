"""Fail-closed identities, real row relations and finite input work."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from replay_fixtures import (assert_error,encoded,export_pair,hashed,rebound,verify,write_historical)
from replay_historical_fixtures import historical_0101


class ExecutionReplayValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.pair=export_pair(self.root/'original')

    def test_expected_execution_id_is_mandatory_exact_external_selector(self):
        from crypto_reconciliation_lab.replay import verify_execution_replay
        for value in (None,'',True,1,'a'*63,'G'*64,'A'*64,'0'*65):
            with self.subTest(value=value):
                result=verify_execution_replay(self.pair['context_path'],self.pair['run_path'],value)
                assert_error(self,result,'REPLAY_INPUT')
        wrong=dict(self.pair,expected='0'*64)
        assert_error(self,verify(wrong),'REPLAY_INTEGRITY')

    def test_cross_pair_and_one_byte_change_fail_before_computation(self):
        other=export_pair(self.root/'other',request_id='different-request')
        cross=dict(self.pair,context_path=other['context_path'])
        result=verify(cross);assert_error(self,result,'REPLAY_INTEGRITY')
        self.assertEqual(result['completion']['calculation'],'NOT_COMPLETED')
        self.pair['run_path'].write_bytes(self.pair['run_path'].read_bytes()+b' ')
        assert_error(self,verify(self.pair),'REPLAY_INTEGRITY')

    def test_all_local_rehashing_does_not_match_old_external_pin(self):
        altered=rebound(self.pair,self.root/'changed',mutate_context=lambda c:c.update(request_id='new-local-request'))
        self.assertNotEqual(altered['expected'],self.pair['expected'])
        altered['expected']=self.pair['expected']
        assert_error(self,verify(altered),'REPLAY_INTEGRITY')

    def test_context_canonical_bytes_and_raw_run_hash_are_independently_checked(self):
        pretty=json.dumps(self.pair['context'],indent=2).encode()
        self.pair['context_path'].write_bytes(pretty)
        # Even a caller-selected binding to noncanonical context bytes cannot
        # turn a noncanonical recorded context into a supported capture.
        c=self.pair['context'];binding={'format':'recorded-execution-v1',**{k:c[k] for k in ('request_id','request_fingerprint','run_id','run_payload_sha256')},'context_hash':hashed(pretty)}
        self.pair['expected']=hashed(encoded(binding))
        assert_error(self,verify(self.pair),'REPLAY_INTEGRITY')

    def test_missing_dangling_and_duplicate_physical_relations_are_rejected(self):
        changes={
            'missing-table':lambda c:c['tables'].pop('records'),
            'missing-row':lambda c:c['tables']['receipts'].pop(),
            'duplicate-pk':lambda c:c['tables']['receipts'].append(copy.deepcopy(c['tables']['receipts'][0])),
            'dangling-record':lambda c:c['tables']['receipts'][0].update(record_id='f'*64),
            'wrong-count':lambda c:c['counts'].update(receipts=29),
            'wrong-selected-id':lambda c:next(iter(c['selected_evidence'].values()))['receipt_ids'].append(9999),
            'wrong-raw':lambda c:c['tables']['receipts'][0].update(raw='{}'),
            'wrong-payload':lambda c:c['tables']['records'][0].update(payload='{}'),
            'unknown-column':lambda c:c['tables']['receipts'][0].update(extra=1),
        }
        for name,change in changes.items():
            with self.subTest(name=name):
                altered=rebound(self.pair,self.root/name,mutate_context=change)
                result=verify(altered);assert_error(self,result,'REPLAY_INTEGRITY')
                self.assertEqual(result['completion']['calculation'],'NOT_COMPLETED')

    def test_future_receipt_cannot_be_promoted_into_claimed_knowledge_inventory(self):
        altered=rebound(self.pair,self.root/'future',mutate_context=lambda c:c['tables']['receipts'][0].update(received_at='2027-01-01T00:00:00.000000Z'))
        assert_error(self,verify(altered),'REPLAY_INTEGRITY')

    def test_bool_float_and_out_of_range_sql_identities_are_rejected(self):
        for index,value in enumerate((True,1.0,-1,0,2**63,-2**63-1,'1',None)):
            with self.subTest(value=value):
                altered=rebound(self.pair,self.root/str(index),mutate_context=lambda c,v=value:c['tables']['receipts'][0].update(id=v))
                assert_error(self,verify(altered),'REPLAY_INTEGRITY')

    def test_closed_schema_rule_profile_and_format(self):
        def unsupported_profile(context):
            context['request']['profile']='selected-evidence-only'
            context['scope']['profile']='selected-evidence-only'
        changes=(lambda c:c.update(schema_version=7),lambda c:c.update(format='recorded-execution-v9'),
                 lambda c:c['request'].update(rule_version='unknown-rule'),unsupported_profile)
        for i,change in enumerate(changes):
            with self.subTest(i=i):
                altered=rebound(self.pair,self.root/str(i),mutate_context=change)
                assert_error(self,verify(altered),'REPLAY_UNSUPPORTED')

    def test_claim_count_and_boolean_types_are_exact(self):
        changes=(lambda c:c.update(schema_version=True),lambda c:c['counts'].update(receipts=True),
                 lambda c:c['scope'].update(complete=1),lambda c:c.update(acceptance_epochs=[True]),
                 lambda c:c['claims'].update(source_signature_verification='VERIFIED'))
        for i,change in enumerate(changes):
            with self.subTest(i=i):
                altered=rebound(self.pair,self.root/str(i),mutate_context=change)
                assert_error(self,verify(altered),'REPLAY_UNSUPPORTED' if i==0 else 'REPLAY_INTEGRITY')

    def test_protected_original_links_and_policy_head_are_required(self):
        original=write_historical(self.root/'protected',historical_0101()['after-current-replay'])
        changes=(lambda c:c['tables']['auth_delivery_links'].pop(),
                 lambda c:c['tables']['auth_keys'].pop(),
                 lambda c:c.update(observed_policy_head=c['tables']['auth_policy_activations'][0]),
                 lambda c:c['tables']['auth_attempt_links'][0].update(decision_id=999999),
                 lambda c:c.update(acceptance_epochs=[1,2]))
        for i,change in enumerate(changes):
            with self.subTest(i=i):
                altered=rebound(original,self.root/str(i),mutate_context=change)
                assert_error(self,verify(altered),'REPLAY_INTEGRITY')

    def test_duplicate_keys_nonfinite_and_malformed_json_are_controlled(self):
        for name,raw in (('duplicate',b'{"format":1,"format":2}'),('nonfinite',b'{"x":NaN}'),
                         ('infinite',b'{"x":1e9999}'),('broken',b'{')):
            with self.subTest(name=name):
                self.pair['context_path'].write_bytes(raw)
                assert_error(self,verify(self.pair),'REPLAY_INTEGRITY')

    def test_explicit_json_depth_and_authoritative_byte_limits(self):
        self.pair['context_path'].write_bytes(b'['*1025+b'0'+b']'*1025)
        assert_error(self,verify(self.pair),'REPLAY_LIMIT')
        self.pair['context_path'].write_bytes(b' '*(16*1024*1024+1))
        assert_error(self,verify(self.pair),'REPLAY_LIMIT')

    def test_oversized_sql_value_is_rejected_even_with_coherent_binding(self):
        altered=rebound(self.pair,self.root/'huge-value',mutate_context=lambda c:c['tables']['receipts'][0].update(raw=' '*(4*1024*1024+1)))
        assert_error(self,verify(altered),'REPLAY_LIMIT')

    def test_roster_cartesian_cardinality_checked_against_actual_findings(self):
        # A modest byte payload must not expand a million-element expected set
        # before noticing that it contains only the original six findings.
        altered=rebound(self.pair,self.root/'cartesian',mutate_run=lambda r:r['configuration'].update(
            investors=['I'+str(i) for i in range(1000)],assets={'A'+str(i):2 for i in range(1000)}))
        assert_error(self,verify(altered),'REPLAY_INTEGRITY')

    def test_duplicate_saved_receipt_hash_references_fail_before_scope_expansion(self):
        from crypto_reconciliation_lab.execution import capture
        from crypto_reconciliation_lab.replay.validation import validate_inputs
        from crypto_reconciliation_lab.replay.common import ReplayError
        def duplicate(run):
            entry=next(e for e in run['evidence'].values() if 'record' in e)
            entry['receipt_ids']*=100
        altered=rebound(self.pair,self.root/'repeated-hashes',mutate_run=duplicate)
        with patch.object(capture,'evidence_mapping',side_effect=AssertionError('expanded invalid scope')) as mapping:
            with self.assertRaises(ReplayError) as error:
                validate_inputs(altered['context_path'].read_bytes(),altered['run_path'].read_bytes(),altered['expected'])
        self.assertEqual(error.exception.reason_code,'REPLAY_INTEGRITY')
        self.assertEqual(mapping.call_count,0)

    def test_no_follow_regular_inputs_and_no_fallback_files(self):
        from crypto_reconciliation_lab.replay import verify_execution_replay
        missing=self.root/'missing.json';directory=self.root/'dir';directory.mkdir()
        linked=self.root/'link.json';linked.symlink_to(self.pair['context_path'])
        for path in (missing,directory,linked):
            with self.subTest(path=path):
                result=verify_execution_replay(path,self.pair['run_path'],self.pair['expected'])
                assert_error(self,result,'REPLAY_INPUT')
        # Adjacent helpful metadata is neither an input nor a missing-file fallback.
        (missing.parent/'execution.json').write_text(json.dumps(self.pair['context']))
        assert_error(self,verify_execution_replay(missing,self.pair['run_path'],self.pair['expected']),'REPLAY_INPUT')
