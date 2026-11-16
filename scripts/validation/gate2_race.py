#!/usr/bin/env python3
"""Run the unchanged historical test under explicit schedules or without hooks.

Scheduling hooks are evidence-only and never used by release verification.
The historical source text, test identity and assertions are not rewritten.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import unittest
from unittest.mock import patch


TEST_ID = "test_lab_contract_validation.ProtocolValidationTests.test_seen_failure_survives_later_truncated_result"
# Independently recorded baseline and narrowly repaired full-file identities.
# These are not generated from the candidate under test.
TRUSTED_TEST_FILES = {
    "6fae4f3eed3bd16356bf71c15630b155daf8d6b6747c62509e0be6e0e92ecd17": 13038,
    "56d0ced238d9bc657a7d4308c14c72faac6022735906e776a1bfbdc1c11daaa1": 13062,
}


class IdentityResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.executed_ids = []

    def startTest(self, test):
        self.executed_ids.append(test.id())
        super().startTest(test)


def digest(path):
    raw = Path(path).read_bytes()
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _wait_readable(path, deadline):
    while time.monotonic() < deadline:
        try:
            value = json.loads(path.read_text())
            if value.get("status") == "CORRECTNESS_FAILED":
                return value
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(.001)
    raise RuntimeError("schedule fixture did not publish readable failure before deadline")


def _wait_truncated(path, deadline):
    while time.monotonic() < deadline:
        try:
            if path.read_text() == "{":
                return
        except FileNotFoundError:
            pass
        time.sleep(.001)
    raise RuntimeError("schedule fixture did not truncate after acknowledging failure")


def schedule_supervise(original, watchdog, schedule, observations):
    """Control only dependency scheduling; forward the unmodified test inputs."""
    def supervised(*args, **kwargs):
        trial = Path(args[2])
        result_path = trial / "result.json"
        ready = trial.parent / "observed"
        # Capture the test's own hooks after its context managers have entered.
        fixture_load = watchdog.load
        fixture_rss = watchdog.current_rss
        real_popen = watchdog.subprocess.Popen
        first_rss = True
        first_read_window = True
        events = []

        def spawn(*spawn_args, **spawn_kwargs):
            child = real_popen(*spawn_args, **spawn_kwargs)
            if schedule == "before_read":
                _wait_readable(result_path, time.monotonic() + 2)
                events.append({"event": "failure_published_before_first_watchdog_read"})
            return child

        def sampled_load(path):
            nonlocal first_read_window
            # In the race schedule, model the legitimate interval where the
            # file is absent at the sampler's read and appears before RSS.
            if schedule == "between_read_and_rss" and first_read_window and Path(path) == result_path:
                events.append({"event": "first_correctness_read_precedes_publication"})
                raise FileNotFoundError("test-owned publication scheduling barrier")
            value = fixture_load(path)
            if Path(path) == result_path:
                events.append({"event": "actual_correctness_load", "status": value.get("status"),
                               "barrier_exists_after_load": ready.exists()})
            return value

        def sampled_rss(pid):
            nonlocal first_rss, first_read_window
            if schedule == "between_read_and_rss" and first_rss:
                first_rss = False
                _wait_readable(result_path, time.monotonic() + 2)
                events.append({"event": "failure_readable_before_rss_callback"})
                value = fixture_rss(pid)
                released = ready.exists()
                events.append({"event": "rss_callback_returned", "barrier_released": released})
                if released:
                    _wait_truncated(result_path, time.monotonic() + 2)
                    events.append({"event": "truncated_before_next_correctness_read"})
                first_read_window = False
                return value
            first_read_window = False
            return fixture_rss(pid)

        with patch.object(watchdog, "load", side_effect=sampled_load), \
             patch.object(watchdog, "current_rss", side_effect=sampled_rss), \
             patch.object(watchdog.subprocess, "Popen", side_effect=spawn):
            result = original(*args, **kwargs)
        observations.append({"schedule": schedule, "events": events, "result": result})
        return result
    return supervised


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--schedule", choices=("unmodified", "before_read", "between_read_and_rss"), default="unmodified")
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args(argv)
    if not 1 <= args.repeats <= 40:
        parser.error("repeats must be between 1 and 40")
    source = args.source.resolve()
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    test_file = source / "tests/test_lab_contract_validation.py"
    before = digest(test_file)
    if TRUSTED_TEST_FILES.get(before["sha256"]) != before["bytes"]:
        rejection = {"format": "gate2-race-evidence-v2", "status": "ERROR",
                     "reason": "TEST_SOURCE_IDENTITY", "observed_test_source": before,
                     "expected_source_pins": TRUSTED_TEST_FILES,
                     "executed": 0, "note": "Unrecognized source rejected before import or execution"}
        (output / "summary.json").write_text(json.dumps(rejection, indent=2)+"\n")
        print(json.dumps(rejection))
        return 2
    sys.path.insert(0, str(source))
    sys.path.insert(0, str(source / "tests"))
    spec = importlib.util.spec_from_file_location("test_lab_contract_validation", test_file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    from crypto_reconciliation_lab.lab import watchdog
    rows = []
    started = time.monotonic()
    for index in range(args.repeats):
        log = io.StringIO()
        observations = []
        suite = unittest.defaultTestLoader.loadTestsFromName(TEST_ID)
        if args.schedule == "unmodified":
            result = unittest.TextTestRunner(stream=log, verbosity=2, resultclass=IdentityResult).run(suite)
        else:
            original = module.supervise
            hook = schedule_supervise(original, watchdog, args.schedule, observations)
            with patch.object(module, "supervise", side_effect=hook):
                result = unittest.TextTestRunner(stream=log, verbosity=2, resultclass=IdentityResult).run(suite)
        (output / f"test-{index+1:02d}.stderr.txt").write_text(log.getvalue())
        rows.append({"repetition": index+1, "test_id": TEST_ID,
                     "executed": result.testsRun, "failures": len(result.failures),
                     "errors": len(result.errors), "skips": len(result.skipped),
                     "expected_failures": len(result.expectedFailures),
                     "unexpected_successes": len(result.unexpectedSuccesses),
                     "executed_ids": result.executed_ids,
                     "passed": result.wasSuccessful(), "observations": observations})
    after = digest(test_file)
    def accepted(row):
        exact_result = (row["passed"] and row["executed"] == 1 and row["executed_ids"] == [TEST_ID]
                        and all(row[name] == 0 for name in ("failures", "errors", "skips",
                                                          "expected_failures", "unexpected_successes")))
        if args.schedule == "unmodified":
            return exact_result
        observed = row["observations"]
        if len(observed) != 1 or observed[0]["schedule"] != args.schedule:
            return False
        evidence = observed[0]
        actual = evidence["result"]
        return (exact_result and actual["correctness"] == "FAILED"
                and actual["completion_state"] == "TIMED_OUT"
                and actual["observed_correctness_failure"] is not None
                and actual["result_parse_error"] is not None
                and any(event.get("event") == "actual_correctness_load" and
                        event.get("status") == "CORRECTNESS_FAILED" for event in evidence["events"]))

    summary = {"format": "gate2-race-evidence-v2", "schedule": args.schedule,
               "instrumented": args.schedule != "unmodified",
               "test_source_before": before, "test_source_after": after,
               "source_bytes_unchanged_during_execution": before == after,
               "command": [sys.executable, *sys.orig_argv[1:]],
               "environment": {"python": sys.version, "platform": platform.platform(),
                               "watchdog_source": str(Path(watchdog.__file__).resolve())},
               "repeats": args.repeats, "results": rows,
               "elapsed_seconds": time.monotonic()-started,
               "status": "PASS" if before == after and all(accepted(row) for row in rows) else "FAIL"}
    (output / "summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print(json.dumps({"status": summary["status"], "schedule": args.schedule,
                      "repeats": args.repeats, "passed": sum(r["passed"] for r in rows),
                      "evidence": str(output / "summary.json")}))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
