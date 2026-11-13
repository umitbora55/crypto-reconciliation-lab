"""S5-F1 regressions: exact observations and ordering under ambient contexts."""
from decimal import Context, Decimal, getcontext, localcontext
import hashlib
from pathlib import Path
import tempfile
import unittest

from crypto_reconciliation_lab import Store, reconcile
from crypto_reconciliation_lab.review.adapter import read_selected_sources
from crypto_reconciliation_lab.triage.contracts import AS_OF, BALANCE_AT, save
from crypto_reconciliation_lab.triage.features import build_features, derived_text, extract_episode
from crypto_reconciliation_lab.triage.ranking import build_queue
from review_fixtures import create_selection
from triage_model_fixtures import document, literal_model, row


LARGE_REPORT = "1234567890123456789012345678911"
LARGE_DIFFERENCE = "-1234567890123456789012345678910"
EXACT_RATIO = "1234567890123456789012345678910.000000000000000000"


def saved_amount_fixture(folder, *, opening_amount="1", reported=LARGE_REPORT):
    """One independent investor/asset; construct real immutable saved runs."""
    folder.mkdir()
    database = folder / "source.sqlite3"
    opening = "2026-11-10T00:00:00Z"
    config = {"platform": "P", "custodian": "C", "investors": ["I"],
              "assets": {"AX": 0}, "opening_at": opening}
    records = []
    for scope, amount in (("I", opening_amount), ("platform", opening_amount), ("external", "0")):
        records.append({"kind": "opening", "source": "P", "platform": "P", "asset": "AX",
                        "scope": scope, "balance_at": opening, "amount": amount})
    reports = [("platform_custody", "platform", opening_amount), ("external_custody", "external", "0")]
    if reported is not None:
        reports.append(("investor", "I", reported))
    for stream, scope, amount in reports:
        records.append({"kind": "report", "source": "C" if stream == "external_custody" else "P",
                        "platform": "P", "asset": "AX", "stream": stream, "scope": scope,
                        "balance_at": BALANCE_AT, "version": 1, "amount": amount})
    for stream, count in (("opening", 3), ("event", 0), ("investor", 1),
                          ("platform_custody", 1), ("external_custody", 1)):
        records.append({"kind": "manifest", "source": "C" if stream == "external_custody" else "P",
                        "platform": "P", "asset": "AX", "stream": stream,
                        "coverage_from": opening if stream in ("opening", "event") else BALANCE_AT,
                        "coverage_to": opening if stream == "opening" else BALANCE_AT,
                        "expected_count": count})
    store = Store(database, config)
    try:
        for record in records:
            outcome = store.ingest(record, "2026-11-10T12:00:00Z")
            if outcome["status"] != "ACCEPTED":
                raise AssertionError("literal input must be valid: " + str(outcome))
        previous = reconcile(store, BALANCE_AT, "2026-11-10T18:00:00Z")
        current = reconcile(store, BALANCE_AT, AS_OF)
    finally:
        store.close()
    episode = {"episode_id": "e0", "world_id": "w0", "split": "train", "as_of": AS_OF,
               "current_run_id": current["run_id"], "history_run_ids": [previous["run_id"]],
               "selection_file": "selection.json"}
    create_selection(folder, [("e0", database, [previous["run_id"], current["run_id"]])])
    save(folder / "episodes.json", {"episodes": [episode]})
    save(folder / "splits.json", {"format": "triage-split-v1", "groups": [
        {"world_id": "w0", "split": "train", "episode_ids": ["e0"]}]})
    return database, episode, current


