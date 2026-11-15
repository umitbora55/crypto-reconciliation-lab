"""Local recorded-observation identities, not an external trust root."""
import hashlib
import re

from ..model import dumps
from ..review.validation import strict_json

FORMAT = 'recorded-execution-v1'
PROFILE = 'all-known-receipts-v1'
MAX_REQUEST_BYTES = 16 * 1024
MAX_RUN_BYTES = 16 * 1024 * 1024


class ExecutionError(ValueError):
    def __init__(self, reason_code, message):
        self.reason_code = self.code = reason_code
        super().__init__(reason_code + ': ' + message)


def require(condition, message, code='EXECUTION_INTEGRITY'):
    if not condition:
        raise ExecutionError(code, message)


def canonical(value):
    return dumps(value).encode('utf-8')


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def is_digest(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def parse(raw, limit):
    require(type(raw) is bytes and 0 < len(raw) <= limit, 'invalid or excessive JSON bytes', 'EXECUTION_LIMIT')
    try:
        return strict_json(raw.decode('utf-8'))
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ExecutionError('EXECUTION_INTEGRITY', 'invalid strict JSON') from exc


def binding(row):
    return {'format': FORMAT, **{k: row[k] for k in (
        'request_id', 'request_fingerprint', 'run_id', 'run_payload_sha256', 'context_hash')}}
