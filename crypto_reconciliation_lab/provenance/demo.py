"""Small TEST-ONLY operator fixtures and literal provenance review controls.

The fixture operator owns and observes its newly created closed database. This is
not an expectations generator for arbitrary untrusted bundles. The independent
verifier never imports this module or uses the scenario labels as evidence.
"""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

PLATFORM = "LARK_EXCHANGE"
CUSTODIAN = "ORBIT_VAULT"
RECEIVER = "TEST-ONLY:review-node"
OPENING = "2026-11-12T00:00:00.000000Z"
BALANCE = "2026-11-12T23:59:59.000000Z"
KNOWLEDGE = "2026-11-13T01:00:00.000000Z"
LATER = "2026-11-13T03:00:00.000000Z"
INVALID_AT = "2026-11-13T04:00:00.000000Z"
CONFIG = {"platform": PLATFORM, "custodian": CUSTODIAN,
          "investors": ["Aster", "Birch"], "assets": {"TOKEN_X": 8, "TOKEN_Y": 2},
          "opening_at": OPENING}
# Public demonstration seeds, deliberately unrelated to the fixed seed-19 demo.
# These literals are public test material, never institution or customer keys.
TEST_SEEDS = {"lark-original": b"1" * 32, "lark-next": b"2" * 32,
              "orbit-original": b"3" * 32, "orbit-next": b"4" * 32}
KEY_SOURCES = {"lark-original": PLATFORM, "lark-next": PLATFORM,
               "orbit-original": CUSTODIAN, "orbit-next": CUSTODIAN}
NAMESPACES = {PLATFORM: "lark-feed:", CUSTODIAN: "orbit-feed:"}
REFERENCE = {
    "TOKEN_X": {"investors": {"Aster": "7", "Birch": "4"}, "liability": "11",
                "custody": {"platform": "2", "external": "9"}},
    "TOKEN_Y": {"investors": {"Aster": "0.3", "Birch": "0.2"}, "liability": "0.5",
                "custody": {"platform": "0.05", "external": "0.45"}},
}
CORRECTED_REFERENCE = {
    "TOKEN_X": {"investors": {"Aster": "8", "Birch": "4"}, "liability": "12",
                "custody": {"platform": "2", "external": "10"}},
    "TOKEN_Y": {"investors": {"Aster": "0.3", "Birch": "0.2"}, "liability": "0.5",
                "custody": {"platform": "0.05", "external": "0.45"}},
}
HOSTILE_TEXT = '<img src="https://invalid.example/never" onerror="window.PROVENANCE_XSS=1"> & </script>'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value) + b"\n")


def financial_records(wrong_custody=False):
    """Hand-authored records; none of the expected quantities uses the engine."""
    feeds = {PLATFORM: [], CUSTODIAN: []}
    def add(kind, asset, source=PLATFORM, received=KNOWLEDGE, **fields):
        feeds[source].append({"record": {"kind": kind, "asset": asset, "source": source,
                                         "platform": PLATFORM, **fields}, "received_at": received})
    for asset, amounts in (("TOKEN_X", ("6", "4", "2", "8")),
                           ("TOKEN_Y", ("0.10", "0.20", "0.05", "0.25"))):
        for scope, amount in zip(("Aster", "Birch", "platform", "external"), amounts):
            add("opening", asset, received=OPENING, scope=scope, balance_at=OPENING, amount=amount)
    events = (("TOKEN_X", "X-transfer", "transfer", "Aster", "Birch", None, "1", 1),
              ("TOKEN_X", "X-deposit", "deposit", None, "Aster", "external", "2", 2),
              ("TOKEN_X", "X-withdrawal", "withdrawal", "Birch", None, "external", "1", 3),
              ("TOKEN_Y", "Y-deposit", "deposit", None, "Aster", "external", "0.20", 2))
    for asset, ref, kind, sender, recipient, custody, amount, hour in events:
        when = f"2026-11-12T{hour:02d}:00:00.000000Z"
        add("event", asset, received=when, business_day="2026-11-12", ref=ref,
            occurred_at=when, sequence=1, type=kind, from_investor=sender,
            to_investor=recipient, custody=custody, amount=amount)
    for asset in ("TOKEN_X", "TOKEN_Y"):
        spec = REFERENCE[asset]
        for stream, scope, amount in (("investor", "Aster", spec["investors"]["Aster"]),
                                      ("investor", "Birch", spec["investors"]["Birch"]),
                                      ("platform_custody", "platform", spec["custody"]["platform"]),
                                      ("external_custody", "external", "8" if wrong_custody and asset == "TOKEN_X" else spec["custody"]["external"])):
            add("report", asset, CUSTODIAN if stream == "external_custody" else PLATFORM,
                stream=stream, scope=scope, balance_at=BALANCE, version=1, amount=amount)
        for stream, count in (("opening", 4), ("event", 3 if asset == "TOKEN_X" else 1),
                               ("investor", 2), ("platform_custody", 1), ("external_custody", 1)):
            add("manifest", asset, CUSTODIAN if stream == "external_custody" else PLATFORM,
                stream=stream, coverage_from=OPENING if stream in ("opening", "event") else BALANCE,
                coverage_to=OPENING if stream == "opening" else BALANCE, expected_count=count)
    return feeds


