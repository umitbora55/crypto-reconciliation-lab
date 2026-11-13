"""New export/publication risks; the existing 218 tests remain untouched."""
import ast
import base64
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from crypto_reconciliation_lab.review import export as exporter
from crypto_reconciliation_lab.review.publication import new_output_directory
from review_fixtures import create_source, create_selection, BIG_INTEGER, LONG_EXPECTED


def embedded(path):
    html = Path(path).read_text(encoding="utf-8")
    data = re.search(r'<script[^>]*id="review-data"[^>]*>(.*?)</script>', html, re.S)
    if data is None:
        raise AssertionError("embedded review-data missing")
    return html, json.loads(data.group(1)), data.group(1)


class ReviewExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="review-export-test-")
        self.root = Path(self.temp.name).resolve()
        self.database, self.run_id = create_source(self.root / "source")
        self.selection = create_selection(self.root, [("clean", self.database, [self.run_id])])

    def tearDown(self):
        self.temp.cleanup()

    def export(self, name="bundle"):
        destination = self.root / name
        exporter.export_selection(self.selection, destination)
        return destination

    def test_complete_manifest_hashes_and_no_self_reference(self):
        destination = self.export()
        self.assertEqual({p.name for p in destination.iterdir()}, {"index.html", "summary.json", "manifest.json"})
        manifest = json.loads((destination / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "COMPLETE")
        self.assertEqual(set(manifest["files"]), {"index.html", "summary.json"})
        for name, item in manifest["files"].items():
            raw = (destination / name).read_bytes()
            self.assertEqual(item, {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        self.assertEqual(set(manifest["assets"]), {"index.html", "style.css", "app.js"})

    def test_exact_reproducibility_excludes_output_and_host_paths(self):
        first, second = self.export("one"), self.export("two")
        for name in ("index.html", "summary.json", "manifest.json"):
            data = (first / name).read_bytes()
            self.assertEqual(data, (second / name).read_bytes())
            self.assertNotIn(str(self.root).encode(), data)

    def test_stored_payload_text_not_wrapper_is_embedded(self):
        destination = self.export()
        _, bundle, _ = embedded(destination / "index.html")
        db = sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True)
        try:
            original = db.execute("SELECT payload FROM runs WHERE id=?", (self.run_id,)).fetchone()[0]
        finally:
            db.close()
        run = bundle["runs"][0]
        self.assertEqual(run["raw_payload"], original)
        self.assertEqual(run["payload_sha256"], hashlib.sha256(original.encode()).hexdigest())
        self.assertNotIn("run_id", json.loads(original))

    def test_view_never_calls_financial_execution(self):
        before = self.database.read_bytes()
        with patch("crypto_reconciliation_lab.store.Store", side_effect=AssertionError("Store constructed")), \
             patch("crypto_reconciliation_lab.engine.reconcile", side_effect=AssertionError("reconcile called")), \
             patch("crypto_reconciliation_lab.migrations.migrate_database", side_effect=AssertionError("migration called")):
            self.export()
        self.assertEqual(before, self.database.read_bytes())

    def test_existing_directory_and_file_are_never_overwritten(self):
        destination = self.root / "existing"
        destination.mkdir()
        (destination / "keep").write_text("untouched")
        with self.assertRaises(FileExistsError):
            exporter.export_selection(self.selection, destination)
        self.assertEqual((destination / "keep").read_text(), "untouched")
        file = self.root / "file"
        file.write_text("untouched")
        with self.assertRaises(FileExistsError):
            exporter.export_selection(self.selection, file)
        self.assertEqual(file.read_text(), "untouched")

    def test_raced_empty_target_is_not_replaced(self):
        destination = self.root / "raced"
        with self.assertRaises(FileExistsError):
            with new_output_directory(destination) as staging:
                (staging / "index.html").write_text("should remain unpublished")
                destination.mkdir()
        self.assertEqual(list(destination.iterdir()), [])
        self.assertFalse(list(self.root.glob(".review-staging-*")))

    def test_broken_symlink_target_is_not_replaced(self):
        destination = self.root / "link"
        destination.symlink_to(self.root / "absent")
        with self.assertRaises(FileExistsError):
            self.export("link")
        self.assertTrue(destination.is_symlink())

    def test_selected_invalid_run_leaves_no_html_or_completed_output(self):
        self.selection = create_selection(self.root, [("bad", self.database, ["0" * 64])])
        before = self.database.read_bytes()
        with self.assertRaisesRegex(ValueError, "0{64}"):
            self.export()
        self.assertFalse((self.root / "bundle").exists())
        self.assertFalse(list(self.root.glob(".review-staging-*")))
        self.assertEqual(before, self.database.read_bytes())

    def test_html_size_failure_removes_only_owned_staging(self):
        before = self.database.read_bytes()
        with patch.object(exporter, "MAX_HTML_BYTES", 256):
            with self.assertRaisesRegex(ValueError, "HTML_LIMIT_EXCEEDED"):
                self.export()
        self.assertFalse((self.root / "bundle").exists())
        self.assertFalse(list(self.root.glob(".review-staging-*")))
        self.assertEqual(before, self.database.read_bytes())

    def test_asset_failure_leaves_no_completed_output(self):
        with patch.object(exporter, "load_assets", side_effect=OSError("owned asset read failed")):
            with self.assertRaises(OSError):
                self.export()
        self.assertFalse((self.root / "bundle").exists())

    def test_script_boundary_and_raw_large_integer_are_lossless(self):
        database, run_id = create_source(self.root / "edge", edge=True)
        self.selection = create_selection(self.root, [("edge", database, [run_id]), ("copy", database, [run_id])])
        html, bundle, raw_data = embedded(self.export() / "index.html")
        self.assertNotIn("<", raw_data)
        self.assertNotIn(">", raw_data)
        self.assertNotIn("&", raw_data)
        self.assertIn("\\u003c", raw_data)
        self.assertEqual(len(bundle["runs"]), 2)
        self.assertEqual([r["source_alias"] for r in bundle["runs"]], ["edge", "copy"])
        self.assertEqual({r["run_id"] for r in bundle["runs"]}, {run_id})
        self.assertIn(str(BIG_INTEGER), bundle["runs"][0]["raw_payload"])
        self.assertIn(LONG_EXPECTED, raw_data)
        values = [f["reported"] for f in bundle["runs"][0]["findings"]]
        self.assertIn(None, values)
        self.assertIn('"difference":"0"', raw_data)

    def test_csp_hashes_match_actual_inline_assets(self):
        html, _, _ = embedded(self.export() / "index.html")
        for name in ("app.js", "style.css"):
            raw = exporter.load_assets()[name]
            expected = base64.b64encode(hashlib.sha256(raw).digest()).decode("ascii")
            self.assertIn("'sha256-" + expected + "'", html)
            self.assertIn(raw.decode("utf-8"), html)
        self.assertIn("connect-src 'none'", html)

    def test_export_and_adapter_have_no_financial_entrypoint_calls(self):
        folder = Path(exporter.__file__).parent
        forbidden = {"Store", "reconcile", "ingest", "save_run", "migrate_database"}
        for name in ("export.py", "adapter.py", "validation.py", "viewmodel.py"):
            tree = ast.parse((folder / name).read_text())
            calls = {node.func.id if isinstance(node.func, ast.Name) else node.func.attr
                     for node in ast.walk(tree) if isinstance(node, ast.Call)
                     and isinstance(node.func, (ast.Name, ast.Attribute))}
            self.assertFalse(calls & forbidden, name)


if __name__ == "__main__":
    unittest.main()
