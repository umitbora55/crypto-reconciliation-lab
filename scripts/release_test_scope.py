"""Pinned release test scope; ordinary verification never regenerates expectations."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat

RELEASE = '0.11.0'
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
PREVIOUS_PATH = 'contracts/release-test-scope-0.8.0.json'
PREVIOUS_BYTES = 80521
PREVIOUS_SHA256 = '7dc06a3a89c2756f1574479cd288cec1bef65fe13925bfa5703a3be829311ec5'
REVIEWED_PATH = 'contracts/release-test-scope-0.8.1.json'
REVIEWED_BYTES = 88456
REVIEWED_SHA256 = 'eaff707f9241792ee5041dae82821f5dd79589468849d8c7e38155590c7f531a'
ACCEPTED_PATH = 'contracts/release-test-scope-0.8.2.json'
ACCEPTED_BYTES = 93087
ACCEPTED_SHA256 = '2191421a231dff4b560e3c0c6b3469a4f097fe277009a56f1e48ed4a7d7aa592'
PROVENANCE_PATH = 'contracts/release-test-scope-0.9.0.json'
PROVENANCE_BYTES = 111648
PROVENANCE_SHA256 = '111f1975957662efe1f73083be03a608f37b055fcf9b61da51c129da40e5a4f5'
MAINTENANCE_PATH = 'contracts/release-test-scope-0.9.1.json'
MAINTENANCE_BYTES = 123752
MAINTENANCE_SHA256 = '6f67d9217776dfe34a8e2f975cbe58c7e2b39eb4f310b78165973b2aa5d81118'
EXECUTION_PATH = 'contracts/release-test-scope-0.10.0.json'
EXECUTION_BYTES = 186212
EXECUTION_SHA256 = '80ab84b011000db8b710b267e850963ec2da0a15063ee516896f14119d5ef8ec'
EXECUTION_REPAIR_PATH = 'contracts/release-test-scope-0.10.1.json'
EXECUTION_REPAIR_BYTES = 219024
EXECUTION_REPAIR_SHA256 = '2ac30fd8f96a5223b174b899484b72aaad2982c64de6c168b34670c419aa8427'
CONTRACT_PATH = 'contracts/release-test-scope-0.11.0.json'
SEMANTIC_FIXTURE_PATH = 'tests/fixtures/admission-semantic-report-v2.json'
# Frozen only after reviewed additions and explicit metadata fixture exceptions.
CONTRACT_BYTES = 245263
CONTRACT_SHA256 = '3bbd2f2252947c90395f69161849ce790fc183a80f3ecf63075d48b18080cdb1'

# Stage 12 permission is finite: current version/schema metadata and genuine
# historical schema-5 setup only. Every changed old byte is reversibly pinned.
EXECUTION_FIXTURE_PATHS = frozenset({
    'tests/test_corrections.py', 'tests/test_receipt_index.py',
    'tests/test_admission_migrations.py', 'tests/test_source_auth_migrations.py',
    'tests/review_fixtures.py', 'tests/test_provenance_export.py',
    'tests/test_provenance_verifier.py', 'tests/test_release_test_scope.py',
    'tests/test_provenance_maintenance_release.py',
})
SCHEMA5_SETUP_EDITS = {
    'tests/review_fixtures.py': [
        ('def create_source(folder, edge=False):', 'def create_source(folder, edge=False, *, target_schema=None):'),
        ('    store = Store(database, config)', '    store = Store(database, config, target_schema=target_schema)'),
    ],
    'tests/test_provenance_export.py': [
        ("        self.db, self.run_id = create_source(self.root / 'fixture')",
         "        self.db, self.run_id = create_source(self.root / 'fixture', target_schema=5)"),
    ],
    'tests/test_provenance_verifier.py': [
        ('        store = Store(database, CONFIG)', '        store = Store(database, CONFIG, target_schema=5)'),
    ],
}
EXECUTION_METADATA_EDITS = {
    'tests/test_corrections.py': [
        ("        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 5)",
         "        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 6)"),
    ],
    'tests/test_receipt_index.py': [
        ("        self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 5)",
         "        self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 6)"),
        ("        self.assertEqual(db.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall(), [(2,), (3,), (4,), (5,)])",
         "        self.assertEqual(db.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall(), [(2,), (3,), (4,), (5,), (6,)])"),
        ("                    store.db.execute('PRAGMA user_version=6')",
         "                    store.db.execute('PRAGMA user_version=7')"),
    ],
    'tests/test_admission_migrations.py': [
        ("        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 5)",
         "        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 6)"),
        ("        self.assertEqual(db.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall(), [(2,), (3,), (4,), (5,)])",
         "        self.assertEqual(db.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall(), [(2,), (3,), (4,), (5,), (6,)])"),
        ("        self.assertEqual(report['schema_version'], 5)", "        self.assertEqual(report['schema_version'], 6)"),
    ],
    'tests/test_source_auth_migrations.py': [
        ("            self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 5)",
         "            self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 6)"),
        ("            self.assertEqual([r[0] for r in store.db.execute('SELECT version FROM schema_migrations ORDER BY version')], [2, 3, 4, 5])",
         "            self.assertEqual([r[0] for r in store.db.execute('SELECT version FROM schema_migrations ORDER BY version')], [2, 3, 4, 5, 6])"),
    ],
    'tests/test_release_test_scope.py': [
        ("CONTRACT_PATH = 'contracts/release-test-scope-0.9.1.json'", "CONTRACT_PATH = 'contracts/release-test-scope-0.11.0.json'"),
        ("                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.9.1'}",
         "                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.11.0'}"),
    ],
    'tests/test_provenance_maintenance_release.py': [
        ("    setup = {'format': 'release-provenance-maintenance-v1', 'package_version': '0.9.1',",
         "    setup = {'format': 'release-provenance-maintenance-v1', 'package_version': '0.11.0',"),
    ],
}



# Stage12.1 is a separate finite authorization, not a wider schema fixture grant.
EXECUTION_REPAIR_METADATA_EDITS = {
    'tests/test_release_test_scope.py': [
        ("CONTRACT_PATH = 'contracts/release-test-scope-0.10.0.json'", "CONTRACT_PATH = 'contracts/release-test-scope-0.11.0.json'"),
        ("                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.10.0'}",
         "                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.11.0'}"),
    ],
    'tests/test_provenance_maintenance_release.py': [
        ("    setup = {'format': 'release-provenance-maintenance-v1', 'package_version': '0.10.0',",
         "    setup = {'format': 'release-provenance-maintenance-v1', 'package_version': '0.11.0',"),
    ],
}
PROCESS_FIXTURE_PATH = 'tests/test_recorded_execution_release_gate.py'
# Filled once by reviewed release authoring; ordinary validation never regenerates.
PROCESS_FIXTURE_PINS = {'literal_result': {'original': {'bytes': 1305, 'sha256': '1d016c323f3805752553ff9d28a47ab00dccf7e654a4c83f542c5eff4870432e'}, 'current': {'bytes': 1717, 'sha256': 'b85f7b50ff2afba472c99514e842884100547c21659d8c7915414a2de78803c6'}}, 'synthetic_process_evidence': {'original': {'bytes': 4966, 'sha256': 'dcc8db604fee09570ee4a796c3d6619384b28f5bbae6003fb0a68dbbdce812ff'}, 'current': {'bytes': 6199, 'sha256': '56db027c1bc8b6b4f98cfb3aba7bcb688a38215de75c43c61ffee3d38e727067'}}}

# Stage 13 permits exactly these three current metadata expressions. Historical
# links use their original text and the same new endpoint, never caller views.
REPLAY_METADATA_EDITS = {
    'tests/test_release_test_scope.py': [
        ("CONTRACT_PATH = 'contracts/release-test-scope-0.10.1.json'", "CONTRACT_PATH = 'contracts/release-test-scope-0.11.0.json'"),
        ("                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.10.1'}",
         "                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.11.0'}"),
    ],
    'tests/test_provenance_maintenance_release.py': [
        ("    setup = {'format': 'release-provenance-maintenance-v1', 'package_version': '0.10.1',",
         "    setup = {'format': 'release-provenance-maintenance-v1', 'package_version': '0.11.0',"),
    ],
}


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



def validate_process_fixture_exception(exception):
    """Exactly the two pinned setup helpers, never test methods or assertions."""
    require(exception.get('path') == PROCESS_FIXTURE_PATH
            and exception.get('kind') == 'process-transcript-fixture-v1',
            'process fixture exceeds fixed authorization')
    edits = exception.get('changes')
    require(type(edits) is list and len(edits) == 2
            and set(PROCESS_FIXTURE_PINS) == {'literal_result', 'synthetic_process_evidence'},
            'process fixture must contain both pinned helpers')
    seen = set()
    for edit in edits:
        require(set(edit) == {'old_text', 'new_text', 'count'} and edit['count'] == 1,
                'invalid process fixture replacement')
        nodes = []
        for label, text in (('original', edit['old_text']), ('current', edit['new_text'])):
            require(type(text) is str, 'invalid process fixture source')
            tree = ast.parse(text)
            require(len(tree.body) == 1 and isinstance(tree.body[0], ast.FunctionDef)
                    and not tree.body[0].decorator_list, 'process fixture includes surrounding code')
            node = tree.body[0]
            require(node.name in PROCESS_FIXTURE_PINS
                    and text == ''.join(text.splitlines(keepends=True)[node.lineno-1:node.end_lineno]),
                    'process fixture exceeds named helper body')
            require(byte_identity(text.encode('utf-8')) == PROCESS_FIXTURE_PINS[node.name][label],
                    'process fixture block differs from fixed pin')
            nodes.append(node)
        require(nodes[0].name == nodes[1].name and nodes[0].name not in seen
                and ast.dump(nodes[0].args) == ast.dump(nodes[1].args),
                'process fixture identity/signature differs')
        seen.add(nodes[0].name)


def validate_execution_repair_fixture_exception(exception):
    if exception.get('path') == PROCESS_FIXTURE_PATH:
        validate_process_fixture_exception(exception)
        return
    pairs = EXECUTION_REPAIR_METADATA_EDITS.get(exception.get('path'))
    require(pairs is not None and exception.get('kind', 'metadata-lines-v1') == 'metadata-lines-v1'
            and exception.get('changes') == [dict(old_text=a, new_text=b, count=1) for a, b in pairs],
            'execution repair fixture exceeds fixed metadata authorization')
    validate_fixture_exception(exception)


def validate_fixture_exception(exception):
    """Metadata lines, or exactly one pinned named-function fixture replacement."""
    edits = exception['changes']
    kind = exception.get('kind', 'metadata-lines-v1')
    if kind == 'process-transcript-fixture-v1':
        validate_process_fixture_exception(exception)
        return
    if kind == 'schema5-history-setup-v1':
        pairs = SCHEMA5_SETUP_EDITS.get(exception['path'])
        require(pairs is not None and edits == [dict(old_text=old, new_text=new, count=1) for old, new in pairs],
                'historical schema5 setup exceeds fixed authorization')
        return
    if kind == 'provenance-view-schema5-fixture-v1':
        require(exception['path'] == 'tests/test_provenance_verifier.py' and len(edits) == 2,
                'combined view/schema5 fixture exceeds fixed authorization')
        validate_fixture_exception({**exception, 'kind': 'provenance-view-fixture-v1', 'changes': edits[:1]})
        validate_fixture_exception({**exception, 'kind': 'schema5-history-setup-v1', 'changes': edits[1:]})
        return
    if kind == 'provenance-view-fixture-v1':
        require(exception['path'] == 'tests/test_provenance_verifier.py'
                and exception.get('function') == 'refresh' and len(edits) == 1,
                'view fixture exception exceeds refresh authorization')
        edit = edits[0]
        require(set(edit) == {'old_text', 'new_text', 'count'} and edit['count'] == 1
                and type(edit['old_text']) is str and type(edit['new_text']) is str
                and edit['old_text'] != edit['new_text'], 'invalid view fixture replacement')
        functions = []
        for label, text in [('original_block', edit['old_text']), ('current_block', edit['new_text'])]:
            tree = ast.parse(text)
            require(len(tree.body) == 1 and isinstance(tree.body[0], ast.FunctionDef)
                    and tree.body[0].name == 'refresh' and not tree.body[0].decorator_list,
                    'view fixture replacement includes code outside refresh')
            node = tree.body[0]
            require(text == ''.join(text.splitlines(keepends=True)[node.lineno-1:node.end_lineno]),
                    'view fixture replacement includes surrounding text')
            require(exception.get(label) == byte_identity(text.encode('utf-8')),
                    'view fixture block identity differs')
            functions.append(node)
        require(ast.dump(functions[0].args) == ast.dump(functions[1].args), 'view fixture signature changed')
        assertions = lambda node: [ast.dump(item) for item in ast.walk(node) if isinstance(item, ast.Assert)]
        require(assertions(functions[0]) == assertions(functions[1]), 'view fixture behavior assertion changed')
        return
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


def validate_execution_fixture_exception(exception):
    """Authorize only the exact Stage 12 metadata or real-schema-5 setup edits."""
    name = exception['path']
    pairs = (SCHEMA5_SETUP_EDITS | EXECUTION_METADATA_EDITS).get(name)
    require(pairs is not None and exception['changes'] == [
        dict(old_text=old, new_text=new, count=1) for old, new in pairs],
        'execution fixture exceeds fixed metadata/setup authorization')
    validate_fixture_exception(exception)


def validate_replay_fixture_exception(exception):
    """Only the user's two old files and three exact current metadata edits."""
    pairs = REPLAY_METADATA_EDITS.get(exception.get('path'))
    require(pairs is not None and exception.get('kind', 'metadata-lines-v1') == 'metadata-lines-v1'
            and exception.get('changes') == [dict(old_text=a, new_text=b, count=1) for a, b in pairs],
            'replay fixture exceeds fixed metadata authorization')
    validate_fixture_exception(exception)


