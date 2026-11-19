"""Real Linux acceptance controls; separate from the immutable 875-test roster."""
import errno
import fcntl
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from crypto_reconciliation_lab.protected_snapshot import ProtectionError
from crypto_reconciliation_lab.protected_snapshot import api, producer, securefs
from crypto_reconciliation_lab.protected_snapshot.sandbox import IsolationError, run_isolated
from crypto_reconciliation_lab.review.export import export_selection

RUN = "db050c7ea9ce4aec4f0a99ea47ecd3e32d30b2d10ec209ff31c12e8cc139115b"
SHA = "1a37873cd1ec44a2e498baedb26c71250fb15afa0cc85e65c21cb35cc3669133"
FIXTURE = Path(os.environ.get("CRL_SNAPSHOT_FIXTURE", "/var/tmp/crl-financial-wal-_2p915zx/snapshot-delete.sqlite3"))
EVIDENCE = Path(os.environ["CRL_PROTECTED_TEST_OUTPUT"])
PACKAGE = Path(__import__("crypto_reconciliation_lab").__file__).parent


def read_noatime(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NOATIME | os.O_CLOEXEC)
    try:
        return os.pread(fd, os.fstat(fd).st_size, 0)
    finally:
        os.close(fd)


def inventory(path):
    """Full tree of regular test inputs with non-mutating directory iteration."""
    result = {}
    def walk(directory, relative):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOATIME | os.O_NOFOLLOW)
        try:
            result[relative or "."] = securefs.metadata(fd)
            for name in sorted(os.listdir(fd)):
                item = directory / name
                key = str(Path(relative) / name)
                info = item.lstat()
                if item.is_symlink():
                    result[key] = {"link": os.readlink(item), "inode": info.st_ino}
                elif item.is_dir():
                    walk(item, key)
                else:
                    child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NOATIME, dir_fd=fd)
                    try:
                        result[key] = {**securefs.metadata(child), **securefs.digest_fd(child)}
                    finally:
                        os.close(child)
        finally:
            os.close(fd)
    walk(Path(path), "")
    return result


