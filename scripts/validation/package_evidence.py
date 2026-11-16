#!/usr/bin/env python3
"""Hash and package finite validation evidence, explicitly inventorying omissions."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
BASELINE = 'b48021273405128c67e2969fd4b46f8d7e876a99'


def proof(path):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024*1024), b''):
            h.update(block)
    return {'bytes': path.stat().st_size, 'sha256': h.hexdigest()}


def omission(relative, size):
    parts = relative.parts
    if any(p in {'environment', 'pip-cache', 'uv-cache', '__pycache__'} or p.startswith('.venv') for p in parts):
        return 'Reinstallable environment/cache; pinned requirements and installed SBOM retained.'
    if parts[:2] == ('setup','python'):
        return 'Downloaded interpreter; version and installation evidence retained.'
    if any(parts[i:i+2] in (('build','source'),('build','sdist')) for i in range(len(parts)-1)):
        return 'Extracted build source duplicates; sdist/wheel and release byte manifests retained.'
    if 'public-data' in parts and 'raw' in parts:
        return 'Public-source redistribution permission not independently established.'
    if relative.suffix in {'.sqlite3', '.db'} or size > 8*1024*1024:
        return 'Large/generated raw payload omitted; hash, size, retained local path and generating command evidence remain.'
    return None


def index_evidence(root, target):
    entries=[]; omitted=[]
    for path in sorted(root.rglob('*')):
        mode=path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        relative=path.relative_to(root)
        if not stat.S_ISREG(mode):
            omitted.append({'path':relative.as_posix(),'reason':'Nonregular file; not dereferenced or read.'})
            continue
        reason=omission(relative,path.stat().st_size)
        # Cache/interpreter bytes are reproducible prerequisites, not experimental evidence.
        if reason and ('cache' in reason or 'interpreter' in reason or 'Extracted build' in reason):
            omitted.append({'path':relative.as_posix(),'bytes':path.stat().st_size,'reason':reason})
            continue
        row={'path':relative.as_posix(),**proof(path)}
        if reason:
            omitted.append(dict(row,reason=reason))
        else:
            entries.append(row)
    record={'format':'validation-evidence-manifest-v1','created_at':datetime.now(timezone.utc).isoformat(),
            'application_commit':BASELINE,'repository_head_at_seal':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'research_identity':'Working-tree research source; per-run source hashes and final archive commit bind it. No claim that uncommitted trials executed a later Git commit.',
            'evidence_root':str(root),'archive_evidence_prefix':'evidence/',
            'excluded_self':'The committed evidence/manifest.json and later archive/hash/handoff do not hash themselves.',
            'files':entries,'omitted':omitted,
            'command_records':[e['path'] for e in entries if e['path'].endswith(('command.json','commands.json'))],
            'claim_registry':'evidence/claims_registry.json','coverage_results':'evidence/coverage-results.json'}
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({'included_files':len(entries),'omitted_files':len(omitted),'index':str(target)}))


def archive(root,index,target):
    if target.exists():
        raise FileExistsError('Never overwrite a review archive')
    target.parent.mkdir(parents=True,exist_ok=True)
    record=json.loads(index.read_text()); members=[]
    source_names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    sources=[(ROOT/name,'source/'+name,None) for name in source_names if name]
    evidence=[(root/e['path'],'evidence/'+e['path'],e) for e in record['files']]
    with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path,name,expected in sources+evidence:
            if not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError('Nonregular archive input: '+name)
            actual=proof(path)
            if expected and any(actual[k]!=expected[k] for k in ('bytes','sha256')):
                raise ValueError('Evidence changed after sealing: '+name)
            z.write(path,name)
            members.append({'path':name,**actual})
        z.write(index,'evidence/manifest.json')
        members.append({'path':'evidence/manifest.json',**proof(index)})
        metadata={'format':'review-archive-v1','repository_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                  'members':members,'excluded_self':'archive-manifest.json is verified by the outer ZIP checksum.'}
        z.writestr('archive-manifest.json',json.dumps(metadata,indent=2)+'\n')
    with zipfile.ZipFile(target) as z:
        names=z.namelist()
        assert len(names)==len(set(names))==len(members)+1
        for item in members:
            name=PurePosixPath(item['path'])
            assert not name.is_absolute() and '..' not in name.parts
            data=z.read(item['path'])
            assert len(data)==item['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256']
        assert z.testzip() is None
    outer={'archive':str(target),**proof(target),'verified_members':len(members)+1,'repository_commit':metadata['repository_commit']}
    target.with_suffix('.verification.json').write_text(json.dumps(outer,indent=2)+'\n')
    target.with_suffix('.sha256').write_text(outer['sha256']+'  '+target.name+'\n')
    print(json.dumps(outer))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence-root',required=True,type=Path)
    p.add_argument('--index',required=True,type=Path)
    p.add_argument('--archive',type=Path)
    args=p.parse_args()
    if args.archive:
        archive(args.evidence_root.resolve(),args.index,args.archive)
    else:
        index_evidence(args.evidence_root.resolve(),args.index)


if __name__=='__main__':
    main()
