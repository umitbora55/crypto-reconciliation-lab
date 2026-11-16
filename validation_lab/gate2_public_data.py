"""Gate 2: offline analysis of hash-bound official Treasury and SEC captures.

The direct source equation, adapted native-engine exercise, and injected-format
experiments are separate populations. No source signatures or institution-level
ground truth are inferred from public aggregates.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import re
import sqlite3
import zipfile
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal, localcontext
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

from scripts.validation.fetch_public_data import plan, verify_offline
from validation_lab.public_data import FTD_FIELDS, cashflow_check, fiscal_api_rows, ftd_profile, whole_number

ACCESS_IDS = [r["id"] for r in plan() if r["kind"] != "data" or r["id"].endswith("2019-01")]
DATA_IDS = [r["id"] for r in plan() if r["id"] not in ACCESS_IDS]
ACCOUNT_ROLES = {
    "opening": "Treasury General Account (TGA) Opening Balance",
    "deposits": "Total TGA Deposits (Table II)",
    "withdrawals": "Total TGA Withdrawals (Table II) (-)",
    "closing": "Treasury General Account (TGA) Closing Balance",
}
FTD_FAMILIES = ("negative_quantity", "invalid_date", "invalid_cusip", "duplicate_key",
                "valid_cusip_substitution", "valid_quantity_change")


def dump_new(path, value):
    path = Path(path)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def proof(path):
    path = Path(path)
    return {"path": str(path.resolve()), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)


def official_sec_links(landing_bytes):
    parser = Links()
    parser.feed(landing_bytes.decode("utf-8", errors="strict"))
    return {urljoin("https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data", href)
            for href in parser.links}


def sec_zip_text(raw):
    """Read a single bounded text member without extracting paths to disk."""
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        if len(members) != 1:
            raise ValueError("SEC_ZIP_MEMBER_COUNT")
        member = members[0]
        if member.is_dir() or Path(member.filename).name != member.filename or "\\" in member.filename:
            raise ValueError("SEC_ZIP_PATH")
        if member.file_size > 32 * 1024 * 1024 or member.flag_bits & 1:
            raise ValueError("SEC_ZIP_LIMIT_OR_ENCRYPTED")
        text = archive.read(member).decode("ascii", errors="strict")
        lines = text.splitlines()
        if len(lines) < 4 or not re.fullmatch(r"Trailer record count [0-9]+", lines[-2]) or not re.fullmatch(r"Trailer total quantity of shares [0-9]+", lines[-1]):
            raise ValueError("SEC_TRAILER_FORMAT")
        body = "\n".join(lines[:-2]) + "\n"
        rows = list(csv.DictReader(io.StringIO(body), delimiter="|"))
        if not rows or int(lines[-2].split()[-1]) != len(rows):
            raise ValueError("SEC_TRAILER_COUNT")
        quantities = [whole_number(r.get("QUANTITY (FAILS)")) for r in rows]
        quantity_sum = sum(quantities)
        if quantity_sum != int(lines[-1].split()[-1]):
            raise ValueError("SEC_TRAILER_QUANTITY_SUM")
        return body, {"name": member.filename, "bytes": member.file_size,
                      "sha256": hashlib.sha256(text.encode("ascii")).hexdigest(),
                      "parsed_body_sha256": hashlib.sha256(body.encode("ascii")).hexdigest(),
                      "trailer": {"record_count": len(rows), "quantity_sum": quantity_sum,
                                  "original_lines": lines[-2:], "status": "COUNT_AND_QUANTITY_SUM_MATCH",
                                  "meaning": "File control totals only; sum across dates is not new failures."}}


def table_profile(rows):
    keys = [tuple(row.get(k) for k in ("record_date", "table_nbr", "account_type", "transaction_type", "src_line_nbr")) for row in rows]
    return {"rows": len(rows), "dates": sorted({r["record_date"] for r in rows}),
            "columns": sorted(set().union(*(r.keys() for r in rows))),
            "account_types": dict(Counter(r.get("account_type") for r in rows)),
            "null_counts": {key: sum(r.get(key) in (None, "null", "") for r in rows) for key in rows[0]},
            "negative_daily_components": sum(str(r.get("transaction_today_amt", "")).startswith("-") for r in rows),
            "candidate_grain": ["record_date", "table_nbr", "account_type", "transaction_type", "src_line_nbr"],
            "duplicate_candidate_grain_rows": len(keys) - len(set(keys)),
            "calendar_gaps": "NOT_CLASSIFIED_AS_MISSING_DELIVERIES"}


def direct_day(rows, detail, record_date):
    """Select exact modern Table I rows and independently check its daily totals."""
    if record_date < "2022-04-18":
        return {"record_date": record_date, "status": "NOT_RUN_LEGACY_FOUR_TOTALS_ABSENT",
                "data_class": "REAL_PUBLIC_DIRECT", "selected_rows": [],
                "reason": "Legacy Table I lacks direct deposit/withdrawal totals; no sum of potentially hierarchical Table II categories is substituted."}
    selected = {}
    for role, account in ACCOUNT_ROLES.items():
        candidates = [(index, row) for index, row in enumerate(rows) if row.get("record_date") == record_date and row.get("account_type") == account]
        if len(candidates) != 1:
            raise ValueError("DAILY_ROW_GRAIN: " + role)
        index, row = candidates[0]
        if row.get("table_nbr") != "I" or row.get("sub_table_name") != "Cash Balance Details":
            raise ValueError("DAILY_TABLE_SCOPE")
        selected[role] = {"json_pointer": "/data/" + str(index), "field": "open_today_bal", "row": row}
    normalized = {"record_date": record_date, **{role: item["row"]["open_today_bal"] for role, item in selected.items()}}
    result = cashflow_check(normalized, tolerance=0)
    with localcontext() as context:
        context.prec = 100
        # Separately expressed Decimal calculation, sharing selected raw text.
        decimal_result = Decimal(normalized["opening"]) - Decimal(normalized["withdrawals"]) + Decimal(normalized["deposits"])
        decimal_residual = decimal_result - Decimal(normalized["closing"])
    if str(decimal_result) != str(result["integer_calculated_closing"]) or int(decimal_residual) != result["residual_million_usd"]:
        raise AssertionError("DECIMAL_INTEGER_DISAGREEMENT")
    cross = {}
    for role, account, kind in (("deposits", "Treasury General Account Total Deposits", "Deposits"),
                                ("withdrawals", "Treasury General Account Total Withdrawals", "Withdrawals")):
        candidates = [(index, row) for index, row in enumerate(detail) if row.get("record_date") == record_date and row.get("account_type") == account and row.get("transaction_type") == kind]
        if len(candidates) != 1:
            raise ValueError("TABLE_II_TOTAL_GRAIN")
        index, row = candidates[0]
        actual = whole_number(row["transaction_today_amt"])
        cross[role] = {"json_pointer": "/data/" + str(index), "field": "transaction_today_amt", "row": row,
                       "equal_to_table_i": actual == result[role], "difference": actual - result[role]}
    result.update(data_class="REAL_PUBLIC_DIRECT", selected_rows=selected, table_ii_cross_checks=cross,
                  decimal_calculated_closing=str(decimal_result), normalized=normalized,
                  rounding_diagnostic="WITHIN_FIXED_2_MILLION_BOUND" if abs(result["residual_million_usd"]) <= 2 else "OUTSIDE_FIXED_ROUNDING_BOUND",
                  shared_parsing="All three arithmetic expressions share selected source row text; independent expressions do not independently validate source semantics.")
    return result


def adapted_input(normalized):
    """Real totals, authored participant/time/manifest semantics; never native data."""
    day = normalized["record_date"]
    opening, cut = day + "T00:00:00Z", day + "T23:00:00Z"
    known = (date.fromisoformat(day) + timedelta(days=1)).isoformat() + "T00:00:00Z"
    config = {"platform": "ADAPTED_TGA", "custodian": "ADAPTED_CUSTODY", "investors": ["AGGREGATE"],
              "assets": {"MILLION_USD": 0}, "opening_at": opening}
    rows, lineage = [], []
    def add(kind, fields, role, source="ADAPTED_TGA", received=known):
        rows.append({"record": {"kind": kind, "platform": "ADAPTED_TGA", "source": source, "asset": "MILLION_USD", **fields}, "received_at": received})
        lineage.append({"input_index": len(rows)-1, "source_role": role,
                        "authored_fields": "Participant/source IDs, custody allocation, all time-of-day values, versions and count manifests are research assumptions."})
    for scope, amount, role in (("AGGREGATE", normalized["opening"], "opening"), ("platform", "0", "AUTHORED_ZERO_ALLOCATION"), ("external", normalized["opening"], "opening")):
        add("opening", {"scope": scope, "balance_at": opening, "amount": amount}, role, received=opening)
    for sequence, role, kind in ((1, "deposits", "deposit"), (2, "withdrawals", "withdrawal")):
        if whole_number(normalized[role]) == 0:
            continue
        add("event", {"business_day": day, "ref": role.upper(), "occurred_at": day + f"T{sequence:02d}:00:00Z", "sequence": sequence,
                       "type": kind, "from_investor": "AGGREGATE" if kind == "withdrawal" else None,
                       "to_investor": "AGGREGATE" if kind == "deposit" else None, "custody": "external", "amount": normalized[role]}, role)
    event_count = sum(r["record"]["kind"] == "event" for r in rows)
    for stream, scope, amount, source, role in (("investor", "AGGREGATE", normalized["closing"], "ADAPTED_TGA", "closing"),
                                               ("platform_custody", "platform", "0", "ADAPTED_TGA", "AUTHORED_ZERO_ALLOCATION"),
                                               ("external_custody", "external", normalized["closing"], "ADAPTED_CUSTODY", "closing")):
        add("report", {"stream": stream, "scope": scope, "balance_at": cut, "version": 1, "amount": amount}, role, source)
    for stream, count in (("opening", 3), ("event", event_count), ("investor", 1), ("platform_custody", 1), ("external_custody", 1)):
        add("manifest", {"stream": stream, "coverage_from": opening if stream in ("opening", "event") else cut,
                         "coverage_to": opening if stream == "opening" else cut, "expected_count": count}, "AUTHORED_COUNT_MANIFEST",
            "ADAPTED_CUSTODY" if stream == "external_custody" else "ADAPTED_TGA")
    return {"data_class": "REAL_PUBLIC_ADAPTED", "config": config, "balance_at": cut, "knowledge_at": known, "rows": rows, "lineage": lineage}


def run_adapted(day, output):
    from crypto_reconciliation_lab.engine import reconcile
    from crypto_reconciliation_lab.store import Store
    data = adapted_input(day["normalized"])
    dump_new(output / "input.json", data)
    store = Store(output / "evidence.sqlite3", data["config"])
    try:
        for row in data["rows"]:
            accepted = store.ingest(row["record"], row["received_at"])
            if accepted["status"] in ("INVALID", "CONFLICT"):
                raise AssertionError("ADAPTED_INGEST: " + str(accepted))
        result = reconcile(store, data["balance_at"], data["knowledge_at"])
        expected_difference = str(day["residual_million_usd"])
        expected_state = "MATCHED" if expected_difference == "0" else "MISMATCH"
        if len(result["findings"]) != 2 or any(r["data_state"] != "COMPLETE" or r["reconciliation_state"] != expected_state or r["difference"] != expected_difference for r in result["findings"]):
            raise AssertionError("ADAPTED_FINANCIAL_DISAGREEMENT")
        if store.read_run(result["run_id"]) != result:
            raise AssertionError("ADAPTED_READBACK")
        dump_new(output / "result.json", result)
        return {"record_date": day["record_date"], "data_class": "REAL_PUBLIC_ADAPTED", "status": "PASS",
                "expected_state": expected_state, "expected_difference": expected_difference,
                "input": proof(output / "input.json"), "result": proof(output / "result.json"), "run_id": result["run_id"]}
    finally:
        store.close()


def ftd_injections(text, source_id, source_proof):
    records = list(csv.DictReader(io.StringIO(text), delimiter="|"))
    candidates = [row for row in records if ftd_profile("|".join(FTD_FIELDS)+"\n"+"|".join(row[k] for k in FTD_FIELDS)+"\n")["status"] == "VALID_WITHIN_DECLARED_CHECKS"]
    observations = []
    for seed in (11, 29, 47):
        picked = random.Random(seed).sample(range(len(candidates)), 5)
        for sample, index in enumerate(picked):
            original = candidates[index]
            for family in FTD_FAMILIES:
                for injected in (False, True):
                    row = dict(original)
                    rows = [row]
                    if injected:
                        if family == "negative_quantity": row["QUANTITY (FAILS)"] = "-1"
                        elif family == "invalid_date": row["SETTLEMENT DATE"] = "20250230"
                        elif family == "invalid_cusip": row["CUSIP"] = "INVALID"
                        elif family == "duplicate_key": rows.append(dict(row))
                        elif family == "valid_cusip_substitution": row["CUSIP"] = "000000001" if row["CUSIP"] != "000000001" else "000000002"
                        elif family == "valid_quantity_change": row["QUANTITY (FAILS)"] = str(int(row["QUANTITY (FAILS)"])+1)
                    payload = "|".join(FTD_FIELDS)+"\n"+"\n".join("|".join(r[k] for k in FTD_FIELDS) for r in rows)+"\n"
                    result = ftd_profile(payload)
                    detected = result["status"] != "VALID_WITHIN_DECLARED_CHECKS"
                    observations.append({"case_id": f"{source_id}.{seed}.{sample}.{family}.{int(injected)}", "seed": seed,
                        "data_class": "REAL_PLUS_SYNTHETIC_INJECTION", "family": family, "injected": injected,
                        "detected": detected, "classification": "TP" if detected and injected else "FP" if detected else "FN" if injected else "TN",
                        "source_file": source_proof, "original_row": original, "input": payload,
                        "input_sha256": hashlib.sha256(payload.encode()).hexdigest(), "actual": result,
                        "truth_provenance": "Known research transformation relative to retained public row; not a natural-error label."})
    return observations


def analyze(access_root, data_root, policy_path, output, *, adapted=True):
    access_root, data_root, output = map(lambda p: Path(p).resolve(), (access_root, data_root, output))
    a = verify_offline(access_root, ACCESS_IDS, emit=False)
    b = verify_offline(data_root, DATA_IDS, emit=False)
    sources = {r["id"]: (root, r) for root, register in ((access_root, a), (data_root, b)) for r in register["sources"]}
    if set(sources) != {r["id"] for r in plan()}:
        raise ValueError("INCOMPLETE_COMBINED_SOURCE_SCOPE")
    policy = json.loads(Path(policy_path).read_text())
    if policy.get("strict_equality_tolerance_million_usd") != 0 or policy.get("rounding_diagnostic_absolute_bound_million_usd") != 2:
        raise ValueError("FIXED_ROUNDING_POLICY_CHANGED")
    output.mkdir(parents=True, exist_ok=False)
    periods, all_days, adapted_rows, ftd, injections = [], [], [], [], []
    for period in ("2019-01", "2022-04", "2024-01", "2025-01", "2026-11"):
        pair = []
        for table in ("operating_cash_balance", "deposits_withdrawals_operating_cash"):
            root, source = sources[f"dts-{table}-{period}"]
            if source["status"] != "DOWNLOADED":
                raise ValueError("SOURCE_UNAVAILABLE: " + source["id"])
            path = root / source["path"]
            rows = fiscal_api_rows(path.read_text())
            if any(not source["period"][0] <= r["record_date"] <= source["period"][1] for r in rows):
                raise ValueError("DATE_OUTSIDE_REQUEST")
            pair.append((rows, proof(path)))
        opening, detail = pair[0][0], pair[1][0]
        dates = sorted({r["record_date"] for r in opening})
        if dates != sorted({r["record_date"] for r in detail}):
            raise ValueError("CROSS_TABLE_DATE_COVERAGE")
        days = [direct_day(opening, detail, day) for day in dates]
        for day in days:
            day["source_files"] = [pair[0][1], pair[1][1]]
            if adapted and "normalized" in day:
                target = output / "adapted" / day["record_date"]
                target.mkdir(parents=True)
                adapted_rows.append(run_adapted(day, target))
        periods.append({"period": period, "operating": table_profile(opening), "flows": table_profile(detail),
                        "dates": len(dates), "direct_days": sum("normalized" in d for d in days),
                        "outcomes": dict(Counter(d["status"] for d in days))})
        all_days.extend(days)
    landing_root, landing = sources["sec-ftd-documentation"]
    if landing["status"] != "DOWNLOADED":
        raise ValueError("SEC_LANDING_NOT_DOWNLOADED")
    links = official_sec_links((landing_root / landing["path"]).read_bytes())
    for source_id in ("sec-ftd-202401a", "sec-ftd-202501a"):
        root, source = sources[source_id]
        if source["url"] not in links or source["status"] != "DOWNLOADED":
            raise ValueError("SEC_FILE_NOT_LINKED_FROM_OFFICIAL_LANDING")
        path = root / source["path"]
        text, member = sec_zip_text(path.read_bytes())
        result = ftd_profile(text)
        parsed_rows = list(csv.DictReader(io.StringIO(text), delimiter="|"))
        layout_warnings = [{"line": index+2, "field": key, "declared_maximum": maximum, "actual_length": len(row[key]),
                            "value": row[key], "record_date": row["SETTLEMENT DATE"], "cusip": row["CUSIP"]}
                           for index, row in enumerate(parsed_rows) for key, maximum in (("SYMBOL", 10), ("DESCRIPTION", 30)) if len(row[key]) > maximum]
        ftd.append({"source_id": source_id, "source_file": proof(path), "member": member,
                    "official_landing": proof(landing_root / landing["path"]), "quality": result,
                    "official_layout_warnings": layout_warnings,
                    "warning_meaning": "Published-record versus documented maximum-length discrepancy; not fraud or an independently labelled financial error."})
        injections.extend(ftd_injections(text, source_id, proof(path)))
    direct = [r for r in all_days if "normalized" in r]
    summary = {"format": "validation-gate2-public-data-v1", "data_class": "MIXED_SEPARATELY_LABELLED", "policy": proof(policy_path),
               "raw_treasury_rows": sum(p["operating"]["rows"]+p["flows"]["rows"] for p in periods),
               "raw_sec_rows": sum(r["quality"]["rows"] for r in ftd), "periods": periods,
               "direct_days": len(direct), "direct_exact_equalities": sum(r["status"] == "EXACT" for r in direct),
               "direct_rounding_only": sum(r["status"] != "EXACT" and abs(r["residual_million_usd"]) <= 2 for r in direct),
               "direct_outside_rounding": sum(abs(r["residual_million_usd"]) > 2 for r in direct),
               "legacy_days_not_run": len(all_days)-len(direct), "cross_table_total_mismatches": sum(not x["equal_to_table_i"] for r in direct for x in r["table_ii_cross_checks"].values()),
               "adapted_cases": len(adapted_rows), "adapted_status": "PASS" if adapted_rows else "NOT_RUN",
               "sec": ftd, "injection_observations": len(injections), "injection_confusion": dict(Counter(r["classification"] for r in injections)),
               "injection_by_family": {family: dict(Counter(r["classification"] for r in injections if r["family"] == family)) for family in FTD_FAMILIES},
               "native_institutional_ground_truth": "NO_PUBLIC_TRANSACTION_GROUND_TRUTH"}
    dump_new(output / "direct-days.json", all_days)
    dump_new(output / "adapted-cases.json", adapted_rows)
    dump_new(output / "ftd-injections.json", injections)
    dump_new(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--access-root", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--no-adapted", action="store_true")
    args = parser.parse_args()
    result = analyze(args.access_root, args.data_root, args.policy, args.output, adapted=not args.no_adapted)
    print(json.dumps({k: result[k] for k in ("raw_treasury_rows", "raw_sec_rows", "direct_days", "direct_exact_equalities", "direct_rounding_only", "legacy_days_not_run", "adapted_cases", "injection_observations", "injection_confusion")}))


if __name__ == "__main__":
    main()
