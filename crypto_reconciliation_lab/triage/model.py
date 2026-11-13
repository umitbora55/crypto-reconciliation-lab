"""Optional train-only learning and strict, standard-library JSON scoring.

Nothing imports an ML library until train_model is explicitly called. Scores are
synthetic ranking signals, not calibrated financial risk probabilities.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, Context, localcontext
from datetime import timedelta
import importlib.metadata
import json
import math
import re
import warnings

from .contracts import (FEATURE_NAMES, DECIMAL_FEATURES, CONTRACT_SHA256,
    digest, validate_values, validate_features as validate_feature_document,
    validate_splits as validate_split_document, timestamp)

MODEL_FORMAT = 'triage-model-v1'
TARGET = 'unresolved_at_horizon'
EXPERIMENT_FORMAT = 'triage-experiment-v1'
HORIZON_HOURS = 24
SCORER_TOLERANCE = 1e-12
PARAMETERS = {'C': 1.0, 'l1_ratio': 0.0, 'solver': 'lbfgs', 'tol': 1e-4,
              'max_iter': 1000, 'fit_intercept': True, 'class_weight': None,
              'random_state': 20261111}
HASH = re.compile(r'[0-9a-f]{64}\Z')
MODEL_KEYS = frozenset(('format', 'experiment_format', 'target', 'horizon_hours',
    'feature_names', 'contract_sha256', 'splits_sha256', 'training',
    'preprocessing', 'estimator', 'versions', 'score_semantics', 'model_id'))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _number(value, name, *, positive=False):
    _require(type(value) in (int, float), name + ' must be a finite JSON number')
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    _require(finite, name + ' must be a finite JSON number')
    if positive:
        _require(value > 0, name + ' must be positive')
    return float(value)


def _hash(value, name):
    _require(isinstance(value, str) and HASH.fullmatch(value), name + ' must be SHA-256 text')


def _text(value, name):
    _require(isinstance(value, str) and bool(value), name + ' must be nonempty text')


def feature_vector(values):
    """Convert only allowlisted dimensionless features at the model boundary."""
    validate_values(values)
    result = []
    for name in FEATURE_NAMES:
        value = values[name]
        if value is None:
            result.append(None)
            continue
        try:
            numeric = float(Decimal(value)) if name in DECIMAL_FEATURES else float(value)
        except (InvalidOperation, ValueError, OverflowError) as error:
            raise ValueError('FEATURE_TYPE: invalid finite feature ' + name) from error
        _require(math.isfinite(numeric), 'FEATURE_TYPE: nonfinite converted feature ' + name)
        result.append(numeric)
    return result


def validate_features(document):
    return validate_feature_document(document)['units']


def validate_splits(document, units):
    episodes = validate_split_document(document)
    for row in units:
        _require(episodes.get(row['episode_id']) == (row['world_id'], row['split']),
                 'SPLIT_LEAKAGE: unit disagrees with complete world/episode split roster')
    return {world: split for world, split in episodes.values()}


def _label_map(document, units, *, expected_splits=None):
    _require(isinstance(document, dict) and document.get('format') == 'triage-labels-v1', 'LABEL_FORMAT: unsupported label document')
    _require(document.get('target') == TARGET and type(document.get('horizon_hours')) is int and document.get('horizon_hours') == HORIZON_HOURS,
             'LABEL_SCOPE: target/horizon mismatch')
    labels = document.get('units')
    _require(isinstance(labels, list), 'LABEL_SCHEMA: units must be a list')
    expected = {row['unit_id']: row for row in units if expected_splits is None or row['split'] in expected_splits}
    result = {}
    for label in labels:
        _require(isinstance(label, dict), 'LABEL_SCHEMA: object required')
        uid = label.get('unit_id')
        _require(isinstance(uid, str) and uid not in result, 'LABEL_DUPLICATE: invalid or repeated unit ID')
        _require(uid in expected, 'LABEL_SCOPE: label outside expected unit roster')
        value = label.get('label')
        _require('label' in label and (value is None or type(value) is int and value in (0, 1)),
                 'LABEL_TYPE: label must be integer zero/one or explicit null')
        row = expected[uid]
        for key in ('world_id', 'episode_id', 'asset'):
            _require(label.get(key) == row[key], 'LABEL_SCOPE: ' + key + ' mismatch')
        for key in ('balance_at', 'as_of'):
            _require(key in label, 'LABEL_SCOPE: missing ' + key)
            _require(timestamp(label[key]) == timestamp(row[key]), 'LABEL_SCOPE: ' + key + ' mismatch')
        _require('horizon' in label, 'LABEL_SCOPE: missing horizon')
        _require(timestamp(label['horizon']) == timestamp(row['as_of']) + timedelta(hours=HORIZON_HOURS),
                 'LABEL_SCOPE: horizon must be exactly T plus 24 hours')
        _text(label.get('reason'), 'label reason')
        _text(label.get('family'), 'label family')
        result[uid] = label
    _require(set(result) == set(expected), 'LABEL_COVERAGE: exact unit coverage required; no silent dropping')
    return result


def validate_model(model, *, contract_sha256=None, splits_sha256=None):
    _require(isinstance(model, dict) and set(model) == MODEL_KEYS, 'MODEL_SCHEMA: unknown or missing model fields')
    _require(model['format'] == MODEL_FORMAT and model['experiment_format'] == EXPERIMENT_FORMAT, 'MODEL_FORMAT: unsupported format')
    _require(model['target'] == TARGET and type(model['horizon_hours']) is int and model['horizon_hours'] == HORIZON_HOURS,
             'MODEL_SCOPE: target/horizon mismatch')
    _require(model['feature_names'] == list(FEATURE_NAMES), 'MODEL_FEATURES: fixed feature order mismatch')
    for name in ('contract_sha256', 'splits_sha256', 'model_id'):
        _hash(model[name], name)
    _require(model['contract_sha256'] == CONTRACT_SHA256, 'MODEL_CONTRACT: frozen contract mismatch')
    if contract_sha256 is not None:
        _require(model['contract_sha256'] == contract_sha256, 'MODEL_CONTRACT: contract mismatch')
    if splits_sha256 is not None:
        _require(model['splits_sha256'] == splits_sha256, 'MODEL_SPLIT: split mismatch')
    training = model['training']
    _require(isinstance(training, dict) and set(training) == {'feature_sha256', 'label_sha256', 'fit_unit_ids', 'fit_world_ids', 'fit_split'}, 'MODEL_TRAINING: invalid training metadata')
    for name in ('feature_sha256', 'label_sha256'):
        _hash(training[name], name)
    _require(training['fit_split'] == 'train', 'MODEL_TRAINING: only train fit permitted')
    for key in ('fit_unit_ids', 'fit_world_ids'):
        ids = training[key]
        _require(isinstance(ids, list) and ids and all(isinstance(x, str) and x for x in ids)
                 and ids == sorted(set(ids)), 'MODEL_TRAINING: sorted distinct IDs required')
    preprocessing = model['preprocessing']
    _require(isinstance(preprocessing, dict) and set(preprocessing) == {'strategy', 'medians', 'all_missing', 'missing_indicators', 'means', 'scales'}, 'MODEL_PREPROCESSING: invalid preprocessing fields')
    _require(preprocessing['strategy'] == 'train_median_then_all_missing_indicators_then_standard_scaler'
             and preprocessing['missing_indicators'] == list(FEATURE_NAMES), 'MODEL_PREPROCESSING: unsupported strategy')
    n = len(FEATURE_NAMES)
    for name, length in (('medians', n), ('means', 2*n), ('scales', 2*n)):
        values = preprocessing[name]
        _require(isinstance(values, list) and len(values) == length, 'MODEL_DIMENSION: ' + name)
        for value in values:
            _number(value, name, positive=name == 'scales')
    _require(isinstance(preprocessing['all_missing'], list) and len(preprocessing['all_missing']) == n
             and all(type(x) is bool for x in preprocessing['all_missing']), 'MODEL_PREPROCESSING: all_missing must be boolean vector')
    for index, missing in enumerate(preprocessing['all_missing']):
        _require(not missing or preprocessing['medians'][index] == 0, 'MODEL_PREPROCESSING: all-null train column must have explicit zero median')
    estimator = model['estimator']
    _require(isinstance(estimator, dict) and set(estimator) == {'kind', 'parameters', 'classes', 'coefficients', 'intercept'}, 'MODEL_ESTIMATOR: invalid fields')
    _require(estimator['kind'] == 'LogisticRegression' and canonical(estimator['parameters']) == canonical(PARAMETERS), 'MODEL_ESTIMATOR: fixed regularized estimator required')
    _require(estimator['classes'] == [0, 1] and all(type(x) is int for x in estimator['classes']), 'MODEL_CLASSES: ordered integer classes zero/one required')
    coefficients = estimator['coefficients']
    _require(isinstance(coefficients, list) and len(coefficients) == 2*n, 'MODEL_DIMENSION: coefficients')
    for coefficient in coefficients:
        _number(coefficient, 'coefficient')
    _number(estimator['intercept'], 'intercept')
    versions = model['versions']
    _require(isinstance(versions, dict) and set(versions) == {'python', 'scikit-learn', 'numpy', 'scipy', 'joblib', 'threadpoolctl'}
             and all(isinstance(value, str) and value for value in versions.values())
             and versions['scikit-learn'] == '1.9.1', 'MODEL_VERSIONS: unsupported training dependency versions')
    _require(model['score_semantics'] == 'Synthetic unresolved_at_horizon ranking score; not calibrated financial risk.', 'MODEL_SEMANTICS: invalid score semantics')
    _require(digest({key: value for key, value in model.items() if key != 'model_id'}) == model['model_id'], 'MODEL_IDENTITY: content hash mismatch')
    return model


def quantized_score(score):
    score = _number(score, 'score')
    _require(0 <= score <= 1, 'MODEL_SCORE: score outside zero/one')
    with localcontext(Context(prec=40)):
        return format(Decimal(str(score)).quantize(Decimal('0.000000000001'), rounding=ROUND_HALF_EVEN), 'f')


def _score_validated(model, values):
    original = feature_vector(values)
    p, e = model['preprocessing'], model['estimator']
    imputed = [p['medians'][i] if value is None else value for i, value in enumerate(original)]
    matrix = imputed + [float(value is None) for value in original]
    standardized = [(value - mean) / scale for value, mean, scale in zip(matrix, p['means'], p['scales'])]
    terms = [value * coefficient for value, coefficient in zip(standardized, e['coefficients'])]
    _require(all(math.isfinite(value) for value in (*standardized, *terms)), 'MODEL_SCORE: nonfinite transformed value')
    decision = math.fsum([e['intercept'], *terms])
    _require(math.isfinite(decision), 'MODEL_SCORE: nonfinite decision')
    score = 1 / (1 + math.exp(-decision)) if decision >= 0 else math.exp(decision) / (1 + math.exp(decision))
    contributions = []
    for i, name in enumerate((*FEATURE_NAMES, *(name + '__missing' for name in FEATURE_NAMES))):
        base = i % len(FEATURE_NAMES)
        contributions.append({'feature': FEATURE_NAMES[base], 'component': name,
            'original_value': values[FEATURE_NAMES[base]], 'model_input': matrix[i],
            'standardized_value': standardized[i], 'coefficient': e['coefficients'][i],
            'linear_contribution': terms[i]})
    return {'score': score, 'rounded_score': quantized_score(score), 'linear_score': decision,
            'intercept': e['intercept'], 'contributions': contributions}


def score_features(model, values):
    validate_model(model)
    return _score_validated(model, values)


def score_rows(model, features):
    rows = validate_features(features)
    validate_model(model, contract_sha256=features['contract_sha256'], splits_sha256=features['splits_sha256'])
    result = []
    for row in rows:
        try:
            result.append(dict(unit_id=row['unit_id'], **_score_validated(model, row['features'])))
        except (ValueError, OverflowError) as cause:
            error = ValueError('TRIAGE_UNSCORABLE_UNIT: ' + row['unit_id'] + ': ' + str(cause))
            error.unit_id = row['unit_id']
            error.unscorable_inventory = [{'unit_id': row['unit_id'], 'reason': str(cause), 'fallback': None}]
            raise error from cause
    return result


def train_model(features, labels, splits):
    """Fit the one frozen estimator; return JSON model and development audit."""
    rows = validate_features(features)
    validate_splits(splits, rows)
    _require(digest(splits) == features['splits_sha256'], 'SPLIT_IDENTITY: feature split hash mismatch')
    train_rows = [row for row in rows if row['split'] == 'train']
    label_map = _label_map(labels, rows, expected_splits={'train'})
    fit_rows, excluded = [], []
    for row in train_rows:
        label = label_map[row['unit_id']]['label']
        if row['status'] != 'OPEN':
            excluded.append({'unit_id': row['unit_id'], 'reason': 'NO_OPEN_FINDING'})
        elif label is None:
            excluded.append({'unit_id': row['unit_id'], 'reason': 'CENSORED_OR_OUT_OF_SCOPE'})
        else:
            fit_rows.append(row)
    fit_rows.sort(key=lambda row: row['unit_id'])
    _require(fit_rows, 'TRAINING_EMPTY: no known-label open train units')
    y = [label_map[row['unit_id']]['label'] for row in fit_rows]
    _require(set(y) == {0, 1}, 'TRAINING_CLASSES: both fixed classes required; no resampling')
    try:
        import numpy as np
        import sklearn
        from sklearn.impute import SimpleImputer
        from sklearn.preprocessing import StandardScaler
        from sklearn.linear_model import LogisticRegression
        from sklearn.exceptions import ConvergenceWarning
    except ImportError as error:
        raise ValueError('AI_DEPENDENCY_MISSING: training requires the pinned ai extra') from error
    _require(sklearn.__version__ == '1.9.1', 'AI_DEPENDENCY_VERSION: scikit-learn==1.9.1 required')
    vectors = [feature_vector(row['features']) for row in fit_rows]
    x = np.array([[np.nan if value is None else value for value in vector] for vector in vectors], dtype=float)
    imputer = SimpleImputer(strategy='median', keep_empty_features=True)
    imputed = imputer.fit_transform(x)
    augmented = np.column_stack((imputed, np.isnan(x).astype(float)))
    scaler = StandardScaler()
    standardized = scaler.fit_transform(augmented)
    _require(bool(np.isfinite(standardized).all()), 'TRAINING_NONFINITE: preprocessing output invalid')
    classifier = LogisticRegression(**PARAMETERS)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        classifier.fit(standardized, y)
    _require(not any(issubclass(item.category, ConvergenceWarning) for item in caught), 'TRAINING_CONVERGENCE: fixed iteration budget did not converge')
    import sys
    versions = {'python': sys.version.split()[0], **{name: importlib.metadata.version(name) for name in ('scikit-learn', 'numpy', 'scipy', 'joblib', 'threadpoolctl')}}
    model = {'format': MODEL_FORMAT, 'experiment_format': EXPERIMENT_FORMAT, 'target': TARGET,
        'horizon_hours': HORIZON_HOURS, 'feature_names': list(FEATURE_NAMES),
        'contract_sha256': features['contract_sha256'], 'splits_sha256': features['splits_sha256'],
        'training': {'feature_sha256': digest([{'unit_id': row['unit_id'], 'features': row['features']} for row in fit_rows]),
                     'label_sha256': digest([label_map[row['unit_id']] for row in fit_rows]),
                     'fit_unit_ids': [row['unit_id'] for row in fit_rows],
                     'fit_world_ids': sorted({row['world_id'] for row in fit_rows}), 'fit_split': 'train'},
        'preprocessing': {'strategy': 'train_median_then_all_missing_indicators_then_standard_scaler',
            'medians': [float(value) for value in imputer.statistics_],
            'all_missing': [bool(value) for value in np.isnan(x).all(axis=0)],
            'missing_indicators': list(FEATURE_NAMES), 'means': [float(value) for value in scaler.mean_],
            'scales': [float(value) for value in scaler.scale_]},
        'estimator': {'kind': 'LogisticRegression', 'parameters': deepcopy(PARAMETERS),
                      'classes': [int(value) for value in classifier.classes_],
                      'coefficients': [float(value) for value in classifier.coef_[0]],
                      'intercept': float(classifier.intercept_[0])},
        'versions': versions, 'score_semantics': 'Synthetic unresolved_at_horizon ranking score; not calibrated financial risk.'}
    model['model_id'] = digest(model)
    validate_model(model)
    # All supplied T rows, including untouched validation/test/challenge features,
    # and literal boundary fixtures compare score implementations, never labels.
    score_vectors = [feature_vector(row['features']) for row in rows]
    literal = [{name: (None if name in DECIMAL_FEATURES else 0) for name in FEATURE_NAMES},
               {name: ('1.25' if name in DECIMAL_FEATURES else 2) for name in FEATURE_NAMES}]
    score_vectors += [feature_vector(values) for values in literal]
    parity_x = np.array([[np.nan if value is None else value for value in vector] for vector in score_vectors], dtype=float)
    library_values = classifier.predict_proba(scaler.transform(np.column_stack((imputer.transform(parity_x), np.isnan(parity_x).astype(float)))))[:, 1]
    json_values = [_score_validated(model, row['features'])['score'] for row in rows]
    json_values += [_score_validated(model, values)['score'] for values in literal]
    maximum_error = max(abs(float(left) - right) for left, right in zip(library_values, json_values))
    _require(maximum_error <= SCORER_TOLERANCE, 'SCORER_PARITY: library/JSON score tolerance exceeded')
    audit = {'status': 'PASS', 'fit_split': 'train', 'fit_unit_ids': model['training']['fit_unit_ids'],
        'fit_world_ids': model['training']['fit_world_ids'], 'fit_count': len(fit_rows),
        'train_inventory_count': len(train_rows), 'excluded': excluded,
        'known_class_counts': {'0': y.count(0), '1': y.count(1)},
        'preprocessing_fit_unit_ids': model['training']['fit_unit_ids'],
        'versions': versions, 'estimator_parameters': deepcopy(PARAMETERS),
        'iterations': [int(value) for value in classifier.n_iter_],
        'warnings': [str(item.message) for item in caught],
        'scorer_parity': {'status': 'PASS', 'rows': len(score_vectors), 'actual_t_rows': len(rows),
                          'literal_fixture_rows': len(literal), 'absolute_tolerance': SCORER_TOLERANCE,
                          'maximum_absolute_error': maximum_error},
        'model_id': model['model_id'], 'fallback_count': 0}
    return model, audit
