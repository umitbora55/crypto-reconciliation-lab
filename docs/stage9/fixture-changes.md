# Stage 9 metadata fixture changes

The 0.6.1 release retains its original fixed contract and 400 test IDs. Stage 9 explicitly authorizes narrow version/schema fixture updates; no financial assertion or test method is removed. The new fixed 0.7.0 contract binds each original/current file hash and each reversible single-line replacement. Ordinary verification reverses only these declared replacements and requires the exact prior file bytes.

## tests/test_corrections.py

The explicit current migration target becomes schema 4; the test still asserts preserved legacy rows, backup parity and foreign keys.

Original SHA-256: `0022e82ce75742fde400f9348270b2e63f14ba7cfd09ae6496c3981e7891a572`. Current SHA-256: `d233406aaebe9aa699de29c3ac86149d3c1967570eb3a39790296a127f70cd40`.

```diff
diff --git a/tests/test_corrections.py b/tests/test_corrections.py
index d853f20..56bb423 100644
--- a/tests/test_corrections.py
+++ b/tests/test_corrections.py
@@ -458,7 +458,7 @@ class MigrationTests(unittest.TestCase):
         self.assertEqual(result['before_digest'], result['after_digest'])
         db = sqlite3.connect(self.path)
         self.assert_legacy(db)
-        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 3)
+        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 4)
         self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
         db.close()
         store = Store(self.path)
```

## tests/test_receipt_index.py

The current schema and migration-history fixtures include 4. The deliberately unsupported future schema moves from 4 to 5; rejection and no-repair assertions stay unchanged.

Original SHA-256: `9be74bbf1b65cef7c9a7b986177fe9d2173d95a6bbe11f00e8c0bf44aa01c12d`. Current SHA-256: `9a3be65e59e5c53f9799de137cf5d07bfe7478d52776fba6420ab56eebc0e585`.

```diff
diff --git a/tests/test_receipt_index.py b/tests/test_receipt_index.py
index b41465d..6e06669 100644
--- a/tests/test_receipt_index.py
+++ b/tests/test_receipt_index.py
@@ -54,7 +54,7 @@ class ReceiptIndexTests(unittest.TestCase):
     def test_fresh_index_is_exactly_one_nonunique_binary_ascending_column(self):
         store = self.fresh()
         validate_current(store.db)
-        self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 3)
+        self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 4)
         listed = {r[1]: r for r in store.db.execute('PRAGMA index_list(receipts)')}
         self.assertEqual(set(listed), {'receipts_time', INDEX_NAME})
         self.assertEqual(tuple(listed[INDEX_NAME][2:]), (0, 'c', 0))
@@ -103,7 +103,7 @@ class ReceiptIndexTests(unittest.TestCase):
                 migrate_connection(db, fail)
             self.assertEqual(application_snapshot(db), before, point)
         self.assertTrue(migrate_connection(db))
-        self.assertEqual(db.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall(), [(2,), (3,)])
+        self.assertEqual(db.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall(), [(2,), (3,), (4,)])
         self.assertEqual(db.execute('SELECT description FROM schema_migrations WHERE version=2').fetchone()[0],
                          'Add immutable correction groups/effects; retain all Stage 1 columns')
         assert_preserved(db, before)
@@ -157,7 +157,7 @@ class ReceiptIndexTests(unittest.TestCase):
                 path = self.path / (case + '.sqlite3')
                 store = Store(path, self.config)
                 if case == 'future':
-                    store.db.execute('PRAGMA user_version=4')
+                    store.db.execute('PRAGMA user_version=5')
                 else:
                     store.db.execute('DROP INDEX receipts_hash_lookup')
                     if case == 'wrong_index':
```

## tests/test_release_test_scope.py

The synthetic successful-verification fixture names the current fixed 0.7.0 scope, while its omitted/substituted/duplicate identity and no-expensive-setup assertions remain unchanged.

Original SHA-256: `c896f58e9cf72156c7de1c89ee63431b0b1cdcd1d8845e508cdac8937760bae7`. Current SHA-256: `66ad85f8bfbee58be4efa64d88ce9e1ae259ac004896a2a0b58ef2174360196b`.

```diff
diff --git a/tests/test_release_test_scope.py b/tests/test_release_test_scope.py
index 974b29f..17a19ce 100644
--- a/tests/test_release_test_scope.py
+++ b/tests/test_release_test_scope.py
@@ -16,7 +16,7 @@ import zipfile
 
 ROOT = Path(__file__).resolve().parents[1]
 BASELINE_PATH = 'contracts/release-tests-baseline-0.6.0.json'
-CONTRACT_PATH = 'contracts/release-test-scope-0.6.1.json'
+CONTRACT_PATH = 'contracts/release-test-scope-0.7.0.json'
 BASELINE = json.loads((ROOT / BASELINE_PATH).read_text())
 SPEC = importlib.util.spec_from_file_location('scope_release_verifier', ROOT / 'scripts/verify_release.py')
 verify = importlib.util.module_from_spec(SPEC)
@@ -35,7 +35,7 @@ def successful_result():
     identities = list(declared_ids())
     current = ROOT / CONTRACT_PATH
     identity = ({'path':CONTRACT_PATH, 'bytes':current.stat().st_size,
-                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.6.1'}
+                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.7.0'}
                 if current.exists() else {})
     return dict(status='PASS', discovered=len(identities), executed=len(identities),
                 discovered_ids=identities, executed_ids=list(identities), scope_identity=identity,
```

The historical 0.6.1 single-expression packaging fixture exception remains in its original contract; it is not widened or reapplied here. `tests/test_review_adapter.py` retains schema 0/2/3 historical fixtures unchanged; schema 4 coverage is added in a new test module. New admission, migration, recovery and release-gate tests are declared as additions, never replacements for the old roster.
