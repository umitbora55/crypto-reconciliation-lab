#!/usr/bin/env python3
"""Reproduce the small offline review with unchanged application subcommands.

Source and installed execution are explicit. This stdlib orchestration script
never generates a triage experiment, trains a model, or evaluates future truth.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/triage-review"
PHASE_COUNTS = {"clean": 1, "late_event": 2, "custody_difference": 1,
                "corrected_report": 2, "deposit_amount_correction": 4,
                "void_deposit": 4, "void_internal_transfer": 3,
                "correction_before_target": 3, "duplicate_and_conflicting_corrections": 4}
# runpy dispatches the existing module exactly as -m would. The finally block
# records actual imports even for the deliberately rejected CLI input.
CLI_AUDIT = r'''import importlib.util, json, pathlib, runpy, sqlite3, sys, sysconfig
report = pathlib.Path(sys.argv[1])
sys.argv = ["crypto_reconciliation_lab", *sys.argv[2:]]
try:
    runpy.run_module("crypto_reconciliation_lab", run_name="__main__")
finally:
    package = sys.modules.get("crypto_reconciliation_lab")
    report.write_text(json.dumps({
        "executable": sys.executable, "python_version": sys.version,
        "sqlite_version": sqlite3.sqlite_version,
        "package_origin": getattr(package, "__file__", None),
        "package_version": getattr(package, "__version__", None),
        "prefix": sys.prefix, "base_prefix": sys.base_prefix,
        "site_packages": [sysconfig.get_path("purelib"), sysconfig.get_path("platlib")],
        "imported_optional": sorted(name for name in ("sklearn", "numpy", "scipy")
                                    if any(key == name or key.startswith(name + ".") for key in sys.modules)),
        "available_optional": {name: importlib.util.find_spec(name) is not None
                               for name in ("sklearn", "numpy", "scipy")},
        "module_argv": sys.argv,
    }, sort_keys=True, indent=2) + "\n", encoding="utf-8")
'''


class ReproductionError(ValueError):
    """An unsuccessful command or incomplete artifact is never a successful demo."""


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def file_entry(path):
    data = Path(path).read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def file_manifest(root):
    result = {}
    for path in sorted(Path(root).rglob("*")):
        if path.is_symlink():
            raise ReproductionError("unexpected symlink: " + str(path))
        if path.is_file():
            result[path.relative_to(root).as_posix()] = file_entry(path)
    return result


def require(condition, message):
    if not condition:
        raise ReproductionError(message)


def relative_file(root, name):
    require(isinstance(name, str) and name and not PurePosixPath(name).is_absolute()
            and "\\" not in name and all(p not in ("", ".", "..") for p in name.split("/")),
            "unsafe relative artifact path")
    path = Path(root) / name
    require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(Path(root).resolve()),
            "missing or unsafe artifact: " + name)
    return path


def json_pointer(value, pointer):
    require(isinstance(pointer, str) and pointer.startswith("/"), "invalid saved pointer")
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def validate_example(root):
    """Check packaged bytes and links, not financial arithmetic or future labels."""
    manifest = read_json(relative_file(root, "selection-manifest.json"))
    for name, proof in manifest["files"].items():
        require(file_entry(relative_file(root, name)) == proof["copied_hash"], "example hash mismatch: " + name)
    features = read_json(relative_file(root, "features.json"))
    expected = manifest["selected_unit_ids"]
    require([u["unit_id"] for u in features["units"]] == expected and len(set(expected)) == len(expected),
            "example unit selection differs from manifest")
    payloads = {}
    for snapshot in features["snapshots"]:
        path = relative_file(root, snapshot["payload_file"])
        require(file_entry(path)["sha256"] == snapshot["sha256"], "snapshot hash mismatch")
        payload = read_json(path)
        require(snapshot["sha256"] == snapshot["run_id"] and payload["knowledge_at"] == snapshot["knowledge_at"],
                "snapshot identity differs from payload")
        payloads[(snapshot["episode_id"], snapshot["run_id"])] = payload
    for unit in features["units"]:
        for ref in unit["finding_refs"]:
            payload = payloads[(unit["episode_id"], ref["run_id"])]
            require(ref["finding"] == json_pointer(payload, ref["pointer"]), "finding differs from saved payload")
            require(file_entry(relative_file(root, ref["payload_file"]))["sha256"] == ref["payload_sha256"],
                    "finding payload hash mismatch")
        for proof in unit["feature_provenance"].values():
            for source in proof["sources"]:
                payload = payloads[(unit["episode_id"], source["run_id"])]
                finding = json_pointer(payload, source["pointer"])
                require(finding["asset"] == unit["asset"] and source["knowledge_at"] == payload["knowledge_at"],
                        "feature source scope differs from saved payload")
                require(json_pointer(payload, source["evidence_pointer"]) == finding["evidence_ids"],
                        "evidence pointer differs from saved finding")
    return manifest, features


def validate_showcase(path):
    showcase = read_json(path)
    rows = showcase.get("runs", [])
    require(showcase.get("status") == "COMPLETE" and isinstance(rows, list) and len(rows) == 24,
            "review-demo did not retain all 24 evaluations")
    require(Counter(row.get("scenario") for row in rows) == PHASE_COUNTS,
            "review-demo does not cover all nine scenarios")
    require(len({(row["scenario"], row["phase"]) for row in rows}) == 24
            and all(row.get("verified") is True for row in rows), "duplicate or unverified demo phase")
    return showcase


def database_state(selection_path):
    selection_path = Path(selection_path)
    result = {}
    for source in read_json(selection_path)["sources"]:
        path = relative_file(selection_path.parent, source["database"])
        for suffix in ("-journal", "-wal", "-shm"):
            require(not os.path.lexists(str(path) + suffix), "unexpected SQLite sidecar: " + str(path) + suffix)
        result[source["database"]] = file_entry(path)
    require(len(result) == 9, "review selection does not contain nine independent source databases")
    return result


def validate_rank(path, features):
    queue = read_json(relative_file(path, "queue.json"))
    relative_file(path, "queue.md")
    require(queue.get("format") == "triage-queue-v1"
            and queue.get("contract_sha256") == features["contract_sha256"]
            and queue.get("splits_sha256") == features["splits_sha256"], "missing or inconsistent queue contract")
    units = queue.get("units", [])
    require([u["unit_id"] for u in units] == [u["unit_id"] for u in features["units"]],
            "ranking silently changed example inventory")
    for actual, expected in zip(units, features["units"]):
        require(all(actual.get(key) == value for key, value in expected.items()), "rank changed an observed feature/finding")
        require(actual.get("score_status") == ("SCORED" if expected["status"] == "OPEN" else "NO_OPEN_FINDING"),
                "rank did not score its eligible observations")
    opened = {u["unit_id"] for u in features["units"] if u["status"] == "OPEN"}
    require(queue.get("inventory") == {"total": len(units), "open": len(opened),
            "no_open_finding": len(units) - len(opened), "unscorable": 0, "fallback_count": 0},
            "incomplete or fallback ranking")
    require(set(queue.get("rankings", {})) == {"fifo", "rules", "model"}
            and all(len(ids) == len(opened) and set(ids) == opened for ids in queue["rankings"].values()),
            "ranking policy omitted or duplicated open units")
    return queue


def validate_negative(output, stdout, stderr):
    require(not os.path.lexists(output), "rejected input published a successful queue directory")
    require("COMPLETE" not in stdout and "TRIAGE_PROVENANCE: future source" in stderr,
            "negative control did not fail for its declared future-source contradiction")


def new_output(path, root=ROOT, example=EXAMPLE):
    requested = Path(path).expanduser().absolute()
    require(not os.path.lexists(requested), "OUTPUT_EXISTS: choose a new owned output directory")
    destination = requested.resolve()
    protected = [Path(example).resolve(), *(Path(root) / name for name in
                 ("crypto_reconciliation_lab", "scripts", "tests", "fixtures", "docs"))]
    require(all(destination != p.resolve() and not destination.is_relative_to(p.resolve()) for p in protected),
            "OUTPUT_SOURCE_CONFLICT: output occupies a source/input path")
    destination.mkdir(parents=True, exist_ok=False)
    return destination


class Recorder:
    def __init__(self, output, python, mode, cwd):
        self.output, self.python, self.mode, self.cwd = Path(output), str(python), mode, Path(cwd)
        self.records = []
        (self.output / "logs").mkdir()

    def command(self, name, arguments, expected=0):
        audit_path = self.output / "logs" / (name + "-imports.json")
        flags = ["-B", "-I"] if self.mode == "installed" else ["-B", "-s"]
        argv = [self.python, *flags, "-c", CLI_AUDIT, str(audit_path), *map(str, arguments)]
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        start = time.perf_counter()
        record = {"name": name, "argv": argv, "module_command": [self.python, *flags, "-m", "crypto_reconciliation_lab", *map(str, arguments)],
                  "cwd": str(self.cwd), "expected_exit": expected, "exit_code": None, "started_at": datetime.now(timezone.utc).isoformat()}
        self.records.append(record)
        try:
            completed = subprocess.run(argv, cwd=self.cwd, env=environment, text=True,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
            record.update(exit_code=completed.returncode, duration_seconds=time.perf_counter() - start)
            for channel in ("stdout", "stderr"):
                relative = "logs/" + name + "." + channel + ".txt"
                (self.output / relative).write_text(getattr(completed, channel), encoding="utf-8")
                record[channel] = relative
            require(completed.returncode == expected,
                    f"{name}: expected exit {expected}, got {completed.returncode}; see logs")
            require(audit_path.is_file(), name + ": missing child import audit")
            audit = read_json(audit_path)
            origin = Path(audit["package_origin"]).resolve()
            if self.mode == "source":
                require(origin == (ROOT / "crypto_reconciliation_lab/__init__.py").resolve(), "source mode imported another package")
            else:
                require(any(origin.is_relative_to(Path(p).resolve()) for p in audit["site_packages"])
                        and not origin.is_relative_to(ROOT / "crypto_reconciliation_lab"),
                        "installed mode did not import a site-packages wheel")
            with (ROOT / "pyproject.toml").open("rb") as source_metadata:
                declared_version = tomllib.load(source_metadata)["project"]["version"]
            require(audit["package_version"] == declared_version, "child package version differs from this source distribution")
            require(not audit["imported_optional"], name + ": offline CLI imported optional AI dependencies")
            record.update(status="PASSED" if expected == 0 else "EXPECTED_REJECTION", import_audit=audit,
                          import_audit_file=audit_path.relative_to(self.output).as_posix())
            return completed
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, KeyError) as error:
            record.update(status="FAILED", duration_seconds=time.perf_counter() - start, error=str(error),
                          timed_out=isinstance(error, subprocess.TimeoutExpired))
            for channel in ("stdout", "stderr"):
                relative = "logs/" + name + "." + channel + ".txt"
                path = self.output / relative
                if not path.exists():
                    text = getattr(error, channel, None) or (str(error) if channel == "stderr" else "")
                    if isinstance(text, bytes):
                        text = text.decode("utf-8", errors="replace")
                    path.write_text(text, encoding="utf-8")
                record[channel] = relative
            raise ReproductionError(name + ": " + str(error)) from error


def write_guide(output):
    (output / "index.md").write_text('''# Small offline evidence review

Open [the review page](review/bundle/index.html) directly in a browser. No server,
API key or network is needed after installation. The [demo guide](review/five-minute-review.md)
explains all nine scenarios and 24 saved evaluations. Clean A balances are 7/4,
customer liability 11 and custody 2+9. The custody-difference scenario has a
complete +1 difference; late data is initially INCOMPLETE/NOT_EVALUATED. These
expected synthetic findings are successful demo outcomes, not application errors.

[Re-exported review](export/index.html) uses the same explicit saved selection.
Its saved run IDs and full payload hashes must match the first bundle; source
databases and sidecars must remain unchanged. Export manifest paths can differ
because the first demo bundle was constructed in an atomic staging directory.

Read the [small fixed-model queue](rank-valid/queue.md) and its [exact JSON](rank-valid/queue.json).
It retains one open asset and one NO_OPEN_FINDING asset from a single historical
T-only episode. This is intentional subset ranking, not a new complete experiment,
training run or holdout evaluation. Scores are not calibrated financial risk and
cannot alter saved findings. No future labels or new success metrics are included.
The [selection manifest](inputs/selection-manifest.json) binds original sources,
selected unit IDs, hashes and packaging-only transformations. Original payloads
are included under inputs/snapshots and referenced from the feature document.
Exact snapshot copies beside rank-valid/queue.json make its same relative
payload_file links resolvable; queue values and financial strings are unchanged.

The [negative input](inputs/features-future.json) moves one source to H while its
summary remains T. Its actual CLI must exit 2 and publish no rank-invalid directory.
See [execution evidence](reproduction.json), command logs and [output hashes](manifest.json).
An unexpected subprocess exit, missing artifact or incomplete inventory fails
this reproduction with exit 2; its evidence remains marked FAILED. Existing output
paths are always rejected rather than overwritten. Installation/build downloads
are separate from these offline commands.
''', encoding="utf-8")


def reproduce(output, mode="source", python=sys.executable):
    output = new_output(output)
    report = {"format": "small-review-reproduction-v1", "status": "RUNNING", "mode": mode,
              "requested_interpreter": str(python), "source_root": str(ROOT), "output": str(output),
              "started_at": datetime.now(timezone.utc).isoformat(), "commands": [],
              "index": "index.md", "manifest": "manifest.json", "training": "NOT_RUN", "final_holdout": "NOT_RUN"}
    start = time.perf_counter()
    recorder = None
    try:
        before = file_manifest(EXAMPLE)
        manifest, features = validate_example(EXAMPLE)
        shutil.copytree(EXAMPLE, output / "inputs")
        with tempfile.TemporaryDirectory(prefix="crypto-review-outside-") as temporary:
            cwd = ROOT if mode == "source" else Path(temporary)
            require(mode != "installed" or not cwd.resolve().is_relative_to(ROOT), "installed cwd must be outside source tree")
            recorder = Recorder(output, python, mode, cwd)
            report["commands"] = recorder.records
            recorder.command("cli-help", ["--help"])
            recorder.command("review-demo", ["review-demo", "--output", output / "review"])
            showcase = validate_showcase(output / "review/showcase.json")
            before_databases = database_state(output / "review/selection.json")
            recorder.command("review-export", ["review-export", "--selection", output / "review/selection.json", "--output", output / "export"])
            require(database_state(output / "review/selection.json") == before_databases, "export changed its database sources")
            summaries = []
            for folder in (output / "review/bundle", output / "export"):
                summary = read_json(relative_file(folder, "summary.json"))
                require(summary.get("status") == "COMPLETE" and summary.get("run_count") == 24
                        and summary.get("source_count") == 9, "incomplete review export")
                publication = read_json(relative_file(folder, "manifest.json"))
                require(publication.get("status") == "COMPLETE"
                        and set(publication.get("files", {})) == {"index.html", "summary.json"},
                        "incomplete export file manifest")
                for name, proof in publication["files"].items():
                    require(file_entry(relative_file(folder, name)) == proof, "export file hash mismatch")
                summaries.append(summary)
            require(summaries[0]["runs"] == summaries[1]["runs"], "re-export changed saved payload identities")
            require({(r["source_alias"], r["run_id"]) for r in summaries[1]["runs"]}
                    == {(r["source_alias"], r["run_id"]) for r in showcase["runs"]},
                    "export selection differs from demo catalog")
            recorder.command("rank-valid", ["triage-rank", "--features", output / "inputs/features.json",
                                            "--model", output / "inputs/model.json", "--output", output / "rank-valid"])
            queue = validate_rank(output / "rank-valid", features)
            require(queue.get("model_id") == read_json(output / "inputs/model.json")["model_id"],
                    "queue does not use the declared fixed model")
            # The CLI preserves relative evidence links but does not copy inputs.
            # Materialize their exact bytes in this owned review delivery so those
            # same links resolve beside queue.json as well as features.json.
            for snapshot in queue["snapshots"]:
                relative = snapshot["payload_file"]
                original = relative_file(output / "inputs", relative)
                target = output / "rank-valid" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                require(not os.path.lexists(target), "duplicate queue snapshot target")
                shutil.copyfile(original, target)
                require(file_entry(target) == file_entry(original), "queue snapshot copy differs")
            rejected = recorder.command("rank-invalid", ["triage-rank", "--features", output / "inputs/features-future.json",
                                                       "--model", output / "inputs/model.json", "--output", output / "rank-invalid"], expected=2)
            validate_negative(output / "rank-invalid", rejected.stdout, rejected.stderr)
        require(file_manifest(EXAMPLE) == before and file_manifest(output / "inputs") == before,
                "example sources or copied inputs changed")
        report.update(status="PASSED", scenarios=len(PHASE_COUNTS), evaluations=len(showcase["runs"]),
                      stage1_evaluations=6, stage2_evaluations=18, queue_inventory=queue["inventory"],
                      selected_unit_ids=manifest["selected_unit_ids"], input_hashes=before,
                      source_database_hashes=before_databases, sources_unchanged=True,
                      sidecars_absent=True, same_selection_payload_hashes_equal=True,
                      negative_cli_exit=2, negative_output_published=False,
                      evidence_materialization="Byte-identical copies of selected snapshots beside queue.json; relative payload_file strings and queue JSON are unchanged.",
                      artifact_paths={"showcase": "review/showcase.json", "stage1": "review/sources/stage1",
                                      "stage2": "review/sources/stage2", "rank": "rank-valid/queue.json"})
        write_guide(output)
    except (OSError, ValueError, TypeError, KeyError, IndexError) as error:
        report.update(status="FAILED", error=str(error))
    finally:
        report["duration_seconds"] = time.perf_counter() - start
        write_json(output / "reproduction.json", report)
        write_json(output / "manifest.json", {"format": "small-review-output-manifest-v1", "status": report["status"],
                                             "excluded_self": "manifest.json", "files": file_manifest(output)})
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="new owned directory, never overwritten")
    parser.add_argument("--mode", choices=("source", "installed"), default="source")
    parser.add_argument("--python", default=sys.executable, help="child interpreter; preserve its virtual-environment path")
    args = parser.parse_args(argv)
    try:
        report = reproduce(args.output, args.mode, args.python)
    except (OSError, ValueError) as error:
        print("Reproduction error: " + str(error), file=sys.stderr)
        return 2
    print(json.dumps({"status": report["status"], "mode": args.mode, "output": report["output"]}, sort_keys=True))
    return 0 if report["status"] == "PASSED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
