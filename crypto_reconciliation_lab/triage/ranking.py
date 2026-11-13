"""Three fixed policies on the same saved evidence; no labels or financial writes."""
from decimal import Decimal
import os
from pathlib import Path

from ..review.publication import new_output_directory
from . import EXPERIMENT_FORMAT
from .contracts import load, save, timestamp, validate_features
from .features import subset
from .model import score_rows, validate_model
from .safeio import preflight_output


def rule_key(unit):
    values = unit["features"]
    if values["a_conflict_count"] + values["b_conflict_count"]:
        priority = 0
    elif values["pending_correction_count"]:
        priority = 1
    elif values["a_mismatch_count"] + values["b_mismatch_count"]:
        priority = 2
    elif values["missing_report_count"]:
        priority = 3
    elif values["missing_manifest_count"]:
        priority = 4
    elif values["a_incomplete_count"] + values["b_incomplete_count"]:
        priority = 5
    elif values["a_stale_count"] + values["b_stale_count"]:
        priority = 6
    else:
        priority = 7
    ratios = [Decimal(values[name]) for name in ("a_relative_difference_max", "b_relative_difference") if values[name] is not None]
    age = Decimal(values["observed_age_hours"]) if values["observed_age_hours"] is not None else Decimal(0)
    return (priority, age.copy_negate(), not bool(ratios),
            max(ratios).copy_negate() if ratios else Decimal(0), unit["unit_id"])


def build_queue(features, model):
    validate_features(features)
    validate_model(model, contract_sha256=features["contract_sha256"], splits_sha256=features["splits_sha256"])
    scores = {row["unit_id"]: row for row in score_rows(model, features)}
    open_units = [u for u in features["units"] if u["status"] == "OPEN"]
    rankings = {
        "fifo": [u["unit_id"] for u in sorted(open_units, key=lambda u: (timestamp(u["first_seen_at"]), u["unit_id"]))],
        "rules": [u["unit_id"] for u in sorted(open_units, key=rule_key)],
        "model": [u["unit_id"] for u in sorted(open_units, key=lambda u: (Decimal(scores[u["unit_id"]]["rounded_score"]).copy_negate(), u["unit_id"]))],
    }
    positions = {policy: {key: i + 1 for i, key in enumerate(order)} for policy, order in rankings.items()}
    units = []
    for unit in features["units"]:
        key = unit["unit_id"]
        scored = scores[key]
        units.append({**unit, "ranks": {p: positions[p].get(key) for p in rankings},
                      "model_id": model["model_id"], "model_score": scored["score"] if unit["status"] == "OPEN" else None,
                      "rounded_score": scored["rounded_score"] if unit["status"] == "OPEN" else None,
                      "score_status": "SCORED" if unit["status"] == "OPEN" else "NO_OPEN_FINDING",
                      "fallback": None, "contributions": scored["contributions"] if unit["status"] == "OPEN" else [],
                      "explanation": "Observed saved states and linear model contributions; not causality, root cause or calibrated financial risk."})
    return {"format": "triage-queue-v1", "experiment_format": EXPERIMENT_FORMAT,
            "model_id": model["model_id"], "contract_sha256": features["contract_sha256"],
            "splits_sha256": features["splits_sha256"], "units": units, "rankings": rankings,
            "source_files": features.get("source_files", []), "snapshots": features.get("snapshots", []),
            "inventory": {"total": len(units), "open": len(open_units), "no_open_finding": len(units)-len(open_units),
                          "unscorable": 0, "fallback_count": 0},
            "policy": "LogisticRegression; no rule fallback", "precision": "12 fractional score places, half-even; neutral unit_id tie-break"}


def markdown(queue):
    lines = ["# Evidence-bound synthetic review queue", "", "Scores do not change saved findings and are not calibrated financial risk probabilities.", "",
             "| Unit | State | FIFO | Rules | Model | Model score | Saved evidence |",
             "|---|---|---:|---:|---:|---|---|"]
    for unit in sorted(queue["units"], key=lambda u: (u["ranks"]["model"] is None, u["ranks"]["model"] or 0, u["unit_id"])):
        refs = ", ".join(f"{r['run_id']}:{r['pointer']}" for r in unit["finding_refs"])
        ranks = unit["ranks"]
        lines.append(f"| {unit['unit_id']} | {unit['status']} | {ranks['fifo']} | {ranks['rules']} | {ranks['model']} | {unit['rounded_score']} | {refs} |")
    lines += ["", "Original financial text/null, state axes, feature provenance and saved evidence references are in queue.json.",
              "NO_OPEN_FINDING units remain in inventory; censored labels are not available to this ranker.",
              "Contributions explain the fitted linear score only, not root cause or intervention necessity.", ""]
    return "\n".join(lines)


def rank_files(features_path, model_path, output, split=None):
    # All input validation/scoring and all protected-path checks precede mkdir.
    if os.path.lexists(Path(output).expanduser().absolute()):
        raise FileExistsError("OUTPUT_EXISTS: choose a new output directory")
    features, model = load(features_path), load(model_path)
    destination = preflight_output(output, features.get("source_files", ()), (features_path, model_path))
    if split is not None:
        if split not in ("train", "validation", "test", "challenge"):
            raise ValueError("TRIAGE_SPLIT: unknown rank subset")
        features = subset(features, split)
    queue = build_queue(features, model)
    with new_output_directory(destination) as staging:
        save(staging / "queue.json", queue)
        (staging / "queue.md").write_text(markdown(queue), encoding="utf-8")
    return queue
