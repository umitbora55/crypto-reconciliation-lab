"""Small presentation-only test sources; never production scenario labels."""
import copy
import json
from pathlib import Path

from crypto_reconciliation_lab import Store, reconcile
from crypto_reconciliation_lab.demo import fixtures, BALANCE_AT, KNOWLEDGE_AT

BIG_INTEGER = 900719925474099312345678901234567890
LONG_OPENING = "123456789012345678901234567890.12345678"
LONG_EXPECTED = "123456789012345678901234567891.12345678"
EDGE_KNOWLEDGE = "2026-11-11T01:00:00.123456Z"
INERT_TEXT = "</script><script>globalThis.REVIEW_XSS=1</script><img src='https://example.invalid/inert-review' onerror='globalThis.REVIEW_XSS=2'> & \" Ω 你好"


def create_source(folder, edge=False):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    database = folder / "source.sqlite3"
    config, rows, _ = fixtures()
    rows = copy.deepcopy(rows)
    if edge:
        for row in rows:
            record = row["record"]
            if record["kind"] == "opening" and record["asset"] == "ASSET_A" and record["scope"] == "I1":
                record["amount"] = LONG_OPENING
            if record["kind"] == "manifest" and record["asset"] == "ASSET_B" and record["stream"] == "event":
                record["expected_count"] = 23
        rows = [row for row in rows if not (row["record"]["kind"] == "report"
                and row["record"]["asset"] == "ASSET_A"
                and row["record"]["stream"] == "external_custody")]
        # Eleven round trips preserve B's literal 0.3 / 0.2 balances, while
        # exercising a second presentation page of the stored economic trace.
        for ordinal in range(22):
            time = f"2026-11-10T04:{ordinal:02d}:00Z"
            sender, recipient = ("I1", "I2") if ordinal % 2 == 0 else ("I2", "I1")
            rows.append({"received_at": time, "record": {"kind": "event", "asset": "ASSET_B",
                "source": "P1", "platform": "P1", "business_day": "2026-11-10",
                "ref": f"PRESENTATION-{ordinal}", "occurred_at": time, "sequence": 1,
                "type": "transfer", "from_investor": sender, "to_investor": recipient,
                "custody": None, "amount": "0.01"}})
    store = Store(database, config)
    try:
        for row in rows:
            store.ingest(row["record"], row["received_at"])
        if edge:
            response = store.ingest({"kind": "report", "asset": "ASSET_A", "source": "P1",
                "platform": "P1", "amount": BIG_INTEGER, "marker": INERT_TEXT}, "not-a-time")
            if response["status"] != "INVALID":
                raise AssertionError("the hostile receipt must remain invalid evidence")
        result = reconcile(store, BALANCE_AT, EDGE_KNOWLEDGE if edge else KNOWLEDGE_AT)
        if edge:
            if result["ledgers"]["ASSET_A"]["investor_balances"]["I1"] != LONG_EXPECTED:
                raise AssertionError("long decimal literal changed")
            if result["ledgers"]["ASSET_B"]["investor_balances"] != {"I1": "0.3", "I2": "0.2"}:
                raise AssertionError("paired presentation transfers changed the literal balances")
        return database, result["run_id"]
    finally:
        store.close()


def create_selection(folder, sources):
    """sources is (alias, database_path, run_ids) tuples."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "selection.json"
    items = []
    for alias, database, run_ids in sources:
        items.append({"alias": alias, "database": str(Path(database).resolve()), "run_ids": list(run_ids)})
    path.write_text(json.dumps({"format": "review-selection-v1", "sources": items}, indent=2) + "\n", encoding="utf-8")
    return path
