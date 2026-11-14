"""Build an allowlisted sdist, then a wheel from its safely extracted contents.

Requires the pinned build-only requirements; installs nothing into the invoking
environment. Application execution belongs to verify_release.py. No publication.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from email.parser import BytesParser
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tarfile
import time
import tomllib
from urllib.parse import unquote
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.8.2"
TOP_FILES = ("README.md", "AGENTS.md", "LICENSE", "pyproject.toml", "MANIFEST.in", ".gitignore", "requirements-build.txt", "requirements-auth.txt")
SCRIPTS = ("build_release.py", "reproduce_review.py", "verify_release.py",
           "release_test_scope.py", "release_financial_scope.py", "release_admission_scope.py",
           "run_ab_stage3_3.py", "ab_worker_stage3_3.py", "ab_retention_stage3_3.py", "measure_stage3_3.py")
DOCS = ("docs/model_contract.md", "docs/correction_semantics.md", "docs/problem_evidence.md",
        "docs/stage2/baseline-schema.json", "docs/stage5/experiment_contract.md", "docs/stage5/ai_constraints.txt",
        "docs/stage6/five-minute-review.md", "docs/stage6/technical-presentation-tr.md",
        "docs/stage6/claim-evidence.md", "docs/stage6/historical-evidence.md",
        "docs/stage6/verification-guide.md", "docs/stage6/build-contract.md",
        "docs/stage6/ci.md", "docs/stage6/financial-reference.json",
        "docs/stage6_1/scope-contract.md", "docs/stage6_1/release-guide.md", "docs/stage6_1/financial-scope.md",
        "docs/showcase/README.tr.md",
        "docs/showcase/case-study.svg",
        "docs/showcase/architecture.svg",
        "docs/showcase/demo-overview.png",
        "docs/showcase/assets-manifest.json",
        "contracts/release-tests-baseline-0.6.0.json", "contracts/release-test-scope-0.6.1.json",
        "contracts/release-test-scope-0.7.0.json", "contracts/admission-recovery-scope-v1.json",
        "docs/stage9/admission-contract.md", "docs/stage9/decisions.md",
        "docs/stage9/recovery-report.md", "docs/stage9/fixture-changes.md", "docs/stage9/HANDOFF.md",
        "contracts/release-test-scope-0.7.1.json", "contracts/admission-recovery-scope-v2.json",
        "crypto_reconciliation_lab/admission/recovery_scope_v2.json",
        "tests/fixtures/admission-semantic-report-v2.json",
        "docs/stage9_1/S9-F1.md", "docs/stage9_1/S9-F2.md", "docs/stage9_1/decisions.md",
        "docs/stage9_1/fixture-changes.md", "docs/stage9_1/HANDOFF.md",
        "contracts/release-test-scope-0.8.0.json",
        "contracts/release-test-scope-0.8.1.json",
        "contracts/release-test-scope-0.8.2.json",
        "docs/stage10/fixture-changes.md",
        "contracts/source-auth-scope-v1.json",
        "crypto_reconciliation_lab/source_auth/experiment_scope_v1.json")
REQUIRED = {*TOP_FILES, *("scripts/" + name for name in SCRIPTS), *DOCS,
            "fixtures/stage1_history.json", "fixtures/stage3_3_schema2_history.json",
            "tests/review_fixtures.py", "tests/triage_model_fixtures.py", "tests/triage_scope_fixtures.py"}


def file_entry(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".writing")
    with temporary.open("xb") as stream:
        stream.write(encoded(value))
    temporary.replace(path)


def safe_name(name):
    if (not isinstance(name, str) or not name or "\\" in name or "\x00" in name
            or PurePosixPath(name).is_absolute() or re.match(r"^[A-Za-z]:", name)
            or any(part in ("", ".", "..") for part in name.split("/"))):
        raise ValueError("ARCHIVE_PATH: unsafe member " + repr(name))
    return name


def permitted(name):
    safe_name(name)
    path = PurePosixPath(name)
    return (not any(part in (".git", "__pycache__", ".DS_Store", "node_modules", "backup", "backups", "work", "build", "dist")
                    or part.startswith(".venv") or part.endswith(".egg-info") for part in path.parts)
            and not path.name.startswith(".env")
            and path.suffix.lower() not in (".db", ".sqlite", ".sqlite3", ".pyc", ".key", ".pem", ".bak", ".zip", ".whl", ".gz")
            and not path.name.endswith(("-wal", "-shm", "-journal")))


def regular_bytes(path):
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("SOURCE_TYPE: regular file required: " + str(path))
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        data = stream.read()
        after_fd = os.fstat(stream.fileno())
    after = path.lstat()
    key = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns)
    if key(before) != key(opened) or key(before) != key(after_fd) or key(before) != key(after) or len(data) != before.st_size:
        raise ValueError("SOURCE_CHANGED: " + str(path))
    return data


def selected_files(root):
    root = Path(root)
    names = set(REQUIRED)
    patterns = (("crypto_reconciliation_lab", {".py", ".html", ".css", ".js"}),
                ("tests", {".py"}), ("examples/triage-review", {".json", ".md"}),
                ("docs/stage6/evidence", {".json", ".md"}),
                ("docs/stage10", {".md"}),
                ("docs/stage10_1", {".md"}),
                ("docs/stage10_2", {".md"}),
                (".github/workflows", {".yml", ".yaml"}))
    for folder, suffixes in patterns:
        for path in (root / folder).rglob("*"):
            name = path.relative_to(root).as_posix()
            if path.is_file() and path.suffix in suffixes and permitted(name):
                names.add(name)
    missing = [name for name in sorted(names) if not (root / name).is_file()]
    if missing:
        raise ValueError("RELEASE_INPUT_MISSING: " + ", ".join(missing))
    if not any(name.startswith("examples/triage-review/") for name in names):
        raise ValueError("RELEASE_INPUT_MISSING: portable example")
    if not any(name.startswith(".github/workflows/") for name in names):
        raise ValueError("RELEASE_INPUT_MISSING: prepared workflow")
    return sorted(names)


def check_links(root):
    checked = []
    paths = [Path(root) / "README.md", *(Path(root) / "docs/stage6").glob("*.md"),
             *(Path(root) / "docs/stage6_1").glob("*.md"),
             *(Path(root) / "docs/stage9").glob("*.md"),
             *(Path(root) / "docs/stage9_1").glob("*.md"),
             *(Path(root) / "docs/stage10").glob("*.md"),
             *(Path(root) / "docs/stage10_1").glob("*.md"),
             *(Path(root) / "docs/stage10_2").glob("*.md")]
    for path in paths:
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", target) or target.startswith("#"):
                continue
            local = unquote(target.strip("<>").split("#", 1)[0])
            destination = (path.parent / local).resolve()
            if not destination.is_relative_to(Path(root).resolve()) or not destination.exists():
                raise ValueError("DOCUMENT_LINK: missing or external local target: " + str(path) + " -> " + target)
            checked.append({"document": path.relative_to(root).as_posix(), "target": target})
    return checked


def scope_helper(name):
    """Resolve trusted sibling validators even under -I or import-by-file tests."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_command(record, output, name, argv, cwd):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    row = {"name": name, "argv": list(map(str, argv)), "cwd": str(cwd),
           "started_at": datetime.now(timezone.utc).isoformat(), "status": "STARTED", "PYTHONPATH_removed": True}
    record["commands"].append(row)
    write_json(output / "release.json", record)
    start = time.monotonic()
    result = subprocess.run(row["argv"], cwd=cwd, env=env, capture_output=True, text=True)
    row.update(exit_code=result.returncode, seconds=time.monotonic() - start, status="FINISHED")
    for kind, text in (("stdout", result.stdout), ("stderr", result.stderr)):
        path = output / "logs" / (name + "." + kind + ".txt")
        path.write_text(text, encoding="utf-8")
        row[kind] = {"path": path.relative_to(output).as_posix(), **file_entry(text.encode())}
    write_json(output / "release.json", record)
    if result.returncode:
        raise RuntimeError("BUILD_COMMAND_FAILED: " + name + " exit " + str(result.returncode))
    return result


