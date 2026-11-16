"""Negative schedules must not erase a correctness sampler's observed failure."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class Gate2CorrectnessSamplerTests(unittest.TestCase):
    def schedule(self, schedule):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="gate2-race-test-") as temporary:
            output = Path(temporary) / "evidence"
            command = [sys.executable, "-I", "-B", str(source / "scripts/validation/gate2_race.py"),
                       "--source", str(source), "--output", str(output), "--schedule", schedule]
            done = subprocess.run(command, cwd=temporary, capture_output=True, text=True, timeout=12)
            self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
            summary = json.loads((output / "summary.json").read_text())
            self.assertEqual(summary["status"], "PASS")
            self.assertTrue(summary["source_bytes_unchanged_during_execution"])
            row = summary["results"][0]
            self.assertEqual((row["executed"], row["failures"], row["errors"], row["skips"]), (1, 0, 0, 0))
            observation = row["observations"][0]
            result = observation["result"]
            self.assertEqual(result["correctness"], "FAILED")
            self.assertEqual(result["completion_state"], "TIMED_OUT")
            self.assertIs(result["observed_correctness_failure"]["oracle"]["passed"], False)
            self.assertIsNotNone(result["result_parse_error"])
            self.assertTrue(any(event.get("event") == "actual_correctness_load" and
                                event.get("status") == "CORRECTNESS_FAILED"
                                for event in observation["events"]))
            return observation

    def test_failure_published_before_sampler_survives_truncation(self):
        self.schedule("before_read")

    def test_rss_callback_cannot_release_before_correctness_sampler(self):
        observation = self.schedule("between_read_and_rss")
        releases = [event for event in observation["events"] if event["event"] == "rss_callback_returned"]
        self.assertEqual(len(releases), 1)
        self.assertIs(releases[0]["barrier_released"], False)

    def test_expected_failure_and_noop_substitutions_are_rejected_before_import(self):
        source = Path(__file__).resolve().parents[1]
        method = "test_seen_failure_survives_later_truncated_result"
        candidates = {
            "expected_failure": "    @unittest.expectedFailure\n    def " + method + "(self): self.fail('injected')\n",
            "noop": "    def " + method + "(self): pass\n",
            "different_id": "    def test_unrelated(self): pass\n",
        }
        with tempfile.TemporaryDirectory(prefix="gate2-race-rejection-") as temporary:
            for label, body in candidates.items():
                with self.subTest(label=label):
                    fake = Path(temporary) / label
                    (fake / "tests").mkdir(parents=True)
                    (fake / "tests/test_lab_contract_validation.py").write_text(
                        "import unittest\nclass ProtocolValidationTests(unittest.TestCase):\n" + body)
                    output = fake / "rejected"
                    command = [sys.executable, "-I", "-B", str(source / "scripts/validation/gate2_race.py"),
                               "--source", str(fake), "--output", str(output)]
                    done = subprocess.run(command, cwd=temporary, capture_output=True, text=True, timeout=12)
                    self.assertEqual(done.returncode, 2, done.stderr + done.stdout)
                    result = json.loads((output / "summary.json").read_text())
                    self.assertEqual((result["status"], result["reason"], result["executed"]),
                                     ("ERROR", "TEST_SOURCE_IDENTITY", 0))


if __name__ == "__main__":
    unittest.main()
