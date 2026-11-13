"""Small, separately planned synthetic worlds; never an input to live ranking.

Economic truth uses integer units and is intentionally independent of the
financial engine and the historical lab generator/oracle. Engine calls are lazy
and confined to fixture construction.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random

from ..review.publication import new_output_directory
from .safeio import preflight_output

FORMAT = "triage-experiment-v1"
DESIGN = "triage-synthetic-2026-11-v1"
OPENING = "2026-11-10T00:00:00.000000Z"
BALANCE = "2026-11-10T01:00:00.000000Z"
AS_OF = "2026-11-11T00:00:00.000000Z"
HORIZON = "2026-11-12T00:00:00.000000Z"
ASSETS = {"ASSET_A": 8, "ASSET_B": 2}


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                       separators=(",", ":")) + "\n").encode("utf-8")


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def save(path, value):
    Path(path).write_bytes(encoded(value))


def at_hours(hours):
    return (datetime.fromisoformat(AS_OF.replace("Z", "+00:00"))
            + timedelta(hours=hours)).isoformat(timespec="microseconds").replace("+00:00", "Z")


def text_amount(units, scale):
    """Convert independent integer accounting units to exact decimal text."""
    if type(units) is not int or type(scale) is not int or not 0 <= scale <= 18:
        raise ValueError("integer units and scale required")
    whole, remainder = divmod(abs(units), 10 ** scale)
    tail = str(remainder).zfill(scale).rstrip("0") if scale else ""
    return ("-" if units < 0 else "") + str(whole) + ("." + tail if tail else "")


def integer_ledger(world, excluded=(), replacement=None):
    """Limited valid-world arithmetic; no production domain helper imports."""
    replacement = replacement or {}
    excluded = set(excluded)
    known = {row["ref"] for row in world["events"]}
    if not excluded <= known or not set(replacement) <= known:
        raise ValueError("unknown independent-plan event")
    result = deepcopy(world["opening"])
    for row in sorted(world["events"], key=lambda value: (value["at"], value["sequence"], value["ref"])):
        if row["ref"] in excluded:
            continue
        quantity = replacement.get(row["ref"], row["units"])
        if type(quantity) is not int or quantity <= 0:
            raise ValueError("positive integer event units required")
        asset = result[row["asset"]]
        if row["sender"] is not None:
            asset["investors"][row["sender"]] -= quantity
        if row["recipient"] is not None:
            asset["investors"][row["recipient"]] += quantity
        if row["kind"] == "deposit":
            asset["custody"][row["custody"]] += quantity
        elif row["kind"] == "withdrawal":
            asset["custody"][row["custody"]] -= quantity
        elif row["kind"] != "transfer":
            raise ValueError("unsupported planned event")
        if min(asset["investors"].values()) < 0 or min(asset["custody"].values()) < 0:
            raise ValueError("unfunded independent world")
    for asset in result.values():
        asset["liability"] = sum(asset["investors"].values())
    return result


def make_world(index, mode="main"):
    if mode not in ("main", "smoke", "archive_smoke") or type(index) is not int:
        raise ValueError("invalid generation mode/index")
    limit = 144 if mode == "main" else 2
    if not 0 <= index < limit:
        raise ValueError("world index outside frozen scope")
    seed = ((500000 + index if index < 120 else 700000 + index - 120)
            if mode == "main" else (900001 if mode == "smoke" else 910001) + index)
    split = ("train" if index < 72 else "validation" if index < 96 else
             "test" if index < 120 else "challenge") if mode == "main" else ("train" if index == 0 else "validation")
    rng = random.Random(seed)
    investor_count, event_count = 4 + index % 3, 24 + 4 * (index % 5)
    investors = [f"I{number:02}" for number in range(investor_count)]
    opening = {}
    for asset in ASSETS:
        positions = {investor: 10000 + rng.randrange(1001) for investor in investors}
        total = sum(positions.values())
        opening[asset] = {"investors": positions,
                          "custody": {"platform": total // 2, "external": total - total // 2}}
    events = []
    start = datetime.fromisoformat(OPENING.replace("Z", "+00:00"))
    for number in range(event_count):
        kind = ("deposit", "withdrawal", "transfer")[number % 3]
        sender, recipient = rng.sample(investors, 2)
        events.append({"ref": f"R{number:04}", "asset": tuple(ASSETS)[number % 2],
                       "kind": kind, "units": rng.randint(1, 50), "sequence": 1,
                       "at": (start + timedelta(seconds=30 * (number + 1))).isoformat(timespec="microseconds").replace("+00:00", "Z"),
                       "sender": None if kind == "deposit" else sender,
                       "recipient": None if kind == "withdrawal" else recipient,
                       "custody": None if kind == "transfer" else rng.choice(("platform", "external"))})
    world = {"world_id": f"{mode}-g{index:03}", "index": index, "seed": seed,
             "split": split, "assets": dict(ASSETS), "investors": investors,
             "opening_at": OPENING, "opening": opening, "events": events}
    integer_ledger(world)
    return world


def configuration(world):
    return {"platform": "P1", "custodian": "C1", "investors": world["investors"],
            "assets": world["assets"], "opening_at": OPENING}


def _record(kind, asset, source="P1", **fields):
    return {"kind": kind, "asset": asset, "source": source, "platform": "P1", **fields}


def _envelope(record, received):
    return {"record": record, "received_at": received}


def _reports(world, ledger, received, version=1, asset_only=None, streams=None):
    rows = []
    for asset in world["assets"]:
        if asset_only is not None and asset != asset_only:
            continue
        slots = [("investor", investor, amount, "P1") for investor, amount in ledger[asset]["investors"].items()]
        slots += [("platform_custody", "platform", ledger[asset]["custody"]["platform"], "P1"),
                  ("external_custody", "external", ledger[asset]["custody"]["external"], "C1")]
        for stream, scope, amount, source in slots:
            if streams is None or stream in streams:
                rows.append(_envelope(_record("report", asset, source, stream=stream, scope=scope,
                    balance_at=BALANCE, version=version, amount=text_amount(amount, world["assets"][asset])), received))
    return rows


def _base_rows(world, first_observation):
    rows = []
    for asset in world["assets"]:
        for scope, amount in [*world["opening"][asset]["investors"].items(),
                              *world["opening"][asset]["custody"].items()]:
            rows.append(_envelope(_record("opening", asset, scope=scope, balance_at=OPENING,
                amount=text_amount(amount, world["assets"][asset])), OPENING))
        rows.append(_envelope(_record("manifest", asset, stream="opening", coverage_from=OPENING,
            coverage_to=OPENING, expected_count=len(world["investors"]) + 2), first_observation))
    for event in world["events"]:
        rows.append(_envelope(_record("event", event["asset"], business_day=event["at"][:10],
            ref=event["ref"], occurred_at=event["at"], sequence=event["sequence"], type=event["kind"],
            from_investor=event["sender"], to_investor=event["recipient"], custody=event["custody"],
            amount=text_amount(event["units"], world["assets"][event["asset"]])), event["at"]))
    rows += _reports(world, integer_ledger(world), first_observation)
    for asset in world["assets"]:
        for stream, count, source in (("event", sum(event["asset"] == asset for event in world["events"]), "P1"),
                ("investor", len(world["investors"]), "P1"), ("platform_custody", 1, "P1"), ("external_custody", 1, "C1")):
            rows.append(_envelope(_record("manifest", asset, source, stream=stream,
                coverage_from=OPENING if stream == "event" else BALANCE,
                coverage_to=BALANCE, expected_count=count), first_observation))
    return rows


def make_episode(world, slot):
    if type(slot) is not int or slot not in range(4):
        raise ValueError("exactly four frozen episode slots")
    index = world["index"]
    # Twin histories use exactly the same random draws and wire prefix.
    variant_rng = random.Random(world["seed"] + 7919 * (0 if slot in (0, 1) else slot))
    asset = variant_rng.choice(tuple(world["assets"]))
    age = variant_rng.choice((3, 6, 12, 18))
    impact = variant_rng.randint(2, 37)
    first = at_hours(-age)
    future_hours = variant_rng.choice((2, 8, 16))
    targets = [event for event in world["events"] if event["asset"] == asset]
    target = variant_rng.choice(targets)
    investors = variant_rng.sample(world["investors"], 2)
    episode_id = "e" + hashlib.sha256((world["world_id"] + "/" + str(slot)).encode()).hexdigest()[:16]
    family = ("COMBINED_REOPEN" if world["split"] == "challenge" else
              "LATE_EVENT" if slot < 2 else
              ("LATE_MANIFEST", "REPORT_REVISION", "CORRECTION_DEPENDENCY", "CUSTODY_DIFFERENCE")[index % 4]
              if slot == 2 else ("CLEAN", "H_NOT_OBSERVED", "OBSERVABILITY_LIMIT", "CLEAN")[index % 4])
    unresolved = slot == 1 if slot < 2 else bool((index // 4) % 2)
    resolution = at_hours(30 if unresolved else future_hours)
    if family == "CORRECTION_DEPENDENCY":
        target = variant_rng.choice([event for event in targets if event["kind"] == "deposit"])
    plan = {"episode_id": episode_id, "world_id": world["world_id"], "split": world["split"],
            "slot": slot, "family": family, "asset": asset, "impact_units": impact,
            "target_ref": target["ref"], "investors": investors, "first_observation": first,
            "arrival_at": resolution, "revision_at": resolution, "available_until": HORIZON,
            "twin_group": world["world_id"] + "/pair" if slot < 2 else None,
            "intermediate_closure_at": None}
    if family == "COMBINED_REOPEN":
        plan.update(arrival_at=at_hours(30 if slot == 2 else 2), bad_report_at=at_hours(8),
                    revision_at=at_hours(30 if slot in (1, 2) else 16),
                    intermediate_closure_at=at_hours(4) if slot in (0, 1, 3) else None)
    elif family == "CORRECTION_DEPENDENCY":
        plan["revision_at"] = at_hours(31 if unresolved else future_hours + 1)
    elif family == "H_NOT_OBSERVED":
        plan.update(arrival_at=at_hours(30), available_until=at_hours(12))
    rows = _base_rows(world, first)
    full = integer_ledger(world)

    def event_row():
        return next(row for row in rows if row["record"].get("ref") == target["ref"])

    def report_row(stream, scope=None):
        return next(row for row in rows if row["record"]["kind"] == "report"
                    and row["record"]["asset"] == asset and row["record"]["stream"] == stream
                    and (scope is None or row["record"]["scope"] == scope))

    if family in ("LATE_EVENT", "CORRECTION_DEPENDENCY", "COMBINED_REOPEN"):
        event_row()["received_at"] = plan["arrival_at"]
    if family == "LATE_MANIFEST":
        row = next(row for row in rows if row["record"]["kind"] == "manifest"
                   and row["record"]["asset"] == asset and row["record"]["stream"] == "event")
        row["received_at"] = plan["arrival_at"]
    elif family == "REPORT_REVISION":
        for investor, sign in zip(investors, (1, -1)):
            report_row("investor", investor)["record"]["amount"] = text_amount(
                full[asset]["investors"][investor] + sign * impact, world["assets"][asset])
        rows += _reports(world, full, plan["revision_at"], 2, asset, ("investor",))
    elif family == "CUSTODY_DIFFERENCE":
        report_row("external_custody")["record"]["amount"] = text_amount(
            full[asset]["custody"]["external"] - impact, world["assets"][asset])
        rows += _reports(world, full, plan["revision_at"], 2, asset, ("external_custody",))
    elif family == "CORRECTION_DEPENDENCY":
        correction = _record("correction", asset, batch_id="B1", correction_id="C1",
            target={"kind": "event", "source": "P1", "platform": "P1", "business_day": target["at"][:10], "ref": target["ref"]},
            target_occurred_at=target["at"], mode="REPLACE", source_ref="S1", reason="Synthetic reporting amendment",
            replacement_amount=text_amount(target["units"] + impact, world["assets"][asset]))
        rows.append(_envelope(correction, first))
        rows.append(_envelope(_record("correction_manifest", asset, batch_id="B1",
            coverage_from=OPENING, coverage_to=BALANCE, expected_count=1), first))
        corrected = integer_ledger(world, replacement={target["ref"]: target["units"] + impact})
        rows += _reports(world, corrected, plan["revision_at"], 2, asset)
    elif family == "H_NOT_OBSERVED":
        report_row("external_custody")["received_at"] = plan["arrival_at"]
    elif family == "OBSERVABILITY_LIMIT":
        event_row()["record"]["ref"] = "Q" + target["ref"]
    elif family == "COMBINED_REOPEN":
        wrong = deepcopy(full)
        wrong[asset]["custody"]["external"] -= impact
        rows += _reports(world, wrong, plan["bad_report_at"], 2, asset, ("external_custody",))
        rows += _reports(world, full, plan["revision_at"], 3, asset, ("external_custody",))
    return plan, rows


def _check(budget):
    if budget is not None:
        budget.check()


def generate_bundle(output, mode="main", budget=None):
    """Create owned synthetic sources; truth never crosses into feature inputs."""
    if mode not in ("main", "smoke", "archive_smoke"):
        raise ValueError("unknown frozen generation mode")
    destination = preflight_output(output)
    _check(budget)
    from ..store import Store
    from ..engine import reconcile
    from .truth import expected_findings, verify_findings
    worlds, episodes, groups = {}, [], []
    truth_episodes = []
    with new_output_directory(destination) as root:
        (root / "episodes").mkdir()
        (root / "truth").mkdir()
        for index in range(144 if mode == "main" else 2):
            _check(budget)
            world = make_world(index, mode)
            worlds[world["world_id"]] = world
            group = {"world_id": world["world_id"], "split": world["split"], "episode_ids": []}
            for slot in range(4):
                _check(budget)
                plan, rows = make_episode(world, slot)
                episode_id = plan["episode_id"]
                folder = root / "episodes" / episode_id
                folder.mkdir()
                save(folder / "config.json", configuration(world))
                (folder / "input.jsonl").write_bytes(b"".join(encoded(row) for row in rows))
                store = Store(folder / "source.sqlite3", configuration(world))
                try:
                    for row in rows:
                        outcome = store.ingest(row["record"], row["received_at"])
                        if outcome["status"] not in ("ACCEPTED", "DUPLICATE"):
                            raise ValueError("synthetic fixture intake failed: " + repr(outcome))
                    results = [reconcile(store, BALANCE, cut) for cut in (plan["first_observation"], AS_OF)]
                    for result in results:
                        try:
                            verify_findings(result, expected_findings(world, plan, result["knowledge_at"]))
                        except ValueError as exc:
                            raise ValueError(f"TRIAGE_WORLD_CHECK: world={world['world_id']} episode={episode_id} slot={slot}: {exc}") from exc
                    if any(store.read_run(result["run_id"]) != result for result in results):
                        raise ValueError("immutable synthetic run readback differs")
                finally:
                    store.close()
                selection = {"format": "review-selection-v1", "sources": [{"alias": "source", "database": "source.sqlite3",
                    "run_ids": [result["run_id"] for result in results]}]}
                save(folder / "selection.json", selection)
                episodes.append({"episode_id": episode_id, "world_id": world["world_id"], "split": world["split"],
                    "balance_at": BALANCE, "as_of": AS_OF, "history_run_ids": [results[0]["run_id"]],
                    "current_run_id": results[1]["run_id"], "selection_file": f"episodes/{episode_id}/selection.json"})
                truth_episodes.append(plan)
                group["episode_ids"].append(episode_id)
                _check(budget)
            groups.append(group)
        split = {"format": "triage-split-v1", "groups": groups}
        public = {"format": "triage-episodes-v1", "experiment_contract": FORMAT, "design_id": DESIGN,
                  "mode": mode, "assets": dict(ASSETS), "balance_at": BALANCE, "as_of": AS_OF,
                  "horizon": HORIZON, "horizon_hours": 24, "episodes": episodes}
        truth_catalog = {"format": "triage-truth-catalog-v1", "design_id": DESIGN, "mode": mode,
                         "split_hash": digest(split), "files": {}}
        for split_name in ("train", "validation", "test", "challenge"):
            split_episodes = [plan for plan in truth_episodes if plan["split"] == split_name]
            split_worlds = {name: item for name, item in worlds.items() if item["split"] == split_name}
            split_truth = {"format": "triage-truth-plan-v1", "design_id": DESIGN, "mode": mode,
                           "split": split_name, "worlds": split_worlds, "episodes": split_episodes,
                           "split_hash": digest(split)}
            raw = encoded(split_truth)
            (root / "truth" / (split_name + ".json")).write_bytes(raw)
            truth_catalog["files"][split_name] = {"path": "truth/" + split_name + ".json",
                "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        save(root / "splits.json", split)
        save(root / "episodes.json", public)
        save(root / "truth/plan.json", truth_catalog)
        manifest = {"format": FORMAT, "design_id": DESIGN, "mode": mode,
                    "worlds": len(groups), "episodes": len(episodes), "visible_units": len(episodes) * 2,
                    "split_hash": digest(split), "files": {}}
        for path in sorted(root.rglob("*")):
            if path.is_file():
                data = path.read_bytes()
                manifest["files"][path.relative_to(root).as_posix()] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        save(root / "bundle.json", manifest)
        _check(budget)
    return manifest
