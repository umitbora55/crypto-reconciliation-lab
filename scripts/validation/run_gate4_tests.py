"""Freeze and execute the exact new Gate 4 research test inventory.

This runner does not run or reclassify the historical 875 application tests.
The external freeze is a byte/scope binding, not an independent trust root.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASE = 'c08114e847b8b0ab58f28d41917ba386878fa873'


def proof(path):
    raw = path.read_bytes()
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def static_ids():
    ids = []
    for path in sorted((ROOT / 'validation_gate4_tests').glob('test_*.py')):
        for node in ast.parse(path.read_bytes()).body:
            if isinstance(node, ast.ClassDef):
                for method in node.body:
                    if isinstance(method, ast.FunctionDef) and method.name.startswith('test_'):
                        ids.append(f'{path.stem}.{node.name}.{method.name}')
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('empty or duplicate static test identities')
    return sorted(ids)


def source_inventory():
    historical = subprocess.check_output(['git', 'ls-tree', '-rz', BASE], cwd=ROOT)
    files = {}
    count = 0
    for entry in historical.split(b'\0'):
        if not entry:
            continue
        metadata, raw_name = entry.split(b'\t', 1)
        mode, kind, blob = metadata.decode().split()
        name = raw_name.decode()
        if kind != 'blob' or mode not in ('100644', '100755'):
            raise ValueError('nonregular historical source')
        expected = subprocess.check_output(['git', 'cat-file', 'blob', blob], cwd=ROOT)
        path = ROOT / name
        if path.is_symlink() or path.read_bytes() != expected:
            raise ValueError('historical source changed: ' + name)
        files[name] = proof(path)
        count += 1
    if count != 445:
        raise ValueError('wrong historical source population')
    for pattern in ('validation_gate4_tests/*.py', 'validation_lab/gate4*.py',
                    'scripts/validation/*gate4*.py', 'contracts/gate4*.json'):
        for path in sorted(ROOT.glob(pattern)):
            if path.is_symlink():
                raise ValueError('nonregular research source')
            files[path.relative_to(ROOT).as_posix()] = proof(path)
    return dict(sorted(files.items()))


def freeze(path):
    if os.path.lexists(path):
        raise ValueError('inventory output exists')
    ids = static_ids()
    record = {'format': 'gate4-test-inventory-v1', 'created_utc': datetime.now(timezone.utc).isoformat(),
              'historical_base': BASE, 'historical_files': 445,
              'expected_ids': ids, 'expected_count': len(ids), 'source_files': source_inventory()}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(record, stream, indent=2)
        stream.write('\n')
    return {'status': 'FROZEN', 'tests': len(ids), 'source_files': len(record['source_files']), **proof(path)}


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item.id()


def validate_inventory(record, actual_ids, actual_sources):
    """Require exact JSON metadata types before comparing identities and bytes.

    Python considers True == 1 and 445.0 == 445; those are not the frozen
    inventory's integer fields. Missing/malformed metadata is an explicit
    rejection, not a partially accepted manifest or an incidental KeyError.
    """
    required = {'format', 'created_utc', 'historical_base', 'historical_files',
                'expected_ids', 'expected_count', 'source_files'}
    if type(record) is not dict or set(record) != required:
        raise ValueError('test/source inventory mismatch: metadata fields')
    expected, sources = record['expected_ids'], record['source_files']
    if (record['format'] != 'gate4-test-inventory-v1'
            or type(record['created_utc']) is not str or not record['created_utc']
            or type(record['expected_count']) is not int
            or type(record['historical_files']) is not int
            or type(expected) is not list or not expected
            or any(type(identity) is not str or not identity for identity in expected)
            or type(sources) is not dict or not sources):
        raise ValueError('test/source inventory mismatch: metadata types')
    for name, binding in sources.items():
        if (type(name) is not str or not name or type(binding) is not dict
                or set(binding) != {'bytes', 'sha256'}
                or type(binding['bytes']) is not int or binding['bytes'] < 0
                or type(binding['sha256']) is not str or len(binding['sha256']) != 64
                or any(character not in '0123456789abcdef' for character in binding['sha256'])):
            raise ValueError('test/source inventory mismatch: source binding types')
    if (expected != actual_ids or len(expected) != len(set(expected))
            or len(expected) != record['expected_count'] or record['historical_base'] != BASE
            or record['historical_files'] != 445 or sources != actual_sources):
        raise ValueError('test/source inventory mismatch')
    return expected


def run(inventory, output):
    raw = inventory.read_bytes()
    record = json.loads(raw)
    expected = validate_inventory(record, static_ids(), source_inventory())
    output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'validation_gate4_tests'))
    discovered = list(flatten(suite))
    if sorted(discovered) != expected or len(discovered) != len(set(discovered)):
        raise ValueError('discovered test identities differ')
    executed, successful, completed = [], [], []

    class Result(unittest.TextTestResult):
        def startTest(self, test):
            executed.append(test.id())
            super().startTest(test)

        def addSuccess(self, test):
            successful.append(test.id())
            super().addSuccess(test)

        def stopTest(self, test):
            completed.append(test.id())
            super().stopTest(test)

    started = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
    counters = {name: len(getattr(result, attr)) for name, attr in {
        'failures': 'failures', 'errors': 'errors', 'skips': 'skipped',
        'expected_failures': 'expectedFailures', 'unexpected_successes': 'unexpectedSuccesses'}.items()}
    unchanged = record['source_files'] == source_inventory()
    passed = (not any(counters.values()) and unchanged and sorted(executed) == expected
              and sorted(successful) == sorted(completed) == expected
              and len(executed) == len(set(executed)) == result.testsRun == len(expected))
    summary = {'status': 'PASS' if passed else 'FAIL', 'python': sys.version,
               'inventory_sha256': hashlib.sha256(raw).hexdigest(), 'source_unchanged': unchanged,
               'scope': 'NEW_GATE4_RESEARCH_ONLY', 'historical_875': 'NOT_RUN_BY_THIS_COMMAND',
               'expected': len(expected), 'discovered': len(discovered), 'executed': result.testsRun,
               'expected_ids': expected, 'discovered_ids': discovered, 'executed_ids': executed,
               'successful_ids': successful, 'completed_ids': completed,
               'counters': counters, 'wall_seconds': time.monotonic() - started}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze', type=Path)
    parser.add_argument('--inventory', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.freeze and not (args.inventory or args.output):
        result = freeze(args.freeze)
    elif args.inventory and args.output and not args.freeze:
        result = run(args.inventory, args.output)
    else:
        parser.error('use --freeze NEW_FILE or --inventory FILE --output NEW_DIR')
    print(json.dumps({key: value for key, value in result.items() if not key.endswith('_ids')}))
    return 0 if result['status'] in ('FROZEN', 'PASS') else 1


if __name__ == '__main__':
    raise SystemExit(main())
