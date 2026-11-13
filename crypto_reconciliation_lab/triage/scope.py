"""Full-experiment public roster gates; never reads private horizon plans."""
from collections import Counter
import hashlib
from pathlib import Path, PurePosixPath
import re

from . import EXPERIMENT_FORMAT, HORIZON_HOURS, TARGET
from .contracts import (AS_OF, BALANCE_AT, CONTRACT_SHA256, HORIZON_AT, SPLITS,
                        digest, load, timestamp, unit_id, validate_splits)

_DESIGN = "triage-synthetic-2026-11-v1"
_ASSETS = {"ASSET_A": 8, "ASSET_B": 2}


def _require(condition, message):
    if not condition:
        raise ValueError("TRIAGE_SCOPE: " + message)


def _entry(value):
    return (isinstance(value, dict) and set(value) == {"bytes", "sha256"}
            and type(value["bytes"]) is int and value["bytes"] >= 0
            and isinstance(value["sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is not None)


def _relative(value):
    return (isinstance(value, str) and value and "\\" not in value
            and not PurePosixPath(value).is_absolute()
            and all(part not in ("", ".", "..") for part in value.split("/")))


def _same_time(value, expected):
    try:
        return timestamp(value) == timestamp(expected)
    except ValueError:
        return False


def load_public_scope(root):
    """Derive expected units only from mutually bound public v1 documents.

    Main counts and split allocation come from the frozen experiment contract.
    The two allowed small modes retain their declared public split assignments.
    Hash-only catalog entries are checked without opening any private plan.
    """
    root = Path(root)
    try:
        public = load(root / "episodes.json")
        splits = load(root / "splits.json")
        bundle = load(root / "bundle.json")
        catalog = load(root / "truth/plan.json")
    except (OSError, ValueError) as exc:
        raise ValueError("TRIAGE_SCOPE: public roster is unreadable or invalid") from exc
    _require(all(isinstance(value, dict) for value in (public, splits, bundle, catalog)),
             "public documents must be objects")
    _require(public.get("format") == "triage-episodes-v1"
             and public.get("experiment_contract") == EXPERIMENT_FORMAT
             and bundle.get("format") == EXPERIMENT_FORMAT
             and catalog.get("format") == "triage-truth-catalog-v1", "public format mismatch")
    mode = public.get("mode")
    _require(mode in ("main", "smoke", "archive_smoke"), "unsupported public mode")
    _require(all(doc.get("mode") == mode and doc.get("design_id") == _DESIGN
                 for doc in (public, bundle, catalog)), "mode/design disagreement")
    assets = public.get("assets")
    _require(isinstance(assets, dict) and assets == _ASSETS
             and all(type(value) is int for value in assets.values()), "public assets differ from contract")
    _require(_same_time(public.get("balance_at"), BALANCE_AT)
             and _same_time(public.get("as_of"), AS_OF)
             and _same_time(public.get("horizon"), HORIZON_AT)
             and type(public.get("horizon_hours")) is int
             and public["horizon_hours"] == HORIZON_HOURS, "public cuts differ from contract")
    try:
        mapping = validate_splits(splits)
    except ValueError as exc:
        raise ValueError("TRIAGE_SCOPE: invalid public split roster") from exc
    split_hash = digest(splits)
    _require(bundle.get("split_hash") == split_hash == catalog.get("split_hash"),
             "public split hash disagreement")
    groups = splits["groups"]
    expected_worlds = 144 if mode == "main" else 2
    _require(len(groups) == expected_worlds and all(len(g["episode_ids"]) == 4 for g in groups),
             "world/episode counts differ from declared mode")
    if mode == "main":
        _require(Counter(g["split"] for g in groups)
                 == {"train": 72, "validation": 24, "test": 24, "challenge": 24},
                 "main split allocation differs from contract")
    episodes = public.get("episodes")
    _require(isinstance(episodes, list) and len(episodes) == expected_worlds * 4,
             "public episode roster is incomplete")
    _require(all(type(bundle.get(key)) is int and bundle[key] == count for key, count in
                 (("worlds", expected_worlds), ("episodes", len(episodes)),
                  ("visible_units", len(episodes) * len(assets)))), "bundle inventory differs from public roster")
    files = bundle.get("files")
    _require(isinstance(files, dict) and all(_relative(name) and _entry(value)
                                           for name, value in files.items()), "invalid bundle file manifest")
    for relative in ("episodes.json", "splits.json", "truth/plan.json"):
        data = (root / relative).read_bytes()
        _require(files.get(relative) == {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()},
                 "public file differs from bundle: " + relative)
    catalog_files = catalog.get("files")
    _require(isinstance(catalog_files, dict) and set(catalog_files) == set(SPLITS),
             "catalog split inventory differs")
    for split, entry in catalog_files.items():
        _require(isinstance(entry, dict) and set(entry) == {"path", "bytes", "sha256"},
                 "invalid hash-only catalog entry")
        relative = entry["path"]
        proof = {key: entry[key] for key in ("bytes", "sha256")}
        _require(relative == "truth/" + split + ".json" and _entry(proof)
                 and files.get(relative) == proof, "catalog entry differs from bundle")
    expected = {}
    observed_episodes = set()
    for episode in episodes:
        _require(isinstance(episode, dict), "episode must be an object")
        identity = episode.get("episode_id")
        _require(isinstance(identity, str) and identity and identity not in observed_episodes,
                 "duplicate or invalid public episode")
        observed_episodes.add(identity)
        _require(mapping.get(identity) == (episode.get("world_id"), episode.get("split")),
                 "episode/world/split disagreement")
        _require(_same_time(episode.get("balance_at"), BALANCE_AT)
                 and _same_time(episode.get("as_of"), AS_OF), "episode cut differs from common public cut")
        selection = episode.get("selection_file")
        _require(_relative(selection) and selection in files, "episode selection missing from bundle")
        for asset in assets:
            uid = unit_id(identity, asset)
            expected[uid] = {"unit_id": uid, "episode_id": identity, "asset": asset,
                             "world_id": episode["world_id"], "split": episode["split"],
                             "balance_at": BALANCE_AT, "as_of": AS_OF}
    _require(observed_episodes == set(mapping), "public episode and split inventories disagree")
    return {"units": expected, "splits": splits, "split_hash": split_hash, "mode": mode}


def validate_unit_roster(rows, expected, *, label):
    """Check exact identities, including closed units, against an external roster."""
    _require(isinstance(rows, list), label + " units must be a list")
    seen = set()
    for row in rows:
        _require(isinstance(row, dict), label + " unit must be an object")
        uid = row.get("unit_id")
        _require(isinstance(uid, str) and uid in expected and uid not in seen,
                 label + " contains an extra, duplicate or incorrect unit")
        seen.add(uid)
        reference = expected[uid]
        _require(all(row.get(key) == reference[key] for key in ("episode_id", "asset", "world_id", "split"))
                 and all(_same_time(row.get(key), reference[key]) for key in ("balance_at", "as_of")),
                 label + " unit scope disagrees with public inventory")
    _require(seen == set(expected), label + " omits public units")


def validate_final_labels(labels, scope):
    """Validate the complete final union before labels_for may select a split."""
    _require(isinstance(labels, dict) and labels.get("format") == "triage-labels-v1"
             and labels.get("target") == TARGET and labels.get("horizon_hours") == HORIZON_HOURS
             and labels.get("contract_sha256") == CONTRACT_SHA256
             and labels.get("splits_sha256") == scope["split_hash"], "final label contract mismatch")
    expected = {uid: row for uid, row in scope["units"].items() if row["split"] in ("test", "challenge")}
    validate_unit_roster(labels.get("units"), expected, label="final labels")
    _require(all(_same_time(row.get("horizon"), HORIZON_AT) for row in labels["units"]),
             "final label horizon disagrees with contract")
