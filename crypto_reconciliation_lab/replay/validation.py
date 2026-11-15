"""Pure portable validation of two bound recorded-execution byte strings."""
from dataclasses import dataclass
import math
import re

from ..execution import capture
from ..execution.common import (FORMAT, PROFILE, MAX_REQUEST_BYTES, MAX_RUN_BYTES,
                                ExecutionError, binding, canonical, is_digest, sha256)
from ..model import config_validate, digest, timestamp
from ..review.validation import strict_json, validate_payload
from .common import MAX_DEPTH, MAX_NODES, ReplayError, require


@dataclass(frozen=True)
class ValidatedReplay:
    context: dict
    saved_payload: dict
    identity: dict
    input_data: dict


CONTEXT_FIELDS = frozenset({
    'format', 'schema_version', 'request_id', 'request', 'request_fingerprint',
    'configuration', 'run_id', 'run_payload_sha256', 'scope', 'binary_encoding',
    'tables', 'selected_evidence', 'counts', 'observed_policy_head',
    'acceptance_epochs', 'claims',
})
REQUEST_FIELDS = frozenset({'format', 'db_scope', 'balance_at', 'knowledge_at',
                            'configuration_digest', 'rule_version', 'profile'})
INTEGER_COLUMNS = {
    'receipts': {'id'},
    'admission_streams': {'input_bytes', 'planned_lines'},
    'delivery_effects': {'sequence', 'core_receipt_id'},
    'delivery_attempts': {'id', 'sequence', 'effect_sequence'},
    'auth_configuration': {'id'},
    'auth_policy_activations': {'epoch', 'previous_epoch'},
    'auth_keys': {'first_epoch'},
    'auth_decisions': {'id', 'epoch', 'sequence'},
    'auth_delivery_links': {'sequence', 'decision_id', 'core_receipt_id'},
    'auth_attempt_links': {'attempt_id', 'decision_id'},
}
NULLABLE_COLUMNS = {
    'receipts': {'record_id', 'received_at', 'error'},
    'delivery_effects': {'core_receipt_id', 'core_receipt_hash', 'core_result', 'reason'},
    'delivery_attempts': {'effect_stream_id', 'effect_sequence', 'reason'},
    'auth_policy_activations': {'previous_epoch', 'previous_hash'},
    'auth_delivery_links': {'core_receipt_id'},
}
SQLITE_MAX_INTEGER = 2**63 - 1


def _depth_before_parse(text):
    """Bound nesting before the standard JSON decoder allocates containers."""
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '[{':
            depth += 1
            require(depth <= MAX_DEPTH, 'JSON nesting limit exceeded', 'REPLAY_LIMIT')
        elif char in ']}':
            depth -= 1


def _json(raw, budget):
    text = raw.decode('utf-8')
    _depth_before_parse(text)
    value = strict_json(text)
    # Iterator frames avoid constructing a second breadth-sized list of nodes.
    stack = [iter((value,))]
    while stack:
        try:
            item = next(stack[-1])
        except StopIteration:
            stack.pop()
            continue
        budget[0] += 1
        require(budget[0] <= MAX_NODES, 'aggregate JSON node limit exceeded', 'REPLAY_LIMIT')
        if type(item) is dict:
            budget[0] += len(item)  # Object keys count as nodes too.
            require(budget[0] <= MAX_NODES, 'aggregate JSON node limit exceeded', 'REPLAY_LIMIT')
            stack.append(iter(item.values()))
        elif type(item) is list:
            stack.append(iter(item))
        elif type(item) is float:
            require(math.isfinite(item), 'nonfinite JSON number')
    return value, text


def _positive_integer(value, label):
    require(type(value) is int and 0 < value <= SQLITE_MAX_INTEGER,
            label + ' must be a positive SQLite integer')