def load_test_scope(root):
    """Retain every historical anchor, including the accepted 778-ID release."""
    root = Path(root).resolve()
    try:
        anchor = checked_document(root, ANCHOR_PATH, ANCHOR_BYTES, ANCHOR_SHA256)
        historical = checked_document(root, HISTORICAL_PATH, HISTORICAL_BYTES, HISTORICAL_SHA256)
        stage9 = checked_document(root, STAGE9_PATH, STAGE9_BYTES, STAGE9_SHA256)
        prior = checked_document(root, BASELINE_PATH, BASELINE_BYTES, BASELINE_SHA256)
        previous = checked_document(root, PREVIOUS_PATH, PREVIOUS_BYTES, PREVIOUS_SHA256)
        reviewed = checked_document(root, REVIEWED_PATH, REVIEWED_BYTES, REVIEWED_SHA256)
        accepted = checked_document(root, ACCEPTED_PATH, ACCEPTED_BYTES, ACCEPTED_SHA256)
        provenance = checked_document(root, PROVENANCE_PATH, PROVENANCE_BYTES, PROVENANCE_SHA256)
        maintenance = checked_document(root, MAINTENANCE_PATH, MAINTENANCE_BYTES, MAINTENANCE_SHA256)
        execution = checked_document(root, EXECUTION_PATH, EXECUTION_BYTES, EXECUTION_SHA256)
        execution_repair = checked_document(root, EXECUTION_REPAIR_PATH, EXECUTION_REPAIR_BYTES, EXECUTION_REPAIR_SHA256)
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
        # This additional binding does not move the historical 0.7.1 anchor.
        require(previous['format'] == 'release-test-scope-v1' and previous['release'] == '0.8.0'
                and previous['baseline'] == scope['baseline']
                and previous['current']['test_count'] == 540,
                'reviewed previous release metadata differs')
        preserved = scope['previous_release']
        require(type(preserved) is dict and set(preserved) == {'path', 'bytes', 'sha256', 'fixture_exceptions'}
                and {key: preserved[key] for key in ('path', 'bytes', 'sha256')}
                == {'path': PREVIOUS_PATH, 'bytes': PREVIOUS_BYTES, 'sha256': PREVIOUS_SHA256},
                'reviewed previous release binding differs')
        check_files(previous['current']['files']); check_ids(previous['current']['test_ids'], 'previous release')
        require(set(previous['current']['test_ids']) <= set(current['test_ids']),
                'current identities do not preserve all 540 reviewed identities')
        previous_amendments = {}
        require(type(preserved['fixture_exceptions']) is list, 'previous release exceptions must be explicit')
        for exception in preserved['fixture_exceptions']:
            name = exception['path']
            require(name in EXECUTION_FIXTURE_PATHS | {'tests/test_source_auth_release.py'}
                    and name not in previous_amendments
                    and exception['original'] == previous['current']['files'][name],
                    'previous release exception exceeds current metadata authorization')
            validate_fixture_exception(exception)
            previous_amendments[name] = exception['current']
        require(all(current['files'].get(name) == previous_amendments.get(name, proof)
                    for name, proof in previous['current']['files'].items()),
                'previous release test files differ outside metadata exceptions')
        # Preserve the actual 0.8.1 reviewed source without advancing either
        # historical BASELINE (0.7.1) or PREVIOUS (0.8.0) anchor.
        require(reviewed['format'] == 'release-test-scope-v1' and reviewed['release'] == '0.8.1'
                and reviewed['baseline'] == scope['baseline']
                and reviewed['current']['test_count'] == 564,
                'reviewed 0.8.1 release metadata differs')
        binding = scope['reviewed_release']
        require(type(binding) is dict and set(binding) == {'path', 'bytes', 'sha256', 'fixture_exceptions'}
                and {key: binding[key] for key in ('path', 'bytes', 'sha256')}
                == {'path': REVIEWED_PATH, 'bytes': REVIEWED_BYTES, 'sha256': REVIEWED_SHA256},
                'reviewed 0.8.1 release binding differs')
        check_files(reviewed['current']['files']); check_ids(reviewed['current']['test_ids'], 'reviewed 0.8.1 release')
        require(set(reviewed['current']['test_ids']) <= set(current['test_ids']),
                'current identities do not preserve all 564 reviewed identities')
        reviewed_amendments = {}
        require(type(binding['fixture_exceptions']) is list, 'reviewed release exceptions must be explicit')
        for exception in binding['fixture_exceptions']:
            name = exception['path']
            require(name in EXECUTION_FIXTURE_PATHS | {'tests/test_source_auth_release.py'}
                    and name not in reviewed_amendments
                    and exception['original'] == reviewed['current']['files'][name],
                    'reviewed release exception exceeds current metadata authorization')
            validate_fixture_exception(exception)
            reviewed_amendments[name] = exception['current']
        require(all(current['files'].get(name) == reviewed_amendments.get(name, proof)
                    for name, proof in reviewed['current']['files'].items()),
                'reviewed 0.8.1 test files differ outside metadata exceptions')
        # Stage 11 binds the accepted 0.8.2 source independently; every earlier
        # historical anchor and its interpretation remains unchanged.
        require(accepted['format'] == 'release-test-scope-v1' and accepted['release'] == '0.8.2'
                and accepted['baseline'] == scope['baseline']
                and accepted['current']['test_count'] == 575,
                'accepted 0.8.2 release metadata differs')
        binding = scope['accepted_release']
        require(type(binding) is dict and set(binding) == {'path', 'bytes', 'sha256', 'fixture_exceptions'}
                and {key: binding[key] for key in ('path', 'bytes', 'sha256')}
                == {'path': ACCEPTED_PATH, 'bytes': ACCEPTED_BYTES, 'sha256': ACCEPTED_SHA256},
                'accepted 0.8.2 release binding differs')
        check_files(accepted['current']['files']); check_ids(accepted['current']['test_ids'], 'accepted 0.8.2 release')
        require(set(accepted['current']['test_ids']) <= set(current['test_ids']),
                'current identities do not preserve all 575 accepted identities')
        accepted_amendments = {}
        require(type(binding['fixture_exceptions']) is list, 'accepted release exceptions must be explicit')
        for exception in binding['fixture_exceptions']:
            name = exception['path']
            require(name in EXECUTION_FIXTURE_PATHS and name not in accepted_amendments
                    and exception['original'] == accepted['current']['files'][name],
                    'accepted release exception exceeds current metadata authorization')
            validate_fixture_exception(exception)
            accepted_amendments[name] = exception['current']
        require(all(current['files'].get(name) == accepted_amendments.get(name, proof)
                    for name, proof in accepted['current']['files'].items()),
                'accepted 0.8.2 test files differ outside metadata exceptions')
        # Stage 11.1 does not advance or reinterpret any earlier historical pin.
        require(provenance['format'] == 'release-test-scope-v1' and provenance['release'] == '0.9.0'
                and provenance['baseline'] == scope['baseline']
                and provenance['current']['test_count'] == 641,
                'reviewed provenance release metadata differs')
        binding = scope['provenance_release']
        require(type(binding) is dict and set(binding) == {'path', 'bytes', 'sha256', 'fixture_exceptions'}
                and {key: binding[key] for key in ('path', 'bytes', 'sha256')}
                == {'path': PROVENANCE_PATH, 'bytes': PROVENANCE_BYTES, 'sha256': PROVENANCE_SHA256},
                'reviewed provenance release binding differs')
        check_files(provenance['current']['files']); check_ids(provenance['current']['test_ids'], 'reviewed provenance release')
        require(set(provenance['current']['test_ids']) <= set(current['test_ids']),
                'current identities do not preserve all 641 reviewed identities')
        amendments = {}
        require(type(binding['fixture_exceptions']) is list, 'provenance release exceptions must be explicit')
        for exception in binding['fixture_exceptions']:
            name = exception['path']
            require(name in EXECUTION_FIXTURE_PATHS
                    and name not in amendments and exception['original'] == provenance['current']['files'][name],
                    'provenance release exception exceeds fixture authorization')
            required_kind = ('provenance-view-schema5-fixture-v1' if name == 'tests/test_provenance_verifier.py'
                             else 'schema5-history-setup-v1' if name in SCHEMA5_SETUP_EDITS else 'metadata-lines-v1')
            require(exception.get('kind', 'metadata-lines-v1') == required_kind,
                    'provenance fixture exception kind differs')
            validate_fixture_exception(exception)
            amendments[name] = exception['current']
        require(all(current['files'].get(name) == amendments.get(name, proof)
                    for name, proof in provenance['current']['files'].items()),
                'reviewed 0.9.0 test files differ outside authorized fixtures')
        require(maintenance['format'] == 'release-test-scope-v1' and maintenance['release'] == '0.9.1'
                and maintenance['baseline'] == scope['baseline'] and maintenance['current']['test_count'] == 661,
                'accepted 0.9.1 release metadata differs')
        binding = scope['maintenance_release']
        require(type(binding) is dict and set(binding) == {'path', 'bytes', 'sha256', 'fixture_exceptions'}
                and {key: binding[key] for key in ('path', 'bytes', 'sha256')}
                == {'path': MAINTENANCE_PATH, 'bytes': MAINTENANCE_BYTES, 'sha256': MAINTENANCE_SHA256},
                'accepted 0.9.1 release binding differs')
        check_files(maintenance['current']['files']); check_ids(maintenance['current']['test_ids'], 'accepted 0.9.1 release')
        require(set(maintenance['current']['test_ids']) <= set(current['test_ids']),
                'current identities do not preserve all 661 accepted identities')
        amendments = {}
        require(type(binding['fixture_exceptions']) is list, 'execution release exceptions must be explicit')
        for exception in binding['fixture_exceptions']:
            name = exception['path']
            require(name in EXECUTION_FIXTURE_PATHS and name not in amendments
                    and exception['original'] == maintenance['current']['files'][name],
                    'execution release exception exceeds fixture authorization')
            required_kind = 'schema5-history-setup-v1' if name in SCHEMA5_SETUP_EDITS else 'metadata-lines-v1'
            require(exception.get('kind', 'metadata-lines-v1') == required_kind, 'execution fixture kind differs')
            validate_execution_fixture_exception(exception)
            amendments[name] = exception['current']
        require(all(current['files'].get(name) == amendments.get(name, proof)
                    for name, proof in maintenance['current']['files'].items()),
                'accepted 0.9.1 files differ outside authorized fixtures')
        require(execution['format'] == 'release-test-scope-v1' and execution['release'] == '0.10.0'
                and execution['baseline'] == scope['baseline']
                and execution['current']['test_count'] == 729 and execution['current']['file_count'] == 70,
                'reviewed execution release metadata differs')
        binding = scope['execution_release']
        require(type(binding) is dict and set(binding) == {'path', 'bytes', 'sha256', 'fixture_exceptions'}
                and {key: binding[key] for key in ('path', 'bytes', 'sha256')}
                == {'path': EXECUTION_PATH, 'bytes': EXECUTION_BYTES, 'sha256': EXECUTION_SHA256},
                'reviewed execution release binding differs')
        check_files(execution['current']['files']); check_ids(execution['current']['test_ids'], 'reviewed execution release')
        require(set(execution['current']['test_ids']) <= set(current['test_ids']),
                'current identities do not preserve all 729 reviewed identities')
        amendments = {}
        require(type(binding['fixture_exceptions']) is list, 'execution repair exceptions must be explicit')
        for exception in binding['fixture_exceptions']:
            name = exception['path']
            require(name not in amendments and name in execution['current']['files']
                    and exception['original'] == execution['current']['files'][name],
                    'execution repair original identity differs')
            validate_execution_repair_fixture_exception(exception)
            amendments[name] = exception['current']
        require(set(amendments) == set(EXECUTION_REPAIR_METADATA_EDITS) | {PROCESS_FIXTURE_PATH},
                'execution repair fixture inventory differs')
        require(all(current['files'].get(name) == amendments.get(name, proof)
                    for name, proof in execution['current']['files'].items()),
                'reviewed 0.10.0 files differ outside authorized fixtures')
        require(execution_repair['format'] == 'release-test-scope-v1' and execution_repair['release'] == '0.10.1'
                and execution_repair['baseline'] == scope['baseline']
                and execution_repair['current']['test_count'] == 778
                and execution_repair['current']['file_count'] == 78,
                'accepted execution repair release metadata differs')
        binding = scope['execution_repair_release']
        require(type(binding) is dict and set(binding) == {'path', 'bytes', 'sha256', 'fixture_exceptions'}
                and {key: binding[key] for key in ('path', 'bytes', 'sha256')}
                == {'path': EXECUTION_REPAIR_PATH, 'bytes': EXECUTION_REPAIR_BYTES, 'sha256': EXECUTION_REPAIR_SHA256},
                'accepted execution repair release binding differs')
        check_files(execution_repair['current']['files']); check_ids(execution_repair['current']['test_ids'], 'accepted execution repair release')
        require(set(execution_repair['current']['test_ids']) <= set(current['test_ids']),
                'current identities do not preserve all 778 accepted identities')
        amendments = {}
        require(type(binding['fixture_exceptions']) is list, 'replay metadata exceptions must be explicit')
        for exception in binding['fixture_exceptions']:
            name = exception['path']
            require(name not in amendments and name in execution_repair['current']['files']
                    and exception['original'] == execution_repair['current']['files'][name],
                    'replay original file identity differs')
            validate_replay_fixture_exception(exception)
            amendments[name] = exception['current']
        require(set(amendments) == set(REPLAY_METADATA_EDITS), 'replay metadata fixture inventory differs')
        require(all(current['files'].get(name) == amendments.get(name, proof)
                    for name, proof in execution_repair['current']['files'].items()),
                'accepted 0.10.1 files differ outside authorized metadata')
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
        for exception in scope['previous_release']['fixture_exceptions']:
            restore_fixture_source(file_bytes(root / exception['path']), exception)
        for exception in scope['reviewed_release']['fixture_exceptions']:
            restore_fixture_source(file_bytes(root / exception['path']), exception)
        for exception in scope['accepted_release']['fixture_exceptions']:
            restore_fixture_source(file_bytes(root / exception['path']), exception)
        for exception in scope['provenance_release']['fixture_exceptions']:
            restore_fixture_source(file_bytes(root / exception['path']), exception)
        for exception in scope['maintenance_release']['fixture_exceptions']:
            restore_fixture_source(file_bytes(root / exception['path']), exception)
        for exception in scope['execution_release']['fixture_exceptions']:
            restore_fixture_source(file_bytes(root / exception['path']), exception)
        for exception in scope['execution_repair_release']['fixture_exceptions']:
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
