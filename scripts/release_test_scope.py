"""Pinned release test scope; ordinary verification never regenerates expectations."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat

RELEASE = '0.8.0'
ANCHOR_PATH = 'contracts/release-tests-baseline-0.6.0.json'
ANCHOR_BYTES = 42896
ANCHOR_SHA256 = 'd69bb489b06f94643ef9b6def46e0723d0533c08a263c4d0c81ca6ee8bc919e1'
HISTORICAL_PATH = 'contracts/release-test-scope-0.6.1.json'
HISTORICAL_BYTES = 51611
HISTORICAL_SHA256 = 'c8d2e637950658ca71d5f2674d122fedc93c9888c4976af81a6607d5a5f3635f'
STAGE9_PATH = 'contracts/release-test-scope-0.7.0.json'
STAGE9_BYTES = 63100
STAGE9_SHA256 = '0d163bd86cd3ecc8f57cf32c4619f245becd600ae01c8f1f7f752c04bf8dfb4d'
BASELINE_PATH = 'contracts/release-test-scope-0.7.1.json'
BASELINE_BYTES = 64724
BASELINE_SHA256 = '2e21ae9f60ec7163af140d9f8e2eb91f33d3492e6b3edb1b3b4a86430a736a7e'
CONTRACT_PATH = 'contracts/release-test-scope-0.8.0.json'
SEMANTIC_FIXTURE_PATH = 'tests/fixtures/admission-semantic-report-v2.json'
# Frozen only after reviewed additions and explicit metadata fixture exceptions.
CONTRACT_BYTES = 80521
CONTRACT_SHA256 = '7dc06a3a89c2756f1574479cd288cec1bef65fe13925bfa5703a3be829311ec5'


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
    require(type(name) is str and (re.fullmatch(r'tests/[A-Za-z0-9_/]+\.py', name) is not None
            or name == SEMANTIC_FIXTURE_PATH)
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



def named_fixture_block(text):
    """Only the one explicitly authorized top-level report_fixture function."""
    try:
        tree = ast.parse(text)
    except SyntaxError as error:
        raise ValueError('TEST_SCOPE: malformed fixture source') from error
    matches = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'report_fixture']
    require(len(matches) == 1 and not matches[0].decorator_list,
            'authorized report_fixture function missing or duplicated')
    node = matches[0]
    require([a.arg for a in node.args.args] == ['scope'] and not node.args.vararg
            and not node.args.kwarg and not node.args.kwonlyargs and not node.args.posonlyargs
            and not node.args.defaults, 'report_fixture signature changed')
    return ''.join(text.splitlines(keepends=True)[node.lineno-1:node.end_lineno])


def validate_fixture_exception(exception):
    """Metadata lines, or exactly one pinned named-function fixture replacement."""
    edits = exception['changes']
    kind = exception.get('kind', 'metadata-lines-v1')
    if kind == 'report-fixture-function-v1':
        require(exception['path'] == 'tests/test_admission_release.py'
                and exception.get('function') == 'report_fixture' and len(edits) == 1,
                'named fixture exception exceeds report_fixture authorization')
        edit = edits[0]
        require(set(edit) == {'old_text', 'new_text', 'count'} and edit['count'] == 1
                and type(edit['old_text']) is str and type(edit['new_text']) is str
                and edit['old_text'] != edit['new_text'], 'invalid named fixture replacement')
        for label, text in [('original_block', edit['old_text']), ('current_block', edit['new_text'])]:
            require(text == named_fixture_block(text) and len(ast.parse(text).body) == 1,
                    'named fixture replacement includes code outside the authorized function')
            require(exception.get(label) == byte_identity(text.encode('utf-8')),
                    'named fixture block identity differs')
        return
    if kind == 'schema4-history-setup-v1':
        require(exception['path'] == 'tests/test_admission_migrations.py',
                'historical fixture exception has wrong file')
        setup = {'old_text': "        expected = dict(db.execute('SELECT id,payload FROM runs'))\n        migrate_connection(db)\n        db.close()",
                 'new_text': "        expected = dict(db.execute('SELECT id,payload FROM runs'))\n        from source_auth_legacy_fixtures import install_historical_schema4\n        install_historical_schema4(db)\n        db.close()", 'count': 1}
        require(edits[-1] == setup, 'historical setup exceeds fixed authorization')
        # Earlier changes are single-line current-version metadata only.
        validate_fixture_exception({'changes': edits[:-1]})
        return
    require(kind == 'metadata-lines-v1', 'unsupported fixture exception kind')
    for edit in edits:
        require(set(edit) == {'old_text', 'new_text', 'count'}
                and type(edit['old_text']) is str and type(edit['new_text']) is str
                and edit['old_text'] and edit['new_text'] and edit['old_text'] != edit['new_text']
                and '\n' not in edit['old_text'] and '\n' not in edit['new_text']
                and type(edit['count']) is int and edit['count'] > 0,
                'fixture exception must be an explicit single-line metadata replacement')


def restore_fixture_source(data, exception):
    """Reversal proves every byte outside the listed fixture changes is intact."""
    validate_fixture_exception(exception)
    require(byte_identity(data) == exception['current'], 'current fixture file identity differs')
    original = data.decode('utf-8')
    if exception.get('kind') == 'report-fixture-function-v1':
        require(named_fixture_block(original) == exception['changes'][0]['new_text'],
                'actual report_fixture differs from authorized block')
    for edit in reversed(exception['changes']):
        require(original.count(edit['new_text']) == edit['count'],
                'authorized fixture expression missing/duplicated: ' + exception['path'])
        original = original.replace(edit['new_text'], edit['old_text'], edit['count'])
    require(byte_identity(original.encode('utf-8')) == exception['original'],
            'fixture change exceeds authorized expressions: ' + exception['path'])
    return original.encode('utf-8')


def load_test_scope(root):
    """Retain the independent anchor and all 472 prior release identities."""
    root = Path(root).resolve()
    try:
        anchor = checked_document(root, ANCHOR_PATH, ANCHOR_BYTES, ANCHOR_SHA256)
        historical = checked_document(root, HISTORICAL_PATH, HISTORICAL_BYTES, HISTORICAL_SHA256)
        stage9 = checked_document(root, STAGE9_PATH, STAGE9_BYTES, STAGE9_SHA256)
        prior = checked_document(root, BASELINE_PATH, BASELINE_BYTES, BASELINE_SHA256)
        scope = checked_document(root, CONTRACT_PATH, CONTRACT_BYTES, CONTRACT_SHA256)
        require(anchor['format'] == 'independent-stage6-baseline-test-inventory-v1'
                and anchor['package'] == '0.6.0' and anchor['test_count'] == 375
                and anchor['file_count'] == 31, 'independent anchor metadata differs')
        require(historical['format'] == 'release-test-scope-v1' and historical['release'] == '0.6.1'
                and historical['current']['test_count'] == 400 and historical['current']['file_count'] == 34,
                'historical 0.6.1 contract metadata differs')
        require(stage9['format'] == 'release-test-scope-v1' and stage9['release'] == '0.7.0'
                and stage9['current']['test_count'] == 451 and stage9['current']['file_count'] == 38
                and stage9['baseline'] == {'path': HISTORICAL_PATH, 'bytes': HISTORICAL_BYTES,
                                          'sha256': HISTORICAL_SHA256},
                'historical 0.7.0 contract metadata/binding differs')
        require(prior['format'] == 'release-test-scope-v1' and prior['release'] == '0.7.1'
                and prior['current']['test_count'] == 472 and prior['current']['file_count'] == 44
                and prior['baseline'] == {'path': STAGE9_PATH, 'bytes': STAGE9_BYTES, 'sha256': STAGE9_SHA256},
                'historical 0.7.1 contract metadata/binding differs')
        check_files(anchor['files']); check_ids(anchor['test_ids'], 'independent anchor')
        baseline = prior['current']
        check_files(baseline['files']); check_ids(baseline['test_ids'], 'baseline')
        require(len(baseline['files']) == 44 and len(baseline['test_ids']) == 472
                and set(anchor['test_ids']) <= set(historical['current']['test_ids']) <= set(stage9['current']['test_ids']) <= set(baseline['test_ids']),
                'baseline roster differs')
        require(scope['format'] == 'release-test-scope-v1' and scope['release'] == RELEASE,
                'current contract format/release differs')
        require(scope['baseline'] == {'path': BASELINE_PATH, 'bytes': BASELINE_BYTES, 'sha256': BASELINE_SHA256},
                'baseline binding differs')
        require(scope['independent_anchor'] == {'path': ANCHOR_PATH, 'bytes': ANCHOR_BYTES, 'sha256': ANCHOR_SHA256},
                'independent anchor binding differs')
        additions, current = scope['additions'], scope['current']
        check_files(additions['files']); check_files(current['files'])
        check_ids(additions['test_ids'], 'additions'); check_ids(current['test_ids'], 'current')
        require(not set(additions['files']).intersection(baseline['files']), 'addition replaces an old file')
        require(not set(additions['test_ids']).intersection(baseline['test_ids']), 'addition replaces an old identity')
        require(all('tests/' + item.split('.')[0] + '.py' in additions['files'] for item in additions['test_ids']),
                'new identity module not in declared files')
        exceptions = scope['fixture_exceptions']
        require(type(exceptions) is list and exceptions, 'explicit metadata fixture exceptions required')
        amended = {}
        for exception in exceptions:
            name = exception['path']; safe_file(name)
            require(name in baseline['files'] and name not in amended
                    and exception['original'] == baseline['files'][name], 'fixture original identity differs')
            check_files({name: exception['current']})
            edits = exception['changes']
            require(type(edits) is list and edits and type(exception['reason']) is str and exception['reason'],
                    'fixture metadata changes/reason missing')
            validate_fixture_exception(exception)
            amended[name] = exception['current']
        require(current['files'] == baseline['files'] | additions['files'] | amended,
                'current files do not preserve the prior release')
        require(set(current['test_ids']) == set(baseline['test_ids']) | set(additions['test_ids']),
                'current identities do not preserve all 472 old identities')
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
            if path.suffix == '.py' or path.relative_to(root).as_posix() == SEMANTIC_FIXTURE_PATH:
                require(path.is_file(), 'non-file in Python test inventory')
                name = path.relative_to(root).as_posix()
                actual[name] = byte_identity(file_bytes(path))
        expected = scope['current']['files']
        missing, extra = sorted(set(expected)-set(actual)), sorted(set(actual)-set(expected))
        require(not missing and not extra, 'test file inventory differs; missing=' + repr(missing) + '; extra=' + repr(extra))
        changed = sorted(name for name in expected if actual[name] != expected[name])
        require(not changed, 'test file bytes differ: ' + repr(changed))
        for exception in scope['fixture_exceptions']:
            restore_fixture_source(file_bytes(root / exception['path']), exception)
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