def _inventory_types(tables):
    """Check actual lists/columns/types before the existing inventory resolver."""
    require(type(tables) is dict and set(tables) == set(capture.COLUMNS), 'incomplete table inventory')
    require(all(type(rows) is list for rows in tables.values()), 'table inventory must be a list')
    require(sum(map(len, tables.values())) <= capture.MAX_ROWS
            and len(tables['receipts']) <= capture.MAX_RECEIPTS
            and len(tables['auth_policy_activations']) <= capture.MAX_EPOCHS,
            'captured row limit exceeded', 'REPLAY_LIMIT')
    for table, rows in tables.items():
        columns = set(capture.COLUMNS[table].split())
        for row in rows:
            require(type(row) is dict and set(row) == columns, 'SQL row field coverage differs: ' + table)
            for column, value in row.items():
                label = table + '.' + column
                if value is None:
                    require(column in NULLABLE_COLUMNS.get(table, ()), 'unexpected NULL: ' + label)
                elif column in INTEGER_COLUMNS.get(table, ()):
                    _positive_integer(value, label)
                else:
                    require(type(value) is str, 'SQL TEXT/BLOB transport must be text: ' + label)
                    if column in capture.BLOBS.get(table, ()):
                        require(len(value) <= 2*capture.MAX_VALUE_BYTES, 'SQL BLOB limit exceeded', 'REPLAY_LIMIT')
                        require(re.fullmatch(r'(?:[0-9a-f]{2})*', value) is not None, 'noncanonical BLOB encoding')
                    else:
                        require(len(value.encode('utf-8')) <= capture.MAX_VALUE_BYTES,
                                'SQL TEXT limit exceeded', 'REPLAY_LIMIT')
    # These are declared SQL unique constraints, separate from the table PKs.
    for table, column in (('delivery_effects', 'core_receipt_id'),
                          ('auth_delivery_links', 'decision_id'), ('auth_keys', 'fingerprint')):
        values = [row[column] for row in tables[table] if row[column] is not None]
        require(len(values) == len(set(values)), 'duplicate unique SQL identity: ' + table + '.' + column)


def _declared_references(tables):
    """Captured reference closure; no signatures, policy replay or invented prefix."""
    epochs = {r['epoch'] for r in tables['auth_policy_activations']}
    require(all(r['first_epoch'] in epochs for r in tables['auth_keys']), 'key first epoch is absent')
    effects = {(r['stream_id'], r['sequence']) for r in tables['delivery_effects']}
    for row in tables['delivery_attempts']:
        linked = row['effect_stream_id'], row['effect_sequence']
        require((linked == (None, None)) or (None not in linked and linked in effects),
                'attempt effect reference is incomplete or missing')
        require(linked == (None, None) or linked == (row['stream_id'], row['sequence']),
                'attempt effect refers to another position')
    attempts = {row['id']: row for row in tables['delivery_attempts']}
    decisions = {row['id']: row for row in tables['auth_decisions']}
    # Existing inventory validation has already established both link targets.
    for link in tables['auth_attempt_links']:
        attempt = attempts[link['attempt_id']]
        decision = decisions[link['decision_id']]
        require((attempt['stream_id'], attempt['sequence'])
                == (decision['stream_id'], decision['sequence']),
                'auth decision and linked attempt refer to different positions')


def _declared_domains(tables):
    """Existing SQL CHECK domains, without restoring tables or stream prefixes."""
    for row in tables['auth_configuration']:
        require(row['id'] == 1, 'protected configuration singleton identity differs')
    streams = {row['stream_id']: row for row in tables['admission_streams']}
    for row in streams.values():
        require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', row['stream_id']) is not None,
                'invalid admission stream identity')
        require(1 <= row['input_bytes'] <= 16*1024*1024
                and 1 <= row['planned_lines'] <= 10000, 'admission stream size/line domain differs')
        require(is_digest(row['input_sha256']) and is_digest(row['plan_hash'])
                and row['framing'] == 'utf8-lf-jsonl-v1', 'admission stream identity/framing differs')
        require(1 <= len(row['observed_at']) <= 64, 'admission observation TEXT domain differs')
    outcomes = {'COMMITTED', 'REPLAY', 'TRANSPORT_CONFLICT', 'PLAN_CONFLICT',
                'BLOCKED', 'GAP', 'OUT_OF_RANGE'}
    for table in ('delivery_effects', 'delivery_attempts'):
        for row in tables[table]:
            require(1 <= row['sequence'] <= 10000 and 2 <= len(row['payload']) <= 2*65536,
                    'delivery sequence/payload domain differs')
            require(1 <= len(row['observed_at']) <= 64, 'delivery observation TEXT domain differs')
            if table == 'delivery_effects':
                require(row['stream_id'] in streams
                        and row['sequence'] <= streams[row['stream_id']]['planned_lines'],
                        'delivery effect exceeds its declared stream')
                require(row['disposition'] in {'ACCEPTED', 'DUPLICATE', 'CONFLICT', 'INVALID', 'REJECTED_FRAME'},
                        'unknown delivery disposition')
                require(row['core_result'] is not None and len(row['core_result']) > 1,
                        'captured receipt effect requires its core result')
            else:
                require(row['outcome'] in outcomes, 'unknown delivery attempt outcome')
                require(is_digest(row['plan_hash']), 'invalid attempt plan identity')
                if row['outcome'] in {'GAP', 'OUT_OF_RANGE'}:
                    require(row['effect_stream_id'] is None and row['effect_sequence'] is None,
                            'uncommitted position has an effect reference')


