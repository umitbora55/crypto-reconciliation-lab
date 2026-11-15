"""Small, deterministic TEST-ONLY inputs and recorded-execution CLI evidence.

The fixtures contain public synthetic names and fixed public signing seeds.
Expected quantities are hand-authored literals, never a financial-engine oracle.
"""
import copy
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

PLATFORM = "TEST_PLATFORM"
CUSTODIAN = "TEST_CUSTODIAN"
RECEIVER = "TEST-ONLY:execution-demo"
OPENING = "2026-11-12T00:00:00.000000Z"
BALANCE_AT = "2026-11-12T23:59:59.000000Z"
KNOWLEDGE_AT = "2026-11-13T01:00:00.000000Z"
CONFIG = {"platform": PLATFORM, "custodian": CUSTODIAN, "investors": ["I1", "I2"],
          "assets": {"ASSET_A": 8, "ASSET_B": 2}, "opening_at": OPENING}
NAMESPACES = {PLATFORM: "test-platform:", CUSTODIAN: "test-custodian:"}
TEST_SEEDS = {"platform-original": b"5" * 32, "platform-next": b"6" * 32,
              "custodian-original": b"7" * 32}
KEY_SOURCES = {"platform-original": PLATFORM, "platform-next": PLATFORM,
               "custodian-original": CUSTODIAN}
REFERENCE = {
    "ASSET_A": {"investors": {"I1": "7", "I2": "4"}, "liability": "11",
                "custody": {"platform": "2", "external": "9"}},
    "ASSET_B": {"investors": {"I1": "0.3", "I2": "0.2"}, "liability": "0.5",
                "custody": {"platform": "0.05", "external": "0.45"}},
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def _identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value) + b"\n")


def financial_records(mismatch=False):
    """Return thirty independently specified complete financial envelopes."""
    feeds = {PLATFORM: [], CUSTODIAN: []}
    def add(kind, asset, source=PLATFORM, received=KNOWLEDGE_AT, **fields):
        feeds[source].append({"record": {"kind": kind, "asset": asset, "source": source,
                                          "platform": PLATFORM, **fields}, "received_at": received})
    for asset, amounts in (("ASSET_A", ("6", "4", "2", "8")),
                           ("ASSET_B", ("0.10", "0.20", "0.05", "0.25"))):
        for scope, amount in zip(("I1", "I2", "platform", "external"), amounts):
            add("opening", asset, received=OPENING, scope=scope, balance_at=OPENING, amount=amount)
    events = (("ASSET_A", "A-transfer", "transfer", "I1", "I2", None, "1", 1),
              ("ASSET_A", "A-deposit", "deposit", None, "I1", "external", "2", 2),
              ("ASSET_A", "A-withdrawal", "withdrawal", "I2", None, "external", "1", 3),
              ("ASSET_B", "B-deposit", "deposit", None, "I1", "external", "0.20", 2))
    for asset, reference, kind, sender, recipient, custody, amount, hour in events:
        when = "2026-11-12T{:02d}:00:00.000000Z".format(hour)
        add("event", asset, received=when, business_day="2026-11-12", ref=reference,
            occurred_at=when, sequence=1, type=kind, from_investor=sender,
            to_investor=recipient, custody=custody, amount=amount)
    for asset in ("ASSET_A", "ASSET_B"):
        values = REFERENCE[asset]
        for stream, scope, amount in (
            ("investor", "I1", values["investors"]["I1"]),
            ("investor", "I2", values["investors"]["I2"]),
            ("platform_custody", "platform", values["custody"]["platform"]),
            ("external_custody", "external", "8" if mismatch and asset == "ASSET_A" else values["custody"]["external"]),
        ):
            add("report", asset, CUSTODIAN if stream == "external_custody" else PLATFORM,
                stream=stream, scope=scope, balance_at=BALANCE_AT, version=1, amount=amount)
        for stream, count in (("opening", 4), ("event", 3 if asset == "ASSET_A" else 1),
                              ("investor", 2), ("platform_custody", 1), ("external_custody", 1)):
            add("manifest", asset, CUSTODIAN if stream == "external_custody" else PLATFORM,
                stream=stream, coverage_from=OPENING if stream in ("opening", "event") else BALANCE_AT,
                coverage_to=OPENING if stream == "opening" else BALANCE_AT, expected_count=count)
    return feeds