def policy(epoch=1):
    from ..model import digest
    from ..source_auth.crypto import public_key, fingerprint
    from ..source_auth.policy import validate_policy
    grants = {PLATFORM: [], CUSTODIAN: []}
    for asset in ("TOKEN_X", "TOKEN_Y"):
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
    names = ["lark-original", "orbit-original"]
    if epoch >= 2:
        names.append("lark-next")
    if epoch >= 4:
        names.append("orbit-next")
    keys = []
    for name in names:
        key = public_key(TEST_SEEDS[name])
        revoked = (epoch >= 3 and name == "lark-original") or (epoch >= 4 and name == "orbit-original")
        keys.append({"key_id": name, "source": KEY_SOURCES[name], "public_key": key.hex(),
                     "fingerprint": fingerprint(key), "status": "revoked" if revoked else "active"})
    value = {"format": "source-auth-policy-v1", "receiver": RECEIVER,
             "configuration_digest": digest(CONFIG),
             "sources": [{"source": name, "namespace": NAMESPACES[name], "capabilities": grants[name]}
                         for name in (PLATFORM, CUSTODIAN)], "keys": keys}
    return validate_policy(value, CONFIG, RECEIVER)


def snapshot(records):
    return b"".join(canonical(row) + b"\n" for row in records)


def signed(data, stream, key):
    from ..model import digest
    from ..source_auth.scope import snapshot_bytes, capabilities
    from ..source_auth.crypto import sign_statement
    snap = snapshot_bytes(data)
    statement = {"format": "source-admission-statement-v1", "source": KEY_SOURCES[key],
                 "receiver": RECEIVER, "configuration_digest": digest(CONFIG), "stream_id": stream,
                 "plan": snap.plan, "capabilities": capabilities(snap, CONFIG)}
    return sign_statement(statement, TEST_SEEDS[key], key)


def _check_financial(result, reference, *, custody_difference=False, incomplete_asset=None):
    """Compare actual fields with independent quantity/state literals."""
    checks = []
    for asset, literal in reference.items():
        ledger = result["ledgers"][asset]
        for key, wanted in (("investor_balances", literal["investors"]), ("liability", literal["liability"]),
                            ("custody_rollforward", literal["custody"])):
            checks.append({"field": asset + "." + key, "expected": wanted, "actual": ledger[key],
                           "passed": ledger[key] == wanted})
    for finding in result["findings"]:
        affected = finding["asset"] == incomplete_asset
        mismatch = custody_difference and finding["asset"] == "TOKEN_X" and finding["comparison"] == "B"
        expected = {"data_state": "INCOMPLETE" if affected else "COMPLETE",
                    "reconciliation_state": "NOT_EVALUATED" if affected else "MISMATCH" if mismatch else "MATCHED",
                    "difference": "1" if mismatch else "0"}
        actual = {key: finding[key] for key in expected}
        checks.append({"field": finding["asset"] + "/" + finding["comparison"] + "/" + finding["scope"],
                       "expected": expected, "actual": actual, "passed": actual == expected})
    if not all(item["passed"] for item in checks):
        raise ValueError("PROVENANCE_DEMO_REFERENCE: independent literal financial reference differs: " + json.dumps(checks))
    return checks