def extract_sdist(archive, destination, expected):
    destination = Path(destination)
    if os.path.lexists(destination):
        raise FileExistsError("Extraction destination must be new")
    with tarfile.open(archive, "r:gz") as stream:
        entries, roots, seen = {}, set(), set()
        members = stream.getmembers()
        if len(members) > 10000 or sum(m.size for m in members) > 128 * 1024 * 1024:
            raise ValueError("ARCHIVE_LIMIT: sdist too large")
        for member in members:
            name = safe_name(member.name.rstrip("/") if member.isdir() else member.name)
            if name in seen or member.size < 0 or not (member.isdir() or member.isfile()):
                raise ValueError("ARCHIVE_TYPE: duplicate, link or special member")
            seen.add(name)
            parts = PurePosixPath(name).parts
            roots.add(parts[0])
            if member.isfile():
                if len(parts) < 2:
                    raise ValueError("ARCHIVE_LAYOUT: one top-level directory required")
                relative = "/".join(parts[1:])
                generated = relative == "PKG-INFO" or relative == "setup.cfg" or (
                    relative.startswith("crypto_reconciliation_lab.egg-info/")
                    and PurePosixPath(relative).name in ("PKG-INFO", "SOURCES.txt", "dependency_links.txt", "entry_points.txt", "requires.txt", "top_level.txt"))
                if relative not in expected and not generated:
                    raise ValueError("ARCHIVE_UNEXPECTED: " + relative)
                data = stream.extractfile(member).read()
                if relative in expected and file_entry(data) != expected[relative]:
                    raise ValueError("ARCHIVE_CHANGED: " + relative)
                entries[relative] = file_entry(data)
        if len(roots) != 1 or not set(expected) <= entries.keys():
            raise ValueError("ARCHIVE_MISSING: sdist dropped selected source/test/fixture files")
        destination.mkdir(parents=True)
        # Only prevalidated regular bytes are written; tarfile.extractall is not used.
        for member in members:
            if member.isfile():
                path = destination / member.name
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as target:
                    target.write(stream.extractfile(member).read())
    return destination / next(iter(roots)), entries


