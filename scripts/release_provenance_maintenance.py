"""Build finite TEST-ONLY maintenance controls using the selected package.

This release helper is not a product CLI or an operator trust service. Actual
verify-provenance subprocesses are launched and recorded by verify_release.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys


def identity(path):
    raw = Path(path).read_bytes()
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tests', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Import the chosen package before adding the isolated test-fixture directory.
    # In installed mode neither the project root nor its package is on sys.path.
    import crypto_reconciliation_lab as package
    from crypto_reconciliation_lab.provenance.demo import build_fixture
    from crypto_reconciliation_lab.provenance.exporter import export_provenance
    origin = str(Path(package.__file__).resolve())
    tests = args.tests.resolve()
    sys.path.insert(0, str(tests))
    from test_provenance_causality import encoded, load, material_inventory, promote_later_replay, reseal, write
    from test_provenance_identity_transport import large_identity_fixture, seal_files, unpack
    args.output.mkdir(parents=True, exist_ok=False)
    root = args.output.resolve()
    rotation = build_fixture(root/'rotation-fixture', scenario='rotation')
    positive = root/'rotation'
    positive.mkdir()
    export_provenance(rotation['database'], rotation['run_id'], rotation['material_dir'], positive/'bundle')
    shutil.copyfile(rotation['expectations'], positive/'expectations.json')
    negative = root/'later_replay_promoted'
    shutil.copytree(positive, negative)
    capture = load(negative/'bundle/capture.json')
    promote_later_replay(capture['tables'])
    write(negative/'bundle/capture.json', capture)
    reseal(negative/'bundle', negative/'expectations.json')
    before, after = load(positive/'expectations.json'), load(negative/'expectations.json')
    changed = sorted(key for key in before if before[key] != after[key])
    preservation = {'external_changed_fields': changed,
        'raw_run_equal': (positive/'bundle/run.json').read_bytes() == (negative/'bundle/run.json').read_bytes(),
        'signed_materials_equal': material_inventory(positive/'bundle') == material_inventory(negative/'bundle')}
    if preservation != {'external_changed_fields': ['capture_digest'], 'raw_run_equal': True, 'signed_materials_equal': True}:
        raise ValueError('maintenance F1 mutation exceeds its controlled scope')
    fixture, expected_capture = large_identity_fixture(root/'large-fixture')
    large = root/'large_ids'
    large.mkdir()
    export_provenance(fixture['database'], fixture['run_id'], fixture['material_dir'], large/'bundle')
    shutil.copyfile(fixture['expectations'], large/'expectations.json')
    raw = load(large/'bundle/capture.json')
    if raw != expected_capture:
        raise ValueError('maintenance F2 raw capture changed')
    shown = unpack((large/'bundle/data.js').read_bytes())['capture']['tables']
    boundaries = ('9007199254740991', '9007199254740992', '9007199254740993', '9223372036854775807')
    for table in ('receipts', 'delivery_attempts', 'auth_decisions'):
        if not set(boundaries) <= {row['id'] for row in shown[table]}:
            raise ValueError('maintenance F2 exact identity transport failed: ' + table)
    paths = []
    for wanted in boundaries:
        receipt = next(row for row in shown['receipts'] if row['id'] == wanted)
        effects = [row for row in shown['delivery_effects'] if row['core_receipt_id'] == wanted]
        if len(effects) != 1 or effects[0]['core_receipt_hash'] != receipt['receipt_hash']:
            raise ValueError('maintenance F2 receipt joins are not distinct')
        paths.append({'receipt_id': wanted, 'effect_count': 1, 'receipt_hash': receipt['receipt_hash'],
                      'stream_id': effects[0]['stream_id'], 'sequence': effects[0]['sequence']})
    malformed = root/'tampered_transport'
    shutil.copytree(large, malformed)
    data = unpack((malformed/'bundle/data.js').read_bytes())
    row = next(row for row in data['capture']['tables']['receipts'] if row['id'] == '9007199254740993')
    row['id'] = '9007199254740992'
    (malformed/'bundle/data.js').write_bytes(b'window.PROVENANCE_DATA = JSON.parse(' + encoded(encoded(data).decode('ascii')) + b');\n')
    seal_files(malformed/'bundle')
    if (large/'bundle/capture.json').read_bytes() != (malformed/'bundle/capture.json').read_bytes():
        raise ValueError('maintenance F2 tamper must preserve authoritative capture')
    report = {'format': 'release-provenance-maintenance-v1', 'package_version': package.__version__,
        'environment': {'origin': origin, 'executable': sys.executable, 'isolated': bool(sys.flags.isolated),
                        'cwd': str(Path.cwd()), 'test_fixture_directory': str(tests)},
        'trust_role': 'TEST-ONLY controlled fixture observation', 'f1_preservation': preservation,
        'f2_identity_paths': paths, 'f2_authoritative_capture_unchanged': True,
        'fixtures': {name: {'bundle': str(root/name/'bundle'), 'expectations': str(root/name/'expectations.json'),
                           'manifest': identity(root/name/'bundle/manifest.json')}
                     for name in ('rotation', 'later_replay_promoted', 'large_ids', 'tampered_transport')}}
    (root/'setup.json').write_bytes(encoded(report))
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
