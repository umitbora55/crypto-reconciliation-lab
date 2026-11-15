"""Finite no-follow reads, one child deadline, and atomic optional publication."""
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

from ..review.publication import new_output_directory
from ..review.validation import strict_json
from .common import FORMAT, MAX_REPORT_BYTES, ReplayError
from .report import empty_report, fail, markdown, report_bytes

MAX_INPUT_BYTES = 16 * 1024 * 1024


def _read_input(path):
    path = Path(path).expanduser().absolute()
    if path.is_symlink():
        raise ReplayError('REPLAY_INPUT', 'final input symlink is unsupported')
    # O_NONBLOCK avoids a FIFO-open wait even if a path changes after lstat.
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ReplayError('REPLAY_INPUT', 'input must be a regular file')
        if before.st_size > MAX_INPUT_BYTES:
            raise ReplayError('REPLAY_LIMIT', 'input byte limit exceeded')
        raw = handle.read(MAX_INPUT_BYTES + 1)
        after = os.fstat(handle.fileno())
    if len(raw) > MAX_INPUT_BYTES:
        raise ReplayError('REPLAY_LIMIT', 'input byte limit exceeded')
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    if any(getattr(before, k) != getattr(after, k) for k in fields) or len(raw) != before.st_size:
        raise ReplayError('REPLAY_INPUT', 'input changed while reading')
    return raw, path.parent.resolve()/path.name


def _worker_command(directory, expected):
    # Fixed current package location, never read from either authoritative input.
    root = str(Path(__file__).resolve().parents[2])
    bootstrap = "import sys,runpy;sys.path.insert(0," + repr(root) + ");runpy.run_module('crypto_reconciliation_lab.replay.worker',run_name='__main__',alter_sys=True)"
    return [sys.executable, '-I', '-B', '-c', bootstrap, str(directory), expected]


def _run_worker(raw_context, raw_run, expected, timeout, *, _command=None):
    with tempfile.TemporaryDirectory(prefix='execution-replay-') as temporary:
        directory = Path(temporary)
        (directory/'context.input').write_bytes(raw_context)
        (directory/'run.input').write_bytes(raw_run)
        command = _worker_command(directory, expected) if _command is None else _command
        # Files avoid unbounded communicate() accumulation; stdout has no authority.
        with (directory/'stdout').open('wb') as stdout, (directory/'stderr').open('wb') as stderr:
            process = subprocess.Popen(command, cwd=directory, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr)
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise ReplayError('REPLAY_TIMEOUT', 'replay child exceeded deadline and was reaped') from None
        path = directory/'result.json'
        if code != 0 or path.is_symlink() or not path.is_file():
            raise ReplayError('REPLAY_LIMIT', 'replay child did not return one complete result')
        with path.open('rb') as handle:
            raw = handle.read(MAX_REPORT_BYTES + 1)
        if len(raw) > MAX_REPORT_BYTES:
            raise ReplayError('REPLAY_LIMIT', 'replay child output byte limit exceeded')
        try:
            result = strict_json(raw.decode('utf-8'))
            _validate_result(result, expected)
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            raise ReplayError('REPLAY_LIMIT', 'replay child result is incomplete or invalid') from None
        return result


def _validate_result(result, expected):
    # Private protocol, not an alternate public report-input verifier.
    if type(result) is not dict or not set(empty_report(expected)) <= set(result):
        raise ValueError('incomplete child report')
    if result['format'] != FORMAT or result['expected_execution_id'] != expected:
        raise ValueError('child identity mismatch')
    state = result['status']
    if state not in ('REPRODUCED', 'DIVERGED', 'ERROR') or type(result['exit_code']) is not int:
        raise ValueError('child status')
    if result['exit_code'] != {'REPRODUCED': 0, 'DIVERGED': 1, 'ERROR': 2}[state]:
        raise ValueError('child exit')
    completed = result['completion']
    if (type(completed) is not dict or set(completed) != {'validation','calculation','comparison'}
            or any(v not in ('COMPLETED','NOT_COMPLETED') for v in completed.values())
            or type(result['comparison']) is not dict):
        raise ValueError('child stage completion')
    if completed['comparison'] == 'COMPLETED':
        if (completed['validation'] != 'COMPLETED' or completed['calculation'] != 'COMPLETED'
                or result['replay_state'] not in ('REPRODUCED','DIVERGED')
                or type(result['comparison'].get('equal')) is not bool):
            raise ValueError('child comparison completion')
    if state != 'ERROR':
        equal = state == 'REPRODUCED'
        if (result['replay_state'] != state or result['operation_state'] != 'COMPLETE'
                or result['reason_code'] != 'REPLAY_' + state
                or result['completion'] != dict.fromkeys(('validation','calculation','comparison'), 'COMPLETED')
                or result['comparison']['equal'] is not equal
                or result['comparison']['state'] != ('EQUAL' if equal else 'DIFFERENT')
                or not result['runtime'] or not result['financial_summary']):
            raise ValueError('child completion')
        from ..execution.common import is_digest
        if (not all(is_digest(result[k]) for k in ('derived_execution_id','context_hash',
                'saved_raw_run_hash','saved_canonical_run_id','recomputed_canonical_run_id'))
                or result['derived_execution_id'] != expected):
            raise ValueError('child completed identity')


def _destination(output, inputs):
    requested = Path(output).expanduser().absolute()
    if os.path.lexists(requested):
        raise ReplayError('REPLAY_OUTPUT', 'output already exists (including final symlink)')
    try:
        destination = (requested.parent.resolve()/requested.name).resolve()
    except RuntimeError as exc:
        # Python 3.12 reports a symlink loop here as RuntimeError. Limit this
        # classification to output canonicalization, preserving the child result.
        raise ReplayError('REPLAY_OUTPUT', str(exc)) from None
    if os.path.lexists(destination):
        raise ReplayError('REPLAY_OUTPUT', 'canonical output already exists')
    if any(destination == path or path in destination.parents for path in inputs):
        raise ReplayError('REPLAY_OUTPUT', 'output overlaps an authoritative input')
    return destination


def verify_execution_replay(context_path, run_path, expected_execution_id, *, output=None, timeout_seconds=30):
    """Return a complete report; successful reproduction may include financial gaps."""
    result = empty_report(expected_execution_id)
    try:
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 60:
            raise ReplayError('REPLAY_INPUT', 'timeout_seconds must be an integer from 1 to 60')
        context, context_location = _read_input(context_path)
        run, run_location = _read_input(run_path)
        observed = {'context': {'bytes': len(context), 'sha256': hashlib.sha256(context).hexdigest()},
                    'run': {'bytes': len(run), 'sha256': hashlib.sha256(run).hexdigest()}}
        result['inputs'] = observed
        # Invalid pins are also validated inside the timed worker. Non-string
        # API arguments cannot be transported as argv and fail as input errors.
        if type(expected_execution_id) is not str:
            raise ReplayError('REPLAY_INPUT', 'external execution identity must be text')
        result = _run_worker(context, run, expected_execution_id, timeout_seconds)
        result['inputs'] = observed
        if output is not None:
            try:
                destination = _destination(output, (context_location, run_location))
                with new_output_directory(destination) as staging:
                    (staging/'report.json').write_bytes(report_bytes(result))
                    (staging/'report.md').write_text(markdown(result), encoding='utf-8')
            except (OSError, ValueError) as exc:
                fail(result, 'REPLAY_OUTPUT', str(exc))
    except ReplayError as exc:
        fail(result, exc.reason_code, str(exc))
    except (OSError, ValueError, TypeError) as exc:
        fail(result, 'REPLAY_INPUT', str(exc))
    return result