def snapshot(records):
    return b"".join(canonical(row) + b"\n" for row in records)


def policy(epoch=1):
    """Public TEST-ONLY policy; epoch two revokes the first platform key."""
    if epoch not in (1, 2):
        raise ValueError("execution demo policy supports only epoch 1 or 2")
    from ..model import digest
    from ..source_auth.crypto import public_key, fingerprint
    from ..source_auth.policy import validate_policy
    grants = {PLATFORM: [], CUSTODIAN: []}
    for asset in ("ASSET_A", "ASSET_B"):
        for kind, channel in (("opening", "none"), ("event", "none"), ("correction", "none"),
                              ("correction_manifest", "none"), ("report", "investor"),
                              ("report", "platform_custody"), ("manifest", "opening"),
                              ("manifest", "event"), ("manifest", "investor"),
                              ("manifest", "platform_custody")):
            grants[PLATFORM].append({"source": PLATFORM, "platform": PLATFORM, "asset": asset,
                                     "kind": kind, "channel": channel})
        for kind in ("report", "manifest"):
            grants[CUSTODIAN].append({"source": CUSTODIAN, "platform": PLATFORM, "asset": asset,
                                      "kind": kind, "channel": "external_custody"})
    names = ["platform-original", "custodian-original"]
    if epoch == 2:
        names.append("platform-next")
    keys = []
    for name in names:
        key = public_key(TEST_SEEDS[name])
        keys.append({"key_id": name, "source": KEY_SOURCES[name], "public_key": key.hex(),
                     "fingerprint": fingerprint(key),
                     "status": "revoked" if epoch == 2 and name == "platform-original" else "active"})
    return validate_policy({"format": "source-auth-policy-v1", "receiver": RECEIVER,
                            "configuration_digest": digest(CONFIG),
                            "sources": [{"source": name, "namespace": NAMESPACES[name], "capabilities": grants[name]}
                                        for name in (PLATFORM, CUSTODIAN)], "keys": keys}, CONFIG, RECEIVER)


def sign_snapshot(data, *, source, stream_id, rotated=False):
    """Sign synthetic input using public fixture seeds; never real source keys."""
    from ..model import digest
    from ..source_auth.crypto import sign_statement
    from ..source_auth.scope import snapshot_bytes, capabilities
    if source not in NAMESPACES:
        raise ValueError("unknown synthetic source")
    key_id = ("platform-next" if rotated else "platform-original") if source == PLATFORM else "custodian-original"
    snap = snapshot_bytes(data)
    statement = {"format": "source-admission-statement-v1", "source": source,
                 "receiver": RECEIVER, "configuration_digest": digest(CONFIG), "stream_id": stream_id,
                 "plan": snap.plan, "capabilities": capabilities(snap, CONFIG)}
    return sign_statement(statement, TEST_SEEDS[key_id], key_id)


