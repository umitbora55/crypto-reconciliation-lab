#!/usr/bin/env python3
"""Run the offline Gate 2 analysis from a pre-bound source snapshot.

The execution closure includes every application Python/JSON resource, the two
public-analysis modules, their acquisition-evidence dependency and this runner.
Unrelated benchmark/identity research is deliberately outside this closure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
RESEARCH_FILES = (
    "validation_lab/public_data.py", "validation_lab/gate2_public_data.py",
    "scripts/validation/fetch_public_data.py", "scripts/validation/run_gate2_public_data.py",
)


def now():
    return datetime.now(timezone.utc).isoformat()


def proof(path):
    path = Path(path)
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}


def dump(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def run(access_root, data_root, policy, output):
    access_root, data_root, policy, output = (Path(p).resolve() for p in (access_root, data_root, policy, output))
    output.mkdir(parents=True, exist_ok=False)
    snapshot = output / "source-snapshot"
    snapshot.mkdir()
    paths = sorted(p for p in (ROOT / "crypto_reconciliation_lab").rglob("*")
                   if p.is_file() and p.suffix in (".py", ".json") and "__pycache__" not in p.parts)
    paths += [ROOT / name for name in RESEARCH_FILES]
    # These are namespace packages in the current checkout; bind an initializer
    # if one is present in a later reviewed version rather than silently omit it.
    paths += [p for p in (ROOT / "validation_lab/__init__.py", ROOT / "scripts/__init__.py", ROOT / "scripts/validation/__init__.py") if p.exists()]
    source_proofs = {}
    for source in sorted(set(paths)):
        if source.is_symlink() or not source.resolve().is_relative_to(ROOT):
            raise ValueError("SOURCE_PATH_NOT_REGULAR_CONTAINED")
        relative = source.relative_to(ROOT)
        target = snapshot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        body = source.read_bytes()
        with target.open("xb") as stream:
            stream.write(body)
        source_proofs[str(relative)] = proof(target)
        if proof(source) != source_proofs[str(relative)]:
            raise ValueError("SOURCE_CHANGED_DURING_SNAPSHOT")
    input_proofs = {}
    for root in (access_root, data_root):
        for name in ("protocol.json", "source-register.json"):
            input_proofs[str(root / name)] = proof(root / name)
        register = json.loads((root / "source-register.json").read_text())
        for item in register["sources"]:
            if "path" in item:
                path = (root / item["path"]).resolve()
                if not path.is_relative_to(root):
                    raise ValueError("INPUT_PATH_ESCAPE")
                input_proofs[str(path)] = proof(path)
    input_proofs[str(policy)] = proof(policy)
    policy_copy = output / "policy.json"
    with policy_copy.open("xb") as stream:
        stream.write(policy.read_bytes())
    if proof(policy_copy) != input_proofs[str(policy)]:
        raise ValueError("POLICY_CHANGED_DURING_SNAPSHOT")
    imports_path = output / "imported-modules.json"
    bootstrap = output / "bootstrap.py"
    bootstrap_text = (
        "import json, pathlib, runpy, sys\n"
        f"snapshot = pathlib.Path({str(snapshot)!r}).resolve()\n"
        "sys.path.insert(0, str(snapshot))\n"
        "try:\n"
        "    runpy.run_module('validation_lab.gate2_public_data', run_name='__main__')\n"
        "finally:\n"
        "    modules = {}\n"
        "    for name, module in list(sys.modules.items()):\n"
        "        value = getattr(module, '__file__', None)\n"
        "        if value and pathlib.Path(value).resolve().is_relative_to(snapshot):\n"
        "            modules[name] = str(pathlib.Path(value).resolve().relative_to(snapshot))\n"
        f"    with open({str(imports_path)!r}, 'x') as stream:\n"
        "        json.dump(modules, stream, indent=2, sort_keys=True)\n"
    )
    with bootstrap.open("x") as stream:
        stream.write(bootstrap_text)
    argv = [sys.executable, "-I", "-B", str(bootstrap), "--access-root", str(access_root),
            "--data-root", str(data_root), "--policy", str(policy_copy), "--output", str(output / "results")]
    git_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    start = {"format": "gate2-public-execution-v1", "status": "STARTED", "started_at_utc": now(),
             "argv": argv, "cwd": str(snapshot), "environment_overrides": {"NO_NETWORK": "1"},
             "checkout_head_at_start": git_head, "source_identity": "Complete pre-execution snapshot hashes; checkout HEAD alone does not identify uncommitted research files.",
             "scope": "Every application .py/.json; public_data, gate2_public_data, fetch_public_data and runner; namespace initializers if present. Unused benchmark/identity modules excluded.",
             "python_version": sys.version, "executable": sys.executable, "executable_resolved": str(Path(sys.executable).resolve()),
             "executable_proof": proof(Path(sys.executable).resolve()), "platform": platform.platform(),
             "machine": platform.machine(), "sqlite_version": sqlite3.sqlite_version,
             "source_files": source_proofs, "input_files": input_proofs,
             "policy_copy": proof(policy_copy), "bootstrap": proof(bootstrap)}
    dump(output / "execution-start.json", start)
    begin = time.monotonic()
    with (output / "stdout.log").open("xb") as stdout, (output / "stderr.log").open("xb") as stderr:
        command = subprocess.run(argv, cwd=snapshot, env={**os.environ, "NO_NETWORK": "1"}, stdout=stdout, stderr=stderr, timeout=180)
    source_unchanged = all(proof(ROOT / path) == value and proof(snapshot / path) == value for path, value in source_proofs.items())
    inputs_unchanged = all(proof(path) == value for path, value in input_proofs.items())
    controls_unchanged = proof(policy_copy) == start["policy_copy"] and proof(bootstrap) == start["bootstrap"]
    result = {"status": "PASS" if command.returncode == 0 and source_unchanged and inputs_unchanged and controls_unchanged else "FAIL",
              "ended_at_utc": now(), "elapsed_seconds": time.monotonic()-begin, "exit_code": command.returncode,
              "source_and_snapshot_unchanged": source_unchanged, "raw_inputs_unchanged": inputs_unchanged,
              "bootstrap_and_policy_unchanged": controls_unchanged,
              "execution_start": proof(output / "execution-start.json"), "stdout": proof(output / "stdout.log"), "stderr": proof(output / "stderr.log"),
              "imported_modules": proof(imports_path) if imports_path.exists() else None}
    dump(output / "execution-completion.json", result)
    print(json.dumps(result))
    return 0 if result["status"] == "PASS" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--access-root", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    return run(args.access_root, args.data_root, args.policy, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
