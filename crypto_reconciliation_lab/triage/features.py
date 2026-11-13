"""Allowlisted observations from saved payloads only; no truth or live Store."""
from copy import deepcopy
from decimal import Context, Decimal, localcontext, ROUND_HALF_EVEN
import os
from pathlib import Path

from ..review.adapter import read_selection
from ..review.publication import new_output_directory
from . import EXPERIMENT_FORMAT, FEATURE_FORMAT
from .contracts import (CONTRACT_SHA256, FEATURE_NAMES, DECIMAL_FEATURES, AS_OF,
                        BALANCE_AT, decimal_value, digest, encoded, load, save,
                        timestamp, unit_id, validate_features, validate_splits)
from .safeio import preflight_output
from .budget import budgeted_read_selected_sources

ISSUE_CODES = {
    "missing_manifest_count": frozenset(("MANIFEST_ABSENT", "CORRECTION_MANIFEST_ABSENT")),
    "missing_report_count": frozenset(("REPORT_ABSENT",)),
    "pending_correction_count": frozenset(("TARGET_PENDING", "CORRECTION_MANIFEST_COUNT")),
}


def is_open(finding):
    return (finding["data_state"], finding["reconciliation_state"]) != ("COMPLETE", "MATCHED")


def derived_text(numerator, denominator):
    # Derived model features have a declared rounding policy independent of the
    # financial calculator's trap-all context; original quantities are untouched.
    with localcontext(Context(prec=100, rounding=ROUND_HALF_EVEN)):
        value = (numerator / denominator).quantize(Decimal("0.000000000000000001"))
    return format(value, "f")


def _sources(run, indexes):
    # A pointer to the actual evidence-ID array preserves the complete contributing
    # set without copying its large strings once per aggregated feature.
    return [{"run_id": run.run_id, "pointer": f"/findings/{index}",
             "evidence_pointer": f"/findings/{index}/evidence_ids",
             "knowledge_at": run.payload["knowledge_at"]} for index in indexes]


