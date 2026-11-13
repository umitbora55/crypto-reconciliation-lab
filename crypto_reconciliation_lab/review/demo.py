"""Prepare new synthetic review sources through the existing demo APIs only."""
import json
from pathlib import Path
import sqlite3

from ..demo import run_demos
from ..correction_demo import run_correction_demos
from . import SELECTION_FORMAT
from .export import export_selection, json_bytes
from .publication import new_output_directory

LABELS = {
    "clean": "Clean balances",
    "custody_difference": "Custody difference",
    "late_event": "Late withdrawal",
    "corrected_report": "Revised custody report",
    "deposit_amount_correction": "Deposit amount correction",
    "correction_before_target": "Correction before target",
    "duplicate_and_conflicting_corrections": "Duplicate and conflicting corrections",
    "void_deposit": "Void deposit",
    "void_internal_transfer": "Void internal transfer",
}
PHASE_LABELS = {
    "initial": "Initial knowledge", "later": "Later knowledge", "original": "Original records",
    "corrected_old_reports": "Correction known; original reports",
    "investor_report_updated": "Investor report revised",
    "investor_reports_updated": "Investor reports revised",
    "custody_report_updated": "Custody report revised",
    "target_pending": "Target pending",
    "target_received_old_reports": "Target known; original reports",
    "independent_reports_updated": "Independent reports revised",
    "single_correction": "One correction", "duplicate_correction": "Exact correction retry",
    "conflicting_corrections": "Conflicting corrections",
}


def write_guide(path, catalog):
    lookup = {(row["scenario"], row["phase"]): row for row in catalog}
    lines = ["# Five-minute review", "", "Open bundle/index.html by double-clicking it. No server or network is required.",
             "The page displays saved decisions. Stored payload identity is an export-integrity check, not a financial verdict or source authentication.",
             "", "## 1. Start with the independent examples", "",
             "Choose Clean balances. Review A for I1/I2 and B for customer liability separately for each asset. ASSET_A is 7 / 4 / 11; ASSET_B is 0.3 / 0.2 / 0.5. Never add A to B or combine assets.",
             "Choose Custody difference. ASSET_A B has expected 11, reported 10, difference +1. Investor checks and ASSET_B still match.",
             "", "## 2. Compare knowledge cuts", "",
             "Choose Late withdrawal / Initial knowledge. ASSET_A is INCOMPLETE / NOT_EVALUATED, with its saved provisional observation. The later withdrawal receipt is absent from this run's evidence.",
             "Compare it with Later knowledge in the same source. The later COMPLETE / MATCHED result has its own evidence. Return to the initial run to confirm its panel has not acquired that receipt.",
             "", "## 3. Inspect the deposit correction", "",
             "Choose Deposit amount correction, ASSET_A / A / I1, then follow these saved runs. Open Reports, Trace and correction groups, and then the linked record/receipt. Trace order is the stored economic order, not correction delivery order.", "",
             "| Saved phase | Exact run ID | A / I1 | B / customer liability |", "|---|---|---|---|"]
    expectations = [("original", "MATCHED; 7 versus 7", "MATCHED; 11 versus 11"),
                    ("corrected_old_reports", "MISMATCH; 8 versus 7, +1", "MISMATCH; 12 versus 11, +1"),
                    ("investor_report_updated", "MATCHED; 8 versus 8", "MISMATCH; 12 versus 11, +1"),
                    ("custody_report_updated", "MATCHED; 8 versus 8", "MATCHED; 12 versus 12")]
    for phase, a, b in expectations:
        row = lookup[("deposit_amount_correction", phase)]
        lines.append(f"| {PHASE_LABELS[phase]} | {row['run_id']} | {a} | {b} |")
    lines += ["", "The corrected ledger has I1=8, I2=4 and customer liability=12. The investor report revision changes A; the subsequent external customer-custody revision changes B. These reports are independent of the correction.",
              "Select B / ASSET_A / customer_liability to inspect the platform and external customer-custody reports separately. These are assets held for customers, not the platform's proprietary assets.",
              "", "## 4. Inspect unresolved and conflicting data", "",
              "Correction before target starts with TARGET_PENDING. Inspect the issue and correction receipt, then compare the later target and independent report revisions. No target is reconstructed in the earlier panel.",
              "Duplicate and conflicting corrections retains the exact retry as evidence without another economic effect. The final cut is CONFLICT / NOT_EVALUATED. A visible difference does not establish fraud, insolvency or a root cause.",
              "", "## 5. Follow and retain the evidence", "",
              "Filter by comparison, asset, scope or either state. Visible and total finding counts remain separate; an empty filter is not all matched.",
              "Open a finding, follow its saved report/trace/group references, and open a receipt. Raw data is text. Use Copy ID, Copy raw evidence, or Download original payload. If clipboard permission is unavailable, select the provided text and use your browser's normal copy command.",
              "Chronological comparison requires the same source alias, entire configuration, economic cut and rule, with different knowledge times. Ineligible pairs show a reason; missing rows remain missing.",
              "", "## Exact catalog", "", "| Source alias | Phase | Run ID |", "|---|---|---|"]
    lines += [f"| {row['source_alias']} | {row['phase']} | {row['run_id']} |" for row in catalog]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_demo(output):
    """Create only owned new sources, close them, then use the public exporter."""
    with new_output_directory(output) as staging:
        generated = [("stage1", run_demos(staging / "sources/stage1")),
                     ("stage2", run_correction_demos(staging / "sources/stage2"))]
        sources, catalog = [], []
        for stage, rows in generated:
            if not all(row["verified"] for row in rows):
                raise ValueError("DEMO_REFERENCE_FAILED: existing literal demo expectations did not match")
            scenarios = list(dict.fromkeys(row["scenario"] for row in rows))
            for scenario in scenarios:
                selected = [row for row in rows if row["scenario"] == scenario]
                relative = f"sources/{stage}/{scenario}/evidence.sqlite3"
                database = staging / relative
                # Demo construction has ended and its connections are closed.
                connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
                try:
                    saved = {row[0] for row in connection.execute("SELECT id FROM runs")}
                finally:
                    connection.close()
                if any(row["run_id"] not in saved for row in selected):
                    raise ValueError("DEMO_RUN_MISSING: selection must use actual saved run IDs")
                alias = scenario
                sources.append({"alias": alias, "label": LABELS[scenario], "database": relative,
                                "run_ids": [row["run_id"] for row in selected],
                                "run_labels": {row["run_id"]: PHASE_LABELS[row["phase"]] for row in selected}})
                for row in selected:
                    catalog.append({"source_alias": alias, "scenario": scenario,
                                    "phase": row["phase"], "run_id": row["run_id"],
                                    "verified": row["verified"], "expected": row["expected"],
                                    "actual": row["actual"]})
        selection = {"format": SELECTION_FORMAT, "sources": sources}
        (staging / "selection.json").write_bytes(json_bytes(selection))
        manifest = export_selection(staging / "selection.json", staging / "bundle")
        summary = {"format": "review-showcase-v1", "status": "COMPLETE", "runs": catalog,
                   "selection": "selection.json", "page": "bundle/index.html",
                   "guide": "five-minute-review.md", "export_format": manifest["format"],
                   "expectations_source": "Existing Stage 1/2 independent literal references; presentation labels never enter financial inputs."}
        (staging / "showcase.json").write_bytes(json_bytes(summary))
        write_guide(staging / "five-minute-review.md", catalog)
    return summary
