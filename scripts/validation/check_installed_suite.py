#!/usr/bin/env python3
"""Run the unchanged strict installed-suite gate after an independent source failure.

This reports only installed tests. It never relabels a failed full release gate.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_release


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--python', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    gate = verify_release.Verification(args.output, 'SUPPLEMENTAL_INSTALLED_ONLY')
    gate.record['source_suite'] = {'status':'NOT_RUN', 'reason':'separate original result retained; no override'}
    try:
        verify_release.preflight(args.source)
        version = verify_release.tomllib.loads((args.source/'pyproject.toml').read_text())['project']['version']
        gate.probe('installed_import', args.python, args.source, True, version)
        gate.tests('installed_tests', args.python, args.source, True)
        gate.record['status'] = 'PASS'
        code = 0
    except Exception as error:
        gate.record.update(status='FAIL', error=str(error))
        code = 1
    gate.record['exit_code'] = code
    gate.persist()
    print(json.dumps({'status':gate.record['status'], 'scope':'INSTALLED_TESTS_ONLY', 'report':str(gate.output/'verification.json')}))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
