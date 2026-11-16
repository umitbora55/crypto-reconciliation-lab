"""Gate 2: a bounded common-output arithmetic lane and separate capacity triage.

The input contract is deliberately finite: exact generated complete static-cycle
workloads, not arbitrary financial records. All methods share validation, public
Store ingestion and common persistence/export. Only recomputation differs.
Production uses its unchanged engine with a test-owned save_run output adapter;
this is not the application's complete evidence/history service.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import resource
import sqlite3
import subprocess
import sys
import time

from validation_lab import benchmark as previous

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "contracts/benchmark-gate2-protocol.json"
METHODS = previous.METHODS
SEEDS = (11, 29, 47, 71, 97)


def write(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n")


def payload(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"


def finite_gate(data):
    previous.validate_narrow(data)
    if data['seed'] not in (0,*SEEDS):
        raise ValueError('COMMON_CONTRACT: seed outside declared finite population')
    if data != previous.workload(data["events"], data["seed"]):
        raise ValueError("COMMON_CONTRACT: only the exact declared static cycle workload is supported")


def bindings():
    names = ["validation_lab/benchmark_gate2.py", "validation_lab/benchmark.py",
             "validation_tests/test_gate2_benchmark.py",
             "crypto_reconciliation_lab/engine.py", "crypto_reconciliation_lab/store.py",
             "crypto_reconciliation_lab/model.py", "crypto_reconciliation_lab/corrections.py",
             "contracts/benchmark-gate2-protocol.json"]
    names.extend(str(p.relative_to(ROOT)) for p in (ROOT/'crypto_reconciliation_lab').rglob('*') if p.is_file() and p.suffix in ('.py','.json'))
    return {name: previous.file_proof(ROOT / name) for name in sorted(set(names))}


def sql_arithmetic(db):
    # Only accepted finite-gate inputs reach this SQL. The parser is independent
    # integer-string arithmetic; no floating cast, Decimal or Python delta loop.
    cte = """WITH raw AS (
       SELECT kind,json_extract(payload,'$.scope') AS scope,
       json_extract(payload,'$.amount') AS amount,
       json_extract(payload,'$.from_investor') AS sender,
       json_extract(payload,'$.to_investor') AS recipient,
       json_extract(payload,'$.custody') AS custody,
       json_extract(payload,'$.type') AS event_type FROM records
    ), parsed AS (SELECT *,CASE WHEN instr(amount,'.')=0 THEN CAST(amount AS INTEGER)*100
       ELSE CAST(substr(amount,1,instr(amount,'.')-1) AS INTEGER)*100
       +CAST(substr(amount,instr(amount,'.')+1)||CASE length(substr(amount,instr(amount,'.')+1))
          WHEN 1 THEN '0' ELSE '' END AS INTEGER) END AS quantity FROM raw)
    """
    balances = dict(db.execute(cte + """SELECT person,SUM(delta) FROM (
       SELECT scope AS person,quantity AS delta FROM parsed WHERE kind='opening' AND scope NOT IN ('platform','external')
       UNION ALL SELECT recipient,quantity FROM parsed WHERE kind='event' AND recipient IS NOT NULL
       UNION ALL SELECT sender,-quantity FROM parsed WHERE kind='event' AND sender IS NOT NULL
    ) GROUP BY person"""))
    custody = dict(db.execute(cte + """SELECT place,SUM(delta) FROM (
       SELECT scope AS place,quantity AS delta FROM parsed WHERE kind='opening' AND scope IN ('platform','external')
       UNION ALL SELECT custody,CASE WHEN event_type='deposit' THEN quantity ELSE -quantity END
       FROM parsed WHERE kind='event' AND custody IS NOT NULL
    ) GROUP BY place"""))
    liability = db.execute(cte + """SELECT SUM(delta) FROM (
       SELECT quantity AS delta FROM parsed WHERE kind='opening' AND scope NOT IN ('platform','external')
       UNION ALL SELECT quantity FROM parsed WHERE kind='event' AND event_type='deposit'
       UNION ALL SELECT -quantity FROM parsed WHERE kind='event' AND event_type='withdrawal'
    )""").fetchone()[0]
    return {"balances": balances, "liability": liability, "custody": custody}


def physical_io():
    path = Path("/proc/self/io")
    if not path.exists():
        return {"status": "NOT_OBSERVABLE"}
    data = dict(line.split(":", 1) for line in path.read_text().splitlines())
    return {"status": "PROCESS_COUNTERS_ONLY", **{key: int(data[key]) for key in ("read_bytes", "write_bytes", "cancelled_write_bytes")},
            "qualification": "Kernel process accounting on overlayfs; not independent physical-device writes or storage billing"}


def run_worker(method, input_path, output):
    if method not in METHODS:
        raise ValueError("unknown method")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    start, cpu_start = time.perf_counter(), time.process_time()
    phases, committed = {}, 0
    io_before = physical_io()

    def progress(name, state):
        write(output / "progress.json", {"phase": name, "state": state, "committed_receipts": committed,
              "elapsed_seconds": time.perf_counter()-start, "completed_phases": phases})

    def phase(name, fn):
        progress(name, "STARTED")
        wall, cpu = time.perf_counter(), time.process_time()
        value = fn()
        phases[name] = {"wall_seconds": time.perf_counter()-wall, "cpu_seconds": time.process_time()-cpu}
        progress(name, "COMPLETED")
        return value

    data = phase("read_input", lambda: json.loads(Path(input_path).read_text()))
    phase("validate_common_contract", lambda: finite_gate(data))
    from crypto_reconciliation_lab import Store, reconcile

    class CommonStore(Store):
        def save_run(self, result, *, fault=None):
            # The actual unchanged engine still creates traces/evidence in RAM.
            # Persist only the common projected contract, below, for every method.
            return result

    store = phase("initialize", lambda: CommonStore(output / "input.sqlite3", data["config"]))
    settings = {key: store.db.execute("PRAGMA " + key).fetchone()[0] for key in ("journal_mode", "synchronous", "page_size")}
    def ingest():
        nonlocal committed
        for envelope in data["rows"]:
            response = store.ingest(envelope["record"], envelope["received_at"])
            if response["status"] != "ACCEPTED":
                raise AssertionError(response)
            committed += 1
            if committed % 1000 == 0:
                progress("ingest", "RUNNING")
    phase("ingest", ingest)
    def compute():
        if method == "production":
            return previous.project_production(reconcile(store, data["balance_at"], data["knowledge_at"]))
        if method == "sqlite_integer":
            calculated = sql_arithmetic(store.db)
        else:
            calculated = previous.python_calculate(json.loads(row[0]) for row in store.db.execute("SELECT payload FROM records"))
        return previous.with_findings(calculated, data)
    common = phase("recompute", compute)
    if store.db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] != 0:
        raise AssertionError("unexpected rich-result persistence in common lane")
    text = payload(common)
    def persist():
        with sqlite3.connect(output / "result.sqlite3") as db:
            db.execute("CREATE TABLE common_result(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)")
            db.execute("INSERT INTO common_result VALUES(1,?)", (text,))
    phase("persist", persist)
    phase("evidence_export", lambda: (output / "export.json").write_text(text))
    phase("close", store.close)
    def verify():
        expected = previous.with_findings(previous.analytic_oracle(data["events"], data["seed"]), data)
        with sqlite3.connect(f"file:{output / 'result.sqlite3'}?mode=ro", uri=True) as db:
            saved = db.execute("SELECT payload FROM common_result WHERE id=1").fetchone()[0]
        exported = (output / "export.json").read_text()
        if common != expected or saved != payload(expected) or exported != saved:
            raise AssertionError("independent oracle/persist/export reread disagreement")
    phase("reread_verify", verify)
    io_after = physical_io()
    result = {"status": "PASS", "method": method, "events": data["events"], "rows": len(data["rows"]), "seed": data["seed"],
              "wall_seconds": time.perf_counter()-start, "cpu_seconds": time.process_time()-cpu_start,
              "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              "phases": phases, "sqlite_settings": settings, "common_output": common,
              "artifacts": {name: previous.file_proof(output / name) for name in ("input.sqlite3", "result.sqlite3", "export.json")},
              "input": {"path": str(Path(input_path).resolve()), **previous.file_proof(input_path)},
              "physical_io_before": io_before, "physical_io_after": io_after, "bindings": bindings(),
              "lane": "common_arithmetic", "evidence_history_lane": "NOT_IMPLEMENTED"}
    result["disk_bytes"] = sum(p["bytes"] for p in result["artifacts"].values())
    result["throughput_events_per_second"] = data["events"] / result["wall_seconds"]
    write(output / "metrics.json", result)
    return result


def execute(command, cwd, timeout):
    """Keep the actual post-wait POSIX status, including deadline termination."""
    start = time.monotonic()
    process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            process.kill()
        except ProcessLookupError:
            pass
        stdout, stderr = process.communicate()
    return {"exit_code": process.returncode, "timed_out": timed_out, "stdout": stdout, "stderr": stderr,
            "subprocess_wall_seconds": time.monotonic()-start,
            "status": "TIMEOUT" if timed_out else "PASS" if process.returncode == 0 else "FAILED",
            "timeout_seconds": timeout}


def parity(trials, profiles):
    if not profiles or len(set(profiles)) != len(profiles):
        raise ValueError("nonempty unique profile inventory required")
    rows = []
    for n in profiles:
        for repeat in range(5):
            group = [t for t in trials if t["events"] == n and t["repeat"] == repeat]
            if len(group) != 3 or {t["method"] for t in group} != set(METHODS) or any(t["status"] != "PASS" for t in group):
                rows.append({"events": n, "repeat": repeat, "status": "NOT_ESTABLISHED"})
                continue
            base = group[0]["metrics"]
            equal = all(t["metrics"][key] == base[key] for t in group for key in ("input", "artifacts", "sqlite_settings", "common_output", "bindings"))
            rows.append({"events": n, "repeat": repeat,
                         "status": "EQUIVALENT_COMMON_ARITHMETIC" if equal else "PARITY_FAILURE"})
    return rows


def validate_record_inventory(record, expected_mode, expected_bindings, evidence_root=None):
    """Consistency gate with caller-selected mode and reviewed source bindings.

    This is not a cryptographic attestation that timings happened. Raw commands,
    independently selected source pins and the external evidence manifest remain
    necessary provenance; a self-issued replacement pin cannot establish trust.
    """
    if expected_mode not in ('smoke','full','triage') or record.get('mode') != expected_mode:
        raise ValueError('BENCHMARK_SCOPE: wrong externally selected mode')
    if record.get('data_class')!='FULLY_SYNTHETIC' or record.get('institutional_cost_savings')!='NOT_PROVEN' or record.get('institutional_risk_reduction')!='NOT_PROVEN':
        raise ValueError('BENCHMARK_SCOPE: unsupported real-data or institutional claim')
    if record.get('bindings') != expected_bindings:
        raise ValueError('BENCHMARK_SCOPE: source binding mismatch')
    profiles = [100] if expected_mode=='smoke' else [100,1000,10000]
    expected = {(n,0,'production') for n in (100000,25000,50000)} if expected_mode=='triage' else {(n,r,m) for n in profiles for r in range(5) for m in METHODS}
    trials = record.get('trials')
    if not isinstance(trials,list) or not trials:
        raise ValueError('BENCHMARK_SCOPE: empty/missing trial inventory')
    identities = [(t.get('events'),t.get('repeat'),t.get('method')) for t in trials]
    if len(identities)!=len(set(identities)) or set(identities)!=expected:
        raise ValueError('BENCHMARK_SCOPE: omitted/duplicate/substituted trial identity')
    evidence_root=Path(evidence_root).resolve() if evidence_root is not None else None
    input_cache={}
    def check_proof(proof):
        if not isinstance(proof,dict) or set(proof)!={'sha256','bytes'} or type(proof.get('bytes')) is not int or proof['bytes']<=0:
            raise ValueError('BENCHMARK_SCOPE: missing/nonpositive byte proof')
        digest=proof.get('sha256')
        if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('BENCHMARK_SCOPE: invalid SHA256 proof')
    for trial in trials:
        expected_seed=11 if expected_mode=='triage' else SEEDS[trial['repeat']]
        if trial.get('seed')!=expected_seed:
            raise ValueError('BENCHMARK_SCOPE: seed substitution')
        status=trial.get('status')
        if status not in ('PASS','FAILED','TIMEOUT','NOT_RUN','BINDING_FAILURE','RESOURCE_LIMIT'):
            raise ValueError('BENCHMARK_SCOPE: invalid outcome')
        if status!='NOT_RUN' and type(trial.get('exit_code')) is not int:
            raise ValueError('BENCHMARK_SCOPE: missing actual process exit')
        if status!='NOT_RUN':
            if evidence_root is None:
                raise ValueError('BENCHMARK_SCOPE: caller-selected evidence root required')
            observed_input=trial.get('input')
            if not isinstance(observed_input,dict) or set(observed_input)!={'path','sha256','bytes'}:
                raise ValueError('BENCHMARK_SCOPE: missing input path/hash/bytes')
            check_proof({k:observed_input[k] for k in ('sha256','bytes')})
            expected_path=evidence_root/'inputs'/f"events{trial['events']}-seed{trial['seed']}.json"
            if observed_input['path']!=str(expected_path) or not expected_path.is_file() or expected_path.resolve()!=expected_path:
                raise ValueError('BENCHMARK_SCOPE: retained input path differs from selected evidence root')
            if str(expected_path) not in input_cache:
                actual_data=json.loads(expected_path.read_text())
                finite_gate(actual_data)
                if (actual_data['events'],actual_data['seed'])!=(trial['events'],trial['seed']):
                    raise ValueError('BENCHMARK_SCOPE: actual input population differs')
                input_cache[str(expected_path)]=previous.file_proof(expected_path)
            if input_cache[str(expected_path)]!={k:observed_input[k] for k in ('sha256','bytes')}:
                raise ValueError('BENCHMARK_SCOPE: actual input bytes differ from observation')
            folder=evidence_root/'trials'/f"n{trial['events']}-r{trial['repeat']}-{trial['method']}"
            if not folder.is_dir() or folder.resolve()!=folder or not (folder/'command.json').is_file():
                raise ValueError('BENCHMARK_SCOPE: original command evidence missing')
            if json.loads((folder/'command.json').read_text())!=json.loads(payload(trial)):
                raise ValueError('BENCHMARK_SCOPE: original command/stdout/stderr record differs')
            command=trial.get('command')
            tail=['-B','-m','validation_lab.benchmark_gate2','--worker',trial['method'],'--input',str(expected_path),'--output',str(folder)]
            if not isinstance(command,list) or not command or not isinstance(command[0],str) or not Path(command[0]).is_absolute() or command[1:]!=tail:
                raise ValueError('BENCHMARK_SCOPE: missing/wrong actual command linkage')
            if not isinstance(trial.get('cwd'),str) or not Path(trial['cwd']).is_absolute() or any(not isinstance(trial.get(k),str) for k in ('stdout','stderr')):
                raise ValueError('BENCHMARK_SCOPE: missing cwd/original stdout/stderr')
            try:
                begun=datetime.strptime(trial['started_utc'],'%Y-%m-%dT%H:%M:%SZ')
                ended=datetime.strptime(trial['completed_utc'],'%Y-%m-%dT%H:%M:%SZ')
            except (ValueError,KeyError,TypeError) as exc:
                raise ValueError('BENCHMARK_SCOPE: missing/invalid UTC observations') from exc
            if ended<begun or type(trial.get('timed_out')) is not bool:
                raise ValueError('BENCHMARK_SCOPE: inconsistent time/timeout evidence')
            if status=='TIMEOUT' and not trial['timed_out'] or status=='PASS' and trial['timed_out']:
                raise ValueError('BENCHMARK_SCOPE: timeout relabeling')
        if status=='PASS':
            metric=trial.get('metrics',{})
            if not (folder/'metrics.json').is_file() or json.loads((folder/'metrics.json').read_text())!=metric:
                raise ValueError('BENCHMARK_SCOPE: original metric record differs')
            if trial['exit_code']!=0 or metric.get('status')!='PASS' or any(metric.get(k)!=trial[k] for k in ('events','method','seed')):
                raise ValueError('BENCHMARK_SCOPE: false success or mismatched metric identity')
            if metric.get('rows')!=trial['events']+17 or metric.get('bindings')!=expected_bindings:
                raise ValueError('BENCHMARK_SCOPE: row/source binding mismatch')
            if metric.get('input')!=trial.get('input'):
                raise ValueError('BENCHMARK_SCOPE: input path/hash/size mismatch')
            if set(metric.get('artifacts',{}))!={'input.sqlite3','result.sqlite3','export.json'}:
                raise ValueError('BENCHMARK_SCOPE: incomplete persisted/exported contract')
            for proof in metric['artifacts'].values(): check_proof(proof)
            settings=metric.get('sqlite_settings')
            if not isinstance(settings,dict) or set(settings)!={'journal_mode','synchronous','page_size'} or settings['journal_mode']!='delete' or settings['synchronous']!=2 or type(settings['page_size']) is not int or not 512<=settings['page_size']<=65536 or settings['page_size']&(settings['page_size']-1):
                raise ValueError('BENCHMARK_SCOPE: missing/invalid observed SQLite settings')
            expected_phases={'read_input','validate_common_contract','initialize','ingest','recompute','persist','evidence_export','close','reread_verify'}
            if set(metric.get('phases',{}))!=expected_phases:
                raise ValueError('BENCHMARK_SCOPE: omitted/substituted measured phase')
            for values in [metric,*metric['phases'].values()]:
                for key in ('wall_seconds','cpu_seconds'):
                    number=values.get(key)
                    if type(number) not in (float,int) or not math.isfinite(number) or number<0:
                        raise ValueError('BENCHMARK_SCOPE: invalid resource measurement')
            if metric['wall_seconds']<=0 or metric.get('throughput_events_per_second')!=trial['events']/metric['wall_seconds']:
                raise ValueError('BENCHMARK_SCOPE: invalid elapsed time or throughput denominator')
            expected_result=previous.with_findings(previous.analytic_oracle(trial['events'],trial['seed']),previous.workload(trial['events'],trial['seed']))
            if metric.get('common_output')!=expected_result:
                raise ValueError('BENCHMARK_SCOPE: independent integer oracle disagreement')
            try:
                stdout=json.loads(trial['stdout'])
            except ValueError as exc:
                raise ValueError('BENCHMARK_SCOPE: successful original stdout missing') from exc
            if stdout!={'status':'PASS','output':str(folder)}:
                raise ValueError('BENCHMARK_SCOPE: successful stdout/output path disagrees')
            expected_export=payload(expected_result).encode()
            if metric['artifacts']['export.json']!={'sha256':hashlib.sha256(expected_export).hexdigest(),'bytes':len(expected_export)}:
                raise ValueError('BENCHMARK_SCOPE: common export proof disagrees with oracle bytes')
            inventory=trial.get('artifact_inventory')
            if not isinstance(inventory,list) or len(inventory)!=3 or {a.get('name') for a in inventory}!=set(metric['artifacts']):
                raise ValueError('BENCHMARK_SCOPE: missing/duplicate retention inventory')
            for artifact in inventory:
                proof=metric['artifacts'][artifact['name']]
                if {k:artifact.get(k) for k in ('sha256','bytes')}!=proof or artifact.get('retained') is not (trial['events']==100):
                    raise ValueError('BENCHMARK_SCOPE: retention proof/status mismatch')
                if trial['events']==100:
                    path=folder/artifact['name']
                    if not path.is_file() or path.resolve()!=path or previous.file_proof(path)!=proof:
                        raise ValueError('BENCHMARK_SCOPE: retained100-event artifact bytes changed')
            if trial['events']==100:
                if (folder/'export.json').read_bytes()!=expected_export:
                    raise ValueError('BENCHMARK_SCOPE: retained JSON readback disagreement')
                with sqlite3.connect(f"file:{folder/'result.sqlite3'}?mode=ro&immutable=1",uri=True) as db:
                    if db.execute('SELECT id,payload FROM common_result').fetchall()!=[(1,expected_export.decode())]:
                        raise ValueError('BENCHMARK_SCOPE: retained SQLite result readback disagreement')
                with sqlite3.connect(f"file:{folder/'input.sqlite3'}?mode=ro&immutable=1",uri=True) as db:
                    if db.execute("SELECT COUNT(*) FROM receipts WHERE status='ACCEPTED'").fetchone()[0]!=metric['rows'] or db.execute('SELECT COUNT(*) FROM records').fetchone()[0]!=metric['rows'] or db.execute('SELECT COUNT(*) FROM runs').fetchone()[0]!=0:
                        raise ValueError('BENCHMARK_SCOPE: retained ingestion readback disagreement')
    if expected_mode!='triage':
        if record.get('parity')!=parity(trials,profiles):
            raise ValueError('BENCHMARK_SCOPE: parity inventory disagrees with trials')
        equivalent=all(p['status']=='EQUIVALENT_COMMON_ARITHMETIC' for p in record['parity'])
        if record.get('comparative_status')!=('EQUIVALENT_COMMON_ARITHMETIC' if equivalent else 'INCONCLUSIVE'):
            raise ValueError('BENCHMARK_SCOPE: incorrect equivalence claim')
        expected_summary,expected_comparisons=previous.summarize(trials)
        for row in expected_comparisons:
            row['semantic_parity']='EQUIVALENT_COMMON_ARITHMETIC' if all(p['status']=='EQUIVALENT_COMMON_ARITHMETIC' for p in record['parity'] if p['events']==row['events']) else 'NOT_ESTABLISHED'
            row['speed_advantage']='DESCRIPTIVE_COMMON_TASK_ONLY; FULL_PRODUCT_INCONCLUSIVE'
        if record.get('summary')!=expected_summary or record.get('comparisons')!=expected_comparisons:
            raise ValueError('BENCHMARK_SCOPE: derived summaries disagree with actual PASS trials')
    complete=all(t['status']=='PASS' for t in trials) and (expected_mode=='triage' or record['comparative_status']=='EQUIVALENT_COMMON_ARITHMETIC')
    if record.get('status')!=('COMPLETE' if complete else 'PARTIAL'):
        raise ValueError('BENCHMARK_SCOPE: overall status disguises partial work')
    return {'status':'PASS','expected':len(expected),'observed':len(trials),'measurement_authenticity':'NOT_ATTESTED'}


def program(output, mode="full"):
    if mode not in ("smoke", "full", "triage"):
        raise ValueError("unsupported mode")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "inputs").mkdir()
    (output / "trials").mkdir()
    protocol = json.loads(PROTOCOL.read_text())
    original_bindings = bindings()
    write(output / "protocol.json", protocol)
    start, cpu_start = time.monotonic(), time.process_time()
    children_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    budget = protocol["budgets"]["triage_seconds" if mode == "triage" else "common_seconds"]
    record = {"status": "RUNNING", "format": "benchmark-gate2-v1", "mode": mode,
        "data_class": "FULLY_SYNTHETIC", "bindings": original_bindings,
        "base_research_commit": "f3dff8dd00837ac7ce6e9bb687dd4861f790cbac",
        "git_head_at_start": subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "command": sys.argv, "cwd": str(ROOT),
        "host": {"python": sys.version, "platform": platform.platform(), "machine": platform.machine(), "sqlite": sqlite3.sqlite_version,
                 "cpu_affinity": sorted(os.sched_getaffinity(0)), "loadavg": os.getloadavg(),
                 "cgroup_limits": {name: (Path('/sys/fs/cgroup')/name).read_text().strip() for name in ('cpu.max','memory.max') if (Path('/sys/fs/cgroup')/name).exists()}},
        "trials": [], "warmups": [], "generation": [], "max_postprocess_disk_bytes": 0,
        "equal_evidence_history_lane": {"status": "NOT_IMPLEMENTED", "parity": "NARROWER_SCOPE", "speed_advantage": "INCONCLUSIVE"},
        "institutional_cost_savings": "NOT_PROVEN", "institutional_risk_reduction": "NOT_PROVEN"}
    write(output / "results.json", record)
    def generate(n, seed):
        path = output / "inputs" / f"events{n}-seed{seed}.json"
        if not path.exists():
            wall, cpu = time.perf_counter(), time.process_time()
            write(path, previous.workload(n, seed))
            record["generation"].append({"events": n, "seed": seed, "path": str(path), **previous.file_proof(path),
                "wall_seconds": time.perf_counter()-wall, "cpu_seconds": time.process_time()-cpu,
                "allocation": "one shared paired input; not charged three times"})
        return path
    def launch(n, repeat, method, seed, warmup=False):
        path = generate(n, seed)
        label = f"{'warmup-' if warmup else ''}n{n}-r{repeat}-{method}"
        folder = output / "trials" / label
        command = [sys.executable, "-B", "-m", "validation_lab.benchmark_gate2", "--worker", method, "--input", str(path), "--output", str(folder)]
        remaining = budget-(time.monotonic()-start)
        if remaining <= 1:
            item = {"events": n, "repeat": repeat, "method": method, "seed": seed, "status": "NOT_RUN", "reason": "program wall budget", "exit_code": None}
        else:
            item = {"events": n, "repeat": repeat, "method": method, "seed": seed,
                    "command": command, "cwd": str(ROOT), "input": {"path": str(path), **previous.file_proof(path)},
                    "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "loadavg_before": os.getloadavg(),
                    **execute(command, ROOT, min(60.0, remaining))}
            folder.mkdir(exist_ok=True)
            if item["status"] == "PASS":
                item["metrics"] = json.loads((folder / "metrics.json").read_text())
                if item["metrics"]["bindings"] != original_bindings:
                    item.update(status="BINDING_FAILURE", reason="executed source differs from preregistered source")
            progress = folder / "progress.json"
            if progress.exists():
                item["last_progress"] = json.loads(progress.read_text())
            observed = sum(p.stat().st_size for p in output.rglob('*') if p.is_file())
            record["max_postprocess_disk_bytes"] = max(record["max_postprocess_disk_bytes"], observed)
            if observed > 1024**3:
                item.update(status="RESOURCE_LIMIT", reason="owned disk budget exceeded")
            inventory = []
            for artifact in folder.iterdir():
                if artifact.is_file() and artifact.name not in ("metrics.json", "progress.json", "command.json"):
                    keep = n == 100 and not warmup
                    inventory.append({"name": artifact.name, **previous.file_proof(artifact), "retained": keep})
                    if not keep:
                        artifact.unlink()
            item["artifact_inventory"] = inventory
            item["completed_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            write(folder / "command.json", item)
        record["warmups" if warmup else "trials"].append(item)
        write(output / "results.json", record)
        return item
    profiles = [100] if mode == "smoke" else [100, 1000, 10000]
    if mode == "triage":
        # Reproduce the target deadline first, then localize below it. A smaller
        # successful run cannot replace or erase the censored 100k attempt.
        for n in (100000, 25000, 50000):
            launch(n, 0, "production", 11)
        record["comparative_status"] = "NOT_A_COMPARISON"
    else:
        warm_ok = all(launch(100, -1, method, 11, True)["status"] == "PASS" for method in METHODS)
        if warm_ok:
            for n in profiles:
                prior_order = list(METHODS)
                stopped = False
                for repeat, seed in enumerate(SEEDS):
                    order = list(reversed(prior_order)) if repeat % 2 else random.Random(871+n+repeat).sample(list(METHODS), 3)
                    prior_order = order
                    for method in order:
                        if launch(n, repeat, method, seed)["status"] != "PASS":
                            stopped = True
                            break
                    if stopped:
                        break
                if stopped:
                    break
        seen = {(t["events"],t["repeat"],t["method"]) for t in record["trials"]}
        for n in profiles:
            for repeat, seed in enumerate(SEEDS):
                for method in METHODS:
                    if (n,repeat,method) not in seen:
                        record["trials"].append({"events": n, "repeat": repeat, "method": method, "seed": seed,
                            "status": "NOT_RUN", "reason": "earlier failure or finite program budget", "exit_code": None})
        record["parity"] = parity(record["trials"], profiles)
        record["comparative_status"] = "EQUIVALENT_COMMON_ARITHMETIC" if record["parity"] and all(p["status"] == "EQUIVALENT_COMMON_ARITHMETIC" for p in record["parity"]) else "INCONCLUSIVE"
        record["summary"], record["comparisons"] = previous.summarize(record["trials"])
        for row in record["comparisons"]:
            row["semantic_parity"] = "EQUIVALENT_COMMON_ARITHMETIC" if all(p["status"] == "EQUIVALENT_COMMON_ARITHMETIC" for p in record["parity"] if p["events"] == row["events"]) else "NOT_ESTABLISHED"
            row["speed_advantage"] = "DESCRIPTIVE_COMMON_TASK_ONLY; FULL_PRODUCT_INCONCLUSIVE"
    expected = 3 if mode == "triage" else len(profiles)*15
    record["status"] = "COMPLETE" if len(record["trials"]) == expected and all(t["status"] == "PASS" for t in record["trials"]) and (mode == "triage" or record["comparative_status"] == "EQUIVALENT_COMMON_ARITHMETIC") else "PARTIAL"
    children_end = resource.getrusage(resource.RUSAGE_CHILDREN)
    record["program_cost"] = {"wall_seconds": time.monotonic()-start, "controller_cpu_seconds": time.process_time()-cpu_start,
        "worker_cpu_seconds": children_end.ru_utime+children_end.ru_stime-children_start.ru_utime-children_start.ru_stime,
        "money": "NOT_ESTIMATED", "ram_seconds": "NOT_MEASURED", "physical_device_io": "NOT_OBSERVABLE"}
    record["completed_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    record["source_unchanged"] = bindings() == original_bindings
    if not record["source_unchanged"]:
        record["status"] = "BINDING_FAILURE"
    if record['source_unchanged']:
        record['inventory_validation']=validate_record_inventory(record,mode,original_bindings,output)
    write(output / "results.json", record)
    write(output / "summary.json", {"status": record["status"], "mode": mode, "data_class": "FULLY_SYNTHETIC",
          "comparative_status": record["comparative_status"], "raw_evidence": "results.json",
          "cases": [{"case_id": f"{t['events']}-{t['repeat']}-{t['method']}", "status": t["status"], "exit_code": t["exit_code"]} for t in record["trials"]],
          "expected_timed_attempts": expected, "executed_timed_attempts": sum(t["status"] != "NOT_RUN" for t in record["trials"]),
          "equal_evidence_history_lane": record["equal_evidence_history_lane"], "program_cost": record["program_cost"]})
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("smoke", "full", "triage"), default="full")
    parser.add_argument("--worker", choices=METHODS)
    parser.add_argument("--input", type=Path)
    args = parser.parse_args()
    if args.worker:
        resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
        resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
        resource.setrlimit(resource.RLIMIT_FSIZE, (384*1024**2, 384*1024**2))
        result = run_worker(args.worker, args.input, args.output)
    else:
        result = program(args.output, args.mode)
    print(json.dumps({"status": result["status"], "output": str(args.output)}))
    return 0 if result["status"] in ("PASS", "COMPLETE") else 3


if __name__ == "__main__":
    raise SystemExit(main())