def _fixture_observation(database, run_id, expected_policies, *, legacy):
    """TEST-ONLY operator observation, independently read before any export.

    This bounded fixture-specific SQL reader does not import the exporter, its
    scope builder or the verifier. It pins this operator's own constructed source.
    It is not exposed as an arbitrary-bundle trust-generation CLI.
    """
    database = Path(database)
    before = database.read_bytes()
    db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    def encode(row):
        return {key: value.hex() if isinstance(value, bytes) else value for key, value in dict(row).items()}
    def all_rows(table, order):
        return [encode(row) for row in db.execute("SELECT * FROM " + table + " ORDER BY " + order)]
    try:
        db.execute("BEGIN")
        raw = db.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()[0].encode("utf-8")
        run = json.loads(raw)
        config = json.loads(db.execute("SELECT payload FROM configuration WHERE id=1").fetchone()[0])
        record_ids, receipt_hashes = set(), set()
        for eid, item in run["evidence"].items():
            if "record" in item:
                record_ids.add(eid)
                receipt_hashes.update(item["receipt_ids"])
            elif "receipt" in item or "quarantined_receipt" in item:
                receipt_hashes.add(eid)
        receipts = [row for row in all_rows("receipts", "id") if row["receipt_hash"] in receipt_hashes]
        physical = {row["id"] for row in receipts}
        effects = [row for row in all_rows("delivery_effects", "stream_id,sequence") if row["core_receipt_id"] in physical]
        positions = {(row["stream_id"], row["sequence"]) for row in effects}
        streams = {row["stream_id"] for row in effects}
        attempts = [row for row in all_rows("delivery_attempts", "id") if (row["stream_id"], row["sequence"]) in positions]
        attempt_ids = {row["id"] for row in attempts}
        original_links = [row for row in all_rows("auth_delivery_links", "stream_id,sequence") if (row["stream_id"], row["sequence"]) in positions]
        attempt_links = [row for row in all_rows("auth_attempt_links", "attempt_id") if row["attempt_id"] in attempt_ids]
        decisions_ids = {row["decision_id"] for row in original_links + attempt_links}
        decisions = [row for row in all_rows("auth_decisions", "id") if row["id"] in decisions_ids]
        endorsement_ids = {row["endorsement_id"] for row in decisions}
        activations = all_rows("auth_policy_activations", "epoch")
        actual_policies = [{"epoch": row["epoch"], "policy_hash": row["policy_hash"]} for row in activations]
        if actual_policies != expected_policies:
            raise ValueError("PROVENANCE_DEMO_POLICY: operator's known activation map differs")
        active_hashes = {row["policy_hash"] for row in activations}
        tables = {
            "receipts": receipts,
            "records": [row for row in all_rows("records", "id") if row["id"] in record_ids],
            "admission_streams": [row for row in all_rows("admission_streams", "stream_id") if row["stream_id"] in streams],
            "delivery_effects": effects, "delivery_attempts": attempts,
            "auth_configuration": all_rows("auth_configuration", "id"),
            "auth_policy_activations": activations,
            "auth_policy_snapshots": [row for row in all_rows("auth_policy_snapshots", "policy_hash") if row["policy_hash"] in active_hashes],
            "auth_keys": all_rows("auth_keys", "key_id"),
            "auth_streams": [row for row in all_rows("auth_streams", "stream_id") if row["stream_id"] in streams],
            "auth_delivery_links": original_links, "auth_attempt_links": attempt_links,
            "auth_decisions": decisions,
            "auth_endorsements": [row for row in all_rows("auth_endorsements", "id") if row["id"] in endorsement_ids],
        }
        capture = {"format": "run-provenance-capture-v1", "schema_version": 5,
                   "database": {"bytes": len(before), "sha256": sha(before)},
                   "configuration": config, "tables": tables}
        db.rollback()
    finally:
        db.close()
    if database.read_bytes() != before:
        raise ValueError("PROVENANCE_DEMO_CAPTURE: closed fixture changed while observed")
    expectations = {"format": "provenance-expectations-v1", "profile": "legacy" if legacy else "protected",
                    "run_id": run_id, "run_payload_sha256": sha(raw), "configuration_digest": sha(canonical(config)),
                    "capture_digest": sha(canonical(capture)), "receiver": None if legacy else RECEIVER,
                    "policy_head": expected_policies[-1] if expected_policies else None,
                    "policies": expected_policies}
    return expectations, capture