def build_fixture(root, *, protected=False, mismatch=False):
    """Initialize/admit a fresh schema-6 fixture; never evaluate or create runs."""
    if protected:
        from ..source_auth.crypto import require_auth
        require_auth()
    from ..store import Store
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    database = root / "source.sqlite3"
    configuration_path = root / "configuration.json"
    _write(configuration_path, CONFIG)
    feeds = financial_records(mismatch)
    paths, envelopes, operations = {}, {}, []
    initial = policy(1) if protected else None
    rotated = policy(2) if protected else None
    store = Store(database, CONFIG, target_schema=6)
    try:
        if protected:
            from ..source_auth.runtime import enable_protection, ingest_signed
            enable_protection(store, RECEIVER, initial, observed_at="2026-11-15T08:00:00Z")
            _write(root / "policy-1.json", initial)
            _write(root / "policy-2.json", rotated)
        for source in (PLATFORM, CUSTODIAN):
            paths[source] = root / (source.lower() + ".jsonl")
            data = snapshot(feeds[source])
            paths[source].write_bytes(data)
            if protected:
                stream = NAMESPACES[source] + "initial"
                envelope = sign_snapshot(data, source=source, stream_id=stream)
                envelopes[source] = root / (source.lower() + "-envelope.json")
                envelopes[source].write_bytes(envelope)
                result = ingest_signed(store, data, envelope, observed_at="2026-11-15T08:01:00Z")
                if result["status"] != "COMPLETE":
                    raise ValueError("EXECUTION_DEMO_ADMISSION: initial synthetic admission failed")
            else:
                result = [store.ingest(row["record"], row["received_at"]) for row in feeds[source]]
                if any(row["status"] != "ACCEPTED" for row in result):
                    raise ValueError("EXECUTION_DEMO_ADMISSION: initial legacy input failed")
            operations.append({"source": source, "snapshot": _identity(data), "result": result})
        if store.db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] != 30:
            raise ValueError("EXECUTION_DEMO_FIXTURE: expected thirty physical receipts")
        if store.db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] != 0:
            raise ValueError("EXECUTION_DEMO_FIXTURE: constructor must not evaluate")
    finally:
        store.close()
    _write(root / "fixture.json", {"format": "execution-test-fixture-v1", "protected": protected,
                                   "expected_initial_physical_receipts": 30, "operations": operations,
                                   "fixture_role": "TEST_ONLY_SYNTHETIC_INPUT_CONSTRUCTION", "financial_evaluation": "NOT_RUN"})
    return {"database": database, "config": copy.deepcopy(CONFIG), "configuration_path": configuration_path,
            "balance_at": BALANCE_AT, "knowledge_at": KNOWLEDGE_AT, "records_by_source": feeds,
            "snapshot_paths": paths, "envelope_paths": envelopes, "initial_policy": initial,
            "rotated_policy": rotated, "receiver": RECEIVER}


LEGACY_CASES = ("legacy_unrecorded", "legacy_recorded", "legacy_retry", "legacy_conflict",
                "legacy_new_request", "legacy_multiple", "legacy_show", "legacy_export", "legacy_export_existing")
PROTECTED_CASES = ("protected_recorded", "protected_retry_after_change", "protected_new_request",
                   "protected_original_readback", "protected_multiple", "protected_export",
                   "signed_mismatch", "signed_mismatch_show")


def _cli(root, name, arguments, expected_exit, expected_status=None, expected_reason=None, *, json_output=True):
    folder = root / "commands" / name
    folder.mkdir(parents=True, exist_ok=False)
    argv = [sys.executable, "-B", *(["-I"] if sys.flags.isolated else []),
            "-m", "crypto_reconciliation_lab", *map(str, arguments)]
    start, timer = datetime.now(timezone.utc).isoformat(), time.monotonic()
    completed = subprocess.run(argv, cwd=Path.cwd(), capture_output=True, timeout=30)
    (folder / "stdout.txt").write_bytes(completed.stdout)
    (folder / "stderr.txt").write_bytes(completed.stderr)
    command = {"argv": argv, "cwd": str(Path.cwd()), "started_at": start,
               "finished_at": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": time.monotonic() - timer,
               "exit_code": completed.returncode, "stdout": _identity(completed.stdout), "stderr": _identity(completed.stderr)}
    _write(folder / "command.json", command)
    try:
        result = json.loads(completed.stdout) if json_output else completed.stdout.decode("utf-8").strip()
    except (ValueError, UnicodeError) as exc:
        raise ValueError("EXECUTION_DEMO_CLI: command did not produce its declared output: " + name) from exc
    _write(folder / "result.json", result)
    actual = {"exit_code": completed.returncode, "status": result.get("status") if json_output else None,
              "reason_code": result.get("reason_code") if json_output else None}
    expected = {"exit_code": expected_exit, "status": expected_status, "reason_code": expected_reason}
    case = {"id": name, "command": str((folder / "command.json").relative_to(root)),
            "result": str((folder / "result.json").relative_to(root)), "expected": expected, "actual": actual,
            "checks": [], "passed": actual == expected}
    if not case["passed"]:
        raise ValueError("EXECUTION_DEMO_CLI: " + name + " expected " + str(expected) + "; actual " + str(actual))
    return result, case


