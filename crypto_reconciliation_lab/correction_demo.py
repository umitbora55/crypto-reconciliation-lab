"""Stage 2 fixtures and independent literal oracles, kept outside the engine."""
import copy
import json
from pathlib import Path
from .demo import BALANCE_AT, KNOWLEDGE_AT, fixtures
from .engine import reconcile
from .model import dumps
from .reporting import write_report
from .store import Store

T1 = "2026-11-11T03:00:00Z"
T2 = "2026-11-11T04:00:00Z"
T3 = "2026-11-11T05:00:00Z"
SCENARIOS = ("deposit_amount_correction", "void_deposit", "void_internal_transfer", "correction_before_target", "duplicate_and_conflicting_corrections")


def correction(ref="A2", mode="REPLACE", replacement="3", correction_id="COR1", batch_id="BATCH1"):
    _, rows, _ = fixtures()
    event = next(r["record"] for r in rows if r["record"].get("ref") == ref)
    raw = {"kind": "correction", "source": "P1", "platform": "P1", "asset": "ASSET_A", "batch_id": batch_id,
           "correction_id": correction_id, "target": {k: event[k] for k in ("kind", "source", "platform", "business_day", "ref")},
           "target_occurred_at": event["occurred_at"], "mode": mode,
           "source_ref": "REVIEW-" + correction_id, "reason": "Synthetic historical reporting error"}
    if mode == "REPLACE":
        raw["replacement_amount"] = replacement
    return raw


def correction_manifest(batch_id="BATCH1", count=1):
    config, _, _ = fixtures()
    return {"kind": "correction_manifest", "source": "P1", "platform": "P1", "asset": "ASSET_A", "batch_id": batch_id,
            "coverage_from": config["opening_at"], "coverage_to": BALANCE_AT, "expected_count": count}


def envelope(record, time):
    return {"record": record, "received_at": time}


def revision(rows, stream, scope, amount, time):
    raw = next(r["record"] for r in rows if r["record"]["kind"] == "report" and r["record"]["asset"] == "ASSET_A" and r["record"]["stream"] == stream and r["record"]["scope"] == scope)
    return envelope({**raw, "version": 2, "amount": amount}, time)


def expected(i1, i2, liability, external, differences, data_state="COMPLETE"):
    # Every quantity/difference passed here is a literal independent reference.
    return {"ASSET_A": {"investors": {"I1": i1, "I2": i2}, "liability": liability,
                         "custody": {"platform": "2", "external": external}, "differences": list(differences), "data_state": data_state},
            "ASSET_B": {"investors": {"I1": "0.3", "I2": "0.2"}, "liability": "0.5",
                         "custody": {"platform": "0.05", "external": "0.45"}, "differences": ["0", "0", "0"], "data_state": "COMPLETE"}}


def correction_fixtures(scenario):
    if scenario not in SCENARIOS:
        raise ValueError("unknown correction demo")
    config, initial, _ = fixtures()
    clean = expected("7", "4", "11", "9", ("0", "0", "0"))
    phases = [("original", KNOWLEDGE_AT, clean)]
    added = []
    if scenario == "void_internal_transfer":
        added = [envelope(correction("A1", "VOID"), T1), envelope(correction_manifest(), T1),
                 revision(initial, "investor", "I1", "8", T2), revision(initial, "investor", "I2", "3", T2)]
        phases += [("corrected_old_reports", T1, expected("8", "3", "11", "9", ("1", "-1", "0"))),
                   ("investor_reports_updated", T2, expected("8", "3", "11", "9", ("0", "0", "0")))]
    elif scenario == "void_deposit":
        added = [envelope(correction(mode="VOID"), T1), envelope(correction_manifest(), T1),
                 revision(initial, "investor", "I1", "5", T2), revision(initial, "external_custody", "external", "7", T3)]
        phases += [("corrected_old_reports", T1, expected("5", "4", "9", "7", ("-2", "0", "-2"))),
                   ("investor_report_updated", T2, expected("5", "4", "9", "7", ("0", "0", "-2"))),
                   ("custody_report_updated", T3, expected("5", "4", "9", "7", ("0", "0", "0")))]
    elif scenario == "deposit_amount_correction":
        added = [envelope(correction(), T1), envelope(correction_manifest(), T1),
                 revision(initial, "investor", "I1", "8", T2), revision(initial, "external_custody", "external", "10", T3)]
        phases += [("corrected_old_reports", T1, expected("8", "4", "12", "10", ("1", "0", "1"))),
                   ("investor_report_updated", T2, expected("8", "4", "12", "10", ("0", "0", "1"))),
                   ("custody_report_updated", T3, expected("8", "4", "12", "10", ("0", "0", "0")))]
    elif scenario == "correction_before_target":
        target = next(r for r in initial if r["record"].get("ref") == "A2")
        initial.remove(target)
        added = [envelope(correction(), T1), envelope(correction_manifest(), T1), envelope(target["record"], T2),
                 revision(initial, "investor", "I1", "8", T3), revision(initial, "external_custody", "external", "10", T3)]
        phases = [("target_pending", T1, expected("5", "4", "9", "7", ("-2", "0", "-2"), "INCOMPLETE")),
                  ("target_received_old_reports", T2, expected("8", "4", "12", "10", ("1", "0", "1"))),
                  ("independent_reports_updated", T3, expected("8", "4", "12", "10", ("0", "0", "0")))]
    else:
        raw = correction()
        added = [envelope(raw, T1), envelope(correction_manifest(), T1), envelope(copy.deepcopy(raw), T2),
                 envelope(correction(replacement="4", correction_id="COR2", batch_id="BATCH2"), T3), envelope(correction_manifest("BATCH2"), T3)]
        phases += [("single_correction", T1, expected("8", "4", "12", "10", ("1", "0", "1"))),
                   ("duplicate_correction", T2, expected("8", "4", "12", "10", ("1", "0", "1"))),
                   ("conflicting_corrections", T3, expected("7", "4", "11", "9", ("0", "0", "0"), "CONFLICT"))]
    return config, initial + added, phases


