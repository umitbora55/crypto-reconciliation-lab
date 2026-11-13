"""Writer provenance regressions on explicitly synthetic verifier input."""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('writer_scope_gate', ROOT / 'scripts/release_admission_scope.py')
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)
FIXTURE_SPEC = importlib.util.spec_from_file_location('writer_report_fixture', ROOT / 'tests/test_admission_release.py')
fixture = importlib.util.module_from_spec(FIXTURE_SPEC)
FIXTURE_SPEC.loader.exec_module(fixture)


class AdmissionWriterProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.scope = gate.load_scope(ROOT)
        self.report = fixture.report_fixture(self.scope)
        self.row = next(row for row in self.report['scenarios'] if row['id']=='clean')

    def validate(self):
        return gate.validate_report(self.report,self.scope,schedule_sha256='a'*64)

    def test_actual_feed_writer_observation_cannot_be_omitted_or_renamed(self):
        original=copy.deepcopy(self.row['writer_connections'])
        for mode in ('omit','rename'):
            self.row['writer_connections']=copy.deepcopy(original)
            index=next(i for i,w in enumerate(original) if w['operation']=='feed')
            if mode=='omit':self.row['writer_connections'].pop(index)
            else:self.row['writer_connections'][index]['operation']='unrelated-placeholder'
            with self.subTest(mode=mode),self.assertRaisesRegex(ValueError,'ADMISSION_SCOPE'):
                self.validate()

    def test_parent_writer_connections_share_the_observed_process(self):
        writer=next(w for w in self.row['writer_connections'] if w['operation']=='feed')
        writer['pid']=99999999
        with self.assertRaisesRegex(ValueError,'ADMISSION_SCOPE'):
            self.validate()

    def test_parent_writer_cannot_be_claimed_as_child_process(self):
        row=next(row for row in self.report['scenarios'] if row['id']=='lost_ack')
        for writer in row['writer_connections']:
            writer['pid']=row['processes'][0]['pid']
        with self.assertRaisesRegex(ValueError,'ADMISSION_SCOPE'):
            self.validate()