def _check(case, field, expected, actual):
    passed = expected == actual
    case["checks"].append({"field": field, "expected": expected, "actual": actual, "passed": passed})
    case["passed"] = case["passed"] and passed
    if not passed:
        raise ValueError("EXECUTION_DEMO_REFERENCE: " + case["id"] + "/" + field)


def _financial(case, result, *, mismatch=False):
    financial = result["financial_result"]
    for asset, literal in REFERENCE.items():
        ledger = financial["ledgers"][asset]
        for name, expected in (("investor_balances", literal["investors"]), ("liability", literal["liability"]),
                               ("custody_rollforward", literal["custody"])):
            _check(case, asset + "." + name, expected, ledger[name])
    expected = []
    for asset, literal in REFERENCE.items():
        for investor in ("I1", "I2"):
            amount = literal["investors"][investor]
            expected.append({"asset": asset, "comparison": "A", "scope": investor, "expected": amount,
                             "reported": amount, "difference": "0", "data_state": "COMPLETE", "reconciliation_state": "MATCHED"})
        wrong = mismatch and asset == "ASSET_A"
        expected.append({"asset": asset, "comparison": "B", "scope": "customer_liability", "expected": literal["liability"],
                         "reported": "10" if wrong else literal["liability"], "difference": "1" if wrong else "0",
                         "data_state": "COMPLETE", "reconciliation_state": "MISMATCH" if wrong else "MATCHED"})
    fields = tuple(expected[0])
    actual = [{key: row[key] for key in fields} for row in financial["findings"]]
    _check(case, "six_literal_financial_findings", expected, actual)
    case["financial_findings"] = actual


def _context(case, result, *, protected=False, receipts=30, epoch=None):
    context = result["context"]
    _check(case, "receipt_inventory", receipts, len(context["tables"]["receipts"]))
    _check(case, "record_inventory", 30, len(context["tables"]["records"]))
    _check(case, "complete_input_scope", True, context["scope"]["complete"])
    _check(case, "admission_mode", "PROTECTED" if protected else "LEGACY", context["claims"]["admission_mode"])
    _check(case, "legacy_signature_status", "NOT_APPLICABLE" if protected else "UNSIGNED", context["claims"]["legacy_signature_status"])
    _check(case, "signature_verification", "NOT_PERFORMED", context["claims"]["source_signature_verification"])
    _check(case, "actor_authorization", "NOT_DEFINED", context["claims"]["run_actor_authorization"])
    _check(case, "observed_policy_epoch", epoch, context["observed_policy_head"]["epoch"] if context["observed_policy_head"] else None)
    _check(case, "original_acceptance_epochs", [1] if protected else [], context["acceptance_epochs"])
    case["execution"] = {key: result[key] for key in ("request_id", "execution_id", "run_id", "context_hash", "run_payload_sha256", "replayed")}
    case["context_observation"] = {"physical_receipts": receipts, "normalized_records": 30,
                                   "observed_policy_epoch": epoch, "acceptance_epochs": context["acceptance_epochs"],
                                   "selected_evidence_count": len(context["selected_evidence"]), "claims": context["claims"]}


