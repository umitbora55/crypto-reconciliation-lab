"""Gate2 LAB identity-reference contract checks, separate from historical tests."""
import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from validation_lab import identity_reference as i


class IdentityReferenceResearchTests(unittest.TestCase):
    def setUp(self):
        self.events=[{'event_id':'9007199254740993','content':b'{"amount":"1"}'},
                     {'event_id':'9007199254740994','content':b'{"amount":"2"}'}]
        self.scope={'publisher':'LAB','dataset':'D','partition':'P','event_day':'2026-01-05',
                    'balance_cut':'2026-01-05T23:59:59.000000Z','record_kind':'event'}
        self.manifest=i.make_manifest(self.events,self.scope)
        self.context=i.context_for(self.manifest)
        self.envelope=i.sign_manifest(self.manifest)

    def test_separate_lab_context_detects_identity_content_and_order(self):
        self.assertEqual(i.verify_reference(self.envelope,self.events,self.context)['outcome'],'MATCH')
        for change in ('identity','content','order'):
            events=copy.deepcopy(self.events)
            if change=='identity':events[0]['event_id']='9007199254740992'
            if change=='content':events[0]['content']=b'{"amount":"3"}'
            if change=='order':events.reverse()
            with self.subTest(change=change):
                self.assertEqual(i.verify_reference(self.envelope,events,self.context)['outcome'],'REFERENCE_MISMATCH')

    def test_valid_signature_does_not_make_self_issued_pin_trusted(self):
        with self.assertRaises(i.ReferenceError):
            i.verify_reference(self.envelope,self.events,replace(self.context,origin='SELF_ISSUED_FROM_CANDIDATE'))

    def test_revocation_and_rotation_are_current_context_constraints(self):
        with self.assertRaises(i.ReferenceError):
            i.verify_reference(self.envelope,self.events,replace(self.context,revoked_key_ids=('LAB-KEY-1',)))
        newer=i.make_manifest(self.events,self.scope,'2',self.context.manifest_sha256,'2')
        context=i.context_for(newer,2,'LAB-KEY-2')
        self.assertEqual(i.verify_reference(i.sign_manifest(newer,2,'LAB-KEY-2'),self.events,context)['outcome'],'MATCH')
        with self.assertRaises(i.ReferenceError):
            i.verify_reference(i.sign_manifest(newer,1,'LAB-KEY-1'),self.events,context)

    def test_same_revision_conflict_and_stale_replay_reject(self):
        changed=copy.deepcopy(self.manifest);changed['entries'][0]['content_sha256']='0'*64
        with self.assertRaises(i.ReferenceError):i.verify_reference(i.sign_manifest(changed),self.events,self.context)
        newer=i.make_manifest(self.events,self.scope,'2',self.context.manifest_sha256)
        with self.assertRaises(i.ReferenceError):i.verify_reference(self.envelope,self.events,i.context_for(newer))

    def test_empty_duplicate_and_multiple_signature_inventories_refuse(self):
        empty=i.make_manifest([],self.scope)
        with self.assertRaises(i.ReferenceError):i.verify_reference(i.sign_manifest(empty),[],i.context_for(empty))
        duplicate=self.events+[self.events[0]]
        with self.assertRaises(i.ReferenceError):i.verify_reference(self.envelope,duplicate,self.context)
        obj=json.loads(self.envelope);obj['signatures']*=2
        with self.assertRaises(i.ReferenceError):i.verify_reference(i.canonical(obj),self.events,self.context)

    def test_extra_unknown_fields_and_duplicate_json_keys_refuse(self):
        obj=json.loads(self.envelope);obj['trusted']=True
        with self.assertRaises(i.ReferenceError):i.verify_reference(i.canonical(obj),self.events,self.context)
        with self.assertRaises(i.ReferenceError):i.strict_reference_json(b'{"a":1,"a":2}')

    def test_empty_scope_cannot_become_authoritative_by_matching_itself(self):
        manifest=i.make_manifest(self.events,{})
        with self.assertRaises(i.ReferenceError):
            i.verify_reference(i.sign_manifest(manifest),self.events,i.context_for(manifest))

    def test_production_fuzz_literal_boundary_oracles(self):
        cases=list(i.production_fuzz_cases(11))
        self.assertEqual(len(cases),34)
        self.assertEqual(len({c['name'] for c in cases}),34)
        for case in cases:
            with self.subTest(case=case['name']):
                result=i.run_production_fuzz(case)
                self.assertEqual(result['outcome'],case['expected'])
                if case['expected']=='ACCEPT':
                    self.assertTrue(result['value_equal'])
                    self.assertEqual(result['value_check'],'CHECKED')
                else:
                    self.assertIsNone(result['value_equal'])
                    self.assertEqual(result['value_check'],'NOT_APPLICABLE_REJECTED')

    def test_boundary_accept_values_do_not_use_target_as_oracle(self):
        cases={case['name']:case for case in i.production_fuzz_cases(11)}
        for name in ('depth_32','nodes_20000','bytes_65536','correction_original_event'):
            target='crypto_reconciliation_lab.correction_model.normalize_correction' if name=='correction_original_event' else 'crypto_reconciliation_lab.source_auth.crypto.strict_json'
            with self.subTest(case=name), patch(target,return_value={'not_the_parsed_value':True}):
                result=i.run_production_fuzz(cases[name])
                self.assertEqual(result['outcome'],'ACCEPT')
                self.assertFalse(result['value_equal'])

    def test_evidence_writer_never_overwrites_prior_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'evidence.json';i.write_json(path,{'value':1});before=path.read_bytes()
            with self.assertRaises(FileExistsError):i.write_json(path,{'value':2})
            self.assertEqual(path.read_bytes(),before)

if __name__=='__main__':unittest.main()
