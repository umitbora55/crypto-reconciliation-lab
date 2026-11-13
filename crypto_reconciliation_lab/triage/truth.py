"""Finite independent integer truth and gated horizon evaluation.

This module belongs to synthetic evaluation, not feature extraction or ranking.
Labels come from the private plan; production findings are checked separately.
"""
from contextlib import nullcontext
import hashlib
import os
from pathlib import Path
import re
import tempfile

from ..review.adapter import read_selection, SIDECARS
from ..review.publication import new_output_directory
from .budget import budgeted_read_selected_sources
from .contracts import CONTRACT_SHA256, digest, encoded, load, save, unit_id, validate_splits
from .safeio import preflight_output
from .world import AS_OF, BALANCE, HORIZON, integer_ledger, text_amount

COMPARE_FIELDS = ("asset", "comparison", "scope", "balance_at", "knowledge_at",
                  "expected", "reported", "difference", "data_state", "reconciliation_state", "provisional")


def expected_findings(world, plan, knowledge):
    """Independent finite schedule table, not a generic financial validator."""
    if knowledge < plan["first_observation"]:
        raise ValueError("truth only covers explicitly observed experiment cuts")
    family, asset = plan["family"], plan["asset"]
    target = next(event for event in world["events"] if event["ref"] == plan["target_ref"])
    missing_event = family in ("LATE_EVENT", "CORRECTION_DEPENDENCY", "COMBINED_REOPEN") and knowledge < plan["arrival_at"]
    replacement = {}
    if family == "CORRECTION_DEPENDENCY" and not missing_event:
        replacement[target["ref"]] = target["units"] + plan["impact_units"]
    available = integer_ledger(world, (target["ref"],) if missing_event else (), replacement)
    reported = integer_ledger(world)
    states, reasons = {}, {}
    if missing_event:
        states[(asset, "A")] = states[(asset, "B")] = "INCOMPLETE"
        reasons[asset] = ["MANIFEST_COUNT"] + (["TARGET_PENDING"] if family == "CORRECTION_DEPENDENCY" else [])
    if family == "LATE_MANIFEST" and knowledge < plan["arrival_at"]:
        states[(asset, "A")] = states[(asset, "B")] = "INCOMPLETE"
        reasons[asset] = ["MANIFEST_ABSENT"]
    if family == "REPORT_REVISION" and knowledge < plan["revision_at"]:
        first, second = plan["investors"]
        reported[asset]["investors"][first] += plan["impact_units"]
        reported[asset]["investors"][second] -= plan["impact_units"]
    elif family == "CUSTODY_DIFFERENCE" and knowledge < plan["revision_at"]:
        reported[asset]["custody"]["external"] -= plan["impact_units"]
    elif family == "CORRECTION_DEPENDENCY" and knowledge >= plan["revision_at"]:
        reported = integer_ledger(world, replacement={target["ref"]: target["units"] + plan["impact_units"]})
    elif family == "H_NOT_OBSERVED" and knowledge < plan["arrival_at"]:
        reported[asset]["custody"]["external"] = None
        states[(asset, "B")] = "INCOMPLETE"
        reasons[(asset, "B")] = ["REPORT_ABSENT"]
    elif family == "COMBINED_REOPEN" and plan["bad_report_at"] <= knowledge < plan["revision_at"]:
        reported[asset]["custody"]["external"] -= plan["impact_units"]
    rows = []
    for current_asset in world["assets"]:
        scale = world["assets"][current_asset]
        for comparison, scope in [("A", investor) for investor in world["investors"]] + [("B", "customer_liability")]:
            expected = available[current_asset]["investors"][scope] if comparison == "A" else available[current_asset]["liability"]
            if comparison == "A":
                amount = reported[current_asset]["investors"][scope]
            else:
                amounts = list(reported[current_asset]["custody"].values())
                amount = None if any(value is None for value in amounts) else sum(amounts)
            difference = None if amount is None else expected - amount
            data_state = states.get((current_asset, comparison), "COMPLETE")
            reconciliation = "NOT_EVALUATED" if data_state != "COMPLETE" else "MATCHED" if difference == 0 else "MISMATCH"
            rows.append({"asset": current_asset, "comparison": comparison, "scope": scope,
                         "balance_at": BALANCE, "knowledge_at": knowledge,
                         "expected": text_amount(expected, scale),
                         "reported": None if amount is None else text_amount(amount, scale),
                         "difference": None if difference is None else text_amount(difference, scale),
                         "data_state": data_state, "reconciliation_state": reconciliation,
                         "provisional": data_state != "COMPLETE",
                         "required_codes": reasons.get((current_asset, comparison), reasons.get(current_asset, []))})
    return rows


