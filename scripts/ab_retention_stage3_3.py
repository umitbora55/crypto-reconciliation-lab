"""Bounded final retention of one newly owned system-temporary A/B tree."""
import argparse
import hashlib
import json
import os
import platform
import resource
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

MARKER = 'STAGE3_3_AB_OWNED'
MARKER_TEXT = 'Owned Stage 3.3 A/B runtime; never remove another directory.\n'

def sha_stream(stream):
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(block)
    return digest.hexdigest()

def file_sha(path):
    with Path(path).open('rb') as stream:
        return sha_stream(stream)

def directory_bytes(path):
    total = 0
    if not Path(path).exists():
        return total
    for item in Path(path).rglob('*'):
        try:
            if item.is_file():
                total += item.stat().st_size
        except FileNotFoundError:
            pass
    return total

def copied_file(source, destination):
    """Verify the fsynced destination through the same open descriptor."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with source.open('rb') as incoming, destination.open('x+b') as outgoing:
        for block in iter(lambda: incoming.read(1024 * 1024), b''):
            digest.update(block); outgoing.write(block); size += len(block)
        outgoing.flush(); os.fsync(outgoing.fileno()); outgoing.seek(0)
        expected = digest.hexdigest(); actual = sha_stream(outgoing)
        if expected != actual or outgoing.tell() != size:
            raise ValueError('retained file hash/size differs: ' + str(source))
    os.chmod(destination, source.stat().st_mode & 0o777)
    return dict(bytes=size, sha256=actual, verified_from_open_destination=True)

def copy_worker(source, destination, owned):
    source, destination, owned = map(lambda p: Path(p).resolve(), (source, destination, owned))
    started, cpu = time.monotonic(), time.process_time()
    record = dict(status='RUNNING', verified=False, cleanup_state='NOT_STARTED', files=[],
        source=str(source), destination=str(destination), owned_runtime=str(owned),
        script_sha256=file_sha(__file__), dont_write_bytecode=sys.dont_write_bytecode,
        pycache_prefix=sys.pycache_prefix, verification='streamed source hash equals fsynced destination reread on the same open descriptor')
    def emit():
        raw=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        record['peak_rss_bytes']=int(raw) if platform.system()=='Darwin' else int(raw)*1024 if platform.system()=='Linux' else None
        record['peak_rss_method']='getrusage peak; macOS bytes, Linux KiB converted to bytes'
        record['worker_elapsed_seconds'] = time.monotonic() - started
        record['process_cpu_seconds'] = time.process_time() - cpu
        print(json.dumps(record, sort_keys=True), flush=True)
    try:
        if not source.is_relative_to(owned) or owned == source or (owned/MARKER).read_text() != MARKER_TEXT:
            raise ValueError('runtime ownership marker or source scope differs')
        if destination.is_relative_to(owned) or owned.is_relative_to(destination):
            raise ValueError('runtime and retained destination must be separate trees')
        copying, copying_cpu = time.monotonic(), time.process_time()
        for path in sorted(source.rglob('*')):
            if path.is_symlink():
                raise ValueError('runtime symlink cannot be retained')
            if not path.is_file():
                continue
            relative = path.relative_to(source)
            target = Path('runtime-'+relative.name) if str(relative) in ('ab.json','ab.md') else relative
            item = copied_file(path, destination/target)
            item.update(source_path=str(relative), retained_path=str(target))
            record['files'].append(item)
        record.update(verified=True, status='COPIED', copy_seconds=time.monotonic()-copying,
            copy_process_cpu_seconds=time.process_time()-copying_cpu)
        # Preserve known verification before any failure or budget stop in cleanup.
        emit()
        record.update(status='COMPLETED',cleanup_state='DEFERRED_TO_FINALIZATION')
        emit();return 0
    except Exception as exc:
        record.update(status='ERROR', error=repr(exc), traceback=traceback.format_exc())
        if record['verified']:
            record['cleanup_state']='ERROR'
        emit(); return 2

def stop(process):
    process.terminate()
    try:
        return process.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        try:return process.communicate(timeout=2)
        except subprocess.TimeoutExpired as exc:
            return exc.output or '',exc.stderr or ''

def retain_runtime(script, python, flags, source, destination, owned, budgets, deadline, rss_reader, finalize_job=None):
    """Copy and cleanup share the original deadline and a sampled combined-tree cap."""
    started=time.monotonic()
    command=[str(python),*flags,str(script),'--source',str(source),'--destination',str(destination),'--owned-runtime',str(owned)]
    if finalize_job is not None:command=[str(python),*flags,str(script),'--finalize-job',str(finalize_job)]
    result=dict(status='RUNNING',completion_state='RUNNING',verified=False,command=command,
        original_deadline_monotonic=deadline,phase_seconds=budgets['phase_seconds'],
        temporary_bytes_limit=budgets['temporary_bytes'],rss_bytes_limit=budgets['rss_bytes'],
        sampled=True,peak_combined_tree_bytes=0,peak_rss_bytes=None,exit_code=None)
    def observation(pid=None):
        runtime_bytes=directory_bytes(owned);retained_bytes=directory_bytes(destination)
        row=dict(elapsed_seconds=time.monotonic()-started,runtime_bytes=runtime_bytes,
            retained_bytes=retained_bytes,combined_tree_bytes=runtime_bytes+retained_bytes,
            rss_bytes=rss_reader(pid) if pid is not None else None)
        result['last_observation']=row
        result['peak_combined_tree_bytes']=max(result['peak_combined_tree_bytes'],row['combined_tree_bytes'])
        if row['rss_bytes'] is not None:
            result['peak_rss_bytes']=max(result['peak_rss_bytes'] or 0,row['rss_bytes'])
        return row
    def violation(row):
        if time.monotonic()>=deadline:return 'TIMED_OUT','original shared deadline during final retention/cleanup'
        if row['elapsed_seconds']>=budgets['phase_seconds']:return 'TIMED_OUT','retention/cleanup phase budget'
        if row['combined_tree_bytes']>budgets['temporary_bytes']:return 'RESOURCE_LIMIT','combined runtime and retained destination bytes'
        if row['rss_bytes'] is not None and row['rss_bytes']>budgets['rss_bytes']:return 'RESOURCE_LIMIT','retention worker RSS'
        return None
    early=violation(observation())
    if early:
        result.update(status=early[0],completion_state=early[0],reason=early[1],elapsed_seconds=time.monotonic()-started)
        return result
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
    output=errors='';limit=None
    while True:
        try:
            output,errors=process.communicate(timeout=budgets['poll_seconds'])
            limit=violation(observation())
            break
        except subprocess.TimeoutExpired:
            limit=violation(observation(process.pid))
            if limit:
                output,errors=stop(process)
                break
    if isinstance(output,bytes):output=output.decode('utf-8',errors='replace')
    if isinstance(errors,bytes):errors=errors.decode('utf-8',errors='replace')
    result.update(exit_code=process.returncode,elapsed_seconds=time.monotonic()-started,stderr=errors,termination_complete=process.poll() is not None)
    snapshots=[]
    for line in output.splitlines():
        try:snapshots.append(json.loads(line))
        except json.JSONDecodeError:result['malformed_stdout']=output
    worker=snapshots[-1] if snapshots else None
    result['worker']=worker
    result['verified']=any(row.get('verified') is True for row in snapshots)
    if worker and worker.get('peak_rss_bytes') is not None:
        result['peak_rss_bytes']=max(result['peak_rss_bytes'] or 0,worker['peak_rss_bytes'])
        if result['peak_rss_bytes']>budgets['rss_bytes'] and not limit:limit=('RESOURCE_LIMIT','retention worker peak RSS')
    if limit:
        result.update(status=limit[0],completion_state=limit[0],reason=limit[1])
    elif process.returncode==0 and worker and worker.get('status')=='COMPLETED' and result['verified']:
        result.update(status='COMPLETED',completion_state='COMPLETED')
    else:
        result.update(status='ERROR',completion_state='ERROR',reason='retention worker did not complete verified copy and cleanup')
    return result

def write_artifact(path, data):
    path=Path(path);temporary=path.with_name(path.name+'.tmp')
    with temporary.open('w+b') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno());stream.seek(0)
        digest=sha_stream(stream)
        if digest!=hashlib.sha256(data).hexdigest():raise ValueError('final report destination verification differs')
    temporary.replace(path)
    return digest


def finalize_worker(job):
    started,cpu=time.monotonic(),time.process_time()
    destination=Path(job['destination']);owned=Path(job['owned_runtime']);report=job['report']
    record=dict(status='RUNNING',verified=False,cleanup_state='NOT_REQUESTED',cleanup_seconds=0,
        runtime_preserved=owned.exists(),original_deadline_monotonic=job['deadline'],
        script_sha256=file_sha(__file__),dont_write_bytecode=sys.dont_write_bytecode,pycache_prefix=sys.pycache_prefix)
    def emit():
        record['worker_elapsed_seconds']=time.monotonic()-started
        record['process_cpu_seconds']=time.process_time()-cpu
        raw=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        record['peak_rss_bytes']=int(raw) if platform.system()=='Darwin' else int(raw)*1024 if platform.system()=='Linux' else None
        print(json.dumps(record,sort_keys=True),flush=True)
    try:
        report.pop('runtime_preserved',None)
        report['finalization']=dict(status='PENDING_RECEIPT',receipt_file='finalization.json',requires_successful_controller_exit=True)
        report['elapsed_seconds']=0 if job.get('performance_started') is None else time.monotonic()-job['performance_started']
        writing=time.monotonic()
        record['report_sha256']=write_artifact(destination/'ab.json',(json.dumps(report,sort_keys=True,indent=2)+'\n').encode())
        record['markdown_sha256']=write_artifact(destination/'ab.md',job['markdown'].encode())
        if report.get('retention',{}).get('worker'):
            write_artifact(destination/'retention-manifest.json',(json.dumps(report['retention']['worker'],sort_keys=True,indent=2)+'\n').encode())
        record['final_report_write_seconds']=time.monotonic()-writing
        record['verified']=True
        # Publish verified report bytes before any cleanup or completion-receipt failure.
        emit()
        if job['cleanup_requested']:
            if (owned/MARKER).read_text()!=MARKER_TEXT:raise ValueError('cleanup ownership marker differs')
            cleaning=time.monotonic();shutil.rmtree(owned)
            record.update(cleanup_state='COMPLETED',cleanup_seconds=time.monotonic()-cleaning)
        record['runtime_preserved']=owned.exists()
        record['shared_deadline_met']=time.monotonic()<job['deadline']
        if not record['shared_deadline_met']:
            record['status']='TIMED_OUT';emit();return 4
        record['status']='COMPLETED'
        record['worker_elapsed_seconds']=time.monotonic()-started
        record['process_cpu_seconds']=time.process_time()-cpu
        write_artifact(destination/'finalization.json',(json.dumps(record,sort_keys=True,indent=2)+'\n').encode())
        emit();return 0
    except Exception as exc:
        record.update(status='ERROR',error=repr(exc),traceback=traceback.format_exc(),runtime_preserved=owned.exists())
        emit();return 2


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source');parser.add_argument('--destination')
    parser.add_argument('--owned-runtime');parser.add_argument('--finalize-job');args=parser.parse_args()
    if args.finalize_job:return finalize_worker(json.loads(Path(args.finalize_job).read_text()))
    if not all((args.source,args.destination,args.owned_runtime)):parser.error('copy requires source, destination and owned runtime')
    return copy_worker(args.source,args.destination,args.owned_runtime)

if __name__=='__main__':raise SystemExit(main())
