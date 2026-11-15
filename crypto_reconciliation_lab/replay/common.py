"""Explicit finite limits and controlled offline replay failures."""
FORMAT = 'execution-replay-report-v1'
MAX_DEPTH = 1024
MAX_NODES = 16_777_216
MAX_COMPUTED_BYTES = 16 * 1024 * 1024
MAX_REPORT_BYTES = 4 * 1024 * 1024
MAX_DIFFS = 100
MAX_PREVIEW = 256


class ReplayError(ValueError):
    def __init__(self, reason_code, message):
        self.reason_code = self.code = reason_code
        super().__init__(message)


def require(condition, message, code='REPLAY_INTEGRITY'):
    if not condition:
        raise ReplayError(code, message)