def financial_projection(result):
    return {"ledgers": {asset: {key: value for key, value in ledger.items() if key in ("investor_balances", "liability", "custody_rollforward", "data_state")}
                        for asset, ledger in result["ledgers"].items()},
            "findings": [{k: f[k] for k in ("asset", "comparison", "scope", "expected", "reported", "difference", "data_state", "reconciliation_state")} for f in result["findings"]]}


def expected_findings(oracle):
    rows = []
    for asset in ("ASSET_A", "ASSET_B"):
        spec = oracle[asset]
        for (comparison, scope), difference in zip((("A", "I1"), ("A", "I2"), ("B", "customer_liability")), spec["differences"]):
            outcome = "NOT_EVALUATED" if spec["data_state"] != "COMPLETE" else ("MATCHED" if difference == "0" else "MISMATCH")
            rows.append(dict(asset=asset, comparison=comparison, scope=scope, data_state=spec["data_state"], reconciliation_state=outcome, difference=difference))
    return rows


def run_correction_demos(output):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    summary = []
    for scenario in SCENARIOS:
        folder = root / scenario
        folder.mkdir(exist_ok=True)
        config, rows, phases = correction_fixtures(scenario)
        (folder / "config.json").write_text(json.dumps(config, indent=2) + "\n")
        (folder / "input.jsonl").write_text("".join(dumps(r) + "\n" for r in rows))
        store = Store(folder / "evidence.sqlite3", config)
        history = []
        try:
            # All envelopes may be ingested in advance; knowledge-time filtering is mandatory.
            for row in rows:
                status = store.ingest(row["record"], row["received_at"])
                if status["status"] == "INVALID":
                    raise ValueError(f"invalid demo fixture: {status}")
            for phase, knowledge, oracle in phases:
                result = reconcile(store, BALANCE_AT, knowledge)
                expected_rows = expected_findings(oracle)
                actual = [{k: row[k] for k in expected_rows[0]} for row in result["findings"]]
                verified = actual == expected_rows
                for asset, spec in oracle.items():
                    ledger = result["ledgers"][asset]
                    verified = verified and ledger["investor_balances"] == spec["investors"] and ledger["liability"] == spec["liability"] and ledger["custody_rollforward"] == spec["custody"]
                for old in history:
                    verified = verified and store.read_run(old["run_id"]) == old
                    verified = verified and reconcile(store, BALANCE_AT, old["knowledge_at"]) == old
                history.append(result)
                document = {"scenario": scenario, "phase": phase, "expected": expected_rows, "actual": actual,
                            "literal_reference": oracle, "verified": verified, "result": result}
                write_report(folder / phase, document)
                summary.append({"scenario": scenario, "phase": phase, "verified": verified, "run_id": result["run_id"],
                                "expected": oracle, "expected_findings": expected_rows, "actual": financial_projection(result)})
        finally:
            store.close()
    (root / "summary.json").write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n")
    lines = ["# Stage 2 demo verification", "", "All quantities are synthetic. Oracles are independent literals. Difference = expected minus reported.", "", "| Scenario | Phase | Expected A differences (I1/I2/B) | Actual | Expected data state | Actual | Verified |", "|---|---|---|---|---|---|---|"]
    for row in summary:
        actual = [f for f in row["actual"]["findings"] if f["asset"] == "ASSET_A"]
        spec = row["expected"]["ASSET_A"]
        lines.append(f"| {row['scenario']} | {row['phase']} | {' / '.join(spec['differences'])} | {' / '.join(f['difference'] for f in actual)} | {spec['data_state']} | {actual[0]['data_state']} | {row['verified']} |")
    lines += ["", "Every ASSET_B investor/custody result is separately checked against 0.30 / 0.20 / 0.50 and 0.05 + 0.45."]
    (root / "summary.md").write_text("\n".join(lines) + "\n")
    return summary
