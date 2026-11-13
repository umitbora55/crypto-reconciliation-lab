"""Parent-side sampled resource supervision; peak RSS alone is not enforcement."""
from dataclasses import asdict,dataclass
import math
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from .common import load

@dataclass(frozen=True)
class Budgets:
    phase_seconds:float=120
    total_seconds:float=1200
    rss_bytes:int=1024**3
    trial_bytes:int=512*1024**2
    temporary_bytes:int=2*1024**3
    poll_seconds:float=0.2

    def __post_init__(self):
        for value in asdict(self).values():
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
                raise ValueError('all budgets must be positive finite values')


def current_rss(pid):
    try:
        p=subprocess.run(['ps','-o','rss=','-p',str(pid)],capture_output=True,text=True,timeout=1)
        value=p.stdout.strip()
        return int(value)*1024 if p.returncode==0 and value.isdigit() else None
    except (OSError,subprocess.TimeoutExpired):return None


def directory_bytes(root):
    total=0
    for p in Path(root).rglob('*'):
        try:
            if p.is_file():total+=p.stat().st_size
        except FileNotFoundError:pass  # A SQLite journal may disappear between samples.
    return total


def stop(process):
    if process.poll() is not None:return
    try:os.killpg(process.pid,signal.SIGTERM)
    except ProcessLookupError:return
    try:process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        process.wait(timeout=2)


def supervise(command,cwd,trial,temporary_root,budgets,deadline=None,env=None):
    from .outcomes import correctness_of
    trial=Path(trial);trial.mkdir(parents=True,exist_ok=False)
    start=time.monotonic();deadline=deadline if deadline is not None else start+budgets.total_seconds
    if start>=deadline:return dict(status='NOT_ATTEMPTED_BUDGET',completion_state='NOT_ATTEMPTED_BUDGET',correctness='UNKNOWN',reason='total deadline exhausted',exit_code=None,last_observation=None)
    forced=None;reason=None;peak_sample=None;last=None;phase_name='startup';phase_start=start
    observed_failure=None;parse_errors=[];violations=[];last_child=None
    def read_child():
        nonlocal observed_failure,last_child
        path=trial/'result.json'
        if not path.exists():return None
        try:
            child=load(path)
            if not isinstance(child,dict):raise ValueError('worker result must be an object')
            last_child=child
            if correctness_of(child,child.get('worker_role','trial'))=='FAILED':observed_failure=child
            return child
        except (ValueError,OSError) as exc:
            error=repr(exc)
            if error not in parse_errors:parse_errors.append(error)
            return None
    with (trial/'stdout.txt').open('w') as stdout,(trial/'stderr.txt').open('w') as stderr:
        process=subprocess.Popen(list(map(str,command)),cwd=cwd,env=env,stdout=stdout,stderr=stderr,start_new_session=True)
        try:
            while True:
                now=time.monotonic();read_child()
                path=trial/'phase.json'
                if path.exists():
                    try:
                        data=load(path)
                        if not isinstance(data,dict) or not isinstance(data.get('phase'),str) or type(data.get('started_monotonic')) not in (int,float) or not math.isfinite(data['started_monotonic']):raise ValueError('invalid worker phase')
                        phase_name=data['phase'];phase_start=data['started_monotonic']
                    except (ValueError,OSError) as exc:
                        error='phase: '+repr(exc)
                        if error not in parse_errors:parse_errors.append(error)
                rss=current_rss(process.pid)
                if rss is not None:peak_sample=max(peak_sample or 0,rss)
                size=directory_bytes(trial);aggregate=directory_bytes(temporary_root)
                last=dict(phase=phase_name,phase_elapsed_seconds=now-phase_start,rss_bytes=rss,trial_bytes=size,temporary_bytes=aggregate,elapsed_seconds=now-start)
                if now>=deadline or now-phase_start>budgets.phase_seconds:
                    forced='TIMED_OUT';reason='total wall-clock deadline' if now>=deadline else 'phase wall-clock deadline'
                elif (rss is not None and rss>budgets.rss_bytes) or size>budgets.trial_bytes or aggregate>budgets.temporary_bytes:
                    forced='RESOURCE_LIMIT';reason='RSS target' if rss is not None and rss>budgets.rss_bytes else 'trial disk budget' if size>budgets.trial_bytes else 'temporary tree budget'
                if forced:
                    violations.append(dict(status=forced,reason=reason,method='sampled',observation=last));stop(process);break
                if process.poll() is not None:break
                time.sleep(min(budgets.poll_seconds,max(0.001,deadline-time.monotonic())))
        finally:
            if process.poll() is None:stop(process)
    final=read_child();child=final or last_child
    worker_status=child.get('status','ERROR') if child else 'ERROR'
    completion=forced or ('COMPLETED' if worker_status=='CORRECTNESS_FAILED' else worker_status)
    if completion not in ('COMPLETED','TIMED_OUT','RESOURCE_LIMIT','ERROR'):completion='ERROR'
    if not forced and process.returncode!=0 and worker_status=='COMPLETED':completion='ERROR';reason='nonzero worker exit'
    if child:
        peak=child.get('peak_rss_bytes')
        if type(peak) in (int,float) and peak>budgets.rss_bytes:
            detail='post-run peak RSS exceeds target (not a hard cap)'
            violations.append(dict(status='RESOURCE_LIMIT',reason=detail,method='post-run',peak_rss_bytes=peak))
            if not forced:completion='RESOURCE_LIMIT';reason=detail
        timings=child.get('timings',{})
        if isinstance(timings,dict) and any(type(t) in (int,float) and t>budgets.phase_seconds for t in timings.values()):
            detail='completed phase exceeded budget between parent samples'
            violations.append(dict(status='TIMED_OUT',reason=detail,method='post-run',timings=timings))
            if not forced:completion='TIMED_OUT';reason=detail
    role=child.get('worker_role','trial') if child else 'trial'
    correctness='FAILED' if observed_failure is not None else correctness_of(child,role)
    status='CORRECTNESS_FAILED' if correctness=='FAILED' else completion
    return dict(status=status,completion_state=completion,correctness=correctness,reason=reason,exit_code=process.returncode,command=list(map(str,command)),cwd=str(cwd),
                last_observation=last,result_parse_error=parse_errors[-1] if parse_errors else None,result_parse_errors=parse_errors,peak_sampled_rss_bytes=peak_sample,worker=child,
                observed_correctness_failure=observed_failure,violations=violations,termination_reason=reason if forced else None,
                elapsed_seconds=time.monotonic()-start,monitoring=dict(wall_clock='sampled watchdog, terminates worker process group',
                rss='ps current RSS in KiB converted to bytes; sampled target, not hard cap',disk='periodic recursive byte sum; temporary spikes may be missed',
                peak_rss='worker getrusage post-run observation, not enforcement',poll_seconds=budgets.poll_seconds))
