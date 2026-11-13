"""Join truth only after ranking; retain unknown capacity and exact denominators."""
from .model import _label_map

POLICIES = ('fifo', 'rules', 'model')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _counts(ids, chosen, labels):
    values = [labels[uid]['label'] for uid in ids]
    selected = [labels[uid]['label'] for uid in chosen]
    positive = values.count(1)
    negative = values.count(0)
    unknown = values.count(None)
    tp, fp, uncertain = selected.count(1), selected.count(0), selected.count(None)
    n, k = len(ids), len(chosen)
    _require(tp + fp + uncertain == k, 'METRIC_ACCOUNTING: TP+FP+U must equal selected capacity')
    return {'N': n, 'K': k, 'K_over_N': k / n if n else None,
        'known_positive': positive, 'known_negative': negative, 'censored_or_unknown': unknown,
        'TP': tp, 'FP': fp, 'U': uncertain, 'known_positive_found': tp,
        'known_positive_missed': positive - tp,
        'recall_known_at_budget': tp / positive if positive else None,
        'full_recall_at_budget': tp / positive if positive and unknown == 0 else None,
        'precision_labeled_at_budget': tp / (tp + fp) if tp + fp else None,
        'precision_at_budget': tp / k if k and uncertain == 0 else None,
        'precision_bounds': [tp / k, (tp + uncertain) / k] if k else None,
        'top_k_label_coverage': (tp + fp) / k if k else None}


def evaluate_comparison(units, rankings, labels):
    """Evaluate one common-T queue; group tables attribute its existing top K.

    Labels cover the complete visible inventory, including NO_OPEN_FINDING units.
    They do not change eligibility, ranking, capacity, or fill unknown positions.
    """
    _require(isinstance(units, list), 'METRIC_SCHEMA: units list required')
    by_id = {}
    for row in units:
        _require(isinstance(row, dict), 'METRIC_SCHEMA: unit object required')
        uid = row.get('unit_id')
        _require(isinstance(uid, str) and uid and uid not in by_id, 'METRIC_IDENTITY: distinct unit IDs required')
        _require(row.get('status') in ('OPEN', 'NO_OPEN_FINDING'), 'METRIC_ELIGIBILITY: invalid state')
        by_id[uid] = row
    # No label has been inspected when N and K are set.
    open_ids = {uid for uid, row in by_id.items() if row['status'] == 'OPEN'}
    n = len(open_ids)
    k = (n + 4) // 5 if n else 0
    _require(isinstance(rankings, dict) and set(rankings) == set(POLICIES), 'METRIC_POLICIES: exact FIFO/rules/model policies required')
    for policy, order in rankings.items():
        _require(isinstance(order, list) and all(isinstance(uid, str) for uid in order)
                 and len(order) == len(set(order)) and set(order) == open_ids,
                 'METRIC_RANKING: each policy must rank the complete same OPEN roster exactly once')
    label_map = _label_map(labels, units)
    results = {}
    for policy in POLICIES:
        order = rankings[policy]
        selected = order[:k]
        result = _counts(order, selected, label_map)
        _require(result['N'] == n and result['K'] == k, 'METRIC_BUDGET: common capacity changed')
        result['ordered_unit_ids'] = list(order)
        result['selected_unit_ids'] = list(selected)
        groups = {}
        for dimension in ('world_id', 'family', 'asset'):
            buckets = {}
            for uid in order:
                value = label_map[uid]['family'] if dimension == 'family' else by_id[uid][dimension]
                buckets.setdefault(value, []).append(uid)
            groups[dimension] = {}
            for value, ids in sorted(buckets.items()):
                member_ids = set(ids)
                group_selected = [uid for uid in selected if uid in member_ids]
                item = _counts(ids, group_selected, label_map)
                item['selection_scope'] = 'Attribution to the same global top-K; no subgroup reranking or new budget.'
                item['global_N'], item['global_K'] = n, k
                item['selected_unit_ids'] = group_selected
                groups[dimension][value] = item
        result['groups'] = groups
        results[policy] = result
    model, rules, fifo = (results[key]['recall_known_at_budget'] for key in ('model', 'rules', 'fifo'))
    delta_rules = model - rules if model is not None and rules is not None else None
    delta_fifo = model - fifo if model is not None and fifo is not None else None
    conclusion = ('Not assessable: no known positive denominator.' if delta_rules is None else
        'Additional recall over fixed rules was observed in this synthetic experiment only.' if delta_rules > 0 else
        'No additional benefit demonstrated in this synthetic experiment.')
    excluded = [{'unit_id': uid, 'reason': 'NO_OPEN_FINDING', 'label': label_map[uid]['label'],
                 'label_reason': label_map[uid]['reason'], 'world_id': row['world_id'],
                 'episode_id': row['episode_id'], 'asset': row['asset'],
                 'family': label_map[uid]['family']} for uid, row in sorted(by_id.items()) if row['status'] != 'OPEN']
    examples = []
    model_selected = set(rankings['model'][:k])
    rules_selected = set(rankings['rules'][:k])
    for uid in rankings['model']:
        if label_map[uid]['label'] == 1 and uid not in model_selected:
            row = by_id[uid]
            examples.append({'unit_id': uid, 'type': 'known_positive_missed_by_model',
                'selected_by_rules': uid in rules_selected, 'label': 1,
                'family': label_map[uid]['family'], 'asset': row['asset'],
                'finding_refs': row.get('finding_refs', []),
                'explanation_limit': 'Saved evidence links describe observed signals; this ranking miss does not establish a root cause.'})
            if len(examples) == 5:
                break
    return {'format': 'triage-metrics-v1', 'target': 'unresolved_at_horizon', 'horizon_hours': 24,
        'budget_fraction': '0.20', 'inventory_count': len(units), 'open_count': n,
        'excluded_count': len(excluded), 'excluded': excluded,
        'policies': results, 'model_minus_rules_recall_known': delta_rules,
        'model_minus_fifo_recall_known': delta_fifo, 'conclusion': conclusion,
        'misprioritized_examples': examples, 'fallback_count': 0,
        'unknown_policy': 'Unknown labels stay in N and selected capacity. No refill or negative relabeling.',
        'dependency_limit': 'Units from a common world are dependent; no independent-sample confidence claim is made.'}
