"""Root supervisor: fail closed, independently inspect output, publish once."""
import hashlib
import json
import os
from pathlib import Path
import stat
import time

from . import FORMAT, ProtectionError
from .producer import encoded, prepare, write_new
from .securefs import no_target, open_beneath, parent_fd, rename_noreplace, require_linux_root


def checked_output(workspace, expected_files):
    root = Path(workspace) / "output"
    # Only after the PID namespace is completely reaped. No recursive traversal
    # of hostile directories or following links when reading consumer results.
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        child = open_beneath(fd, "review", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            names = {"index.html", "summary.json", "manifest.json"}
            if set(os.listdir(child)) != names:
                raise ProtectionError("OUTPUT_INVALID: exact review file set required")
            files = {}
            for name in sorted(names):
                opened = open_beneath(child, name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                try:
                    info = os.fstat(opened)
                    limit = 128 * 1024 * 1024 if name == "index.html" else 8 * 1024 * 1024
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
                        raise ProtectionError("OUTPUT_INVALID: type, link count or size")
                    with os.fdopen(opened, "rb", closefd=False) as stream:
                        files[name] = stream.read(limit + 1)
                finally:
                    os.close(opened)
            summary = json.loads(files["summary.json"])
            manifest = json.loads(files["manifest.json"])
            if summary.get("status") != "COMPLETE" or manifest.get("status") != "COMPLETE":
                raise ProtectionError("OUTPUT_INCOMPLETE")
            for name in ("index.html", "summary.json"):
                if manifest["files"][name] != {"bytes": len(files[name]), "sha256": hashlib.sha256(files[name]).hexdigest()}:
                    raise ProtectionError("OUTPUT_HASH_MISMATCH")
            actual = {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                      for name, data in files.items()}
            if actual != expected_files:
                raise ProtectionError("OUTPUT_REFERENCE_MISMATCH: untrusted output differs from authorized snapshot")
            return files
        finally:
            os.close(child)
    finally:
        os.close(fd)


def protected_export(source, output, *, kind, run_ids, expected_sha256=None,
                     producer_uid=0, alias="custody_difference", label="Custody difference",
                     run_labels=None, timeout=60):
    require_linux_root()
    from .sandbox import run_isolated
    if not 0 < timeout <= 60:
        raise ProtectionError("TIMEOUT_INVALID: 0 < seconds <= 60")
    start = time.monotonic()
    with parent_fd(output, output=True) as (directory, target_name):
        no_target(directory, target_name)
        # mkdirat pins the work location to the checked parent. Root-owned
        # parent cannot be renamed by the consumer; no path resolution fallback.
        name = ".protected-work-" + os.urandom(16).hex()
        os.mkdir(name, 0o700, dir_fd=directory)
        workspace = Path(output).parent / name
        stage_name = ".protected-publish-" + os.urandom(16).hex()
        proof = {"format": FORMAT, "status": "STARTED", "output": str(output)}
        write_new(workspace / "started.json", encoded(proof))
        try:
            with prepare(source, workspace, kind=kind, expected_sha256=expected_sha256,
                         producer_uid=producer_uid, run_ids=run_ids, alias=alias,
                         label=label, run_labels=run_labels) as (sealed, selection, production):
                sandbox_workspace = workspace / "sandbox"
                sandbox_workspace.mkdir(mode=0o700)
                isolated = run_isolated(sealed, selection, sandbox_workspace,
                                        Path(__file__).resolve().parents[1], timeout=timeout)
                write_new(workspace / "consumer-process.json", encoded(isolated))
                if isolated["returncode"] != 0 or isolated.get("timed_out"):
                    raise ProtectionError("CONSUMER_FAILED: " + isolated.get("stderr", "")[-1000:])
                attestation = isolated.get("trusted_attestation")
                if (not isinstance(attestation, dict)
                        or attestation.get("format") != "protected-snapshot-supervisor-attestation-v1"
                        or attestation.get("consumer_returncode") != 0
                        or attestation.get("snapshot_unchanged") is not True
                        or attestation.get("snapshot_before") != attestation.get("snapshot_after")
                        or attestation.get("sealed_anchor", {}).get("sha256") != production["snapshot_bytes"]["sha256"]
                        or attestation.get("sealed_anchor", {}).get("inode") != production["transport"]["inode"]
                        or attestation.get("sealed_anchor", {}).get("device") != production["transport"]["device"]
                        or attestation.get("snapshot_before", {}).get("sha256") != production["snapshot_bytes"]["sha256"]):
                    raise ProtectionError("ATTESTATION_INVALID: trusted consumed inode proof missing or mismatched")
                files = checked_output(sandbox_workspace, production["reference_files"])
            # Context exit verified source + sealed snapshot after consumption.
            proof.update({"production": production, "consumer": isolated, "status": "VERIFIED",
                          "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                                    for name, data in files.items()}})
            boundary_times = isolated["trusted_attestation"]["timings"]
            proof["timings"] = {**production["timings"], "isolation_and_review_seconds": isolated["elapsed_seconds"],
                                "isolation_setup_seconds": boundary_times["setup_seconds"],
                                "consumer_process_seconds": boundary_times["consumer_process_seconds"],
                                "snapshot_postcheck_seconds": boundary_times["snapshot_postcheck_seconds"],
                                "financial_review_seconds": (isolated.get("consumer_audit") or {}).get("consumer_seconds"),
                                "launch_and_teardown_seconds": max(0.0, isolated["elapsed_seconds"] - boundary_times["namespace_total_seconds"]),
                                "retained_evidence_cleanup_seconds": None}
            publication = time.monotonic()
            os.mkdir(stage_name, 0o700, dir_fd=directory)
            stage = Path(output).parent / stage_name
            for filename, data in files.items():
                write_new(stage / filename, data, 0o644)
            # Proof is outside the legacy three-file review bundle.
            write_new(workspace / "verified.json", encoded(proof))
            stage_fd = open_beneath(directory, stage_name, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(stage_fd)
            finally:
                os.close(stage_fd)
            rename_noreplace(directory, stage_name, target_name)
            proof["timings"]["publication_seconds"] = time.monotonic() - publication
            proof["timings"]["total_seconds"] = time.monotonic() - start
            proof["status"] = "COMPLETE"
            proof["evidence_directory"] = str(workspace)
            write_new(workspace / "complete.json", encoded(proof))
            return proof
        except BaseException as exc:
            # Preserve the first original failure and abandoned work. No cleanup
            # traverses consumer-controlled links. SIGKILL leaves STARTED only.
            proof.update({"status": "FAILED", "error_type": type(exc).__name__, "error": str(exc)})
            write_new(workspace / "failed.json", encoded(proof))
            raise
