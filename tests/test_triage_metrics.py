"""Manual denominators and censored-capacity examples, not model-derived oracles."""
from copy import deepcopy
import unittest

from crypto_reconciliation_lab.triage.metrics import evaluate_comparison
from triage_model_fixtures import row, labels


class TriageMetricTests(unittest.TestCase):
    def fixture(self, targets, *, closed=()):
        rows = [row(i, world='w' + str(i // 4), status='NO_OPEN_FINDING' if i in closed else 'OPEN') for i in range(len(targets))]
        ids = [item['unit_id'] for item in rows if item['status'] == 'OPEN']
        return rows, {name:list(ids) for name in ('fifo','rules','model')}, labels(rows, targets)

    def test_unknown_top_k_is_not_negative_refilled_or_removed_from_capacity(self):
        rows, rankings, truth = self.fixture([1,None,0,1,0,0,0,1,0,0])
        result = evaluate_comparison(rows, rankings, truth)['policies']['model']
        self.assertEqual((result['N'], result['K'], result['TP'], result['FP'], result['U']), (10,2,1,0,1))
        self.assertEqual((result['known_positive'],result['known_negative'],result['censored_or_unknown']), (3,6,1))
        self.assertEqual(result['recall_known_at_budget'], 1/3)
        self.assertEqual(result['precision_labeled_at_budget'], 1)
        self.assertIsNone(result['precision_at_budget'])
        self.assertEqual(result['precision_bounds'], [0.5,1])
        self.assertEqual(result['top_k_label_coverage'], 0.5)
        self.assertIsNone(result['full_recall_at_budget'])
        self.assertEqual(result['known_positive_missed'], 2)

    def test_censored_counts_for_ceil_budget_and_can_consume_all_selected_capacity(self):
        rows, rankings, truth = self.fixture([None,0,1,0,1])
        result = evaluate_comparison(rows, rankings, truth)['policies']['fifo']
        self.assertEqual((result['N'], result['K'], result['U']), (5,1,1))
        self.assertEqual(result['recall_known_at_budget'], 0)
        self.assertIsNone(result['precision_labeled_at_budget'])
        self.assertEqual(result['precision_bounds'], [0,1])
        self.assertEqual(result['top_k_label_coverage'], 0)
        rows, rankings, truth = self.fixture([1,0,0,0,0,None])
        result = evaluate_comparison(rows, rankings, truth)['policies']['fifo']
        self.assertEqual((result['N'], result['K']), (6,2))
        self.assertEqual(result['precision_at_budget'], 0.5)
        self.assertIsNone(result['full_recall_at_budget'])

    def test_empty_no_positive_and_closed_inventory_are_not_fabricated_successes(self):
        rows, rankings, truth = self.fixture([])
        result = evaluate_comparison(rows, rankings, truth)
        self.assertEqual((result['open_count'],result['policies']['fifo']['K']), (0,0))
        for key in ('recall_known_at_budget','precision_labeled_at_budget','precision_at_budget','precision_bounds','top_k_label_coverage'):
            self.assertIsNone(result['policies']['fifo'][key])
        rows, rankings, truth = self.fixture([0,0,None])
        result = evaluate_comparison(rows, rankings, truth)
        self.assertIsNone(result['policies']['rules']['recall_known_at_budget'])
        self.assertIsNone(result['model_minus_rules_recall_known'])
        self.assertIn('Not assessable', result['conclusion'])
        rows, rankings, truth = self.fixture([1,0,0], closed=(0,))
        result = evaluate_comparison(rows, rankings, truth)
        self.assertEqual((result['inventory_count'],result['open_count'],result['excluded_count']), (3,2,1))
        self.assertEqual(result['excluded'][0]['label'], 1)
        self.assertEqual(result['policies']['model']['known_positive'], 0)

    def test_groups_attribute_same_global_selection_without_local_reranking(self):
        rows, rankings, truth = self.fixture([1,0,1,0,1,0,1,0,1,0])
        for index, item in enumerate(truth['units']):
            item['family'] = 'alpha' if index < 4 else 'beta'
        result = evaluate_comparison(rows, rankings, truth)['policies']['model']
        self.assertEqual(result['groups']['world_id']['w0']['K'], 2)
        self.assertEqual(result['groups']['world_id']['w1']['K'], 0)
        self.assertEqual(result['groups']['family']['beta']['known_positive_missed'], 3)
        self.assertEqual(sum(item['K'] for item in result['groups']['world_id'].values()), 2)
        self.assertEqual(sum(item['TP'] for item in result['groups']['family'].values()), result['TP'])
        self.assertIn('same global', result['groups']['world_id']['w1']['selection_scope'])

    def test_rankings_are_complete_and_label_scope_exact(self):
        rows, rankings, truth = self.fixture([1,0,None,0,1])
        bad = deepcopy(rankings); bad['model'].pop()
        with self.assertRaisesRegex(ValueError, 'METRIC_RANKING'):
            evaluate_comparison(rows, bad, truth)
        bad = deepcopy(rankings); bad['model'][1] = bad['model'][0]
        with self.assertRaises(ValueError):
            evaluate_comparison(rows, bad, truth)
        bad = deepcopy(truth); bad['units'].pop()
        with self.assertRaisesRegex(ValueError, 'LABEL_COVERAGE'):
            evaluate_comparison(rows, rankings, bad)
        bad = deepcopy(truth); bad['units'][0]['label'] = False
        with self.assertRaisesRegex(ValueError, 'LABEL_TYPE'):
            evaluate_comparison(rows, rankings, bad)
        bad = deepcopy(truth); bad['units'][0]['asset'] = 'OTHER'
        with self.assertRaisesRegex(ValueError, 'LABEL_SCOPE'):
            evaluate_comparison(rows, rankings, bad)

    def test_label_time_scope_is_required_and_horizon_is_really_24_hours(self):
        rows, rankings, truth = self.fixture([1,0])
        for key in ('balance_at','as_of','horizon'):
            bad=deepcopy(truth); bad['units'][0].pop(key)
            with self.subTest(missing=key), self.assertRaisesRegex(ValueError,'LABEL_SCOPE'):
                evaluate_comparison(rows,rankings,bad)
        bad=deepcopy(truth); bad['units'][0]['horizon']='2026-11-11T04:00:00Z'
        with self.assertRaisesRegex(ValueError,'LABEL_SCOPE'):
            evaluate_comparison(rows,rankings,bad)
        bad=deepcopy(truth); bad['horizon_hours']=24.0
        with self.assertRaisesRegex(ValueError,'LABEL_SCOPE'):
            evaluate_comparison(rows,rankings,bad)

    def test_policy_difference_and_evidence_examples_keep_negative_result(self):
        rows, rankings, truth = self.fixture([1,0,1,0,0])
        rankings['model'] = rankings['model'][1:] + rankings['model'][:1]
        result = evaluate_comparison(rows, rankings, truth)
        self.assertEqual(result['model_minus_rules_recall_known'], -0.5)
        self.assertEqual(result['conclusion'], 'No additional benefit demonstrated in this synthetic experiment.')
        missed = result['misprioritized_examples']
        self.assertEqual(len(missed), 2)
        self.assertEqual(missed[0]['finding_refs'], rows[2]['finding_refs'])
        self.assertEqual(result['fallback_count'], 0)
        self.assertEqual(result['policies']['model']['selected_unit_ids'], ['e1::AX'])


if __name__ == '__main__':
    unittest.main()
