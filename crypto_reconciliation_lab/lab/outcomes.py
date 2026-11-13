"""Worker protocol: correctness is independent of execution/resource completion."""

def correctness_of(worker,role='trial'):
    if role=='generate':return 'NOT_APPLICABLE'
    if not isinstance(worker,dict):return 'UNKNOWN'
    oracle=worker.get('oracle')
    if (worker.get('status')=='CORRECTNESS_FAILED' or worker.get('correctness')=='FAILED'
        or isinstance(oracle,dict) and oracle.get('passed') is False or worker.get('restart_equal') is False):return 'FAILED'
    if isinstance(oracle,dict) and oracle.get('passed') is True and worker.get('restart_equal') is True:return 'PASSED'
    return 'UNKNOWN'


def normalize_outcome(result,role='trial'):
    """Also defend the benchmark boundary against an inconsistent outer status."""
    state=correctness_of(result.get('worker'),role)
    if role!='generate' and result.get('correctness')=='FAILED':state='FAILED'
    completion=result.get('completion_state',result.get('status','ERROR'))
    if completion=='CORRECTNESS_FAILED':completion='COMPLETED'
    if role=='trial' and completion=='COMPLETED' and state=='UNKNOWN':
        completion='ERROR';result['reason']='completed worker lacks passed oracle/readback evidence'
    result.update(correctness=state,completion_state=completion)
    result['status']='CORRECTNESS_FAILED' if state=='FAILED' else completion
    return result
