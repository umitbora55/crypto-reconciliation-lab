"""Adversarial controls for source identity and compact review ZIP acceptance."""
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SOURCE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("gate2_package_under_test", SOURCE / "scripts/validation/package_gate2.py")
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)


class Gate2PackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gate2-package-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def git(self, repo, *args):
        return subprocess.check_output(["git", "-c", "user.name=ArchiveFixture",
            "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", *args],
            cwd=repo, stderr=subprocess.DEVNULL)

    def repository(self):
        repo = self.root / "source"
        repo.mkdir()
        self.git(repo, "init", "-q")
        (repo / "README.md").write_bytes(b"committed source\n")
        self.git(repo, "add", "README.md")
        self.git(repo, "commit", "-qm", "synthetic fixture")
        return repo

    def evidence(self):
        root = self.root / "evidence"
        root.mkdir()
        (root / "result.json").write_bytes(b'{"status":"synthetic fixture"}\n')
        return root

    def archive(self, payload=b"x", **changes):
        archive = self.root / (changes.pop("name", "candidate") + ".zip")
        row = {"path": "evidence/record.txt", "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        row.update(changes.pop("row", {}))
        manifest = {"format": "validation-gate2-review-v1", "repository_commit": "1" * 40,
                    "members": [row]}
        manifest.update(changes.pop("manifest", {}))
        with zipfile.ZipFile(archive, "w") as zipped:
            info = zipfile.ZipInfo(row["path"])
            if changes.pop("symlink", False):
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zipped.writestr(info, changes.pop("actual_payload", payload))
            for name, data in changes.pop("extras", []):
                zipped.writestr(name, data)
            zipped.writestr("archive-manifest.json", json.dumps(manifest))
        return archive

    def test_public_raw_allowlist_and_secret_paths_are_explicit(self):
        evidence = self.evidence()
        files = ["public-data/data-01/raw/dts-operating_cash_balance-2024-01.body",
                 "public-data/data-01/raw/sec-ftd.zip", "public-data/data-01/raw/treasury-about.body",
                 "public-data/data-01/raw/dts-terms.html", ".env", ".aws/credentials"]
        for name in files:
            path = evidence / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic nonsecret fixture")
        included, omitted = package.inventory(evidence)
        self.assertEqual({row["path"] for row in included}, {"result.json", files[0]})
        self.assertEqual({row["path"] for row in omitted}, set(files[1:5]) | {".aws"})

    def test_untracked_source_blocks_clean_revision_claim(self):
        repo = self.repository()
        (repo / "uncommitted-research.py").write_text("uncommitted = True\n")
        with patch.object(package, "ROOT", repo), self.assertRaises((ValueError, subprocess.CalledProcessError)):
            package.package(self.evidence(), self.root / "sealed")

    def test_source_mutation_after_initial_git_check_cannot_seal(self):
        repo = self.repository()
        original_inventory = package.inventory
        def inventory(root):
            rows = original_inventory(root)
            (repo / "README.md").write_bytes(b"uncommitted changed bytes\n")
            return rows
        with patch.object(package, "ROOT", repo), patch.object(package, "inventory", side_effect=inventory), \
             self.assertRaises((ValueError, subprocess.CalledProcessError)):
            package.package(self.evidence(), self.root / "sealed")
        self.assertFalse((self.root / "sealed/archive-verification.json").exists())

    def test_evidence_mutation_after_inventory_cannot_publish_final_archive(self):
        repo = self.repository()
        original_inventory = package.inventory
        def inventory(root):
            rows = original_inventory(root)
            (root / "result.json").write_bytes(b"changed after inventory\n")
            return rows
        with patch.object(package, "ROOT", repo), patch.object(package, "inventory", side_effect=inventory), \
             self.assertRaisesRegex(ValueError, "evidence changed"):
            package.package(self.evidence(), self.root / "sealed")
        self.assertFalse((self.root / "sealed/crypto-reconciliation-validation-gate2.zip").exists())
        self.assertFalse((self.root / "sealed/archive-verification.json").exists())

    def test_clean_archive_has_exact_committed_source_and_evidence(self):
        repo = self.repository()
        with patch.object(package, "ROOT", repo):
            result = package.package(self.evidence(), self.root / "sealed")
        self.assertEqual(result["status"], "PASS")
        with zipfile.ZipFile(result["archive"]) as zipped:
            self.assertEqual(zipped.read("source/README.md"), b"committed source\n")
            self.assertEqual(set(zipped.namelist()), {"source/README.md", "evidence/result.json",
                                                     "evidence-manifest.json", "archive-manifest.json"})

    def test_boolean_size_cannot_pass_for_one_byte_member(self):
        with self.assertRaises(ValueError):
            package.verify(self.archive(row={"bytes": True}))

    def test_noncanonical_and_cross_platform_paths_are_rejected(self):
        for name in ("a//b", "a/./b", "C:/outside", "../outside", "/absolute", "."):
            with self.subTest(name=name), self.assertRaises(ValueError):
                package.safe_name(name)

    def test_symlink_zip_member_is_not_a_regular_evidence_file(self):
        with self.assertRaises(ValueError):
            package.verify(self.archive(symlink=True))

    def test_mutation_extra_and_empty_inventories_are_rejected(self):
        for kwargs in ({"name": "mutated", "actual_payload": b"y"},
                       {"name": "extra", "extras": [("unlisted", b"z")]},
                       {"name": "empty", "manifest": {"members": []}}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                package.verify(self.archive(**kwargs))


if __name__ == "__main__":
    unittest.main()
