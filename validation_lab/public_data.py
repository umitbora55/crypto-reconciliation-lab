"""Offline public-data checks, independent of production financial helpers.

Treasury mappings must be selected from reviewed official documentation. This
module never guesses changing account labels or treats a missing number as zero.
It is a cash-flow arithmetic adapter, not a customer custody-liability adapter.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sqlite3
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from scripts.validation.fetch_public_data import selected_scope, verify_offline

MAX_INT = 2**63 - 1
FTD_FIELDS = ("SETTLEMENT DATE", "CUSIP", "SYMBOL", "QUANTITY (FAILS)", "DESCRIPTION", "PRICE")


def whole_number(value, *, nonnegative=True):
    if not isinstance(value, str) or not re.fullmatch(r"-?(?:0|[1-9][0-9]*)", value):
        raise ValueError("MISSING_OR_NONINTEGER: exact whole-unit text required")
    number = int(value)
    if abs(number) > MAX_INT or (nonnegative and number < 0):
        raise ValueError("INTEGER_DOMAIN: outside declared nonnegative signed-64-bit range")
    return number


def cashflow_check(row, *, tolerance=0, rounding_reference=None):
    """Compare independent Python-integer and SQLite expressions for one day.

Values are published million USD units; no conversion into fictitious precise
cents. A nonzero tolerance requires an explicit reviewed rounding reference.
"""
    if set(row) != {"record_date", "opening", "deposits", "withdrawals", "closing"}:
        raise ValueError("SCHEMA: unexpected or missing cash-flow field")
    if not isinstance(row["record_date"], str) or date.fromisoformat(row["record_date"]).isoformat() != row["record_date"]:
        raise ValueError("DATE: canonical YYYY-MM-DD required")
    if type(tolerance) is not int or tolerance < 0 or tolerance > 2 or (tolerance and not rounding_reference):
        raise ValueError("ROUNDING: explicit reviewed policy required; maximum two published units")
    values = [whole_number(row[k]) for k in ("opening", "deposits", "withdrawals", "closing")]
    opening, deposits, withdrawals, closing = values
    calculated = opening + deposits - withdrawals
    residual = calculated - closing
    # SQLite can silently promote overflowing integer arithmetic to REAL. Refuse
    # that domain before the independent SQL expression, rather than rounding it.
    if any(abs(n) > MAX_INT for n in (opening + deposits, calculated, residual)):
        raise ValueError("SQL_INTEGER_OVERFLOW")
    with sqlite3.connect(":memory:") as connection:
        sql_result, sql_residual, sql_type = connection.execute(
            "SELECT ?1 + ?2 - ?3, ?1 + ?2 - ?3 - ?4, typeof(?1 + ?2 - ?3 - ?4)", values
        ).fetchone()
    if sql_type != "integer" or sql_result != calculated or sql_residual != residual:
        raise AssertionError("INDEPENDENT_ARITHMETIC_DISAGREEMENT")
    return {"record_date": row["record_date"], "unit": "million USD (published precision)",
            "opening": opening, "deposits": deposits, "withdrawals": withdrawals, "closing": closing,
            "integer_calculated_closing": calculated, "sql_calculated_closing": sql_result,
            "residual_million_usd": residual, "tolerance_million_usd": tolerance,
            "rounding_reference": rounding_reference,
            "status": "EXACT" if residual == 0 else "WITHIN_ROUNDING" if abs(residual) <= tolerance else "MISMATCH"}


def unique_field(rows, selectors, field, record_date):
    selected = [r for r in rows if r.get("record_date") == record_date and all(r.get(k) == v for k, v in selectors.items())]
    if len(selected) != 1:
        raise ValueError("SOURCE_GRAIN: expected exactly one matching row, found " + str(len(selected)))
    if field not in selected[0]:
        raise ValueError("SOURCE_SCHEMA: mapped field absent")
    whole_number(selected[0][field])
    return selected[0][field]


def map_dts_day(tables, record_date, mapping):
    """Map only explicit reviewed table/row/field identities; do not infer schema.

Both old close_today_bal and newer closing-account-row layouts can be expressed
by a mapping. No default mapping is asserted while official access is blocked.
"""
    if mapping.get("review_status") != "OFFICIAL_DOCUMENTATION_VERIFIED" or not mapping.get("reference"):
        raise ValueError("DOCUMENTATION_UNVERIFIED")
    if set(mapping.get("fields", {})) != {"opening", "deposits", "withdrawals", "closing"}:
        raise ValueError("MAPPING_INCOMPLETE")
    row = {"record_date": record_date}
    for name, spec in mapping["fields"].items():
        if spec["table"] not in tables:
            raise ValueError("SOURCE_TABLE_ABSENT")
        row[name] = unique_field(tables[spec["table"]], spec["where"], spec["field"], record_date)
    return row


def fiscal_api_rows(raw):
    """Reject incomplete pages, duplicate keys, absent rows, and schema omission."""
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    payload = json.loads(raw, object_pairs_hook=reject_duplicates)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list) or not payload["data"]:
        raise ValueError("EMPTY_OR_INVALID_DATA")
    rows = payload["data"]
    meta = payload.get("meta", {})
    if type(meta.get("total-count")) is not int or meta["total-count"] != len(rows):
        raise ValueError("INCOMPLETE_PAGINATION")
    if type(meta.get("total-pages")) is not int or meta["total-pages"] != 1:
        raise ValueError("INCOMPLETE_PAGINATION")
    if any(not isinstance(row, dict) or not row.get("record_date") for row in rows):
        raise ValueError("INVALID_ROW_SCHEMA")
    return rows


def ftd_profile(text):
    """Profile daily outstanding balances; never difference them into new fails.

