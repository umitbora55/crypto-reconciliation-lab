"""Knowledge-bounded reconciliation. No scenario names or expected outcomes enter here."""
from collections import defaultdict
import json
from decimal import Decimal, localcontext
from .corrections import resolve_corrections
from .model import CONTEXT, RULE_VERSION, canonical, timestamp
from .quarantine import relevant

PRIORITY = {"COMPLETE": 0, "STALE": 1, "INCOMPLETE": 2, "CONFLICT": 3}


def state(issues):
    return max((x["state"] for x in issues), key=PRIORITY.get, default="COMPLETE")


def issue(level, code, **detail):
    return {"state": level, "code": code, **detail}


class Snapshot:
    def __init__(self, store, balance_at, knowledge_at):
        self.store, self.config = store, store.config
        self.balance_at, self.knowledge_at = balance_at, knowledge_at
        self.records, self.receipts, self.invalid = store.known(knowledge_at)
        self.groups = defaultdict(list)
        for r in self.records:
            self.groups[r["key"]].append(r)
        self.evidence = {}

    def remember(self, records):
        ids = []
        for r in records:
            rid = r["id"]
            receipt_ids = sorted(self.receipts[rid])
            self.evidence[rid] = {"record": {k: v for k, v in r.items() if k not in ("id", "key")}, "logical_key": r["key"], "receipt_ids": receipt_ids}
            for receipt_id in receipt_ids:
                row = self.store.db.execute("SELECT raw FROM receipts WHERE receipt_hash=? LIMIT 1", (receipt_id,)).fetchone()
                self.evidence[receipt_id] = {"receipt": json.loads(row[0])}
            ids.append(rid)
        return sorted(set(ids))

    def taints(self, asset, stream, scope=None):
        issues = []
        for bad in self.invalid:
            r = bad["record"] if isinstance(bad["record"], dict) else {}
            if r.get("kind") in ("correction", "correction_manifest"):
                continue  # Separate correction deliveries have their own scope and time rules.
            if not relevant(r, self.config, asset, stream, self.balance_at, scope):
                continue
            self.evidence[bad["id"]] = {"quarantined_receipt": bad}
            issues.append(issue("INCOMPLETE", "QUARANTINED_INPUT", evidence_ids=[bad["id"]], detail=bad["error"]))
        return issues

    def manifest(self, asset, stream, actual, has_stale=False):
        start = self.config["opening_at"] if stream in ("opening", "event") else self.balance_at
        end = self.config["opening_at"] if stream == "opening" else self.balance_at
        candidates = [r for r in self.records if r["kind"] == "manifest" and r["asset"] == asset and r["stream"] == stream
                      and r["coverage_from"] == start and r["coverage_to"] == end]
        refs = self.remember(candidates)
        if not candidates:
            return [issue("INCOMPLETE", "MANIFEST_ABSENT", stream=stream, detail="Completeness unknown; no missing-event count inferred")], refs
        if len(candidates) > 1:
            return [issue("CONFLICT", "MANIFEST_CONFLICT", stream=stream, evidence_ids=refs)], refs
        expected = candidates[0]["expected_count"]
        if actual != expected:
            level = "CONFLICT" if actual > expected else ("STALE" if has_stale else "INCOMPLETE")
            return [issue(level, "MANIFEST_COUNT", stream=stream, expected_count=expected, observed_unique_valid_count=actual, evidence_ids=refs)], refs
        return [], refs

    def openings(self, asset):
        selected, issues, refs = {}, self.taints(asset, "opening"), []
        for scope in [*self.config["investors"], "platform", "external"]:
            rows = [r for r in self.records if r["kind"] == "opening" and r["asset"] == asset and r["scope"] == scope]
            refs += self.remember(rows)
            if len(rows) == 1:
                selected[scope] = rows[0]
            else:
                issues.append(issue("CONFLICT" if rows else "INCOMPLETE", "OPENING_CONFLICT" if rows else "OPENING_ABSENT", scope=scope))
        checks, ids = self.manifest(asset, "opening", len(selected))
        return selected, issues + checks, sorted(set(refs + ids))

    def events(self, asset):
        selected, issues, refs = [], self.taints(asset, "event"), []
        for key in sorted(self.groups):
            rows = self.groups[key]
            if not any(r["kind"] == "event" and r["asset"] == asset and self.config["opening_at"] < r["occurred_at"] <= self.balance_at for r in rows):
                continue
            refs += self.remember(rows)
            if len(rows) > 1:
                issues.append(issue("CONFLICT", "EVENT_ID_CONFLICT", evidence_ids=sorted(r["id"] for r in rows)))
            else:
                selected.append(rows[0])
        checks, ids = self.manifest(asset, "event", len(selected))
        selected.sort(key=lambda r: (r["occurred_at"], r["sequence"], r["source"], r["business_day"], r["ref"]))
        return selected, issues + checks, sorted(set(refs + ids))

    def reports(self, asset, stream, scopes):
        selected, issues, refs = {}, self.taints(asset, stream), []
        stale = False
        for scope in scopes:
            rows = [r for r in self.records if r["kind"] == "report" and r["asset"] == asset and r["stream"] == stream
                    and r["scope"] == scope and r["balance_at"] <= self.balance_at]
            exact = [r for r in rows if r["balance_at"] == self.balance_at]
            if not exact:
                old = [r for r in rows if r["balance_at"] < self.balance_at]
                old_refs = self.remember(old)
                refs += old_refs
                stale = stale or bool(old)
                issues.append(issue("STALE" if old else "INCOMPLETE", "REPORT_STALE" if old else "REPORT_ABSENT", scope=scope, evidence_ids=old_refs))
                continue
            version = max(r["version"] for r in exact)
            latest = [r for r in exact if r["version"] == version]
            latest_refs = self.remember(latest)
            refs += latest_refs
            if len(latest) > 1:
                issues.append(issue("CONFLICT", "REPORT_VERSION_CONFLICT", scope=scope, evidence_ids=latest_refs))
            else:
                selected[scope] = latest[0]
        checks, ids = self.manifest(asset, stream, len(selected), stale)
        return selected, issues + checks, sorted(set(refs + ids))


