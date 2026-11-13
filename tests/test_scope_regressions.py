"""Independent literal regressions for the three Stage 2.1 review findings."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from crypto_reconciliation_lab import Store, reconcile
from crypto_reconciliation_lab.correction_demo import T1, T2, correction, correction_manifest
from crypto_reconciliation_lab.demo import BALANCE_AT, KNOWLEDGE_AT, fixtures

CUT = '2026-11-10T04:00:00Z'
FUTURE = '2026-11-10T05:00:00Z'
BAD_TYPES = ([], {}, None, True, 17, 'UNKNOWN')


class ScopeRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stores = []
        self.addCleanup(lambda: [s.close() for s in self.stores])

    def store(self, cut=BALANCE_AT, rows=None):
        config, base, _ = fixtures(balance_at=cut)
        s = Store(Path(self.tmp.name)/f'{len(self.stores)}.sqlite3', config)
        self.stores.append(s)
        for row in base if rows is None else rows:
            s.ingest(row['record'], row['received_at'])
        return s

    def event(self):
        return copy.deepcopy(next(x['record'] for x in fixtures()[1] if x['record'].get('ref') == 'A2'))

    def future_claim(self, invalid=False):
        c = correction()
        c['target_occurred_at'] = FUTURE
        if invalid:
            c['replacement_amount'] = 'NaN'
        m = correction_manifest()
        m.update(coverage_from=CUT, coverage_to='2026-11-10T06:00:00Z')
        return c, m

    def findings(self, result, asset='ASSET_A'):
        return [f for f in result['findings'] if f['asset'] == asset]

    def clean_amounts(self, r):
        self.assertEqual(r['ledgers']['ASSET_A']['investor_balances'], {'I1':'7','I2':'4'})
        self.assertEqual(r['ledgers']['ASSET_A']['liability'], '11')
        self.assertEqual(r['ledgers']['ASSET_A']['custody_rollforward'], {'platform':'2','external':'9'})
        self.assertEqual(r['ledgers']['ASSET_B']['investor_balances'], {'I1':'0.3','I2':'0.2'})
        self.assertEqual(r['ledgers']['ASSET_B']['liability'], '0.5')

    def states(self, r, asset, data, outcome):
        for f in self.findings(r,asset):
            self.assertEqual((f['data_state'], f['reconciliation_state']), (data,outcome))
            self.assertEqual(f['provisional'], data != 'COMPLETE')

    def quarantine(self, r, receipt, assets=('ASSET_A',)):
        self.assertIn(receipt['receipt_id'], r['evidence'])
        self.assertTrue(receipt['error'])
        evidence = r['evidence'][receipt['receipt_id']]['quarantined_receipt']
        self.assertEqual(evidence['error'], receipt['error'])
        for asset in assets:
            self.states(r,asset,'INCOMPLETE','NOT_EVALUATED')
            for f in self.findings(r,asset):
                self.assertIn(receipt['receipt_id'], f['evidence_ids'])
                self.assertTrue(any(i['code']=='QUARANTINED_INPUT' for i in f['issues']))

    def test_f1_known_target_overrides_future_claim_and_batch_start(self):
        s = self.store(CUT)
        clean = reconcile(s,CUT,T1)
        c,m = self.future_claim()
        rc,rm = s.ingest(c,T1),s.ingest(m,T1)
        self.assertEqual((rc['status'],rm['status']),('ACCEPTED','ACCEPTED'))
        r = reconcile(s,CUT,T1)
        self.states(r,'ASSET_A','CONFLICT','NOT_EVALUATED')
        self.states(r,'ASSET_B','COMPLETE','MATCHED')
        self.clean_amounts(r)
        self.assertFalse(r['ledgers']['ASSET_A']['correction_groups'])
        self.assertTrue(r['ledgers']['ASSET_A']['correction_deliveries'])
        self.assertNotEqual(r['run_id'],clean['run_id'])
        target = next(x for x in r['evidence'].values() if x.get('record',{}).get('ref')=='A2')
        for f in self.findings(r):
            self.assertIn('TARGET_TIME_MISMATCH',{i['code'] for i in f['issues']})
            self.assertTrue({rc['record_id'],rm['record_id']} <= set(f['evidence_ids']))
        self.assertTrue({rc['receipt_id'],rm['receipt_id'],*target['receipt_ids']} <= r['evidence'].keys())
        self.assertEqual(s.read_run(clean['run_id']),clean)

    def test_f1_schema_invalid_future_claim_still_blocks_known_target(self):
        s = self.store(CUT)
        c,m = self.future_claim(invalid=True)
        rc,rm = s.ingest(c,T1),s.ingest(m,T1)
        self.assertEqual(rc['status'],'INVALID')
        r = reconcile(s,CUT,T1)
        self.states(r,'ASSET_A','INCOMPLETE','NOT_EVALUATED')
        self.states(r,'ASSET_B','COMPLETE','MATCHED')
        self.clean_amounts(r)
        self.assertFalse(r['ledgers']['ASSET_A']['correction_groups'])
        self.assertIn(rc['receipt_id'],r['evidence'])
        self.assertIn(rm['record_id'],r['evidence'])
        self.assertTrue(any(v.get('record',{}).get('ref')=='A2' for v in r['evidence'].values()))
        for f in self.findings(r):
            self.assertIn(rc['receipt_id'],f['evidence_ids'])
            self.assertIn('INVALID_REPLACEMENT_AMOUNT',{i['code'] for i in f['issues']})

    def test_f1_future_target_and_batch_do_not_reach_past(self):
        s = self.store(CUT)
        future = self.event()
        future.update(ref='FUTURE_EVENT',occurred_at=FUTURE)
        s.ingest(future,T1)
        c,m = self.future_claim()
        c['target']['ref']='FUTURE_EVENT'
        s.ingest(c,T1)
        s.ingest(m,T1)
        r = reconcile(s,CUT,T1)
        self.clean_amounts(r)
        self.states(r,'ASSET_A','COMPLETE','MATCHED')
        self.assertEqual(r['ledgers']['ASSET_A']['correction_groups'],[])
        self.assertEqual(r['ledgers']['ASSET_A']['correction_deliveries'],[])

    def test_f1_future_schema_invalid_target_does_not_block_past(self):
        s = self.store(CUT)
        future=self.event()
        future.update(ref='FUTURE_EVENT',occurred_at=FUTURE)
        s.ingest(future,T1)
        c,m=self.future_claim(invalid=True)
        c['target']['ref']='FUTURE_EVENT'
        receipt=s.ingest(c,T1)
        s.ingest(m,T1)
        r=reconcile(s,CUT,T1)
        self.states(r,'ASSET_A','COMPLETE','MATCHED')
        self.assertNotIn(receipt['receipt_id'],r['evidence'])

    def test_f1_unknown_target_uses_claim_without_future_knowledge(self):
        _,rows,_=fixtures(balance_at=CUT)
        target=next(x for x in rows if x['record'].get('ref')=='A2')
        rows.remove(target)
        s=self.store(CUT,rows)
        c,m=self.future_claim()
        rc=s.ingest(c,T1)
        s.ingest(m,T1)
        s.ingest(target['record'],T2)
        earlier=reconcile(s,CUT,T1)
        self.states(earlier,'ASSET_A','INCOMPLETE','NOT_EVALUATED')
        self.assertEqual(earlier['ledgers']['ASSET_A']['correction_deliveries'],[])
        self.assertNotIn(rc['record_id'],earlier['evidence'])
        later=reconcile(s,CUT,T2)
        self.states(later,'ASSET_A','CONFLICT','NOT_EVALUATED')
        self.assertIn('TARGET_TIME_MISMATCH',{i['code'] for i in later['ledgers']['ASSET_A']['issues']})
        self.assertEqual(s.read_run(earlier['run_id']),earlier)

    def test_f1_earlier_knowledge_and_saved_history_unchanged(self):
        s=self.store(CUT)
        earlier=reconcile(s,CUT,KNOWLEDGE_AT)
        c,m=self.future_claim()
        s.ingest(c,T1)
        s.ingest(m,T1)
        self.assertEqual(reconcile(s,CUT,KNOWLEDGE_AT),earlier)
        self.states(reconcile(s,CUT,T1),'ASSET_A','CONFLICT','NOT_EVALUATED')
        self.assertEqual(s.read_run(earlier['run_id']),earlier)

    def test_f2_event_extra_stream_cannot_route_quarantine(self):
        self.check_f2(False)

    def test_f2_event_extra_balance_time_cannot_hide_quarantine(self):
        self.check_f2(True)

    def check_f2(self, fake_time):
        s=self.store()
        raw=self.event()
        raw.update(amount='3',stream='external_custody')
        if fake_time:
            raw['balance_at']='2026-11-09T00:00:00Z'
        receipt=s.ingest(raw,KNOWLEDGE_AT)
        self.assertEqual(receipt['status'],'INVALID')
        r=reconcile(s,BALANCE_AT,KNOWLEDGE_AT)
        self.quarantine(r,receipt)
        self.clean_amounts(r)
        self.states(r,'ASSET_B','COMPLETE','MATCHED')
        self.assertEqual(r['evidence'][receipt['receipt_id']]['quarantined_receipt']['record'],raw)

    def test_f3_list_asset_does_not_crash(self):
        self.check_bad_asset([])

    def test_f3_dict_asset_does_not_crash(self):
        self.check_bad_asset({})

    def check_bad_asset(self,value):
        s=self.store()
        raw=self.event()
        raw['asset']=value
        receipt=s.ingest(raw,KNOWLEDGE_AT)
        self.assertEqual(receipt['status'],'INVALID')
        r=reconcile(s,BALANCE_AT,KNOWLEDGE_AT)
        self.quarantine(r,receipt,('ASSET_A','ASSET_B'))
        self.clean_amounts(r)
        self.assertEqual(r['evidence'][receipt['receipt_id']]['quarantined_receipt']['record'],raw)

    def test_f3_asset_json_type_table(self):
        for value in BAD_TYPES:
            with self.subTest(value=value):
                self.check_bad_asset(value)

    def test_f3_kind_json_type_table(self):
        for value in BAD_TYPES:
            with self.subTest(value=value):
                s=self.store()
                raw=self.event()
                raw.update(kind=value,stream='external_custody',balance_at='2026-11-09T00:00:00Z')
                rec=s.ingest(raw,KNOWLEDGE_AT)
                self.assertEqual(rec['status'],'INVALID')
                r=reconcile(s,BALANCE_AT,KNOWLEDGE_AT)
                self.quarantine(r,rec)
                self.states(r,'ASSET_B','COMPLETE','MATCHED')

    def test_f3_report_stream_scope_time_json_types(self):
        for field in ('stream','scope','balance_at'):
            for value in ([],{},None,True,17):
                with self.subTest(field=field,value=value):
                    s=self.store()
                    raw=copy.deepcopy(next(x['record'] for x in fixtures()[1] if x['record'].get('stream')=='external_custody' and x['record']['kind']=='report' and x['record']['asset']=='ASSET_A'))
                    raw[field]=value
                    rec=s.ingest(raw,KNOWLEDGE_AT)
                    self.assertEqual(rec['status'],'INVALID')
                    r=reconcile(s,BALANCE_AT,KNOWLEDGE_AT)
                    b=next(f for f in self.findings(r) if f['comparison']=='B')
                    self.assertEqual((b['data_state'],b['reconciliation_state']),('INCOMPLETE','NOT_EVALUATED'))
                    self.assertIn(rec['receipt_id'],b['evidence_ids'])
                    self.states(r,'ASSET_B','COMPLETE','MATCHED')
                    if field!='stream':
                        self.assertTrue(all(f['reconciliation_state']=='MATCHED' for f in self.findings(r) if f['comparison']=='A'))

    def test_f3_manifest_stream_and_time_json_types(self):
        for field in ('stream','coverage_from','coverage_to'):
            for value in ([],{},None,True,17):
                with self.subTest(field=field,value=value):
                    s=self.store()
                    raw=copy.deepcopy(next(x['record'] for x in fixtures()[1] if x['record']['kind']=='manifest' and x['record']['stream']=='event' and x['record']['asset']=='ASSET_A'))
                    raw[field]=value
                    rec=s.ingest(raw,KNOWLEDGE_AT)
                    self.assertEqual(rec['status'],'INVALID')
                    r=reconcile(s,BALANCE_AT,KNOWLEDGE_AT)
                    self.quarantine(r,rec)
                    self.states(r,'ASSET_B','COMPLETE','MATCHED')

    def test_f3_correction_target_and_time_types(self):
        variants=[('target',v) for v in ([],{},None,True,17)]
        variants += [('target_occurred_at',v) for v in ([],{},None,True,17)]
        variants += [('target.'+f,[]) for f in ('kind','source','platform','business_day','ref')]
        for field,value in variants:
            with self.subTest(field=field,value=value):
                s=self.store()
                raw=correction()
                if field.startswith('target.'):
                    raw['target'][field.split('.')[1]]=value
                else:
                    raw[field]=value
                rec=s.ingest(raw,T1)
                self.assertEqual(rec['status'],'INVALID')
                s.ingest(correction_manifest(),T1)
                r=reconcile(s,BALANCE_AT,T1)
                self.states(r,'ASSET_A','INCOMPLETE','NOT_EVALUATED')
                self.states(r,'ASSET_B','COMPLETE','MATCHED')
                self.assertIn(rec['receipt_id'],r['evidence'])
                self.clean_amounts(r)

    def test_existing_correction_and_manifest_invalid_asset_controls(self):
        for make in (correction,correction_manifest):
            with self.subTest(kind=make.__name__):
                s=self.store()
                raw=make()
                raw['asset']=[]
                rec=s.ingest(raw,T1)
                self.assertEqual(rec['status'],'INVALID')
                r=reconcile(s,BALANCE_AT,T1)
                for a in ('ASSET_A','ASSET_B'):
                    self.states(r,a,'INCOMPLETE','NOT_EVALUATED')
                self.assertIn(rec['receipt_id'],r['evidence'])
                self.clean_amounts(r)

    def test_existing_nan_event_control(self):
        s=self.store()
        raw=self.event()
        raw['amount']='NaN'
        rec=s.ingest(raw,KNOWLEDGE_AT)
        self.assertEqual(rec['status'],'INVALID')
        r=reconcile(s,BALANCE_AT,KNOWLEDGE_AT)
        self.quarantine(r,rec)
        self.states(r,'ASSET_B','COMPLETE','MATCHED')
        self.clean_amounts(r)

    def test_actual_external_report_preserves_investor_comparison(self):
        s=self.store()
        raw=copy.deepcopy(next(x['record'] for x in fixtures()[1] if x['record']['kind']=='report' and x['record']['stream']=='external_custody' and x['record']['asset']=='ASSET_A'))
        raw['amount']='NaN'
        rec=s.ingest(raw,KNOWLEDGE_AT)
        self.assertEqual(rec['status'],'INVALID')
        r=reconcile(s,BALANCE_AT,KNOWLEDGE_AT)
        for f in self.findings(r):
            self.assertEqual(f['data_state'],'COMPLETE' if f['comparison']=='A' else 'INCOMPLETE')
            self.assertEqual(f['reconciliation_state'],'MATCHED' if f['comparison']=='A' else 'NOT_EVALUATED')
        self.assertIn(rec['receipt_id'],r['evidence'])
        self.states(r,'ASSET_B','COMPLETE','MATCHED')

    def test_event_outside_cut_ignores_extra_fields(self):
        s=self.store(CUT)
        raw=self.event()
        raw.update(occurred_at=FUTURE,amount='3',stream='investor',balance_at=CUT)
        rec=s.ingest(raw,T1)
        self.assertEqual(rec['status'],'INVALID')
        r=reconcile(s,CUT,T1)
        self.states(r,'ASSET_A','COMPLETE','MATCHED')
        self.assertNotIn(rec['receipt_id'],r['evidence'])
        self.clean_amounts(r)

    def test_old_invalid_report_outside_cut_does_not_block(self):
        s=self.store()
        raw=copy.deepcopy(next(x['record'] for x in fixtures()[1] if x['record']['kind']=='report' and x['record']['asset']=='ASSET_A'))
        raw.update(balance_at='2026-11-09T00:00:00Z',amount='NaN',occurred_at=BALANCE_AT)
        rec=s.ingest(raw,KNOWLEDGE_AT)
        r=reconcile(s,BALANCE_AT,KNOWLEDGE_AT)
        self.states(r,'ASSET_A','COMPLETE','MATCHED')
        self.assertNotIn(rec['receipt_id'],r['evidence'])

    def test_saved_conflict_and_incomplete_survive_restart(self):
        for mode in ('F1','F2'):
            with self.subTest(mode=mode):
                s=self.store(CUT)
                before=reconcile(s,CUT,KNOWLEDGE_AT)
                if mode=='F1':
                    c,m=self.future_claim()
                    s.ingest(c,T1)
                    s.ingest(m,T1)
                else:
                    raw=self.event()
                    raw.update(stream='external_custody',balance_at='2026-11-09T00:00:00Z',amount='3')
                    s.ingest(raw,T1)
                result=reconcile(s,CUT,T1)
                self.states(result,'ASSET_A','CONFLICT' if mode=='F1' else 'INCOMPLETE','NOT_EVALUATED')
                path=s.db.execute('PRAGMA database_list').fetchone()[2]
                old_rows=[tuple(row) for row in s.db.execute('SELECT * FROM evidence WHERE run_id=? ORDER BY evidence_id',(before['run_id'],))]
                s.close()
                self.stores.remove(s)
                reopened=Store(path)
                self.stores.append(reopened)
                self.assertEqual(reopened.read_run(result['run_id']),result)
                self.assertEqual(reopened.read_run(before['run_id']),before)
                self.assertEqual([tuple(row) for row in reopened.db.execute('SELECT * FROM evidence WHERE run_id=? ORDER BY evidence_id',(before['run_id'],))],old_rows)

    def test_f1_f2_physical_arrival_order_preserves_full_evidence(self):
        for mode in ('F1','F2'):
            with self.subTest(mode=mode):
                _,rows,_=fixtures(balance_at=CUT)
                if mode=='F1':
                    extra=self.future_claim()
                else:
                    raw=self.event()
                    raw.update(amount='3',stream='external_custody',balance_at='2026-11-09T00:00:00Z')
                    extra=[raw]
                rows += [{'record':r,'received_at':T1} for r in extra]
                a=reconcile(self.store(CUT,rows),CUT,T1)
                b=reconcile(self.store(CUT,list(reversed(rows))),CUT,T1)
                self.states(a,'ASSET_A','CONFLICT' if mode=='F1' else 'INCOMPLETE','NOT_EVALUATED')
                self.clean_amounts(a)
                self.assertEqual(a,b)

if __name__=='__main__':
    unittest.main()
