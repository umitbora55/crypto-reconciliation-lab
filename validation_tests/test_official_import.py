"""Synthetic-only finite controls for the deterministic offline import path."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.validation.import_official_files import import_files


class OfficialImportTests(unittest.TestCase):
    def fixture(self, root):
        body = b"SYNTHETIC test document, not a captured official page.\n"
        (root / "source.txt").write_bytes(body)
        value = {"format": "official-file-import-v1", "capture_method": "USER_DOWNLOADED_OFFICIAL_BYTES", "files": [
            {"source_id": "synthetic-test", "file_name": "source.txt", "source_url": "https://www.sec.gov/synthetic-test-fixture",
             "downloaded_at_utc": "2026-11-16T12:00:00Z", "publication_vintage": "UNKNOWN", "kind": "official_document",
             "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "usage_terms": "SYNTHETIC_TEST_ONLY"}]}
        path = root / "manifest.json"
        path.write_text(json.dumps(value))
        return path, value

    def test_offline_copy_matches_bytes_without_origin_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); manifest, _ = self.fixture(root)
            with patch.dict(os.environ, {"NO_NETWORK": "1"}), patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
                result = import_files(manifest, root, root / "output")
            self.assertEqual(result["status"], "INTEGRITY_VERIFIED_ORIGIN_USER_ATTESTED")
            self.assertEqual(result["real_financial_equalities_verified"], 0)
            self.assertEqual((root / "output/raw/synthetic-test-source.txt").read_bytes(), (root / "source.txt").read_bytes())

    def test_no_overwrite_existing_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); manifest, _ = self.fixture(root)
            target = root / "output"; target.mkdir(); (target / "RED").write_text("preserve")
            with self.assertRaises(FileExistsError): import_files(manifest, root, target)
            self.assertEqual((target / "RED").read_text(), "preserve")

    def test_empty_and_duplicate_inventory_rejected(self):
        for mode in ("empty", "duplicate"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); manifest, value = self.fixture(root)
                value["files"] = [] if mode == "empty" else value["files"] * 2
                manifest.write_text(json.dumps(value))
                with self.assertRaises(ValueError): import_files(manifest, root, root / "output")
                self.assertFalse((root / "output").exists())

    def test_tampered_hash_and_size_rejected(self):
        for field, value in (("sha256", "0" * 64), ("bytes", 1)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); manifest, data = self.fixture(root)
                data["files"][0][field] = value; manifest.write_text(json.dumps(data))
                with self.assertRaises(ValueError): import_files(manifest, root, root / "output")

    def test_path_escape_and_symlink_rejected(self):
        for mode in ("escape", "symlink"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); manifest, value = self.fixture(root)
                if mode == "escape": value["files"][0]["file_name"] = "../source.txt"
                else:
                    (root / "alias.txt").symlink_to(root / "source.txt")
                    value["files"][0]["file_name"] = "alias.txt"
                manifest.write_text(json.dumps(value))
                with self.assertRaises(ValueError): import_files(manifest, root, root / "output")

    def test_url_tls_host_and_userinfo_rejected(self):
        for url in ("http://www.sec.gov/a", "https://example.invalid/a", "https://user:secret@www.sec.gov/a"):
            with self.subTest(url=url), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); manifest, value = self.fixture(root)
                value["files"][0]["source_url"] = url; manifest.write_text(json.dumps(value))
                with self.assertRaises(ValueError): import_files(manifest, root, root / "output")

    def test_naive_or_non_utc_timestamp_rejected(self):
        for timestamp in ("2026-11-16T12:00:00", "2026-11-16T12:00:00+03:00"):
            with self.subTest(timestamp=timestamp), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); manifest, value = self.fixture(root)
                value["files"][0]["downloaded_at_utc"] = timestamp; manifest.write_text(json.dumps(value))
                with self.assertRaises(ValueError): import_files(manifest, root, root / "output")

    def test_duplicate_json_key_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); manifest, _ = self.fixture(root)
            manifest.write_text('{"format":"official-file-import-v1","format":"other","files":[]}')
            with self.assertRaises(ValueError): import_files(manifest, root, root / "output")


if __name__ == "__main__":
    unittest.main()