def _selected_types(selected):
    require(type(selected) is dict, 'selected evidence mapping must be an object')
    for key, entry in selected.items():
        require(type(key) is str and type(entry) is dict
                and set(entry) == {'record_ids', 'receipt_ids'}, 'selected evidence fields differ')
        require(type(entry['record_ids']) is list and all(type(v) is str for v in entry['record_ids'])
                and type(entry['receipt_ids']) is list, 'selected evidence identity list differs')
        for value in entry['receipt_ids']:
            _positive_integer(value, 'selected receipt identity')


def _evidence_cardinality(tables, saved, selected):
    """Check real candidate cardinalities before the legacy mapping expands them."""
    evidence = saved['evidence']
    require(set(selected) == set(evidence), 'selected evidence key coverage differs')
    hash_counts, record_hashes = {}, {}
    for row in tables['receipts']:
        receipt_hash = row['receipt_hash']
        hash_counts[receipt_hash] = hash_counts.get(receipt_hash, 0) + 1
        record_hashes.setdefault(row['record_id'], set()).add(receipt_hash)
    for key, entry in evidence.items():
        if 'record' in entry:
            hashes = entry['receipt_ids']
            require(len(hashes) == len(set(hashes)), 'record evidence repeats a receipt hash')
        elif 'derived_correction_group' in entry:
            group = entry['derived_correction_group']
            hashes = (record_hashes.get(group['correction_record_id'], set())
                      | record_hashes.get(group['target_record_id'], set()))
        else:
            hashes = (key,)
        require(all(value in hash_counts for value in hashes), 'selected receipt is outside captured inputs')
        actual_count = sum(hash_counts[value] for value in hashes)
        require(actual_count == len(selected[key]['receipt_ids']),
                'selected physical candidate cardinality differs')


def _financial_cardinality(saved):
    """Reject false small scopes before review's Cartesian key-set allocation."""
    require(type(saved) is dict and type(saved.get('configuration')) is dict,
            'saved financial configuration required')
    config = saved['configuration']
    require(type(config.get('assets')) is dict and type(config.get('investors')) is list
            and type(saved.get('findings')) is list and type(saved.get('ledgers')) is dict,
            'saved financial scope types differ')
    expected = len(config['assets']) * (len(config['investors']) + 1)
    require(len(saved['findings']) == expected, 'finding cardinality differs from asset/investor scope')
    require(len(saved['ledgers']) == len(config['assets']), 'ledger cardinality differs from assets')


