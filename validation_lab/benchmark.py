"""Finite, offline, deliberately narrower-scope reconciliation benchmarks.

No production modules are used by either reference implementation or the oracle.
Timing the production application does not establish semantic equivalence to the
two baselines: production persists and exports much richer historical evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import resource
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "contracts/benchmark-protocol-v1.json"
METHODS = ("stdlib_integer", "sqlite_integer", "production")
OPENING = "2026-01-02T00:00:00Z"
EVENT_TIME = "2026-01-02T12:00:00Z"
CUT = "2026-01-02T23:00:00Z"
KNOWN = "2026-01-03T00:00:00Z"
INVESTORS = tuple("I" + str(i) for i in range(4))


def dump(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n")


def file_proof(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return {"sha256": h.hexdigest(), "bytes": Path(path).stat().st_size}


def cents(text):
    # Independent strict integer parser; no Decimal or production normalizer.
    if not isinstance(text, str) or text.startswith("-"):
        raise ValueError("nonnegative decimal string required")
    parts = text.split(".")
    if len(parts) > 2 or not all(p.isascii() and p.isdigit() for p in parts):
        raise ValueError("plain ASCII decimal required")
    if len(parts) == 2 and len(parts[1]) > 2:
        raise ValueError("at most two decimal places")
    result = int(parts[0]) * 100 + int((parts[1] if len(parts) == 2 else "").ljust(2, "0"))
    if result >= 2**60:
        raise ValueError("narrow integer range exceeded")
    return result


def amount(value):
    return f"{value // 100}.{value % 100:02d}"


def analytic_oracle(n, seed):
    """Whole deposit/transfer/withdraw triples cancel; only a suffix remains."""
    balances = {key: 10000 for key in INVESTORS}
    groups, remainder = divmod(n, 3)
    residual = ((groups * 17 + seed) % 99) + 1 if remainder else 0
    if remainder:
        recipient = INVESTORS[(groups + (remainder == 2)) % 4]
        balances[recipient] += residual
    return {"balances": balances, "liability": 40000 + residual,
            "custody": {"platform": 0, "external": 40000 + residual}}


def workload(n, seed):
    if type(n) is not int or n < 0 or n > 100000:
        raise ValueError("finite event profile 0..100000 required")
    config = {"platform": "P", "custodian": "C", "investors": list(INVESTORS),
              "assets": {"UNIT": 2}, "opening_at": OPENING}
    rows = []

    def add(kind, fields, source="P", received=KNOWN):
        rows.append({"record": {"kind": kind, "platform": "P", "source": source,
                                "asset": "UNIT", **fields}, "received_at": received})

    for key, val in {**{i: 10000 for i in INVESTORS}, "platform": 0, "external": 40000}.items():
        add("opening", {"scope": key, "balance_at": OPENING, "amount": amount(val)}, received=OPENING)
    for index in range(n):
        group, step = divmod(index, 3)
        q = ((group * 17 + seed) % 99) + 1
        sender, recipient = INVESTORS[group % 4], INVESTORS[(group + 1) % 4]
        add("event", {"business_day": "2026-01-02", "ref": f"E{index}",
                      "occurred_at": EVENT_TIME, "sequence": index,
                      "type": ("deposit", "transfer", "withdrawal")[step],
                      "from_investor": None if step == 0 else sender if step == 1 else recipient,
                      "to_investor": sender if step == 0 else recipient if step == 1 else None,
                      "custody": None if step == 1 else "external", "amount": amount(q)})
    expected = analytic_oracle(n, seed)
    for key in INVESTORS:
        add("report", {"scope": key, "stream": "investor", "balance_at": CUT,
                       "version": 1, "amount": amount(expected["balances"][key])})
    for stream, scope, source in (("platform_custody", "platform", "P"), ("external_custody", "external", "C")):
        add("report", {"scope": scope, "stream": stream, "balance_at": CUT, "version": 1,
                       "amount": amount(expected["custody"][scope])}, source)
    for stream, count in (("opening", 6), ("event", n), ("investor", 4), ("platform_custody", 1), ("external_custody", 1)):
        add("manifest", {"stream": stream, "coverage_from": OPENING if stream in ("event", "opening") else CUT,
                         "coverage_to": OPENING if stream == "opening" else CUT, "expected_count": count},
            "C" if stream == "external_custody" else "P")
    return {"config": config, "balance_at": CUT, "knowledge_at": KNOWN,
            "data_class": "FULLY_SYNTHETIC", "events": n, "seed": seed, "rows": rows}


def validate_narrow(data):
    """Reject unsupported inputs, rather than silently broadening scope."""
    if data["config"] != {"platform": "P", "custodian": "C", "investors": list(INVESTORS),
                          "assets": {"UNIT": 2}, "opening_at": OPENING}:
        raise ValueError("NARROWER_SCOPE configuration")
    if data["balance_at"] != CUT or data["knowledge_at"] != KNOWN:
        raise ValueError("NARROWER_SCOPE time cut")
    seen = set()
    counts = {}
    manifests = {}
    opening_scopes, report_scopes = set(), set()
    fields = {"opening": {"scope", "balance_at", "amount"},
              "event": {"business_day", "ref", "occurred_at", "sequence", "type", "from_investor", "to_investor", "custody", "amount"},
              "report": {"scope", "stream", "balance_at", "version", "amount"},
              "manifest": {"stream", "coverage_from", "coverage_to", "expected_count"}}
    for env in data["rows"]:
        if set(env) != {"record", "received_at"}:
            raise ValueError("envelope fields")
        r = env["record"]
        kind = r.get("kind")
        if kind not in fields or set(r) != fields[kind] | {"kind", "platform", "source", "asset"}:
            raise ValueError("NARROWER_SCOPE record shape/kind")
        if r["asset"] != "UNIT" or r["platform"] != "P":
            raise ValueError("asset/platform outside scope")
        stream = r.get("stream", kind)
        if r["source"] != ("C" if stream == "external_custody" else "P"):
            raise ValueError("unexpected source")
        if env["received_at"] != (OPENING if kind == "opening" else KNOWN):
            raise ValueError("NARROWER_SCOPE receipt time")
        if kind != "manifest":
            q = cents(r["amount"])
        if kind == "event":
            if r["occurred_at"] != EVENT_TIME or r["business_day"] != "2026-01-02" or type(r["sequence"]) is not int or r["sequence"] < 0:
                raise ValueError("NARROWER_SCOPE economic time/sequence")
            if r["ref"] in seen or not isinstance(r["ref"], str) or q == 0:
                raise ValueError("duplicate/event identity/amount")
            seen.add(r["ref"])
            sender, target, custody = r["from_investor"], r["to_investor"], r["custody"]
            valid = ((r["type"] == "deposit" and sender is None and target in INVESTORS and custody == "external")
                     or (r["type"] == "withdrawal" and target is None and sender in INVESTORS and custody == "external")
                     or (r["type"] == "transfer" and sender in INVESTORS and target in INVESTORS and sender != target and custody is None))
            if not valid:
                raise ValueError("NARROWER_SCOPE participants")
        elif kind == "opening":
            if r["scope"] not in (*INVESTORS, "platform", "external") or r["scope"] in opening_scopes or r["balance_at"] != OPENING:
                raise ValueError("opening scope/time/duplicate")
            opening_scopes.add(r["scope"])
        elif kind == "report":
            key = (stream, r["scope"])
            allowed = {( "investor", i) for i in INVESTORS} | {("platform_custody", "platform"), ("external_custody", "external")}
            if key not in allowed or key in report_scopes or r["version"] != 1 or r["balance_at"] != CUT:
                raise ValueError("NARROWER_SCOPE report revision/scope/time")
            report_scopes.add(key)
        else:
            start = OPENING if stream in ("opening", "event") else CUT
            end = OPENING if stream == "opening" else CUT
            if stream in manifests or r["coverage_from"] != start or r["coverage_to"] != end or type(r["expected_count"]) is not int:
                raise ValueError("manifest scope/time/duplicate")
            manifests[stream] = r["expected_count"]
            continue
        counts[stream] = counts.get(stream, 0) + 1
    counts.setdefault("event", 0)
    if manifests != counts or set(manifests) != {"opening", "event", "investor", "platform_custody", "external_custody"}:
        raise ValueError("manifest completeness")
    if len(opening_scopes) != 6 or len(report_scopes) != 6:
        raise ValueError("missing opening/report")
    # Fixed profiles are safely below signed SQLite SUM overflow.
    if len(seen) > 100000 or any(cents(e["record"]["amount"]) > 1000000 for e in data["rows"] if e["record"]["kind"] != "manifest"):
        raise ValueError("NARROWER_SCOPE bounded integer sum")
    if type(data.get("events")) is not int or data["events"] != len(seen) or type(data.get("seed")) is not int:
        raise ValueError("event-count/seed metadata differs from the actual workload")


def with_findings(result, data):
    reports = {r["scope"]: cents(r["amount"]) for e in data["rows"] if (r := e["record"])["kind"] == "report"}
    finding = {key: result["balances"][key] - reports[key] for key in INVESTORS}
    finding["customer_liability"] = result["liability"] - reports["platform"] - reports["external"]
    return {**result, "differences": finding,
            "outcomes": {k: "MATCHED" if v == 0 else "MISMATCH" for k, v in finding.items()}}


def python_calculate(rows):
    balances, custody = {}, {}
    events = []
    for r in rows:
        if r["kind"] == "opening":
            (balances if r["scope"] in INVESTORS else custody)[r["scope"]] = cents(r["amount"])
        elif r["kind"] == "event":
            events.append(r)
    for r in sorted(events, key=lambda r: (r["occurred_at"], r["sequence"], r["source"], r["business_day"], r["ref"])):
        q = cents(r["amount"])
        if r["from_investor"] is not None:
            balances[r["from_investor"]] -= q
        if r["to_investor"] is not None:
            balances[r["to_investor"]] += q
        if r["custody"]:
            custody[r["custody"]] += q if r["type"] == "deposit" else -q
        if min(balances.values()) < 0:
            raise ValueError("NARROWER_SCOPE intermediate negative balance")
    return {"balances": balances, "liability": sum(balances.values()), "custody": custody}


def reference_database(path):
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE input(raw TEXT NOT NULL, kind TEXT, scope TEXT, quantity INTEGER, sender TEXT, recipient TEXT, custody TEXT, event_type TEXT); CREATE TABLE result(payload TEXT NOT NULL);")
    return db


def reference_ingest(db, data):
    for env in data["rows"]:
        r = env["record"]
        with db:
            db.execute("INSERT INTO input VALUES(?,?,?,?,?,?,?,?)", (json.dumps(r), r["kind"], r.get("scope"),
                cents(r["amount"]) if "amount" in r else None, r.get("from_investor"), r.get("to_investor"), r.get("custody"), r.get("type")))


def sql_calculate(db):
    balances = dict(db.execute("""SELECT person,SUM(delta) FROM (
      SELECT scope AS person,quantity AS delta FROM input WHERE kind='opening' AND scope NOT IN ('platform','external')
      UNION ALL SELECT recipient,quantity FROM input WHERE kind='event' AND recipient IS NOT NULL
      UNION ALL SELECT sender,-quantity FROM input WHERE kind='event' AND sender IS NOT NULL
    ) GROUP BY person"""))
    custody = dict(db.execute("""SELECT place,SUM(delta) FROM (
      SELECT scope AS place,quantity AS delta FROM input WHERE kind='opening' AND scope IN ('platform','external')
      UNION ALL SELECT custody,CASE WHEN event_type='deposit' THEN quantity ELSE -quantity END
        FROM input WHERE kind='event' AND custody IS NOT NULL
    ) GROUP BY place"""))
    liability = db.execute("""SELECT SUM(delta) FROM (
      SELECT quantity AS delta FROM input WHERE kind='opening' AND scope NOT IN ('platform','external')
      UNION ALL SELECT quantity FROM input WHERE kind='event' AND event_type='deposit'
      UNION ALL SELECT -quantity FROM input WHERE kind='event' AND event_type='withdrawal'
    )""").fetchone()[0]
    return {"balances": balances, "liability": liability, "custody": custody}


def project_production(result):
    ledger = result["ledgers"]["UNIT"]
    if ledger["data_state"] != "COMPLETE" or any(r["data_state"] != "COMPLETE" for r in result["findings"]):
        raise AssertionError("production did not complete the declared valid profile")
    return {"balances": {k: cents(v) for k, v in ledger["investor_balances"].items()},
            "liability": cents(ledger["liability"]), "custody": {k: cents(v) for k, v in ledger["custody_rollforward"].items()},
            "differences": {r["scope"]: (-cents(r["difference"][1:]) if r["difference"].startswith("-") else cents(r["difference"])) for r in result["findings"]},
            "outcomes": {r["scope"]: r["reconciliation_state"] for r in result["findings"]}}


def run_one(method, input_path, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    phases = {}
    start, cpu_start = time.perf_counter(), time.process_time()

    def phase(name, fn):
        wall, cpu = time.perf_counter(), time.process_time()
        dump(output / "progress.json", {"phase": name, "state": "STARTED", "elapsed_seconds": wall-start, "phases_completed": phases})
        value = fn()
        phases[name] = {"wall_seconds": time.perf_counter() - wall, "cpu_seconds": time.process_time() - cpu}
        dump(output / "progress.json", {"phase": name, "state": "COMPLETED", "elapsed_seconds": time.perf_counter()-start, "phases_completed": phases})
        return value

    data = phase("read_input", lambda: json.loads(Path(input_path).read_text()))
    actual_events = sum(e["record"].get("kind") == "event" for e in data["rows"])
    if type(data.get("events")) is not int or data["events"] != actual_events or type(data.get("seed")) is not int:
        raise ValueError("event-count/seed metadata differs from the actual workload")
    db_path = output / "database.sqlite3"
    if method == "production":
        from crypto_reconciliation_lab import Store, reconcile

        class TimedStore(Store):
            def save_run(self, result, *, fault=None):
                return phase("persist_result", lambda: super(TimedStore, self).save_run(result, fault=fault))

        store = phase("initialize", lambda: TimedStore(db_path, data["config"]))
        settings = {key: store.db.execute("PRAGMA " + key).fetchone()[0] for key in ("journal_mode", "synchronous", "page_size")}
        def ingest():
            for env in data["rows"]:
                answer = store.ingest(env["record"], env["received_at"])
                if answer["status"] != "ACCEPTED":
                    raise AssertionError(answer)
        phase("ingest", ingest)
        full = phase("reconcile_including_persist", lambda: reconcile(store, CUT, KNOWN))
        phases["reconcile"] = {k: phases["reconcile_including_persist"][k] - phases["persist_result"][k] for k in ("wall_seconds", "cpu_seconds")}
        result = phase("project_common_output", lambda: project_production(full))
        phase("export", lambda: dump(output / "export.json", full))
        phase("close", store.close)
    else:
        phase("validate_narrow_scope", lambda: validate_narrow(data))
        db = phase("initialize", lambda: reference_database(db_path))
        settings = {key: db.execute("PRAGMA " + key).fetchone()[0] for key in ("journal_mode", "synchronous", "page_size")}
        phase("ingest", lambda: reference_ingest(db, data))
        def calculate():
            if method == "stdlib_integer":
                return with_findings(python_calculate(json.loads(row[0]) for row in db.execute("SELECT raw FROM input")), data)
            return with_findings(sql_calculate(db), data)
        result = phase("reconcile", calculate)
        def persist():
            with db:
                db.execute("INSERT INTO result VALUES(?)", (json.dumps(result),))
        phase("persist_result", persist)
        phase("export", lambda: dump(output / "export.json", result))
        phase("close", db.close)
    def verify():
        expected = with_findings(analytic_oracle(data["events"], data["seed"]), data)
        if result != expected or any(value != "MATCHED" for value in result["outcomes"].values()):
            raise AssertionError({"observed": result, "expected": expected})
    phase("verification", verify)
    elapsed, cpu = time.perf_counter() - start, time.process_time() - cpu_start
    metrics = {"method": method, "events": data["events"], "rows": len(data["rows"]), "seed": data["seed"],
               "status": "PASS", "wall_seconds": elapsed, "cpu_seconds": cpu,
               "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               "throughput_events_per_second": data["events"] / elapsed, "phases": phases,
               "sqlite_settings": settings, "common_output": result,
               "artifacts": {p.name: file_proof(p) for p in (db_path, output / "export.json")},
               "timing_excludes": "child interpreter startup, input generation, artifact hashing and cleanup",
               "input": file_proof(input_path), "optional_extras_used": False}
    metrics["disk_bytes"] = sum(x["bytes"] for x in metrics["artifacts"].values())
    dump(output / "metrics.json", metrics)
    return metrics


def percentile(values, p):
    return sorted(values)[max(0, math.ceil(len(values) * p) - 1)]


def bootstrap(values, seed=9281):
    rng = random.Random(seed)
    draws = sorted(statistics.median(rng.choices(values, k=len(values))) for _ in range(2000))
    return [draws[49], draws[1949]]


def summarize(trials):
    result, comparisons = [], []
    sizes = sorted(set(t["events"] for t in trials))
    for n in sizes:
        for method in METHODS:
            group = [t for t in trials if t["events"] == n and t["method"] == method and t["status"] == "PASS"]
            row = {"events": n, "method": method, "completed_repeats": len(group),
                   "status": "MEASURED" if len(group) >= 5 else "INCONCLUSIVE"}
            for metric in ("wall_seconds", "cpu_seconds", "peak_rss_kib", "disk_bytes", "throughput_events_per_second"):
                vals = [t["metrics"][metric] for t in group]
                row[metric] = {"p50": statistics.median(vals), "p95_nearest_rank": percentile(vals, .95), "min": min(vals), "max": max(vals)} if vals else None
            row["export_bytes"] = statistics.median(t["metrics"]["artifacts"]["export.json"]["bytes"] for t in group) if group else None
            row["phase_wall_medians"] = {name: statistics.median(t["metrics"]["phases"][name]["wall_seconds"] for t in group)
                                         for name in group[0]["metrics"]["phases"]} if group else {}
            result.append(row)
        for baseline in METHODS[:2]:
            pairs = []
            for rep in range(5):
                pair = {t["method"]: t for t in trials if t["events"] == n and t["repeat"] == rep and t["status"] == "PASS"}
                if "production" in pair and baseline in pair:
                    a, b = pair[baseline]["metrics"]["wall_seconds"], pair["production"]["metrics"]["wall_seconds"]
                    pairs.append({"repeat": rep, "production_minus_baseline_seconds": b-a, "production_divided_by_baseline": b/a})
            differences = [p["production_minus_baseline_seconds"] for p in pairs]
            ratios = [p["production_divided_by_baseline"] for p in pairs]
            comparisons.append({"events": n, "baseline": baseline, "pairs": pairs, "n": len(pairs),
                                "median_difference_seconds": statistics.median(differences) if pairs else None,
                                "difference_bootstrap95": bootstrap(differences) if pairs else None,
                                "median_ratio": statistics.median(ratios) if pairs else None,
                                "ratio_bootstrap95": bootstrap(ratios) if pairs else None,
                                "semantic_parity": "NARROWER_SCOPE", "speed_advantage": "INCONCLUSIVE"})
    return result, comparisons


def benchmark(output, profiles, repeats=5, total_timeout=360):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    if not profiles or len(profiles) != len(set(profiles)) or repeats != 5 or any(n not in (100, 1000, 10000, 100000) for n in profiles):
        raise ValueError("run the preregistered profiles and exactly five repeats")
    (output / "inputs").mkdir()
    (output / "trials").mkdir()
    protocol = json.loads(PROTOCOL.read_text())
    dump(output / "protocol.json", protocol)
    start = time.monotonic()
    controller_cpu_start = time.process_time()
    children_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    trials, warmups = [], []
    record = {"status": "RUNNING", "protocol": file_proof(PROTOCOL), "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "implementation": {"module": file_proof(Path(__file__)), "tests": file_proof(ROOT / "validation_tests/test_benchmark.py"),
                                 "base_commit": protocol["source_baseline"]},
              "host": {"platform": platform.platform(), "machine": platform.machine(), "python": sys.version,
                       "sqlite": sqlite3.sqlite_version, "cpu_count": os.cpu_count(), "loadavg": os.getloadavg(),
                       "cpu_affinity": sorted(os.sched_getaffinity(0)),
                       "cgroup_limits": {name: (Path("/sys/fs/cgroup") / name).read_text().strip() for name in ("cpu.max", "memory.max") if (Path("/sys/fs/cgroup") / name).is_file()},
                       "storage": "workspace filesystem; physical disk type unknown; OS page cache not dropped"},
              "command": sys.argv, "profiles": profiles, "trials": trials, "warmups": warmups,
              "max_postprocess_disk_observation_bytes": 0,
              "repeats": repeats, "full_semantic_parity": False, "comparative_speed_advantage": "INCONCLUSIVE"}
    dump(output / "results.json", record)

    def launch(n, rep, method, seed, warmup=False):
        label = f"{'warmup' if warmup else 'n'+str(n)}-r{rep}-{method}"
        input_path = output / "inputs" / f"n{n}-seed{seed}.json"
        if not input_path.exists():
            dump(input_path, workload(n, seed))
        trial = output / "trials" / label
        cmd = [sys.executable, "-B", "-m", "validation_lab.benchmark", "--worker", method,
               "--input", str(input_path), "--output", str(trial)]
        item = {"events": n, "repeat": rep, "method": method, "seed": seed, "command": cmd,
                "cwd": str(ROOT), "input": file_proof(input_path), "loadavg_before": os.getloadavg()}
        t0 = time.monotonic()
        try:
            response = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=min(60, max(1, total_timeout-(time.monotonic()-start))))
            item.update(exit_code=response.returncode, stdout=response.stdout, stderr=response.stderr,
                        status="PASS" if response.returncode == 0 else "FAILED")
            if response.returncode == 0:
                item["metrics"] = json.loads((trial / "metrics.json").read_text())
        except subprocess.TimeoutExpired as error:
            def decode(value):
                return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
            item.update(status="TIMEOUT", exit_code=None, timeout_seconds=min(60, total_timeout),
                        stdout=decode(error.stdout), stderr=decode(error.stderr))
        item["subprocess_wall_seconds"] = time.monotonic()-t0
        item["loadavg_after"] = os.getloadavg()
        trial.mkdir(parents=True, exist_ok=True)
        observed_bytes = sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
        record["max_postprocess_disk_observation_bytes"] = max(record["max_postprocess_disk_observation_bytes"], observed_bytes)
        item["postprocess_disk_observation_bytes"] = observed_bytes
        if observed_bytes > protocol["budgets"]["owned_disk_budget_bytes"]:
            item["status"] = "RESOURCE_LIMIT"
            item["reason"] = "owned logical file-size budget exceeded; no larger/repeated workload will run"
        # Retain compact command/metrics and proofs. Large DB/export bytes are not
        # silently represented as retained evidence; explicit inventory follows.
        omitted = []
        for path in trial.iterdir():
            if path.name in ("metrics.json", "command.json", "progress.json"):
                continue
            if path.is_file():
                omitted.append({"path": path.name, **file_proof(path), "retained": n == 100 and not warmup})
                if not (n == 100 and not warmup):
                    path.unlink()
        item["artifact_inventory"] = omitted
        dump(trial / "command.json", item)
        (warmups if warmup else trials).append(item)
        dump(output / "results.json", record)
        return item

    for method in METHODS:
        if launch(100, -1, method, 11, True)["status"] != "PASS":
            record["status"] = "FAILED_WARMUP"
            dump(output / "results.json", record)
            return record
    for n in profiles:
        previous = list(METHODS)
        profile_failed = False
        for rep in range(repeats):
            if time.monotonic()-start >= total_timeout-5:
                trials.append({"events": n, "repeat": rep, "method": "ALL", "status": "NOT_RUN", "reason": "total time budget"})
                profile_failed = True
                break
            order = list(reversed(previous)) if rep % 2 else random.Random(481+rep+n).sample(list(METHODS), len(METHODS))
            previous = order
            for method in order:
                item = launch(n, rep, method, (11, 29, 47, 71, 97)[rep])
                if item["status"] != "PASS":
                    profile_failed = True
                    break
            if profile_failed:
                trials.append({"events": n, "repeat": rep, "method": "ALL", "status": "NOT_RUN", "reason": "remaining profile repetitions stopped after recorded failure/timeout"})
                break
        if profile_failed and n < 100000:
            for later in profiles[profiles.index(n)+1:]:
                trials.append({"events": later, "repeat": -1, "method": "ALL", "status": "NOT_RUN", "reason": "larger profile stopped after smaller failure/budget"})
            break
    record["summary"], record["comparisons"] = summarize(trials)
    record["status"] = "COMPLETE" if all(t["status"] == "PASS" for t in trials) else "PARTIAL"
    record["elapsed_seconds"] = time.monotonic()-start
    children_end = resource.getrusage(resource.RUSAGE_CHILDREN)
    record["program_cost"] = {"controller_cpu_seconds": time.process_time()-controller_cpu_start,
        "worker_cpu_seconds": (children_end.ru_utime + children_end.ru_stime) - (children_start.ru_utime + children_start.ru_stime),
        "elapsed_seconds_including_warmup_inputs_hashing_cleanup_statistics": record["elapsed_seconds"],
        "retained_bytes_before_final_summaries": sum(p.stat().st_size for p in output.rglob("*") if p.is_file()),
        "physical_disk_io": "NOT_MEASURED", "ram_seconds": "NOT_MEASURED", "monetary_cost": "NOT_ESTIMATED"}
    record["completed_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    dump(output / "results.json", record)
    dump(output / "summary.json", {"status": record["status"], "data_class": "FULLY_SYNTHETIC", "repeats": repeats,
        "cases": [{"case_id": f"n{t['events']}-r{t['repeat']}-{t['method']}", "status": t["status"]} for t in trials],
        "executed_trials": sum(t["method"] in METHODS for t in trials),
        "passed_trials": sum(t["status"] == "PASS" for t in trials),
        "full_semantic_parity": False, "comparative_speed_advantage": "INCONCLUSIVE",
        "summary": record["summary"], "comparisons": record["comparisons"], "raw_evidence": "results.json"})
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("smoke", "full"), default="full")
    parser.add_argument("--profiles", type=int, nargs="+")
    parser.add_argument("--worker", choices=METHODS)
    parser.add_argument("--input", type=Path)
    args = parser.parse_args()
    if args.worker:
        resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
        resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
        resource.setrlimit(resource.RLIMIT_FSIZE, (384 * 1024**2, 384 * 1024**2))
        result = run_one(args.worker, args.input, args.output)
        print(json.dumps({"status": result["status"], "events": result["events"], "method": result["method"]}))
    else:
        result = benchmark(args.output, args.profiles or ([100] if args.mode == "smoke" else [100, 1000, 10000, 100000]))
        print(json.dumps({"status": result["status"], "results": str(args.output / "results.json")}))
    return 0 if result["status"] in ("PASS", "COMPLETE") else 3 if result["status"] == "PARTIAL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
