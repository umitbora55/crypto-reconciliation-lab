"""Resolve immutable correction deliveries, then derive atomic signed effects."""
from collections import defaultdict
from decimal import Decimal
from .correction_model import event_key
from .migrations import inject
from .model import canonical, digest
from .quarantine import known_asset, parsed_time


def problem(state, code, **detail):
    return {"state": state, "code": code, **detail}


def signed_effect(event, amount):
    changes = {}
    if event["from_investor"]:
        changes[event["from_investor"]] = canonical(-amount)
    if event["to_investor"]:
        changes[event["to_investor"]] = canonical(amount)
    custody_delta = Decimal(0)
    if event["custody"]:
        custody_delta = amount if event["type"] == "deposit" else -amount
    return {"investor_deltas": changes, "custody_location": event["custody"], "custody_delta": canonical(custody_delta)}


def derive_group(snap, correction, target, manifests, fault=None):
    original = Decimal(target["amount"])
    effective = Decimal(correction["replacement_amount"]) if correction["mode"] == "REPLACE" else Decimal(0)
    reversal = {"role": "reversal", **signed_effect(target, -original)}
    inject(fault, "derive_after_reversal")
    effects = [reversal]
    if correction["mode"] == "REPLACE":
        effects.append({"role": "replacement", **signed_effect(target, effective)})
    first_known = snap.store.db.execute("SELECT MIN(received_at) FROM receipts WHERE record_id=? AND received_at<=?",
                                        (correction["id"], snap.knowledge_at)).fetchone()[0]
    body = {"correction_record_id": correction["id"], "target_record_id": target["id"],
            "target_key": correction["target"], "occurred_at": target["occurred_at"], "mode": correction["mode"],
            "original_amount": target["amount"], "effective_amount": canonical(effective),
            "original_effect": signed_effect(target, original), "effects": effects,
            "net_effect": signed_effect(target, effective), "manifest_ids": sorted(manifests),
            "first_known_at": first_known}
    return {"id": digest(body), **body}


def known_targets(snap, raw):
    """Resolve only well-typed identities against this knowledge-bounded snapshot."""
    target = raw.get("target")
    fields = ("kind", "source", "platform", "business_day", "ref")
    if (not isinstance(target, dict)
            or any(not isinstance(target.get(field), str) for field in fields)
            or target["kind"] != "event"):
        return []
    return snap.groups.get(event_key(target), [])


def correction_relevant(snap, raw):
    targets = known_targets(snap, raw)
    if targets:
        # A sender's assertion cannot hide a visible original. Conflicting variants
        # conservatively include the batch if any known original is in the cut.
        return any(r["occurred_at"] <= snap.balance_at for r in targets)
    asserted = parsed_time(raw, "target_occurred_at")
    return asserted is None or asserted <= snap.balance_at


def batch_hint(raw):
    value = raw.get("batch_id")
    return value if isinstance(value, str) else "<unknown>"


