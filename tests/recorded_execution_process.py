"""Bounded, observable process supervision used only by execution tests."""
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
import uuid

TIMEOUT = 30


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


def evidence_folder(test_id, temporary):
    root = os.environ.get('CRYPTO_EXECUTION_TEST_EVIDENCE')
    if root:
        # This test-only variable cannot inject a runtime fault or change input.
        folder = Path(root).resolve() / (test_id + '-' + uuid.uuid4().hex)
    else:
        folder = Path(temporary) / 'process-evidence' / test_id
    folder.mkdir(parents=True, exist_ok=False)
    return folder


class Child:
    def __init__(self, folder, name, request):
        self.folder, self.name, self.messages, self.buffer = Path(folder), name, [], b''
        self.request = request
        self.started = time.monotonic()
        self.started_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        path = self.folder / (name + '-request.json')
        write(path, request)
        worker = Path(__file__).with_name('recorded_execution_worker.py')
        launcher = 'import runpy,sys; p=sys.argv.pop(1); runpy.run_path(p,run_name="__main__")'
        self.argv = [sys.executable, '-B', *(['-I'] if sys.flags.isolated else []),
                     '-c', launcher, str(worker), '--request', str(path)]
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        env.pop('PYTHONHOME', None)
        self.process = subprocess.Popen(self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, env=env)
        self.finished = False
        try:
            ready = self.receive('READY')
            if ready['pid'] != self.process.pid:
                raise AssertionError('wrong child READY pid')
        except BaseException:
            self.finish(kill=True)
            raise

    def send(self, text):
        self.process.stdin.write((text+'\n').encode('ascii'))
        self.process.stdin.flush()

    def receive(self, expected):
        deadline = time.monotonic() + TIMEOUT
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while b'\n' not in self.buffer:
                remaining = deadline-time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise TimeoutError('private child protocol timed out waiting for '+expected)
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise RuntimeError('child exited before '+expected)
                self.buffer += chunk
                if len(self.buffer) > 8*1024*1024:
                    raise ValueError('private child message exceeds 8 MiB')
        line, self.buffer = self.buffer.split(b'\n', 1)
        item = json.loads(line)
        self.messages.append(item)
        if item['pid'] != self.process.pid or item['type'] != expected:
            raise AssertionError('unexpected child event: '+repr(item))
        return item

    def finish(self, *, kill=False):
        if self.finished:
            return self.record
        if kill and self.process.poll() is None:
            self.process.send_signal(signal.SIGKILL)
        timed_out = False
        try:
            tail, stderr = self.process.communicate(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            self.process.kill()
            tail, stderr = self.process.communicate(timeout=TIMEOUT)
            timed_out = True
        finally:
            self.finished = True
        (self.folder/(self.name+'-stdout-tail.txt')).write_bytes(self.buffer+tail)
        (self.folder/(self.name+'-stderr.txt')).write_bytes(stderr)
        self.record = {'argv': self.argv, 'cwd': str(Path.cwd()), 'pid': self.process.pid,
                       'joined': True, 'exit_code': self.process.returncode,
                       'signal': 'SIGKILL' if kill else None, 'sender_result': 'UNKNOWN' if kill else 'RESPONSE',
                       'messages': self.messages, 'stdout_tail': (self.buffer+tail).decode('utf-8', errors='replace'),
                       'stderr': stderr.decode('utf-8', errors='replace'),
                       'started_at': self.started_at, 'seconds': time.monotonic()-self.started}
        self.record['forced_timeout_cleanup'] = timed_out
        write(self.folder/(self.name+'-process.json'), self.record)
        if timed_out:
            raise TimeoutError('child required timeout cleanup: '+self.name)
        return self.record


def normal(folder, name, request, expected='RESULT'):
    child = Child(folder, name, request)
    try:
        child.send('GO')
        event = child.receive(expected)
        record = child.finish()
        return event, record
    finally:
        if child.process.poll() is None:
            child.finish(kill=True)