def verify_findings(payload, expected):
    """A mismatch aborts evaluation, never becomes a predictive success/failure."""
    def key(row):
        return row["asset"], row["comparison"], row["scope"]
    actual = payload["findings"]
    if len(actual) != len(expected) or len({key(row) for row in actual}) != len(actual):
        raise ValueError("TRIAGE_TRUTH_MISMATCH: finding roster/uniqueness")
    by_key = {key(row): row for row in actual}
    for row in expected:
        observed = by_key.get(key(row))
        observed_fields = None if observed is None else {field: observed.get(field) for field in COMPARE_FIELDS}
        expected_fields = {field: row[field] for field in COMPARE_FIELDS}
        if observed is None or encoded(observed_fields) != encoded(expected_fields):
            detail = {"key": key(row), "expected": expected_fields, "actual": observed_fields}
            raise ValueError("TRIAGE_TRUTH_MISMATCH: independent financial/state expectation " + encoded(detail).decode().strip())
        codes = {issue["code"] for issue in observed["issues"]}
        if not set(row["required_codes"]) <= codes:
            raise ValueError("TRIAGE_TRUTH_MISMATCH: missing independent reason " + repr(key(row)))
    return {"findings": len(expected), "financial_state_fields_equal": True, "required_issue_codes_present": True}


def scope_label(expected, asset, *, observed=True, in_scope=True):
    if not observed:
        return None, "H_NOT_OBSERVED"
    if not in_scope:
        return None, "OUT_OF_SCOPE_OBSERVABILITY_LIMIT"
    rows = [row for row in expected if row["asset"] == asset]
    if not rows or not any(row["comparison"] == "A" for row in rows) or not any(row["comparison"] == "B" for row in rows):
        raise ValueError("TRIAGE_LABEL_SCOPE: missing A/B finding coverage")
    opened = any(row["data_state"] != "COMPLETE" or row["reconciliation_state"] != "MATCHED" for row in rows)
    return int(opened), "OPEN_SCOPE_FINDING_AT_H" if opened else "ALL_SCOPE_FINDINGS_MATCHED_AT_H"


def _check(budget, *, force=False):
    if budget is not None:
        budget.check(force=force)


def _file_entry(path):
    raw = Path(path).read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _verify_bundle_file(bundle, root, path):
    relative = Path(path).resolve().relative_to(root).as_posix()
    expected = bundle.get("files", {}).get(relative)
    if expected != _file_entry(path):
        raise ValueError("TRIAGE_BUNDLE_CHANGED: immutable generated file differs: " + relative)


def _validate_freeze(freeze, split_hash, root):
    if not isinstance(freeze, dict) or freeze.get("status") != "FROZEN":
        raise ValueError("TRIAGE_HOLDOUT_LOCK: frozen model/rankings required")
    if freeze.get("contract_hash") != CONTRACT_SHA256 or freeze.get("split_hash") != split_hash:
        raise ValueError("TRIAGE_HOLDOUT_LOCK: contract/split hash mismatch")
    if not isinstance(freeze.get("model_id"), str) or not freeze["model_id"]:
        raise ValueError("TRIAGE_HOLDOUT_LOCK: model identity required")
    if not isinstance(freeze.get("prediction_hash"), str) or re.fullmatch(r"[0-9a-f]{64}", freeze["prediction_hash"]) is None:
        raise ValueError("TRIAGE_HOLDOUT_LOCK: complete unlabelled rankings hash required")
    for key, relative in (("dataset_bundle", "bundle.json"), ("truth_catalog", "truth/plan.json")):
        if freeze.get(key) != _file_entry(root / relative):
            raise ValueError("TRIAGE_HOLDOUT_LOCK: frozen dataset/truth binding differs: " + key)


