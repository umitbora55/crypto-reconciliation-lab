#!/usr/bin/env python3
"""Seal a clean Git revision and finite Gate4 evidence; verify every ZIP member.

Hashes prove byte identity, not independent source authority. Derived from the unchanged Gate3 packager; new Gate4 limits admit original
11.5MB synthetic inputs and complete raw trial ledgers. Generated databases and
WAL/shm/journal sidecars are explicitly omitted with exact identities, except
the named small pre-checkpoint portability witness copies described below. No public
source redistribution permission is inferred. This is a byte seal, not a
substitute for the separate independent trial/economic/statistical verifier.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
PRUNED = {"environment", "__pycache__", "pip-cache", "uv-cache", "extracted"}
MAX_MEMBERS = 30000
MAX_MEMBER_BYTES = 256 * 1024 * 1024
MAX_EXPANDED_BYTES = 2 * 1024 * 1024 * 1024
MAX_PORTABILITY_RAW_BYTES = 8 * 1024 * 1024
SECRET_DIRECTORIES = {".git", ".aws", ".ssh", ".gnupg"}
BASELINE = "c08114e847b8b0ab58f28d41917ba386878fa873"
GATE3_ARCHIVE = {"bytes": 102474747, "members": 13053, "sha256": "73949a1325de7b99c8b09a226b4deadf408c46a72c1cd6d9f3b4b1de814a7aa7"}


def sensitive_path(path):
    parts = PurePosixPath(path).parts
    name = parts[-1] if parts else ""
    return (any(part in SECRET_DIRECTORIES for part in parts)
            or name == ".env" or name.startswith(".env.")
            or name in {"credentials", "credentials.json", "tokens.json"}
            or PurePosixPath(name).suffix.lower() in {".pem", ".key", ".p12", ".pfx"})


def proof(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def account_metadata(path):
    """Recognize structured public account objects without logging their values."""
    if path.suffix.lower() not in {".json", ".txt", ".log", ".bin"} or path.stat().st_size > MAX_MEMBER_BYTES:
        return False
    try:
        data = json.loads(path.read_bytes())
    except (ValueError, UnicodeError, RecursionError):
        return False
    pending = [data]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if ({"login", "id"} <= item.keys()
                    or {"node_id", "avatar_url"} <= item.keys()):
                return True
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return False


def safe_name(name):
    if type(name) is not str:
        raise ValueError("archive member name must be text")
    path = PurePosixPath(name)
    if (not name or name == "." or path.is_absolute() or ".." in path.parts
            or "\\" in name or "\x00" in name or ":" in path.parts[0]
            or path.as_posix() != name):
        raise ValueError("unsafe archive member")
    return name


def database_payload(path, relative):
    """Classify known DB files; the three small raw portability copies are explicit.

    SQLite SHM has no universal magic signature. Its known raw-copy basename and
    the ordinary -shm suffix are checked; arbitrary renamed bytes cannot prove
    their origin. The exception preserves authored 30-receipt witness bytes only.
    """
    name = path.name.lower()
    raw_names = {"database.bin", "wal.bin", "shm.bin"}
    if relative.parts[-2:-1] == ("pre-checkpoint-raw",) and name in raw_names:
        return "SMALL_PORTABILITY_WITNESS" if path.stat().st_size <= MAX_PORTABILITY_RAW_BYTES else "DATABASE"
    if (path.suffix.lower() in {".sqlite3", ".sqlite", ".db"}
            or name.endswith(("-wal", "-shm", "-journal")) or name in raw_names):
        return "DATABASE"
    if path.suffix.lower() == ".bin":
        with path.open("rb") as stream:
            header = stream.read(16)
        if header == b"SQLite format 3\0" or header[:4] in {b"\x37\x7f\x06\x82", b"\x37\x7f\x06\x83"}:
            return "DATABASE"
    return None


def inventory(root):
    included, omitted = [], []
    for folder, directories, files in os.walk(root, followlinks=False):
        directories.sort()
        for name in list(directories):
            path = Path(folder) / name
            relative = path.relative_to(root)
            if path.is_symlink() or name in PRUNED or name in SECRET_DIRECTORIES or name.startswith(".venv") or relative.parts[-2:] in {("build", "source"), ("build", "sdist")}:
                directories.remove(name)
                omitted.append({"path": relative.as_posix(), "kind": "subtree", "reason": "Reinstallable environment, cache, duplicate build tree, or nonregular path; not dereferenced."})
        for name in sorted(files):
            path = Path(folder) / name
            relative = path.relative_to(root)
            if not stat.S_ISREG(path.lstat().st_mode):
                omitted.append({"path": relative.as_posix(), "reason": "Nonregular file; not dereferenced."})
                continue
            if sensitive_path(relative.as_posix()):
                omitted.append({"path": relative.as_posix(), "kind": "credential_path",
                                "reason": "Credential/private-key path: content is neither read nor archived."})
                continue
            row = {"path": relative.as_posix(), **proof(path)}
            database_kind = database_payload(path, relative)
            reason = None
            if (path.suffix.lower() in {".body", ".text", ".links"}
                    or (name.lower().startswith("sec-") and path.suffix.lower() == ".zip")):
                reason = "Downloaded public-source body/document: redistribution rights not inferred; original retained locally."
            elif database_kind == "DATABASE":
                reason = "Generated database or WAL/shm/journal sidecar: original exact bytes retained locally; logical snapshots and canonical outputs are separate included evidence."
            elif re.fullmatch(r"crypto-reconciliation-validation-gate[123]\.zip", name):
                reason = "Historical Gate1/2/3 archive is not duplicated; Gate3 external seal and fresh intake audit are retained."
            elif row["bytes"] > MAX_MEMBER_BYTES:
                if path.suffix.lower() in {".json", ".jsonl", ".csv"}:
                    raise ValueError("required raw record exceeds finite archive member limit: " + relative.as_posix())
                reason = "Payload exceeds the disclosed finite member limit; original retained locally."
            elif account_metadata(path):
                reason = "Raw API account metadata: original retained locally; values not rewritten or redistributed."
            if reason:
                omitted.append(dict(row, reason=reason))
            else:
                included.append(row)
    if not included:
        raise ValueError("empty evidence inventory")
    return included, omitted


def verify(archive, *, expected_commit=None, expected_sha256=None, expected_bytes=None, expected_members=None):
    if not stat.S_ISREG(archive.lstat().st_mode):
        raise ValueError("archive must be a regular file")
    outer = proof(archive)
    if expected_sha256 is not None and outer["sha256"] != expected_sha256:
        raise ValueError("external archive SHA256 mismatch")
    if expected_bytes is not None and outer["bytes"] != expected_bytes:
        raise ValueError("external archive byte count mismatch")
    with zipfile.ZipFile(archive) as zipped:
        names = zipped.namelist()
        if expected_members is not None and len(names) != expected_members:
            raise ValueError("external archive member count mismatch")
        if not names or len(names) > MAX_MEMBERS:
            raise ValueError("archive member count limit")
        if len(names) != len(set(names)):
            raise ValueError("duplicate ZIP names")
        if sum(member.file_size for member in zipped.infolist()) > MAX_EXPANDED_BYTES:
            raise ValueError("archive expanded size limit")
        for member in zipped.infolist():
            safe_name(member.filename)
            if member.file_size > MAX_MEMBER_BYTES or member.flag_bits & 1:
                raise ValueError("archive member size or encryption limit")
            mode = member.external_attr >> 16
            if member.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                raise ValueError("archive contains a nonregular member")
        if "archive-manifest.json" not in names:
            raise ValueError("missing archive manifest")
        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate manifest JSON field")
                result[key] = value
            return result
        manifest = json.loads(zipped.read("archive-manifest.json"), object_pairs_hook=unique_object)
        if (type(manifest) is not dict or manifest.get("format") != "validation-gate4-review-v1"
                or type(manifest.get("members")) is not list or not manifest["members"]):
            raise ValueError("missing nonempty Gate4 inventory")
        if not isinstance(manifest.get("repository_commit"), str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", manifest["repository_commit"]):
            raise ValueError("invalid Git commit identity")
        if expected_commit is not None and manifest["repository_commit"] != expected_commit:
            raise ValueError("externally selected commit mismatch")
        rows = manifest["members"]
        for row in rows:
            if (type(row) is not dict or set(row) != {"path", "bytes", "sha256"}
                    or type(row["bytes"]) is not int or row["bytes"] < 0
                    or type(row["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])):
                raise ValueError("malformed member identity")
        expected = [safe_name(row["path"]) for row in rows]
        if ("archive-manifest.json" in expected or len(expected) != len(set(expected))
                or set(names) != set(expected) | {"archive-manifest.json"}):
            raise ValueError("missing, duplicate or additional archive members")
        streamed = 0
        for row in rows:
            if row["bytes"] != zipped.getinfo(row["path"]).file_size:
                raise ValueError("declared member size mismatch")
            digest = hashlib.sha256()
            size = 0
            with zipped.open(row["path"]) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    size += len(block)
                    streamed += len(block)
                    if size > MAX_MEMBER_BYTES or streamed > MAX_EXPANDED_BYTES:
                        raise ValueError("streamed expansion limit")
                    digest.update(block)
            if size != row["bytes"] or digest.hexdigest() != row["sha256"]:
                raise ValueError("member identity mismatch: " + row["path"])
        # Complete member reads, including both manifests, validate ZIP CRCs.
        if "evidence-manifest.json" not in names:
            raise ValueError("missing Gate4 evidence manifest")
        evidence = json.loads(zipped.read("evidence-manifest.json"), object_pairs_hook=unique_object)
        if (type(evidence) is not dict or evidence.get("format") != "validation-gate4-evidence-v1"
                or evidence.get("repository_commit_at_seal") != manifest["repository_commit"]
                or evidence.get("gate3_baseline_commit") != BASELINE
                or evidence.get("gate3_archive_reference") != GATE3_ARCHIVE):
            raise ValueError("invalid Gate4 evidence source/baseline identity")
        files, source, omitted = evidence.get("files"), evidence.get("committed_source"), evidence.get("omitted")
        if not isinstance(files, list) or not files or not isinstance(source, list) or not source or not isinstance(omitted, list):
            raise ValueError("missing nonempty evidence/source inventory")
        member_rows = {row["path"]: row for row in rows}
        evidence_names, source_names, omitted_names = set(), set(), set()
        for row in files:
            if (type(row) is not dict or set(row) != {"path", "bytes", "sha256"}
                    or type(row["bytes"]) is not int or row["bytes"] < 0
                    or type(row["sha256"]) is not str
                    or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])):
                raise ValueError("malformed evidence identity")
            name = safe_name(row["path"])
            if name in evidence_names:
                raise ValueError("duplicate evidence identity")
            evidence_names.add(name)
            if member_rows.get("evidence/" + name) != {**row, "path": "evidence/" + name}:
                raise ValueError("evidence identity disagrees with archive members")
        for row in source:
            if (type(row) is not dict or set(row) != {"path", "git_blob", "git_mode"}
                    or row["git_mode"] not in {"100644", "100755"}
                    or type(row["git_blob"]) is not str
                    or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", row["git_blob"])):
                raise ValueError("malformed committed source identity")
            name = safe_name(row["path"])
            if name in source_names or sensitive_path(name):
                raise ValueError("duplicate or sensitive committed source path")
            source_names.add(name)
            if "source/" + name not in member_rows:
                raise ValueError("missing committed source member")
            raw = zipped.read("source/" + name)
            blob = b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
            digest = hashlib.sha1(blob).hexdigest() if len(row["git_blob"]) == 40 else hashlib.sha256(blob).hexdigest()
            if digest != row["git_blob"]:
                raise ValueError("Git source blob identity mismatch")
        for row in omitted:
            if type(row) is not dict or type(row.get("reason")) is not str or not row["reason"]:
                raise ValueError("malformed omission reason")
            name = safe_name(row.get("path"))
            if name in omitted_names or name in evidence_names:
                raise ValueError("duplicate or included omission identity")
            omitted_names.add(name)
            if ("sha256" in row) != ("bytes" in row):
                raise ValueError("partial omission byte identity")
            if "sha256" in row and (type(row["bytes"]) is not int or row["bytes"] < 0
                    or type(row["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])):
                raise ValueError("malformed omission byte identity")
        declared = {"evidence/" + n for n in evidence_names} | {"source/" + n for n in source_names} | {"evidence-manifest.json"}
        if declared != set(member_rows):
            raise ValueError("undeclared evidence or source member")
    return {"status": "PASS", "archive": str(archive), **outer,
            "verified_members": len(names), "verified_source_members": len(source_names),
            "verified_evidence_members": len(evidence_names), "omission_entries": len(omitted_names),
            "expanded_bytes": sum(member.file_size for member in zipped.infolist()),
            "repository_commit": manifest["repository_commit"], "authority": "BYTE_INTEGRITY_ONLY",
            "commit_binding_limit": "Source blob hashes are checked. Complete tree-to-commit correspondence additionally requires the independent Git audit; a manifest commit label alone is not that proof.",
            "external_pins_checked": {"commit": expected_commit, "sha256": expected_sha256,
                                      "bytes": expected_bytes, "members": expected_members}}


def package(evidence, output):
    if not evidence.is_dir() or evidence.is_symlink():
        raise ValueError("evidence must be a real directory")
    if os.path.lexists(output) or output.resolve().is_relative_to(evidence.resolve()):
        raise ValueError("output must be fresh and outside evidence")
    def clean_revision():
        status = subprocess.check_output(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=ROOT)
        if status:
            raise ValueError("source checkout has tracked or untracked changes")
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()

    commit = clean_revision()
    subprocess.run(["git", "merge-base", "--is-ancestor", BASELINE, commit], cwd=ROOT, check=True)
    for name in subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASELINE], cwd=ROOT, text=True).splitlines():
        baseline_blob = subprocess.check_output(["git", "rev-parse", BASELINE + ":" + name], cwd=ROOT)
        current_blob = subprocess.check_output(["git", "rev-parse", commit + ":" + name], cwd=ROOT)
        if baseline_blob != current_blob:
            raise ValueError("original Gate3 source changed: " + name)
    tree = subprocess.check_output(["git", "ls-tree", "-rz", "--full-tree", commit], cwd=ROOT)
    source_files = []
    for entry in tree.split(b"\0"):
        if not entry:
            continue
        metadata, raw_name = entry.split(b"\t", 1)
        mode, kind, blob = metadata.decode("ascii").split()
        name = raw_name.decode("utf-8")
        safe_name(name)
        if mode not in {"100644", "100755"} or kind != "blob" or sensitive_path(name):
            raise ValueError("tracked source contains a nonregular or credential path")
        source_files.append({"path": name, "git_blob": blob, "git_mode": mode})
    if not source_files:
        raise ValueError("empty committed source inventory")
    files, omitted = inventory(evidence)
    if len(source_files) + len(files) + 2 > MAX_MEMBERS:
        raise ValueError("archive member count limit")
    record = {"format": "validation-gate4-evidence-v1", "created_utc": datetime.now(timezone.utc).isoformat(), "repository_commit_at_seal": commit,
              "gate3_baseline_commit": BASELINE, "gate3_archive_reference": GATE3_ARCHIVE, "evidence_root": str(evidence), "files": files, "omitted": omitted,
              "committed_source": source_files,
              "run_identity": "Source members are read from immutable Git blobs at the seal commit. Per-run snapshots/hashes identify earlier execution; final seal is not retroactive execution evidence.",
              "archive_policy": {"max_members": MAX_MEMBERS, "max_member_bytes": MAX_MEMBER_BYTES,
                                 "max_expanded_bytes": MAX_EXPANDED_BYTES,
                                 "database_sidecars": "Omit and hash ordinary SQLite databases, -wal/-shm/-journal, named DB/WAL/SHM .bin copies and .bin SQLite/WAL headers. Arbitrary renamed SHM bytes have no universal magic detector.",
                                 "small_portability_raw_exception": "Retain exact pre-checkpoint-raw/{database,wal,shm}.bin portability witness copies, each at most 8 MiB; these are authored 30-receipt witnesses, not benchmark DBs or power-loss proof.",
                                 "oversize_raw_records": "Reject oversized JSON/JSONL/CSV rather than silently omitting required trial records."},
              "authority": "Byte identities only; independent evidence/financial/statistical verification is a separate gate."}
    output.mkdir(parents=True)
    index = output / "evidence-manifest.json"
    index.write_text(json.dumps(record, indent=2) + "\n")
    inputs = [(evidence / row["path"], "evidence/" + row["path"], row) for row in files]
    inputs.append((index, "evidence-manifest.json", proof(index)))
    archive = output / "crypto-reconciliation-validation-gate4.zip"
    partial = output / (archive.name + ".partial")
    members = []
    expanded = 0
    with zipfile.ZipFile(partial, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for row in source_files:
            raw = subprocess.check_output(["git", "cat-file", "blob", row["git_blob"]], cwd=ROOT)
            expanded += len(raw)
            if len(raw) > MAX_MEMBER_BYTES or expanded > MAX_EXPANDED_BYTES:
                raise ValueError("source expansion limit")
            name = "source/" + row["path"]
            zipped.writestr(name, raw)
            members.append({"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        for path, name, expected in inputs:
            safe_name(name)
            if not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError("nonregular archive input")
            actual = proof(path)
            if expected and any(actual[key] != expected[key] for key in ("bytes", "sha256")):
                raise ValueError("evidence changed during seal: " + name)
            expanded += actual["bytes"]
            if actual["bytes"] > MAX_MEMBER_BYTES or expanded > MAX_EXPANDED_BYTES:
                raise ValueError("evidence expansion limit")
            zipped.write(path, name)
            members.append({"path": name, **actual})
        zipped.writestr("archive-manifest.json", json.dumps({"format": "validation-gate4-review-v1", "repository_commit": commit, "members": members, "self_identity": "Outer archive SHA256 binds this manifest; no external trust authority claimed."}, indent=2) + "\n")
    result = verify(partial, expected_commit=commit)
    if clean_revision() != commit:
        raise ValueError("source revision changed during archive sealing")
    os.link(partial, archive)  # Atomic no-overwrite publication in the owned output directory.
    partial.unlink()
    result["archive"] = str(archive)
    (output / "archive-verification.json").write_text(json.dumps(result, indent=2) + "\n")
    (output / "archive.sha256").write_text(result["sha256"] + "  " + archive.name + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--expected-commit")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--expected-bytes", type=int)
    parser.add_argument("--expected-members", type=int)
    args = parser.parse_args()
    if args.verify and not (args.evidence or args.output):
        if not args.expected_commit:
            parser.error("verification requires caller-selected --expected-commit; outside size/SHA/member pins are recommended")
        result = verify(args.verify, expected_commit=args.expected_commit,
                        expected_sha256=args.expected_sha256, expected_bytes=args.expected_bytes,
                        expected_members=args.expected_members)
    elif args.evidence and args.output and not args.verify and not any((args.expected_commit, args.expected_sha256, args.expected_bytes, args.expected_members)):
        result = package(args.evidence.absolute(), args.output.absolute())
    else:
        parser.error("use --verify ARCHIVE or --evidence DIR --output NEW_DIR")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
