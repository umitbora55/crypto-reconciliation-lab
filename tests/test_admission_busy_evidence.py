"""A real no-AI run exposed legitimate UNKNOWN busy evidence rejected by v2.

The input here is explicitly synthetic verifier data; real writer runs are separate.
"""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('busy_scope',ROOT/'scripts/release_admission_scope.py')
gate=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(gate)
FIXTURE=importlib.util.spec_from_file_location('busy_fixture',ROOT/'tests/test_admission_release.py')
fixture=importlib.util.module_from_spec(FIXTURE);FIXTURE.loader.exec_module(fixture)


def unknown_contender(report):
    row=next(r for r in report['scenarios'] if r['id']=='writers_same_stream')
    process=next(p for p in row['processes'] if p['result']['response_outcomes']=={'REPLAY':30})
    result=process['result']
    result.update(status='INCOMPLETE',committed_prefix=None,blocked=None,
                  state_observation='UNKNOWN',response_count=1,response_outcomes={'RETRYABLE_BUSY':1})
    result['last_response'].update(outcome='RETRYABLE_BUSY',ack=False,durable=False,attempt_id=None,
        committed_prefix=None,blocked=None,core_receipt_row_id=None,core_result=None,disposition=None,
        reason='database is locked',sequence=1)
    next(m for m in process['messages'] if m['type']=='RESULT')['result']=copy.deepcopy(result)
    row['observed']['attempt_outcomes']={'COMMITTED':30}
    return row,process,result


class AdmissionBusyEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.scope=gate.load_scope(ROOT)
        self.report=fixture.report_fixture(self.scope)

    def test_legitimate_unknown_busy_observation_is_accepted_after_complete_readback(self):
        row,process,result=unknown_contender(self.report)
        accepted=gate.validate_report(self.report,self.scope,schedule_sha256='a'*64)
        self.assertEqual(accepted['executed_count'],21)
        self.assertEqual(row['observed']['core_receipts'],30)
        self.assertEqual(row['financial']['status'],'EVALUATED')
        self.assertFalse(result['last_response']['ack'])

    def test_unknown_busy_evidence_rejects_partial_or_success_claims(self):
        for mode in ('missing_unknown','partial_null','ack','durable','attempt','complete','not_busy','final_incomplete'):
            report=copy.deepcopy(self.report);row,process,result=unknown_contender(report)
            if mode=='missing_unknown': result.pop('state_observation')
            elif mode=='partial_null':result['blocked']=False
            elif mode=='ack':result['last_response']['ack']=True
            elif mode=='durable':result['last_response']['durable']=True
            elif mode=='attempt':result['last_response']['attempt_id']=1
            elif mode=='complete':result['status']='COMPLETE'
            elif mode=='not_busy':result['last_response']['outcome']='GAP';result['response_outcomes']={'GAP':1}
            else:row['observed']['effect_identities'].pop()
            next(m for m in process['messages'] if m['type']=='RESULT')['result']=copy.deepcopy(result)
            with self.subTest(mode=mode),self.assertRaisesRegex(ValueError,'ADMISSION_SCOPE'):
                gate.validate_report(report,self.scope,schedule_sha256='a'*64)