def _raw_execution(database, execution_id):
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute("""SELECT c.payload,r.payload FROM recorded_executions e
            JOIN execution_contexts c ON c.context_hash=e.context_hash JOIN runs r ON r.id=e.run_id
            WHERE e.execution_id=?""", (execution_id,)).fetchone()
        if row is None:
            raise ValueError("EXECUTION_DEMO_EXPORT: saved execution missing")
        return row[0], row[1].encode("utf-8")


def _export_checks(case, database, execution_id, output):
    context, run = _raw_execution(database, execution_id)
    _check(case, "export_member_inventory", ["context.json", "execution.json", "run.json", "summary.json", "summary.md"],
           sorted(p.name for p in output.iterdir()))
    _check(case, "exact_saved_context_bytes", _identity(context), _identity((output / "context.json").read_bytes()))
    _check(case, "exact_saved_run_bytes", _identity(run), _identity((output / "run.json").read_bytes()))


def _advance_protected(fixture, root):
    from ..model import digest
    from ..source_auth.runtime import activate_policy, ingest_signed
    from ..store import Store
    duplicate = copy.deepcopy(next(row for row in fixture["records_by_source"][CUSTODIAN]
                                   if row["record"]["kind"] == "report" and row["record"]["asset"] == "ASSET_A"))
    data = snapshot([duplicate])
    envelope = sign_snapshot(data, source=CUSTODIAN, stream_id=NAMESPACES[CUSTODIAN] + "second-physical")
    (root / "duplicate.jsonl").write_bytes(data)
    (root / "duplicate-envelope.json").write_bytes(envelope)
    store = Store(fixture["database"])
    try:
        admitted = ingest_signed(store, data, envelope, observed_at="2026-11-15T09:00:00Z")
        if admitted["status"] != "COMPLETE":
            raise ValueError("EXECUTION_DEMO_ADMISSION: second physical delivery failed")
        activated = activate_policy(store, fixture["rotated_policy"], expected_epoch=1,
                                    expected_hash=digest(fixture["initial_policy"]), observed_at="2026-11-15T09:01:00Z")
    finally:
        store.close()
    _write(root / "changes.json", {"operation_kind": "real_existing_admission_and_policy_APIs",
                                   "received_at_note": "Same original envelope/time; newly observed physical delivery after E1.",
                                   "admission": admitted, "policy_activation": activated,
                                   "policy_epoch": 2, "new_policy": fixture["rotated_policy"]})


