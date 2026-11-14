"""Local command-line entry points; no network or credentials."""
import argparse
import json
import sqlite3
import sys
from decimal import DecimalException
from pathlib import Path
from .demo import BALANCE_AT, KNOWLEDGE_AT, LATER_KNOWLEDGE_AT, run_demos
from .engine import reconcile
from .migrations import migrate_database
from .reporting import write_report
from .store import Store


def strict_loads(text):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key: {key}")
            value[key] = item
        return value
    def no_constant(value):
        raise ValueError(f"non-finite JSON constant: {value}")
    return json.loads(text, object_pairs_hook=unique, parse_constant=no_constant)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="crypto-reconciliation-lab")
    commands = parser.add_subparsers(dest="command", required=True)
    triage_generate = commands.add_parser("triage-generate", help="generate separate synthetic triage sources and private plans")
    triage_generate.add_argument("--output", required=True)
    triage_generate.add_argument("--mode", choices=("main", "smoke", "archive-smoke"), default="main")
    triage_features = commands.add_parser("triage-features", help="extract allowlisted observations from saved <=T payloads")
    triage_features.add_argument("--input", required=True)
    triage_features.add_argument("--output", required=True)
    triage_train = commands.add_parser("triage-train", help="fit one train-only optional-ai model and export strict JSON")
    triage_train.add_argument("--features", required=True)
    triage_train.add_argument("--labels", required=True)
    triage_train.add_argument("--splits", required=True)
    triage_train.add_argument("--output", required=True)
    triage_rank = commands.add_parser("triage-rank", help="stdlib JSON scoring; no truth input or financial writes")
    triage_rank.add_argument("--features", required=True)
    triage_rank.add_argument("--model", required=True)
    triage_rank.add_argument("--output", required=True)
    triage_rank.add_argument("--split", choices=("train", "validation", "test", "challenge"))
    triage_evaluate = commands.add_parser("triage-evaluate", help="evaluate frozen holdout rankings exactly once")
    for name in ("input", "features", "model", "queues", "freeze", "output"):
        triage_evaluate.add_argument("--" + name, required=True)
    triage_experiment = commands.add_parser("triage-experiment", help="run the bounded synthetic experiment or a distinct two-world smoke")
    triage_experiment.add_argument("--output", required=True)
    triage_experiment.add_argument("--mode", choices=("main", "smoke", "archive-smoke"), default="main")
    review_export = commands.add_parser("review-export", help="export selected saved runs to a read-only offline review page")
    review_export.add_argument("--selection", required=True, help="review-selection-v1 JSON; database paths resolve relative to it")
    review_export.add_argument("--output", required=True, help="new output directory; never replaces an existing path")
    review_demo = commands.add_parser("review-demo", help="prepare fresh synthetic sources and an offline review showcase")
    review_demo.add_argument("--output", required=True, help="new owned showcase directory")
    demo = commands.add_parser("demo", help="run and verify all four synthetic demos")
    demo.add_argument("--output", default="demo-output")
    demo.add_argument("--balance-at", default=BALANCE_AT)
    demo.add_argument("--knowledge-at", default=KNOWLEDGE_AT)
    demo.add_argument("--later-knowledge-at", default=LATER_KNOWLEDGE_AT)
    correction_demo = commands.add_parser("demo-corrections", help="verify five Stage 2 correction demos")
    correction_demo.add_argument("--output", default="stage2-output/demos")
    migration = commands.add_parser("migrate", help="back up, test on a copy, then migrate physical schema to v5")
    migration.add_argument("--db", required=True)
    migration.add_argument("--backup-dir", required=True)
    init = commands.add_parser("init", help="create an immutable-config SQLite store")
    init.add_argument("--db", required=True)
    init.add_argument("--config", required=True)
    ingest = commands.add_parser("ingest", help="append JSONL envelopes, retaining invalid records")
    ingest.add_argument("--db", required=True)
    ingest.add_argument("--input", required=True)
    feed = commands.add_parser("ingest-feed", help="admit/replay a bounded immutable JSONL snapshot; no reconciliation")
    feed.add_argument("--db", required=True)
    feed.add_argument("--input", required=True)
    feed.add_argument("--stream-id", required=True)
    feed.add_argument("--busy-timeout-ms", type=int, default=250)
    feed_status = commands.add_parser("feed-status", help="read committed transport scope and delivery history")
    feed_status.add_argument("--db", required=True)
    feed_status.add_argument("--stream-id", required=True)
    recovery = commands.add_parser("demo-recovery", help="run the bounded real-process interruption and replay experiment")
    recovery.add_argument("--output", required=True)
    recovery.add_argument("--seed", type=int, default=19)
    auth_demo = commands.add_parser("demo-source-auth", help="run bounded signed-admission and real interruption evidence")
    auth_demo.add_argument("--output", required=True)
    auth_demo.add_argument("--seed", type=int, default=19)
    auth_verify = commands.add_parser("verify-source-auth", help="independently verify source-auth evidence against a local anchor")
    auth_verify.add_argument("--bundle", required=True)
    auth_verify.add_argument("--anchor", required=True, help="local operator anchor JSON or explicit demo-test-only")
    protect = commands.add_parser("auth-enable", help="atomically protect an empty schema-5 database using local operator policy")
    protect.add_argument("--db", required=True)
    protect.add_argument("--receiver", required=True)
    protect.add_argument("--policy", required=True)
    policy = commands.add_parser("auth-activate-policy", help="append a local policy epoch using compare-and-swap")
    policy.add_argument("--db", required=True)
    policy.add_argument("--policy", required=True)
    policy.add_argument("--expected-epoch", required=True, type=int)
    policy.add_argument("--expected-hash", required=True)
    signed = commands.add_parser("ingest-signed", help="authenticate one immutable publisher snapshot; no reconciliation")
    signed.add_argument("--db", required=True)
    signed.add_argument("--input", required=True)
    signed.add_argument("--envelope", required=True)
    auth_status = commands.add_parser("auth-status", help="read protected mode and immutable policy/admission history")
    auth_status.add_argument("--db", required=True)
    run = commands.add_parser("reconcile", help="create a knowledge-bounded evaluation")
    run.add_argument("--db", required=True)
    run.add_argument("--balance-at", required=True)
    run.add_argument("--knowledge-at", required=True)
    run.add_argument("--output", required=True, help="output path prefix, without extension")
    show = commands.add_parser("show", help="read a persisted historical evaluation")
    show.add_argument("--db", required=True)
    show.add_argument("--run-id", required=True)
    show.add_argument("--output", required=True)
    lab_generate = commands.add_parser("lab-generate", help="create independent Stage 3 truth, inputs and expectations")
    lab_generate.add_argument("--output", required=True)
    lab_generate.add_argument("--seed", type=int, action="append", dest="seeds")
    lab_generate.add_argument("--events", type=int, default=100)
    lab_generate.add_argument("--investors", type=int, default=6)
    lab_generate.add_argument("--scenario", action="append", dest="scenarios")
    lab_generate.add_argument("--stress", action="store_true")
    lab_verify = commands.add_parser("lab-verify", help="compare each finding and ledger with independent expectations")
    lab_verify.add_argument("--input", required=True)
    lab_verify.add_argument("--output", required=True)
    lab_verify.add_argument("--case")
    lab_benchmark = commands.add_parser("lab-benchmark", help="run three-trial clean scale sweeps after a full correctness gate")
    lab_benchmark.add_argument("--correctness", required=True)
    lab_benchmark.add_argument("--output", required=True)
    lab_benchmark.add_argument("--seed", type=int, default=11)
    lab_benchmark.add_argument("--phase-seconds", type=float, default=120)
    lab_benchmark.add_argument("--total-seconds", type=float, default=1200)
    lab_benchmark.add_argument("--rss-mib", type=int, default=1024)
    lab_benchmark.add_argument("--trial-mib", type=int, default=512)
    lab_benchmark.add_argument("--temporary-mib", type=int, default=2048)
    lab_benchmark.add_argument("--stress", action="store_true")
    lab_benchmark.add_argument("--smoke", action="store_true", help="only 100 events / 20 investors, three trials; not a full scale benchmark")
    args = parser.parse_args(argv)
    store = None
    try:
        if args.command in ("demo-source-auth", "verify-source-auth", "auth-enable", "auth-activate-policy", "ingest-signed"):
            from .source_auth.crypto import require_auth
            require_auth()  # Before creating any output or opening a mutable database.
        if args.command == "demo-source-auth":
            from .source_auth.demo import demo_source_auth
            result = demo_source_auth(args.output, seed=args.seed)
            print(json.dumps(result, sort_keys=True))
            return 0 if result["status"] == "PASSED" else 2
        if args.command == "verify-source-auth":
            from .source_auth.verifier import verify_bundle
            from .source_auth.fixtures import operator_anchor
            anchor = operator_anchor() if args.anchor == "demo-test-only" else strict_loads(Path(args.anchor).read_text(encoding="utf-8"))
            result = verify_bundle(args.bundle, operator_anchor=anchor)
            print(json.dumps(result, sort_keys=True))
            return 0 if result["status"] == "PASSED" else 2
        if args.command == "demo-recovery":
            from .admission.recovery import run_demo
            result = run_demo(args.output, seed=args.seed)
            print(json.dumps(result, sort_keys=True))
            return 0 if result["status"] == "PASS" else 2
        if args.command.startswith("triage-"):
            if args.command == "triage-generate":
                from .triage.world import generate_bundle
                result = generate_bundle(args.output, mode=args.mode.replace("-", "_"))
                summary = {"status": "COMPLETE", "worlds": result["worlds"], "episodes": result["episodes"]}
            elif args.command == "triage-features":
                from .triage.features import build_features
                result = build_features(args.input, args.output)
                summary = {"status": "COMPLETE", **result["inventory"]}
            elif args.command == "triage-train":
                from .triage.runner import train_files
                model, audit = train_files(args.features, args.labels, args.splits, args.output)
                summary = {"status": "COMPLETE", "model_id": model["model_id"]}
            elif args.command == "triage-rank":
                from .triage.ranking import rank_files
                result = rank_files(args.features, args.model, args.output, args.split)
                summary = {"status": "COMPLETE", "model_id": result["model_id"], **result["inventory"]}
            elif args.command == "triage-evaluate":
                from .triage.runner import evaluate_frozen
                reports, labels = evaluate_frozen(args.input, args.features, args.model, args.queues, args.freeze, args.output)
                summary = {"status": "COMPLETE", "test_open": reports["test"]["open_count"], "challenge_open": reports["challenge"]["open_count"]}
            else:
                from .triage.runner import run_experiment
                result = run_experiment(args.output, args.mode.replace("-", "_"))
                summary = {"status": result["status"], "mode": result["mode"], "budget": result["budget"]}
            print(json.dumps(summary, sort_keys=True))
            return 0
        if args.command == "review-export":
            from .review.export import export_selection
            result = export_selection(args.selection, args.output)
            print(json.dumps({"status": result["status"], "format": result["format"],
                              "page": str(Path(args.output).resolve() / "index.html")}))
            return 0
        if args.command == "review-demo":
            from .review.demo import run_demo
            result = run_demo(args.output)
            print(json.dumps({"status": result["status"], "runs": len(result["runs"]),
                              "page": str(Path(args.output).resolve() / result["page"]),
                              "open": "Double-click index.html; no server or network required."}))
            return 0
        if args.command == "lab-generate":
            from .lab.runner import generate_bundle
            from .lab.faults import SCENARIOS
            if args.events >= 100000 and not args.stress:
                raise ValueError("100,000+ events require explicit --stress")
            result = generate_bundle(args.output, args.seeds or (11, 29, 47), args.events, args.investors, args.scenarios or SCENARIOS)
            print(json.dumps({"cases": len(result["cases"]), "events": result["events"], "seeds": result["seeds"]}))
            return 0
        if args.command == "lab-verify":
            from .lab.runner import run_bundle
            result = run_bundle(args.input, args.output, args.case)
            print(json.dumps({"status": result["status"], "evaluations": result["evaluations"], "counters": result["counters"]}))
            return {"PASS": 0, "CORRECTNESS_FAILED": 3, "ERROR": 2}[result["status"]]
        if args.command == "lab-benchmark":
            from .lab.benchmark import run_benchmark
            from .lab.watchdog import Budgets
            budgets = Budgets(phase_seconds=args.phase_seconds, total_seconds=args.total_seconds, rss_bytes=args.rss_mib*1024**2,
                              trial_bytes=args.trial_mib*1024**2, temporary_bytes=args.temporary_mib*1024**2)
            result = run_benchmark(args.correctness, args.output, budgets, args.seed, args.stress, args.smoke)
            print(json.dumps({"gate": result["gate_status"], "correctness": result["correctness"], "completion": result["completion_state"], "benchmark": result["status"]}))
            return {"COMPLETED": 0, "PARTIAL_BUDGET": 1, "ERROR": 2, "CORRECTNESS_FAILED": 3}[result["status"]]
        if args.command == "migrate":
            print(json.dumps(migrate_database(args.db, args.backup_dir), indent=2, sort_keys=True))
            return 0
        if args.command == "demo-corrections":
            from .correction_demo import run_correction_demos
            summary = run_correction_demos(args.output)
            for row in summary:
                print(f"{row['scenario']}/{row['phase']}: {'PASS' if row['verified'] else 'FAIL'} {row['run_id']}")
            return 0 if all(r["verified"] for r in summary) else 2
        if args.command == "demo":
            summary = run_demos(args.output, args.balance_at, args.knowledge_at, args.later_knowledge_at)
            for row in summary:
                print(f"{row['scenario']}/{row['phase']}: {'PASS' if row['verified'] else 'FAIL'} {row['run_id']}")
            return 0 if all(r["verified"] for r in summary) else 2
        if args.command == "init":
            store = Store(args.db, strict_loads(Path(args.config).read_text()))
            print("Database initialized")
            return 0
        if not Path(args.db).is_file():
            raise ValueError("database does not exist; run init first")
        store = Store(args.db, busy_timeout_ms=args.busy_timeout_ms if args.command == "ingest-feed" else None)
        if args.command == "auth-enable":
            from .source_auth.runtime import enable_protection
            from .source_auth.crypto import strict_json
            result = enable_protection(store, args.receiver, strict_json(Path(args.policy).read_bytes()))
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.command == "auth-activate-policy":
            from .source_auth.runtime import activate_policy
            from .source_auth.crypto import strict_json
            result = activate_policy(store, strict_json(Path(args.policy).read_bytes()),
                                     expected_epoch=args.expected_epoch, expected_hash=args.expected_hash)
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.command == "ingest-signed":
            from .admission.feed import snapshot_feed
            from .source_auth.runtime import ingest_signed
            snapshot = snapshot_feed(args.input)
            with Path(args.envelope).open("rb") as source:
                envelope = source.read(262145)
            result = ingest_signed(store, b"".join(snapshot.lines), envelope)
            print(json.dumps(result, sort_keys=True))
            return 0 if result["status"] == "COMPLETE" else 1
        if args.command == "auth-status":
            from .source_auth.runtime import auth_status
            print(json.dumps(auth_status(store), sort_keys=True))
            return 0
        if args.command == "ingest-feed":
            from .admission.feed import ingest_feed
            result = ingest_feed(store, args.input, args.stream_id, busy_timeout_ms=args.busy_timeout_ms)
            print(json.dumps(result, sort_keys=True))
            state = result["delivery_status"]
            return 0 if result["status"] == "COMPLETE" and not state["core_invalid_count"] and not state["frame_rejected_count"] and not any(e["disposition"] == "CONFLICT" for e in state["effects"]) else 1
        if args.command == "feed-status":
            print(json.dumps(store.feed_status(args.stream_id), sort_keys=True))
            return 0
        if args.command == "ingest":
            counts = {}
            with Path(args.input).open() as source:
                for line in source:
                    try:
                        envelope = strict_loads(line)
                        if not isinstance(envelope, dict) or set(envelope) != {"record", "received_at"}:
                            raise ValueError("envelope requires only record and received_at")
                        result = store.ingest(envelope["record"], envelope["received_at"])
                    except (ValueError, TypeError) as exc:
                        # Preserve even syntactically malformed lines; unknown time blocks completeness.
                        result = store.ingest({"malformed_line": line, "parse_error": str(exc)}, None)
                    counts[result["status"]] = counts.get(result["status"], 0) + 1
            print(json.dumps(counts, sort_keys=True))
            return 1 if counts.get("INVALID") or counts.get("CONFLICT") else 0
        result = store.read_run(args.run_id) if args.command == "show" else reconcile(store, args.balance_at, args.knowledge_at)
        write_report(args.output, result)
        print(result["run_id"])
        return 0 if all(r["data_state"] == "COMPLETE" and r["reconciliation_state"] == "MATCHED" for r in result["findings"]) else 1
    except (ValueError, OSError, sqlite3.Error, DecimalException) as exc:
        if (args.command == "ingest-feed" and isinstance(exc, sqlite3.OperationalError)
                and getattr(exc, "sqlite_errorcode", 0) & 255 in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)):
            from .admission.feed import unknown_status
            print(json.dumps({"format": "feed-admission-v1", "stream_id": args.stream_id,
                              "status": "INCOMPLETE", "outcome": "RETRYABLE_BUSY", "ack": False,
                              "durable": False, "responses": [],
                              "delivery_status": unknown_status(args.stream_id, str(exc)),
                              "financial_evaluation": "NOT_RUN"}, sort_keys=True))
            return 1
        print(f"Application/configuration error: {exc}", file=sys.stderr)
        return 2
    finally:
        if store is not None:
            store.close()
