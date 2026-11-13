"""Independent literal truth, schedule, split and horizon-boundary tests."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from crypto_reconciliation_lab.triage import world, truth
from crypto_reconciliation_lab.triage.contracts import CONTRACT_SHA256, unit_id


def literal_world():
    return {"assets": {"A": 0}, "opening": {"A": {"investors": {"I1": 6, "I2": 4},
            "custody": {"platform": 2, "external": 8}}}, "events": [
        {"ref": "x1", "asset": "A", "at": "2026-11-10T00:01:00Z", "sequence": 1,
         "kind": "transfer", "units": 1, "sender": "I1", "recipient": "I2", "custody": None},
        {"ref": "x2", "asset": "A", "at": "2026-11-10T00:02:00Z", "sequence": 1,
         "kind": "deposit", "units": 2, "sender": None, "recipient": "I1", "custody": "external"},
        {"ref": "x3", "asset": "A", "at": "2026-11-10T00:03:00Z", "sequence": 1,
         "kind": "withdrawal", "units": 1, "sender": "I2", "recipient": None, "custody": "external"}]}


def one_episode_bundle(root, index=0, slot=0, *, challenge=False):
    """One unit-test world, not either formal two-world experiment smoke."""
    from crypto_reconciliation_lab.store import Store
    from crypto_reconciliation_lab.engine import reconcile
    economic = world.make_world(index)
    economic["seed"] = 920000 + index
    economic["world_id"] = "unit-g" + str(index)
    if challenge:
        economic["split"] = "challenge"
    plan, rows = world.make_episode(economic, slot)
    folder = root / "episode"
    folder.mkdir()
    (root / "truth").mkdir()
    dbpath = folder / "source.sqlite3"
    store = Store(dbpath, world.configuration(economic))
    try:
        for row in rows:
            store.ingest(row["record"], row["received_at"])
        results = [reconcile(store, world.BALANCE, cut) for cut in (plan["first_observation"], world.AS_OF)]
    finally:
        store.close()
    selection = {"format": "review-selection-v1", "sources": [{"alias": "source", "database": "source.sqlite3", "run_ids": [r["run_id"] for r in results]}]}
    world.save(folder / "selection.json", selection)
    episode = {"episode_id": plan["episode_id"], "world_id": economic["world_id"], "split": economic["split"],
               "balance_at": world.BALANCE, "as_of": world.AS_OF, "history_run_ids": [results[0]["run_id"]],
               "current_run_id": results[1]["run_id"], "selection_file": "episode/selection.json"}
    split = {"format": "triage-split-v1", "groups": [{"world_id": economic["world_id"], "split": economic["split"], "episode_ids": [plan["episode_id"]]}]}
    world.save(root / "episodes.json", {"episodes": [episode], "assets": world.ASSETS})
    world.save(root / "splits.json", split)
    private = {"format": "triage-truth-plan-v1", "split": economic["split"],
               "worlds": {economic["world_id"]: economic}, "episodes": [plan], "split_hash": world.digest(split)}
    raw = world.encoded(private)
    (root / "truth" / (economic["split"] + ".json")).write_bytes(raw)
    world.save(root / "truth/plan.json", {"format": "triage-truth-catalog-v1", "split_hash": world.digest(split),
        "files": {economic["split"]: {"path": "truth/" + economic["split"] + ".json",
                                       "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}}})
    world.save(root / "bundle.json", {"split_hash": world.digest(split), "files": {
        path.relative_to(root).as_posix(): truth._file_entry(path)
        for path in sorted(root.rglob("*")) if path.is_file()}})
    return economic, plan, dbpath, split, results


def frozen_fixture(root, split):
    return {"status": "FROZEN", "contract_hash": CONTRACT_SHA256, "split_hash": world.digest(split),
            "model_id": "unit-model", "prediction_hash": "1" * 64,
            "dataset_bundle": truth._file_entry(root / "bundle.json"),
            "truth_catalog": truth._file_entry(root / "truth/plan.json")}


class TriageWorldTests(unittest.TestCase):
    def test_literal_integer_balances_and_custody_are_independent(self):
        self.assertEqual(world.integer_ledger(literal_world()), {"A": {
            "investors": {"I1": 7, "I2": 4}, "custody": {"platform": 2, "external": 9}, "liability": 11}})
        fractional = {"assets": {"B": 2}, "opening": {"B": {"investors": {"I1": 10, "I2": 20},
            "custody": {"platform": 5, "external": 25}}}, "events": [
                {"ref": "d", "asset": "B", "at": "2026-11-10T00:01:00Z", "sequence": 1,
                 "kind": "deposit", "units": 20, "sender": None, "recipient": "I1", "custody": "external"}]}
        self.assertEqual(world.integer_ledger(fractional), {"B": {"investors": {"I1": 30, "I2": 20},
            "custody": {"platform": 5, "external": 45}, "liability": 50}})
        self.assertEqual(world.text_amount(30, 2), "0.3")
        self.assertEqual(world.text_amount(7, 8), "0.00000007")
        self.assertEqual(world.text_amount(0, 8), "0")
        for invalid in (True, 1.5, "2", None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                world.text_amount(invalid, 2)

    def test_main_roster_has_fixed_groups_sizes_seeds_and_disjoint_worlds(self):
        worlds = [world.make_world(index) for index in range(144)]
        self.assertEqual({split: sum(item["split"] == split for item in worlds) for split in ("train", "validation", "test", "challenge")},
                         {"train": 72, "validation": 24, "test": 24, "challenge": 24})
        self.assertEqual(len({item["world_id"] for item in worlds}), 144)
        self.assertEqual(worlds[0]["seed"], 500000)
        self.assertEqual(worlds[119]["seed"], 500119)
        self.assertEqual(worlds[120]["seed"], 700000)
        self.assertEqual(worlds[-1]["seed"], 700023)
        self.assertEqual({len(item["events"]) for item in worlds}, {24, 28, 32, 36, 40})
        self.assertEqual({len(item["investors"]) for item in worlds}, {4, 5, 6})
        self.assertEqual(world.make_world(0, "smoke")["seed"], 900001)
        self.assertEqual(world.make_world(1, "archive_smoke")["seed"], 910002)

    def test_twins_have_identical_visible_prefix_and_distinct_literal_horizon_labels(self):
        economic = world.make_world(0, "smoke")
        first, first_rows = world.make_episode(economic, 0)
        second, second_rows = world.make_episode(economic, 1)
        visible = lambda rows: [row for row in rows if row["received_at"] <= world.AS_OF]
        self.assertEqual(visible(first_rows), visible(second_rows))
        self.assertEqual(first["first_observation"], second["first_observation"])
        self.assertEqual(truth.expected_findings(economic, first, world.AS_OF), truth.expected_findings(economic, second, world.AS_OF))
        self.assertEqual(truth.scope_label(truth.expected_findings(economic, first, world.HORIZON), first["asset"])[0], 0)
        self.assertEqual(truth.scope_label(truth.expected_findings(economic, second, world.HORIZON), second["asset"])[0], 1)

    def test_future_deliveries_do_not_change_complete_saved_twin_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left, right = root / "left", root / "right"
            left.mkdir(); right.mkdir()
            first = one_episode_bundle(left, 0, 0)[-1]
            second = one_episode_bundle(right, 0, 1)[-1]
            self.assertEqual(first, second)

    def test_challenge_future_revisions_do_not_change_complete_twin_payloads_at_t(self):
        # A separate 920000 development fixture; this never evaluates main H.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left, right = root / "left", root / "right"
            left.mkdir(); right.mkdir()
            first = one_episode_bundle(left, 0, 0, challenge=True)[-1]
            second = one_episode_bundle(right, 0, 1, challenge=True)[-1]
            self.assertEqual(first, second)

    def test_every_rotating_family_has_resolved_and_unresolved_training_examples(self):
        for index, expected_family in enumerate(("LATE_MANIFEST", "REPORT_REVISION", "CORRECTION_DEPENDENCY", "CUSTODY_DIFFERENCE")):
            for offset, expected_label in ((0, 0), (4, 1)):
                with self.subTest(index=index, offset=offset):
                    economic = world.make_world(index + offset)
                    plan, _ = world.make_episode(economic, 2)
                    self.assertEqual(plan["family"], expected_family)
                    self.assertEqual(truth.scope_label(truth.expected_findings(economic, plan, world.HORIZON), plan["asset"])[0], expected_label)

    def test_resolved_initial_problem_then_new_scope_problem_is_positive(self):
        economic = world.make_world(0, "archive_smoke")
        economic.update(seed=920001, world_id="unit-challenge", split="challenge")
        plan, _ = world.make_episode(economic, 1)
        plan.update(asset="ASSET_A", impact_units=5,
                    target_ref=next(event["ref"] for event in economic["events"] if event["asset"] == "ASSET_A"))
        before = truth.expected_findings(economic, plan, world.at_hours(4))
        after = truth.expected_findings(economic, plan, world.HORIZON)
        self.assertEqual(truth.scope_label(before, "ASSET_A")[0], 0)
        self.assertEqual(truth.scope_label(after, "ASSET_A")[0], 1)
        custody = next(row for row in after if row["asset"] == "ASSET_A" and row["comparison"] == "B")
        self.assertEqual(custody["difference"], "0.00000005")
        self.assertTrue(all(row["reconciliation_state"] == "MATCHED" for row in after if row["comparison"] == "A"))

    def test_null_and_out_of_scope_are_never_negative_labels(self):
        self.assertEqual(truth.scope_label(None, "ASSET_A", observed=False), (None, "H_NOT_OBSERVED"))
        self.assertEqual(truth.scope_label([], "ASSET_A", in_scope=False), (None, "OUT_OF_SCOPE_OBSERVABILITY_LIMIT"))
        with self.assertRaisesRegex(ValueError, "LABEL_SCOPE"):
            truth.scope_label([], "ASSET_A")

    def test_finite_truth_is_checked_against_real_engine_without_deriving_labels(self):
        from crypto_reconciliation_lab.store import Store
        from crypto_reconciliation_lab.engine import reconcile
        cases = [(index, 2, False) for index in range(8)] + [(1, 3, False), (2, 3, False)] + [(0, slot, True) for slot in range(4)]
        for index, slot, challenge in cases:
            with self.subTest(index=index, slot=slot, challenge=challenge), tempfile.TemporaryDirectory() as directory:
                economic, plan, source, _, _ = one_episode_bundle(Path(directory), index, slot, challenge=challenge)
                store = Store(source)
                try:
                    cut = world.AS_OF if plan["family"] == "H_NOT_OBSERVED" else world.HORIZON
                    result = reconcile(store, world.BALANCE, cut)
                    expected = truth.expected_findings(economic, plan, cut)
                    self.assertTrue(truth.verify_findings(result, expected)["financial_state_fields_equal"])
                    corrupted = deepcopy(result)
                    corrupted["findings"][0]["expected"] = "999"
                    with self.assertRaisesRegex(ValueError, "TRUTH_MISMATCH"):
                        truth.verify_findings(corrupted, expected)
                finally:
                    store.close()

    def test_censored_evaluation_keeps_source_bytes_run_ids_and_null_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, plan, source, _, _ = one_episode_bundle(root, 1, 3)
            before = source.read_bytes()
            result = truth.evaluate_labels(root, ("train",), output=root / "labels")
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(result["inventory"], {"episodes": 1, "units": 2, "positive": 0, "negative": 0, "unknown": 2})
            self.assertTrue(all(row["label"] is None and row["reason"] == "H_NOT_OBSERVED" for row in result["units"]))
            self.assertFalse(list((root / "labels/horizon").iterdir()))
            self.assertTrue(all(not Path(str(source) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")))
            expected = truth.expected_findings(world.make_world(1), plan, world.AS_OF)
            custody = next(row for row in expected if row["asset"] == plan["asset"] and row["comparison"] == "B")
            self.assertIsNone(custody["reported"])
            self.assertIsNone(custody["difference"])

    def test_holdout_truth_requires_freeze_and_is_single_use(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, source, split, _ = one_episode_bundle(root, 0, 1, challenge=True)
            before = source.read_bytes()
            real_load = truth.load
            seen = []
            def observe(path):
                seen.append(Path(path))
                return real_load(path)
            with patch.object(truth, "load", side_effect=observe), self.assertRaisesRegex(ValueError, "HOLDOUT_LOCK"):
                truth.evaluate_labels(root, ("test", "challenge"), output=root / "denied")
            self.assertNotIn(root / "truth/plan.json", seen)
            self.assertFalse((root / "denied").exists())
            freeze = frozen_fixture(root, split)
            result = truth.evaluate_labels(root, ("test", "challenge"), freeze, root / "evaluated")
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(sorted(row["label"] for row in result["units"]), [0, 1])
            self.assertIsNotNone(result["verification"][0]["intermediate_closure"])
            with self.assertRaises(FileExistsError):
                truth.evaluate_labels(root, ("test", "challenge"), freeze, root / "again")
            self.assertFalse((root / "again").exists())

    def test_truth_catalog_cannot_be_rewritten_outside_original_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            one_episode_bundle(root)
            catalog = truth.load(root / "truth/plan.json")
            catalog["files"]["train"]["sha256"] = "0" * 64
            world.save(root / "truth/plan.json", catalog)
            original_open = Path.open
            private = (root / "truth/train.json").resolve()
            def guarded_open(path, *args, **kwargs):
                if path.resolve() == private:
                    raise AssertionError("private truth opened before catalog binding check")
                return original_open(path, *args, **kwargs)
            with patch.object(Path, "open", autospec=True, side_effect=guarded_open), self.assertRaisesRegex(ValueError, "BUNDLE_CHANGED"):
                truth.evaluate_labels(root, ("train",), output=root / "denied")
            self.assertFalse((root / "denied").exists())

    def test_final_freeze_binds_bundle_and_catalog_before_horizon_truth_access(self):
        for key in ("dataset_bundle", "truth_catalog"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, _, _, split, _ = one_episode_bundle(root, 0, 1, challenge=True)
                freeze = frozen_fixture(root, split)
                freeze[key]["sha256"] = "0" * 64
                original_open = Path.open
                private = (root / "truth/challenge.json").resolve()
                def guarded_open(path, *args, **kwargs):
                    if path.resolve() == private:
                        raise AssertionError("private holdout truth opened with invalid freeze binding")
                    return original_open(path, *args, **kwargs)
                with patch.object(Path, "open", autospec=True, side_effect=guarded_open), self.assertRaisesRegex(ValueError, "HOLDOUT_LOCK"):
                    truth.evaluate_labels(root, ("test", "challenge"), freeze, root / "denied")
                self.assertFalse((root / "denied").exists())
                self.assertFalse((root / "truth/final-evaluation-lock.json").exists())

    def test_train_evaluator_does_not_open_private_holdout_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            one_episode_bundle(root)
            for name in ("test", "challenge"):
                (root / "truth" / (name + ".json")).write_bytes(b"must never be opened before freeze")
            original_open = Path.open
            forbidden = {(root / "truth/test.json").resolve(), (root / "truth/challenge.json").resolve()}
            def guarded_open(path, *args, **kwargs):
                if path.resolve() in forbidden:
                    raise AssertionError("private holdout truth opened during training evaluation")
                return original_open(path, *args, **kwargs)
            with patch.object(Path, "open", autospec=True, side_effect=guarded_open):
                result = truth.evaluate_labels(root, ("train",), output=root / "labels")
            self.assertEqual(result["inventory"]["units"], 2)

    def test_label_output_rejects_source_sidecar_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, source, _, _ = one_episode_bundle(root)
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            for suffix in ("-wal", "-shm", "-journal"):
                with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, "OUTPUT_SOURCE_CONFLICT"):
                    truth.evaluate_labels(root, ("train",), output=Path(str(source) + suffix) / "labels")
                self.assertFalse(Path(str(source) + suffix).exists())
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