def inspect_wheel(path, source):
    expected = {p.relative_to(source).as_posix(): file_entry(regular_bytes(p))
                for p in (Path(source) / "crypto_reconciliation_lab").rglob("*")
                if p.is_file() and permitted(p.relative_to(source).as_posix())}
    with zipfile.ZipFile(path) as archive:
        entries, seen = {}, set()
        if len(archive.infolist()) > 1000 or sum(m.file_size for m in archive.infolist()) > 32 * 1024 * 1024:
            raise ValueError("ARCHIVE_LIMIT: wheel too large")
        for member in archive.infolist():
            name = safe_name(member.filename)
            if name in seen or member.is_dir() or stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError("WHEEL_TYPE: duplicate/directory/link member")
            seen.add(name)
            if not name.startswith(("crypto_reconciliation_lab/", f"crypto_reconciliation_lab-{VERSION}.dist-info/")) or not permitted(name):
                raise ValueError("WHEEL_SCOPE: " + name)
            entries[name] = file_entry(archive.read(name))
        if ({name for name in entries if name.startswith("crypto_reconciliation_lab/")} != set(expected)
                or any(entries.get(name) != proof for name, proof in expected.items())):
            raise ValueError("WHEEL_BYTES: application or review assets changed/missing")
        meta = BytesParser().parsebytes(archive.read(f"crypto_reconciliation_lab-{VERSION}.dist-info/METADATA"))
        if meta["Version"] != VERSION or meta["Requires-Python"] != ">=3.12" or meta["Name"] != "crypto-reconciliation-lab":
            raise ValueError("WHEEL_METADATA: version/minimum Python mismatch")
        dependencies = meta.get_all("Requires-Dist", [])
        if dependencies != ['scikit-learn==1.9.1; extra == "ai"',
                            'cryptography==50.0.2; extra == "auth"',
                            'cffi==2.1.1; extra == "auth"', 'pycparser==3.12; extra == "auth"']:
            raise ValueError("WHEEL_METADATA: runtime dependency contract changed: " + repr(dependencies))
        entrypoints = archive.read(f"crypto_reconciliation_lab-{VERSION}.dist-info/entry_points.txt").decode()
        if "crypto-reconciliation-lab = crypto_reconciliation_lab.cli:main" not in entrypoints:
            raise ValueError("WHEEL_METADATA: CLI entrypoint missing")
    return entries, {"name": meta["Name"], "version": meta["Version"], "requires_python": meta["Requires-Python"], "requires_dist": dependencies}


