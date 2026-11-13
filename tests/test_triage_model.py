"""Meaningful scoring/schema/leakage and opt-in training regression checks."""
from copy import deepcopy
from decimal import localcontext, Rounded
import importlib.util
import json
import math
import unittest
from unittest.mock import patch

from crypto_reconciliation_lab.triage import model as scoring
from crypto_reconciliation_lab.triage.contracts import FEATURE_NAMES, digest
from triage_model_fixtures import values, row, document, labels, literal_model, reidentify


class JSONModelTests(unittest.TestCase):
    def test_literal_linear_score_and_missing_contribution_are_exactly_explained(self):
        model = literal_model()
        scored = scoring.score_features(model, values(count=2))
        self.assertAlmostEqual(scored['score'], 0.8807970779778823, places=15)
        self.assertEqual(scored['rounded_score'], '0.880797077978')
        self.assertEqual(scored['linear_score'], 2)
        self.assertEqual(math.fsum(item['linear_contribution'] for item in scored['contributions']), 2)
        ratio_index = FEATURE_NAMES.index('a_relative_difference_max')
        model['preprocessing']['medians'][ratio_index] = 1.0
        model['estimator']['coefficients'] = [0.0] * (2 * len(FEATURE_NAMES))
        model['estimator']['coefficients'][ratio_index] = 1
        model['estimator']['coefficients'][len(FEATURE_NAMES)+ratio_index] = -1
        reidentify(model)
        original = values(ratio=None)
        scored = scoring.score_features(model, original)
        self.assertEqual(scored['score'], 0.5)
        self.assertIsNone(original['a_relative_difference_max'])
        self.assertIsNone(scored['contributions'][ratio_index]['original_value'])

    def test_metadata_version_order_horizon_and_content_tampering_reject(self):
        mutations = [lambda m: m.update(format='other'), lambda m: m.update(horizon_hours=48),
            lambda m: m.update(contract_sha256='8'*64), lambda m: m['feature_names'].reverse(),
            lambda m: m.update(secret_new_feature=1),
            lambda m: m['preprocessing']['scales'].__setitem__(0, 0),
            lambda m: m['estimator']['coefficients'].__setitem__(0, float('inf')),
            lambda m: m['estimator'].update(classes=[False, True]),
            lambda m: m['training'].update(fit_split='validation')]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                model = literal_model()
                mutate(model)
                with self.assertRaises(ValueError):
                    scoring.validate_model(model)
        model = literal_model()
        model['estimator']['intercept'] = 1
        with self.assertRaisesRegex(ValueError, 'MODEL_IDENTITY'):
            scoring.validate_model(model)

    def test_unknown_wrong_type_missing_and_nonfinite_features_reject(self):
        variants = []
        for name, value in [('a_open_count', True), ('a_open_count', None), ('a_open_count', -1),
                            ('a_open_count', 1.5), ('observed_age_hours', float('nan')),
                            ('observed_age_hours', 'Infinity'), ('a_relative_difference_max', '1e4')]:
            item = values(); item[name] = value; variants.append(item)
        item = values(); item['seed'] = 10; variants.append(item)
        item = values(); item.pop('b_open_count'); variants.append(item)
        for item in variants:
            with self.subTest(item=item), self.assertRaises(ValueError):
                scoring.score_features(literal_model(), item)

    def test_same_observation_renamed_ids_aliases_and_paths_keep_score(self):
        first = row(0)
        features, splits = document([first])
        model = literal_model(digest(splits))
        before = scoring.score_rows(model, features)[0]
        changed = deepcopy(features)
        changed['units'][0].update(unit_id='renamed::AX', episode_id='renamed', world_id='neutral',
                                  source_alias='renamed-anything', scenario_filename='does-not-enter-vector')
        changed['units'][0]['finding_refs'][0]['run_id'] = 'changed-run-provenance'
        for proof in changed['units'][0]['feature_provenance'].values():
            for source in proof['sources']:
                source['run_id'] = 'changed-run-provenance'
        after = scoring.score_rows(model, changed)[0]
        self.assertNotEqual(before['unit_id'], after['unit_id'])
        self.assertEqual(before['score'], after['score'])
        self.assertEqual(before['rounded_score'], after['rounded_score'])

    def test_feature_time_and_provenance_future_are_rejected(self):
        original, splits = document([row(0)])
        for change in ('as_of', 'first_seen_at', 'proof'):
            features = deepcopy(original)
            if change == 'proof':
                features['units'][0]['feature_provenance']['a_open_count']['latest_knowledge_at'] = '2026-11-12T00:00:00Z'
            else:
                features['units'][0][change] = '2026-11-12T00:00:00Z'
            with self.subTest(change=change), self.assertRaises(ValueError):
                scoring.score_rows(literal_model(digest(splits)), features)

    def test_half_even_common_score_precision(self):
        self.assertEqual(scoring.quantized_score(0.5000000000005), '0.500000000000')
        self.assertEqual(scoring.quantized_score(0.5000000000015), '0.500000000002')
        self.assertEqual(scoring.quantized_score(0.5), '0.500000000000')
        with localcontext() as context:
            context.prec = 2
            context.traps[Rounded] = True
            self.assertEqual(scoring.quantized_score(0.5000000000015), '0.500000000002')

    def test_json_roundtrip_deterministic_and_metadata_mismatch_is_not_fallback(self):
        features, splits = document([row(0), row(1)])
        model = literal_model(digest(splits))
        decoded = json.loads(json.dumps(model, allow_nan=False))
        self.assertEqual(scoring.score_rows(model, features), scoring.score_rows(decoded, features))
        wrong = deepcopy(features); wrong['splits_sha256'] = 'a'*64
        with self.assertRaisesRegex(ValueError, 'MODEL_SPLIT'):
            scoring.score_rows(model, wrong)

    def test_unscorable_unit_is_explicit_and_never_a_successful_fallback(self):
        features, splits = document([row(0, count=3)])
        model = literal_model(digest(splits))
        model['estimator']['coefficients'][0] = 1e308
        reidentify(model)
        with self.assertRaisesRegex(ValueError, 'TRIAGE_UNSCORABLE_UNIT') as raised:
            scoring.score_rows(model, features)
        self.assertEqual(raised.exception.unit_id, 'e0::AX')
        self.assertEqual(raised.exception.unscorable_inventory[0]['fallback'], None)

    def test_scoring_does_not_import_optional_libraries(self):
        real_import = __import__
        def checked(name, *args, **kwargs):
            if name.split('.')[0] in {'sklearn', 'numpy', 'scipy'}:
                raise AssertionError('optional library imported by JSON rank')
            return real_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=checked):
            self.assertEqual(scoring.score_features(literal_model(), values())['score'], 0.5)