def save(path, value):
    producer.write_new(path, producer.encoded(value))


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.root = EVIDENCE / self._testMethodName
        self.root.mkdir(mode=0o700)
        self.inputs = self.root / "inputs"
        self.inputs.mkdir(mode=0o700)
        self.source = self.inputs / "snapshot.sqlite3"
        self.source.write_bytes(read_noatime(FIXTURE))
        self.source.chmod(0o600)
        self.assertEqual(hashlib.sha256(read_noatime(self.source)).hexdigest(), SHA)
        self.options = dict(kind="snapshot", run_ids=[RUN], expected_sha256=SHA,
                            run_labels={RUN: "Initial knowledge"})

    def export(self, source=None, name="review", **overrides):
        return api.protected_export(str(source or self.source), str(self.root / name),
                                    **(self.options | overrides))

    def reject(self, source=None, name="rejected", **overrides):
        with self.assertRaises((ProtectionError, OSError, ValueError)) as caught:
            self.export(source, name, **overrides)
        self.assertFalse(os.path.lexists(self.root / name))
        save(self.root / (name + ".rejection.json"), {"status": "EXPECTED_REJECTION",
             "error_type": type(caught.exception).__name__, "message": str(caught.exception)})
        return caught.exception

    def sealed(self):
        with securefs.source_fd(self.source) as (fd, _, __):
            return producer.sealed_copy(fd)

    def isolated(self, code, name="sandbox", **kwargs):
        script = self.root / (name + ".py")
        script.write_text(code)
        workspace = self.root / name
        workspace.mkdir(mode=0o700)
        fd = self.sealed()
        try:
            result = run_isolated(fd, producer.encoded(producer.selection_for(
                "/input/snapshot.sqlite3", [RUN], "custody_difference", "Custody difference",
                {RUN: "Initial knowledge"})), workspace, PACKAGE, consumer_script=script, **kwargs)
        finally:
            os.close(fd)
        save(self.root / (name + ".process.json"), result)
        return result, workspace

    def test_C01_protected_metadata_acl_xattr_and_all_output_parity(self):
        os.setxattr(self.source, "user.crl", b"preserve-this-value")
        subprocess.run(["setfacl", "-m", "u:65534:r--", str(self.source)], check=True)
        before = inventory(self.inputs)
        proof = self.export()
        after = inventory(self.inputs)
        self.assertEqual(before, after)
        save(self.root / "before.json", before)
        save(self.root / "after.json", after)
        save(self.root / "proof.json", proof)
        self.assertEqual(proof["status"], "COMPLETE")
        self.assertEqual(proof["production"]["source_before"], proof["production"]["source_after"])
        self.assertEqual(proof["production"]["transport"], proof["production"]["transport_after"])
        financial = proof["production"]["financial"]
        self.assertEqual({name: financial["tables"][name]["rows"] for name in ("receipts", "runs", "findings", "evidence")},
                         {"receipts": 30, "runs": 1, "findings": 6, "evidence": 60})
        self.assertEqual(financial["selected_runs"][0]["run_id"], RUN)
        selection = self.root / "baseline-selection.json"
        save(selection, producer.selection_for(self.source, [RUN], "custody_difference",
                                              "Custody difference", {RUN: "Initial knowledge"}))
        export_selection(selection, self.root / "ordinary")
        for name in ("index.html", "summary.json", "manifest.json"):
            self.assertEqual((self.root / "ordinary" / name).read_bytes(), (self.root / "review" / name).read_bytes())

    def test_C01_WAL_backup_and_bounded_phase_cost(self):
        costs = []
        for iteration in range(3):
            wal = self.inputs / ("wal-" + str(iteration) + ".sqlite3")
            wal.write_bytes(read_noatime(self.source))
            wal.chmod(0o600)
            live = sqlite3.connect(wal)
            try:
                self.assertEqual(live.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
                live.execute("PRAGMA synchronous=FULL")
                live.execute("PRAGMA wal_autocheckpoint=0")
                # Same schema value creates a genuine uncheckpointed WAL page
                # without violating append-only financial table triggers.
                live.execute("PRAGMA user_version=6")
                live.commit()
                proof = self.export(wal, "wal-review-" + str(iteration), kind="wal", expected_sha256=None)
                self.assertNotEqual(proof["production"]["source_before"]["inode"], proof["production"]["snapshot"]["inode"])
                costs.append({"kind": "wal", "iteration": iteration, "timings": proof["timings"]})
                save(self.root / ("wal-proof-" + str(iteration) + ".json"), proof)
            finally:
                live.close()
        for iteration in range(3):
            proof = self.export(name="snapshot-review-" + str(iteration))
            costs.append({"kind": "snapshot", "iteration": iteration, "timings": proof["timings"]})
        for iteration in range(3):
            for filename in ("index.html", "summary.json"):
                self.assertEqual((self.root / ("wal-review-" + str(iteration)) / filename).read_bytes(),
                                 (self.root / "snapshot-review-0" / filename).read_bytes())
        save(self.root / "phase-costs.json", {"samples": costs, "scope": "30 receipts; n=3 per mode; no Gate4 workload comparison"})

    def test_C02_unprotected_unsealed_and_writable_handles(self):
        fd = os.open(self.source, os.O_RDONLY)
        try:
            workspace = self.root / "unsealed"
            workspace.mkdir(mode=0o700)
            with self.assertRaisesRegex(IsolationError, "ISOLATION_INPUT"):
                run_isolated(fd, b"{}", workspace, PACKAGE)
            self.assertFalse((workspace / "output").exists())
        finally:
            os.close(fd)
        sealed = self.sealed()
        writable = os.open(f"/proc/self/fd/{sealed}", os.O_RDWR)
        try:
            workspace = self.root / "writable"
            workspace.mkdir(mode=0o700)
            with self.assertRaisesRegex(IsolationError, "ISOLATION_INPUT: caller must release writable"):
                run_isolated(writable, b"{}", workspace, PACKAGE)
            self.assertFalse((workspace / "output").exists())
        finally:
            os.close(writable)
            os.close(sealed)

    def test_C02_untrusted_parent_and_nonroot_supervisor(self):
        self.inputs.chmod(0o777)
        self.reject(name="untrusted")
        self.inputs.chmod(0o700)
        # Actual boundary call runs via fork, retaining already imported module.
        child = os.fork()
        if child == 0:
            try:
                os.setgroups([]); os.setgid(65534); os.setuid(65534)
                securefs.require_linux_root()
                os._exit(0)
            except ProtectionError:
                os._exit(2)
        _, status = os.waitpid(child, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 2)

    def test_C02_missing_contract_preflight_refuses(self):
        from crypto_reconciliation_lab.protected_snapshot.namespace_worker import consumer_preflight
        with self.assertRaises(FileNotFoundError) as caught:
            consumer_preflight()
        self.assertEqual(caught.exception.filename, "/input/contract.json")

    def test_C02_actual_misconfigured_mounts_refuse_before_export(self):
        from crypto_reconciliation_lab.protected_snapshot import sandbox
        worker = PACKAGE / "protected_snapshot" / "namespace_worker.py"
        source = worker.read_text()
        original = "mount(None, root, flags=MS_REMOUNT | MS_RDONLY | MS_NOSUID | MS_NODEV | MS_NOATIME)"
        self.assertEqual(source.count(original), 1)
        for name, replacement in (("writable-root", original.replace("MS_RDONLY | ", "")),
                                  ("atime-root", original.replace("MS_NOATIME", "(1 << 24)"))):
            fault = self.root / name
            fault.mkdir()
            changed = source.replace(original, replacement)
            (fault / "namespace_worker.py").write_text(changed)
            workspace = fault / "workspace"
            workspace.mkdir(mode=0o700)
            fd = self.sealed()
            try:
                with patch.object(sandbox, "__file__", str(fault / "sandbox.py")):
                    result = run_isolated(fd, producer.encoded(producer.selection_for(
                        "/input/snapshot.sqlite3", [RUN], "custody_difference", "Custody difference", {})),
                        workspace, PACKAGE)
                self.assertNotEqual(result["returncode"], 0, result)
                self.assertIn("ISOLATION_ROOT", result["stderr"])
                self.assertFalse((workspace / "output" / "review").exists())
                save(fault / "result.json", {"fault_worker_sha256": hashlib.sha256(changed.encode()).hexdigest(),
                                           "status": "EXPECTED_REJECTION", "process": result})
            finally:
                os.close(fd)

    def test_C03_sealed_anchor_rejects_retained_writable_fd_processes(self):
        fd = self.sealed()
        writable = os.open(f"/proc/self/fd/{fd}", os.O_RDWR)
        code = """import os,sys,json
fd=int(sys.argv[1]); failures=[]
for i in range(100):
 try: os.pwrite(fd,b'CRL!',68)
 except OSError as e: failures.append(e.errno)
print(json.dumps({'uid':os.getuid(),'attempts':100,'denied':len(failures),'errnos':sorted(set(failures))}))
assert failures==[1]*100
"""
        before = securefs.digest_fd(fd)
        try:
            children = [subprocess.Popen([sys.executable, "-I", "-c", code, str(writable)],
                         pass_fds=(writable,), user=65534, group=65534, extra_groups=(),
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(4)]
            rows = []
            for child in children:
                stdout, stderr = child.communicate(timeout=10)
                rows.append({"returncode": child.returncode, "stdout": stdout.decode(), "stderr": stderr.decode()})
                self.assertEqual(child.returncode, 0)
            self.assertEqual(before, securefs.digest_fd(fd))
            save(self.root / "concurrent-sealed-writers.json", rows)
        finally:
            os.close(writable); os.close(fd)

    def test_C03_import_source_concurrent_writer_detected_no_publication(self):
        from crypto_reconciliation_lab.protected_snapshot import sandbox
        original = sandbox.run_isolated
        retained = os.open(self.source, os.O_RDWR)
        def changed_input(*args, **kwargs):
            attack = subprocess.run([sys.executable, "-I", "-c",
                "import os,sys;os.pwrite(int(sys.argv[1]),b'RACE',68)", str(retained)],
                pass_fds=(retained,), user=65534, group=65534, extra_groups=(), capture_output=True)
            self.assertEqual(attack.returncode, 0, attack.stderr)
            result = original(*args, **kwargs)
            self.assertEqual(result["returncode"], 0, result)
            self.assertTrue(result["trusted_attestation"]["snapshot_unchanged"])
            save(self.root / "protected-consumption.json", result)
            return result
        try:
            with patch.object(sandbox, "run_isolated", changed_input):
                self.assertIn("SOURCE_CHANGED", str(self.reject(name="concurrent-import")))
        finally:
            os.close(retained)

    def test_C03_actual_consumer_privilege_and_namespace_attacks(self):
        code = Path(__file__).with_name("sandbox_probe.py").read_text()
        result, workspace = self.isolated(code, name="privilege-attacks")
        self.assertEqual(result["returncode"], 0, result)
        attacks = json.loads((workspace / "output" / "attacks.json").read_text())
        self.assertEqual(attacks["status"], "PASS")
        self.assertEqual(len(attacks["observations"]), 14)

    def test_C03_controlled_privileged_mutation_detected(self):
        from crypto_reconciliation_lab.protected_snapshot import sandbox
        fault = self.root / "fault-worker"
        fault.mkdir()
        worker = (PACKAGE / "protected_snapshot" / "namespace_worker.py").read_text()
        trigger = '    snapshot_after = snapshot_observation("/input/snapshot.sqlite3")'
        self.assertEqual(worker.count(trigger), 1)
        injected = '''    # Test-only trusted supervisor fault, outside nonroot threat scope.
    mount(None, "/", flags=MS_REMOUNT | MS_NOSUID | MS_NODEV | MS_NOATIME)
    with open("/input/snapshot.sqlite3", "r+b") as changed:
        changed.seek(68)
        changed.write(b"ROOT")
    mount(None, "/", flags=MS_REMOUNT | MS_RDONLY | MS_NOSUID | MS_NODEV | MS_NOATIME)
'''
        (fault / "namespace_worker.py").write_text(worker.replace(trigger, injected + trigger))
        with patch.object(sandbox, "__file__", str(fault / "sandbox.py")):
            error = self.reject(name="trusted-supervisor-fault")
        self.assertIn("CONSUMER_FAILED", str(error))

    def test_C03_C04_real_consumer_concurrent_attacks_and_FD_isolation(self):
        code = r'''
import os,json,pathlib,sys,time
observed={}
for value in os.listdir('/proc/self/fd'):
 try: observed[value]=os.readlink('/proc/self/fd/'+value)
 except FileNotFoundError: pass
assert all(int(value)<3 for value in observed), observed
from crypto_reconciliation_lab.review.export import export_selection
assert not pathlib.Path(HOST_SOURCE).exists()
assert not pathlib.Path(HOST_PRIVATE).exists()
children=[]
for index in range(4):
 pid=os.fork()
 if pid==0:
  denials=[]
  for attempt in range(100):
   for operation in ('write','rename','link','traverse'):
    try:
     if operation=='write': fd=os.open('/input/snapshot.sqlite3',os.O_WRONLY);os.close(fd)
     elif operation=='rename': os.rename('/input/snapshot.sqlite3','/tmp/replaced')
     elif operation=='link': os.link('/input/snapshot.sqlite3','/tmp/link-'+str(index))
     else: fd=os.open('/proc/1/root'+HOST_SOURCE,os.O_RDONLY);os.close(fd)
    except OSError as e: denials.append([operation,e.errno])
  pathlib.Path('/output/writer-'+str(index)+'.json').write_text(json.dumps(denials))
  os._exit(0 if len(denials)==400 else 3)
 children.append(pid)
export_selection('/input/selection.json','/output/review')
for pid in children:
 assert os.waitstatus_to_exitcode(os.waitpid(pid,0)[1])==0
pathlib.Path('/output/attack-results.json').write_text(json.dumps({'fd_inventory':observed,'concurrent_writers':4,'denied_attempts':1600,'uid':os.getuid()}))
'''.replace("HOST_SOURCE", repr(str(self.source))).replace("HOST_PRIVATE", repr(str(self.root)))
        # Deliberately inheritable original writable file description must vanish.
        leak = os.open(self.source, os.O_RDWR)
        os.set_inheritable(leak, True)
        try:
            result, workspace = self.isolated(code)
        finally:
            os.close(leak)
        self.assertEqual(result["returncode"], 0, result)
        attacks = json.loads((workspace / "output" / "attack-results.json").read_text())
        self.assertEqual(attacks["denied_attempts"], 1600)
        self.assertEqual(hashlib.sha256(read_noatime(self.source)).hexdigest(), SHA)

    def test_C04_symlink_hardlink_traversal_and_bind_mount_alias(self):
        link = self.inputs / "symbolic.sqlite3"
        link.symlink_to(self.source)
        self.assertEqual(self.reject(link, "symlink").errno, errno.ELOOP)
        hard = self.inputs / "hard.sqlite3"
        os.link(self.source, hard)
        self.assertIn("SOURCE_TYPE", str(self.reject(hard, "hardlink")))
        hard.unlink()
        self.assertIn("UNSAFE_PATH", str(self.reject(str(self.inputs) + "/../inputs/snapshot.sqlite3", "traversal")))
        alias = self.inputs / "mount.sqlite3"
        alias.touch()
        subprocess.run(["mount", "--bind", str(self.source), str(alias)], check=True)
        try:
            self.assertEqual(self.reject(alias, "mount-alias").errno, errno.EXDEV)
        finally:
            subprocess.run(["umount", str(alias)], check=True)

    def test_C04_real_process_inode_swap_after_pinned_open(self):
        replacement = self.inputs / "replacement.sqlite3"
        replacement.write_bytes(read_noatime(self.source)); replacement.chmod(0o600)
        source_before = self.source.stat().st_ino
        original_seal = producer.sealed_copy
        def race(fd):
            child = subprocess.run([sys.executable, "-I", "-c",
                                    "import os,sys;os.replace(sys.argv[1],sys.argv[2])",
                                    str(replacement), str(self.source)], capture_output=True, timeout=10)
            self.assertEqual(child.returncode, 0)
            return original_seal(fd)
        with patch.object(producer, "sealed_copy", race):
            self.reject(name="inode-race")
        self.assertNotEqual(source_before, self.source.stat().st_ino)

    def test_C05_existing_targets_and_publication_collision(self):
        for name, kind in (("old-directory", "dir"), ("old-file", "file"), ("dangling", "link")):
            path = self.root / name
            if kind == "dir": path.mkdir(); (path / "prior.txt").write_text("previous evidence")
            elif kind == "file": path.write_text("previous evidence")
            else: path.symlink_to("missing-previous-evidence")
            before = path.lstat()
            with self.assertRaises(FileExistsError): self.export(name=name)
            self.assertEqual(before, path.lstat())
        real_rename = api.rename_noreplace
        def collision(fd, source, target):
            # A real competing process claims the output just before the syscall.
            subprocess.run([sys.executable, "-I", "-c", "import pathlib,sys;p=pathlib.Path(sys.argv[1]);p.mkdir();(p/'prior').write_text('retain')",
                            str(self.root / target)], check=True)
            return real_rename(fd, source, target)
        with patch.object(api, "rename_noreplace", collision):
            with self.assertRaises(FileExistsError): self.export(name="collision")
        self.assertEqual((self.root / "collision" / "prior").read_text(), "retain")

    def test_C06_WAL_sidecar_and_corrupt_snapshot(self):
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(str(self.source) + suffix)
            sidecar.touch()
            self.reject(name="sidecar" + suffix)
            sidecar.unlink()
        wal = self.inputs / "clean-wal.sqlite3"
        wal.write_bytes(read_noatime(self.source)); wal.chmod(0o600)
        with sqlite3.connect(wal) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
        self.assertEqual(read_noatime(wal)[18:20], b"\x02\x02")
        self.reject(wal, "clean-wal", expected_sha256=hashlib.sha256(read_noatime(wal)).hexdigest())
        corrupt = self.inputs / "corrupt.sqlite3"
        data = bytearray(read_noatime(self.source)); data[100:120] = b"!" * 20
        corrupt.write_bytes(data); corrupt.chmod(0o600)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "malformed"):
            self.export(corrupt, "corrupt", expected_sha256=hashlib.sha256(data).hexdigest())
        self.assertFalse((self.root / "corrupt").exists())

    def test_C07_forged_consumer_output_rejected(self):
        workspace = self.root / "forged"
        folder = workspace / "output" / "review"
        folder.mkdir(parents=True)
        files = {"index.html": b"<html>Forged financial result</html>",
                 "summary.json": b'{"status":"COMPLETE"}'}
        for name, data in files.items(): (folder / name).write_bytes(data)
        save(folder / "manifest.json", {"status": "COMPLETE", "files": {
            name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in files.items()}})
        with self.assertRaisesRegex(ProtectionError, "OUTPUT_REFERENCE_MISMATCH"):
            api.checked_output(workspace, {"index.html": {"bytes": 0, "sha256": "not-the-authorized-output"}})

    def test_C08_real_SIGKILL_before_atomic_publication(self):
        prior = self.root / "previous"
        prior.mkdir(); (prior / "evidence.txt").write_text("never replace")
        before = inventory(prior)
        read_pipe, write_pipe = os.pipe()
        child = os.fork()
        if child == 0:
            os.close(read_pipe)
            def barrier(directory, source, target):
                os.write(write_pipe, b"R")
                while True: signal.pause()
            try:
                with patch.object(api, "rename_noreplace", barrier): self.export(name="interrupted")
            except BaseException:
                os._exit(3)
            os._exit(4)
        os.close(write_pipe)
        import select
        ready, _, __ = select.select([read_pipe], [], [], 60)
        try:
            self.assertTrue(ready, "child failed to reach pre-publication barrier")
            self.assertEqual(os.read(read_pipe, 1), b"R")
            os.kill(child, signal.SIGKILL)
            _, status = os.waitpid(child, 0)
            self.assertEqual(os.waitstatus_to_exitcode(status), -signal.SIGKILL)
        finally:
            os.close(read_pipe)
            try: os.kill(child, signal.SIGKILL)
            except ProcessLookupError: pass
            try: os.waitpid(child, 0)
            except ChildProcessError: pass
        self.assertFalse((self.root / "interrupted").exists())
        self.assertEqual(before, inventory(prior))
        save(self.root / "kill.json", {"signal": "SIGKILL", "exit": -9, "final_output_absent": True,
                                      "previous_evidence_preserved": True, "barrier": "after complete real export/fsync, before renameat2"})

    def test_C08_controlled_failure_preserves_prior_output(self):
        prior = self.root / "prior"
        prior.mkdir(); (prior / "file").write_text("original")
        before = inventory(prior)
        with patch.object(api, "rename_noreplace", side_effect=OSError(errno.EIO, "controlled publication failure")):
            self.reject(name="io-failure")
        self.assertEqual(before, inventory(prior))
        recovery_start = time.monotonic()
        proof = self.export(name="io-failure")
        recovery_seconds = time.monotonic() - recovery_start
        self.assertEqual(proof["status"], "COMPLETE")
        self.assertEqual(before, inventory(prior))
        self.assertEqual(len(list(self.root.glob(".protected-work-*/failed.json"))), 1)
        save(self.root / "recovery.json", {"status": "PASS", "seconds": recovery_seconds,
             "previous_evidence_preserved": True, "first_failure_preserved": True,
             "method": "fresh owned attempt after failure; no deletion or overwrite"})

    def test_C08_live_supervisor_SIGKILL_reaps_detached_descendant(self):
        selection = self.root / "kill-selection.json"
        save(selection, producer.selection_for(self.source, [RUN], "custody_difference", "Custody difference", {}))
        helper = Path(__file__).with_name("sandbox_kill_probe.py")
        command = [sys.executable, "-I", "-S", str(helper), "--repo", str(PACKAGE.parent),
                   "--snapshot", str(self.source), "--selection", str(selection), "--output", str(self.root / "kill")]
        result = subprocess.run(command, capture_output=True, timeout=45)
        (self.root / "kill.stdout").write_bytes(result.stdout)
        (self.root / "kill.stderr").write_bytes(result.stderr)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        record = json.loads((self.root / "kill" / "result.json").read_text())
        self.assertEqual(record["status"], "PASS")
        self.assertEqual(record["survivors"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
