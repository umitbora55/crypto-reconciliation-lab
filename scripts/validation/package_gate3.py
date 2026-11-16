#!/usr/bin/env python3
"""Seal a clean Git revision and finite Gate3 evidence; verify every ZIP member.

Hashes prove byte identity, not independent source authority. Official numeric
Treasury API bodies may be included under the saved Fiscal Data reuse terms.
Other downloaded public-source bodies stay local with their exact identities.
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
MAX_MEMBERS = 50000
MAX_MEMBER_BYTES = 32 * 1024 * 1024
MAX_EXPANDED_BYTES = 1024 * 1024 * 1024
SECRET_DIRECTORIES = {".git", ".aws", ".ssh", ".gnupg"}
TREASURY_BODY = re.compile(r"dts-(?:operating_cash_balance|deposits_withdrawals_operating_cash)-\d{4}-\d{2}(?:-page-\d+)?\.body\Z")


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
    if path.suffix != ".json" or path.stat().st_size > MAX_MEMBER_BYTES:
        return False
    try:
        data = json.loads(path.read_bytes())
    except (ValueError, UnicodeError):
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
            reason = None
            if ("raw" in relative.parts or path.suffix in {".body", ".text", ".links"}
                    or (name.lower().startswith("sec-") and path.suffix == ".zip")) and not (
                    "public-data" in path.parts and path.parent.name == "raw"
                    and TREASURY_BODY.fullmatch(name)):
                reason = "Downloaded public-source body/document: redistribution rights not inferred; retained locally for manual import and audit."
            elif path.suffix in {".sqlite3", ".db"} or row["bytes"] > 8 * 1024 * 1024:
                reason = "Large/generated payload: exact bytes retained locally; omitted from compact review archive."
            elif account_metadata(path):
                reason = "Raw API account metadata: original retained locally; values not rewritten or redistributed."
            if reason:
                omitted.append(dict(row, reason=reason))
            else:
                included.append(row)
    if not included:
        raise ValueError("empty evidence inventory")
    return included, omitted


def verify(archive):
    if not stat.S_ISREG(archive.lstat().st_mode):
        raise ValueError("archive must be a regular file")
    with zipfile.ZipFile(archive) as zipped:
        names = zipped.namelist()
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
        if (type(manifest) is not dict or manifest.get("format") != "validation-gate3-review-v1"
                or type(manifest.get("members")) is not list or not manifest["members"]):
            raise ValueError("missing nonempty Gate3 inventory")
        if not isinstance(manifest.get("repository_commit"), str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", manifest["repository_commit"]):
            raise ValueError("invalid Git commit identity")
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
        # Reading each full member above (including the manifest) checked CRC.
    return {"status": "PASS", "archive": str(archive), **proof(archive), "verified_members": len(names), "repository_commit": manifest["repository_commit"], "authority": "BYTE_INTEGRITY_ONLY"}


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
    record = {"format": "validation-gate3-evidence-v1", "created_utc": datetime.now(timezone.utc).isoformat(), "repository_commit_at_seal": commit,
              "gate2_starting_commit": "6876b384030a7cdab1d35445f66bf874768dcfce", "evidence_root": str(evidence), "files": files, "omitted": omitted,
              "committed_source": source_files,
              "run_identity": "Source members are read from immutable Git blobs at the seal commit. Per-run snapshots/hashes identify earlier execution; final seal is not retroactive execution evidence.",
              "treasury_numeric_reuse_basis": "public-data/access-01/raw/treasury-about.body (local, hashed in omissions); official Fiscal Data allows copy/adapt/redistribute, commercial and noncommercial."}
    output.mkdir(parents=True)
    index = output / "evidence-manifest.json"
    index.write_text(json.dumps(record, indent=2) + "\n")
    inputs = [(evidence / row["path"], "evidence/" + row["path"], row) for row in files]
    inputs.append((index, "evidence-manifest.json", proof(index)))
    archive = output / "crypto-reconciliation-validation-gate3.zip"
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
        zipped.writestr("archive-manifest.json", json.dumps({"format": "validation-gate3-review-v1", "repository_commit": commit, "members": members, "self_identity": "Outer archive SHA256 binds this manifest; no external trust authority claimed."}, indent=2) + "\n")
    result = verify(partial)
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
    args = parser.parse_args()
    if args.verify and not (args.evidence or args.output):
        result = verify(args.verify)
    elif args.evidence and args.output and not args.verify:
        result = package(args.evidence.resolve(), args.output.absolute())
    else:
        parser.error("use --verify ARCHIVE or --evidence DIR --output NEW_DIR")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
