"""Pinned release test scope; ordinary verification never regenerates expectations."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat

RELEASE = '0.6.1'
BASELINE_PATH = 'contracts/release-tests-baseline-0.6.0.json'
BASELINE_BYTES = 42896
BASELINE_SHA256 = 'd69bb489b06f94643ef9b6def46e0723d0533c08a263c4d0c81ca6ee8bc919e1'
CONTRACT_PATH = 'contracts/release-test-scope-0.6.1.json'
CONTRACT_BYTES = 51611
CONTRACT_SHA256 = 'c8d2e637950658ca71d5f2674d122fedc93c9888c4976af81a6607d5a5f3635f'


def require(condition, message):
    if not condition:
        raise ValueError('TEST_SCOPE: ' + message)


def identity():
    return {'path': CONTRACT_PATH, 'bytes': CONTRACT_BYTES, 'sha256': CONTRACT_SHA256, 'release': RELEASE}


def unique_object(pairs):
    result = {}
    for name, value in pairs:
        require(name not in result, 'duplicate JSON key: ' + name)
        result[name] = value
    return result


def file_bytes(path):
    path = Path(path)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode), 'not a regular file: ' + str(path))
    data = path.read_bytes()
    after = path.lstat()
    signature = lambda row: (row.st_dev, row.st_ino, row.st_mode, row.st_size, row.st_mtime_ns)
    require(signature(before) == signature(after) and len(data) == before.st_size,
            'file changed while reading: ' + str(path))
    return data


def byte_identity(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def checked_document(root, name, size, sha):
    data = file_bytes(root / name)
    require(byte_identity(data) == {'bytes': size, 'sha256': sha}, 'pinned identity differs: ' + name)
    return json.loads(data, object_pairs_hook=unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('TEST_SCOPE: nonfinite JSON')))


def safe_file(name):
    require(type(name) is str and re.fullmatch(r'tests/[A-Za-z0-9_/]+\.py', name) is not None
            and all(part not in ('', '.', '..') for part in name.split('/'))
            and not PurePosixPath(name).is_absolute(), 'unsafe test file path')


def check_files(files):
    require(type(files) is dict and files, 'empty or invalid test file inventory')
    for name, value in files.items():
        safe_file(name)
        require(type(value) is dict and set(value) == {'bytes', 'sha256'}
                and type(value['bytes']) is int and value['bytes'] > 0
                and type(value['sha256']) is str and re.fullmatch('[0-9a-f]{64}', value['sha256']) is not None,
                'invalid file identity: ' + name)


def check_ids(ids, label):
    require(type(ids) is list and ids, label + ' identities missing or empty')
    require(all(type(item) is str and re.fullmatch(r'test[A-Za-z0-9_]*\.[A-Za-z0-9_]+\.test[A-Za-z0-9_]+', item)
                and '_FailedTest' not in item for item in ids), label + ' has invalid/import-error identities')
    require(len(ids) == len(set(ids)), label + ' has duplicate identities')


def load_test_scope(root):
    """Load the independent 0.6.0 anchor and explicitly frozen current roster."""
    root = Path(root).resolve()
    try:
        baseline = checked_document(root, BASELINE_PATH, BASELINE_BYTES, BASELINE_SHA256)
        scope = checked_document(root, CONTRACT_PATH, CONTRACT_BYTES, CONTRACT_SHA256)
        require(baseline['format'] == 'independent-stage6-baseline-test-inventory-v1'
                and baseline['package'] == '0.6.0' and type(baseline['test_count']) is int
                and baseline['test_count'] == 375 and type(baseline['file_count']) is int
                and baseline['file_count'] == 31, 'independent baseline metadata differs')
        check_files(baseline['files']); check_ids(baseline['test_ids'], 'baseline')
        require(len(baseline['files']) == 31 and len(baseline['test_ids']) == 375, 'baseline roster size differs')
        require(scope['format'] == 'release-test-scope-v1' and scope['release'] == RELEASE,
                'current contract format/release differs')
        require(scope['baseline'] == {'path': BASELINE_PATH, 'bytes': BASELINE_BYTES, 'sha256': BASELINE_SHA256},
                'baseline binding differs')
        additions, current = scope['additions'], scope['current']
        check_files(additions['files']); check_files(current['files'])
        check_ids(additions['test_ids'], 'additions'); check_ids(current['test_ids'], 'current')
        require(not set(additions['files']).intersection(baseline['files']), 'addition replaces an old file')
        require(not set(additions['test_ids']).intersection(baseline['test_ids']), 'addition replaces an old identity')
        require(all('tests/' + item.split('.')[0] + '.py' in additions['files'] for item in additions['test_ids']),
                'new identity module not in declared files')
        exceptions = scope['fixture_exceptions']
        require(type(exceptions) is list and len(exceptions) == 1, 'exactly one authorized fixture exception required')
        exception = exceptions[0]
        name = 'tests/test_release_packaging.py'
        require(exception['path'] == name and exception['original'] == baseline['files'][name],
                'fixture original identity differs')
        require(type(exception['old_text']) is str and type(exception['new_text']) is str
                and exception['old_text'] != exception['new_text']
                and '\n' not in exception['old_text'] and '\n' not in exception['new_text'],
                'fixture exception is not a single-line expression')
        expected_files = baseline['files'] | additions['files'] | {name: exception['current']}
        require(current['files'] == expected_files, 'current files do not preserve the independent baseline')
        require(set(current['test_ids']) == set(baseline['test_ids']) | set(additions['test_ids']),
                'current identities do not preserve the independent baseline')
        require(type(current['file_count']) is int and current['file_count'] == len(current['files'])
                and type(current['test_count']) is int and current['test_count'] == len(current['test_ids']),
                'declared current counts differ')
        return scope
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
        if str(error).startswith('TEST_SCOPE:'):
            raise
        raise ValueError('TEST_SCOPE: cannot read required contract: ' + str(error)) from error


def validate_test_files(root, scope=None):
    """Preflight without importing tests or optional AI dependencies (also core-safe)."""
    root = Path(root).resolve()
    # Reload the pin even if a caller supplied a parsed scope, preventing mutation.
    pinned = load_test_scope(root)
    require(scope is None or scope == pinned, 'supplied scope differs from pinned contract')
    scope = pinned
    try:
        folder = root / 'tests'
        require(folder.is_dir() and not folder.is_symlink(), 'test directory missing or unsafe')
        actual = {}
        for path in folder.rglob('*'):
            require(not path.is_symlink(), 'symlink in test source')
            if path.suffix == '.py':
                require(path.is_file(), 'non-file in Python test inventory')
                name = path.relative_to(root).as_posix()
                actual[name] = byte_identity(file_bytes(path))
        expected = scope['current']['files']
        missing, extra = sorted(set(expected)-set(actual)), sorted(set(actual)-set(expected))
        require(not missing and not extra, 'test file inventory differs; missing=' + repr(missing) + '; extra=' + repr(extra))
        changed = sorted(name for name in expected if actual[name] != expected[name])
        require(not changed, 'test file bytes differ: ' + repr(changed))
        exception = scope['fixture_exceptions'][0]
        current = file_bytes(root / exception['path']).decode('utf-8')
        require(current.count(exception['new_text']) == 1, 'authorized fixture expression missing/duplicated')
        original = current.replace(exception['new_text'], exception['old_text'], 1).encode('utf-8')
        require(byte_identity(original) == exception['original'], 'fixture change exceeds the authorized single expression')
        return {'status': 'PASS', 'scope_identity': identity(), 'baseline': scope['baseline'],
                'expected_count': scope['current']['test_count'], 'file_count': len(actual),
                'files': actual, 'expected_ids': scope['current']['test_ids'],
                'fixture_exceptions': scope['fixture_exceptions']}
    except (OSError, UnicodeError) as error:
        raise ValueError('TEST_SCOPE: cannot read test source: ' + str(error)) from error


def validate_discovered_ids(ids, scope):
    check_ids(ids, 'discovered')
    require(set(ids) == set(scope['current']['test_ids']), 'discovered identities differ from declared scope')


def validate_test_result(result, scope):
    # Preserve prior failure/skip/count checks before requiring the new evidence.
    require(type(result) is dict, 'test result must be an object')
    require(all(type(result.get(field, 0)) is int and result.get(field, 0) == 0
                for field in ('skips', 'failures', 'errors', 'unexpected_successes', 'expected_failures')),
            'tests skipped or unsuccessful')
    require(result.get('status') == 'PASS' and type(result.get('discovered')) is int
            and type(result.get('executed')) is int and result['discovered'] > 0
            and result['executed'] == result['discovered'], 'incomplete test discovery/execution')
    require(result['discovered'] == scope['current']['test_count'], 'incomplete declared test coverage')
    require(all(field in result for field in ('skips', 'failures', 'errors', 'unexpected_successes', 'expected_failures')),
            'actual failure/skip counters missing')
    require(result.get('scope_identity') == identity(), 'test result contract identity missing or different')
    discovered, executed = result.get('discovered_ids'), result.get('executed_ids')
    validate_discovered_ids(discovered, scope); check_ids(executed, 'executed')
    require(len(discovered) == result['discovered'] and len(executed) == result['executed'], 'ID evidence/count mismatch')
    require(set(executed) == set(discovered), 'discovered and executed identities differ')
    return {'status': 'PASS', 'scope_identity': identity(), 'expected_count': scope['current']['test_count'],
            'discovered_count': len(discovered), 'executed_count': len(executed), 'each_identity_executed_once': True}
