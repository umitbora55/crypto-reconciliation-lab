"""Test-owned child protocol fixtures; never exposed by production CLI."""
import json
import os
from pathlib import Path
import shutil
import sys
import time

directory,mode,marker=Path(sys.argv[1]),sys.argv[2],Path(sys.argv[3])
marker.write_text(json.dumps({'pid':os.getpid(),'mode':mode,'cwd':str(Path.cwd()),'argv':sys.argv}))
if mode=='hang':
    while True:time.sleep(60)
elif mode=='missing':
    pass
elif mode=='partial':
    (directory/'result.json').write_text('{"status":"REPRODUCED"')
elif mode=='oversized':
    (directory/'result.json').write_bytes(b' '*(4*1024*1024+1))
elif mode=='supplied':
    shutil.copyfile(sys.argv[4],directory/'result.json')
elif mode=='failure':
    raise SystemExit(7)
elif mode in ('runtime-failure','report-limit'):
    from unittest.mock import patch
    sys.path.insert(0,sys.argv[4])
    from crypto_reconciliation_lab.replay import worker
    sys.argv=[__file__,str(directory),sys.argv[5]]
    behavior=({'side_effect':OSError('TEST-ONLY runtime identity read failed')} if mode=='runtime-failure'
              else {'return_value':{'oversized_diagnostic':'x'*(4*1024*1024)}})
    with patch.object(worker,'runtime_identity',**behavior):worker.main()
else:
    raise ValueError(mode)
