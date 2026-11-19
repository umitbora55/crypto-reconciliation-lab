"""Separate opt-in command: python -m crypto_reconciliation_lab.protected_snapshot."""
import argparse
import json
import sys

from .api import protected_export


def main(argv=None):
    parser = argparse.ArgumentParser(description="Linux root-supervised sealed snapshot review; never enables WAL")
    parser.add_argument("--source", required=True, help="absolute, trusted-parent SQLite path")
    parser.add_argument("--output", required=True, help="new name in an existing root-owned private output parent")
    parser.add_argument("--kind", required=True, choices=("snapshot", "wal"))
    parser.add_argument("--expected-sha256", help="required for closed snapshot imports")
    parser.add_argument("--producer-uid", type=int, default=0)
    parser.add_argument("--run-id", action="append", required=True)
    parser.add_argument("--alias", default="custody_difference")
    parser.add_argument("--label", default="Custody difference")
    parser.add_argument("--run-label", help="optional label when exactly one run is selected")
    args = parser.parse_args(argv)
    if args.run_label is not None and len(args.run_id) != 1:
        parser.error("--run-label requires exactly one --run-id")
    try:
        result = protected_export(args.source, args.output, kind=args.kind,
                                  run_ids=args.run_id, expected_sha256=args.expected_sha256,
                                  producer_uid=args.producer_uid, alias=args.alias, label=args.label,
                                  run_labels={args.run_id[0]: args.run_label} if args.run_label else None)
    except Exception as exc:
        print(json.dumps({"status": "REJECTED", "error_type": type(exc).__name__, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