def evaluate_labels(input_path, splits=("train", "validation"), freeze=None, output=None, budget=None):
    """Open only the authorized labels and verify engine H on owned DB copies.

    Final test and challenge must be requested together after a model/ranking
    freeze. An exclusive persistent marker prevents a repeated final truth read.
    """
    root = Path(input_path).resolve()
    requested = tuple(splits)
    if not requested or len(set(requested)) != len(requested) or not set(requested) <= {"train", "validation", "test", "challenge"}:
        raise ValueError("TRIAGE_LABEL_SCOPE: invalid split request")
    public = load(root / "episodes.json")
    split = load(root / "splits.json")
    mapping = validate_splits(split)
    split_hash = digest(split)
    episodes = public["episodes"]
    if len({row["episode_id"] for row in episodes}) != len(episodes) or set(mapping) != {row["episode_id"] for row in episodes}:
        raise ValueError("TRIAGE_LABEL_SCOPE: incomplete or duplicate episode roster")
    for row in episodes:
        if mapping.get(row["episode_id"]) != (row["world_id"], row["split"]) or row["balance_at"] != BALANCE or row["as_of"] != AS_OF:
            raise ValueError("TRIAGE_LABEL_SCOPE: inconsistent public unit identity")
    selected = [row for row in episodes if row["split"] in requested]
    if not selected:
        raise ValueError("TRIAGE_LABEL_SCOPE: requested splits contain no episodes")
    paths = []
    for row in selected:
        path = (root / row["selection_file"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError("TRIAGE_LABEL_SCOPE: selection escapes bundle")
        databases = [source.database for source in read_selection(path).sources]
        if any(not database.is_relative_to(root) for database in databases):
            raise ValueError("TRIAGE_LABEL_SCOPE: synthetic source escapes generated bundle")
        paths.extend(databases)
    destination = None if output is None else preflight_output(output, paths, (root / "episodes.json", root / "splits.json", root / "bundle.json", root / "truth/plan.json"))
    heldout = bool(set(requested) & {"test", "challenge"})
    if heldout:
        if set(requested) != {"test", "challenge"}:
            raise ValueError("TRIAGE_HOLDOUT_LOCK: evaluate test and challenge together once")
        _validate_freeze(freeze, split_hash, root)
        marker = root / "truth/final-evaluation-lock.json"
        with marker.open("xb") as stream:
            stream.write(encoded({"status": "STARTED", "freeze": freeze, "splits": list(requested)}))
    # No private horizon plan is read before the holdout freeze gate above.
    bundle = load(root / "bundle.json")
    if bundle.get("split_hash") != split_hash:
        raise ValueError("TRIAGE_BUNDLE_CHANGED: split hash differs")
    for path in (root / "episodes.json", root / "splits.json", root / "truth/plan.json"):
        _verify_bundle_file(bundle, root, path)
    catalog = load(root / "truth/plan.json")
    if catalog.get("format") != "triage-truth-catalog-v1" or catalog["split_hash"] != split_hash:
        raise ValueError("TRIAGE_LABEL_SCOPE: private/public coverage mismatch")
    private = {"worlds": {}, "episodes": []}
    private_hashes = {}
    for split_name in requested:
        if not any(row["split"] == split_name for row in selected):
            continue
        entry = catalog["files"][split_name]
        private_path = (root / entry["path"]).resolve()
        if not private_path.is_relative_to(root / "truth"):
            raise ValueError("TRIAGE_LABEL_SCOPE: private file escapes truth directory")
        if bundle.get("files", {}).get(private_path.relative_to(root).as_posix()) != {key: entry[key] for key in ("bytes", "sha256")}:
            raise ValueError("TRIAGE_BUNDLE_CHANGED: private catalog entry differs from generated bundle")
        raw = private_path.read_bytes()
        if len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("TRIAGE_LABEL_SCOPE: private plan file hash differs")
        split_plan = load(private_path)
        if split_plan.get("format") != "triage-truth-plan-v1" or split_plan["split"] != split_name or split_plan["split_hash"] != split_hash:
            raise ValueError("TRIAGE_LABEL_SCOPE: private split metadata mismatch")
        if set(private["worlds"]) & set(split_plan["worlds"]):
            raise ValueError("TRIAGE_LABEL_SCOPE: world appears in two private splits")
        private["worlds"].update(split_plan["worlds"])
        private["episodes"].extend(split_plan["episodes"])
        private_hashes[split_name] = entry["sha256"]
    plans = {row["episode_id"]: row for row in private["episodes"]}
    if len(plans) != len(private["episodes"]) or set(plans) != {row["episode_id"] for row in selected}:
        raise ValueError("TRIAGE_LABEL_SCOPE: missing or duplicate private episodes")
    document = {"format": "triage-labels-v1", "target": "unresolved_at_horizon", "horizon_hours": 24,
                "contract_sha256": CONTRACT_SHA256, "splits_sha256": split_hash,
                "evaluated_splits": list(requested), "units": [], "verification": []}
    manager = new_output_directory(destination) if destination is not None else nullcontext(None)
    with manager as folder:
        if folder is not None:
            (folder / "horizon").mkdir()
        from ..store import Store
        from ..engine import reconcile
        for episode in selected:
            _check(budget)
            plan = plans[episode["episode_id"]]
            world = private["worlds"][episode["world_id"]]
            if (plan["world_id"], plan["split"]) != mapping[episode["episode_id"]] or world["world_id"] != episode["world_id"]:
                raise ValueError("TRIAGE_LABEL_SCOPE: private group/split mismatch")
            selection = root / episode["selection_file"]
            _verify_bundle_file(bundle, root, selection)
            chosen = read_selection(selection)
            if len(chosen.sources) != 1:
                raise ValueError("TRIAGE_LABEL_SCOPE: one owned source per episode")
            source = chosen.sources[0].database
            _verify_bundle_file(bundle, root, source)
            saved = budgeted_read_selected_sources(chosen, budget)
            expected_ids = set(episode["history_run_ids"] + [episode["current_run_id"]])
            if {run.run_id for run in saved.runs} != expected_ids:
                raise ValueError("TRIAGE_LABEL_SCOPE: saved observation scope differs")
            initial_checks = []
            for run in saved.runs:
                initial_checks.append(verify_findings(run.payload, expected_findings(world, plan, run.payload["knowledge_at"])))
            before_bytes = source.read_bytes()
            source_sha = hashlib.sha256(before_bytes).hexdigest()
            if any(os.path.lexists(Path(str(source) + suffix)) for suffix in SIDECARS):
                raise ValueError("TRIAGE_SOURCE: unexpected sidecar")
            horizon_payload = None
            expectation = None
            closure_proof = None
            horizon_id = None
            observed = plan["available_until"] >= HORIZON
            if observed:
                # Only the independently planned integer expectations determine a label.
                expectation = expected_findings(world, plan, HORIZON)
                with tempfile.TemporaryDirectory(prefix="triage-horizon-copy-", dir=getattr(budget, "temporary_root", None)) as temporary:
                    copy = Path(temporary) / "source.sqlite3"
                    copy.write_bytes(before_bytes)
                    _check(budget, force=True)
                    store = Store(copy)
                    try:
                        if plan["intermediate_closure_at"] is not None:
                            intermediate = reconcile(store, BALANCE, plan["intermediate_closure_at"])
                            expected_intermediate = expected_findings(world, plan, plan["intermediate_closure_at"])
                            closure_proof = verify_findings(intermediate, expected_intermediate)
                            if scope_label(expected_intermediate, plan["asset"])[0] != 0:
                                raise ValueError("TRIAGE_TRUTH_MISMATCH: planned intermediate closure absent")
                            closure_proof.update(knowledge_at=plan["intermediate_closure_at"], run_id=intermediate["run_id"])
                        horizon_result = reconcile(store, BALANCE, HORIZON)
                        horizon_id = horizon_result["run_id"]
                        checked = verify_findings(horizon_result, expectation)
                        horizon_payload = store.db.execute("SELECT payload FROM runs WHERE id=?", (horizon_id,)).fetchone()[0]
                    finally:
                        store.close()
                    _check(budget, force=True)
                if folder is not None:
                    save(folder / "horizon" / (episode["episode_id"] + ".json"),
                         {"run_id": horizon_id, "raw_payload": horizon_payload, "independent_expected_findings": expectation,
                          "verification": checked, "intermediate_closure": closure_proof})
            if source.read_bytes() != before_bytes or any(os.path.lexists(Path(str(source) + suffix)) for suffix in SIDECARS):
                raise ValueError("TRIAGE_SOURCE_CHANGED: horizon evaluation changed original source")
            after_read = budgeted_read_selected_sources(chosen, budget)
            if saved.sources != after_read.sources or [(run.run_id, run.payload_text) for run in saved.runs] != [(run.run_id, run.payload_text) for run in after_read.runs]:
                raise ValueError("TRIAGE_SOURCE_CHANGED: saved source schema/runs/proofs changed")
            proof = {"episode_id": episode["episode_id"], "source_sha256": source_sha,
                     "source_preserved": True, "source_proofs_before": saved.sources, "source_proofs_after": after_read.sources,
                     "observed_t_checks": initial_checks, "horizon_observed": observed,
                     "horizon_run_id": horizon_id, "intermediate_closure": closure_proof}
            document["verification"].append(proof)
            for asset in world["assets"]:
                label, reason = scope_label(expectation, asset, observed=observed,
                                            in_scope=plan["family"] != "OBSERVABILITY_LIMIT")
                document["units"].append({"unit_id": unit_id(episode["episode_id"], asset),
                    "world_id": episode["world_id"], "episode_id": episode["episode_id"], "asset": asset,
                    "split": episode["split"], "balance_at": BALANCE, "as_of": AS_OF, "horizon": HORIZON,
                    "label": label, "reason": reason, "family": plan["family"],
                    "twin_group": plan["twin_group"], "observed_run_id": episode["current_run_id"],
                    "horizon_run_id": horizon_id,
                    "truth_plan_sha256": private_hashes[episode["split"]]})
            _check(budget)
        if len(document["units"]) != len(selected) * len(public["assets"]):
            raise ValueError("TRIAGE_LABEL_SCOPE: incomplete asset-unit count")
        document["inventory"] = {"episodes": len(selected), "units": len(document["units"]),
            "positive": sum(row["label"] == 1 for row in document["units"]),
            "negative": sum(row["label"] == 0 for row in document["units"]),
            "unknown": sum(row["label"] is None for row in document["units"])}
        if folder is not None:
            save(folder / "labels.json", document)
        _check(budget)
    return document
