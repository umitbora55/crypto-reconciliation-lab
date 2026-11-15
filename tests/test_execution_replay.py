"""Literal financial, historical and complete-input offline replay checks."""
from contextlib import closing
import copy
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from crypto_reconciliation_lab import Store
from crypto_reconciliation_lab.execution import reconcile_recorded, export_execution
from crypto_reconciliation_lab.execution.demo import BALANCE_AT, KNOWLEDGE_AT, CONFIG
from replay_fixtures import (all_rows,assert_error,assert_reproduced,encoded,export_pair,
    hashed,literal_finances,load_pair,rebound,verify,write_historical)
from replay_historical_fixtures import historical_0101, GENERATION
from stage12_1_epoch_fixture import historical_records


class ExecutionReplayFinancialTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_clean_literal_balances_and_full_comparison(self):
        pair=export_pair(self.root/'clean')
        literal_finances(self,pair)
        self.assertEqual(len(pair['run']['findings']),6)
        self.assertEqual({f['reconciliation_state'] for f in pair['run']['findings']},{'MATCHED'})
        assert_reproduced(self,verify(pair))

    def test_financial_custody_difference_is_successfully_reproduced(self):
        rows=all_rows()
        next(row['record'] for row in rows if row['record']['kind']=='report' and row['record']['asset']=='ASSET_A' and row['record']['scope']=='external')['amount']='8'
        pair=export_pair(self.root/'mismatch',rows=rows)
        literal_finances(self,pair)
        differences=[f for f in pair['run']['findings'] if f['reconciliation_state']=='MISMATCH']
        self.assertEqual([(f['comparison'],f['asset'],f['difference']) for f in differences],[('B','ASSET_A','1')])
        assert_reproduced(self,verify(pair))

    def test_manifest_supported_incomplete_and_id_conflict_are_reproduced(self):
        base=all_rows()
        withdrawal=next(row for row in base if row['record'].get('ref')=='A-withdrawal')
        missing=[row for row in base if row is not withdrawal]
        conflict=copy.deepcopy(withdrawal);conflict['record']['amount']='2'
        for name,rows,state in (('incomplete',missing,'INCOMPLETE'),('conflict',base+[conflict],'CONFLICT')):
            with self.subTest(name=name):
                pair=export_pair(self.root/name,rows=rows)
                selected=[f for f in pair['run']['findings'] if f['asset']=='ASSET_A']
                self.assertEqual({f['data_state'] for f in selected},{state})
                self.assertEqual({f['reconciliation_state'] for f in selected},{'NOT_EVALUATED'})
                assert_reproduced(self,verify(pair))

    def test_late_event_preserves_old_pair_after_new_database_data(self):
        rows=all_rows();withdrawal=next(row for row in rows if row['record'].get('ref')=='A-withdrawal')
        rows.remove(withdrawal)
        pair=export_pair(self.root/'late',rows=rows)
        before=(pair['context_path'].read_bytes(),pair['run_path'].read_bytes())
        with closing(Store(pair['database'])) as store:
            store.ingest(withdrawal['record'],'2026-11-13T02:00:00Z')
            after=reconcile_recorded(store,BALANCE_AT,'2026-11-13T03:00:00Z','after-arrival')
        target=self.root/'after';export_execution(pair['database'],after['execution_id'],target)
        newer=load_pair(target,after['execution_id'])
        self.assertEqual(pair['run']['ledgers']['ASSET_A']['investor_balances'],{'I1':'7','I2':'5'})
        literal_finances(self,newer)
        assert_reproduced(self,verify(pair));assert_reproduced(self,verify(newer))
        self.assertEqual((pair['context_path'].read_bytes(),pair['run_path'].read_bytes()),before)

    def test_report_revision_and_old_knowledge_cut_reproduce_separately(self):
        rows=all_rows();report=next(row for row in rows if row['record']['kind']=='report' and row['record']['asset']=='ASSET_A' and row['record']['scope']=='external')
        report['record']['amount']='8'
        pair=export_pair(self.root/'reports',rows=rows)
        revision=copy.deepcopy(report['record']);revision.update(version=2,amount='9')
        with closing(Store(pair['database'])) as store:
            store.ingest(revision,'2026-11-13T02:00:00Z')
            after=reconcile_recorded(store,BALANCE_AT,'2026-11-13T03:00:00Z','revised')
        target=self.root/'revised';export_execution(pair['database'],after['execution_id'],target)
        new=load_pair(target,after['execution_id'])
        old_b=next(f for f in pair['run']['findings'] if f['asset']=='ASSET_A' and f['comparison']=='B')
        new_b=next(f for f in new['run']['findings'] if f['asset']=='ASSET_A' and f['comparison']=='B')
        self.assertEqual((old_b['difference'],new_b['difference']),('1','0'))
        self.assertNotEqual(old_b['report_ids'],new_b['report_ids'])
        assert_reproduced(self,verify(pair));assert_reproduced(self,verify(new))

    def test_void_and_amount_replacement_preserve_trace_effects(self):
        from crypto_reconciliation_lab.correction_demo import correction_fixtures,T1
        from crypto_reconciliation_lab.demo import BALANCE_AT as CUT
        for name,values in (('void_deposit',('5','4','9','7')),('deposit_amount_correction',('8','4','12','10'))):
            with self.subTest(name=name):
                config,rows,_=correction_fixtures(name)
                pair=export_pair(self.root/name,config=config,rows=rows,balance_at=CUT,knowledge_at=T1)
                literal_finances(self,pair,*values)
                groups=pair['run']['ledgers']['ASSET_A']['correction_groups']
                self.assertEqual(len(groups),1)
                self.assertEqual(groups[0]['first_known_at'],'2026-11-11T03:00:00.000000Z')
                self.assertEqual(groups[0]['mode'],'VOID' if name=='void_deposit' else 'REPLACE')
                self.assertEqual(groups[0]['effective_amount'],'0' if name=='void_deposit' else '3')
                self.assertEqual(pair['run']['evidence'][groups[0]['id']]['derived_correction_group'],groups[0])
                assert_reproduced(self,verify(pair))

    def test_correction_before_target_and_competing_corrections(self):
        from crypto_reconciliation_lab.correction_demo import correction_fixtures,T1,T2,T3
        from crypto_reconciliation_lab.demo import BALANCE_AT as CUT
        config,rows,_=correction_fixtures('correction_before_target')
        for index,cut,expected in ((1,T1,('5','4','9','7')),(2,T2,('8','4','12','10'))):
            pair=export_pair(self.root/str(index),config=config,rows=rows,balance_at=CUT,knowledge_at=cut)
            literal_finances(self,pair,*expected)
            self.assertEqual(len(pair['run']['ledgers']['ASSET_A']['correction_groups']),index-1)
            assert_reproduced(self,verify(pair))
        config,rows,_=correction_fixtures('duplicate_and_conflicting_corrections')
        pair=export_pair(self.root/'competing',config=config,rows=rows,balance_at=CUT,knowledge_at=T3)
        literal_finances(self,pair)
        self.assertEqual(pair['run']['ledgers']['ASSET_A']['correction_groups'],[])
        self.assertEqual({f['data_state'] for f in pair['run']['findings'] if f['asset']=='ASSET_A'},{'CONFLICT'})
        assert_reproduced(self,verify(pair))

    def test_complete_empty_inventory_has_real_incomplete_findings(self):
        pair=export_pair(self.root/'empty',rows=[])
        self.assertTrue(all(value==[] for value in pair['context']['tables'].values()))
        self.assertEqual(len(pair['run']['findings']),6)
        self.assertEqual({f['data_state'] for f in pair['run']['findings']},{'INCOMPLETE'})
        assert_reproduced(self,verify(pair))
        missing=rebound(pair,self.root/'missing',mutate_context=lambda c:c['tables'].pop('receipts'))
        assert_error(self,verify(missing),'REPLAY_INTEGRITY')
        fake=rebound(pair,self.root/'fake',mutate_run=lambda r:r.update(findings=[]))
        assert_error(self,verify(fake),'REPLAY_INTEGRITY')

    def test_all_physical_rows_and_unselected_records_reach_query_only_adapter(self):
        from crypto_reconciliation_lab.replay.validation import validate_inputs
        from crypto_reconciliation_lab.replay.adapter import InputOnlyStore
        rows=all_rows();rows.append(copy.deepcopy(rows[0]))
        old=next(row for row in rows if row['record']['kind']=='report' and row['record']['asset']=='ASSET_A' and row['record']['scope']=='I1')
        new=copy.deepcopy(old);new['record']['version']=2;rows.append(new)
        outside=copy.deepcopy(next(row for row in rows if row['record'].get('ref')=='A-deposit'))
        outside['record'].update(ref='future-economic',occurred_at='2026-11-14T02:00:00Z',business_day='2026-11-14')
        rows.append(outside)
        rows.append({'record':{'kind':'event','asset':'ASSET_A'},'received_at':'bad-time'})
        pair=export_pair(self.root/'inventory',rows=rows)
        tables=pair['context']['tables'];self.assertEqual(len(tables['receipts']),34)
        self.assertEqual(len(tables['records']),32)
        selected={rid for item in pair['context']['selected_evidence'].values() for rid in item['record_ids']}
        self.assertLess(len(selected),len(tables['records']))
        validated=validate_inputs(pair['context_path'].read_bytes(),pair['run_path'].read_bytes(),pair['expected'])
        adapter=InputOnlyStore(validated.input_data['configuration'],validated.input_data['records'],validated.input_data['receipts'])
        self.addCleanup(adapter.db.close)
        actual=[dict(row) for row in adapter.db.execute('SELECT * FROM receipts ORDER BY id')]
        self.assertEqual(actual,tables['receipts'])
        self.assertEqual([dict(row) for row in adapter.db.execute('SELECT * FROM records ORDER BY id')],tables['records'])
        self.assertEqual(adapter.db.execute('PRAGMA query_only').fetchone()[0],1)
        with self.assertRaises(sqlite3.OperationalError):adapter.db.execute('DELETE FROM receipts')
        # Explicit test mutant: filtering to saved evidence silently drops an
        # unselected valid input even though that input need not change output.
        subset=[row for row in tables['records'] if row['id'] in selected]
        with self.assertRaises(AssertionError):self.assertEqual(subset,tables['records'])
        assert_reproduced(self,verify(pair))

    def test_large_physical_ids_remain_exact_in_adapter_and_public_replay(self):
        from crypto_reconciliation_lab.replay.validation import validate_inputs
        from crypto_reconciliation_lab.replay.adapter import InputOnlyStore
        original=export_pair(self.root/'large-original')
        def change(context):
            mapping={1:2**53+1,2:2**63-1}
            for row in context['tables']['receipts']:row['id']=mapping.get(row['id'],row['id'])
            context['tables']['receipts'].sort(key=lambda r:r['id'])
            for scope in context['selected_evidence'].values():scope['receipt_ids']=sorted(mapping.get(x,x) for x in scope['receipt_ids'])
        pair=rebound(original,self.root/'large',mutate_context=change)
        v=validate_inputs(pair['context_path'].read_bytes(),pair['run_path'].read_bytes(),pair['expected'])
        adapter=InputOnlyStore(v.input_data['configuration'],v.input_data['records'],v.input_data['receipts']);self.addCleanup(adapter.db.close)
        ids=[r[0] for r in adapter.db.execute('SELECT id FROM receipts ORDER BY id')]
        self.assertIn(9007199254740993,ids);self.assertIn(9223372036854775807,ids)
        self.assertNotIn(9007199254740992,ids)
        assert_reproduced(self,verify(pair))

    def test_raw_whitespace_hash_is_separate_from_canonical_run_identity(self):
        original=export_pair(self.root/'ordinary')
        pretty=(json.dumps(original['run'],indent=2,ensure_ascii=True)+'\n').encode()
        pair=rebound(original,self.root/'pretty',raw_run=pretty)
        self.assertEqual(pair['context']['run_id'],original['context']['run_id'])
        self.assertNotEqual(pair['context']['run_payload_sha256'],original['context']['run_payload_sha256'])
        result=verify(pair);assert_reproduced(self,result)
        self.assertEqual(pair['run_path'].read_bytes(),pretty)

    def test_two_authoritative_files_work_after_source_database_is_removed(self):
        pair=export_pair(self.root/'source')
        moved=self.root/'relocated';moved.mkdir()
        for key,name in (('context_path','context.json'),('run_path','run.json')):shutil.copyfile(pair[key],moved/name)
        identity={p.name:hashed(p.read_bytes()) for p in moved.iterdir()}
        shutil.rmtree(self.root/'source')
        moved_pair=load_pair(moved,pair['expected'])
        assert_reproduced(self,verify(moved_pair))
        self.assertEqual({p.name:hashed(p.read_bytes()) for p in moved.iterdir()},identity)
        self.assertFalse(pair['database'].exists())


class ExecutionReplayHistoricalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def test_authentic_0100_correct_pairs_and_wrong_original_epoch_summary(self):
        records=historical_records()
        for phase,expected in (('before-rotation',[1]),('after-real-new-delivery',[1,2])):
            pair=write_historical(self.root/phase,records[phase])
            self.assertEqual(pair['context']['acceptance_epochs'],expected)
            literal_finances(self,pair);assert_reproduced(self,verify(pair))
        for phase in ('after-current-replay','after-historical-replay'):
            pair=write_historical(self.root/phase,records[phase])
            self.assertEqual(pair['context']['acceptance_epochs'],[1,2])
            assert_error(self,verify(pair),'REPLAY_INTEGRITY')

    def test_authentic_0101_five_policy_phases_preserve_original_epoch_semantics(self):
        self.assertEqual(GENERATION['package'],'0.10.1')
        records=historical_0101()
        phases=('before-rotation','after-rotation','after-current-replay','after-historical-replay','after-real-new-delivery')
        for phase,epochs,attempts,receipts in zip(phases,([1],[1],[1],[1],[1,2]),(30,30,34,60,61),(30,30,30,30,31)):
            with self.subTest(phase=phase):
                pair=write_historical(self.root/phase,records[phase])
                self.assertEqual(pair['context']['acceptance_epochs'],epochs)
                self.assertEqual(pair['context']['counts']['delivery_attempts'],attempts)
                self.assertEqual(pair['context']['counts']['receipts'],receipts)
                literal_finances(self,pair);assert_reproduced(self,verify(pair))

    def test_escaped_unicode_quarantine_raw_strings_remain_untouched(self):
        from crypto_reconciliation_lab.replay.validation import validate_inputs
        from crypto_reconciliation_lab.replay.adapter import InputOnlyStore
        entry=historical_0101()['unicode-quarantine'];pair=write_historical(self.root/'unicode',entry)
        raw_context=pair['context_path'].read_bytes();raw_run=pair['run_path'].read_bytes()
        invalid=[r for r in pair['context']['tables']['receipts'] if r['status']=='INVALID']
        self.assertEqual(len(invalid),1)
        self.assertIn('\\ud800',invalid[0]['raw'])
        self.assertEqual(json.loads(invalid[0]['raw'])['record']['diagnostic'],'prefix\ud800suffix')
        v=validate_inputs(raw_context,raw_run,pair['expected'])
        adapter=InputOnlyStore(v.input_data['configuration'],v.input_data['records'],v.input_data['receipts']);self.addCleanup(adapter.db.close)
        self.assertEqual(adapter.db.execute('SELECT raw FROM receipts WHERE id=?',(invalid[0]['id'],)).fetchone()[0],invalid[0]['raw'])
        assert_reproduced(self,verify(pair))
        self.assertEqual((pair['context_path'].read_bytes(),pair['run_path'].read_bytes()),(raw_context,raw_run))