def extract_episode(runs, episode, payload_paths=None):
    """Accept SavedRun objects only; no database/intake/truth API is available here."""
    runs = list(runs)
    if not runs or len({r.run_id for r in runs}) != len(runs):
        raise ValueError("TRIAGE_HISTORY: missing or duplicate selected run")
    selected = [r for r in runs if r.run_id == episode["current_run_id"]]
    if len(selected) != 1:
        raise ValueError("TRIAGE_HISTORY: exactly one declared T run required")
    current = selected[0]
    if timestamp(current.payload["knowledge_at"]) != timestamp(episode["as_of"]) or timestamp(episode["as_of"]) != timestamp(AS_OF):
        raise ValueError("TRIAGE_HISTORY: main run must represent common T")
    if timestamp(current.payload["balance_at"]) != timestamp(BALANCE_AT):
        raise ValueError("TRIAGE_HISTORY: economic cut mismatch")
    seen_times = set()
    for run in runs:
        p = run.payload
        if (run.source_alias != current.source_alias or p["configuration"] != current.payload["configuration"] or p["rule_version"] != current.payload["rule_version"]
                or timestamp(p["balance_at"]) != timestamp(current.payload["balance_at"])):
            raise ValueError("TRIAGE_HISTORY: incompatible configuration/rule/economic cut")
        time = timestamp(p["knowledge_at"])
        if time > timestamp(AS_OF) or time in seen_times:
            raise ValueError("TRIAGE_HISTORY: future or duplicate knowledge cut")
        seen_times.add(time)
    runs.sort(key=lambda r: timestamp(r.payload["knowledge_at"]))
    payload_paths = payload_paths or {}
    units = []
    for asset in sorted(current.payload["configuration"]["assets"]):
        indexed = [(i, f) for i, f in enumerate(current.payload["findings"]) if f["asset"] == asset]
        if not indexed:
            raise ValueError("TRIAGE_FINDINGS: missing asset coverage")
        values, provenance = {}, {}
        current_sources = _sources(current, [i for i, _ in indexed])

        def set_feature(name, value, sources, meaning):
            values[name] = value
            provenance[name] = {"type": "decimal_text_or_null" if name in DECIMAL_FEATURES else "nonnegative_integer",
                "meaning": meaning, "null_policy": "undefined remains null" if name in DECIMAL_FEATURES else "observed count; no inferred missing data",
                "sources": sources, "latest_knowledge_at": max((s["knowledge_at"] for s in sources), key=timestamp)}

        ratios = {}
        for comparison, prefix in (("A", "a"), ("B", "b")):
            group = [(i, f) for i, f in indexed if f["comparison"] == comparison]
            sources = _sources(current, [i for i, _ in group])
            if not group or (comparison == "B" and len(group) != 1):
                raise ValueError("TRIAGE_FINDINGS: invalid A/B coverage")
            set_feature(prefix + "_open_count", sum(is_open(f) for _, f in group), sources, "Observed open " + comparison + " findings")
            for state in ("INCOMPLETE", "CONFLICT", "STALE"):
                set_feature(prefix + "_" + state.lower() + "_count", sum(f["data_state"] == state for _, f in group), sources, comparison + " saved data_state=" + state)
            for state in ("MISMATCH", "NOT_EVALUATED"):
                set_feature(prefix + "_" + state.lower() + "_count", sum(f["reconciliation_state"] == state for _, f in group), sources, comparison + " saved reconciliation_state=" + state)
            defined, unknown = [], 0
            for _, finding in group:
                denominator, difference = finding["expected"], finding["difference"]
                if denominator is None or difference is None or decimal_value(denominator) == 0:
                    unknown += 1
                else:
                    defined.append(derived_text(decimal_value(difference).copy_abs(),
                                                decimal_value(denominator).copy_abs()))
            ratios[prefix] = max(defined, key=decimal_value) if defined else None
            name = "a_relative_difference_max" if prefix == "a" else "b_relative_difference"
            set_feature(name, ratios[prefix], sources, "Within-asset abs(saved difference)/abs(saved expected); 18-place half-even")
            set_feature(prefix + "_ratio_undefined_count", unknown, sources, "Null difference/expected or zero denominator; no epsilon")
        for name, codes in ISSUE_CODES.items():
            count = sum(issue["code"] in codes for _, f in indexed for issue in f["issues"])
            set_feature(name, count, current_sources, "Observed issue entries with code in " + ",".join(sorted(codes)))
        history_sources, open_times = [], []
        for run in runs:
            group = [(i, f) for i, f in enumerate(run.payload["findings"]) if f["asset"] == asset]
            if not group:
                raise ValueError("TRIAGE_HISTORY: missing asset in an earlier observation")
            history_sources.extend(_sources(run, [i for i, _ in group]))
            if any(is_open(f) for _, f in group):
                open_times.append(run.payload["knowledge_at"])
        first_seen = min(open_times, key=timestamp) if open_times else None
        if first_seen is None:
            age = None
        else:
            elapsed = timestamp(AS_OF) - timestamp(first_seen)
            micros = (elapsed.days * 86400 + elapsed.seconds) * 1000000 + elapsed.microseconds
            age = derived_text(Decimal(micros), Decimal(3600000000))
        set_feature("observed_age_hours", age, history_sources, "Age since first open compatible saved observation, not event/private resolution time")
        set_feature("observation_count", len(runs), history_sources, "Number of distinct compatible saved knowledge cuts")
        set_feature("open_observation_count", len(open_times), history_sources, "Compatible saved cuts with at least one open A/B finding")
        refs = []
        for index, finding in indexed:
            if not set(finding["evidence_ids"]) <= current.payload["evidence"].keys():
                raise ValueError("TRIAGE_PROVENANCE: saved finding references missing evidence")
            refs.append({"source_alias": current.source_alias, "run_id": current.run_id,
                         "pointer": f"/findings/{index}", "payload_sha256": current.payload_sha256,
                         "payload_file": payload_paths.get(current.run_id), "finding": deepcopy(finding)})
        status = "OPEN" if any(is_open(f) for _, f in indexed) else "NO_OPEN_FINDING"
        units.append({"unit_id": unit_id(episode["episode_id"], asset), "episode_id": episode["episode_id"],
                      "world_id": episode["world_id"], "split": episode["split"], "asset": asset,
                      "balance_at": current.payload["balance_at"], "as_of": current.payload["knowledge_at"],
                      "first_seen_at": first_seen, "status": status,
                      "exclusion_reason": None if status == "OPEN" else "All related A/B findings are COMPLETE/MATCHED",
                      "rule_version": current.payload["rule_version"], "configuration_sha256": digest(current.payload["configuration"]),
                      "features": {name: values[name] for name in FEATURE_NAMES},
                      "feature_provenance": {name: provenance[name] for name in FEATURE_NAMES}, "finding_refs": refs})
    return units


