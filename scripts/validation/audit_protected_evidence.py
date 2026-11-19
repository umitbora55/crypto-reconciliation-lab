#!/usr/bin/env python3
"""Independent raw-artifact reader; imports no application or test modules.

This reader has its own fixed 19-case roster, reads SQLite into memory, compares
actual output bytes, and follows host-PID annotations in supplemental strace.
It never converts missing evidence into a successful control.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys


BASE = "19b19c7cd17bd0b7e6a93964044562c584f7e63a"
FIXTURE_SHA = "1a37873cd1ec44a2e498baedb26c71250fb15afa0cc85e65c21cb35cc3669133"
RUN_ID = "db050c7ea9ce4aec4f0a99ea47ecd3e32d30b2d10ec209ff31c12e8cc139115b"
NAMES = (
    "C01_WAL_backup_and_bounded_phase_cost",
    "C01_protected_metadata_acl_xattr_and_all_output_parity",
    "C02_actual_misconfigured_mounts_refuse_before_export",
    "C02_missing_contract_preflight_refuses",
    "C02_unprotected_unsealed_and_writable_handles",
    "C02_untrusted_parent_and_nonroot_supervisor",
    "C03_C04_real_consumer_concurrent_attacks_and_FD_isolation",
    "C03_actual_consumer_privilege_and_namespace_attacks",
    "C03_controlled_privileged_mutation_detected",
    "C03_import_source_concurrent_writer_detected_no_publication",
    "C03_sealed_anchor_rejects_retained_writable_fd_processes",
    "C04_real_process_inode_swap_after_pinned_open",
    "C04_symlink_hardlink_traversal_and_bind_mount_alias",
    "C05_existing_targets_and_publication_collision",
    "C06_WAL_sidecar_and_corrupt_snapshot",
    "C07_forged_consumer_output_rejected",
    "C08_controlled_failure_preserves_prior_output",
    "C08_live_supervisor_SIGKILL_reaps_detached_descendant",
    "C08_real_SIGKILL_before_atomic_publication",
)
EXPECTED_IDS = ["test_boundary.BoundaryTests.test_" + name for name in NAMES]
FILES = {"index.html", "summary.json", "manifest.json"}
METADATA = {"device", "inode", "size", "mode", "uid", "gid", "nlink",
            "atime_ns", "mtime_ns", "ctime_ns", "xattrs"}


def read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NOATIME | os.O_CLOEXEC)
    try:
        result = bytearray()
        while block := os.read(fd, 1024 * 1024):
            result.extend(block)
        return bytes(result)
    finally:
        os.close(fd)


def document(path):
    return json.loads(read(path))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def need(condition, reason):
    if not condition:
        raise AssertionError(reason)


def sqlite_rows(data):
    need(data[:16] == b"SQLite format 3\x00" and data[18:20] == b"\x01\x01", "DELETE SQLite header required")
    connection = sqlite3.connect(":memory:")
    try:
        connection.deserialize(data)
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA query_only=ON")
        need(connection.execute("PRAGMA user_version").fetchone() == (6,), "schema 6 required")
        need(connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)], "integrity_check failed")
        need(not connection.execute("PRAGMA foreign_key_check").fetchall(), "foreign key check failed")
        schema = list(connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"))
        result = {}
        for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            quoted = '"' + name.replace('"', '""') + '"'
            rows = []
            for row in connection.execute("SELECT * FROM " + quoted):
                rows.append(json.dumps([{"blob": value.hex()} if isinstance(value, bytes) else value
                                        for value in row], ensure_ascii=True, allow_nan=False, separators=(",", ":")))
            result[name] = sorted(rows)
        need({name: len(result[name]) for name in ("receipts", "runs", "findings", "evidence")} ==
             {"receipts": 30, "runs": 1, "findings": 6, "evidence": 60}, "financial row counts differ")
        row = connection.execute("SELECT id,payload FROM runs").fetchone()
        need(row[0] == RUN_ID and digest(row[1].encode()) == RUN_ID, "saved run payload identity differs")
        payload = json.loads(row[1])
        ids = sorted(row[0] for row in connection.execute("SELECT evidence_id FROM evidence WHERE run_id=?", (RUN_ID,)))
        need(ids == sorted(payload["evidence"]) and len(ids) == 60, "saved evidence IDs differ")
        return {"schema": schema, "tables": result, "run_id": RUN_ID, "evidence_ids": ids}
    finally:
        connection.close()


class Audit:
    def __init__(self):
        self.checks = []

    def check(self, name, operation):
        try:
            details = operation()
            self.checks.append({"id": name, "status": "PASS", "details": details})
        except FileNotFoundError as error:
            self.checks.append({"id": name, "status": "NOT_RUN", "error": str(error)})
        except (AssertionError, OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
            self.checks.append({"id": name, "status": "FAIL", "error_type": type(error).__name__, "error": str(error)})


def historical_bytes(repo, baseline):
    head = subprocess.check_output(["git", "-C", str(baseline), "rev-parse", "HEAD"], text=True).strip()
    need(head == BASE, "wrong historical checkout")
    names = subprocess.check_output(["git", "-C", str(baseline), "ls-files", "-z"]).decode().rstrip("\0").split("\0")
    differences = [name for name in names if not (repo / name).is_file() or read(repo / name) != read(baseline / name)]
    need(not differences, "historical files changed: " + repr(differences))
    return {"baseline_commit": head, "unchanged_tracked_files": len(names), "old_test_files": sum(name.startswith("tests/") for name in names)}


def roster_and_source(run, repo):
    protocol, result = document(run / "protocol.json"), document(run / "results.json")
    need(protocol["tests"] == EXPECTED_IDS, "preregistered roster differs from independent 19 IDs")
    records = result["tests"]
    need([item["test"] for item in records] == EXPECTED_IDS, "executed roster differs/duplicates/missing cases")
    need(all(item["status"] == "PASS" and item.get("error") is None for item in records), "non-PASS observation retained")
    need(document(run / "observations.json") == records, "observation ledger differs from results")
    need(result["protocol_sha256"] == digest(read(run / "protocol.json")), "protocol hash mismatch")
    need(result["status"] == "PASS" and result["source_unchanged_during_execution"] is True, "runner did not pass")
    log = read(run / "unittest.log").decode()
    for name in NAMES:
        need(re.search(r"^test_" + re.escape(name) + r" \(.*\) \.\.\. ok$", log, re.M), "missing successful test log: " + name)
    need(re.search(r"Ran 19 tests in .+\n\nOK\n", log), "unittest log completion differs")
    mismatches = [name for name, expected in protocol["source_sha256"].items()
                  if digest(read(repo / name)) != expected]
    need(not mismatches, "current source differs from executed bytes: " + repr(mismatches))
    package = Path(protocol["package_import"]).parent
    # Installed execution must match actual installed package bytes, not merely
    # the source directory whose test code the runner loaded.
    installed_mismatches = [name for name, expected in protocol["source_sha256"].items()
                           if name.startswith("crypto_reconciliation_lab/")
                           and digest(read(package / name.removeprefix("crypto_reconciliation_lab/"))) != expected]
    need(not installed_mismatches, "executed installed package differs: " + repr(installed_mismatches))
    return {"exact_test_ids": EXPECTED_IDS, "source_files": len(protocol["source_sha256"]),
            "package_import": str(package), "python": protocol["python"], "kernel": protocol["kernel"]}


def inventory_records(run):
    before, after = document(run / "inventory-before.json"), document(run / "inventory-after.json")
    need(set(before) == {"."}, "before inventory must describe the initially empty run root")
    files = 0
    for name, item in after.items():
        if "link" in item:
            need(os.readlink(run / name) == item["link"], "inventory symlink changed: " + name)
            continue
        need(METADATA <= set(item), "inventory omitted metadata: " + name)
        if "sha256" in item:
            data = read(run / name)
            need(digest(data) == item["sha256"] and len(data) == item["bytes"], "inventory file identity changed: " + name)
            files += 1
    return {"before_entries": len(before), "after_entries": len(after), "file_bytes_rehashed": files,
            "note": "Retained artifact atimes can change during later independent reading; source-consumption metadata equality is audited separately."}


def source_preservation(run):
    case = run / "test_C01_protected_metadata_acl_xattr_and_all_output_parity"
    before, after, proof = document(case / "before.json"), document(case / "after.json"), document(case / "proof.json")
    need(before == after and set(before) == {".", "snapshot.sqlite3"}, "source tree inventory changed during protected call")
    for value in before.values():
        need(METADATA <= set(value), "source metadata coverage incomplete")
    item = before["snapshot.sqlite3"]
    need(item["sha256"] == FIXTURE_SHA and item["xattrs"].get("user.crl") == b"preserve-this-value".hex(), "xattr fixture absent")
    need("system.posix_acl_access" in item["xattrs"], "ACL not exercised")
    need(proof["production"]["source_before"] == proof["production"]["source_after"], "source metadata equality missing")
    need({key: item[key] for key in METADATA} == proof["production"]["source_before"], "independent inventory/producer observations disagree")
    fd = os.open(case / "inputs/snapshot.sqlite3", os.O_RDONLY | os.O_NOATIME)
    try:
        actual_xattrs = {name: os.getxattr(fd, name).hex() for name in os.listxattr(fd)}
        need(actual_xattrs == item["xattrs"], "retained ACL/xattr no longer matches")
    finally:
        os.close(fd)
    return {"fields": sorted(METADATA), "preserved_xattrs": sorted(item["xattrs"]),
            "note": "Ordinary comparison export runs afterward and may change atime; equality applies to the captured protected-consumption interval."}


def completed_exports(run, oracle):
    observations = []
    for complete in sorted(run.rglob("complete.json")):
        proof = document(complete)
        need(proof["status"] == "COMPLETE", "complete record has wrong status")
        work, output = complete.parent, Path(proof["output"])
        actual = {}
        need(set(os.listdir(output)) == FILES, "published output inventory differs")
        for name in sorted(FILES):
            data = read(output / name)
            need(data == read(work / "reference-review" / name), "actual output/reference byte mismatch")
            need(data == read(work / "sandbox/output/review" / name), "published/consumer byte mismatch")
            actual[name] = {"sha256": digest(data), "bytes": len(data)}
        production = proof["production"]
        need(actual == proof["files"] == production["reference_files"], "claimed output hashes differ")
        data = read(work / "snapshot-delete.sqlite3")
        need(sqlite_rows(data) == oracle, "independently read financial tables/schema/evidence differ")
        need(digest(data) == production["snapshot_bytes"]["sha256"], "snapshot digest differs")
        need(production["seals"] == 15 and production["transport"] == production["transport_after"], "transport seals/metadata mismatch")
        attestation = document(work / "sandbox/sandbox-boundary.json")
        need(attestation == proof["consumer"]["trusted_attestation"], "trusted attestation/raw file mismatch")
        need(attestation["snapshot_before"] == attestation["snapshot_after"] and attestation["snapshot_unchanged"] is True, "consumed metadata changed")
        need(attestation["consumer_returncode"] == 0, "consumer did not exit successfully")
        consumed = attestation["snapshot_before"]
        need(METADATA | {"sha256"} <= set(consumed), "consumed metadata scope incomplete")
        need(consumed["sha256"] == digest(data) == attestation["sealed_anchor"]["sha256"], "source/anchor/consumed bytes differ")
        identities = [(item["device"], item["inode"]) for item in (production["source_before"], production["snapshot"], production["transport"], consumed)]
        need(len(set(identities)) == 4, "source/finalized/transport/consumed inode identities are not independent")
        need(consumed["uid"] == 0 and consumed["nlink"] == 1 and not consumed["mode"] & 0o222, "consumed inode permissions differ")
        raw_stat = (work / "sandbox/sandbox-boundary.json").stat()
        need(raw_stat.st_uid == 0 and stat.S_IMODE(raw_stat.st_mode) == 0o600, "attestation not root-private")
        audit = proof["consumer"]["consumer_audit"]
        need(audit["preflight"] == "PASS" and audit["uid"] == 65534 and audit["gid"] == 65534, "consumer credentials differ")
        need(all(int(audit["status"][name], 16) == 0 for name in ("CapEff", "CapPrm", "CapInh", "CapAmb", "CapBnd")), "consumer capability retained")
        need(audit["status"]["NoNewPrivs"] == "1" and audit["status"]["Seccomp"] == "2", "consumer privilege controls missing")
        need(set(audit["inherited_fds"]) == {"0", "1", "2"}, "consumer inherited an extra descriptor")
        need(audit["snapshot_identity"] == list(identities[-1]), "consumer opened the wrong inode")
        need({"ro", "noatime", "nosuid", "nodev"} <= set(audit["snapshot_mount"][5].split(",")), "consumer mount flags differ")
        config = document(work / "sandbox/sandbox-config.json")
        need(all(audit["namespaces"][name] != value for name, value in config["host_namespaces"].items()), "host namespace retained")
        observations.append({"complete": str(complete), "output": str(output), "input_kind": production["input_kind"],
                             "identities": identities, "files": actual})
    need(len(observations) >= 7, "positive export scope incomplete")
    case = run / "test_C01_protected_metadata_acl_xattr_and_all_output_parity"
    need(all(read(case / "ordinary" / name) == read(case / "review" / name) for name in FILES), "ordinary/protected canonical three-file parity differs")
    return {"independently_verified_exports": observations, "financial_counts": {"receipts": 30, "runs": 1, "findings": 6, "evidence": 60}}


def negative_controls(run):
    rows = document(run / "test_C03_sealed_anchor_rejects_retained_writable_fd_processes/concurrent-sealed-writers.json")
    need(len(rows) == 4, "four retained-FD processes missing")
    for row in rows:
        value = json.loads(row["stdout"])
        need(row["returncode"] == 0 and not row["stderr"] and value == {"uid": 65534, "attempts": 100, "denied": 100, "errnos": [1]}, "retained writable-FD attacks not EPERM")
    case = run / "test_C03_C04_real_consumer_concurrent_attacks_and_FD_isolation/sandbox/output"
    for index in range(4):
        attempts = document(case / f"writer-{index}.json")
        need(len(attempts) == 400, "concurrent attacker scope incomplete")
        allowed = {"write": {30}, "rename": {18, 30}, "link": {18}, "traverse": {2, 13}}
        need(all(operation in allowed and error in allowed[operation] for operation, error in attempts), "unexpected attacker errno")
        need(all(sum(op == name for op, _ in attempts) == 100 for name in allowed), "operation roster differs")
    probe = document(run / "test_C03_actual_consumer_privilege_and_namespace_attacks/privilege-attacks/output/attacks.json")
    expected = {"snapshot_writable_open": {30}, "snapshot_truncate": {30}, "snapshot_chmod": {30},
                "snapshot_utime": {30}, "snapshot_unlink": {30}, "snapshot_rename": {18, 30},
                "snapshot_hardlink_alias": {18}, "live_wal_visibility": {2, 13}, "host_tmp_visibility": {2, 13},
                "supervisor_fd_visibility": {2, 13}, "regain_root": {1}, "new_user_namespace": {1},
                "clone_user_namespace": {1}, "clone3": {38}}
    need({item["attack"] for item in probe["observations"]} == set(expected) and len(probe["observations"]) == 14, "privilege attack roster differs")
    need(all(item["status"] == "EXPECTED_REJECTION" and item["errno"] in expected[item["attack"]] for item in probe["observations"]), "privilege attack unexpected outcome")
    need(probe["snapshot_before"] == probe["snapshot_after"] == FIXTURE_SHA, "attack changed snapshot")
    need(len(probe["waited"]) == 3 and all(status == 0 for _, status in probe["waited"]), "concurrent privilege attackers not reaped")
    malformed = run / "test_C02_actual_misconfigured_mounts_refuse_before_export"
    for name in ("writable-root", "atime-root"):
        value = document(malformed / name / "result.json")
        process = value["process"]
        need(value["status"] == "EXPECTED_REJECTION" and process["returncode"] != 0 and "ISOLATION_ROOT" in process["stderr"], "misconfigured mount not rejected")
        need(process["consumer_audit"] is None and not (malformed / name / "workspace/output/review").exists(), "exporter started under wrong mount")
        need(digest(read(malformed / name / "namespace_worker.py")) == value["fault_worker_sha256"], "fault-injection code identity differs")
    rejected = []
    for path in sorted(run.rglob("*.rejection.json")):
        value = document(path)
        need(value["status"] == "EXPECTED_REJECTION" and value["message"], "missing rejection details")
        rejected.append({"file": str(path), **value})
    need(len(rejected) >= 12, "negative artifact coverage incomplete")
    target = run / "test_C05_existing_targets_and_publication_collision"
    need(read(target / "old-file") == b"previous evidence" and read(target / "old-directory/prior.txt") == b"previous evidence", "old target overwritten")
    need(os.readlink(target / "dangling") == "missing-previous-evidence" and read(target / "collision/prior") == b"retain", "collision/dangling target overwritten")
    return {"retained_fd_denials": 400, "concurrent_path_denials": 1600, "privilege_cases": 14, "rejections": rejected}


def kill_controls(run):
    live = document(run / "test_C08_live_supervisor_SIGKILL_reaps_detached_descendant/kill/result.json")
    need(live["status"] == "PASS" and live["supervisor_signal"] == 9 and live["supervisor_wait_status"] == 9, "real supervisor SIGKILL absent")
    need(live["survivors"] == [] and len(live["processes_before"]) >= 5 and live["ready"], "process lifetime proof incomplete")
    need(all(item is not None for item in live["processes_before"]), "process missing before kill")
    need(sum(item["uid"] == ["65534"] * 4 for item in live["processes_before"]) >= 2, "consumer+detached process not observed nonroot")
    need(not live["published_review_exists"] and live["previous_evidence_unchanged"], "kill exposed output or changed sentinel")
    for path, expected in live["sources"].items():
        need(digest(read(Path(path))) == expected, "kill helper/runtime source identity changed")
    publication = document(run / "test_C08_real_SIGKILL_before_atomic_publication/kill.json")
    need(publication["exit"] == -9 and publication["signal"] == "SIGKILL" and publication["final_output_absent"] and publication["previous_evidence_preserved"], "prepublication SIGKILL control failed")
    need(not (run / "test_C08_real_SIGKILL_before_atomic_publication/interrupted").exists(), "interrupted output published")
    need(read(run / "test_C08_real_SIGKILL_before_atomic_publication/previous/evidence.txt") == b"never replace", "prior evidence changed")
    return {"live_supervisor": live, "prepublication": publication,
            "scope": "Lifetime test previous proof is a sentinel; atomic-publication test preserves a separate prior evidence directory."}


def kernel_trace(folder, repo):
    command, protocol, result = document(folder / "command.json"), document(folder / "protocol.json"), document(folder / "result.json")
    need("--decode-pids=pidns" in command["argv"], "host PID annotations missing")
    need(result["status"] == "PASS" and result["testsRun"] == 2 and result["sources_unchanged"], "supplemental tests failed")
    need(result["fixture_after"] == protocol["fixture_before"], "original fixture metadata changed")
    need(digest(read(folder / "runner.py")) == command["runner_sha256"], "trace helper identity differs")
    need(all(digest(read(repo / name)) == value for name, value in protocol["sources"].items()), "trace used different source bytes")
    traces = {int(path.name.rsplit(".", 1)[1]): read(path).decode(errors="replace").splitlines()
              for path in (folder / "trace").glob("access.*")}
    consumers = {}
    for pid, lines in traces.items():
        starts = [index for index, line in enumerate(lines) if line.startswith("execve(") and '"--consumer"' in line and line.endswith("= 0")]
        if starts:
            need(len(starts) == 1, "consumer re-exec ambiguity")
            prefix = "\n".join(lines[:starts[0]])
            need("setresuid(65534, 65534, 65534)" in prefix and "close_range(3, 4294967295, 0)" in prefix, "privilege/FD setup not seen in kernel trace")
            need("PR_SET_SECCOMP" in prefix and "PR_SET_NO_NEW_PRIVS" in prefix, "seccomp/NNP not observed")
            consumers[pid] = lines[starts[0] + 1:]
    need(len(consumers) == 2, "two actual consumer execs required")
    descendants = {}
    queue = list(consumers.items())
    while queue:
        parent, lines = queue.pop()
        for line in lines:
            if line.startswith(("clone(", "clone3(", "fork(", "vfork(")):
                match = re.search(r"= \d+ /\* (\d+) in strace's PID NS \*/", line)
                if match:
                    child = int(match.group(1))
                    need(child in traces, "descendant trace missing")
                    if child not in descendants:
                        descendants[child] = traces[child]
                        queue.append((child, traces[child]))
    need(len(descendants) == 4, "four real concurrent attacker descendants required")
    snapshot_reads, failed_attacks, hidden_source_attempts = 0, 0, 0
    for pid, lines in (consumers | descendants).items():
        for line in lines:
            if line.startswith(("open(", "openat(", "openat2(")):
                success = re.search(r"= [0-9]+(?:\s|$)", line) is not None
                if '"/input/snapshot.sqlite3"' in line:
                    if success:
                        need("O_RDONLY" in line and not any(flag in line for flag in ("O_RDWR", "O_WRONLY", "O_CREAT", "O_TRUNC")), "consumer acquired writable snapshot FD")
                        snapshot_reads += 1
                if "/var/tmp/" in line and (".sqlite3" in line or "crl-protected" in line):
                    need(not success, "consumer successfully opened hidden host source/staging")
                    hidden_source_attempts += 1
            if pid in descendants and line.startswith(("open(", "openat(", "openat2(", "link(", "linkat(", "rename(", "renameat(", "renameat2(")):
                if "/input/snapshot.sqlite3" in line or "/proc/1/root/var/tmp/" in line:
                    need("= -1 " in line and any(name in line for name in ("EROFS", "EXDEV", "ENOENT", "EACCES")), "attacker syscall did not fail for expected protection")
                    failed_attacks += 1
    need(snapshot_reads >= 14, "actual exporter repeated snapshot opens not observed")
    need(failed_attacks == 1600 and hidden_source_attempts >= 400, "attacker kernel coverage incomplete")
    mount_events = [line for lines in traces.values() for line in lines
                    if line.startswith("mount(") and all(flag in line for flag in ("MS_RDONLY", "MS_REMOUNT", "MS_NOATIME")) and line.endswith("= 0")]
    need(len(mount_events) >= 2, "successful readonly/noatime root mounts not observed")
    return {"consumer_host_pids": sorted(consumers), "attacker_host_pids": sorted(descendants),
            "snapshot_readonly_opens": snapshot_reads, "denied_attack_syscalls": failed_attacks,
            "denied_hidden_source_opens": hidden_source_attempts, "readonly_noatime_mount_events": len(mount_events),
            "producer_live_WAL_access": "Expected producer access is not classified as consumer access."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--run", type=Path, action="append", required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--pidns-trace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit = Audit()
    oracle = None
    def reference():
        nonlocal oracle
        data = read(args.fixture)
        need(digest(data) == FIXTURE_SHA, "reference snapshot identity differs")
        oracle = sqlite_rows(data)
        return {"sha256": digest(data), "run_id": oracle["run_id"], "tables": len(oracle["tables"]), "evidence_ids": oracle["evidence_ids"]}
    audit.check("historical_source_bytes", lambda: historical_bytes(args.repo, args.baseline))
    audit.check("independent_financial_reference", reference)
    for run in args.run:
        for name, operation in (("exact_roster_and_source", lambda r=run: roster_and_source(r, args.repo)),
                                ("full_inventory_records", lambda r=run: inventory_records(r)),
                                ("source_metadata_acl_xattr", lambda r=run: source_preservation(r)),
                                ("canonical_outputs_financial_attestations", lambda r=run: completed_exports(r, oracle)),
                                ("negative_controls", lambda r=run: negative_controls(r)),
                                ("real_SIGKILL_controls", lambda r=run: kill_controls(r))):
            audit.check(run.name + ":" + name, operation)
    audit.check("supplemental_PID_mapped_kernel_trace", lambda: kernel_trace(args.pidns_trace, args.repo))
    result = {"format": "independent-protected-evidence-audit-v1", "auditor": str(Path(__file__).resolve()),
              "auditor_sha256": digest(read(__file__)), "argv": sys.argv, "checks": audit.checks,
              "outside_scope": {name: "NOT_RUN" for name in ("hostile_host_root", "physical_power_loss", "non_Linux", "x86_64_execution", "institutional_financial_truth")}}
    result["status"] = "PASS" if all(item["status"] == "PASS" for item in audit.checks) else "FAIL_OR_NOT_RUN"
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"status": result["status"], "output": str(args.output),
                      "nonpassing": [item for item in audit.checks if item["status"] != "PASS"]}, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
