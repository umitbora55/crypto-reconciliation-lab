"""Deterministic JSON and human-readable Markdown evidence reports."""
import json
from pathlib import Path


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ") if value is not None else "unknown"


def write_report(prefix, document):
    prefix = Path(prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    result = document.get("result", document)
    prefix.with_suffix(".json").write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    lines = ["# Crypto reconciliation evidence", "", "Synthetic reference model; no fraud, insolvency or root-cause inference.", "",
             f"Run: `{result['run_id']}`  ", f"Rule: `{result['rule_version']}`  ", f"Balance at: `{result['balance_at']}`  ", f"Knowledge at: `{result['knowledge_at']}`", ""]
    if "scenario" in document:
        lines += [f"Demo: **{document['scenario']} / {document['phase']}**; oracle verified: **{document['verified']}**.", ""]
    lines += ["Difference = expected minus reported. Non-COMPLETE values are provisional observations only.", "", "| Check | Asset / scope | Expected amount | Reported amount | Difference | Expected status | Actual status |", "|---|---|---|---|---|---|---|"]
    for i, row in enumerate(result["findings"]):
        target = document.get("expected", [])
        expected = f"{target[i]['data_state']}/{target[i]['reconciliation_state']}" if target else "not an oracle run"
        lines.append(f"| {row['comparison']} | {row['asset']} / {row['scope']} | {cell(row['expected'])} | {cell(row['reported'])} | {cell(row['difference'])} | {expected} | {row['data_state']}/{row['reconciliation_state']} |")
    for asset, ledger in result["ledgers"].items():
        lines += ["", f"## {asset}: ledger roll-forward", "", f"Opening: `{json.dumps(ledger['opening_amounts'], sort_keys=True)}`", "", "| Event ID | Economic time | Investor deltas | Custody location / delta | Balances after |", "|---|---|---|---|---|"]
        for row in ledger["trace"]:
            lines.append(f"| `{row['event_id']}` | {row['occurred_at']} | {cell(row['investor_deltas'])} | {cell(row['custody_location'])} / {row['custody_delta']} | {cell(row['balances_after'])} |")
        lines += ["", f"Calculated liability: **{cell(ledger['liability'])}**. Customer custody roll-forward: `{json.dumps(ledger['custody_rollforward'], sort_keys=True)}`."]
    for asset, ledger in result["ledgers"].items():
        if ledger.get("correction_deliveries"):
            lines += ["", f"## {asset}: correction delivery and atomic groups", "", "Batch counts refer to source envelopes, not derived effects. Groups apply at the original economic time.", "", "```json", json.dumps({"deliveries": ledger["correction_deliveries"], "groups": ledger["correction_groups"]}, indent=2, sort_keys=True), "```"]
    lines += ["", "## Findings and evidence references", ""]
    for row in result["findings"]:
        lines += [f"### {row['comparison']} / {row['asset']} / {row['scope']}", "", f"Issues: `{json.dumps(row['issues'], sort_keys=True)}`", "", "Evidence IDs:", ""]
        lines += [f"- `{rid}`" for rid in row["evidence_ids"]]
    lines += ["", "## Evidence payloads", "", "Record hashes and receipt hashes reference immutable SQLite rows; the JSON report carries the same payloads.", ""]
    for rid, payload in result["evidence"].items():
        lines += [f"### `{rid}`", "", "```json", json.dumps(payload, indent=2, sort_keys=True), "```", ""]
    prefix.with_suffix(".md").write_text("\n".join(lines))