Malformed rows remain in issue evidence. Duplicate date/CUSIP keys are a grain
warning, not automatically a financial failure. Source-specific exceptions need
reviewed documentation rather than silent deletion.
"""
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), delimiter="|")
    if tuple(reader.fieldnames or ()) != FTD_FIELDS:
        raise ValueError("FTD_SCHEMA_DRIFT")
    issues, keys, dates, cusips, rows = [], Counter(), [], set(), []
    for line, row in enumerate(reader, 2):
        problems = []
        if set(row) != set(FTD_FIELDS) or None in row.values():
            problems.append("COLUMN_COUNT")
        try:
            raw_date = row.get("SETTLEMENT DATE", "")
            parsed = datetime.strptime(raw_date, "%Y%m%d").date()
            if parsed.strftime("%Y%m%d") != raw_date:
                raise ValueError("noncanonical date")
            dates.append(parsed.isoformat())
        except (ValueError, TypeError):
            problems.append("SETTLEMENT_DATE")
        cusip = row.get("CUSIP", "")
        if not isinstance(cusip, str) or not re.fullmatch(r"[0-9A-Z*@#]{9}", cusip):
            problems.append("CUSIP_FORMAT")
        else:
            cusips.add(cusip)
        try:
            whole_number(row.get("QUANTITY (FAILS)"))
        except ValueError:
            problems.append("QUANTITY_DOMAIN")
        # Blank/dot price is preserved as missing; quantity and price do not give
        # labelled truth about institution-level failures or illegal short sales.
        price = row.get("PRICE")
        if price not in ("", ".") and (not isinstance(price, str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", price)):
            problems.append("PRICE_DOMAIN")
        key = (row.get("SETTLEMENT DATE"), cusip)
        keys[key] += 1
        if problems:
            issues.append({"line": line, "problems": problems, "record": row})
        rows.append(row)
    if not rows:
        raise ValueError("FTD_EMPTY_FILE")
    duplicates = [{"settlement_date": key[0], "cusip": key[1], "count": count} for key, count in keys.items() if count > 1]
    return {"rows": len(rows), "columns": list(FTD_FIELDS), "grain": "settlement date / CUSIP outstanding net fail balance",
            "date_min": min(dates) if dates else None, "date_max": max(dates) if dates else None,
            "distinct_dates": len(set(dates)), "distinct_cusips": len(cusips),
            "invalid_rows": len(issues), "invalid_row_fraction": len(issues) / len(rows), "issues": issues,
            "duplicate_keys": duplicates, "missing_price_rows": sum(r.get("PRICE") in ("", ".") for r in rows),
            "status": "QUALITY_ISSUES" if issues or duplicates else "VALID_WITHIN_DECLARED_CHECKS",
            "new_failure_count": "NOT_IDENTIFIABLE", "fail_age": "NOT_IDENTIFIABLE",
            "institutional_matching_ground_truth": "UNAVAILABLE", "illegal_short_selling": "NOT_INFERRED"}


def validate_cached_sources(root, output, selected_ids=None):
    """Report source access truth without treating a failed download as data."""
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError("choose a fresh validation output")
    register = verify_offline(root, selected_ids=selected_ids, emit=False)
    observations = []
    for source in register["sources"]:
        result = {"id": source["id"], "download_status": source["status"], "quality_status": "NOT_RUN"}
        if source["status"] == "DOWNLOADED":
            path = (root / source["path"]).resolve()
            if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
                raise ValueError("SOURCE_INTEGRITY")
            if source.get("table") in ("operating_cash_balance", "deposits_withdrawals_operating_cash"):
                try:
                    rows = fiscal_api_rows(path.read_text())
                    result.update(quality_status="PAGINATION_AND_STRUCTURE_ONLY", rows=len(rows),
                                  columns=sorted(set().union(*(r.keys() for r in rows))),
                                  dates=sorted({r["record_date"] for r in rows}),
                                  arithmetic_status="NOT_RUN_REVIEWED_MAPPING_REQUIRED")
                except (ValueError, TypeError) as error:
                    result.update(quality_status="FAIL", error=str(error))
            else:
                result["quality_status"] = "DOWNLOADED_REVIEW_REQUIRED"
        observations.append(result)
    result = {"format": "public-data-validation-v1", "status": "REAL_DATA_UNVERIFIED",
              "source_register_sha256": hashlib.sha256((root / "source-register.json").read_bytes()).hexdigest(),
              "real_financial_equalities_verified": 0, "observations": observations,
              "note": "Source download and independent arithmetic are separate acceptance gates."}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--scope", choices=("all", "financial", "references"), default="all")
    args = parser.parse_args()
    result = validate_cached_sources(args.source_root, args.output, selected_ids=selected_scope(args.scope))
    print(json.dumps({"status": result["status"], "equalities": result["real_financial_equalities_verified"]}))


if __name__ == "__main__":
    main()
