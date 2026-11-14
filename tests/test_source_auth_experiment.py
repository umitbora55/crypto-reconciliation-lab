"""Real bounded process proof and independently constrained evidence mutations."""
import base64
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from crypto_reconciliation_lab.source_auth.demo import demo_source_auth
from crypto_reconciliation_lab.source_auth.fixtures import operator_anchor, TEST_KEYS
from crypto_reconciliation_lab.source_auth.verifier import verify_bundle, rehash
from crypto_reconciliation_lab.source_auth.crypto import sign_statement


class SourceAuthExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace=tempfile.TemporaryDirectory(prefix='source-auth-tests-')
        cls.bundle=Path(cls.workspace.name)/'actual'
        cls.report=demo_source_auth(cls.bundle)

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def mutate(self,change,pattern=None):
        with tempfile.TemporaryDirectory(prefix='source-auth-negative-') as tmp:
            target=Path(tmp)/'bundle'
            shutil.copytree(self.bundle,target,ignore=shutil.ignore_patterns('*.sqlite3','*-journal'))
            report=json.loads((target/'report.json').read_text())
            cases={c['id']:c for c in report['cases']}
            change(report,cases,target)
            (target/'report.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
            rehash(target)
            if pattern is None:
                return verify_bundle(target,operator_anchor())
            with self.assertRaisesRegex(ValueError,pattern):
                verify_bundle(target,operator_anchor())

    @staticmethod
    def sync(case):
        for name in case['auth_status']['tables']:
            case['auth_status']['tables'][name]=copy.deepcopy(case['sql_final'][name])

    def test_actual_complete_bundle(self):
        result=verify_bundle(self.bundle,operator_anchor())
        self.assertEqual((result['status'],result['families'],result['scenarios']),('PASSED',18,33))

    def test_fixed_literal_financial_outputs_and_paired_core_rows(self):
        cases={c['id']:c for c in self.report['cases']}
        for table in ('records','receipts','runs'):
            self.assertEqual(cases['valid_publishers']['sql_final'][table],cases['valid_publishers']['legacy_sql'][table])
        wrong=json.loads((self.bundle/cases['wrong_custody']['financial']).read_text())
        row=next(r for r in wrong['findings'] if r['comparison']=='B' and r['asset']=='ASSET_A')
        self.assertEqual((row['expected'],row['reported'],row['difference'],row['reconciliation_state']),('11','10','1','MISMATCH'))

    def test_mutation_campaign_all_six_rejections_and_extra_information(self):
        values=self.report['cases'][-1]['mutations']
        self.assertEqual(values['extra_information'],'ACCEPTED')
        self.assertEqual(len(values),7)
        self.assertTrue(all(v=='REJECTED' for k,v in values.items() if k!='extra_information'))

    def test_removed_required_family_rejected_after_rehash(self):
        self.mutate(lambda r,c,p:r.update(cases=[x for x in r['cases'] if x['id']!='wrong_custody']),'missing required scenario')

    def test_removed_decision_and_its_references_rejected(self):
        def change(r,c,p):
            case=c['valid_publishers'];s=case['sql_final']
            s['auth_decisions']=[d for d in s['auth_decisions'] if d['id']!=1]
            s['auth_delivery_links']=[d for d in s['auth_delivery_links'] if d['decision_id']!=1]
            s['auth_attempt_links']=[d for d in s['auth_attempt_links'] if d['decision_id']!=1]
            self.sync(case)
        self.mutate(change,'every effect/stream')

    def test_same_count_scope_with_valid_signature_rejected(self):
        def change(r,c,p):
            path=p/c['valid_publishers']['operations'][0]['envelope']
            env=json.loads(path.read_text());statement=json.loads(base64.b64decode(env['payload']))
            statement['capabilities'][0]={'source':'P1','platform':'P1','asset':'ASSET_A','kind':'correction','channel':'none'}
            path.write_bytes(sign_statement(statement,bytes.fromhex(TEST_KEYS['P1-old'][0]),'P1-old'))
        self.mutate(change,'independently invalid claim')

    def test_wrong_receipt_binding_rejected(self):
        def change(r,c,p):
            case=c['valid_publishers'];case['sql_final']['auth_delivery_links'][0]['core_receipt_id']=2;self.sync(case)
        self.mutate(change,'core receipt link')

    def test_wrong_key_binding_rejected(self):
        def change(r,c,p):
            case=c['valid_publishers'];case['sql_final']['auth_endorsements'][0]['key_id']='C1-key';self.sync(case)
        self.mutate(change,'endorsement key_id mismatch')

    def test_wrong_source_binding_rejected(self):
        def change(r,c,p):
            case=c['valid_publishers'];case['sql_final']['auth_streams'][0]['source']='C1';self.sync(case)
        self.mutate(change,'stream owner linkage')

    def test_denied_pass_flag_cannot_hide_committed_actual(self):
        self.mutate(lambda r,c,p:c['bad_signature']['controls']['status'].update(actual='COMMITTED',passed=True),'semantic control')

    def test_signed_mismatch_cannot_be_relabelled_matched(self):
        def change(r,c,p):
            path=p/c['wrong_custody']['financial'];value=json.loads(path.read_text())
            for row in value['findings']:
                if row['asset']=='ASSET_A' and row['comparison']=='B':row['reconciliation_state']='MATCHED';row['difference']='0'
            path.write_text(json.dumps(value))
        self.mutate(change,'financial report differs from saved run')

    def test_extra_information_is_accepted(self):
        result=self.mutate(lambda r,c,p:r.update({'extra:note':'Additional non-authoritative explanation.'}))
        self.assertEqual(result['status'],'PASSED')

    def test_missing_attempt_authorization_rejected(self):
        def change(r,c,p):
            case=c['normal_replay'];case['sql_final']['auth_attempt_links'].pop();self.sync(case)
        self.mutate(change,'complete one-to-one attempt decision links')

    def test_historical_replay_requires_revoked_key_and_original_approval(self):
        def change(r,c,p):
            case=c['revoked_replay'];case['sql_final']['auth_decisions'][-1]['decision']='CURRENT';self.sync(case)
        self.mutate(change,'unauthorized current decision')

    def test_decision_stream_must_equal_signed_stream(self):
        def change(r,c,p):
            case=c['valid_publishers'];case['sql_final']['auth_decisions'][0]['stream_id']='platform-demo:other';self.sync(case)
        self.mutate(change,'decision statement stream/sequence')

    def test_initial_policy_hash_is_bound_to_first_epoch(self):
        def change(r,c,p):
            case=c['valid_publishers'];case['sql_final']['auth_configuration'][0]['initial_policy_hash']='0'*64;self.sync(case)
        self.mutate(change,'initial policy binding')

    def test_policy_cannot_change_grants_in_report(self):
        def change(r,c,p):
            c['unauthorized_asset']['initial_policy']['sources'][0]['capabilities'].append({'source':'P1','platform':'P1','asset':'ASSET_B','kind':'opening','channel':'none'})
        self.mutate(change,'operator case setup policy differs')

    def test_kill_requires_real_pid_barrier_join_unknown(self):
        for field,value in (('joined',False),('sender','RESPONSE'),('signal',None)):
            with self.subTest(field=field):
                self.mutate(lambda r,c,p:c['lost_ack']['process'].update({field:value}),'process identity/join|process kill/unknown')

    def test_policy_race_requires_actual_result_and_no_new_receipt(self):
        def change(r,c,p):
            c['policy_race']['process']['observations']=[o for o in c['policy_race']['process']['observations'] if o['type']!='RESULT']
        self.mutate(change,'policy race response')

    def test_false_financial_payload_not_equal_saved_run(self):
        def change(r,c,p):
            path=p/c['valid_publishers']['financial'];value=json.loads(path.read_text());value['knowledge_at']='2026-11-12T01:00:00.000000Z';path.write_text(json.dumps(value))
        self.mutate(change,'financial report differs from saved run')

    def test_manifest_rehash_does_not_replace_operator_anchor(self):
        def change(r,c,p):r['operator_anchor']['keys']['P1-old']['public_key']='0'*64
        self.mutate(change,'operator anchor mismatch')

    def test_precommit_half_authorization_rejected(self):
        def change(r,c,p):
            c['precommit_kill']['interrupted']['after']['auth_decisions'].append(copy.deepcopy(c['precommit_kill']['sql_final']['auth_decisions'][0]))
        self.mutate(change,'semantic control precommit_kill/before_retry_decisions')

    def test_missing_financial_report_file_rejected(self):
        self.mutate(lambda r,c,p:(p/c['wrong_custody']['financial']).unlink(),'missing or nonlocal evidence file')

    def test_snapshot_receipt_membership_exact_bytes(self):
        def change(r,c,p):
            case=c['valid_publishers'];case['sql_final']['delivery_effects'][0]['payload']='00';self.sync(case)
        self.mutate(change,'effect line membership')

    def test_denied_families_require_independent_invalid_input_or_policy_denial(self):
        # A recorded denial is not proof the required bad input was exercised.
        # Replace it with an authentic, authorized request; preserve DENIED, SQL,
        # expected/actual/PASS and recompute the entire file manifest.
        from crypto_reconciliation_lab.source_auth.fixtures import signed
        cases=('tampered_bytes','unsigned_hash','unknown_key','wrong_key','bad_signature',
               'wrong_receiver','wrong_config','wrong_namespace','scope_missing',
               'scope_substitution','malformed_type','duplicate_key','unicode_surrogate',
               'authority_redirection','hijack_empty','hijack_populated')
        for case_id in cases:
            with self.subTest(case_id=case_id):
                def change(r,c,p):
                    from crypto_reconciliation_lab.source_auth.fixtures import small_records,snapshot
                    op=c[case_id]['operations'][-1]
                    data=snapshot(small_records())
                    (p/op['snapshot']).write_bytes(data)
                    (p/op['envelope']).write_bytes(signed(data))
                self.mutate(change,'denial input condition')
        for case_id in ('unauthorized_asset','unauthorized_kind','unauthorized_channel','cartesian_hole'):
            with self.subTest(case_id=case_id):
                def change(r,c,p):
                    from crypto_reconciliation_lab.source_auth.fixtures import financial_records,snapshot
                    kind='event' if case_id=='unauthorized_kind' else 'opening'
                    record=next(x for x in financial_records()['P1'] if x['record']['asset']=='ASSET_A' and x['record']['kind']==kind)
                    data=snapshot([record]);op=c[case_id]['operations'][-1]
                    (p/op['snapshot']).write_bytes(data);(p/op['envelope']).write_bytes(signed(data))
                self.mutate(change,'denial input condition')
