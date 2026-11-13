"""Hand-verifiable fixtures and an independent demo oracle, outside the engine."""
import json
from pathlib import Path
from .engine import reconcile
from .model import dumps, timestamp
from .reporting import write_report
from .store import Store

BALANCE_AT = "2026-11-10T23:59:59Z"
KNOWLEDGE_AT = "2026-11-11T01:00:00Z"
LATER_KNOWLEDGE_AT = "2026-11-11T03:00:00Z"
SCENARIOS = ("clean", "late_event", "custody_difference", "corrected_report")
# Literals from the user contract, never derived from reconcile().
REFERENCE = {
    "ASSET_A": {"I1": "7", "I2": "4", "liability": "11", "platform": "2", "external": "9"},
    "ASSET_B": {"I1": "0.3", "I2": "0.2", "liability": "0.5", "platform": "0.05", "external": "0.45"},
}


def fixtures(scenario="clean", balance_at=BALANCE_AT, knowledge_at=KNOWLEDGE_AT, later_at=LATER_KNOWLEDGE_AT):
    if scenario not in SCENARIOS:
        raise ValueError("unknown scenario")
    balance_at, knowledge_at, later_at = map(timestamp, (balance_at, knowledge_at, later_at))
    opening_at = timestamp(balance_at[:10] + "T00:00:00Z")
    if not opening_at[:10] + "T03:00:00.000000Z" < balance_at <= knowledge_at < later_at:
        raise ValueError("demo requires same-day cutoff after 03:00 UTC and balance_at <= knowledge_at < later_at")
    config = {"platform": "P1", "custodian": "C1", "investors": ["I1", "I2"], "assets": {"ASSET_A": 8, "ASSET_B": 2}, "opening_at": opening_at}
    initial, later = [], []

    def envelope(record, received=knowledge_at):
        return {"record": record, "received_at": received}

    def base(kind, asset, source="P1"):
        return {"kind": kind, "asset": asset, "source": source, "platform": "P1"}

    openings = {"ASSET_A": {"I1": "6", "I2": "4", "platform": "2", "external": "8"},
                "ASSET_B": {"I1": "0.10", "I2": "0.20", "platform": "0.05", "external": "0.25"}}
    for asset, scopes in openings.items():
        for scope, amount in scopes.items():
            initial.append(envelope({**base("opening", asset), "scope": scope, "balance_at": opening_at, "amount": amount}, opening_at))
    specs = [
        ("ASSET_A", "A1", "transfer", "I1", "I2", None, "1", 1),
        ("ASSET_A", "A2", "deposit", None, "I1", "external", "2", 2),
        ("ASSET_A", "A3", "withdrawal", "I2", None, "external", "1", 3),
        ("ASSET_B", "B1", "deposit", None, "I1", "external", "0.20", 2),
    ]
    for asset, ref, kind, sender, recipient, custody, amount, hour in specs:
        occurred = timestamp(f"{balance_at[:10]}T{hour:02d}:00:00Z")
        record = {**base("event", asset), "business_day": balance_at[:10], "ref": ref, "occurred_at": occurred, "sequence": 1,
                  "type": kind, "from_investor": sender, "to_investor": recipient, "custody": custody, "amount": amount}
        target = later if scenario == "late_event" and ref == "A3" else initial
        target.append(envelope(record, later_at if target is later else occurred))
    for asset in config["assets"]:
        for stream, scope, value in [("investor", "I1", REFERENCE[asset]["I1"]), ("investor", "I2", REFERENCE[asset]["I2"]),
                                    ("platform_custody", "platform", REFERENCE[asset]["platform"]), ("external_custody", "external", REFERENCE[asset]["external"])]:
            wrong = asset == "ASSET_A" and stream == "external_custody" and scenario in ("custody_difference", "corrected_report")
            r = {**base("report", asset, "C1" if stream == "external_custody" else "P1"), "stream": stream, "scope": scope,
                 "balance_at": balance_at, "version": 1, "amount": "8" if wrong else value}
            initial.append(envelope(r))
            if wrong and scenario == "corrected_report":
                later.append(envelope({**r, "version": 2, "amount": "9"}, later_at))
        for stream, count in [("opening", 4), ("event", 3 if asset == "ASSET_A" else 1), ("investor", 2), ("platform_custody", 1), ("external_custody", 1)]:
            initial.append(envelope({**base("manifest", asset, "C1" if stream == "external_custody" else "P1"), "stream": stream,
                                     "coverage_from": opening_at if stream in ("opening", "event") else balance_at,
                                     "coverage_to": opening_at if stream == "opening" else balance_at, "expected_count": count}))
    return config, initial, later


