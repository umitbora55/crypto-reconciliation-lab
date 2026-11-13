"""Frozen financial-reference identity and mandatory release parity scopes.

This binds the reviewed 0.5.1 reference against accidental scope changes. It is
not a third-party signature or an authenticity guarantee against hostile code.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat

REFERENCE_PATH = 'docs/stage6/financial-reference.json'
REFERENCE_BYTES = 70721
REFERENCE_SHA256 = '4abda380a19acd4cdfed97a46b6fb15528f32b8ef308c6931815c5b03641275e'
# Independently recorded once from the reviewed immutable reference; never
# generated from the candidate at build or verification time.
DOCUMENT_SHA256 = 'b7329cb6c0b0cc95afe00de012f3f52e81cb2333a5ba0d17dba4bb65272d425d'
GROUP_COUNTS = {'matrix': 325, 'stage1': 12, 'stage2': 36}
# Producer configuration and demo summaries are not saved financial reports.
# Their explicit names do not enlarge or replace the mandatory parity inventory.
ANCILLARY_FILES = {
    'matrix': frozenset({'correctness.json', 'correctness.md'}),
    'stage1': frozenset({'summary.json', 'summary.md',
        *(name + '/config.json' for name in
          ('clean', 'corrected_report', 'custody_difference', 'late_event'))}),
    'stage2': frozenset({'summary.json', 'summary.md',
        *(name + '/config.json' for name in ('correction_before_target', 'deposit_amount_correction',
          'duplicate_and_conflicting_corrections', 'void_deposit', 'void_internal_transfer'))}),
}
ZERO_COUNTERS = ('clean_false_mismatch', 'false_definitive', 'healthy_scope_block',
                 'missed_mismatch', 'missing_evidence', 'missing_reason', 'structural_error',
                 'unnecessary_not_evaluated', 'wrong_amount', 'wrong_state')


def require(condition, message):
    if not condition:
        raise ValueError('FINANCIAL_REFERENCE: ' + message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('utf-8')


def reference_identity():
    return {'format': 'financial-reference-v1', 'path': REFERENCE_PATH,
            'bytes': REFERENCE_BYTES, 'sha256': REFERENCE_SHA256,
            'canonical_document_sha256': DOCUMENT_SHA256, 'baseline_version': '0.5.1',
            'rule_version': 'stage2-v2', 'schema_version': 3,
            'group_counts': dict(GROUP_COUNTS), 'file_count': 373}


def safe_name(name):
    return (type(name) is str and bool(name) and '\\' not in name
            and not any(ord(char) < 32 for char in name)
            and not PurePosixPath(name).is_absolute() and not re.match(r'^[A-Za-z]:', name)
            and all(part not in ('', '.', '..') for part in name.split('/')))


def file_proof(proof):
    return (type(proof) is dict and set(proof) == {'bytes', 'sha256'}
            and type(proof['bytes']) is int and proof['bytes'] > 0
            and type(proof['sha256']) is str
            and re.fullmatch(r'[0-9a-f]{64}', proof['sha256']) is not None)


def validate_reference_document(reference):
    require(type(reference) is dict, 'reference must be a JSON object')
    require(set(reference) == {'demo_evaluations', 'file_count', 'format', 'matrix', 'producer_record',
                               'reports', 'rule_version', 'schema_version', 'source_fingerprint',
                               'verification', 'version'}, 'unexpected or missing reference fields')
    require(reference['format'] == 'financial-reference-v1' and reference['version'] == '0.5.1'
            and reference['rule_version'] == 'stage2-v2', 'unsupported baseline format/version/rule')
    require(type(reference['schema_version']) is int and reference['schema_version'] == 3,
            'schema must be integer 3')
    require(type(reference['file_count']) is int and reference['file_count'] == 373,
            'total must be integer 373')
    demos = reference['demo_evaluations']
    require(type(demos) is dict and set(demos) == {'stage1', 'stage2'}
            and all(type(demos[k]) is int and demos[k] == v for k, v in {'stage1': 6, 'stage2': 18}.items()),
            'demo evaluation scope differs')
    matrix = reference['matrix']
    require(type(matrix) is dict and set(matrix) == {'cases', 'evaluations', 'events', 'investors', 'seeds', 'zero_counters'},
            'matrix fields differ')
    require(all(type(matrix[k]) is int and matrix[k] == value for k, value in
                {'cases': 69, 'evaluations': 162, 'events': 100, 'investors': 6}.items()), 'matrix settings differ')
    require(type(matrix['seeds']) is list and all(type(v) is int for v in matrix['seeds'])
            and matrix['seeds'] == [11, 29, 47], 'matrix seeds differ')
    require(type(matrix['zero_counters']) is list and matrix['zero_counters'] == list(ZERO_COUNTERS),
            'matrix named counters differ')
    require(file_proof(reference['producer_record']), 'invalid producer proof')
    require(type(reference['source_fingerprint']) is str
            and re.fullmatch(r'[0-9a-f]{64}', reference['source_fingerprint']) is not None,
            'invalid source fingerprint')
    require(type(reference['verification']) is str and bool(reference['verification']), 'invalid verification note')
    reports = reference['reports']
    require(type(reports) is dict and set(reports) == set(GROUP_COUNTS), 'required report groups differ')
    for group, count in GROUP_COUNTS.items():
        scope = reports[group]
        require(type(scope) is dict and set(scope) == {'files', 'status', 'full_bytes_and_run_ids_equal'},
                group + ': invalid scope fields')
        require(scope['status'] == 'PASS' and scope['full_bytes_and_run_ids_equal'] is True,
                group + ': unsupported baseline parity status')
        files = scope['files']
        require(type(files) is dict and len(files) == count, group + ': required file count differs')
        for name, proof in files.items():
            require(safe_name(name) and PurePosixPath(name).suffix in ('.json', '.md'),
                    group + ': unsafe or unsupported report name')
            require(file_proof(proof), group + ': invalid file hash/size')
    # This fixed external digest binds every actual name, hash and size, including
    # same-count substitutions and group exchanges, not merely the totals above.
    require(hashlib.sha256(canonical(reference)).hexdigest() == DOCUMENT_SHA256,
            'complete reviewed document inventory differs')
    return reference


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def regular_digest(path):
    path = Path(path)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode), 'regular file required: ' + str(path))
    digest = hashlib.sha256()
    total = 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            total += len(block)
            digest.update(block)
    after = path.lstat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns)
    require(identity(before) == identity(after) and total == before.st_size, 'file changed while hashing')
    return {'bytes': total, 'sha256': digest.hexdigest()}


def load_financial_reference(path):
    path = Path(path)
    try:
        require(path.lstat().st_size == REFERENCE_BYTES, 'reviewed reference byte count differs')
        require(regular_digest(path) == {'bytes': REFERENCE_BYTES, 'sha256': REFERENCE_SHA256},
                'reviewed reference byte identity differs')
        data = path.read_bytes()
        require(len(data) == REFERENCE_BYTES and hashlib.sha256(data).hexdigest() == REFERENCE_SHA256,
                'reference changed after identity check')
        reference = json.loads(data, object_pairs_hook=unique_object,
                               parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON: ' + value)))
        return validate_reference_document(reference)
    except (OSError, UnicodeError, ValueError) as error:
        if str(error).startswith('FINANCIAL_REFERENCE:'):
            raise
        raise ValueError('FINANCIAL_REFERENCE: cannot read reviewed reference: ' + str(error)) from error


def compare_required_reports(directory, reference, group):
    validate_reference_document(reference)
    require(type(group) is str and group in GROUP_COUNTS, 'unknown required comparison group')
    directory = Path(directory)
    require(directory.is_dir() and not directory.is_symlink(), 'missing or unsafe report directory')
    expected = reference['reports'][group]['files']
    actual_names = set()
    for path in directory.rglob('*'):
        require(not path.is_symlink(), 'symlink in report scope')
        if path.is_file() and path.suffix in ('.json', '.md'):
            actual_names.add(path.relative_to(directory).as_posix())
    ancillary = actual_names & ANCILLARY_FILES[group]
    require(actual_names - ancillary == set(expected), group + ': actual report file inventory differs')
    checked = {}
    for name in sorted(expected):
        path = directory / name
        require(path.resolve().is_relative_to(directory.resolve()), 'report escapes its scope')
        try:
            actual = regular_digest(path)
        except OSError as error:
            raise ValueError('FINANCIAL_REFERENCE: missing report: ' + name) from error
        require(actual == expected[name], 'financial report changed: ' + name)
        checked[name] = actual
    require(len(checked) == GROUP_COUNTS[group] and set(checked) == set(expected),
            group + ': incomplete actual comparison')
    return {'status': 'PASS', 'count': len(checked), 'expected_count': GROUP_COUNTS[group],
            'compared_count': len(checked), 'files': checked, 'full_bytes_and_run_ids_equal': True,
            'excluded_producer_ancillary_files': sorted(ancillary),
            'scope': {'format': 'release-financial-scope-v1', 'group': group,
                      'inventory_sha256': hashlib.sha256(canonical(expected)).hexdigest()},
            'reference_identity': reference_identity()}


def validate_matrix_result(result):
    require(type(result) is dict and result.get('status') == 'PASS'
            and type(result.get('evaluations')) is int and result['evaluations'] == 162,
            'matrix result status/evaluations differ')
    counters = result.get('counters')
    require(type(counters) is dict and set(counters) == set(ZERO_COUNTERS)
            and all(type(value) is int and value == 0 for value in counters.values()),
            'matrix must report the ten named integer-zero counters')