def _guide(root, summary):
    lines = ["# Recorded execution demonstration", "", "Profile: `" + summary["profile"] + "`. Result: **" + summary["status"] + "**.", "",
             "Each case names its actual CLI command, exit, output and independent checks in summary.json and commands/.",
             "A recorded input/admission context does not assert actor authorization, fresh signature verification or financial correctness.", "",
             "| Case | Expected exit/status | Actual exit/status | Passed |", "|---|---|---|---|"]
    for case in summary["cases"]:
        lines.append("| {} | {} / {} | {} / {} | {} |".format(case["id"], case["expected"]["exit_code"], case["expected"]["status"],
                     case["actual"]["exit_code"], case["actual"]["status"], case["passed"]))
    lines += ["", "Open exports/legacy/summary.md and its exact context.json/run.json bytes. An ordinary saved run first returns NOT_RECORDED; its later explicitly requested execution is a separate observation.",
              "A repeated request returns its original execution. A new request may share the financial run ID and still receives another execution/context. Run-only lookup lists all execution IDs."]
    if summary["profile"] == "protected":
        lines += ["", "Protected E1 records 30 physical receipts and policy head 1. A new same-hash delivery and policy revocation then occur. The ACK retry still returns E1; E2 records 31 receipts and head 2, preserving both physical candidates and their original epoch-1 admissions.",
                  "The separately signed mismatch keeps customer liability 11 and reported custody 10: COMPLETE/MISMATCH, difference +1. Admission does not change that result."]
    lines += ["", "No UI, independent cryptographic verifier, full financial replay, frozen experiment, process-crash or race experiment runs in this small demo. Those process guarantees have separate focused test evidence."]
    (root / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_demo(output, *, profile="protected"):
    """Run the finite literal-reference CLI examples, retaining every actual call."""
    if profile not in ("legacy", "protected"):
        raise ValueError("EXECUTION_DEMO_PROFILE: use legacy or protected")
    if profile == "protected":
        from ..source_auth.crypto import require_auth
        require_auth()  # Refuse before creating output in a core-only installation.
    import crypto_reconciliation_lab as package
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    summary = {"format": "execution-context-demo-v1", "status": "RUNNING", "profile": profile,
               "schema_version": 6, "rule_version": "stage2-v2",
               "environment": {"import_origin": package.__file__, "executable": sys.executable,
                               "python": sys.version, "isolated": bool(sys.flags.isolated)},
               "case_inventory": list(LEGACY_CASES + (PROTECTED_CASES if profile == "protected" else ())),
               "cases": [], "process_crash_race_experiments": "NOT_RUN", "frozen_experiment": "NOT_RUN"}
    _write(root / "summary.json", summary)
    def call(name, arguments, code=0, status="RECORDED", reason=None):
        result, row = _cli(root, name, arguments, code, status, reason)
        summary["cases"].append(row)
        return result, row
    def recorded(database, request, knowledge=KNOWLEDGE_AT):
        return ["reconcile-recorded", "--db", database, "--balance-at", BALANCE_AT,
                "--knowledge-at", knowledge, "--request-id", request]
    def show(database, execution):
        return ["show-execution", "--db", database, "--execution-id", execution]
    try:
        legacy = build_fixture(root / "legacy-inputs")
        db = legacy["database"]
        ordinary, setup = _cli(root, "ordinary_run_setup", ["reconcile", "--db", db,
            "--balance-at", BALANCE_AT, "--knowledge-at", KNOWLEDGE_AT, "--output", root / "ordinary-run"], 0, json_output=False)
        summary["setup_command"] = setup["command"]
        old, row = call("legacy_unrecorded", ["show-execution", "--db", db, "--run-id", ordinary], status="NOT_RECORDED")
        _check(row, "execution_inventory", [], old["execution_ids"])
        _financial(row, old)
        first, row = call("legacy_recorded", recorded(db, "legacy-first"))
        _check(row, "reused_financial_run", ordinary, first["run_id"])
        _check(row, "new_execution", False, first["replayed"])
        _context(row, first); _financial(row, first)
        retry, row = call("legacy_retry", recorded(db, "legacy-first"))
        _check(row, "retry_identity", first["execution_id"], retry["execution_id"])
        _check(row, "retry_context", _identity(canonical(first["context"])), _identity(canonical(retry["context"])))
        _check(row, "replayed", True, retry["replayed"])
        call("legacy_conflict", recorded(db, "legacy-first", "2026-11-13T02:00:00Z"), 2, "ERROR", "EXECUTION_REQUEST_CONFLICT")
        second, row = call("legacy_new_request", recorded(db, "legacy-second"))
        _check(row, "same_financial_run", first["run_id"], second["run_id"])
        _check(row, "different_execution", True, first["execution_id"] != second["execution_id"])
        _check(row, "different_context", True, first["context_hash"] != second["context_hash"])
        _context(row, second); _financial(row, second)
        multiple, row = call("legacy_multiple", ["show-execution", "--db", db, "--run-id", ordinary], status="MULTIPLE_EXECUTIONS")
        _check(row, "all_execution_ids", sorted([first["execution_id"], second["execution_id"]]), multiple["execution_ids"])
        before = _identity(db.read_bytes())
        saved, row = call("legacy_show", show(db, first["execution_id"]))
        _check(row, "saved_context_unchanged", _identity(canonical(first["context"])), _identity(canonical(saved["context"])))
        _check(row, "readonly_database_bytes", before, _identity(db.read_bytes()))
        target = root / "exports" / "legacy"
        _, row = call("legacy_export", ["export-execution", "--db", db, "--execution-id", first["execution_id"], "--output", target], status="EXPORTED")
        _export_checks(row, db, first["execution_id"], target)
        exported = {p.name: _identity(p.read_bytes()) for p in target.iterdir()}
        _, row = call("legacy_export_existing", ["export-execution", "--db", db, "--execution-id", first["execution_id"], "--output", target], 2, "ERROR", "EXECUTION_OUTPUT")
        _check(row, "existing_export_preserved", exported, {p.name: _identity(p.read_bytes()) for p in target.iterdir()})
        if profile == "protected":
            protected = build_fixture(root / "protected-inputs", protected=True)
            db = protected["database"]
            e1, row = call("protected_recorded", recorded(db, "protected-first"))
            _context(row, e1, protected=True, epoch=1); _financial(row, e1)
            _advance_protected(protected, root / "protected-inputs")
            retry, row = call("protected_retry_after_change", recorded(db, "protected-first"))
            _check(row, "original_execution", e1["execution_id"], retry["execution_id"])
            _check(row, "original_context", _identity(canonical(e1["context"])), _identity(canonical(retry["context"])))
            _check(row, "replayed", True, retry["replayed"])
            _context(row, retry, protected=True, epoch=1)
            e2, row = call("protected_new_request", recorded(db, "protected-second"))
            _check(row, "same_financial_run", e1["run_id"], e2["run_id"])
            _check(row, "different_execution", True, e1["execution_id"] != e2["execution_id"])
            _context(row, e2, protected=True, receipts=31, epoch=2); _financial(row, e2)
            duplicate_hash = hashlib.sha256(canonical(next(x for x in protected["records_by_source"][CUSTODIAN]
                if x["record"]["kind"] == "report" and x["record"]["asset"] == "ASSET_A"))).hexdigest()
            candidates = [r["id"] for r in e2["context"]["tables"]["receipts"] if r["receipt_hash"] == duplicate_hash]
            _check(row, "two_distinct_physical_candidates", 2, len(set(candidates)))
            _check(row, "both_selected_candidates", sorted(candidates), e2["context"]["selected_evidence"][duplicate_hash]["receipt_ids"])
            preserved, row = call("protected_original_readback", show(db, e1["execution_id"]))
            _check(row, "original_context_after_policy_change", _identity(canonical(e1["context"])), _identity(canonical(preserved["context"])))
            _context(row, preserved, protected=True, epoch=1)
            multiple, row = call("protected_multiple", ["show-execution", "--db", db, "--run-id", e1["run_id"]], status="MULTIPLE_EXECUTIONS")
            _check(row, "all_execution_ids", sorted([e1["execution_id"], e2["execution_id"]]), multiple["execution_ids"])
            target = root / "exports" / "protected-original"
            _, row = call("protected_export", ["export-execution", "--db", db, "--execution-id", e1["execution_id"], "--output", target], status="EXPORTED")
            _export_checks(row, db, e1["execution_id"], target)
            wrong = build_fixture(root / "mismatch-inputs", protected=True, mismatch=True)
            mismatch, row = call("signed_mismatch", recorded(wrong["database"], "signed-mismatch"), 1)
            _context(row, mismatch, protected=True, epoch=1); _financial(row, mismatch, mismatch=True)
            mismatch_read, row = call("signed_mismatch_show", show(wrong["database"], mismatch["execution_id"]))
            _financial(row, mismatch_read, mismatch=True)
        if [row["id"] for row in summary["cases"]] != summary["case_inventory"] or not all(row["passed"] for row in summary["cases"]):
            raise ValueError("EXECUTION_DEMO_COVERAGE: incomplete case inventory")
        summary["status"] = "PASS"
    except Exception as exc:
        summary.update(status="FAILED", error=str(exc))
        _write(root / "summary.json", summary)
        _guide(root, summary)
        raise
    _write(root / "summary.json", summary)
    _guide(root, summary)
    return summary
