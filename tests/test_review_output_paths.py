"""S4-F1: output paths cannot occupy a selected SQLite source or sidecar.

All fixtures are owned temporary sources. Preservation proofs use independent
file/SQLite inspection, not the exporter's own preservation assertions.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from crypto_reconciliation_lab.review import adapter, export as exporter
from crypto_reconciliation_lab.review.validation import ReviewError
from review_fixtures import create_source, create_selection

SIDECARS = ("-wal", "-shm", "-journal")
AUDIT_RECORDS = []


def path_state(path):
    """lstat includes broken links; do not follow a sidecar or target symlink."""
    path = Path(path)
    try:
        info = path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return {"exists": False}
    kind = ("symlink" if stat.S_ISLNK(info.st_mode) else
            "file" if stat.S_ISREG(info.st_mode) else
            "directory" if stat.S_ISDIR(info.st_mode) else "special")
    result = {"exists": True, "kind": kind, "mode": info.st_mode,
              "device": info.st_dev, "inode": info.st_ino,
              "bytes": info.st_size, "mtime_ns": info.st_mtime_ns}
    if kind == "symlink":
        result["link_text"] = os.readlink(path)
    elif kind == "file":
        result["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def source_state(path):
    """Inspect run IDs/payload text and schema only on an owned byte copy."""
    path = Path(path)
    raw = path.read_bytes()
    with tempfile.TemporaryDirectory(prefix="s4-f1-proof-") as temporary:
        copied = Path(temporary) / "inspection.sqlite3"
        copied.write_bytes(raw)
        db = sqlite3.connect(copied.as_uri() + "?mode=ro", uri=True)
        try:
            schema = [list(row) for row in db.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")]
            runs = [list(row) for row in db.execute(
                "SELECT id,balance_at,knowledge_at,payload FROM runs ORDER BY id")]
            version = db.execute("PRAGMA user_version").fetchone()[0]
        finally:
            db.close()
    return {"database": path_state(path), "sha256": hashlib.sha256(raw).hexdigest(),
            "user_version": version, "schema": schema, "runs": runs,
            "sidecars": {suffix: path_state(Path(str(path) + suffix)) for suffix in SIDECARS}}


def tree_state(root):
    """No directory metadata: reads may affect atime; entry identity is retained."""
    result = {}
    for folder, directories, files in os.walk(root, followlinks=False):
        for name in sorted(directories + files):
            path = Path(folder) / name
            entry = path_state(path)
            if entry.get("kind") == "directory":
                entry = {key: entry[key] for key in ("exists", "kind", "mode", "device", "inode")}
            result[str(path.relative_to(root))] = entry
    return result


@contextmanager
def working_directory(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class ReviewOutputPathTests(unittest.TestCase):
    @contextmanager
    def fixture(self, second=False):
        with tempfile.TemporaryDirectory(prefix="s4-f1-test-") as temporary:
            root = Path(temporary).resolve()
            database, run_id = create_source(root / "source")
            sources = [("source", database, [run_id])]
            if second:
                first, first_id = create_source(root / "first")
                sources.insert(0, ("first", first, [first_id]))
            selection = create_selection(root, sources)
            yield root, database, selection, sources

    def attempt(self, label, root, selection, sources, destination,
                expected="conflict", cli=False):
        before = {alias: source_state(database) for alias, database, _ in sources}
        before_tree = tree_state(root)
        target_before = path_state(destination)
        outcome, write_calls = {}, None
        manifest = None
        if cli:
            package_root = Path(exporter.__file__).resolve().parents[2]
            command = [sys.executable, "-B", "-s", "-m", "crypto_reconciliation_lab",
                       "review-export", "--selection", str(selection), "--output", str(destination)]
            environment = dict(os.environ)
            environment.pop("PYTHONPATH", None)
            origin = subprocess.run([sys.executable, "-B", "-s", "-c",
                "import json,sys,crypto_reconciliation_lab as p; "
                "print(json.dumps({'interpreter':sys.executable,'import':p.__file__,'version':p.__version__}))"],
                cwd=package_root, env=environment, text=True, capture_output=True, check=False)
            completed = subprocess.run(command, cwd=package_root, env=environment,
                text=True, capture_output=True, check=False)
            outcome = {"argv": command, "cwd": str(package_root),
                       "returncode": completed.returncode, "stdout": completed.stdout,
                       "stderr": completed.stderr, "provenance_exit": origin.returncode,
                       "provenance": json.loads(origin.stdout) if origin.returncode == 0 else origin.stderr}
        else:
            original_mkdir, original_mkdtemp = Path.mkdir, tempfile.mkdtemp
            with patch.object(Path, "mkdir", autospec=True, side_effect=original_mkdir) as mkdir, \
                 patch.object(tempfile, "mkdtemp", wraps=original_mkdtemp) as mkdtemp:
                try:
                    manifest = exporter.export_selection(selection, destination)
                    outcome = {"status": manifest.get("status")}
                except Exception as exc:
                    outcome = {"exception": type(exc).__name__, "code": getattr(exc, "code", None),
                               "message": str(exc)}
                write_calls = {"mkdir": mkdir.call_count, "mkdtemp": mkdtemp.call_count}
        after = {alias: source_state(database) for alias, database, _ in sources}
        after_tree = tree_state(root)
        target_after = path_state(destination)
        record = {"test": self.id(), "case": label, "destination": str(destination),
                  "expected": expected, "before": before, "after": after,
                  "tree_before": before_tree, "tree_after": after_tree,
                  "target_before": target_before, "target_after": target_after,
                  "outcome": outcome, "write_calls": write_calls,
                  "sources_equal": before == after,
                  "new_staging": sorted(name for name in set(after_tree) - set(before_tree)
                                        if ".review-staging-" in Path(name).parts[-1])}
        AUDIT_RECORDS.append(record)
        violations = []
        if before != after:
            violations.append("source byte/run/schema/sidecar inventory changed")
        if record["new_staging"]:
            violations.append("new staging residue")
        if expected != "complete":
            if before_tree != after_tree:
                violations.append("rejected operation changed owned source/target tree")
            if target_before != target_after:
                violations.append("rejected target lstat/content changed")
            if not cli and write_calls != {"mkdir": 0, "mkdtemp": 0}:
                violations.append("rejection occurred after a mkdir/staging call")
            wanted = "OUTPUT_EXISTS" if expected == "exists" else "OUTPUT_SOURCE_CONFLICT"
            if cli:
                if outcome["returncode"] != 2 or wanted not in outcome["stderr"] + outcome["stdout"]:
                    violations.append("CLI must return 2 with " + wanted)
                if "COMPLETE" in outcome["stdout"]:
                    violations.append("CLI reported COMPLETE for conflicting output")
                if outcome["provenance_exit"] != 0 or Path(outcome["provenance"].get("import", "")).resolve() != package_root / "crypto_reconciliation_lab" / "__init__.py":
                    violations.append("CLI did not import the tested package")
            elif expected == "exists":
                if outcome.get("exception") != "FileExistsError" or wanted not in outcome.get("message", ""):
                    violations.append("existing target must preserve FileExistsError/OUTPUT_EXISTS")
            elif outcome.get("exception") != "ReviewError" or outcome.get("code") != wanted:
                violations.append("missing ReviewError/OUTPUT_SOURCE_CONFLICT")
        else:
            if outcome.get("status") != "COMPLETE":
                violations.append("normal export did not complete")
            else:
                if {path.name for path in Path(destination).resolve().iterdir()} != {"index.html", "summary.json", "manifest.json"}:
                    violations.append("normal export did not publish exactly three files")
                expected_aliases = {alias for alias, _, _ in sources}
                if {item["alias"] for item in manifest["sources"]} != expected_aliases:
                    violations.append("manifest source set differs from selection")
                for proof in manifest["sources"]:
                    independently_observed = after[proof["alias"]]
                    if (proof["unchanged"] is not True or proof["before"] != proof["after"]
                            or proof["after"]["files"]["database"]["sha256"] != independently_observed["sha256"]
                            or proof["after"]["schema"]["user_version"] != independently_observed["user_version"]
                            or proof["after"]["run_inventory"]["count"] != len(independently_observed["runs"])
                            or proof["after"]["files"]["sidecars"] != dict.fromkeys(SIDECARS)):
                        violations.append("manifest does not describe the independent source state")
                reread = adapter.read_selected_sources(selection)
                if {(run.source_alias, run.run_id, run.payload_text) for run in reread.runs} != {
                        (alias, row[0], row[3]) for alias, observed in after.items() for row in observed["runs"]}:
                    violations.append("source reread differs from independent saved runs")
                after_reread = {alias: source_state(database) for alias, database, _ in sources}
                record["after_reread"] = after_reread
                if after_reread != before:
                    violations.append("successful export/reread changed sources")
                record["manifest_sources"] = manifest["sources"]
        record["violations"] = violations
        self.assertEqual(violations, [], f"{label}: {outcome}")

    def test_sidecar_direct_and_descendant_rejected_before_first_write(self):
        for suffix in SIDECARS:
            for descendant in (False, True):
                with self.subTest(suffix=suffix, descendant=descendant), self.fixture() as (root, database, selection, sources):
                    destination = Path(str(database) + suffix)
                    if descendant:
                        destination /= "review"
                    self.attempt(f"sidecar:{suffix}:{descendant}", root, selection, sources, destination)

    def test_second_selected_source_is_protected(self):
        for suffix in SIDECARS:
            for descendant in (False, True):
                with self.subTest(suffix=suffix, descendant=descendant), self.fixture(second=True) as (root, database, selection, sources):
                    destination = Path(str(database) + suffix)
                    if descendant:
                        destination /= "review"
                    self.attempt(f"second:{suffix}:{descendant}", root, selection, sources, destination)

    def test_relative_selection_and_output_resolve_same_physical_source(self):
        for suffix in SIDECARS:
            with self.subTest(suffix=suffix), self.fixture() as (root, database, selection, sources):
                data = json.loads(selection.read_text())
                data["sources"][0]["database"] = "source/../source/source.sqlite3"
                selection.write_text(json.dumps(data))
                with working_directory(root):
                    destination = Path("source") / (database.name + suffix) / "review"
                    self.attempt("relative:" + suffix, root, Path("selection.json"), sources, destination)

    def test_existing_symlink_parent_resolves_before_writing(self):
        for suffix in SIDECARS:
            for descendant in (False, True):
                with self.subTest(suffix=suffix, descendant=descendant), self.fixture() as (root, database, selection, sources):
                    linked = root / "linked-source-parent"
                    linked.symlink_to(database.parent, target_is_directory=True)
                    destination = linked / (database.name + suffix)
                    if descendant:
                        destination /= "review"
                    self.attempt(f"parent-symlink:{suffix}:{descendant}", root, selection, sources, destination)

    def test_main_database_itself_and_descendant_are_protected(self):
        for descendant in (False, True):
            with self.subTest(descendant=descendant), self.fixture() as (root, database, selection, sources):
                destination = database / "review" if descendant else database
                self.attempt(f"main:{descendant}", root, selection, sources, destination,
                             expected="conflict" if descendant else "exists")

    def test_real_cli_rejects_sidecars_and_nested_targets_without_complete(self):
        for suffix in SIDECARS:
            for descendant in (False, True):
                with self.subTest(suffix=suffix, descendant=descendant), self.fixture(second=True) as (root, database, selection, sources):
                    destination = Path(str(database) + suffix)
                    if descendant:
                        destination /= "review"
                    self.attempt(f"cli:{suffix}:{descendant}", root, selection, sources, destination, cli=True)

    def test_existing_file_directory_and_dangling_symlink_stay_untouched(self):
        for suffix in SIDECARS + ("-ordinary",):
            for kind in ("file", "directory", "symlink"):
                with self.subTest(suffix=suffix, kind=kind), self.fixture() as (root, database, selection, sources):
                    destination = Path(str(database) + suffix)
                    if kind == "file":
                        destination.write_bytes(b"user-owned bytes\x00\xff")
                    elif kind == "directory":
                        destination.mkdir()
                        (destination / "keep.txt").write_text("user-owned contents")
                    else:
                        destination.symlink_to(root / "missing-user-target")
                    self.attempt(f"existing:{suffix}:{kind}", root, selection, sources, destination, expected="exists")

    def test_normal_export_manifest_and_source_reread(self):
        with self.fixture(second=True) as (root, database, selection, sources):
            self.attempt("normal", root, selection, sources, root / "normal" / "bundle", expected="complete")

    def test_text_prefix_siblings_remain_valid(self):
        for suffix in SIDECARS:
            with self.subTest(suffix=suffix), self.fixture() as (root, database, selection, sources):
                self.attempt("prefix:" + suffix, root, selection, sources,
                             Path(str(database) + suffix + "-report"), expected="complete")

    def test_dotdot_normal_target_does_not_materialize_sidecar_component(self):
        for suffix in SIDECARS:
            with self.subTest(suffix=suffix), self.fixture() as (root, database, selection, sources):
                destination = Path(str(database) + suffix) / ".." / "normal"
                self.attempt("dotdot:" + suffix, root, selection, sources, destination, expected="complete")

    def test_selection_is_parsed_once_and_same_object_reaches_reader(self):
        with self.fixture() as (root, database, selection, sources):
            parsed = []
            original_parse = adapter.read_selection
            original_read = adapter.read_selected_sources
            def parse(path):
                value = original_parse(path)
                parsed.append(value)
                return value
            with patch.object(adapter, "read_selection", side_effect=parse), \
                 patch.object(exporter, "read_selection", side_effect=parse, create=True), \
                 patch.object(exporter, "read_selected_sources", wraps=original_read) as read:
                self.attempt("single-selection", root, selection, sources, root / "bundle", expected="complete")
            # attempt's independent post-export reread parses once separately.
            self.assertEqual(len(parsed), 2)
            self.assertEqual(read.call_count, 1)
            self.assertIs(read.call_args.args[0], parsed[0])
            self.assertIsInstance(read.call_args.args[0], adapter.Selection)


if __name__ == "__main__":
    unittest.main()
