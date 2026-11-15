"""One command-specific bounded child; no input-selectable code or database."""
from pathlib import Path
import sys

from .adapter import compute
from .common import ReplayError
from .comparison import compare_payloads
from .report import empty_report, fail, financial_summary, report_bytes, runtime_identity
from .validation import validate_inputs


def verify_bytes(raw_context, raw_run, expected):
    report = empty_report(expected)
    try:
        validated = validate_inputs(raw_context, raw_run, expected)
        report.update(validated.identity)
        report['completion']['validation'] = 'COMPLETED'
        computed = compute(**validated.input_data)
        report['completion']['calculation'] = 'COMPLETED'
        computed_id = computed.pop('run_id')
        report['recomputed_canonical_run_id'] = computed_id
        comparison = compare_payloads(validated.saved_payload, computed)
        if comparison['equal'] != (computed_id == report['saved_canonical_run_id']):
            raise ReplayError('REPLAY_COMPUTATION', 'canonical identity and full comparison disagree')
        report['comparison'] = comparison
        report['completion']['comparison'] = 'COMPLETED'
        status = 'REPRODUCED' if comparison['equal'] else 'DIVERGED'
        report.update(status=status, replay_state=status, operation_state='COMPLETE',
                      exit_code=0 if comparison['equal'] else 1,
                      reason_code='REPLAY_' + status, message='Complete canonical financial payload compared')
        report['financial_summary'] = {'saved': financial_summary(validated.saved_payload),
                                       'recomputed': financial_summary(computed)}
    except ReplayError as exc:
        fail(report, exc.reason_code, str(exc))
    try:
        report['runtime'] = runtime_identity()
    except (OSError, ValueError) as exc:
        fail(report, 'REPLAY_OUTPUT', 'current runtime identity could not be recorded: ' + str(exc))
    return report


def main():
    # Higher than the explicitly checked 1024-container contract, finite itself.
    sys.setrecursionlimit(4096)
    directory, expected = Path(sys.argv[1]), sys.argv[2]
    report = verify_bytes((directory/'context.input').read_bytes(),
                          (directory/'run.input').read_bytes(), expected)
    try:
        raw = report_bytes(report)
    except ReplayError as exc:
        # The comparison has already finished. Preserve its verdict and full
        # difference count even if publication diagnostics exceeded their cap.
        fail(report, exc.reason_code, str(exc))
        comparison = report['comparison']
        comparison.update(differences=[], reported_differences=0,
                          truncated=comparison['total_differences'] > 0)
        if report['financial_summary']:
            for summary in report['financial_summary'].values():
                summary.update(findings=[], reported_findings=0,
                               truncated=summary['finding_count'] > 0,
                               data_states={}, reconciliation_states={},
                               state_details='OMITTED_REPORT_LIMIT')
        report['runtime'] = None
        raw = report_bytes(report)
    (directory/'result.json').write_bytes(raw)


if __name__ == '__main__':
    main()