def build_fixture(root, *, scenario="clean"):
    """Create one small closed fixture and explicit external TEST-ONLY trust.

    Returned Paths name the database/materials/expectations. No bundle is read to
    decide what to trust. All construction uses existing financial/auth APIs.
    """
    from ..source_auth.crypto import require_auth
    require_auth()  # Before even creating the output directory in core mode.
    from ..source_auth.runtime import enable_protection, activate_policy, ingest_signed
    from ..engine import reconcile
    from ..store import Store
    allowed = {"clean", "custody_difference", "history", "correction", "quarantine", "rotation",
               "replay", "ambiguous", "missing_snapshot", "prefix_only", "legacy"}
    if scenario not in allowed:
        raise ValueError("unknown small provenance fixture")
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    materials = root / "source-materials"
    (materials / "snapshots").mkdir(parents=True)
    database = root / "capture.sqlite3"
    legacy = scenario == "legacy"
    store = Store(database, CONFIG)
    policy_map, operations, runs, references, preserved = [], [], {}, {}, {}
    feeds = financial_records(scenario == "custody_difference")
    initial_data = {}
    def admit(records, source, suffix, key=None, max_lines=None):
        data = snapshot(records)
        (materials / "snapshots" / (sha(data) + ".jsonl")).write_bytes(data)
        stream = NAMESPACES[source] + suffix
        if legacy:
            result = [store.ingest(row["record"], row["received_at"]) for row in records]
        else:
            key = key or ("lark-original" if source == PLATFORM else "orbit-original")
            envelope = signed(data, stream, key)
            hour = 12 if len(policy_map) > 1 else 10
            result = ingest_signed(store, data, envelope, max_lines=max_lines,
                                   observed_at=f"2026-11-14T{hour}:{len(operations):02d}:00.000000Z")
            if result["status"] not in ("COMPLETE", "INCOMPLETE"):
                raise ValueError("PROVENANCE_DEMO_ADMISSION: " + json.dumps(result))
        operations.append({"source": source, "stream_id": stream, "snapshot_sha256": sha(data), "result": result})
        return data
    def save(phase, knowledge, reference, *, wrong=False, incomplete_asset=None):
        actual = reconcile(store, BALANCE, knowledge)
        references[phase] = _check_financial(actual, reference, custody_difference=wrong, incomplete_asset=incomplete_asset)
        runs[phase] = actual["run_id"]
        preserved[phase] = store.db.execute("SELECT payload FROM runs WHERE id=?", (actual["run_id"],)).fetchone()[0].encode("utf-8")
        return actual
    try:
        if not legacy:
            first = policy(1)
            enable_protection(store, RECEIVER, first, observed_at="2026-11-14T09:00:00Z")
            policy_map.append({"epoch": 1, "policy_hash": sha(canonical(first))})
        for source in (PLATFORM, CUSTODIAN):
            initial_data[source] = admit(feeds[source], source, "financial",
                                         max_lines=5 if scenario == "prefix_only" and source == PLATFORM else None)
        if scenario == "prefix_only":
            actual = reconcile(store, BALANCE, KNOWLEDGE)
            if any(row["data_state"] != "INCOMPLETE" or row["reconciliation_state"] != "NOT_EVALUATED" for row in actual["findings"]):
                raise ValueError("PROVENANCE_DEMO_REFERENCE: prefix fixture must remain incomplete")
            runs["original"] = actual["run_id"]
            preserved["original"] = store.db.execute("SELECT payload FROM runs WHERE id=?", (actual["run_id"],)).fetchone()[0].encode()
            references["original"] = [{"expected": "INCOMPLETE/NOT_EVALUATED for every finding", "passed": True}]
        else:
            save("original", KNOWLEDGE, REFERENCE, wrong=scenario == "custody_difference")
        if scenario in ("history", "correction", "quarantine"):
            target = next(row["record"] for row in feeds[PLATFORM] if row["record"].get("ref") == "X-deposit")
            correction = {"kind": "correction", "source": PLATFORM, "platform": PLATFORM, "asset": "TOKEN_X",
                          "batch_id": "batch-adjustment", "correction_id": "fix-deposit",
                          "target": {key: target[key] for key in ("kind", "source", "platform", "business_day", "ref")},
                          "target_occurred_at": target["occurred_at"], "mode": "REPLACE", "replacement_amount": "3",
                          "source_ref": "review-note", "reason": "Synthetic amount correction. " + HOSTILE_TEXT}
            delivery = {"kind": "correction_manifest", "source": PLATFORM, "platform": PLATFORM,
                        "asset": "TOKEN_X", "batch_id": "batch-adjustment", "coverage_from": OPENING,
                        "coverage_to": BALANCE, "expected_count": 1}
            revised_i1 = copy.deepcopy(next(row["record"] for row in feeds[PLATFORM] if row["record"].get("stream") == "investor" and row["record"].get("scope") == "Aster" and row["record"]["asset"] == "TOKEN_X"))
            revised_i1.update(version=2, amount="8")
            revised_custody = copy.deepcopy(next(row["record"] for row in feeds[CUSTODIAN] if row["record"]["kind"] == "report" and row["record"]["asset"] == "TOKEN_X"))
            revised_custody.update(version=2, amount="10")
            admit([{"record": row, "received_at": LATER} for row in (correction, delivery, revised_i1)], PLATFORM, "correction")
            admit([{"record": revised_custody, "received_at": LATER}], CUSTODIAN, "revision")
            save("corrected", LATER, CORRECTED_REFERENCE)
            invalid = copy.deepcopy(target)
            # Keep the independent TOKEN_X correction case complete. The
            # established engine does not apply corrections to a tainted ledger.
            invalid.update(asset="TOKEN_Y", ref="invalid-amount", amount="NaN")
            admit([{"record": invalid, "received_at": INVALID_AT}], PLATFORM, "quarantine")
            save("quarantine", INVALID_AT, CORRECTED_REFERENCE, incomplete_asset="TOKEN_Y")
        if scenario == "rotation":
            for epoch in (2, 3, 4):
                value = policy(epoch)
                previous = policy_map[-1]
                activate_policy(store, value, previous["epoch"], previous["policy_hash"],
                                observed_at=f"2026-11-14T11:0{epoch}:00Z")
                policy_map.append({"epoch": epoch, "policy_hash": sha(canonical(value))})
            # The original receipt/effect remains; this is a new audit attempt.
            admit(feeds[PLATFORM], PLATFORM, "financial")
        if scenario == "replay":
            for source in (PLATFORM, CUSTODIAN):
                admit(feeds[source], source, "financial")
        if scenario == "ambiguous":
            duplicate = next(row for row in feeds[CUSTODIAN] if row["record"]["kind"] == "report" and row["record"]["asset"] == "TOKEN_X")
            # Deliberately AFTER saving the run. Same envelope -> same hash;
            # another physical delivery -> a second local receipt candidate.
            admit([copy.deepcopy(duplicate)], CUSTODIAN, "later-physical-candidate")
        for phase, original in preserved.items():
            current = store.db.execute("SELECT payload FROM runs WHERE id=?", (runs[phase],)).fetchone()[0].encode("utf-8")
            if current != original:
                raise ValueError("PROVENANCE_DEMO_HISTORY: an old saved run changed")
    finally:
        store.close()
    if scenario in ("missing_snapshot", "prefix_only"):
        raw = initial_data[PLATFORM]
        (materials / "snapshots" / (sha(raw) + ".jsonl")).unlink()
        # This file is explicitly not the full snapshot's content-addressed path.
        # Export must not invent the absent suffix or use it as a replacement.
        (materials / "observed-prefix-only.jsonl").write_bytes(b"".join(raw.splitlines(keepends=True)[:5]))
    paths = {}
    for phase, run_id in runs.items():
        expected, capture = _fixture_observation(database, run_id, policy_map, legacy=legacy)
        path = root / "expectations" / (phase + ".json")
        write_json(path, expected)
        write_json(root / "operator-observation" / (phase + ".json"), capture)
        paths[phase] = path
    phase = "quarantine" if scenario == "quarantine" else "corrected" if scenario in ("history", "correction") else "original"
    proof = {"format": "provenance-test-operator-v1", "trust_role": "TEST-ONLY_CONTROLLED_FIXTURE_OPERATOR",
             "not_a_general_bundle_trust_generator": True, "scenario": scenario,
             "configuration": CONFIG, "known_policy_epochs": policy_map, "runs": runs,
             "saved_payload_sha256": {key: sha(value) for key, value in preserved.items()},
             "financial_literal_checks": references, "operations": operations,
             "run_creation_authorization_cut": "NOT_RECORDED",
             "operation_order_note": "The ambiguous fixture adds its second physical delivery after save_run in this producer; the verifier must not infer a run-creation cut from that later capture."}
    write_json(root / "fixture-proof.json", proof)
    return {"database": database, "run_id": runs[phase], "material_dir": materials,
            "expectations": paths[phase], "expectations_by_phase": paths, "runs": runs,
            "literal_reference": CORRECTED_REFERENCE if phase != "original" else REFERENCE,
            "proof": root / "fixture-proof.json"}