@unittest.skipUnless(importlib.util.find_spec('sklearn'), 'optional ai extra not installed; training checks NOT RUN')
class TrainingBoundaryTests(unittest.TestCase):
    def fixture(self):
        rows = [row(0, count=0, age='3', ratio=None), row(1, count=2, age='9', ratio='2'),
                row(2, status='NO_OPEN_FINDING', count=99), row(3, count=500),
                row(4, split='validation', world='w1', count=999999, age='9000', ratio='9999'),
                row(5, split='test', world='w2', count=888888),
                row(6, split='challenge', world='w3', count=777777)]
        features, splits = document(rows)
        return features, labels(rows[:4], [0, 1, 0, None]), splits

    def test_preprocessing_train_known_open_only_and_actual_library_parity(self):
        features, truth, splits = self.fixture()
        model, audit = scoring.train_model(features, truth, splits)
        self.assertEqual(model['training']['fit_unit_ids'], ['e0::AX', 'e1::AX'])
        self.assertEqual(audit['preprocessing_fit_unit_ids'], ['e0::AX', 'e1::AX'])
        self.assertEqual(model['preprocessing']['means'][0], 1.0)
        self.assertEqual(model['preprocessing']['medians'][0], 1.0)
        self.assertEqual(audit['fit_count'], 2)
        self.assertEqual(audit['train_inventory_count'], 4)
        self.assertEqual(len(audit['excluded']), 2)
        self.assertLessEqual(audit['scorer_parity']['maximum_absolute_error'], 1e-12)
        self.assertEqual(audit['scorer_parity']['actual_t_rows'], 7)
        self.assertEqual(audit['scorer_parity']['literal_fixture_rows'], 2)
        ratio = FEATURE_NAMES.index('b_relative_difference')
        self.assertTrue(model['preprocessing']['all_missing'][ratio])
        self.assertEqual(model['preprocessing']['medians'][ratio], 0)
        self.assertIsNone(features['units'][0]['features']['a_relative_difference_max'])

    def test_validation_changes_never_fit_and_same_t_twins_score_equally(self):
        features, truth, splits = self.fixture()
        model, _ = scoring.train_model(features, truth, splits)
        changed = deepcopy(features)
        for unit in changed['units'][4:]:
            unit['features']['a_open_count'] = 1234567
        second, _ = scoring.train_model(changed, truth, splits)
        self.assertEqual(model, second)
        twin = deepcopy(features['units'][0]); twin.update(unit_id='twin::AX', episode_id='twin')
        test_doc = deepcopy(features); test_doc['units'] = [features['units'][0], twin]
        scores = scoring.score_rows(model, test_doc)
        self.assertEqual(scores[0]['score'], scores[1]['score'])

    def test_cross_split_and_incomplete_label_coverage_halt_training(self):
        features, truth, splits = self.fixture()
        bad = deepcopy(splits); bad['groups'].append({'world_id':'w0','split':'test','episode_ids':['new']})
        with self.assertRaises(ValueError):
            scoring.train_model(features, truth, bad)
        bad = deepcopy(features); bad['units'][0]['split'] = 'test'
        with self.assertRaises(ValueError):
            scoring.train_model(bad, truth, splits)
        bad = deepcopy(truth); bad['units'].pop()
        with self.assertRaisesRegex(ValueError, 'LABEL_COVERAGE'):
            scoring.train_model(features, bad, splits)
        bad = deepcopy(truth); bad['units'][0]['label'] = False
        with self.assertRaisesRegex(ValueError, 'LABEL_TYPE'):
            scoring.train_model(features, bad, splits)


if __name__ == '__main__':
    unittest.main()
