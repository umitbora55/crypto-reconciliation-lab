#!/usr/bin/env python3
"""Seal an explicit C01–C08 roster before running; retain original failures."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time
import unittest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--installed", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.environ["CRL_PROTECTED_TEST_OUTPUT"] = str(args.output)
    if not args.installed:
        sys.path.insert(0, str(args.repo))
    sys.path.insert(0, str(args.repo / "protected_snapshot_tests"))
    import test_boundary
    import crypto_reconciliation_lab
    before_inventory = test_boundary.inventory(args.output)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(test_boundary.BoundaryTests)
    ids = [item.id() for item in suite]
    identity = {}
    for base in (args.repo / "crypto_reconciliation_lab", args.repo / "protected_snapshot_tests", args.repo / "scripts" / "validation"):
        for path in sorted(base.rglob("*.py")):
            identity[str(path.relative_to(args.repo))] = hashlib.sha256(path.read_bytes()).hexdigest()
    protocol = {"format": "protected-tests-v1", "status": "PREREGISTERED", "tests": ids,
                "source_sha256": identity, "kernel": platform.release(), "python": sys.version,
                "package_import": str(crypto_reconciliation_lab.__file__), "argv": sys.argv,
                "start_ns": time.time_ns(), "scope": "trusted-root local Linux; not hostile host root or physical power loss"}
    (args.output / "protocol.json").write_text(json.dumps(protocol, sort_keys=True, indent=2) + "\n")
    (args.output / "inventory-before.json").write_text(json.dumps(before_inventory, sort_keys=True, indent=2) + "\n")
    records = []
    class Result(unittest.TextTestResult):
        def startTest(self, test):
            super().startTest(test)
            self.started = time.monotonic()
        def record(self, test, status, error=None):
            records.append({"test": test.id(), "status": status, "seconds": time.monotonic()-self.started, "error": error})
            (args.output / "observations.json").write_text(json.dumps(records, sort_keys=True, indent=2) + "\n")
        def addSuccess(self, test):
            super().addSuccess(test); self.record(test, "PASS")
        def addFailure(self, test, err):
            super().addFailure(test, err); self.record(test, "FAIL", self._exc_info_to_string(err, test))
        def addError(self, test, err):
            super().addError(test, err); self.record(test, "ERROR", self._exc_info_to_string(err, test))
        def addSkip(self, test, reason):
            super().addSkip(test, reason); self.record(test, "NOT_RUN", reason)
    with (args.output / "unittest.log").open("w") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=Result).run(suite)
    observed = {row["test"] for row in records}
    for name in ids:
        if name not in observed: records.append({"test": name, "status": "NOT_RUN"})
    unchanged = all((args.repo / name).is_file() and hashlib.sha256((args.repo / name).read_bytes()).hexdigest() == digest
                    for name, digest in identity.items())
    success = result.wasSuccessful() and not result.skipped and len(observed) == len(ids) and unchanged
    final = {"format": "protected-tests-v1", "status": "PASS" if success else "FAIL", "tests": records,
             "source_unchanged_during_execution": unchanged,
             "protocol_sha256": hashlib.sha256((args.output / "protocol.json").read_bytes()).hexdigest()}
    (args.output / "results.json").write_text(json.dumps(final, sort_keys=True, indent=2) + "\n")
    after_inventory = test_boundary.inventory(args.output)
    (args.output / "inventory-after.json").write_text(json.dumps(after_inventory, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"status": final["status"], "tests": len(ids), "output": str(args.output)}))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