def validate_inputs(raw_context, raw_run, expected_execution_id):
    """Validate the exact bytes; never read a DB or calculate financial answers."""
    try:
        require(is_digest(expected_execution_id), 'external execution digest required', 'REPLAY_INPUT')
        require(type(raw_context) is bytes and 0 < len(raw_context) <= capture.MAX_CONTEXT_BYTES
                and type(raw_run) is bytes and 0 < len(raw_run) <= MAX_RUN_BYTES,
                'authoritative input byte limit', 'REPLAY_LIMIT')
        require(len(raw_context) + len(raw_run) <= 32*1024*1024,
                'combined input byte limit', 'REPLAY_LIMIT')
        budget = [0]
        context, _ = _json(raw_context, budget)
        saved, run_text = _json(raw_run, budget)
        require(type(context) is dict and set(context) == CONTEXT_FIELDS, 'context field coverage differs')
        require(context['format'] == FORMAT and type(context['schema_version']) is int
                and context['schema_version'] == 6 and context['binary_encoding'] == 'hex',
                'unsupported context format/schema/encoding', 'REPLAY_UNSUPPORTED')
        require(type(context['request_id']) is str
                and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', context['request_id']) is not None,
                'invalid request identity')
        request = context['request']
        require(type(request) is dict and set(request) == REQUEST_FIELDS
                and all(type(v) is str for v in request.values()), 'request fields/types differ')
        require(request['format'] == FORMAT and request['profile'] == PROFILE
                and request['rule_version'] == 'stage2-v2' and request['db_scope'] == 'local-request-registry',
                'unsupported request format/profile/rule/scope', 'REPLAY_UNSUPPORTED')
        config = config_validate(context['configuration'])
        require(context['configuration'] == config, 'configuration is not normalized')
        require(request['configuration_digest'] == digest(config), 'configuration digest differs')
        require(timestamp(request['balance_at']) == request['balance_at']
                and timestamp(request['knowledge_at']) == request['knowledge_at'], 'request cuts are not normalized')
        require(request['balance_at'] >= config['opening_at'], 'balance cut precedes opening')
        require(canonical(context) == raw_context, 'context bytes are not canonical')
        raw_request = canonical(request)
        require(len(raw_request) <= MAX_REQUEST_BYTES, 'request byte limit', 'REPLAY_LIMIT')
        for key in ('request_fingerprint', 'run_id', 'run_payload_sha256'):
            require(is_digest(context[key]), 'invalid context digest: ' + key)
        require(sha256(raw_request) == context['request_fingerprint'], 'request fingerprint differs')
        context_hash, run_hash = sha256(raw_context), sha256(raw_run)
        require(run_hash == context['run_payload_sha256'], 'raw financial payload hash differs')
        require(type(saved) is dict and saved.get('rule_version') == 'stage2-v2',
                'unsupported financial payload rule', 'REPLAY_UNSUPPORTED')
        _financial_cardinality(saved)
        require(digest(saved) == context['run_id'], 'canonical saved run identity differs')
        row = {key: context[key] for key in ('request_id', 'request_fingerprint', 'run_id', 'run_payload_sha256')}
        row['context_hash'] = context_hash
        execution_id = sha256(canonical(binding(row)))
        require(execution_id == expected_execution_id, 'execution differs from external expected identity')
        saved = validate_payload(run_text, context['run_id'], 6)
        require(saved['configuration'] == config and saved['balance_at'] == request['balance_at']
                and saved['knowledge_at'] == request['knowledge_at']
                and saved['rule_version'] == request['rule_version'], 'context/financial metadata differs')
        require(canonical(context['scope']) == canonical(capture.SCOPE), 'captured scope differs')
        tables = context['tables']
        _inventory_types(tables)
        _declared_domains(tables)
        # These TEXT columns contain nested JSON which the existing pure
        # inventory helpers parse. Bound it too without changing stored TEXT.
        for table, column in (('records', 'payload'), ('receipts', 'raw'),
                              ('auth_policy_snapshots', 'payload')):
            for item in tables[table]:
                _json(item[column].encode('utf-8'), budget)
        capture.validate_inventory(tables, config, request['knowledge_at'])
        _declared_references(tables)
        counts = context['counts']
        require(type(counts) is dict and set(counts) == set(capture.COLUMNS)
                and all(type(v) is int and v >= 0 for v in counts.values()), 'inventory count types differ')
        require(counts == {name: len(rows) for name, rows in tables.items()}, 'inventory counts differ')
        _selected_types(context['selected_evidence'])
        _evidence_cardinality(tables, saved, context['selected_evidence'])
        require(context['selected_evidence'] == capture.evidence_mapping(tables, saved), 'selected evidence mapping differs')
        head = tables['auth_policy_activations'][-1] if tables['auth_policy_activations'] else None
        require(canonical(context['observed_policy_head']) == canonical(head), 'observed policy head differs')
        epochs = context['acceptance_epochs']
        require(type(epochs) is list and len(epochs) <= capture.MAX_EPOCHS, 'acceptance epoch list differs')
        for epoch in epochs:
            _positive_integer(epoch, 'acceptance epoch')
        require(epochs == capture.original_acceptance_epochs(tables), 'original acceptance epoch coverage differs')
        require(context['claims'] == capture.claims(tables), 'observation claims differ')
        identity = {
            'expected_execution_id': expected_execution_id, 'derived_execution_id': execution_id,
            'context_hash': context_hash, 'saved_raw_run_hash': run_hash,
            'saved_canonical_run_id': context['run_id'], 'request_fingerprint': context['request_fingerprint'],
            'inputs': {'context': {'bytes': len(raw_context), 'sha256': context_hash},
                       'run': {'bytes': len(raw_run), 'sha256': run_hash}},
            'captured_counts': counts, 'parsed_nodes': budget[0],
        }
        input_data = {'configuration': config, 'records': tables['records'], 'receipts': tables['receipts'],
                      'balance_at': request['balance_at'], 'knowledge_at': request['knowledge_at']}
        return ValidatedReplay(context, saved, identity, input_data)
    except ReplayError:
        raise
    except ExecutionError as exc:
        code = 'REPLAY_LIMIT' if exc.reason_code == 'EXECUTION_LIMIT' else 'REPLAY_INTEGRITY'
        raise ReplayError(code, str(exc)) from exc
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ReplayError('REPLAY_INTEGRITY', str(exc)) from exc
