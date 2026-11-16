#!/usr/bin/env python3
"""Bind finite inventories to retained actual results without changing preregistration."""
import argparse
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(path.read_text())


def failure_ids(log, kind, executed_ids):
    identities=set()
    for method, qualified in re.findall(r'^'+kind+r': (\w+) \(([^)]+)\)', log, re.M):
        # Python versions differ: parentheses may already contain the method.
        identity=qualified if qualified.endswith('.'+method) else qualified+'.'+method
        identities.add(identity)
    if not identities.issubset(set(executed_ids)):
        raise ValueError('Failure identity outside executed roster; cannot label unknown failures PASS')
    return identities


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(); base=args.evidence_root.resolve()
    scope=read(ROOT/'contracts/validation-scope-v1.json')
    family={r['test_id']:r['family_id'] for r in scope['existing_test_index']}
    rows=[]; runs=[]
    for label,folder,kind in [('source-py312','release-full-py312','source'),('installed-py312','release-full-py312','installed'),
                              ('source-py314','release-full-py314','source'),('installed-py314','installed-py314','installed')]:
        result=read(base/folder/(kind+'_tests.json'))
        log=(base/folder/'logs'/(kind+'_tests.stderr.txt')).read_text()
        failed=failure_ids(log,'FAIL',result['executed_ids'])
        errors=failure_ids(log,'ERROR',result['executed_ids'])
        if set(result['executed_ids']) != set(family) or len(result['executed_ids']) != 875:
            raise ValueError('Unexpected protected test inventory')
        if result['failures']!=len(failed) or result['errors']!=len(errors):
            raise ValueError('Runner/log failure identities need explicit investigation')
        for identity in result['executed_ids']:
            actual='FAIL' if identity in failed else 'ERROR' if identity in errors else 'PASS'
            rows.append({'case_id':label+'::'+identity,'original_test_id':identity,'family_id':family[identity],
                         'feature':identity,'data_class':'SYNTHETIC','invariant_oracle':'Unchanged assertions in pinned historical test; independence varies and is not inferred from name.',
                         'seed':None,'expected_result':'PASS','actual_result':actual,'environment':label,
                         'command_record':folder+'/verification.json','raw_evidence':[folder+'/'+kind+'_tests.json',folder+'/logs/'+kind+'_tests.stderr.txt'],
                         'repeat_count':1,'unexplained_behavior':None,
                         'known_issue':'VAL-P2-TEST-BARRIER-RACE' if actual=='FAIL' and 'test_seen_failure_survives_later_truncated_result' in identity else None,
                         'decision':actual})
        runs.append({'id':label,'unique_ids':len(set(result['executed_ids'])),'failures':result['failures'],'errors':result['errors'],
                     'skips':result['skips'],'status':result['status']})
    prop=base/'properties/run-004'
    summary=read(prop/'summary.json')
    for line in (prop/'cases.jsonl').read_text().splitlines():
        r=json.loads(line)
        rows.append({'case_id':'properties::'+r['case_id'],'family_id':'F08','feature':r['family'],
                     'data_class':'FULLY_SYNTHETIC','invariant_oracle':'Independent integer transitions and explicit model-contract verdicts',
                     'seed':r['seed'],'expected_result':r['expected'],'actual_result':r.get('observed'),
                     'environment':summary['environment'],'command':summary['command'],
                     'raw_evidence':['properties/run-004/cases.jsonl','properties/run-004/'+r['input']],
                     'repeat_count':1,'unexplained_behavior':None,'decision':r['status'],
                     'truth_anomaly':r['truth_anomaly'],'alert':r['alert'],'label_limit':'Known synthetic injection labels, not real institutional outcomes.'})
    resilience=read(base/'resilience/run-001/summary.json')
    for r in resilience['cases']:
        rows.append({'case_id':'resilience::'+r['case_id'],'family_id':'F05' if 'sqlite' in r['case_id'] or 'quota' in r['case_id'] or 'backup' in r['case_id'] else 'F09',
                     'feature':r['level'],'data_class':r['data_class'],'invariant_oracle':'Literal bounded reader or SQLite outcome',
                     'seed':None,'expected_result':r['expected'],'actual_result':r['actual'],'environment':resilience['environment'],
                     'command':resilience['command'],'raw_evidence':['resilience/run-001/results.json'],'repeat_count':1,
                     'unexplained_behavior':None,'decision':'PASS' if r['passed'] else 'FAIL'})
    record={'format':'validation-coverage-results-v1','preregistration':'contracts/validation-scope-v1.json',
            'original_unique_ids':875,'suite_executions':runs,'canonical_property_run':'properties/run-004',
            'property_cases':summary['cases'],'resilience_cases':resilience['case_count'],
            'counting_note':'Repeated execution of one old identity in another interpreter/import mode is not a new unique test. Earlier property runs are excluded.',
            'cases':rows,'unexecuted':['Real public-data arithmetic','real-data-based injections','macOS arm64','one million events','months-long soak','physical disk/power failure','remote CI verification']}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({'records':len(rows),'suites':runs,'property_cases':summary['cases'],'resilience_cases':resilience['case_count']}))


if __name__=='__main__':
    main()
