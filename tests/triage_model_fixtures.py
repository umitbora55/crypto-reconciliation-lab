"""Literal model-vector fixtures, independent of financial/model calculators."""
from copy import deepcopy
from crypto_reconciliation_lab.triage.contracts import (FEATURE_NAMES, DECIMAL_FEATURES,
    CONTRACT_SHA256, BALANCE_AT, AS_OF, HORIZON_AT, digest)
from crypto_reconciliation_lab.triage.model import PARAMETERS


def values(count=0, age='6', ratio=None):
    result = {name: (None if name in DECIMAL_FEATURES else 0) for name in FEATURE_NAMES}
    result['a_open_count'] = count
    result['observed_age_hours'] = age
    result['a_relative_difference_max'] = ratio
    result['observation_count'] = 2
    result['open_observation_count'] = 2
    return result


def row(index, *, split='train', world='w0', count=0, status='OPEN', age='6', ratio=None):
    episode = 'e' + str(index)
    # Explicit synthetic v1 metadata; the literal model vector is unchanged.
    proof = {'latest_knowledge_at': AS_OF,
             'sources': [{'run_id': 'literal-vector-fixture', 'pointer': '/findings/0',
                          'evidence_pointer': '/findings/0/evidence_ids', 'knowledge_at': AS_OF}]}
    return {'unit_id': episode + '::AX', 'world_id': world, 'episode_id': episode,
        'split': split, 'asset': 'AX', 'balance_at': BALANCE_AT, 'as_of': AS_OF,
        'first_seen_at': '2026-11-10T18:00:00Z' if status == 'OPEN' else None,
        'status': status, 'features': values(count, age, ratio),
        'feature_provenance': {name: deepcopy(proof) for name in FEATURE_NAMES},
        'finding_refs': [{'run_id': 'literal-vector-fixture', 'pointer': '/findings/0',
                          'source_alias': 'synthetic-vector-fixture', 'payload_sha256': '0' * 64,
                          'payload_file': None, 'finding': {'asset': 'AX', 'balance_at': BALANCE_AT,
                          'knowledge_at': AS_OF, 'evidence_ids': []}}]}


def document(rows):
    groups = {}
    for item in rows:
        group = groups.setdefault(item['world_id'], {'world_id': item['world_id'], 'split': item['split'], 'episode_ids': []})
        if item['episode_id'] not in group['episode_ids']:
            group['episode_ids'].append(item['episode_id'])
    splits = {'format': 'triage-split-v1', 'groups': list(groups.values())}
    features = {'format': 'triage-features-v1', 'experiment_format': 'triage-experiment-v1',
        'contract_sha256': CONTRACT_SHA256, 'splits_sha256': digest(splits),
        'feature_names': list(FEATURE_NAMES), 'units': rows}
    return features, splits


def labels(rows, targets):
    return {'format': 'triage-labels-v1', 'target': 'unresolved_at_horizon', 'horizon_hours': 24,
        'units': [{key: item[key] for key in ('unit_id', 'world_id', 'episode_id', 'asset', 'balance_at', 'as_of')} |
                  {'label': target, 'reason': 'literal independent model fixture', 'family': 'literal', 'horizon': HORIZON_AT}
                  for item, target in zip(rows, targets)]}


def literal_model(split_hash='1'*64):
    n = len(FEATURE_NAMES)
    model = {'format': 'triage-model-v1', 'experiment_format': 'triage-experiment-v1',
        'target': 'unresolved_at_horizon', 'horizon_hours': 24, 'feature_names': list(FEATURE_NAMES),
        'contract_sha256': CONTRACT_SHA256, 'splits_sha256': split_hash,
        'training': {'feature_sha256': '2'*64, 'label_sha256': '3'*64,
                     'fit_unit_ids': ['e0::AX', 'e1::AX'], 'fit_world_ids': ['w0'], 'fit_split': 'train'},
        'preprocessing': {'strategy': 'train_median_then_all_missing_indicators_then_standard_scaler',
            'medians': [0.0]*n, 'all_missing': [False]*n, 'missing_indicators': list(FEATURE_NAMES),
            'means': [0.0]*(2*n), 'scales': [1.0]*(2*n)},
        'estimator': {'kind': 'LogisticRegression', 'parameters': deepcopy(PARAMETERS), 'classes': [0,1],
                      'coefficients': [1.0]+[0.0]*(2*n-1), 'intercept': 0.0},
        'versions': {'python': 'fixture', 'scikit-learn': '1.9.1', 'numpy': 'fixture', 'scipy': 'fixture',
                     'joblib': 'fixture', 'threadpoolctl': 'fixture'},
        'score_semantics': 'Synthetic unresolved_at_horizon ranking score; not calibrated financial risk.'}
    return reidentify(model)


def reidentify(model):
    model['model_id'] = digest({key: value for key, value in model.items() if key != 'model_id'})
    return model
