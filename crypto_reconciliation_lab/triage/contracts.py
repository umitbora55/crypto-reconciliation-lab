"""Frozen feature/identity boundaries; no truth or training-library dependency."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re

from ..review.validation import strict_json
from . import EXPERIMENT_FORMAT, FEATURE_FORMAT, TARGET, HORIZON_HOURS

CONTRACT_SHA256 = "d532627546c49a582397fcb700ad723269fafe45ac25af7f162eded5f85d7428"
BALANCE_AT = "2026-11-10T01:00:00.000000Z"
AS_OF = "2026-11-11T00:00:00.000000Z"
HORIZON_AT = "2026-11-12T00:00:00.000000Z"
FEATURE_NAMES = (
    "a_open_count", "b_open_count", "a_incomplete_count", "b_incomplete_count",
    "a_conflict_count", "b_conflict_count", "a_stale_count", "b_stale_count",
    "a_mismatch_count", "b_mismatch_count", "a_not_evaluated_count", "b_not_evaluated_count",
    "missing_manifest_count", "missing_report_count", "pending_correction_count",
    "observed_age_hours", "observation_count", "open_observation_count",
    "a_relative_difference_max", "b_relative_difference",
    "a_ratio_undefined_count", "b_ratio_undefined_count",
)
DECIMAL_FEATURES = frozenset(("observed_age_hours", "a_relative_difference_max", "b_relative_difference"))
SPLITS = ("train", "validation", "test", "challenge")


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                       separators=(",", ":")) + "\n").encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def load(path):
    return strict_json(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    Path(path).write_bytes(encoded(value))


def timestamp(value):
    if not isinstance(value, str) or re.fullmatch(
            r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)", value) is None:
        raise ValueError("TRIAGE_TIME: timezone-aware ISO 8601 required")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError as exc:
        raise ValueError("TRIAGE_TIME: invalid timestamp") from exc


def unit_id(episode_id, asset):
    if not all(isinstance(x, str) and x and "::" not in x for x in (episode_id, asset)):
        raise ValueError("TRIAGE_ID: nonempty neutral episode/asset identifiers required")
    return episode_id + "::" + asset


def decimal_value(value):
    if not isinstance(value, str) or re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", value) is None:
        raise ValueError("TRIAGE_DECIMAL: finite plain decimal text required")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("TRIAGE_DECIMAL: invalid decimal") from exc
    if not result.is_finite():
        raise ValueError("TRIAGE_DECIMAL: nonfinite decimal")
    return result


def validate_values(values):
    if not isinstance(values, dict) or set(values) != set(FEATURE_NAMES):
        raise ValueError("TRIAGE_FEATURE_SCHEMA: exact feature allowlist required")
    for name, value in values.items():
        if name in DECIMAL_FEATURES:
            if value is not None and decimal_value(value) < 0:
                raise ValueError("TRIAGE_FEATURE_VALUE: nonnegative derived decimal required")
        elif type(value) is not int or value < 0:
            raise ValueError("TRIAGE_FEATURE_VALUE: nonnegative integer count required")
    return values


def validate_splits(document):
    if not isinstance(document, dict) or set(document) != {"format", "groups"} or document["format"] != "triage-split-v1":
        raise ValueError("TRIAGE_SPLIT: unsupported roster")
    groups, episodes = {}, {}
    if not isinstance(document["groups"], list) or not document["groups"]:
        raise ValueError("TRIAGE_SPLIT: nonempty groups required")
    for row in document["groups"]:
        if not isinstance(row, dict) or set(row) != {"world_id", "split", "episode_ids"}:
            raise ValueError("TRIAGE_SPLIT: invalid group fields")
        world, split, ids = row["world_id"], row["split"], row["episode_ids"]
        if not isinstance(world, str) or not world or world in groups or split not in SPLITS:
            raise ValueError("TRIAGE_SPLIT: duplicate/cross-split world or invalid split")
        if not isinstance(ids, list) or not ids or len(ids) > 4 or any(not isinstance(x, str) or not x or x in episodes for x in ids) or len(ids) != len(set(ids)):
            raise ValueError("TRIAGE_SPLIT: duplicate/cross-split episode or invalid count")
        groups[world] = split
        for episode in ids:
            episodes[episode] = (world, split)
    return episodes


def _provenance_text(value, name):
    if not isinstance(value, str) or not value:
        raise ValueError("TRIAGE_PROVENANCE: nonempty " + name + " required")
    return value


def _finding_pointer(value):
    if not isinstance(value, str) or re.fullmatch(r"/findings/(?:0|[1-9][0-9]*)", value) is None:
        raise ValueError("TRIAGE_PROVENANCE: finding pointer required")
    return value


def _payload_metadata(row, hash_field):
    alias = _provenance_text(row.get("source_alias"), "source_alias")
    value = row.get(hash_field)
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("TRIAGE_PROVENANCE: payload hash required")
    if "payload_file" not in row or (row["payload_file"] is not None
                                     and (not isinstance(row["payload_file"], str) or not row["payload_file"])):
        raise ValueError("TRIAGE_PROVENANCE: payload_file must be text or null")
    return alias, value, row["payload_file"]


def _snapshots(document):
    # Metadata is optional. If supplied, use the episode scope: twins may share
    # a run hash while referring to different copies/aliases of the same payload.
    if "snapshots" not in document:
        return None
    if not isinstance(document["snapshots"], list):
        raise ValueError("TRIAGE_PROVENANCE: snapshots must be a list")
    result = {}
    for snapshot in document["snapshots"]:
        if not isinstance(snapshot, dict):
            raise ValueError("TRIAGE_PROVENANCE: snapshot must be an object")
        key = (_provenance_text(snapshot.get("episode_id"), "episode_id"),
               _provenance_text(snapshot.get("run_id"), "run_id"))
        known = timestamp(snapshot.get("knowledge_at"))
        if key in result or known > timestamp(AS_OF):
            raise ValueError("TRIAGE_PROVENANCE: duplicate or future snapshot")
        result[key] = (known, _payload_metadata(snapshot, "sha256"))
    return result


def _validate_provenance(row, snapshots, known_runs, finding_assets):
    proofs, refs = row["feature_provenance"], row["finding_refs"]
    if (not isinstance(proofs, dict) or set(proofs) != set(FEATURE_NAMES)
            or not isinstance(refs, list) or not refs):
        raise ValueError("TRIAGE_PROVENANCE: missing feature/finding sources")
    cutoff, balance = timestamp(row["as_of"]), timestamp(row["balance_at"])
    current_refs = set()

    def bind_finding(run_id, pointer):
        key = (row["episode_id"], run_id, pointer)
        if finding_assets.setdefault(key, row["asset"]) != row["asset"]:
            raise ValueError("TRIAGE_PROVENANCE: same saved finding has contradictory asset scope")

    def bind(run_id, known, metadata=None):
        key = (row["episode_id"], run_id)
        if snapshots is not None:
            snapshot = snapshots.get(key)
            if snapshot is None or known != snapshot[0] or (metadata is not None and metadata != snapshot[1]):
                raise ValueError("TRIAGE_PROVENANCE: source/ref contradicts episode snapshot")
        previous = known_runs.get(key)
        if previous is not None:
            if previous[0] != known or (metadata is not None and previous[1] is not None and previous[1] != metadata):
                raise ValueError("TRIAGE_PROVENANCE: contradictory run metadata")
            if metadata is None:
                metadata = previous[1]
        known_runs[key] = (known, metadata)

    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("finding"), dict):
            raise ValueError("TRIAGE_PROVENANCE: finding reference object required")
        run_id = _provenance_text(ref.get("run_id"), "run_id")
        pointer = _finding_pointer(ref.get("pointer"))
        bind_finding(run_id, pointer)
        finding = ref["finding"]
        if (finding.get("asset") != row["asset"] or timestamp(finding.get("balance_at")) != balance
                or timestamp(finding.get("knowledge_at")) != cutoff):
            raise ValueError("TRIAGE_PROVENANCE: current finding scope mismatch")
        evidence = finding.get("evidence_ids")
        if not isinstance(evidence, list) or any(not isinstance(e, str) or not e for e in evidence):
            raise ValueError("TRIAGE_PROVENANCE: evidence IDs must be a list of strings")
        if (run_id, pointer) in current_refs:
            raise ValueError("TRIAGE_PROVENANCE: duplicate current finding reference")
        current_refs.add((run_id, pointer))
        bind(run_id, cutoff, _payload_metadata(ref, "payload_sha256"))

    current_sources = set()
    for proof in proofs.values():
        if not isinstance(proof, dict) or not isinstance(proof.get("sources"), list) or not proof["sources"]:
            raise ValueError("TRIAGE_PROVENANCE: every aggregate needs its observed source set")
        times = []
        for source in proof["sources"]:
            if not isinstance(source, dict):
                raise ValueError("TRIAGE_PROVENANCE: source must be an object")
            run_id = _provenance_text(source.get("run_id"), "run_id")
            pointer = _finding_pointer(source.get("pointer"))
            bind_finding(run_id, pointer)
            if source.get("evidence_pointer") != pointer + "/evidence_ids":
                raise ValueError("TRIAGE_PROVENANCE: finding/evidence pointer mismatch")
            known = timestamp(source.get("knowledge_at"))
            if known > cutoff:
                raise ValueError("TRIAGE_PROVENANCE: future source")
            bind(run_id, known)
            times.append(known)
            if known == cutoff:
                current_sources.add((run_id, pointer))
        if timestamp(proof.get("latest_knowledge_at")) != max(times):
            raise ValueError("TRIAGE_PROVENANCE: summary differs from source time maximum")
    if current_sources != current_refs:
        raise ValueError("TRIAGE_PROVENANCE: current sources and finding references disagree")


def validate_features(document, splits=None):
    required = {"format", "experiment_format", "contract_sha256", "splits_sha256", "feature_names", "units"}
    optional = {"source_files", "source_proofs", "snapshots", "inventory", "subset"}
    if not isinstance(document, dict) or not required <= document.keys() or set(document) - required - optional:
        raise ValueError("TRIAGE_FEATURE_SCHEMA: missing or unknown document fields")
    if (document["format"] != FEATURE_FORMAT or document["experiment_format"] != EXPERIMENT_FORMAT
            or document["contract_sha256"] != CONTRACT_SHA256 or document["feature_names"] != list(FEATURE_NAMES)):
        raise ValueError("TRIAGE_FEATURE_SCHEMA: contract/version/order mismatch")
    if not isinstance(document["splits_sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", document["splits_sha256"]) is None:
        raise ValueError("TRIAGE_SPLIT: hash required")
    mapping = validate_splits(splits) if splits is not None else None
    if mapping is not None and digest(splits) != document["splits_sha256"]:
        raise ValueError("TRIAGE_SPLIT: feature roster hash mismatch")
    if not isinstance(document["units"], list):
        raise ValueError("TRIAGE_FEATURE_SCHEMA: units must be a list")
    identities = set()
    snapshots, known_runs, finding_assets = _snapshots(document), {}, {}
    for row in document["units"]:
        if not isinstance(row, dict) or not {"unit_id", "world_id", "episode_id", "split", "asset", "balance_at", "as_of", "first_seen_at", "status", "features", "feature_provenance", "finding_refs"} <= row.keys():
            raise ValueError("TRIAGE_UNIT: missing fields")
        if row["unit_id"] != unit_id(row["episode_id"], row["asset"]) or row["unit_id"] in identities:
            raise ValueError("TRIAGE_UNIT: duplicate or incorrect identity")
        identities.add(row["unit_id"])
        if not isinstance(row["world_id"], str) or not row["world_id"] or row["split"] not in SPLITS:
            raise ValueError("TRIAGE_UNIT: invalid grouping")
        if mapping is not None and mapping.get(row["episode_id"]) != (row["world_id"], row["split"]):
            raise ValueError("TRIAGE_SPLIT: unit crosses world split")
        if timestamp(row["balance_at"]) != timestamp(BALANCE_AT) or timestamp(row["as_of"]) != timestamp(AS_OF):
            raise ValueError("TRIAGE_TIME: incompatible common economic/knowledge cut")
        if row["status"] not in ("OPEN", "NO_OPEN_FINDING"):
            raise ValueError("TRIAGE_UNIT: invalid eligibility")
        if row["first_seen_at"] is not None and timestamp(row["first_seen_at"]) > timestamp(row["as_of"]):
            raise ValueError("TRIAGE_TIME: future first observation")
        if row["status"] == "OPEN" and row["first_seen_at"] is None:
            raise ValueError("TRIAGE_UNIT: OPEN requires observed first time")
        validate_values(row["features"])
        _validate_provenance(row, snapshots, known_runs, finding_assets)
    return document