GROUPS = (
    ("clean_two_publishers", ("clean",)),
    ("signed_custody_difference", ("signed_mismatch",)),
    ("historical_correction_quarantine", ("history_original", "history_corrected", "history_quarantine")),
    ("rotation_and_revocation", ("rotation",)),
    ("exact_replay", ("replay",)),
    ("multiple_physical_candidates", ("ambiguous",)),
    ("missing_full_snapshot", ("missing_snapshot", "prefix_only")),
    ("legacy_and_protected", ("legacy", "broken_protected_link", "protected_downgrade")),
    ("external_expectations", ("wrong_run", "wrong_capture", "wrong_policy", "hidden_policy_head")),
    ("semantic_relations", ("removed_receipt", "changed_receipt", "removed_quarantine", "removed_correction",
                             "changed_effect", "changed_endorsement", "broken_link_and_missing_snapshot")),
)
CASE_REASONS = {
    "ambiguous": (3, "MULTIPLE_RECEIPT_CANDIDATES"),
    "missing_snapshot": (3, "MISSING_SIGNED_SNAPSHOT"), "prefix_only": (3, "MISSING_SIGNED_SNAPSHOT"),
    "legacy": (3, "UNSIGNED_LEGACY"), "broken_protected_link": (2, "PROTECTED_LINK"),
    "protected_downgrade": (2, "PROFILE_MISMATCH"), "wrong_run": (2, "RUN_IDENTITY"),
    "wrong_capture": (2, "CAPTURE_BINDING"), "wrong_policy": (2, "POLICY_BINDING"),
    "hidden_policy_head": (2, "POLICY_BINDING"), "removed_receipt": (2, "EVIDENCE_SCOPE"),
    "changed_receipt": (2, "RECEIPT_BINDING"), "removed_quarantine": (2, "EVIDENCE_SCOPE"),
    "removed_correction": (2, "EVIDENCE_SCOPE"), "changed_effect": (2, "DELIVERY_RELATION"),
    "changed_endorsement": (2, "ENDORSEMENT_BINDING"),
    "broken_link_and_missing_snapshot": (2, "PROTECTED_LINK"),
}