class DecimalContextRegressionTests(unittest.TestCase):
    def test_large_saved_amount_ratio_is_exact_at_precision_28_and_64(self):
        original_precision = getcontext().prec
        with tempfile.TemporaryDirectory(prefix="triage-decimal-amount-") as temporary:
            root = Path(temporary)
            database, episode, current = saved_amount_fixture(root / "input")
            finding = next(f for f in current["findings"] if f["comparison"] == "A")
            self.assertEqual((finding["expected"], finding["reported"], finding["difference"]),
                             ("1", LARGE_REPORT, LARGE_DIFFERENCE))
            before = hashlib.sha256(database.read_bytes()).hexdigest()
            runs = read_selected_sources(root / "input/selection.json").runs
            saved_payloads = [(r.run_id, r.payload_text) for r in runs]
            for precision in (28, 64):
                with self.subTest(precision=precision), localcontext(Context(prec=precision)):
                    features = build_features(root / "input", root / ("features-" + str(precision)))
                    same_saved_runs = extract_episode(runs, episode)
                    self.assertEqual((features["units"][0]["features"]["a_relative_difference_max"],
                                      same_saved_runs[0]["features"]["a_relative_difference_max"]),
                                     (EXACT_RATIO, EXACT_RATIO))
                    self.assertEqual(features["units"][0]["finding_refs"][0]["finding"], finding)
            self.assertEqual([(r.run_id, r.payload_text) for r in runs], saved_payloads)
            self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), before)
        self.assertEqual(getcontext().prec, original_precision)

    def test_rules_order_long_ratios_without_ambient_rounding(self):
        features, _ = document([
            row(0, ratio="1234567890123456789012345678900"),
            row(1, ratio="1234567890123456789012345678901")])
        model = literal_model(features["splits_sha256"])
        for precision in (28, 64):
            with self.subTest(precision=precision), localcontext(Context(prec=precision)):
                self.assertEqual(build_queue(features, model)["rankings"]["rules"], ["e1::AX", "e0::AX"])

    def test_rules_order_age_without_low_precision_rounding(self):
        younger = row(0, age="6.01", ratio="0.25")
        younger["first_seen_at"] = "2026-11-10T17:59:24Z"
        older = row(1, age="6.02", ratio="0.25")
        older["first_seen_at"] = "2026-11-10T17:58:48Z"
        features, _ = document([younger, older])
        model = literal_model(features["splits_sha256"])
        for precision in (2, 28, 64):
            with self.subTest(precision=precision), localcontext(Context(prec=precision)):
                self.assertEqual(build_queue(features, model)["rankings"]["rules"], ["e1::AX", "e0::AX"])

    def test_model_rounded_score_order_and_neutral_tie_survive_low_precision(self):
        features, _ = document([row(0, count=10), row(1, count=11), row(2, count=10)])
        model = literal_model(features["splits_sha256"])
        for precision in (2, 28, 64):
            with self.subTest(precision=precision), localcontext(Context(prec=precision)):
                queue = build_queue(features, model)
                self.assertEqual([u["rounded_score"] for u in queue["units"]],
                                 ["0.999954602131", "0.999983298578", "0.999954602131"])
                self.assertEqual(queue["rankings"]["model"], ["e1::AX", "e0::AX", "e2::AX"])

    def test_18_place_half_even_and_actual_null_denominators_are_preserved(self):
        for precision in (2, 28, 64):
            with self.subTest(precision=precision), localcontext(Context(prec=precision)):
                self.assertEqual(derived_text(Decimal("1"), Decimal("3")), "0.333333333333333333")
                self.assertEqual(derived_text(Decimal("1"), Decimal("6")), "0.166666666666666667")
                self.assertEqual(derived_text(Decimal("1"), Decimal("2000000000000000000")), "0.000000000000000000")
                self.assertEqual(derived_text(Decimal("3"), Decimal("2000000000000000000")), "0.000000000000000002")
        with tempfile.TemporaryDirectory(prefix="triage-decimal-null-") as temporary:
            root = Path(temporary)
            for name, opening, reported in (("zero", "0", "1"), ("missing", "1", None)):
                with self.subTest(case=name):
                    _, _, current = saved_amount_fixture(root / name, opening_amount=opening, reported=reported)
                    features = build_features(root / name, root / (name + "-features"))
                    values = features["units"][0]["features"]
                    self.assertIsNone(values["a_relative_difference_max"])
                    self.assertEqual(values["a_ratio_undefined_count"], 1)
                    finding = next(f for f in current["findings"] if f["comparison"] == "A")
                    self.assertEqual(finding["reported"], reported)
                    if name == "missing":
                        self.assertIsNone(finding["difference"])
                    else:
                        self.assertEqual((finding["expected"], finding["difference"]), ("0", "-1"))
