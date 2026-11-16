"""Finite Gate3 LAB reference replay and marginal-cost audit.

The verifier under test is unchanged. Expected labels and raw-file identities
come from a separately preregistered retained-input protocol, never from a
candidate-issued trust context. This is not an institutional authority service.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import datetime
import hashlib
import json
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_SHA256 = "4a42bfc3b519380e9589fbd8e4e855d512716d5dcafa72e26088863b801a2e84"
DOMAIN = b"identity-reference-research-v1\x00"
SEEDS = (11, 29, 47)
FACTORS = (0, 1, 2, 3)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def check_context(candidate, externally_selected):
    """Out-of-band equality is a precondition; it does not authenticate its source."""
    require(candidate == externally_selected, "EXTERNAL_CONTEXT_MISMATCH")
    require(externally_selected["origin"] == "LAB_TEST_ONLY", "NOT_LAB_CONTEXT")


def independent_events(raw):
    """Explicit audited economic-field mapping; no research extraction helper."""
    rows = [row["record"] for row in json.loads(raw)["rows"]
            if row["record"].get("kind") == "event" and row["record"].get("asset") == "COIN"]
    rows.sort(key=lambda row: (row["occurred_at"], row["sequence"], row["source"],
                              row["business_day"], row["ref"]))
    return [{"event_id": canonical([row[key] for key in
            ("source", "platform", "business_day", "ref")]).decode("ascii"),
             "content": canonical(row)} for row in rows]


def independent_checks(envelope, events, anchor):
    obj = json.loads(envelope)
    manifest = obj["manifest"]
    require(manifest["scope"] == anchor["scope"], "SCOPE")
    require(manifest["revision"] == anchor["revision"], "REVISION")
    require(manifest["key_epoch"] == anchor["epoch"], "EPOCH")
    require(manifest["previous_sha256"] == anchor["previous_sha256"], "PREDECESSOR")
    require(digest(canonical(manifest)) == anchor["manifest_sha256"], "MANIFEST_PIN")
    signature = obj["signatures"]
    require(len(signature) == 1 and signature[0]["key_id"] == anchor["key_id"], "KEY_ID")
    require(anchor["key_id"] not in anchor["revoked_key_ids"], "KEY_REVOKED")
    entries = manifest["entries"]
    require([entry["position"] for entry in entries] ==
            [str(i) for i in range(1, len(entries) + 1)], "POSITION")
    expected = [(entry["event_id"], entry["content_sha256"]) for entry in entries]
    actual = [(event["event_id"], digest(event["content"])) for event in events]
    require(len({entry[0] for entry in expected}) == len(expected), "DUPLICATE_REFERENCE_ID")
    require(len({entry[0] for entry in actual}) == len(actual), "DUPLICATE_CANDIDATE_ID")
    return "MATCH" if actual == expected else "REFERENCE_MISMATCH"


def confusion(rows, truth_key, detected_key):
    result = {key: 0 for key in ("TP", "FP", "TN", "FN")}
    for row in rows:
        truth, detected = row[truth_key], row[detected_key]
        require(type(truth) is bool and type(detected) is bool, "NON_BOOLEAN_LABEL")
        result[("T" if truth == detected else "F") + ("P" if detected else "N")] += 1
    return result


def verify_files(entries):
    require(len({entry["path"] for entry in entries}) == len(entries), "DUPLICATE_INPUT")
    for entry in entries:
        path = Path(entry["path"])
        require(path.is_file() and not path.is_symlink(), "MISSING_OR_SYMLINK_INPUT")
        raw = path.read_bytes()
        require(len(raw) == entry["bytes"] and digest(raw) == entry["sha256"], "INPUT_IDENTITY")


def audit(protocol_path, output):
    start, cpu_start = time.perf_counter(), time.process_time()
    protocol_raw = Path(protocol_path).read_bytes()
    require(digest(protocol_raw) == PROTOCOL_SHA256, "PREREGISTERED_PROTOCOL_IDENTITY")
    protocol = json.loads(protocol_raw)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    limits = protocol["limits"]
    resource.setrlimit(resource.RLIMIT_CPU, (limits["cpu_seconds"], limits["cpu_seconds"]))
    resource.setrlimit(resource.RLIMIT_AS, (limits["address_space_bytes"], limits["address_space_bytes"]))
    source_raw = Path(__file__).read_bytes()
    command = {"argv": [sys.executable, *sys.argv], "cwd": str(Path.cwd()),
               "interpreter": str(Path(sys.executable).absolute()), "python": sys.version,
               "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "effective_limits": limits, "wall_limit_enforced_by": "outer command recorder",
               "source_sha256": digest(source_raw), "protocol_sha256": PROTOCOL_SHA256,
               "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()}
    write_json(output / "execution-start.json", command)
    verify_files(protocol["inputs"])
    sys.path.insert(0, str(ROOT))
    import cryptography
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from validation_lab import identity_reference as sut
    command["imports"] = {"verifier": str(Path(sut.__file__).resolve()),
                          "cryptography": str(Path(cryptography.__file__).resolve()),
                          "cryptography_version": cryptography.__version__}
    gate1 = Path("/workspace/validation-evidence/properties/run-004")
    gate2 = Path("/workspace/validation-gate2-evidence/identity/run-002")
    public = Path("/workspace/validation-gate2-evidence/public-data/analysis-02/results")
    baseline = [json.loads(line) for line in (gate1 / "cases.jsonl").read_text().splitlines()]
    require(len(baseline) == len({row["case_id"] for row in baseline}) == 264, "BASELINE_ROSTER")
    baseline_matrix = confusion(baseline, "truth_anomaly", "alert")
    require(baseline_matrix == {"TP": 132, "FP": 0, "TN": 120, "FN": 12}, "BASELINE_COUNTS")
    old = {row["case_id"]: row for row in baseline}
    expected_ids = [f"s{s}-f{f}-{family}" for s in SEEDS for f in FACTORS
                    for family in ("clean", "same_count_substitution")]
    require([row["case_id"] for row in protocol["selected_cases"]] == expected_ids, "EXTERNAL_CASE_SCOPE")
    trials = []
    for selected in protocol["selected_cases"]:
        case_id, group = selected["case_id"], selected["group"]
        case_dir = gate2 / "identity" / case_id
        anchor = json.loads((gate2 / "identity" / (group + "-clean") / "context.json").read_text())
        context = json.loads((case_dir / "context.json").read_text())
        check_context(context, anchor)
        envelope = (case_dir / "envelope.json").read_bytes()
        candidate = json.loads((case_dir / "candidate.json").read_text())
        events = [{"event_id": row["event_id"], "content": base64.b64decode(row["content_base64"], validate=True)}
                  for row in candidate]
        old_input = (gate1 / old[case_id]["input"]).read_bytes()
        require(events == independent_events(old_input), "CANDIDATE_BASELINE_LINEAGE")
        expected = "MATCH" if selected["family"] == "clean" else "REFERENCE_MISMATCH"
        oracle = independent_checks(envelope, events, anchor)
        require(oracle == selected["expected"] == expected, "INDEPENDENT_IDENTITY_ORACLE")
        obj = json.loads(envelope)
        signature = base64.b64decode(obj["signatures"][0]["signature"], validate=True)
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(anchor["public_key_hex"])).verify(
            signature, DOMAIN + canonical(obj["manifest"]))
        c = sut.TrustContext(**{**anchor, "revoked_key_ids": tuple(anchor["revoked_key_ids"])})
        t0, c0 = time.perf_counter(), time.process_time()
        result = sut.verify_reference(envelope, events, c)
        duration, cpu = time.perf_counter() - t0, time.process_time() - c0
        require(result["outcome"] == expected, "VERIFIER_OUTCOME")
        require(old[case_id]["alert"] is False and old[case_id]["observed"]["reconciliation_state"] == "MATCHED", "BASELINE_SUBSET")
        trials.append({**selected, "population": "FULLY_SYNTHETIC", "authority": "LAB_TEST_ONLY",
                       "status": "PASS", "actual": result["outcome"], "expected": expected,
                       "independent_expected": oracle, "baseline_alert": False,
                       "truth_anomaly": selected["family"] != "clean", "detected": result["outcome"] != "MATCH",
                       "input_sha256": digest(old_input), "envelope_sha256": digest(envelope),
                       "context_sha256": digest((case_dir / "context.json").read_bytes()),
                       "candidate_sha256": digest((case_dir / "candidate.json").read_bytes()),
                       "source_sha256": digest(Path(sut.__file__).read_bytes()), "exit_status": "IN_PROCESS_RETURN",
                       "wall_seconds": duration, "cpu_seconds": cpu, "event_count": len(events),
                       "work_units": {"signature_verifications": 1, "candidate_content_hashes": len(events),
                                      "ordered_identity_comparisons": len(events), "manifest_digest_checks": 1,
                                      "external_context_equality_preconditions": 1},
                       "extra_envelope_bytes": len(envelope), "extra_context_file_bytes": (case_dir / "context.json").stat().st_size})
    require(confusion(trials, "truth_anomaly", "detected") == {"TP": 12, "FP": 0, "TN": 12, "FN": 0}, "SIGNED_SUBSET_COUNTS")
    injected = json.loads((public / "ftd-injections.json").read_text())
    injection_matrix = confusion(injected, "injected", "detected")
    require(len(injected) == len({row["case_id"] for row in injected}) == 360, "INJECTION_ROSTER")
    source_rows = {(row["source_file"]["sha256"], canonical(row["original_row"])) for row in injected}
    require(len(source_rows) == 30 and injection_matrix == {"TP": 120, "FP": 0, "TN": 180, "FN": 60}, "INJECTION_COUNTS")
    by_family = {name: confusion([row for row in injected if row["family"] == name], "injected", "detected")
                 for name in sorted({row["family"] for row in injected})}
    # Fixed one-case microdiagnostic; retained output rows are not extra efficacy observations.
    d = gate2 / "identity" / "s11-f0-clean"
    env = (d / "envelope.json").read_bytes()
    ctx = json.loads((d / "context.json").read_text())
    ev = [{"event_id": row["event_id"], "content": base64.b64decode(row["content_base64"])}
          for row in json.loads((d / "candidate.json").read_text())]
    obj = json.loads(env)
    signature = base64.b64decode(obj["signatures"][0]["signature"])
    signed_bytes = DOMAIN + canonical(obj["manifest"])
    key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(ctx["public_key_hex"]))
    trust = sut.TrustContext(**{**ctx, "revoked_key_ids": tuple(ctx["revoked_key_ids"])})
    operations = {"ed25519_signature_only": lambda: key.verify(signature, signed_bytes),
                  "independent_context_and_event_checks": lambda: independent_checks(env, ev, ctx),
                  "complete_reference_verify": lambda: sut.verify_reference(env, ev, trust)}
    settings = protocol["microbenchmark"]
    warm0 = time.perf_counter()
    for operation in operations.values():
        for _ in range(settings["warmup_calls"]):
            operation()
    warmup_seconds = time.perf_counter() - warm0
    measures = []
    names = list(operations)
    for repeat in range(settings["repeats"]):
        for name in names[repeat % 3:] + names[:repeat % 3]:
            t0, c0 = time.perf_counter(), time.process_time()
            for _ in range(settings["iterations_per_repeat"]):
                operations[name]()
            wall, cpu = time.perf_counter() - t0, time.process_time() - c0
            measures.append({"operation": name, "repeat": repeat, "iterations": settings["iterations_per_repeat"],
                             "wall_seconds": wall, "cpu_seconds": cpu,
                             "wall_seconds_per_operation": wall / settings["iterations_per_repeat"],
                             "status": "PASS", "exit_status": "IN_PROCESS_RETURN"})
    verify_files(protocol["inputs"])
    require(Path(__file__).read_bytes() == source_raw, "AUDITOR_CHANGED_DURING_EXECUTION")
    write_json(output / "trial-roster.json", trials)
    write_json(output / "timing-trials.json", measures)
    totals = {name: {"n_batches": settings["repeats"], "iterations_per_batch": settings["iterations_per_repeat"],
                    "p50_seconds_per_operation": statistics.median(row["wall_seconds_per_operation"] for row in measures if row["operation"] == name),
                    "observed_max_seconds_per_operation": max(row["wall_seconds_per_operation"] for row in measures if row["operation"] == name)} for name in names}
    summary = {"format": "gate3-trust-audit-v1", "status": "PASS", "population": "FULLY_SYNTHETIC",
               "authority": "LAB_TEST_ONLY", "independent_institutional_counterparties": 0,
               "baseline_preserved": {"observations": 264, **baseline_matrix, "status": "HISTORICAL_NOT_RERUN"},
               "signed_subset_replayed": {"observations": 24, **confusion(trials, "truth_anomaly", "detected")},
               "public_injected_preserved": {"observations": 360, "source_rows": 30, **injection_matrix, "by_family": by_family, "status": "RECOUNTED_NOT_REGENERATED"},
               "timing": totals, "warmup_seconds": warmup_seconds,
               "bytes_per_three_event_envelope": sorted({row["extra_envelope_bytes"] for row in trials}),
               "context_file_bytes": sorted({row["extra_context_file_bytes"] for row in trials}),
               "microbenchmark_scope": settings, "effective_limits": limits,
               "wall_seconds": time.perf_counter() - start, "cpu_seconds": time.process_time() - cpu_start,
               "observed_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
               "rss_scope": "whole finite audit process high-water RSS; not isolated signature allocation",
               "input_files_verified_pre_and_post": len(protocol["inputs"]),
               "dependency_overlap": "SUT unchanged validation_lab.identity_reference; independent mapping/checks use stdlib JSON/SHA256; signature oracle and SUT both use installed cryptography/OpenSSL Ed25519, so not independent crypto implementation.",
               "institutional_trust": "NOT_PROVEN", "natural_precision_recall": "NOT_MEASURABLE",
               "two_party_record_acquisition": "NOT_AVAILABLE", "cost_savings": "NOT_PROVEN",
               "not_run": ["Independent institutional source or signer acquisition", "Natural labelled financial-error sample",
                           "Independent cryptographic primitive implementation", "Persistent reference registry and revocation feed",
                           "Production admission integration", "Institutional network/storage/key-management cost",
                           "Provider pricing or monetary cost comparison", "Production RTO/RPO", "Isolated allocator-level signature RSS"]}
    write_json(output / "summary.json", summary)
    output_bytes = sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
    require(output_bytes <= limits["output_bytes"], "OUTPUT_BUDGET")
    command.update(exit_code=0, completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   wall_seconds=time.perf_counter() - start, output_bytes=output_bytes,
                   inputs=protocol["inputs"], status="PASS")
    write_json(output / "execution-completion.json", command)
    print(json.dumps({"status": "PASS", "cases": len(trials), "timing": totals,
                      "wall_seconds": summary["wall_seconds"]}, sort_keys=True))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    audit(args.protocol, args.output)
