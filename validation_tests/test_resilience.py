"""Independent rejection controls for the supplementary evidence acceptance gate."""
import copy
import unittest

from validation_lab.resilience import acceptance


class EvidenceAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.rows = [dict(case_id="positive", passed=True, expected="ACCEPTED", actual="ACCEPTED"),
                     dict(case_id="negative", passed=True, expected="REPLAY_LIMIT", actual="REPLAY_LIMIT")]
        self.expected = ["positive", "negative"]

    def test_valid_controls_are_accepted(self):
        self.assertTrue(acceptance(self.rows, self.expected))

    def test_empty_or_duplicate_inventory_cannot_pass(self):
        self.assertFalse(acceptance([], self.expected))
        self.assertFalse(acceptance(self.rows + [self.rows[0]], self.expected))
        self.assertFalse(acceptance(self.rows[:1], self.expected))

    def test_false_success_counter_cannot_hide_wrong_outcome(self):
        forged = copy.deepcopy(self.rows)
        forged[1]["actual"] = "ACCEPTED"
        self.assertFalse(acceptance(forged, self.expected))

    def test_non_boolean_or_missing_result_cannot_pass(self):
        for value in (1, "True", None, False):
            forged = copy.deepcopy(self.rows)
            forged[0]["passed"] = value
            self.assertFalse(acceptance(forged, self.expected))


if __name__ == "__main__":
    unittest.main()
