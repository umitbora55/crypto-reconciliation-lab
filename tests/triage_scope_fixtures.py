"""Complete small public scope from independent real saved T fixture payloads.

This is new maintenance-test data, never the frozen main experiment. Its public
smoke-sized roster deliberately uses test/challenge to exercise the pretruth
boundary without calling the horizon evaluator or changing generator assignments.
"""
from copy import deepcopy
from crypto_reconciliation_lab.triage.contracts import AS_OF, BALANCE_AT, HORIZON_AT, digest, load, save
from crypto_reconciliation_lab.triage.features import build_features
from crypto_reconciliation_lab.triage.runner import file_entry
from test_triage_features import public_fixture
from triage_model_fixtures import literal_model


def scope_fixture(root):
    """Own real T payloads, copied into a declared small public test roster.

    The real generator's smoke assignments remain train/validation. This bounded
    synthetic public fixture uses test/challenge to exercise pretruth guards only;
    both are legal split labels and no truth engine is invoked.
    """
    public_fixture(root / 'source')
    original = build_features(root / 'source', root / 'observed')
    source_episode = load(root / 'source/episodes.json')['episodes'][0]
    data = root / 'data'; data.mkdir(); (data / 'truth').mkdir()
    groups, episodes, units, snapshots = [], [], [], []
    for number, split in enumerate(('test', 'challenge')):
        world = 'scope-world-' + str(number)
        ids = ['scope-episode-' + str(number) + '-' + str(slot) for slot in range(4)]
        groups.append({'world_id':world, 'split':split, 'episode_ids':ids})
        for episode_id in ids:
            selection_file = 'episodes/' + episode_id + '/selection.json'
            target = data / selection_file; target.parent.mkdir(parents=True)
            target.write_bytes((root / 'source/selection.json').read_bytes())
            episodes.append({'episode_id':episode_id, 'world_id':world, 'split':split,
                'balance_at':BALANCE_AT, 'as_of':AS_OF,
                'history_run_ids':source_episode['history_run_ids'],
                'current_run_id':source_episode['current_run_id'], 'selection_file':selection_file})
            for old in original['units']:
                row = deepcopy(old)
                row.update(unit_id=episode_id+'::'+row['asset'], episode_id=episode_id,
                           world_id=world, split=split)
                units.append(row)
            for old in original['snapshots']:
                snapshots.append({**old, 'episode_id':episode_id})
    splits = {'format':'triage-split-v1', 'groups':groups}
    features = {**original, 'splits_sha256':digest(splits), 'units':units, 'snapshots':snapshots,
                'inventory':{'units':16, 'episodes':8, 'open':8, 'no_open_finding':8}}
    public = {'format':'triage-episodes-v1', 'experiment_contract':'triage-experiment-v1',
        'design_id':'triage-synthetic-2026-11-v1', 'mode':'smoke',
        'assets':{'ASSET_A':8, 'ASSET_B':2}, 'balance_at':BALANCE_AT, 'as_of':AS_OF,
        'horizon':HORIZON_AT, 'horizon_hours':24, 'episodes':episodes}
    catalog = {'format':'triage-truth-catalog-v1', 'design_id':public['design_id'],
               'mode':'smoke', 'split_hash':digest(splits), 'files':{}}
    for split in ('train','validation','test','challenge'):
        relative = 'truth/' + split + '.json'
        (data / relative).write_bytes(b'PRIVATE H PLAN MUST NEVER BE OPENED BY THIS FIXTURE\n')
        catalog['files'][split] = {'path':relative, **file_entry(data / relative)}
    save(data / 'splits.json', splits); save(data / 'episodes.json', public)
    save(data / 'truth/plan.json', catalog)
    bundle = {'format':'triage-experiment-v1', 'design_id':public['design_id'], 'mode':'smoke',
              'worlds':2, 'episodes':8, 'visible_units':16, 'split_hash':digest(splits),
              'files':{p.relative_to(data).as_posix():file_entry(p) for p in data.rglob('*') if p.is_file()}}
    save(data / 'bundle.json', bundle)
    save(root / 'features.json', features)
    save(root / 'model.json', literal_model(digest(splits)))
    return features, splits