def subset(document, split):
    return {**document, "subset": split, "units": [row for row in document["units"] if row["split"] == split]}


def build_features(input_path, output, budget=None):
    """Read a public episode roster, never the generator's private truth tree."""
    root = Path(input_path).resolve()
    if os.path.lexists(Path(output).expanduser().absolute()):
        raise FileExistsError("OUTPUT_EXISTS: choose a new output directory")
    manifest, splits = load(root / "episodes.json"), load(root / "splits.json")
    mapping = validate_splits(splits)
    episodes = manifest["episodes"]
    if len(episodes) != len(mapping) or {e["episode_id"] for e in episodes} != set(mapping):
        raise ValueError("TRIAGE_EPISODES: missing, extra or duplicate episode")
    selections, databases = [], []
    for episode in episodes:
        if mapping[episode["episode_id"]] != (episode["world_id"], episode["split"]):
            raise ValueError("TRIAGE_SPLIT: episode crosses world group")
        path = (root / episode["selection_file"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError("TRIAGE_PATH: selection escapes public dataset")
        selection = read_selection(path)
        selections.append(selection)
        databases.extend(source.database for source in selection.sources)
    destination = preflight_output(output, databases, (root / "episodes.json", root / "splits.json"))
    with new_output_directory(destination) as staging:
        units, snapshots, proofs = [], [], []
        for episode, selection in zip(episodes, selections):
            if budget:
                budget.check()
            saved = budgeted_read_selected_sources(selection, budget)
            expected = set(episode["history_run_ids"]) | {episode["current_run_id"]}
            if {r.run_id for r in saved.runs} != expected:
                raise ValueError("TRIAGE_HISTORY: selected runs differ from declared T/history roster")
            folder = staging / "snapshots" / digest(episode["episode_id"])
            folder.mkdir(parents=True)
            paths = {}
            for run in saved.runs:
                relative = str((folder / (run.run_id + ".json")).relative_to(staging))
                paths[run.run_id] = relative
                (staging / relative).write_bytes(run.payload_text.encode("utf-8"))
                snapshots.append({"episode_id": episode["episode_id"], "source_alias": run.source_alias,
                    "run_id": run.run_id, "knowledge_at": run.payload["knowledge_at"],
                    "payload_file": relative, "sha256": run.payload_sha256})
            units.extend(extract_episode(saved.runs, episode, paths))
            proofs.extend(saved.sources)
        document = {"format": FEATURE_FORMAT, "experiment_format": EXPERIMENT_FORMAT,
                    "contract_sha256": CONTRACT_SHA256, "splits_sha256": digest(splits),
                    "feature_names": list(FEATURE_NAMES), "units": sorted(units, key=lambda u: u["unit_id"]),
                    "source_files": sorted({str(path) for path in databases}), "source_proofs": proofs,
                    "snapshots": snapshots, "inventory": {"units": len(units), "episodes": len(episodes),
                       "open": sum(u["status"] == "OPEN" for u in units),
                       "no_open_finding": sum(u["status"] == "NO_OPEN_FINDING" for u in units)}}
        validate_features(document, splits)
        save(staging / "features.json", document)
        save(staging / "splits.json", splits)
        if budget:
            budget.check()
    return document