def expected_rows(scenario, phase):
    expected = []
    for asset in ("ASSET_A", "ASSET_B"):
        for comparison, scope in [("A", "I1"), ("A", "I2"), ("B", "customer_liability")]:
            data, outcome, difference = "COMPLETE", "MATCHED", "0"
            if asset == "ASSET_A" and scenario == "late_event" and phase == "initial":
                data, outcome = "INCOMPLETE", "NOT_EVALUATED"
                difference = "0" if scope == "I1" else "1"
            if asset == "ASSET_A" and comparison == "B" and (scenario == "custody_difference" or scenario == "corrected_report" and phase == "initial"):
                outcome, difference = "MISMATCH", "1"
            expected.append({"asset": asset, "comparison": comparison, "scope": scope, "data_state": data, "reconciliation_state": outcome, "difference": difference})
    return expected


def actual_rows(result):
    fields = ("asset", "comparison", "scope", "data_state", "reconciliation_state", "difference")
    return [{k: row[k] for k in fields} for row in result["findings"]]


def run_demos(output, balance_at=BALANCE_AT, knowledge_at=KNOWLEDGE_AT, later_at=LATER_KNOWLEDGE_AT):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    summary = []
    for scenario in SCENARIOS:
        folder = root / scenario
        folder.mkdir(exist_ok=True)
        config, initial, later = fixtures(scenario, balance_at, knowledge_at, later_at)
        (folder / "config.json").write_text(json.dumps(config, indent=2) + "\n")
        (folder / "input.jsonl").write_text("".join(dumps(item) + "\n" for item in initial + later))
        store = Store(folder / "evidence.sqlite3", config)
        try:
            for envelope in initial:
                response = store.ingest(envelope["record"], envelope["received_at"])
                if response["status"] in ("INVALID", "CONFLICT"):
                    raise ValueError(f"unexpected demo ingestion failure: {response}")
            before = reconcile(store, balance_at, knowledge_at)
            stages = [("initial", before)]
            if later:
                for envelope in later:
                    store.ingest(envelope["record"], envelope["received_at"])
                after = reconcile(store, balance_at, later_at)
                if store.read_run(before["run_id"]) != before or reconcile(store, balance_at, knowledge_at) != before:
                    raise ValueError("historical evaluation changed")
                stages.append(("later", after))
            for phase, result in stages:
                expected = expected_rows(scenario, phase)
                actual = actual_rows(result)
                verified = expected == actual
                # Check the final hand-calculated ledger independently of reported balances.
                if phase == "later" or scenario != "late_event":
                    for asset, ref in REFERENCE.items():
                        ledger = result["ledgers"][asset]
                        verified = verified and ledger["investor_balances"] == {"I1": ref["I1"], "I2": ref["I2"]} and ledger["liability"] == ref["liability"]
                        verified = verified and ledger["custody_rollforward"] == {"platform": ref["platform"], "external": ref["external"]}
                report = {"scenario": scenario, "phase": phase, "expected": expected, "actual": actual, "verified": verified, "result": result}
                write_report(folder / phase, report)
                summary.append({"scenario": scenario, "phase": phase, "verified": verified, "run_id": result["run_id"], "expected": expected, "actual": actual})
        finally:
            store.close()
    (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    lines = ["# Demo verification", "", "All values are synthetic. Expected results are literal reference values.", "", "| Scenario | Phase | Expected = actual | Run |", "|---|---|---|---|"]
    lines += [f"| {r['scenario']} | {r['phase']} | {r['verified']} | `{r['run_id']}` |" for r in summary]
    lines += ["", "See each scenario's initial.md / later.md for expected/actual findings, roll-forwards and evidence."]
    (root / "summary.md").write_text("\n".join(lines) + "\n")
    return summary