def reconcile(store, balance_at, knowledge_at, *, fault=None):
    balance_at, knowledge_at = timestamp(balance_at), timestamp(knowledge_at)
    if balance_at < store.config["opening_at"]:
        raise ValueError("balance_at precedes opening snapshot")
    snap = Snapshot(store, balance_at, knowledge_at)
    findings, ledgers = [], {}
    with localcontext(CONTEXT):
        for asset in sorted(store.config["assets"]):
            opening, opening_issues, opening_refs = snap.openings(asset)
            events, event_issues, event_refs = snap.events(asset)
            ledger_issues = opening_issues + event_issues
            groups, correction_issues, correction_refs, deliveries = resolve_corrections(
                snap, asset, state(ledger_issues) == "COMPLETE", fault)
            ledger_issues += correction_issues
            balances = {i: Decimal(opening[i]["amount"]) if i in opening else None for i in store.config["investors"]}
            custody = {i: Decimal(opening[i]["amount"]) if i in opening else None for i in ("platform", "external")}
            trace, negatives = [], []
            for event in events:
                group = groups.get(event["id"])
                quantity = Decimal(group["effective_amount"] if group else event["amount"])
                changes = {}
                if event["from_investor"]:
                    changes[event["from_investor"]] = -quantity
                if event["to_investor"]:
                    changes[event["to_investor"]] = quantity
                for investor, delta in changes.items():
                    if balances[investor] is not None:
                        balances[investor] += delta
                        if balances[investor] < 0:
                            negatives.append({"event_id": event["id"], "investor": investor, "balance": canonical(balances[investor])})
                custody_delta = Decimal(0)
                if event["custody"]:
                    custody_delta = quantity if event["type"] == "deposit" else -quantity
                    if custody[event["custody"]] is not None:
                        custody[event["custody"]] += custody_delta
                trace.append({"event_id": event["id"], "occurred_at": event["occurred_at"], "sequence": event["sequence"],
                              "investor_deltas": {k: canonical(v) for k, v in changes.items()}, "custody_location": event["custody"],
                              "custody_delta": canonical(custody_delta), "correction_group_id": group["id"] if group else None, "balances_after": {k: canonical(v) if v is not None else None for k, v in balances.items()}})
            if negatives and state(ledger_issues) == "COMPLETE":
                ledger_issues.append(issue("CONFLICT", "NEGATIVE_ECONOMIC_BALANCE", observations=negatives))
            elif negatives:
                ledger_issues.append(issue("INCOMPLETE", "PROVISIONAL_NEGATIVE_BALANCE", observations=negatives))
            liability = sum(balances.values(), Decimal(0)) if all(v is not None for v in balances.values()) else None
            ledgers[asset] = {"opening_record_ids": sorted(r["id"] for r in opening.values()), "opening_amounts": {k: r["amount"] for k, r in opening.items()},
                              "event_ids": [r["id"] for r in events], "trace": trace,
                              "investor_balances": {k: canonical(v) if v is not None else None for k, v in balances.items()},
                              "liability": canonical(liability) if liability is not None else None,
                              "custody_rollforward": {k: canonical(v) if v is not None else None for k, v in custody.items()},
                              "data_state": state(ledger_issues), "issues": ledger_issues,
                              "correction_groups": sorted(groups.values(), key=lambda g: g["id"]), "correction_deliveries": deliveries}

            def finding(comparison, scope, expected, reported, issues, refs, components):
                data_state = state(issues)
                difference = expected - reported if expected is not None and reported is not None else None
                outcome = "NOT_EVALUATED" if data_state != "COMPLETE" else ("MATCHED" if difference == 0 else "MISMATCH")
                findings.append({"comparison": comparison, "platform": store.config["platform"], "scope": scope, "asset": asset,
                                 "expected": canonical(expected) if expected is not None else None,
                                 "reported": canonical(reported) if reported is not None else None,
                                 "difference": canonical(difference) if difference is not None else None,
                                 "difference_direction": "expected_minus_reported", "provisional": data_state != "COMPLETE",
                                 "data_state": data_state, "reconciliation_state": outcome, "issues": issues,
                                 "balance_at": balance_at, "knowledge_at": knowledge_at, "rule_version": RULE_VERSION,
                                 "event_ids": [r["id"] for r in events], "report_ids": sorted(r["id"] for r in components),
                                 "correction_ids": sorted(g["correction_record_id"] for g in groups.values()),
                                 "evidence_ids": sorted(set(opening_refs + event_refs + correction_refs + refs + [eid for x in issues for eid in x.get("evidence_ids", [])]))})

            reports, report_issues, report_refs = snap.reports(asset, "investor", store.config["investors"])
            for investor in store.config["investors"]:
                report = reports.get(investor)
                finding("A", investor, balances[investor], Decimal(report["amount"]) if report else None,
                        ledger_issues + report_issues, report_refs, [report] if report else [])
            platform, p_issues, p_refs = snap.reports(asset, "platform_custody", ["platform"])
            external, e_issues, e_refs = snap.reports(asset, "external_custody", ["external"])
            components = list(platform.values()) + list(external.values())
            reported = sum((Decimal(r["amount"]) for r in components), Decimal(0)) if len(components) == 2 else None
            finding("B", "customer_liability", liability, reported, ledger_issues + p_issues + e_issues, p_refs + e_refs, components)
    result = {"rule_version": RULE_VERSION, "configuration": store.config, "balance_at": balance_at, "knowledge_at": knowledge_at,
              "ledgers": ledgers, "findings": findings, "evidence": dict(sorted(snap.evidence.items()))}
    return store.save_run(result, fault=fault)
