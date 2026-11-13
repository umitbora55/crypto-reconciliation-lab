"""Small bounded experiment orchestration; rank itself has no truth dependency."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import traceback

from ..review.publication import new_output_directory
from . import EXPERIMENT_FORMAT
from .contracts import CONTRACT_SHA256, FEATURE_NAMES, digest, encoded, load, save, validate_features
from .budget import ExperimentBudget
from .features import build_features, subset
from .model import train_model, validate_model, score_rows
from .metrics import evaluate_comparison
from .ranking import build_queue, rank_files, markdown
from .safeio import preflight_output
from .scope import load_public_scope, validate_unit_roster, validate_final_labels


def file_entry(path):
    data = Path(path).read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def implementation_hashes():
    return {p.name: file_entry(p) for p in sorted(Path(__file__).parent.glob("*.py"))}


def verify_twins(features, model, splits):
    """Public neutral pair positions only; no family/label/private plan is read."""
    units = {(u["episode_id"], u["asset"]): u for u in features["units"]}
    scores = {r["unit_id"]: r for r in score_rows(model, features)}
    assets = sorted({u["asset"] for u in features["units"]})
    pairs = []
    for group in splits["groups"]:
        first, second = group["episode_ids"][:2]
        for asset in assets:
            left, right = units[(first, asset)], units[(second, asset)]
            if (left["features"] != right["features"] or
                    [r["finding"] for r in left["finding_refs"]] != [r["finding"] for r in right["finding_refs"]] or
                    scores[left["unit_id"]]["score"] != scores[right["unit_id"]]["score"] or
                    scores[left["unit_id"]]["rounded_score"] != scores[right["unit_id"]]["rounded_score"]):
                raise ValueError("TRIAGE_TWIN_LEAKAGE: identical-T pair observations/features/scores differ")
            pairs.append({"world_id": group["world_id"], "asset": asset,
                          "units": [left["unit_id"], right["unit_id"]],
                          "feature_hash": digest(left["features"]),
                          "score": scores[left["unit_id"]]["score"], "equal": True})
    return {"status": "PASS", "asset_pairs": len(pairs), "pairs": pairs,
            "scope": "Actual frozen-model equality before opening holdout truth"}


def labels_for(labels, units):
    """Select an intentional split; final evaluation first validates its full union."""
    ids = {row["unit_id"] for row in units}
    selected = [row for row in labels["units"] if row["unit_id"] in ids]
    if len(selected) != len(ids) or {r["unit_id"] for r in selected} != ids:
        raise ValueError("TRIAGE_LABEL_COVERAGE: missing or duplicate unit in evaluator labels")
    return {**labels, "units": selected, "inventory": {"units": len(selected)}}


def train_files(features_path, labels_path, splits_path, output):
    if os.path.lexists(Path(output).expanduser().absolute()):
        raise FileExistsError("OUTPUT_EXISTS: choose a new output directory")
    features, labels, splits = load(features_path), load(labels_path), load(splits_path)
    destination = preflight_output(output, features.get("source_files", ()), (features_path, labels_path, splits_path))
    model, audit = train_model(features, labels, splits)
    with new_output_directory(destination) as staging:
        save(staging / "model.json", model)
        save(staging / "training.json", audit)
    return model, audit


def development_labels(input_path, output, budget=None):
    from .truth import evaluate_labels
    return evaluate_labels(input_path, splits=("train", "validation"), output=output, budget=budget)


def freeze_model(features_path, model_path, splits_path, output):
    features, model, splits = load(features_path), load(model_path), load(splits_path)
    validate_features(features, splits)
    scope = load_public_scope(Path(splits_path).parent)
    if digest(splits) != scope["split_hash"]:
        raise ValueError("TRIAGE_SCOPE: supplied splits differ from public inventory")
    validate_unit_roster(features.get("units"), scope["units"], label="freeze features")
    validate_model(model, contract_sha256=CONTRACT_SHA256, splits_sha256=digest(splits))
    document = {"status": "FROZEN", "format": EXPERIMENT_FORMAT,
                "contract_hash": CONTRACT_SHA256, "model_id": model["model_id"],
                "model_file": file_entry(model_path), "feature_file": file_entry(features_path),
                "split_hash": digest(splits), "implementation": implementation_hashes(),
                "feature_order": list(FEATURE_NAMES),
                "dataset_bundle": file_entry(Path(splits_path).parent / "bundle.json"),
                "truth_catalog": file_entry(Path(splits_path).parent / "truth/plan.json"),
                "purpose": "Frozen before any final test/challenge ranking or truth evaluation"}
    with Path(output).open("xb") as stream:
        stream.write(encoded(document))
    return document


def evaluate_frozen(input_path, features_path, model_path, queues_path, freeze_path, output, budget=None):
    from .truth import evaluate_labels
    if os.path.lexists(Path(output).expanduser().absolute()):
        raise FileExistsError("OUTPUT_EXISTS: choose a new output directory")
    features, model, frozen = load(features_path), load(model_path), load(freeze_path)
    if not isinstance(features, dict):
        raise ValueError("TRIAGE_SCOPE: final features must be an object")
    destination = preflight_output(output, features.get("source_files", ()),
                                   (features_path, model_path, freeze_path, queues_path))
    if (frozen.get("status") != "FROZEN" or frozen.get("contract_hash") != CONTRACT_SHA256
            or frozen.get("model_id") != model.get("model_id") or frozen.get("model_file") != file_entry(model_path)
            or frozen.get("feature_file") != file_entry(features_path)
            or frozen.get("dataset_bundle") != file_entry(Path(input_path) / "bundle.json")
            or frozen.get("truth_catalog") != file_entry(Path(input_path) / "truth/plan.json")
            or frozen.get("implementation") != implementation_hashes()):
        raise ValueError("TRIAGE_FREEZE: model/features/implementation changed before holdout truth")
    scope = load_public_scope(input_path)
    if frozen.get("split_hash") != scope["split_hash"]:
        raise ValueError("TRIAGE_SCOPE: frozen split differs from public inventory")
    validate_unit_roster(features.get("units"), scope["units"], label="final features")
    validate_features(features, scope["splits"])
    queues = {split: load(Path(queues_path) / split / "queue.json") for split in ("test", "challenge")}
    if frozen.get("prediction_hash") != digest(queues):
        raise ValueError("TRIAGE_FREEZE: complete unlabelled rankings changed")
    # Validate every unit and ranking against T-only deterministic scoring before
    # opening even one held-out private plan. This is not another label evaluation.
    for split, queue in queues.items():
        expected = {uid: row for uid, row in scope["units"].items() if row["split"] == split}
        validate_unit_roster(queue.get("units") if isinstance(queue, dict) else None,
                             expected, label=split + " queue")
        if queue != build_queue(subset(features, split), model):
            raise ValueError("TRIAGE_FREEZE: queue is not the frozen model's full T ranking")
    with new_output_directory(destination) as staging:
        labels = evaluate_labels(input_path, splits=("test", "challenge"), freeze=frozen,
                                 output=staging / "horizon-proof", budget=budget)
        # Coverage of the independent full final union precedes split filtering.
        validate_final_labels(labels, scope)
        reports = {split: evaluate_comparison(queue["units"], queue["rankings"], labels_for(labels, queue["units"]))
                   for split, queue in queues.items()}
        save(staging / "labels.json", labels)
        save(staging / "metrics.json", reports)
        (staging / "evaluation.md").write_text(evaluation_markdown(reports), encoding="utf-8")
    return reports, labels


def evaluation_markdown(reports):
    lines = ["# Synthetic unresolved-at-horizon evaluation", "",
             "Target: scope still open at T+24h. Known-label recall is not complete censored recall.",
             "Unknown labels retain queue positions and capacity; there is no refill.", ""]
    for split, report in reports.items():
        lines += ["## " + split, "", report["conclusion"], "",
                  "| Policy | N | K | P | TP | FP | U | Recall known | Precision labeled | Precision bounds | Coverage |",
                  "|---|---:|---:|---:|---:|---:|---:|---|---|---|---|"]
        for name, result in report["policies"].items():
            lines.append("| " + name + " | " + " | ".join(str(result.get(key)) for key in
                ("N", "K", "known_positive", "TP", "FP", "U", "recall_known_at_budget", "precision_labeled_at_budget", "precision_bounds", "top_k_label_coverage")) + " |")
        lines += ["", "Model minus rules Recall_known: " + str(report["model_minus_rules_recall_known"]),
                  "", "### Saved-evidence review examples", ""]
        for example in report["misprioritized_examples"]:
            links = ", ".join(ref["run_id"] + ":" + ref["pointer"] for ref in example["finding_refs"])
            lines.append("- " + example["unit_id"] + ": " + example["type"] + "; " + links)
        lines += ["", "World/family/asset attribution and all raw denominators are in metrics.json.", ""]
    lines += ["No claim of institutional benefit, fraud detection, causal explanation or independent-sample statistical certainty.", ""]
    return "\n".join(lines)


def _write_queue(path, queue):
    path.mkdir(parents=True)
    save(path / "queue.json", queue)
    (path / "queue.md").write_text(markdown(queue), encoding="utf-8")


def _run_small(root, mode, budget):
    from .world import generate_bundle
    generate_bundle(root / "data", mode=mode, budget=budget)
    features = build_features(root / "data", root / "features", budget)
    labels = development_labels(root / "data", root / "development-labels", budget)
    train = subset(features, "train")
    model, audit = train_model(train, labels_for(labels, train["units"]), load(root / "data/splits.json"))
    root.mkdir(parents=True, exist_ok=True)
    save(root / "model.json", model)
    save(root / "training.json", audit)
    queue = build_queue(features, model)
    _write_queue(root / "queue", queue)
    # Counts/evidence are retained; this small feasibility scope is not the locked
    # main test or a second main evaluation.
    save(root / "smoke.json", {"status": "PASS", "mode": mode, "groups": 2,
                               "units": len(features["units"]), "model_id": model["model_id"],
                               "scope": "two-world feasibility only; no held-out main evaluation"})
    budget.check(force=True)
    return features, model


def _retain(runtime, staging, budget, execution):
    """Copy bytes and read back the owned destination FD before closing it.

    Avoid a second cold managed-folder traversal; every retained byte is still
    independently read back. Original DBs are omitted from publication, not from
    the combined runtime/retained budget while they exist.
    """
    manifest, omissions = {}, {}
    for source in sorted(runtime.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(runtime)
        data = source.read_bytes()
        expected = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        if source.suffix in (".sqlite3", ".db") or source.name.endswith(("-wal", "-shm", "-journal")):
            omissions[str(relative)] = expected
            continue
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x+b") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            stream.seek(0)
            retained = stream.read()
        if retained != data:
            raise ValueError("TRIAGE_RETENTION: retained bytes differ")
        manifest[str(relative)] = expected
        budget.check()
    save(staging / "omitted-files.json", {"files": omissions,
         "producer": {"argv": execution["argv"], "cwd": execution["cwd"], "mode": execution["mode"],
                      "contract_sha256": execution["contract_sha256"]},
         "reason": "Runtime SQLite sources; saved payloads/features/labels remain"})
    return manifest, omissions


def run_experiment(output, mode="main"):
    if mode not in ("main", "smoke", "archive_smoke"):
        raise ValueError("TRIAGE_MODE: unsupported experiment scope")
    destination = preflight_output(output)
    runtime = Path(tempfile.mkdtemp(prefix="crypto-triage-experiment-")).resolve()
    budget = ExperimentBudget([runtime])
    record = {"status": "RUNNING", "format": EXPERIMENT_FORMAT, "mode": mode,
              "contract_sha256": CONTRACT_SHA256, "implementation": implementation_hashes(),
              "interpreter": sys.executable, "python": sys.version, "cwd": str(Path.cwd()),
              "runtime": str(runtime), "argv": sys.orig_argv, "phases": []}
    published = False
    save(runtime / "execution.json", record)
    try:
        if mode != "main":
            _run_small(runtime / "small", mode, budget)
            record["phases"].append("two_world_feasibility")
        else:
            _run_small(runtime / "smoke", "smoke", budget)
            record["phases"].append("two_world_feasibility")
            from .world import generate_bundle
            main = runtime / "main"
            generate_bundle(main / "data", mode="main", budget=budget)
            record["phases"].append("144_world_generation_and_T_truth_checks")
            features = build_features(main / "data", main / "features", budget)
            development = development_labels(main / "data", main / "development-labels", budget)
            train = subset(features, "train")
            model, audit = train_model(train, labels_for(development, train["units"]), load(main / "data/splits.json"))
            save(main / "model.json", model)
            save(main / "training.json", audit)
            save(main / "train-features.json", train)
            save(main / "train-labels.json", labels_for(development, train["units"]))
            validation = build_queue(subset(features, "validation"), model)
            _write_queue(main / "queues/validation", validation)
            validation_report = evaluate_comparison(validation["units"], validation["rankings"], labels_for(development, validation["units"]))
            save(main / "validation-metrics.json", validation_report)
            record["phases"].append("train_only_fit_and_validation_consistency")
            budget.check(force=True)
            initial_freeze = freeze_model(main / "features/features.json", main / "model.json", main / "data/splits.json", main / "model-freeze.json")
            twins = verify_twins(features, model, load(main / "data/splits.json"))
            save(main / "twin-audit.json", twins)
            queues = {split: build_queue(subset(features, split), model) for split in ("test", "challenge")}
            for split, queue in queues.items():
                _write_queue(main / "queues" / split, queue)
            frozen = {**initial_freeze, "prediction_hash": digest(queues)}
            with (main / "holdout-freeze.json").open("xb") as stream:
                stream.write(encoded(frozen))
            record["phases"].append("model_and_complete_unlabelled_rankings_frozen")
            reports, labels = evaluate_frozen(main / "data", main / "features/features.json", main / "model.json", main / "queues", main / "holdout-freeze.json", main / "evaluation", budget)
            record["phases"].append("single_final_test_and_challenge_evaluation")
            save(main / "metrics.json", reports)
            (main / "evaluation.md").write_text(evaluation_markdown(reports), encoding="utf-8")
            model_card = ["# Synthetic triage model card", "", "One L2 LogisticRegression with frozen parameters; no hyperparameter search.",
                "144 world groups, 576 episodes, 1152 visible asset units; actual eligible/label counts are in metrics.json.",
                "72 train / 24 validation / 24 final-test worlds; 24 separate COMBINED_REOPEN challenge worlds.",
                "Target: unresolved_at_horizon at T+24h; not calibrated financial risk, fraud, loss or a required action.", "",
                "Primary test: " + reports["test"]["conclusion"], "Challenge: " + reports["challenge"]["conclusion"], "",
                "Exact-T twins have different future labels and must receive identical features/scores.",
                "Family timelines, sample sizes and budgets were fixed before final labels. Dependent asset units are not independent statistical samples.",
                "Preprocessing uses train-only medians, all-feature missing indicators and train-only scaling. Original financial text/null remains in evidence.",
                "Training/library parity checks and exact installed dependencies are in training.json; model.json is strict data, never pickle/joblib.",
                "Same model JSON and feature input yield deterministic ranking; retraining bit equality across BLAS/OS is not claimed.",
                "No operational/institutional benefit is inferred. There is no rule fallback or automatic remediation.", ""]
            (main / "model_card.md").write_text("\n".join(model_card), encoding="utf-8")
        record["status"] = "COMPUTATION_COMPLETE"
        record["budget"] = budget.check(force=True)
        save(runtime / "execution.json", record)
        with new_output_directory(destination) as staging:
            budget.add_root(staging)
            manifest, omissions = _retain(runtime, staging, budget, record)
            (staging / "five-minute-review.md").write_text(
                "# Five-minute review\n\nRun `python -m crypto_reconciliation_lab triage-experiment --mode main --output NEW_DIRECTORY` for the full frozen design.\n\n"
                "Read main/model_card.md, main/evaluation.md and main/metrics.json; compare N/K/P/TP/FP/U before interpreting recall.\n"
                "Inspect main/queues/test/queue.json and queue.md, then the referenced saved raw payload in main/features/snapshots.\n"
                "The challenge is a separate queue. Unknown labels consume capacity. Exact-T twins cannot be separated by hidden future knowledge.\n"
                "Use triage-rank with main/model.json and main/features/features.json; ranking needs no AI dependency or truth file.\n"
                "This is a synthetic evidence review experiment, not a production risk system or an institution claim.\n", encoding="utf-8")
            record.update(status="COMPLETE", exit_code=0, retained_files=len(manifest), omitted_runtime_databases=len(omissions), budget=budget.check(force=True))
            save(staging / "execution.json", record)
            # Bind final artifact bytes; this manifest excludes itself only.
            for name in ("execution.json", "omitted-files.json", "five-minute-review.md"):
                manifest[name] = file_entry(staging / name)
            save(staging / "retained-files.json", {"files": manifest,
                 "verification": "full owned-FD readback; final metadata rehashed", "self_hash_omitted": True})
            budget.check(force=True)
        published = True
        budget.add_root(destination)
        # Publication is in the same deadline. An overrun is explicitly changed
        # to ERROR at this operation's own destination, never left COMPLETE.
        budget.check(force=True)
        return record
    except BaseException as exc:
        record.update(status="ERROR", exit_code=2, error=repr(exc), traceback=traceback.format_exc(),
                      elapsed_seconds=time.monotonic() - budget.started,
                      unscorable_inventory=getattr(exc, "unscorable_inventory", []),
                      completed_scope=record["phases"], runtime_preserved=True)
        save(runtime / "execution.json", record)
        # Retain the execution failure at the requested new destination; no
        # completed experiment or model result is claimed. Runtime inputs stay.
        if not os.path.lexists(destination):
            with new_output_directory(destination) as staging:
                save(staging / "execution.json", record)
        elif published:
            save(destination / "execution.json", record)
            (destination / "retained-files.json").unlink(missing_ok=True)
        raise