def _rehash_controlled_mutation(bundle, capture, *, expectations=None):
    """Coherent test candidate; not a general operator-trust generator."""
    from .ui import render_page
    bundle = Path(bundle)
    run = json.loads((bundle / "run.json").read_bytes())
    report = json.loads((bundle / "report.json").read_bytes())
    report["capture_digest"] = sha(canonical(capture))
    (bundle / "capture.json").write_bytes(canonical(capture))
    (bundle / "report.json").write_bytes(canonical(report))
    materials = {}
    for path in sorted((bundle / "materials").rglob("*")):
        if path.is_file():
            raw = path.read_bytes()
            materials[path.relative_to(bundle).as_posix()] = {"bytes": len(raw), "sha256": sha(raw)}
    for name, raw in render_page(run, report, capture, materials).items():
        (bundle / name).write_bytes(raw)
    manifest = json.loads((bundle / "manifest.json").read_bytes())
    manifest["files"] = {}
    for path in sorted(bundle.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            raw = path.read_bytes()
            manifest["files"][path.relative_to(bundle).as_posix()] = {"bytes": len(raw), "sha256": sha(raw)}
    write_json(bundle / "manifest.json", manifest)
    if expectations is not None:
        expectations["capture_digest"] = sha(canonical(capture))


def _mutate_case(case_id, bundle, expectations):
    """Independent finite counterexamples with fixed semantic expectations."""
    capture = json.loads((bundle / "capture.json").read_bytes())
    original_pin = expectations["capture_digest"]
    tables = capture["tables"]
    repin = True
    if case_id == "wrong_run":
        expectations["run_id"] = "0" * 64
        repin = False
    elif case_id == "wrong_capture":
        expectations["capture_digest"] = "0" * 64
        repin = False
    elif case_id == "wrong_policy":
        expectations["policies"][0]["policy_hash"] = "0" * 64
        if expectations["policy_head"]["epoch"] == 1:
            expectations["policy_head"]["policy_hash"] = "0" * 64
        repin = False
    elif case_id in ("broken_protected_link", "broken_link_and_missing_snapshot"):
        tables["auth_delivery_links"].pop(0)
        if case_id == "broken_link_and_missing_snapshot":
            next((bundle / "materials" / "snapshots").glob("*.jsonl")).unlink()
    elif case_id == "protected_downgrade":
        tables["auth_configuration"] = []
    elif case_id == "hidden_policy_head":
        tables["auth_policy_activations"].pop()
    elif case_id == "removed_receipt":
        tables["receipts"].pop(0)
    elif case_id == "changed_receipt":
        raw = json.loads(tables["receipts"][0]["raw"])
        raw["record"]["amount"] = "999"
        tables["receipts"][0]["raw"] = canonical(raw).decode("ascii")
    elif case_id == "removed_quarantine":
        tables["receipts"] = [row for row in tables["receipts"] if row["error"] is None]
    elif case_id == "removed_correction":
        tables["records"] = [row for row in tables["records"] if row["kind"] != "correction"]
    elif case_id == "changed_effect":
        tables["delivery_effects"][0]["core_receipt_id"] = tables["delivery_effects"][1]["core_receipt_id"]
    elif case_id == "changed_endorsement":
        tables["auth_endorsements"][0]["key_id"] = "nonexistent-key"
    else:
        raise ValueError("unknown controlled provenance mutation")
    if repin:
        _rehash_controlled_mutation(bundle, capture, expectations=expectations)
    return {"fixture_mutation": case_id, "original_capture_digest": original_pin,
            "test_controlled_capture_pin": expectations["capture_digest"],
            "capture_repin": repin,
            "meaning": "Explicit TEST-ONLY operator observation override exercises semantic links; it is not a claim that an attacker can alter a real operator's trust input."}


def _verify_case_cli(root, case_id, group_id):
    case = root / "cases" / case_id
    commands = case / "commands" / "verify"
    commands.mkdir(parents=True)
    argv = [sys.executable, "-B"] + (["-I"] if sys.flags.isolated else []) + [
        "-m", "crypto_reconciliation_lab", "verify-provenance", "--bundle", str(case / "bundle"),
        "--expectations", str(case / "expectations.json")]
    started = time.perf_counter()
    completed = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    elapsed = time.perf_counter() - started
    (commands / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (commands / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
    record = {"argv": argv, "cwd": str(Path.cwd()), "exit_code": completed.returncode,
              "elapsed_seconds": elapsed,
              "stdout": (commands / "stdout.txt").relative_to(root).as_posix(),
              "stderr": (commands / "stderr.txt").relative_to(root).as_posix(),
              "stdout_sha256": sha(completed.stdout.encode("utf-8")),
              "stderr_sha256": sha(completed.stderr.encode("utf-8"))}
    write_json(commands / "command.json", record)
    try:
        verification = json.loads(completed.stdout)
    except (ValueError, TypeError):
        verification = {"status": "CLI_OUTPUT_INVALID", "exit_code": completed.returncode,
                        "reasons": [{"code": "CLI_OUTPUT_INVALID", "message": completed.stderr}]}
    write_json(case / "verification.json", verification)
    wanted_exit, reason = CASE_REASONS.get(case_id, (0, None))
    expected = {"exit_code": wanted_exit,
                "status": {0: "VERIFIED_FOR_CAPTURE", 3: "PARTIAL", 2: "FAILED"}[wanted_exit],
                "reasons": [reason] if reason else []}
    actual = {"exit_code": completed.returncode, "status": verification.get("status"),
              "reasons": sorted({item.get("code") for item in verification.get("reasons", [])})}
    raw_run = json.loads((case / "bundle" / "run.json").read_bytes())
    financial = {"findings": [{key: row[key] for key in ("asset", "comparison", "scope", "expected", "reported",
                                                          "difference", "data_state", "reconciliation_state")}
                              for row in raw_run["findings"]]}
    passed = actual == expected and verification.get("exit_code") == completed.returncode
    if wanted_exit in (0, 3):
        passed = passed and verification.get("run_creation_authorization_cut") == "NOT_RECORDED"
        passed = passed and verification.get("financial_recomputation") == "NOT_PERFORMED"
    return {"id": case_id, "group_id": group_id,
            "bundle": (case / "bundle").relative_to(root).as_posix(),
            "expectations": (case / "expectations.json").relative_to(root).as_posix(),
            "verification": (case / "verification.json").relative_to(root).as_posix(),
            "command": (commands / "command.json").relative_to(root).as_posix(),
            "expected": expected, "actual": actual, "passed": bool(passed), "financial": financial}


def _write_demo_guide(root, summary):
    lines = ["# Five-minute saved-run provenance review", "",
             "This is a finite synthetic, TEST-ONLY operator demonstration. It is not a production identity or compliance claim.", "",
             "1. Open `cases/signed_mismatch/bundle/index.html` directly. TOKEN_X customer liability is 11, reported custody is 2 + 8 = 10 and the saved difference is +1. The separate verifier still accepts its source relationship; a signature does not establish the correct financial quantity.",
             "2. Open the external custody report, follow its recorded receipt, select the physical candidate and inspect its original acceptance, policy, signature and exact source line. Download the line or the full signed snapshot. The page itself remains CREATED / NOT_PERFORMED.",
             "3. Compare `history_original`, `history_corrected` and `history_quarantine`. The correction changes TOKEN_X to 8 / 4 / 12 and a later signed invalid TOKEN_Y amount remains quarantined. Old run bytes are unchanged. Inspect the correction reason as harmless text.",
             "4. Open `rotation` to compare original epoch 1 with capture head epoch 4 and revoked old keys. Open `ambiguous` to see both physical rows; neither becomes a proven run-creation origin. Open `missing_snapshot`, `prefix_only` and `legacy` for their separate incomplete-source boundaries.",
             "5. Run `crypto-reconciliation-lab verify-provenance --bundle cases/clean/bundle --expectations cases/clean/expectations.json` from this directory. The expectations are a deliberately explicit TEST-ONLY observation of this producer's own closed database. They are not automatically trusted because a bundle supplied them.", "",
             "The verifier does not need source DBs or network. All real per-case CLI calls, exits and reason codes are recorded in each case's commands/verify directory and verification.json. The page does not load or modify those external verification records.", "",
             "`NOT_RECORDED` is a permanent limit on the run-creation authorization cut; `NOT_PERFORMED` applies to financial recomputation.", "",
             "| Case | Expected exit / status | Actual exit / status | Reason | Passed |", "|---|---|---|---|---|"]
    for row in summary["cases"]:
        lines.append(f"| {row['id']} | {row['expected']['exit_code']} / {row['expected']['status']} | {row['actual']['exit_code']} / {row['actual']['status']} | {', '.join(row['actual']['reasons']) or 'none'} | {row['passed']} |")
    text = "\n".join(lines) + "\n"
    (root / "five-minute-review.md").write_text(text, encoding="utf-8")
    (root / "summary.md").write_text(text, encoding="utf-8")


def run_demo(output):
    """Produce ten finite groups and their real isolated/source CLI outcomes."""
    from ..source_auth.crypto import require_auth
    require_auth()
    from .. import __file__ as package_origin
    from .exporter import export_provenance
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    summary = {"format": "provenance-demo-v1", "status": "RUNNING",
               "environment": {"import_origin": package_origin, "python": sys.version,
                               "executable": sys.executable, "isolated": bool(sys.flags.isolated), "cwd": str(Path.cwd())},
               "trust_role": "TEST-ONLY_CONTROLLED_FIXTURE_OPERATOR",
               "run_creation_authorization_cut": "NOT_RECORDED", "financial_recomputation": "NOT_PERFORMED",
               "scenario_groups": [], "cases": []}
    write_json(root / "summary.json", summary)
    try:
        fixtures = {name: build_fixture(root / "fixtures" / name, scenario=name)
                    for name in ("clean", "custody_difference", "history", "rotation", "replay", "ambiguous",
                                 "missing_snapshot", "prefix_only", "legacy")}
        positives = {"clean": ("clean", "original"), "signed_mismatch": ("custody_difference", "original"),
                     "history_original": ("history", "original"), "history_corrected": ("history", "corrected"),
                     "history_quarantine": ("history", "quarantine"), "rotation": ("rotation", "original"),
                     "replay": ("replay", "original"), "ambiguous": ("ambiguous", "original"),
                     "missing_snapshot": ("missing_snapshot", "original"), "prefix_only": ("prefix_only", "original"),
                     "legacy": ("legacy", "original")}
        for case_id, (fixture_name, phase) in positives.items():
            source = fixtures[fixture_name]
            case = root / "cases" / case_id
            case.mkdir(parents=True)
            shutil.copyfile(source["expectations_by_phase"][phase], case / "expectations.json")
            exported = export_provenance(source["database"], source["runs"][phase], source["material_dir"], case / "bundle")
            write_json(case / "export.json", exported)
        for _, case_ids in GROUPS:
            for case_id in case_ids:
                if case_id in positives:
                    continue
                base = "rotation" if case_id == "hidden_policy_head" else "history_quarantine" if case_id == "removed_quarantine" else "history_corrected" if case_id == "removed_correction" else "clean"
                case = root / "cases" / case_id
                case.mkdir(parents=True)
                shutil.copytree(root / "cases" / base / "bundle", case / "bundle")
                expected = json.loads((root / "cases" / base / "expectations.json").read_bytes())
                mutation = _mutate_case(case_id, case / "bundle", expected)
                write_json(case / "expectations.json", expected)
                write_json(case / "controlled-mutation.json", {"positive_control": base, **mutation})
        for group_id, case_ids in GROUPS:
            rows = []
            for case_id in case_ids:
                item = _verify_case_cli(root, case_id, group_id)
                summary["cases"].append(item)
                rows.append(item)
                write_json(root / "summary.json", summary)
            summary["scenario_groups"].append({"id": group_id, "case_ids": list(case_ids), "passed": all(row["passed"] for row in rows)})
        summary["status"] = "PASS" if all(row["passed"] for row in summary["cases"]) else "FAILED"
        write_json(root / "summary.json", summary)
        _write_demo_guide(root, summary)
        return summary
    except Exception as exc:
        summary["status"] = "FAILED"
        summary["error"] = type(exc).__name__ + ": " + str(exc)
        write_json(root / "summary.json", summary)
        raise