def build(output, root=ROOT):
    root, output = Path(root).resolve(), Path(output).expanduser().absolute()
    if os.path.lexists(output):
        raise FileExistsError("OUTPUT_EXISTS: choose a new build directory")
    resolved = output.resolve()
    protected = [root / folder for folder in ("crypto_reconciliation_lab", "tests", "scripts", "fixtures", "examples", "docs", ".github", "review")]
    protected += [p for p in root.iterdir() if p.is_dir() and p.name.startswith("stage") and p.name.endswith("-output") and p.name != "stage6_1-output"]
    protected = [path.resolve() for path in protected]
    if resolved == root or any(resolved == path or resolved.is_relative_to(path) for path in protected):
        raise ValueError("OUTPUT_SOURCE_COLLISION: output lies in a protected source/history tree")
    # Use the checked canonical path for writes too; lexical '..' paths must not
    # create intermediate directories inside protected trees while traversing.
    output = resolved
    names = selected_files(root)
    config = tomllib.loads((root / "pyproject.toml").read_text())
    if config["project"]["version"] != VERSION or config["project"]["requires-python"] != ">=3.12":
        raise ValueError(f"RELEASE_METADATA: expected {VERSION} / Python >=3.12")
    output.mkdir(parents=True)
    (output / "logs").mkdir()
    record = {"status": "RUNNING", "commands": [], "format": "stage6-build-v1", "package": VERSION,
              "invocation": [sys.executable, *sys.orig_argv[1:]], "cwd": str(Path.cwd()), "interpreter": sys.executable,
              "source_checkout": str(root), "network_scope": "Build isolation may download pinned build dependencies; no publication.",
              "byte_reproducible_wheel_claim": False}
    write_json(output / "release.json", record)
    try:
        source = output / "source"
        source.mkdir()
        manifest = {}
        for name in names:
            data = regular_bytes(root / name)
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            manifest[name] = file_entry(data)
        record["source_manifest"] = manifest
        record["document_links"] = check_links(source)
        # Keep the established link-check boundary before scope preflight. Both
        # checks precede any external build command and cannot refresh contracts.
        record["test_scope"] = scope_helper("release_test_scope").validate_test_files(source)
        admission = scope_helper("release_admission_scope")
        admission.load_scope(source)
        record["admission_scope"] = admission.identity()
        financial = scope_helper("release_financial_scope")
        financial.load_financial_reference(source / financial.REFERENCE_PATH)
        record["financial_reference"] = financial.reference_identity()
        record["build_tools"] = {name: importlib.metadata.version(name) for name in ("build", "packaging", "pyproject-hooks")}
        if record["build_tools"] != {"build": "1.6.1", "packaging": "26.3", "pyproject-hooks": "1.3.3"}:
            raise ValueError("BUILD_VERSION: install requirements-build.txt")
        dist = output / "dist"
        run_command(record, output, "build-sdist", [sys.executable, "-B", "-m", "build", "--sdist", "--outdir", dist, source], output)
        sdists = list(dist.glob("*.tar.gz"))
        if len(sdists) != 1:
            raise ValueError("SDIST_COUNT: expected exactly one source distribution")
        extracted, members = extract_sdist(sdists[0], output / "sdist", manifest)
        record.update(sdist=str(sdists[0]), sdist_proof=file_entry(regular_bytes(sdists[0])), sdist_members=members, source_root=str(extracted))
        check_links(extracted)
        run_command(record, output, "build-wheel-from-sdist", [sys.executable, "-B", "-m", "build", "--wheel", "--outdir", dist, extracted], output)
        wheels = list(dist.glob("*.whl"))
        if len(wheels) != 1:
            raise ValueError("WHEEL_COUNT: expected exactly one wheel")
        wheel_members, metadata = inspect_wheel(wheels[0], extracted)
        if any(file_entry(regular_bytes(root / name)) != proof for name, proof in manifest.items()):
            raise ValueError("SOURCE_CHANGED: checkout changed during build")
        record.update(status="PASS", exit_code=0, wheel=str(wheels[0]), wheel_proof=file_entry(regular_bytes(wheels[0])),
                      wheel_members=wheel_members, wheel_metadata=metadata, clean_source=str(source), source_unchanged=True,
                      wheel_built_from="safely extracted sdist; never directly from checkout")
        write_json(output / "release.json", record)
        return record
    except BaseException as error:
        record.update(status="ERROR", exit_code=2, error=repr(error))
        write_json(output / "release.json", record)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = build(args.output)
        print(json.dumps({key: result[key] for key in ("status", "source_root", "sdist", "wheel")}))
        return 0
    except (OSError, ValueError, RuntimeError, tarfile.TarError, zipfile.BadZipFile, importlib.metadata.PackageNotFoundError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
