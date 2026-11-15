"""One transaction for financial persistence, physical context and retry identity."""
import re
import sqlite3

from .. import engine
from ..migrations import inject, transaction, validate_current
from ..model import RULE_VERSION, config_validate, digest, timestamp
from . import capture
from .common import (ExecutionError, FORMAT, PROFILE, MAX_REQUEST_BYTES, MAX_RUN_BYTES,
                     binding, canonical, is_digest, parse, require, sha256)
from .reader import load_execution, read_run, validate_registry


class _OwnedStore:
    def __init__(self, store, config):
        self.store, self.db, self.config = store, store.db, config

    def known(self, knowledge_at):
        return self.store.known(knowledge_at)

    def save_run(self, result, *, fault=None):
        raw = canonical(result)
        require(len(raw) <= MAX_RUN_BYTES, 'financial payload byte limit', 'EXECUTION_LIMIT')
        rid = sha256(raw)
        if self.db.execute('SELECT 1 FROM runs WHERE id=?', (rid,)).fetchone():
            _, stored = read_run(self.db, rid)
            require(stored == result, 'pre-existing financial result differs')
            return {'run_id': rid, **stored}
        return self.store._save_run_in_transaction(result, fault=fault)


def reconcile_recorded(store, balance_at, knowledge_at, request_id, *, busy_timeout_ms=250,
                       configuration_digest=None, rule_version=RULE_VERSION, profile=PROFILE, _fault=None):
    db = store.db
    # The caller's unrelated transaction must remain untouched, even on failure.
    require(not db.in_transaction, 'caller-owned transaction is not supported', 'EXECUTION_TRANSACTION')
    require(type(busy_timeout_ms) is int and 0 <= busy_timeout_ms <= 5000, 'busy timeout must be 0..5000 ms', 'EXECUTION_INPUT')
    require(isinstance(request_id, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', request_id), 'invalid request identity', 'EXECUTION_INPUT')
    try:
        balance_at, knowledge_at = timestamp(balance_at), timestamp(knowledge_at)
    except (ValueError, TypeError) as exc:
        raise ExecutionError('EXECUTION_INPUT', str(exc)) from exc
    require(configuration_digest is None or is_digest(configuration_digest), 'invalid configuration digest', 'EXECUTION_INPUT')
    require(type(rule_version) is str and type(profile) is str and len(rule_version) <= 128 and len(profile) <= 128, 'invalid rule/profile', 'EXECUTION_INPUT')
    prior_timeout = db.execute('PRAGMA busy_timeout').fetchone()[0]
    db.execute('PRAGMA busy_timeout=' + str(busy_timeout_ms))
    try:
        with transaction(db):
            inject(_fault, 'execution_after_begin')
            require(db.execute('PRAGMA user_version').fetchone()[0] == 6, 'recorded execution requires schema 6', 'EXECUTION_SCHEMA')
            validate_current(db)
            validate_registry(db)
            row = db.execute('SELECT typeof(payload),length(CAST(payload AS BLOB)) FROM configuration WHERE id=1').fetchone()
            require(row is not None and row[0] == 'text' and 0 < row[1] <= capture.MAX_VALUE_BYTES, 'configuration limit', 'EXECUTION_LIMIT')
            config = config_validate(parse(db.execute('SELECT CAST(payload AS BLOB) FROM configuration WHERE id=1').fetchone()[0], capture.MAX_VALUE_BYTES))
            observed_digest = digest(config)
            request = {'format': FORMAT, 'db_scope': 'local-request-registry', 'balance_at': balance_at,
                       'knowledge_at': knowledge_at, 'configuration_digest': configuration_digest or observed_digest,
                       'rule_version': rule_version, 'profile': profile}
            raw_request = canonical(request)
            require(len(raw_request) <= MAX_REQUEST_BYTES, 'request byte limit', 'EXECUTION_LIMIT')
            fingerprint = sha256(raw_request)
            prior = db.execute('SELECT execution_id,request_fingerprint FROM recorded_executions WHERE request_id=?', (request_id,)).fetchone()
            if prior is not None:
                # Even a conflict must not conceal corrupt persisted retry rows.
                result = load_execution(db, prior['execution_id'], replayed=True)[0]
                require(prior['request_fingerprint'] == fingerprint, 'same request ID has different stable parameters', 'EXECUTION_REQUEST_CONFLICT')
            else:
                require(request['configuration_digest'] == observed_digest, 'expected configuration differs', 'EXECUTION_INPUT')
                require(rule_version == RULE_VERSION and profile == PROFILE, 'unsupported rule/profile', 'EXECUTION_INPUT')
                tables = capture.capture_inputs(db, knowledge_at)
                capture.validate_inventory(tables, config, knowledge_at)
                result_run = engine.reconcile(_OwnedStore(store, config), balance_at, knowledge_at)
                inject(_fault, 'execution_after_financial')
                raw_run, run = read_run(db, result_run['run_id'])
                context = {'format': FORMAT, 'schema_version': 6, 'request_id': request_id, 'request': request,
                           'request_fingerprint': fingerprint, 'configuration': config, 'run_id': result_run['run_id'],
                           'run_payload_sha256': sha256(raw_run), 'scope': capture.SCOPE, 'binary_encoding': 'hex',
                           'tables': tables, 'selected_evidence': capture.evidence_mapping(tables, run),
                           'counts': {name: len(rows) for name, rows in tables.items()},
                           'observed_policy_head': tables['auth_policy_activations'][-1] if tables['auth_policy_activations'] else None,
                           'acceptance_epochs': sorted({r['epoch'] for r in tables['auth_decisions']}), 'claims': capture.claims(tables)}
                raw_context = canonical(context)
                require(len(raw_context) <= capture.MAX_CONTEXT_BYTES, 'context byte limit exceeded', 'EXECUTION_LIMIT')
                row = {'request_id': request_id, 'request_fingerprint': fingerprint, 'run_id': result_run['run_id'],
                       'run_payload_sha256': sha256(raw_run), 'context_hash': sha256(raw_context)}
                execution_id = sha256(canonical(binding(row)))
                db.execute('INSERT INTO execution_contexts VALUES (?,?,?)', (row['context_hash'], FORMAT, raw_context))
                db.execute('INSERT INTO recorded_executions VALUES (?,?,?,?,?,?,?)', (execution_id, request_id, fingerprint, raw_request,
                           row['run_id'], row['run_payload_sha256'], row['context_hash']))
                result = load_execution(db, execution_id)[0]
                inject(_fault, 'execution_after_context')
        inject(_fault, 'execution_after_commit')
        return result
    except ExecutionError:
        raise
    except sqlite3.OperationalError as exc:
        code = getattr(exc, 'sqlite_errorcode', 0)
        if code & 255 in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise ExecutionError('EXECUTION_BUSY', str(exc)) from exc
        raise ExecutionError('EXECUTION_INTEGRITY', str(exc)) from exc
    except (ValueError, TypeError, KeyError, sqlite3.Error, RecursionError) as exc:
        raise ExecutionError('EXECUTION_INTEGRITY', str(exc)) from exc
    finally:
        db.execute('PRAGMA busy_timeout=' + str(prior_timeout))