def resolve_corrections(snap, asset, ledger_complete, fault=None):
    """No mutation of input events. A group is usable only with a complete batch."""
    records = [r for r in snap.records if r["kind"] == "correction"]
    by_target = defaultdict(set)
    for r in records:
        by_target[event_key(r["target"])].add(r["key"])
    local = [r for r in records if r["asset"] == asset]
    manifests = [r for r in snap.records if r["kind"] == "correction_manifest" and r["asset"] == asset]
    batches = {r["batch_id"] for r in local if correction_relevant(snap, r)}
    batches |= {r["batch_id"] for r in manifests if r["coverage_from"] < snap.balance_at}
    bad_by_batch = defaultdict(list)
    refs, issues, deliveries, applied = [], [], [], {}
    candidates = []
    for bad in snap.invalid:
        raw = bad["record"]
        if not isinstance(raw, dict) or raw.get("kind") not in ("correction", "correction_manifest"):
            continue
        hinted_asset = known_asset(raw, snap.config)
        if hinted_asset is not None and hinted_asset != asset:
            continue
        candidates.append(bad)
    # Select correction dependencies first so a manifest's false future coverage
    # cannot hide a batch, regardless of receipt hash or physical arrival order.
    batches |= {batch_hint(b["record"]) for b in candidates
                if b["record"]["kind"] == "correction" and correction_relevant(snap, b["record"])}
    for bad in candidates:
        raw = bad["record"]
        batch = batch_hint(raw)
        if raw["kind"] == "correction":
            if not correction_relevant(snap, raw):
                continue
            refs += snap.remember(known_targets(snap, raw))
        else:
            start = parsed_time(raw, "coverage_from")
            end = parsed_time(raw, "coverage_to")
            if (batch not in batches and start is not None and end is not None
                    and start < end and start >= snap.balance_at):
                continue
        batches.add(batch)
        snap.evidence[bad["id"]] = {"quarantined_receipt": bad}
        refs.append(bad["id"])
        code = bad["error"].split(":", 1)[0] if ":" in bad["error"] else "INVALID_CORRECTION"
        bad_by_batch[batch].append(problem("INCOMPLETE", code, evidence_ids=[bad["id"]], detail=bad["error"]))

    for batch_id in sorted(batches):
        rows = sorted([r for r in local if r["batch_id"] == batch_id], key=lambda r: r["id"])
        declarations = [m for m in manifests if m["batch_id"] == batch_id]
        batch_refs = snap.remember(rows + declarations)
        refs += batch_refs
        batch_issues = list(bad_by_batch[batch_id])
        if batch_id != "<unknown>":
            batch_issues += bad_by_batch["<unknown>"]
        if not declarations:
            batch_issues.append(problem("INCOMPLETE", "CORRECTION_MANIFEST_ABSENT", batch_id=batch_id))
        elif len(declarations) > 1:
            batch_issues.append(problem("CONFLICT", "CORRECTION_MANIFEST_CONFLICT", evidence_ids=snap.remember(declarations)))
        valid = []
        for correction in rows:
            errors = []
            key = event_key(correction["target"])
            variants = snap.groups[correction["key"]]
            target_rows = snap.groups.get(key, [])
            refs += snap.remember(variants + target_rows)
            if len(variants) > 1:
                errors.append(problem("CONFLICT", "CORRECTION_ID_CONFLICT", evidence_ids=snap.remember(variants)))
            if len(by_target[key]) > 1:
                rivals = [r for r in records if event_key(r["target"]) == key]
                refs += snap.remember(rivals)
                errors.append(problem("CONFLICT", "MULTIPLE_TARGET_CORRECTIONS", evidence_ids=snap.remember(rivals)))
            invalid_targets = []
            for bad in snap.invalid:
                raw = bad["record"]
                if isinstance(raw, dict) and raw.get("kind") == "event":
                    try:
                        if event_key(raw) == key:
                            invalid_targets.append(bad)
                    except (KeyError, TypeError):
                        pass
            if invalid_targets:
                for bad in invalid_targets:
                    snap.evidence[bad["id"]] = {"quarantined_receipt": bad}
                refs += [b["id"] for b in invalid_targets]
                errors.append(problem("INCOMPLETE", "INVALID_TARGET", evidence_ids=[b["id"] for b in invalid_targets]))
            elif not target_rows:
                errors.append(problem("INCOMPLETE", "TARGET_PENDING", target=correction["target"]))
            elif len(target_rows) > 1:
                errors.append(problem("CONFLICT", "TARGET_EVENT_CONFLICT", evidence_ids=snap.remember(target_rows)))
            target = target_rows[0] if len(target_rows) == 1 else None
            if target:
                if target["asset"] != asset:
                    errors.append(problem("CONFLICT", "TARGET_ASSET_MISMATCH", evidence_ids=[target["id"]]))
                if target["occurred_at"] != correction["target_occurred_at"]:
                    errors.append(problem("CONFLICT", "TARGET_TIME_MISMATCH", evidence_ids=[target["id"]]))
                if target["occurred_at"] <= snap.config["opening_at"]:
                    errors.append(problem("INCOMPLETE", "UNSUPPORTED_OPENING_HORIZON"))
            if len(declarations) == 1:
                m = declarations[0]
                if not m["coverage_from"] < correction["target_occurred_at"] <= m["coverage_to"]:
                    errors.append(problem("CONFLICT", "TARGET_OUTSIDE_CORRECTION_COVERAGE"))
            if errors:
                batch_issues += [{**e, "correction_id": correction["correction_id"]} for e in errors]
            elif target:
                valid.append((correction, target))
        observed = len(valid)
        if len(declarations) == 1 and observed != declarations[0]["expected_count"]:
            expected = declarations[0]["expected_count"]
            batch_issues.append(problem("CONFLICT" if observed > expected else "INCOMPLETE", "CORRECTION_MANIFEST_COUNT",
                                        expected_count=expected, observed_unique_valid_count=observed, evidence_ids=snap.remember(declarations)))
        complete = not batch_issues
        applied_ids = []
        if complete and ledger_complete:
            for correction, target in valid:
                if target["occurred_at"] <= snap.balance_at:
                    group = derive_group(snap, correction, target, [m["id"] for m in declarations], fault)
                    applied[target["id"]] = group
                    snap.evidence[group["id"]] = {"derived_correction_group": group}
                    refs.append(group["id"])
                    applied_ids.append(correction["id"])
        deliveries.append({"batch_id": batch_id, "manifest_ids": sorted(m["id"] for m in declarations),
                           "expected_count": declarations[0]["expected_count"] if len(declarations) == 1 else None,
                           "observed_unique_valid_count": observed, "complete": complete,
                           "applied_correction_ids": sorted(applied_ids), "issues": batch_issues})
        issues += batch_issues
    return applied, issues, sorted(set(refs)), deliveries
